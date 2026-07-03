from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    dtype: str


class DatasetProfile(BaseModel):
    dataset_id: str
    filename: str
    row_count: int
    columns: list[ColumnProfile]
    sample_rows: list[dict]


class AnalyzeRequest(BaseModel):
    dataset_id: str | None = None
    source_ids: list[str] | None = None    # Phase 3 — multi-source (files and/or connections)
    session_id: str | None = None          # Phase 3 — thread the run into a session's conversation
    question: str = Field(..., min_length=1)
    want_chart: bool = False


class RunTokens(BaseModel):
    prompt: int = 0
    completion: int = 0


class RunDetail(BaseModel):
    run_id: str
    dataset_id: str
    question: str
    generated_code: str | None = None
    plan: str | None = None
    result_summary: dict | None = None
    chart_spec: dict | None = None
    answer: str | None = None
    status: str
    low_confidence: bool = False
    retry_count: int = 0
    tokens: RunTokens = RunTokens()
    cost_usd: float = 0.0
    step_trace: list = []
    error_message: str | None = None
    created_at: str | None = None


class RunListItem(BaseModel):
    run_id: str
    dataset_id: str
    question: str
    status: str
    created_at: str | None = None
