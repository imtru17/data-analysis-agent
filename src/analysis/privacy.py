"""THE SINGLE PRIVACY CHOKE POINT.

Every LLM-calling node builds its user-message content ONLY through this
module. The invariant: the bytes that reach the Anthropic API are only
(a) the schema — an ordered list of {column_name, dtype} — and (b) at most
``AGENT_SAMPLE_ROWS`` sample rows, plus (for the answer node) a bounded
``result_summary`` produced by *local* code. The full DataFrame, and any
computed result beyond the capped summary, never appear here.

``LlmContext`` has NO reference to a DataFrame — it cannot, by construction,
carry raw data onward. The caps are re-enforced here as defense-in-depth even
though ``store.profile`` and ``executor`` already bound their outputs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from config.settings import get_settings


@dataclass
class LlmContext:
    """The only shape of data allowed into an LLM prompt.

    Carries schema + bounded samples (+ optional bounded result summary and
    plan / prior-error for the refine loop). Never a DataFrame.
    """

    columns: list[dict] = field(default_factory=list)   # [{name, dtype}]
    sample_rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    question: str = ""
    plan: str | None = None
    result_summary: dict | None = None      # bounded — from local execution
    previous_code: str | None = None        # refine loop
    previous_error: str | None = None       # refine loop


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
    """Re-bound a result summary before it can leave. Scalars pass; any
    embedded ``rows`` list is truncated + cell-capped."""
    if summary is None:
        return None
    bounded = dict(summary)
    rows = bounded.get("rows")
    if isinstance(rows, list):
        bounded["rows"] = _bound_rows(rows, max_rows, cap)
        if len(rows) > max_rows:
            bounded["truncated"] = True
    return bounded


def build_context(
    dataset_meta: dict,
    *,
    question: str = "",
    plan: str | None = None,
    result_summary: dict | None = None,
    previous_code: str | None = None,
    previous_error: str | None = None,
) -> LlmContext:
    """Build the ONLY object allowed to become an LLM prompt.

    ``dataset_meta`` is the schema+samples dict from ``store.profile``; a
    DataFrame passed here is a programming error and is rejected loudly.
    """
    if not isinstance(dataset_meta, dict):
        raise TypeError(
            "privacy.build_context received a non-dict dataset_meta "
            f"({type(dataset_meta).__name__}); only schema+samples may cross "
            "the privacy boundary, never a DataFrame."
        )

    settings = get_settings()
    sample_cap = settings.sample_rows
    cell_cap = settings.sample_cell_chars
    result_cap = settings.result_rows

    columns = [
        {"name": str(c["name"]), "dtype": str(c["dtype"])}
        for c in dataset_meta.get("columns", [])
    ]
    sample_rows = _bound_rows(dataset_meta.get("sample_rows", []), sample_cap, cell_cap)

    return LlmContext(
        columns=columns,
        sample_rows=sample_rows,
        row_count=int(dataset_meta.get("row_count", 0)),
        question=question,
        plan=plan,
        result_summary=_bound_summary(result_summary, result_cap, cell_cap),
        previous_code=previous_code,
        previous_error=previous_error,
    )


def render_context(ctx: LlmContext) -> str:
    """Render the user-message text. This string is the ENTIRE payload the
    LLM sees beyond the system prompt — it contains only schema, bounded
    samples, and (optionally) the bounded result summary / plan / prior error."""
    lines: list[str] = []

    if ctx.question:
        lines.append(f"Question: {ctx.question}")
        lines.append("")

    lines.append(f"Dataset: {ctx.row_count} rows.")
    lines.append("The DataFrame variable is named `df`.")
    lines.append("")
    lines.append("Schema (column name — dtype):")
    for col in ctx.columns:
        lines.append(f"  - {col['name']}: {col['dtype']}")
    lines.append("")

    lines.append(f"Sample rows (at most {len(ctx.sample_rows)}, not the full data):")
    lines.append(json.dumps(ctx.sample_rows, ensure_ascii=False, default=str))

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
