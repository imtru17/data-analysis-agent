"""Phase 2 — per-query cost accounting against the REAL Anthropic API.

A real run must record non-zero prompt/completion tokens + cost on its audit
row (from the actual Anthropic ``usage``), and ``GET /cost/today`` must sum
today's runs.
"""
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from db.models import AnalysisRunRow


def _upload_sales(client) -> str:
    regions = ["West"] * 20 + ["East"] * 20 + ["North"] * 20
    df = pd.DataFrame({"region": regions, "revenue": list(range(1, 61))})
    files = {"file": ("sales.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


@pytest.mark.usefixtures("_require_llm_key")
def test_run_records_tokens_and_cost_and_cost_today_sums(api_client, _isolated_db):
    from graph.runner import run_analysis

    dataset_id = _upload_sales(api_client)
    result = run_analysis(dataset_id, "What is the total revenue by region?")
    assert result["status"] == "completed", result

    # Real usage recorded on the persisted audit row.
    with Session(_isolated_db) as s:
        run = s.get(AnalysisRunRow, result["run_id"])
        assert run is not None
        assert run.prompt_tokens > 0, run.prompt_tokens
        assert run.completion_tokens > 0, run.completion_tokens
        assert run.cost_usd > 0.0, run.cost_usd

    # The endpoint sums today's spend.
    r = api_client.get("/cost/today")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["run_count"] >= 1
    assert data["prompt_tokens"] > 0
    assert data["completion_tokens"] > 0
    assert data["cost_usd"] > 0.0
    assert data["prompt_tokens"] >= run.prompt_tokens
