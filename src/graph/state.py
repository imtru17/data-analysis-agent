from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Identity
    run_id: str
    dataset_id: str
    session_id: str          # Phase 3 — the session this run belongs to

    # Input
    question: str
    dataset_meta: dict          # {dataset_id, filename, columns, dtypes, sample_rows, row_count} — schema+samples ONLY
    want_chart: bool            # request-level flag: force chart generation

    # Phase 3 — multi-source + memory + annotations (all schema/samples/prose ONLY)
    sources: list                # registered sources in scope: [{source_id, kind, name, columns/tables, sample_rows}]
    selected_sources: list       # [source_id, ...] chosen by `select_sources`
    is_multi_source: bool        # True when >1 source selected -> join/compare path
    source_plan: dict | None     # {per_source:[...], combine:str} from `select_sources`
    conversation: list           # prior turns [{role, content}] — privacy-safe prose
    annotations: list            # [{source_id, table_name, column, note}] — privacy-safe text

    # Pipeline data (populated progressively by nodes)
    is_trivial: bool
    plan: str | None
    generated_code: str
    per_source_code: dict           # Phase 3 — {source_id: {lang: "pandas"|"sql", code}}
    combine_code: str | None        # Phase 3 — local pandas snippet combining per-source intermediates
    execution_result: dict | None   # {result_summary, stdout, error} — result stays LOCAL
    verification: dict | None       # {passed: bool, notes: str}
    retry_count: int
    low_confidence: bool

    # Output
    answer: str
    chart_spec: dict | None     # Vega-Lite v5 spec with bounded inline data (or None)
    step_trace: list            # [{step, status, detail, ts}]
    tokens: dict                # {prompt, completion}
    cost_usd: float

    # Control
    error: str | None
    status: str                 # "running" | "completed" | "failed"
