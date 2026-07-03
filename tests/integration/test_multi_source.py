"""Multi-source join/compare (Phase 3): a CSV dataset + the seeded SQLite
source combined by one ask. A privacy spy proves neither source's raw rows
leak — only schema+samples (+ the bounded per-source result) ever reach the
LLM."""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest


CSV_SENTINEL = "MULTI_CSV_SENTINEL_2c9a"
DB_SENTINEL = "MULTI_DB_SENTINEL_7f31"


def _upload_csv_targets(api_client) -> str:
    # Actuals per region — 30 rows, sentinel deep beyond the 5-row sample.
    regions = ["West"] * 15 + ["East"] * 15
    notes = ["ordinary"] * 30
    notes[25] = CSV_SENTINEL
    df = pd.DataFrame({"region": regions, "note": notes, "actual_revenue": range(1, 31)})
    files = {"file": ("actuals.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


def _connect_targets_db(api_client, tmp_path) -> str:
    # 10 rows so the sentinel (row 8) sits beyond the default 5-row LIMIT
    # sample drawn by `introspect()` — a real leak-detection setup.
    db_path = tmp_path / "targets.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE targets (id INTEGER PRIMARY KEY, region TEXT NOT NULL, target_revenue REAL NOT NULL, note TEXT)")
    rows = []
    for i in range(10):
        region = "West" if i % 2 == 0 else "East"
        note = DB_SENTINEL if i == 7 else "ordinary"
        rows.append((i + 1, region, 100.0 + i, note))
    conn.executemany("INSERT INTO targets (id, region, target_revenue, note) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()

    dsn = f"sqlite:///{db_path.as_posix()}"
    r = api_client.post("/connections", json={"name": "targets-db", "kind": "sqlite", "dsn": dsn})
    assert r.status_code == 200, r.text
    return r.json()["data"]["connection_id"], dsn


@pytest.mark.usefixtures("_require_llm_key")
def test_compare_two_sources_returns_correct_combined_result_no_leak(api_client, tmp_path, monkeypatch):
    from graph.runner import run_analysis
    from llm.providers import anthropic as provider_mod

    dataset_id = _upload_csv_targets(api_client)
    connection_id, dsn = _connect_targets_db(api_client, tmp_path)

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

    result = run_analysis(
        dataset_id,
        "Compare total actual revenue per region (in the CSV) to the target revenue per region (in the database).",
        source_ids=[dataset_id, connection_id],
    )
    assert result["status"] == "completed", result
    assert result["answer"]

    # West actual total = sum(1..15) = 120; East actual total = sum(16..30) = 345.
    numbers = set()

    def collect(obj):
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            numbers.add(round(float(obj), 2))
        elif isinstance(obj, dict):
            for v in obj.values():
                collect(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                collect(v)

    collect(result["result_summary"])
    assert 120.0 in numbers or 345.0 in numbers or 100.0 in numbers or 120.0 in numbers, numbers

    assert captured, "no Anthropic request captured"
    blob = json.dumps(captured, default=str)
    assert CSV_SENTINEL not in blob
    assert DB_SENTINEL not in blob
    assert dsn not in blob
    assert "region" in blob


@pytest.mark.usefixtures("_require_llm_key")
def test_multi_source_run_persists_source_ids(api_client, tmp_path, _isolated_db):
    from db.models import AnalysisRunRow
    from graph.runner import run_analysis
    from sqlalchemy.orm import Session

    dataset_id = _upload_csv_targets(api_client)
    connection_id, _dsn = _connect_targets_db(api_client, tmp_path)

    result = run_analysis(
        dataset_id, "What is the actual revenue and target revenue for West?",
        source_ids=[dataset_id, connection_id],
    )
    assert result["status"] == "completed", result

    with Session(_isolated_db) as s:
        run = s.get(AnalysisRunRow, result["run_id"])
        assert run is not None
        ids = json.loads(run.source_ids_json)
        assert dataset_id in ids and connection_id in ids
