"""Phase-4 GATE — data workbench end-to-end via the real HTTP API.

Uploads two RELATED CSVs through the real ``POST /datasets`` (a parent with a
unique non-null ``id`` and a child whose ``customer_id`` is a subset of it), each
with more rows than ``AGENT_SAMPLE_ROWS`` so a sampled answer would differ from
the full-data profile. Everything here is LOCAL — no LLM, no network.
"""
from __future__ import annotations

import pandas as pd
import pytest


# Parent: 50 unique, non-null ids (> the 5-row sample).
def _parent_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": list(range(1, 51)),
            "tier": ["gold", "silver"] * 25,  # duplicates → not a PK candidate
        }
    )


# Child: 600 rows. order_id is unique+non-null (PK); customer_id ⊂ parent.id (FK);
# region has duplicates; note has nulls.
def _child_df() -> pd.DataFrame:
    n = 600
    return pd.DataFrame(
        {
            "order_id": list(range(1, n + 1)),
            "customer_id": [(i % 50) + 1 for i in range(n)],
            "region": ["W" if i % 2 == 0 else "E" for i in range(n)],
            "note": [None if i % 7 == 0 else "x" for i in range(n)],
        }
    )


def _upload(api_client, df: pd.DataFrame, name: str) -> str:
    files = {"file": (name, df.to_csv(index=False).encode("utf-8"), "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    return r.json()["data"]["dataset_id"]


def test_workbench_end_to_end(api_client):
    parent_df, child_df = _parent_df(), _child_df()
    parent_id = _upload(api_client, parent_df, "customers.csv")
    child_id = _upload(api_client, child_df, "orders.csv")

    # ── Tiles: full-data row count + per-column distinct/null_count ──────────
    r = api_client.get(f"/datasets/{child_id}/tiles")
    assert r.status_code == 200, r.text
    tiles = r.json()["data"]
    assert tiles["row_count"] == 600  # full data, not the 5-row sample

    cols = {c["name"]: c for c in tiles["columns"]}
    for name in child_df.columns:
        assert cols[name]["distinct"] == int(child_df[name].nunique(dropna=True))
        assert cols[name]["null_count"] == int(child_df[name].isna().sum())

    # PK candidate: unique + non-null; not for duplicated / nullable columns.
    assert cols["order_id"]["is_pk_candidate"] is True
    assert cols["customer_id"]["is_pk_candidate"] is False
    assert cols["region"]["is_pk_candidate"] is False
    assert cols["note"]["is_pk_candidate"] is False
    assert "order_id" in tiles["primary_key_candidates"]

    # FK candidate: customer_id ⊂ customers.id.
    fk = cols["customer_id"]["fk_candidates"]
    assert fk, "expected an FK candidate on customer_id"
    assert fk[0]["references_dataset_id"] == parent_id
    assert fk[0]["references_dataset_name"] == "customers.csv"
    assert fk[0]["references_column"] == "id"

    top_fk = {c["column"]: c for c in tiles["foreign_key_candidates"]}
    assert top_fk["customer_id"]["references_dataset_id"] == parent_id
    assert top_fk["customer_id"]["references_column"] == "id"

    # ── Column drill-in: top values + counts over the full data ─────────────
    r = api_client.get(f"/datasets/{child_id}/columns/region/values")
    assert r.status_code == 200, r.text
    vals = r.json()["data"]
    assert vals["total"] == 600
    counts = {v["value"]: v["count"] for v in vals["values"]}
    assert counts == {"W": 300, "E": 300}
    assert vals["truncated"] is False

    # Unknown column → 400 BAD_REQUEST.
    r = api_client.get(f"/datasets/{child_id}/columns/nope/values")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"

    # ── SQL query: grouped result ───────────────────────────────────────────
    r = api_client.post(
        f"/datasets/{child_id}/query",
        json={"sql": "SELECT customer_id, COUNT(*) AS n FROM data GROUP BY customer_id ORDER BY customer_id"},
    )
    assert r.status_code == 200, r.text
    q = r.json()["data"]
    assert q["columns"] == ["customer_id", "n"]
    assert q["row_count"] == 50
    assert q["truncated"] is False
    # each of the 50 customers appears exactly 12 times (600 / 50).
    assert all(row["n"] == 12 for row in q["rows"])

    # ── Over-cap query → truncated (default display cap is 500) ──────────────
    r = api_client.post(f"/datasets/{child_id}/query", json={"sql": "SELECT * FROM data"})
    assert r.status_code == 200, r.text
    q = r.json()["data"]
    assert q["row_count"] == 600
    assert len(q["rows"]) == 500
    assert q["truncated"] is True

    # ── Malformed SQL → 400, NOT 500, with a friendly message ───────────────
    r = api_client.post(f"/datasets/{child_id}/query", json={"sql": "SELECT * FROM nope"})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "BAD_REQUEST"
    assert r.json()["detail"]["message"]  # non-empty friendly message

    # ── Download: full (uncapped) result as a text/csv attachment ───────────
    sql = "SELECT * FROM data WHERE customer_id = 1"
    r = api_client.post(f"/datasets/{child_id}/query/download", json={"sql": sql})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert f"query_{child_id[:8]}.csv" in r.headers["content-disposition"]
    body_rows = r.text.strip().splitlines()
    # header + 12 matching rows (customers 1 appears 12 times).
    assert len(body_rows) == 13

    # Cross-check the download row count against the unbounded query row_count.
    r2 = api_client.post(f"/datasets/{child_id}/query", json={"sql": sql})
    assert r2.json()["data"]["row_count"] == len(body_rows) - 1


def test_tiles_unknown_dataset_404(api_client):
    r = api_client.get("/datasets/does-not-exist/tiles")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"


def test_query_unknown_dataset_404(api_client):
    r = api_client.post("/datasets/nope/query", json={"sql": "SELECT 1"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "NOT_FOUND"
