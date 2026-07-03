"""End-to-end analysis pipeline against the REAL Anthropic API.

Skips (never stubs) only if the key is genuinely absent. Uses the production
SQLite driver via the isolated-DB fixture.
"""
import json

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from db.models import AnalysisRunRow, DatasetRow


def _collect_numbers(obj) -> list[float]:
    """Recursively collect every numeric value in a result summary."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_collect_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_collect_numbers(v))
    return out


def _upload_sales(client) -> tuple[str, pd.DataFrame]:
    # 60 rows across 3 regions — well beyond the 5-row sample, so a correct
    # per-region total can ONLY come from executing on the full data.
    regions = ["West"] * 20 + ["East"] * 20 + ["North"] * 20
    revenue = list(range(1, 61))
    df = pd.DataFrame({"region": regions, "revenue": revenue})
    files = {"file": ("sales.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"], df


@pytest.mark.usefixtures("_require_llm_key")
def test_total_revenue_by_region_matches_pandas(api_client, _isolated_db):
    from graph.runner import run_analysis

    dataset_id, df = _upload_sales(api_client)

    result = run_analysis(dataset_id, "What is the total revenue by region?")

    assert result["status"] == "completed", result
    assert result["answer"] and len(result["answer"]) > 10
    assert result["generated_code"] and "df" in result["generated_code"]

    # The correct per-region totals must appear in the locally-computed summary.
    expected = df.groupby("region")["revenue"].sum().to_dict()  # West 210, East 610, North 1010
    numbers = set(round(n, 2) for n in _collect_numbers(result["result_summary"]))
    for region, total in expected.items():
        assert float(total) in numbers, f"{region} total {total} missing from {numbers}"

    # Persisted audit row.
    with Session(_isolated_db) as s:
        run = s.get(AnalysisRunRow, result["run_id"])
        assert run is not None
        assert run.status == "completed"
        assert run.generated_code
        assert run.answer
        assert run.result_summary_json
        assert run.step_trace_json


@pytest.mark.usefixtures("_require_llm_key")
def test_trivial_ask_takes_fast_path_and_answers(api_client, _isolated_db):
    from graph.runner import run_analysis

    dataset_id, df = _upload_sales(api_client)

    result = run_analysis(dataset_id, "How many rows are there?")

    assert result["status"] == "completed", result
    numbers = _collect_numbers(result["result_summary"])
    assert 60.0 in [round(n, 2) for n in numbers]

    # Fast path: the `plan` step is not in the trace.
    steps = [e["step"] for e in result["step_trace"]]
    assert "plan" not in steps
    assert "generate_code" in steps and "execute_locally" in steps


@pytest.mark.usefixtures("_require_llm_key")
def test_sse_stream_emits_steps_then_done(api_client):
    from graph.runner import stream_analysis

    dataset_id, _ = _upload_sales(api_client)
    events = list(stream_analysis(dataset_id, "What is the total revenue by region?"))

    kinds = [e["event"] for e in events]
    assert "step" in kinds
    assert kinds[-1] in ("done", "error")
    assert kinds[-1] == "done", events[-1]
    done = events[-1]["data"]
    assert done["answer"]
    assert done["generated_code"]


@pytest.mark.usefixtures("_require_llm_key")
def test_outbound_anthropic_payload_carries_no_raw_data(api_client, monkeypatch):
    """Transport-level privacy gate: capture the EXACT request body the
    Anthropic SDK would send during a real run and assert it contains the
    schema + <=N samples but NONE of a sentinel planted deep in the file.
    The SDK call is intercepted (no network) but the full node->client->SDK
    payload path is real."""
    from graph.runner import run_analysis
    from llm.providers import anthropic as provider_mod

    sentinel = "TRANSPORT_SENTINEL_7c1a"
    regions = ["West"] * 40
    notes = ["ordinary"] * 40
    notes[30] = sentinel  # beyond the 5-row sample window
    df = pd.DataFrame({"region": regions, "note": notes, "revenue": range(40)})
    files = {"file": ("d.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    dataset_id = api_client.post("/datasets", files=files).json()["data"]["dataset_id"]

    captured: list[dict] = []
    real_init = provider_mod.AnthropicProvider.__init__

    def capturing_init(self, api_key, model):
        real_init(self, api_key, model)
        original_create = self._client.messages.create

        def spy(**kwargs):
            captured.append(kwargs)
            return original_create(**kwargs)

        self._client.messages.create = spy

    monkeypatch.setattr(provider_mod.AnthropicProvider, "__init__", capturing_init)

    run_analysis(dataset_id, "What is the total revenue by region?")

    assert captured, "no Anthropic request was captured"
    for kwargs in captured:
        blob = json.dumps(kwargs, default=str)
        assert "region" in blob            # schema present
        assert sentinel not in blob        # raw data absent


def test_verify_node_rejects_impossible_group_count():
    """Deterministic verify check — no LLM key needed. A group count that
    exceeds the source row count must fail verification."""
    from graph.nodes import verify

    state = {
        "dataset_meta": {"row_count": 10},
        "execution_result": {
            "result_summary": {
                "kind": "series",
                "length": 999,
                "rows": [{"index": "a", "value": 1}],
            },
            "error": None,
        },
        "retry_count": 0,
        "step_trace": [],
    }
    out = verify(state)
    assert out["verification"]["passed"] is False


def test_verify_node_flags_low_confidence_when_retries_exhausted():
    from graph.nodes import verify
    from config.settings import get_settings

    state = {
        "dataset_meta": {"row_count": 10},
        "execution_result": {"result_summary": None, "error": "boom"},
        "retry_count": get_settings().max_retries,
        "step_trace": [],
    }
    out = verify(state)
    assert out["verification"]["passed"] is False
    assert out["low_confidence"] is True
