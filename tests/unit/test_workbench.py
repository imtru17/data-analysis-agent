"""Unit tests for the Phase-4 workbench: PK/FK detection helpers + the DuckDB
runner. Small in-memory fixtures, all LOCAL (no LLM, no network)."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from analysis import sql_query, store, workbench
from db.models import DatasetRow


def _persist(df: pd.DataFrame, filename: str, engine, session_id=None) -> str:
    """Save a CSV to the (isolated) store and insert its DatasetRow."""
    dataset_id = store.save(df.to_csv(index=False).encode("utf-8"), filename)
    with Session(engine) as s:
        s.add(
            DatasetRow(
                id=dataset_id,
                filename=filename,
                source_kind="csv",
                file_path=store.path(dataset_id).name,
                row_count=len(df),
                schema_json=json.dumps([{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns]),
                sample_rows_json=json.dumps([]),
                session_id=session_id,
            )
        )
        s.commit()
    return dataset_id


# ── PK/FK detection helpers ──────────────────────────────────────────────────

def test_pk_columns_flags_unique_non_null_only():
    df = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],           # unique + non-null → PK candidate
            "region": ["W", "E", "W", "E"],  # duplicates → not
            "opt": [1, None, 3, 4],       # has a null → not
        }
    )
    pk = workbench._pk_columns(df)
    assert "id" in pk
    assert "region" not in pk
    assert "opt" not in pk
    assert pk["id"] == frozenset({1, 2, 3, 4})


def test_distinct_set_drops_nulls_and_is_json_safe():
    s = pd.Series([1, 2, 2, None])
    assert workbench._distinct_set(s) == frozenset({1, 2})


def test_build_tiles_detects_pk_and_fk_subset(_isolated_db):
    engine = _isolated_db
    parent = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
    child = pd.DataFrame(
        {
            "order_id": [10, 11, 12, 13],       # unique + non-null → PK candidate
            "customer_id": [1, 2, 1, 3],        # subset of parent.id → FK
            "region": ["W", "E", "W", "E"],     # duplicates, not a subset of any PK
        }
    )
    parent_id = _persist(parent, "customers.csv", engine)
    child_id = _persist(child, "orders.csv", engine)

    with Session(engine) as session:
        tiles = workbench.build_tiles(child_id, session)

    assert tiles["row_count"] == 4
    cols = {c["name"]: c for c in tiles["columns"]}
    assert cols["order_id"]["is_pk_candidate"] is True
    assert cols["customer_id"]["is_pk_candidate"] is False

    fk = cols["customer_id"]["fk_candidates"]
    assert fk, "expected an FK candidate on customer_id"
    assert fk[0]["references_dataset_id"] == parent_id
    assert fk[0]["references_dataset_name"] == "customers.csv"
    assert fk[0]["references_column"] == "id"

    assert "order_id" in tiles["primary_key_candidates"]
    top = {c["column"]: c for c in tiles["foreign_key_candidates"]}
    assert "customer_id" in top
    assert top["customer_id"]["references_column"] == "id"


def test_build_tiles_no_fk_when_not_subset(_isolated_db):
    engine = _isolated_db
    parent = pd.DataFrame({"id": [1, 2, 3]})
    # values 7,8,9 are NOT a subset of parent.id → no FK candidate.
    child = pd.DataFrame({"ref": [7, 8, 9], "k": [1, 1, 2]})
    _persist(parent, "parent.csv", engine)
    child_id = _persist(child, "child.csv", engine)

    with Session(engine) as session:
        tiles = workbench.build_tiles(child_id, session)
    cols = {c["name"]: c for c in tiles["columns"]}
    assert cols["ref"]["fk_candidates"] == []


def test_column_values_top_counts(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"region": ["W"] * 5 + ["E"] * 3 + ["N"] * 2})
    dataset_id = _persist(df, "r.csv", engine)
    out = workbench.column_values(dataset_id, "region")
    assert out["total"] == 10
    assert out["values"][0] == {"value": "W", "count": 5}
    assert out["truncated"] is False


def test_column_values_unknown_column_raises(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"a": [1, 2]})
    dataset_id = _persist(df, "a.csv", engine)
    with pytest.raises(ValueError):
        workbench.column_values(dataset_id, "nope")


# ── DuckDB runner ────────────────────────────────────────────────────────────

def test_run_query_grouped_result(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"region": ["W", "E", "W", "W"], "rev": [1, 2, 3, 4]})
    dataset_id = _persist(df, "sales.csv", engine)
    out = sql_query.run_query(
        dataset_id,
        "SELECT region, SUM(rev) AS total FROM data GROUP BY region ORDER BY total DESC",
        display_cap=500,
        filename="sales.csv",
    )
    assert out["columns"] == ["region", "total"]
    assert out["row_count"] == 2
    assert out["truncated"] is False
    top = out["rows"][0]
    assert top["region"] == "W" and top["total"] == 8


def test_run_query_registers_filename_stem_view(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"x": [1, 2, 3]})
    dataset_id = _persist(df, "orders.csv", engine)
    out = sql_query.run_query(
        dataset_id, "SELECT COUNT(*) AS n FROM orders", display_cap=500, filename="orders.csv"
    )
    assert out["rows"][0]["n"] == 3


def test_run_query_truncates_over_cap(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"x": list(range(10))})
    dataset_id = _persist(df, "nums.csv", engine)
    out = sql_query.run_query(dataset_id, "SELECT * FROM data", display_cap=3, filename="nums.csv")
    assert out["row_count"] == 10
    assert len(out["rows"]) == 3
    assert out["truncated"] is True


def test_run_query_bad_sql_raises_typed_error(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"x": [1]})
    dataset_id = _persist(df, "x.csv", engine)
    with pytest.raises(sql_query.SqlQueryError):
        sql_query.run_query(dataset_id, "SELECT * FROM nope", display_cap=500, filename="x.csv")


def test_query_to_csv_full_result(_isolated_db):
    engine = _isolated_db
    df = pd.DataFrame({"x": list(range(10))})
    dataset_id = _persist(df, "nums.csv", engine)
    blob = sql_query.query_to_csv(dataset_id, "SELECT * FROM data", filename="nums.csv")
    text = blob.decode("utf-8")
    # header + 10 rows
    assert len(text.strip().splitlines()) == 11
