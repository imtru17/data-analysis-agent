"""Phase 2 — LLM-suggested follow-up questions against the REAL Anthropic API.

Uploading a CSV then fetching its profile yields 2-3 non-empty follow-up
questions. A transport-level privacy spy proves the follow-up prompt carried
only schema + bounded samples — a sentinel planted in a non-sampled row never
reaches the outbound request.
"""
import json

import pandas as pd
import pytest

SENTINEL = "FOLLOWUP_SENTINEL_LEAK_3ac9"


def _upload_with_sentinel(client) -> str:
    # 40 rows; the sentinel lives at row 30, far beyond the 5-row head sample.
    df = pd.DataFrame(
        {
            "region": ["West"] * 40,
            "note": ["ordinary"] * 30 + [SENTINEL] + ["ordinary"] * 9,
            "revenue": list(range(40)),
        }
    )
    files = {"file": ("d.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


@pytest.mark.usefixtures("_require_llm_key")
def test_profile_route_returns_followups_and_is_privacy_safe(api_client, monkeypatch):
    from llm.providers import anthropic as provider_mod

    dataset_id = _upload_with_sentinel(api_client)

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

    r = api_client.get(f"/datasets/{dataset_id}/profile")
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    # Rich LOCAL profile is present.
    assert data["profile"]["row_count"] == 40
    assert data["profile"]["columns"]

    # 2-3 non-empty follow-up strings.
    followups = data["followups"]
    assert isinstance(followups, list)
    assert 2 <= len(followups) <= 3, followups
    assert all(isinstance(q, str) and q.strip() for q in followups)

    # Privacy: isolate the follow-up node's request and assert schema present,
    # sentinel absent.
    followup_reqs = [
        k for k in captured if "follow-up" in str(k.get("system", "")).lower()
    ]
    assert followup_reqs, "the follow-up node made no Anthropic request"
    for kwargs in followup_reqs:
        user_content = json.dumps(kwargs.get("messages", []), default=str)
        assert "region" in user_content        # real schema column present
        assert SENTINEL not in user_content     # raw-row sentinel absent

    # Defense in depth: no request in the whole call leaked the sentinel.
    for kwargs in captured:
        assert SENTINEL not in json.dumps(kwargs, default=str)
