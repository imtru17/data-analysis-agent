"""THE SINGLE PRIVACY CHOKE POINT.

Every LLM-calling node builds its user-message content ONLY through this
module. The invariant: the bytes that reach the Anthropic API are only
(a) the schema — an ordered list of {column_name, dtype} — and (b) at most
``AGENT_SAMPLE_ROWS`` sample rows, plus (for the answer node) a bounded
``result_summary`` produced by *local* code.

Phase 3 extends WHAT may cross — but not the principle. In addition to schema +
bounded samples + bounded summary, the choke point may now carry, for EACH
source in scope: its schema + bounded samples; plus user-authored **column
annotations** (privacy-safe text); plus the last few **conversation** turns
(prior questions + the agent's own prior answers — prose it already produced
from bounded summaries). It NEVER carries: a full DataFrame, a full DB table,
raw rows beyond the bounded sample, or a database connection string (DSN).

``LlmContext`` has NO reference to a DataFrame, a DB engine, or a DSN — it
cannot, by construction, carry raw data or a secret onward. The caps are
re-enforced here as defense-in-depth even though the callers already bound their
outputs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from config.settings import get_settings


@dataclass
class LlmContext:
    """The only shape of data allowed into an LLM prompt.

    Carries schema + bounded samples (single or multi-source) + optional bounded
    result summary, plan, prior-error (refine loop), user annotations, and
    bounded conversation prose. Never a DataFrame, a DB table, or a DSN.
    """

    columns: list[dict] = field(default_factory=list)   # single-source [{name, dtype}]
    sample_rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    question: str = ""
    plan: str | None = None
    result_summary: dict | None = None      # bounded — from local execution
    previous_code: str | None = None        # refine loop
    previous_error: str | None = None       # refine loop
    # Phase 3
    sources: list[dict] | None = None        # [{source_id, kind, name, columns/tables, sample_rows}]
    annotations: list[dict] | None = None    # [{source_id, table_name, column, note}]
    conversation: list[dict] | None = None   # [{role, content}] — privacy-safe prose
    source_plan: dict | None = None          # {per_source:[...], combine:str}


def _cap_cell(value: object, cap: int) -> object:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    return text[:cap] + "…" if len(text) > cap else text


def _bound_rows(rows: list[dict], max_rows: int, cap: int) -> list[dict]:
    bounded: list[dict] = []
    for row in rows[:max_rows]:
        bounded.append({str(k): _cap_cell(v, cap) for k, v in row.items()})
    return bounded


def _bound_summary(summary: dict | None, max_rows: int, cap: int) -> dict | None:
    """Re-bound a result summary before it can leave. Scalars pass; any embedded
    ``rows`` list is truncated + cell-capped."""
    if summary is None:
        return None
    bounded = dict(summary)
    rows = bounded.get("rows")
    if isinstance(rows, list):
        bounded["rows"] = _bound_rows(rows, max_rows, cap)
        if len(rows) > max_rows:
            bounded["truncated"] = True
    return bounded


def _bound_source(source: dict, sample_cap: int, cell_cap: int) -> dict:
    """Re-bound a single source's schema+samples (file or DB). Strips anything
    that is not schema/sample metadata — never carries a path, DSN, or engine."""
    kind = source.get("kind", "file")
    out: dict = {
        "source_id": str(source.get("source_id", "")),
        "kind": kind,
        "name": str(source.get("name", "")),
    }
    if kind == "db":
        tables = []
        for t in source.get("tables", []) or []:
            tables.append(
                {
                    "table": str(t.get("table", "")),
                    "columns": [
                        {"name": str(c["name"]), "dtype": str(c["dtype"])}
                        for c in t.get("columns", [])
                    ],
                    "sample_rows": _bound_rows(
                        t.get("sample_rows", []) or [], sample_cap, cell_cap
                    ),
                }
            )
        out["tables"] = tables
    else:
        out["row_count"] = int(source.get("row_count", 0) or 0)
        out["columns"] = [
            {"name": str(c["name"]), "dtype": str(c["dtype"])}
            for c in source.get("columns", [])
        ]
        out["sample_rows"] = _bound_rows(
            source.get("sample_rows", []) or [], sample_cap, cell_cap
        )
    return out


def build_context(
    dataset_meta: dict | None = None,
    *,
    question: str = "",
    plan: str | None = None,
    result_summary: dict | None = None,
    previous_code: str | None = None,
    previous_error: str | None = None,
    sources: list[dict] | None = None,
    annotations: list[dict] | None = None,
    conversation: list[dict] | None = None,
    source_plan: dict | None = None,
) -> LlmContext:
    """Build the ONLY object allowed to become an LLM prompt.

    ``dataset_meta`` (single source) or ``sources`` (multi-source) carry the
    schema+samples. A DataFrame passed as ``dataset_meta`` is a programming error
    and is rejected loudly.
    """
    if dataset_meta is not None and not isinstance(dataset_meta, dict):
        raise TypeError(
            "privacy.build_context received a non-dict dataset_meta "
            f"({type(dataset_meta).__name__}); only schema+samples may cross "
            "the privacy boundary, never a DataFrame."
        )

    settings = get_settings()
    sample_cap = settings.sample_rows
    cell_cap = settings.sample_cell_chars
    result_cap = settings.result_rows

    columns: list[dict] = []
    sample_rows: list[dict] = []
    row_count = 0
    if dataset_meta is not None:
        columns = [
            {"name": str(c["name"]), "dtype": str(c["dtype"])}
            for c in dataset_meta.get("columns", [])
        ]
        sample_rows = _bound_rows(dataset_meta.get("sample_rows", []), sample_cap, cell_cap)
        row_count = int(dataset_meta.get("row_count", 0))

    bounded_sources = None
    if sources:
        bounded_sources = [_bound_source(s, sample_cap, cell_cap) for s in sources]

    bounded_annotations = None
    if annotations:
        bounded_annotations = [
            {
                "source_id": str(a.get("source_id", "")),
                "table_name": (str(a["table_name"]) if a.get("table_name") else None),
                "column": str(a.get("column", "")),
                "note": _cap_cell(a.get("note", ""), settings.sample_cell_chars),
            }
            for a in annotations
        ]

    bounded_conversation = None
    if conversation:
        turns = conversation[-settings.memory_turns * 2 :]
        bounded_conversation = [
            {"role": str(t.get("role", "")), "content": str(t.get("content", ""))}
            for t in turns
        ]

    return LlmContext(
        columns=columns,
        sample_rows=sample_rows,
        row_count=row_count,
        question=question,
        plan=plan,
        result_summary=_bound_summary(result_summary, result_cap, cell_cap),
        previous_code=previous_code,
        previous_error=previous_error,
        sources=bounded_sources,
        annotations=bounded_annotations,
        conversation=bounded_conversation,
        source_plan=source_plan,
    )


def _render_single_source(ctx: LlmContext, lines: list[str]) -> None:
    lines.append(f"Dataset: {ctx.row_count} rows.")
    lines.append("The DataFrame variable is named `df`.")
    lines.append("")
    lines.append("Schema (column name — dtype):")
    for col in ctx.columns:
        lines.append(f"  - {col['name']}: {col['dtype']}")
    lines.append("")
    lines.append(f"Sample rows (at most {len(ctx.sample_rows)}, not the full data):")
    lines.append(json.dumps(ctx.sample_rows, ensure_ascii=False, default=str))


def _render_sources(ctx: LlmContext, lines: list[str]) -> None:
    lines.append(f"Sources in scope ({len(ctx.sources)}):")
    for src in ctx.sources or []:
        lines.append("")
        if src["kind"] == "db":
            lines.append(f"- Source {src['source_id']} — DB \"{src['name']}\" (SQL source):")
            for tbl in src.get("tables", []):
                lines.append(f"    Table {tbl['table']} (columns — dtype):")
                for col in tbl["columns"]:
                    lines.append(f"      - {col['name']}: {col['dtype']}")
                lines.append(
                    f"    Sample rows (≤{len(tbl['sample_rows'])}): "
                    + json.dumps(tbl["sample_rows"], ensure_ascii=False, default=str)
                )
        else:
            lines.append(
                f"- Source {src['source_id']} — file \"{src['name']}\" "
                f"({src.get('row_count', 0)} rows, pandas DataFrame source):"
            )
            lines.append("    Schema (column name — dtype):")
            for col in src.get("columns", []):
                lines.append(f"      - {col['name']}: {col['dtype']}")
            lines.append(
                f"    Sample rows (≤{len(src.get('sample_rows', []))}): "
                + json.dumps(src.get("sample_rows", []), ensure_ascii=False, default=str)
            )


def render_context(ctx: LlmContext) -> str:
    """Render the user-message text. This string is the ENTIRE payload the LLM
    sees beyond the system prompt — schema, bounded samples, and (optionally) the
    bounded result summary / plan / prior error / annotations / conversation.
    Never raw data beyond the bounded sample, never a DSN."""
    lines: list[str] = []

    if ctx.question:
        lines.append(f"Question: {ctx.question}")
        lines.append("")

    if ctx.conversation:
        lines.append("Prior conversation (most recent last, prose only):")
        for turn in ctx.conversation:
            who = "User" if turn["role"] == "user" else "Assistant"
            lines.append(f"  {who}: {turn['content']}")
        lines.append("")

    if ctx.sources:
        _render_sources(ctx, lines)
    else:
        _render_single_source(ctx, lines)

    if ctx.annotations:
        lines.append("")
        lines.append("Column annotations (user-authored business meaning):")
        for ann in ctx.annotations:
            loc = ann["column"]
            if ann.get("table_name"):
                loc = f"{ann['table_name']}.{ann['column']}"
            lines.append(f"  - [{ann['source_id']}] {loc}: {ann['note']}")

    if ctx.source_plan:
        lines.append("")
        lines.append("Source plan (how to split + combine across sources):")
        lines.append(json.dumps(ctx.source_plan, ensure_ascii=False, default=str))

    if ctx.plan:
        lines.append("")
        lines.append("Plan:")
        lines.append(ctx.plan)

    if ctx.previous_code is not None:
        lines.append("")
        lines.append("Your previous code failed. Previous code:")
        lines.append(ctx.previous_code)
        lines.append("Error it produced:")
        lines.append(str(ctx.previous_error))
        lines.append("Fix the code so it runs and answers the question.")

    if ctx.result_summary is not None:
        lines.append("")
        lines.append("Computed result summary (already calculated locally):")
        lines.append(json.dumps(ctx.result_summary, ensure_ascii=False, default=str))

    return "\n".join(lines)
