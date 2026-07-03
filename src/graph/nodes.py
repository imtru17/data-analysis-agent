"""LangGraph nodes for the analysis pipeline.

Privacy invariant: the three LLM-calling nodes (`plan`, `generate_code`,
`answer`) build their user content ONLY via ``analysis.privacy.render_context``
— they never touch a DataFrame. The full DataFrame is loaded from the store
inside ``execute_locally`` and never placed in state.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import SecretStr

from analysis import db_source, privacy, store
from analysis.executor import run_code, run_code_raw, run_combine, summarize_result
from config.settings import get_settings
from graph.state import AgentState
from llm.client import LLMClient
from observability.llm_log import estimate_cost, timed_llm_call

_PROMPTS = Path(__file__).parent.parent / "prompts"

# Captures the (optional) language tag and the body of a fenced code block
# separately so a ```sql fence never leaks its language tag into the code text.
_CODE_FENCE = re.compile(r"```[ \t]*(\w+)?[ \t]*\n(.*?)```", re.DOTALL)

# Trivial fast-path detection: single-column count/sum/mean/min/max or row count,
# with no join/group/compare phrasing.
_TRIVIAL_PATTERNS = re.compile(
    r"\b(how many rows|number of rows|row count|count of rows|total count|"
    r"how many records)\b",
    re.IGNORECASE,
)
_NONTRIVIAL_PATTERNS = re.compile(
    r"\b(by|per|group|grouped|join|compare|versus|vs\.?|correlat|trend|"
    r"breakdown|across|between|each)\b",
    re.IGNORECASE,
)


def _load_prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace(state: AgentState, step: str, status: str, detail: str) -> list:
    trace = list(state.get("step_trace", []))
    trace.append({"step": step, "status": status, "detail": detail, "ts": _now_iso()})
    return trace


def _accumulate_usage(state: AgentState, usage: dict) -> tuple[dict, float]:
    tokens = dict(state.get("tokens", {"prompt": 0, "completion": 0}))
    tokens["prompt"] = tokens.get("prompt", 0) + usage.get("prompt_tokens", 0)
    tokens["completion"] = tokens.get("completion", 0) + usage.get("completion_tokens", 0)
    cost = state.get("cost_usd", 0.0) + estimate_cost(
        usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    )
    return tokens, round(cost, 6)


def is_trivial_question(question: str, dataset_meta: dict) -> bool:
    """Deterministic pre-check for the fast path (skip `plan`)."""
    if _NONTRIVIAL_PATTERNS.search(question):
        return False
    return bool(_TRIVIAL_PATTERNS.search(question))


def _extract_code(text: str) -> str:
    match = _CODE_FENCE.search(text)
    if match:
        return match.group(2).strip()
    # No fence — best effort: assume the whole text is code if it mentions result
    return text.strip()


def _extract_json(text: str) -> object | None:
    text = text.strip()
    fence = _CODE_FENCE.search(text)
    if fence:
        text = fence.group(2).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _safe_var(source_id: str) -> str:
    return "src_" + re.sub(r"[^0-9a-zA-Z_]", "_", source_id)


def _source_to_dataset_meta(src: dict) -> dict:
    return {
        "dataset_id": src.get("source_id", ""),
        "filename": src.get("name", ""),
        "row_count": src.get("row_count", 0),
        "columns": src.get("columns", []),
        "sample_rows": src.get("sample_rows", []),
    }


def _connection_dsn(connection_id: str) -> SecretStr:
    from db.models import ConnectionRow
    from db.session import create_db_session

    with create_db_session() as session:
        row = session.get(ConnectionRow, connection_id)
        if row is None:
            raise db_source.DbSourceError(f"Unknown connection: {connection_id}")
        return SecretStr(row.dsn)


def select_sources(state: AgentState) -> AgentState:
    """Phase 3 entry node. With 0/1 sources in scope this is a near-noop (no
    LLM call) — it just normalises ``selected_sources``/``dataset_id`` and
    (for a single FILE source) fills ``dataset_meta`` so every downstream node
    behaves exactly like the Phase-1/2 single-source path. With >1 sources it
    makes one real LLM call (schema+samples ONLY) to pick + plan a join."""
    try:
        sources = state.get("sources") or []

        if len(sources) <= 1:
            if sources:
                src = sources[0]
                sid = str(src.get("source_id", ""))
                dataset_meta = (
                    _source_to_dataset_meta(src) if src.get("kind", "file") == "file" else None
                )
            else:
                sid = state.get("dataset_id", "")
                dataset_meta = state.get("dataset_meta")
            return {
                **state,
                "dataset_id": sid or state.get("dataset_id", ""),
                "selected_sources": [sid] if sid else [],
                "is_multi_source": False,
                "source_plan": None,
                "dataset_meta": dataset_meta,
                "step_trace": _trace(state, "select_sources", "done", "Single source in scope"),
            }

        ctx = privacy.build_context(
            None,
            question=state.get("question", ""),
            sources=sources,
            annotations=state.get("annotations"),
            conversation=state.get("conversation"),
        )
        system = _load_prompt("select_sources.md")
        with timed_llm_call("select_sources", state.get("run_id", "")) as usage:
            text, u = LLMClient().call_with_usage(privacy.render_context(ctx), system=system)
            usage.update(u)
        tokens, cost = _accumulate_usage(state, u)

        parsed = _extract_json(text) or {}
        known_ids = {str(s.get("source_id", "")) for s in sources}
        selected = [sid for sid in (parsed.get("selected") or []) if sid in known_ids]
        if not selected:
            selected = [str(s.get("source_id", "")) for s in sources]
        multi = bool(parsed.get("multi", len(selected) > 1)) and len(selected) > 1

        return {
            **state,
            "dataset_id": selected[0] if selected else state.get("dataset_id", ""),
            "selected_sources": selected,
            "is_multi_source": multi,
            "source_plan": {
                "per_source": parsed.get("per_source") or [],
                "combine": parsed.get("combine"),
            },
            "dataset_meta": None,
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(
                state, "select_sources", "done", f"Selected {len(selected)} source(s)"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": f"select_sources failed: {exc}"}


def plan(state: AgentState) -> AgentState:
    try:
        use_sources = state.get("dataset_meta") is None
        ctx = privacy.build_context(
            None if use_sources else state["dataset_meta"],
            question=state.get("question", ""),
            sources=state.get("sources") if use_sources else None,
            annotations=state.get("annotations"),
            conversation=state.get("conversation"),
            source_plan=state.get("source_plan"),
        )
        system = _load_prompt("plan.md")
        with timed_llm_call("plan", state.get("run_id", "")) as usage:
            text, u = LLMClient().call_with_usage(privacy.render_context(ctx), system=system)
            usage.update(u)
        tokens, cost = _accumulate_usage(state, u)
        return {
            **state,
            "plan": text.strip(),
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(state, "plan", "done", "Planned the analysis"),
        }
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": f"plan failed: {exc}"}


def generate_code(state: AgentState) -> AgentState:
    try:
        is_multi = bool(state.get("is_multi_source"))
        legacy = (not is_multi) and state.get("dataset_meta") is not None
        prev = state.get("execution_result") or {}
        retry_count = state.get("retry_count", 0)
        is_retry = bool(prev.get("error"))
        if is_retry:
            retry_count += 1

        if legacy:
            # ---- Phase 1/2 behaviour: single file source, one pandas block ----
            ctx = privacy.build_context(
                state["dataset_meta"],
                question=state.get("question", ""),
                plan=state.get("plan"),
                previous_code=(state.get("generated_code") if prev.get("error") else None),
                previous_error=prev.get("error"),
                annotations=state.get("annotations"),
                conversation=state.get("conversation"),
            )
            system = _load_prompt("generate_code.md")
            with timed_llm_call("generate_code", state.get("run_id", "")) as usage:
                text, u = LLMClient().call_with_usage(privacy.render_context(ctx), system=system)
                usage.update(u)
            code = _extract_code(text)
            tokens, cost = _accumulate_usage(state, u)
            detail = "Wrote pandas code" if not is_retry else f"Revised code (retry {retry_count})"
            return {
                **state,
                "generated_code": code,
                "per_source_code": {},
                "combine_code": None,
                "retry_count": retry_count,
                "tokens": tokens,
                "cost_usd": cost,
                "step_trace": _trace(state, "generate_code", "done", detail),
            }

        # ---- Phase 3: per-source (pandas or SQL) + optional local combine ----
        sources = state.get("sources") or []
        by_id = {str(s.get("source_id", "")): s for s in sources}
        selected = state.get("selected_sources") or list(by_id.keys())
        prev_error = prev.get("error")
        prior_per_source = state.get("per_source_code") or {}

        tokens = dict(state.get("tokens", {"prompt": 0, "completion": 0}))
        cost = state.get("cost_usd", 0.0)
        per_source_code: dict = {}
        display_parts: list[str] = []

        for sid in selected:
            src = by_id.get(sid, {"source_id": sid, "kind": "file"})
            kind = src.get("kind", "file")
            ctx = privacy.build_context(
                None,
                question=state.get("question", ""),
                sources=[src],
                plan=state.get("plan"),
                previous_code=(prior_per_source.get(sid, {}).get("code") if prev_error else None),
                previous_error=(prev_error if prev_error else None),
                annotations=state.get("annotations"),
                conversation=state.get("conversation"),
            )
            prompt_file = "generate_sql.md" if kind == "db" else "generate_code.md"
            with timed_llm_call(f"generate_code:{sid}", state.get("run_id", "")) as usage:
                text, u = LLMClient().call_with_usage(
                    privacy.render_context(ctx), system=_load_prompt(prompt_file)
                )
                usage.update(u)
            code = _extract_code(text)
            tokens, cost = _accumulate_usage({"tokens": tokens, "cost_usd": cost}, u)
            lang = "sql" if kind == "db" else "pandas"
            per_source_code[sid] = {"lang": lang, "code": code}
            display_parts.append(f"# --- source {sid} ({lang}) ---\n{code}")

        combine_code = None
        if is_multi:
            combine_sources = [by_id[sid] for sid in selected if sid in by_id]
            combine_ctx = privacy.build_context(
                None,
                question=state.get("question", ""),
                sources=combine_sources,
                plan=state.get("plan"),
                source_plan=state.get("source_plan"),
            )
            var_lines = [
                "",
                "Per-source computed result variable names (already-computed pandas objects — "
                "each is exactly what the per-source code below assigns to `result`):",
            ]
            for sid in selected:
                entry = per_source_code.get(sid, {})
                var_lines.append(f"  - {_safe_var(sid)}   (source {sid}, {entry.get('lang', 'pandas')}):")
                var_lines.append("    " + entry.get("code", "").replace("\n", "\n    "))
            if prev_error:
                var_lines.append("")
                var_lines.append("Your previous combine attempt failed with this error — fix it:")
                var_lines.append(str(prev_error))
            combine_user = privacy.render_context(combine_ctx) + "\n" + "\n".join(var_lines)
            with timed_llm_call("generate_code:combine", state.get("run_id", "")) as usage:
                text, u = LLMClient().call_with_usage(
                    combine_user, system=_load_prompt("generate_combine.md")
                )
                usage.update(u)
            combine_code = _extract_code(text)
            tokens, cost = _accumulate_usage({"tokens": tokens, "cost_usd": cost}, u)
            display_parts.append(f"# --- combine ---\n{combine_code}")

        detail = "Wrote per-source code" if not is_retry else f"Revised per-source code (retry {retry_count})"
        return {
            **state,
            "generated_code": "\n\n".join(display_parts),
            "per_source_code": per_source_code,
            "combine_code": combine_code,
            "retry_count": retry_count,
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(state, "generate_code", "done", detail),
        }
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": f"generate_code failed: {exc}"}


def execute_locally(state: AgentState) -> AgentState:
    per_source_code = state.get("per_source_code") or {}

    if not per_source_code:
        # ---- Phase 1/2 behaviour: single file source, local pandas run ----
        try:
            df = store.load_df(state["dataset_id"])
        except Exception as exc:  # noqa: BLE001 — file load is fatal
            return {**state, "error": f"Could not load dataset: {exc}"}

        exec_result = run_code(state.get("generated_code", ""), df)
        detail = (
            f"Ran locally on {len(df):,} rows"
            if exec_result.ok
            else f"Execution error: {exec_result.error}"
        )
        return {
            **state,
            "execution_result": {
                "result_summary": exec_result.result_summary,
                "stdout": exec_result.stdout,
                "error": exec_result.error,
            },
            "step_trace": _trace(
                state, "execute_locally", "done" if exec_result.ok else "error", detail
            ),
        }

    # ---- Phase 3: source-type-aware execution (+ local combine) ----
    sources = state.get("sources") or []
    by_id = {str(s.get("source_id", "")): s for s in sources}
    selected = state.get("selected_sources") or list(per_source_code.keys())

    intermediates: dict[str, object] = {}
    variables: dict[str, object] = {}
    errors: list[str] = []
    notes: list[str] = []

    for sid in selected:
        src = by_id.get(sid, {"source_id": sid, "kind": "file"})
        kind = src.get("kind", "file")
        entry = per_source_code.get(sid) or {}
        code = entry.get("code", "")
        try:
            if kind == "db":
                dsn = _connection_dsn(str(src.get("connection_id", sid)))
                df_i = db_source.run_query(dsn, code)
            else:
                full_df = store.load_df(sid)
                df_i = run_code_raw(code, full_df)
        except Exception as exc:  # noqa: BLE001 — non-fatal, drives the refine loop
            errors.append(f"[{sid}] {type(exc).__name__}: {exc}")
            continue
        intermediates[sid] = df_i
        variables[_safe_var(sid)] = df_i
        try:
            notes.append(f"{sid}:{len(df_i)} rows")
        except TypeError:
            notes.append(sid)

    if errors:
        message = "; ".join(errors)
        return {
            **state,
            "execution_result": {"result_summary": None, "stdout": "", "error": message},
            "step_trace": _trace(state, "execute_locally", "error", message),
        }

    combine_code = state.get("combine_code")
    if combine_code:
        combine_result = run_combine(combine_code, variables)
        if not combine_result.ok:
            return {
                **state,
                "execution_result": {
                    "result_summary": None,
                    "stdout": combine_result.stdout,
                    "error": combine_result.error,
                },
                "step_trace": _trace(
                    state, "execute_locally", "error", f"Combine error: {combine_result.error}"
                ),
            }
        result_summary = combine_result.result_summary
    else:
        only = next(iter(intermediates.values())) if intermediates else None
        result_summary = summarize_result(only)

    detail = f"Ran locally across {len(selected)} source(s): " + ", ".join(notes)
    return {
        **state,
        "execution_result": {"result_summary": result_summary, "stdout": "", "error": None},
        "step_trace": _trace(state, "execute_locally", "done", detail),
    }


def _verify_summary(summary: dict | None, row_count: int) -> tuple[bool, str]:
    if summary is None:
        return False, "No result produced."
    kind = summary.get("kind")

    if kind == "none":
        return False, "Result is None."

    if kind in ("dataframe", "series"):
        rows = summary.get("rows", [])
        if not rows:
            return False, "Result table is empty."
        # Group counts cannot exceed total row count.
        length = summary.get("shape", [0])[0] if kind == "dataframe" else summary.get("length", 0)
        if length > row_count and row_count > 0:
            return False, f"Result has {length} groups > {row_count} source rows."
        # All-null guard.
        if kind == "series":
            values = [r.get("value") for r in rows]
            if values and all(v is None for v in values):
                return False, "All result values are null."
        return True, "Checks passed"

    if kind == "scalar":
        val = summary.get("value")
        if val is None:
            return False, "Scalar result is null."
        if isinstance(val, float):
            import math

            if math.isnan(val) or math.isinf(val):
                return False, "Scalar result is not finite."
        return True, "Checks passed"

    if kind in ("dict", "list"):
        if not summary.get("value"):
            return False, "Result is empty."
        return True, "Checks passed"

    return True, "Checks passed"


def verify(state: AgentState) -> AgentState:
    exec_result = state.get("execution_result") or {}
    max_retries = get_settings().max_retries
    retry_count = state.get("retry_count", 0)

    if exec_result.get("error"):
        passed, notes = False, exec_result["error"]
    else:
        row_count = int((state.get("dataset_meta") or {}).get("row_count", 0))
        passed, notes = _verify_summary(exec_result.get("result_summary"), row_count)

    low_confidence = state.get("low_confidence", False)
    if not passed and retry_count >= max_retries:
        low_confidence = True

    return {
        **state,
        "verification": {"passed": passed, "notes": notes},
        "low_confidence": low_confidence,
        "step_trace": _trace(
            state, "verify", "done" if passed else "error", notes
        ),
    }


def answer(state: AgentState) -> AgentState:
    try:
        exec_result = state.get("execution_result") or {}
        low_conf = state.get("low_confidence", False)
        question = state.get("question", "")
        if low_conf:
            question = f"{question}\n(Note: confidence is low — the result could not be fully verified.)"
        use_sources = state.get("dataset_meta") is None
        ctx = privacy.build_context(
            None if use_sources else state["dataset_meta"],
            question=question,
            sources=state.get("sources") if use_sources else None,
            result_summary=exec_result.get("result_summary"),
            annotations=state.get("annotations"),
            conversation=state.get("conversation"),
        )
        system = _load_prompt("answer.md")
        with timed_llm_call("answer", state.get("run_id", "")) as usage:
            text, u = LLMClient().call_with_usage(privacy.render_context(ctx), system=system)
            usage.update(u)
        tokens, cost = _accumulate_usage(state, u)
        return {
            **state,
            "answer": text.strip(),
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(state, "answer", "done", "Wrote the answer"),
        }
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": f"answer failed: {exc}"}


def is_chartable(state: AgentState) -> bool:
    """Decide whether the chart_spec node should run.

    Charts when the user asked for one (``want_chart``) OR the result is
    naturally chartable — a non-empty grouped/aggregated table or series.
    Scalars, empty results, and failed runs are never charted.
    """
    if state.get("error"):
        return False
    exec_result = state.get("execution_result") or {}
    summary = exec_result.get("result_summary") or {}
    kind = summary.get("kind")
    if kind not in ("dataframe", "series"):
        return False
    if not summary.get("rows"):
        return False
    return True


def _validate_vega_spec(spec: object, max_rows: int) -> dict | None:
    """Return the spec if it is a usable Vega-Lite object, else None.

    Requires a `mark` and an `encoding`, and enforces the privacy bound: any
    inline `data.values` must not exceed ``max_rows`` rows (defense-in-depth —
    the model only ever saw the bounded summary)."""
    if not isinstance(spec, dict):
        return None
    if "mark" not in spec or "encoding" not in spec:
        return None
    data = spec.get("data")
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        if len(data["values"]) > max_rows:
            data["values"] = data["values"][:max_rows]
    return spec


def chart_spec(state: AgentState) -> AgentState:
    """Emit a Vega-Lite v5 chart spec from schema + the BOUNDED result summary.

    Prompt built ONLY via the privacy choke point (never raw data). Degrades
    gracefully: on any failure the run continues with no chart (not an error).
    """
    exec_result = state.get("execution_result") or {}
    result_summary = exec_result.get("result_summary")
    max_rows = get_settings().result_rows
    # No usable result → no chart, no LLM call (e.g. want_chart forced on a
    # scalar/failed result). Degrade quietly.
    if not result_summary or result_summary.get("kind") not in ("dataframe", "series"):
        return {
            **state,
            "chart_spec": None,
            "step_trace": _trace(state, "chart_spec", "done", "No chart (result not chartable)"),
        }
    try:
        ctx = privacy.build_context(
            state["dataset_meta"],
            question=state.get("question", ""),
            result_summary=result_summary,
        )
        system = _load_prompt("chart.md")
        with timed_llm_call("chart_spec", state.get("run_id", "")) as usage:
            text, u = LLMClient().call_with_usage(privacy.render_context(ctx), system=system)
            usage.update(u)
        tokens, cost = _accumulate_usage(state, u)
        spec = _validate_vega_spec(_extract_json(text), max_rows)
        if spec is None:
            return {
                **state,
                "chart_spec": None,
                "tokens": tokens,
                "cost_usd": cost,
                "step_trace": _trace(
                    state, "chart_spec", "done", "No chart (result not chartable)"
                ),
            }
        return {
            **state,
            "chart_spec": spec,
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(state, "chart_spec", "done", "Built a chart"),
        }
    except Exception as exc:  # noqa: BLE001 — charting never fails the run
        return {
            **state,
            "chart_spec": None,
            "step_trace": _trace(state, "chart_spec", "done", f"Chart skipped: {exc}"),
        }


def finalize(state: AgentState) -> AgentState:
    return {**state, "status": "completed"}


def handle_error(state: AgentState) -> AgentState:
    return {
        **state,
        "status": "failed",
        "step_trace": _trace(state, "error", "error", state.get("error", "Unknown error")),
    }
