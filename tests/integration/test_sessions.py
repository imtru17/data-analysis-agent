"""Persistent sessions (Phase 3): create a session, run an analysis in it,
reload it, and confirm conversation memory (bounded, privacy-safe prose)
reaches the LLM on a follow-up — never raw rows."""
from __future__ import annotations

import json

import pandas as pd
import pytest


def _upload_sales(client) -> str:
    regions = ["West"] * 20 + ["East"] * 20 + ["North"] * 20
    revenue = list(range(1, 61))
    df = pd.DataFrame({"region": regions, "revenue": revenue})
    files = {"file": ("sales.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


@pytest.mark.usefixtures("_require_llm_key")
def test_session_create_run_reload_restores_thread(api_client):
    from graph.runner import run_analysis

    r = api_client.post("/sessions", json={"title": "Q3 revenue"})
    assert r.status_code == 200, r.text
    session_id = r.json()["data"]["session_id"]

    dataset_id = _upload_sales(api_client)

    result = run_analysis(
        dataset_id, "What is the total revenue by region?", session_id=session_id
    )
    assert result["status"] == "completed", result

    r2 = api_client.get(f"/sessions/{session_id}")
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert data["session_id"] == session_id
    roles = [m["role"] for m in data["messages"]]
    assert "user" in roles and "assistant" in roles
    assert any("revenue" in m["content"].lower() or "region" in m["content"].lower() for m in data["messages"])


@pytest.mark.usefixtures("_require_llm_key")
def test_followup_prompt_carries_prior_turn_prose_not_raw_rows(api_client, monkeypatch):
    """A privacy spy captures the exact Anthropic request for a follow-up ask
    in the same session; it must carry the prior turn's prose but never a
    sentinel planted deep in the raw file."""
    from graph.runner import run_analysis
    from llm.providers import anthropic as provider_mod

    sentinel = "SESSION_SENTINEL_44df"
    regions = ["West"] * 40
    notes = ["ordinary"] * 40
    notes[35] = sentinel
    df = pd.DataFrame({"region": regions, "note": notes, "revenue": range(40)})
    files = {"file": ("d.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    dataset_id = api_client.post("/datasets", files=files).json()["data"]["dataset_id"]

    session_id = api_client.post("/sessions", json={}).json()["data"]["session_id"]

    first = run_analysis(dataset_id, "What is the total revenue?", session_id=session_id)
    assert first["status"] == "completed", first

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

    second = run_analysis(dataset_id, "And what about the row count?", session_id=session_id)
    assert second["status"] == "completed", second

    assert captured, "no Anthropic request was captured on the follow-up"
    blob = json.dumps(captured, default=str)
    assert sentinel not in blob
    # The prior turn's question text should be present (bounded prose).
    assert "total revenue" in blob.lower()


@pytest.mark.usefixtures("_require_llm_key")
def test_list_sessions_returns_created_session(api_client):
    r = api_client.post("/sessions", json={"title": "listed"})
    session_id = r.json()["data"]["session_id"]

    r2 = api_client.get("/sessions")
    assert r2.status_code == 200
    ids = [s["session_id"] for s in r2.json()["data"]]
    assert session_id in ids


def test_get_unknown_session_returns_404(api_client):
    r = api_client.get("/sessions/does-not-exist")
    assert r.status_code == 404
