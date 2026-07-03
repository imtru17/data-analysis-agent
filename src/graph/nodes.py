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

from analysis import privacy, store
from analysis.executor import run_code
from config.settings import get_settings
from graph.state import AgentState
from llm.client import LLMClient
from observability.llm_log import estimate_cost, timed_llm_call

_PROMPTS = Path(__file__).parent.parent / "prompts"

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

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
        return match.group(1).strip()
    # No fence — best effort: assume the whole text is code if it mentions result
    return text.strip()


def plan(state: AgentState) -> AgentState:
    try:
        ctx = privacy.build_context(
            state["dataset_meta"], question=state.get("question", "")
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
        prev = state.get("execution_result") or {}
        retry_count = state.get("retry_count", 0)
        is_retry = bool(prev.get("error"))
        if is_retry:
            retry_count += 1
        ctx = privacy.build_context(
            state["dataset_meta"],
            question=state.get("question", ""),
            plan=state.get("plan"),
            previous_code=(state.get("generated_code") if prev.get("error") else None),
            previous_error=prev.get("error"),
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
            "retry_count": retry_count,
            "tokens": tokens,
            "cost_usd": cost,
            "step_trace": _trace(state, "generate_code", "done", detail),
        }
    except Exception as exc:  # noqa: BLE001
        return {**state, "error": f"generate_code failed: {exc}"}


def execute_locally(state: AgentState) -> AgentState:
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
        row_count = int(state.get("dataset_meta", {}).get("row_count", 0))
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
        ctx = privacy.build_context(
            state["dataset_meta"],
            question=question,
            result_summary=exec_result.get("result_summary"),
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


def _extract_json(text: str) -> object | None:
    text = text.strip()
    # Strip an accidental code fence.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
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
