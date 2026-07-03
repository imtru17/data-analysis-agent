from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Identity
    run_id: str
    dataset_id: str

    # Input
    question: str
    dataset_meta: dict          # {dataset_id, filename, columns, dtypes, sample_rows, row_count} — schema+samples ONLY
    want_chart: bool            # request-level flag: force chart generation

    # Pipeline data (populated progressively by nodes)
    is_trivial: bool
    plan: str | None
    generated_code: str
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
