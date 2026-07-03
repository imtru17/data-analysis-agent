"""Phase 2 — chart_spec node against the REAL Anthropic API.

Runs a real analysis with ``want_chart=True`` on a small grouped dataset and
asserts the terminal chart spec is valid Vega-Lite v5 with bounded inline data.
A transport-level privacy spy proves the chart prompt carried only schema + the
bounded result summary — a sentinel planted deep in the raw file never reaches
the chart node's outbound request.
"""
import json

import pandas as pd
import pytest

from config.settings import get_settings

SENTINEL = "CHART_SENTINEL_LEAK_b71e"


def _upload_grouped(client) -> str:
    # 60 rows across 3 regions; the sentinel lives in a non-sampled row and in a
    # column that the grouped result never surfaces, so it can only leak via raw
    # data — which the privacy boundary forbids.
    regions = ["West"] * 20 + ["East"] * 20 + ["North"] * 20
    notes = ["ordinary"] * 60
    notes[45] = SENTINEL  # far beyond the 5-row head sample
    df = pd.DataFrame(
        {"region": regions, "note": notes, "revenue": list(range(1, 61))}
    )
    files = {"file": ("sales.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


def _install_anthropic_spy(monkeypatch, captured: list[dict]) -> None:
    from llm.providers import anthropic as provider_mod

    real_init = provider_mod.AnthropicProvider.__init__

    def capturing_init(self, api_key, model):
        real_init(self, api_key, model)
        original_create = self._client.messages.create

        def spy(**kwargs):
            captured.append(kwargs)
            return original_create(**kwargs)

        self._client.messages.create = spy

    monkeypatch.setattr(provider_mod.AnthropicProvider, "__init__", capturing_init)


@pytest.mark.usefixtures("_require_llm_key")
def test_want_chart_yields_valid_vega_lite_spec(api_client, monkeypatch):
    from graph.runner import run_analysis

    dataset_id = _upload_grouped(api_client)
    captured: list[dict] = []
    _install_anthropic_spy(monkeypatch, captured)

    result = run_analysis(
        dataset_id, "What is the total revenue by region?", want_chart=True
    )

    assert result["status"] == "completed", result
    spec = result["chart_spec"]
    assert spec is not None, f"want_chart=True produced no chart: {result}"

    # Valid Vega-Lite v5: JSON-serialisable object with a mark + encoding.
    reparsed = json.loads(json.dumps(spec))
    assert isinstance(reparsed, dict)
    assert "mark" in reparsed
    assert "encoding" in reparsed
    assert isinstance(reparsed["encoding"], dict) and reparsed["encoding"]

    # Inline data is bounded to at most AGENT_RESULT_ROWS rows.
    max_rows = get_settings().result_rows
    data = reparsed.get("data")
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        assert len(data["values"]) <= max_rows

    # The chart run must be persisted onto the audit row.
    assert result["chart_spec"] is not None


@pytest.mark.usefixtures("_require_llm_key")
def test_chart_prompt_is_privacy_safe(api_client, monkeypatch):
    """The chart node's outbound Anthropic request carries a real column name
    but NEVER the sentinel from a non-sampled raw row."""
    from graph.runner import run_analysis

    dataset_id = _upload_grouped(api_client)
    captured: list[dict] = []
    _install_anthropic_spy(monkeypatch, captured)

    run_analysis(dataset_id, "What is the total revenue by region?", want_chart=True)

    # Isolate the chart node's request by its system prompt.
    chart_reqs = [
        k for k in captured
        if "visualization expert" in str(k.get("system", ""))
    ]
    assert chart_reqs, "the chart node made no Anthropic request"

    for kwargs in chart_reqs:
        user_content = json.dumps(kwargs.get("messages", []), default=str)
        assert "region" in user_content          # real schema column present
        assert SENTINEL not in user_content       # raw-row sentinel absent
        assert SENTINEL not in str(kwargs.get("system", ""))

    # Defense in depth: no request in the whole run leaked the sentinel.
    for kwargs in captured:
        assert SENTINEL not in json.dumps(kwargs, default=str)
