"""Column annotations (Phase 3): set via the API, then assert the note flows
into the outbound LLM context through the privacy choke point. No LLM key
needed — the node's LLM client is faked to capture the exact prompt."""
from __future__ import annotations

import pandas as pd


def _upload(api_client) -> str:
    df = pd.DataFrame({"amt": [100, 200, 300], "region": ["West", "East", "North"]})
    files = {"file": ("d.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


def test_put_annotation_upserts_and_returns_note(api_client):
    dataset_id = _upload(api_client)

    r = api_client.put(
        f"/datasets/{dataset_id}/columns/amt/annotation",
        json={"note": "amt = net amount in paise"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["source_id"] == dataset_id
    assert data["column"] == "amt"
    assert data["note"] == "amt = net amount in paise"

    # Upsert — same (source, column) updates in place.
    r2 = api_client.put(
        f"/datasets/{dataset_id}/columns/amt/annotation",
        json={"note": "amt = net amount in cents (corrected)"},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["note"] == "amt = net amount in cents (corrected)"


def test_annotation_unknown_dataset_returns_404(api_client):
    r = api_client.put(
        "/datasets/does-not-exist/columns/amt/annotation", json={"note": "x"}
    )
    assert r.status_code == 404


def test_annotation_appears_in_outbound_llm_prompt(api_client, monkeypatch, _isolated_db):
    """Exercise the real generate_code node with a faked LLM client that
    captures the prompt; assert the annotation note is present."""
    from analysis import annotations as ann_mod
    from db.session import create_db_session
    from graph import nodes

    dataset_id = _upload(api_client)

    with create_db_session() as session:
        ann_mod.upsert(session, source_id=dataset_id, table_name=None, column="amt", note="amt = net amount in paise")
        annotations = ann_mod.list_for_sources(session, [dataset_id])

    captured = {}

    class FakeClient:
        def call_with_usage(self, prompt, *, system=None):
            captured["prompt"] = prompt
            return "```python\nresult = df['amt'].sum()\n```", {
                "prompt_tokens": 1,
                "completion_tokens": 1,
            }

    monkeypatch.setattr(nodes, "LLMClient", FakeClient)

    dataset_meta = {
        "dataset_id": dataset_id,
        "filename": "d.csv",
        "row_count": 3,
        "columns": [{"name": "amt", "dtype": "int64"}, {"name": "region", "dtype": "object"}],
        "sample_rows": [{"amt": 100, "region": "West"}],
    }
    state = {
        "run_id": "r1",
        "dataset_id": dataset_id,
        "question": "total amt",
        "dataset_meta": dataset_meta,
        "annotations": annotations,
    }
    out = nodes.generate_code(state)

    assert out.get("error") is None
    assert "amt = net amount in paise" in captured["prompt"]
