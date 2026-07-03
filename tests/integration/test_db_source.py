"""Live SQL DB source (Phase 3): connect a local SQLite DB, ask a question,
and prove the agent generates read-only SQL that executes via pushdown, the
result matches a direct SQL computation, and a privacy spy shows only schema
(+ a bounded sample) ever reaches the LLM — never a non-sampled row value."""
from __future__ import annotations

import json
import sqlite3

import pytest


SENTINEL = "DB_SENTINEL_91ba"


def _seed_db(tmp_path):
    db_path = tmp_path / "orders.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT NOT NULL, revenue REAL NOT NULL, note TEXT)"
    )
    rows = []
    rid = 1
    for region, count in (("West", 15), ("East", 15)):
        for i in range(count):
            note = SENTINEL if rid == 20 else "ordinary"  # deep row, beyond any small sample
            rows.append((rid, region, float(rid * 10), note))
            rid += 1
    conn.executemany("INSERT INTO orders (id, region, revenue, note) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db_path, rows


@pytest.mark.usefixtures("_require_llm_key")
def test_db_source_pushdown_matches_direct_sql_and_never_leaks_raw_rows(api_client, tmp_path, monkeypatch):
    from graph.runner import run_analysis
    from llm.providers import anthropic as provider_mod

    db_path, rows = _seed_db(tmp_path)
    dsn = f"sqlite:///{db_path.as_posix()}"

    r = api_client.post("/connections", json={"name": "orders-db", "kind": "sqlite", "dsn": dsn})
    assert r.status_code == 200, r.text
    connection_id = r.json()["data"]["connection_id"]
    assert "dsn" not in r.json()["data"]  # only dsn_masked is ever returned (secret hygiene)

    # Direct SQL computation — the ground truth.
    conn = sqlite3.connect(db_path)
    expected = dict(conn.execute("SELECT region, SUM(revenue) FROM orders GROUP BY region").fetchall())
    conn.close()

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
        connection_id, "What is the total revenue by region?", source_ids=[connection_id]
    )
    assert result["status"] == "completed", result

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
    for total in expected.values():
        assert round(total, 2) in numbers, f"expected {total} in {numbers}"

    assert captured, "no Anthropic request captured"
    blob = json.dumps(captured, default=str)
    assert "region" in blob            # schema present
    assert SENTINEL not in blob        # raw non-sampled row value absent
    assert dsn not in blob             # DSN never sent to the LLM


@pytest.mark.usefixtures("_require_llm_key")
def test_generated_sql_is_read_only(api_client, tmp_path):
    from graph.runner import run_analysis

    db_path, _ = _seed_db(tmp_path)
    dsn = f"sqlite:///{db_path.as_posix()}"
    connection_id = api_client.post(
        "/connections", json={"name": "orders-db2", "kind": "sqlite", "dsn": dsn}
    ).json()["data"]["connection_id"]

    result = run_analysis(
        connection_id, "How many orders are there per region?", source_ids=[connection_id]
    )
    assert result["status"] == "completed", result
    code = result["generated_code"].lower()
    assert "select" in code
    for forbidden in ("insert", "update", "delete", "drop"):
        assert forbidden not in code


def test_connect_unreachable_or_bad_dialect_returns_bad_request(api_client):
    r = api_client.post("/connections", json={"name": "bad", "kind": "mongodb", "dsn": "mongodb://x"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"
