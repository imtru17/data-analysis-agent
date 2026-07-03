"""Phase 2 — export builders + /analyses/{id}/export route.

No LLM key needed: exports RE-EXECUTE a run's stored ``generated_code`` locally
against the FULL dataset. Asserts csv/parquet round-trip to the full derived
result (not the bounded summary), code bytes are exact, and the report is HTML
containing the answer (plus a vega-embed script when a chart exists).
"""
import io
import json

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from analysis import store
from db.models import AnalysisRunRow, DatasetRow

# 60 rows across 3 regions → a grouped result of exactly 3 rows.
_REGIONS = ["West"] * 20 + ["East"] * 20 + ["North"] * 20
_GENERATED_CODE = "result = df.groupby('region')['revenue'].sum().reset_index()"
_ANSWER = "Revenue totals differ by region, with North the highest."


def _seed_run(engine, chart_spec: dict | None = None) -> str:
    """Save a real dataset file + a completed AnalysisRunRow, return run_id."""
    df = pd.DataFrame({"region": _REGIONS, "revenue": list(range(1, 61))})
    dataset_id = store.save(df.to_csv(index=False).encode("utf-8"), "sales.csv")

    with Session(engine) as s:
        s.add(
            DatasetRow(
                id=dataset_id,
                filename="sales.csv",
                source_kind="csv",
                file_path=f"{dataset_id}.csv",
                row_count=60,
                schema_json=json.dumps(
                    [{"name": "region", "dtype": "object"}, {"name": "revenue", "dtype": "int64"}]
                ),
                sample_rows_json=json.dumps([]),
            )
        )
        run = AnalysisRunRow(
            dataset_id=dataset_id,
            question="Total revenue by region?",
            generated_code=_GENERATED_CODE,
            answer=_ANSWER,
            status="completed",
            result_summary_json=json.dumps(
                {
                    "kind": "dataframe",
                    "shape": [3, 2],
                    "columns": ["region", "revenue"],
                    "rows": [
                        {"region": "West", "revenue": 210},
                        {"region": "East", "revenue": 610},
                        {"region": "North", "revenue": 1010},
                    ],
                    "truncated": False,
                }
            ),
            chart_spec_json=json.dumps(chart_spec) if chart_spec else None,
        )
        s.add(run)
        s.commit()
        return run.id


def test_csv_export_reexecutes_to_full_derived_result(api_client, _isolated_db):
    run_id = _seed_run(_isolated_db)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")

    frame = pd.read_csv(io.BytesIO(r.content))
    assert list(frame.columns) == ["region", "revenue"]
    assert frame.shape == (3, 2)  # the full grouped result, not a bounded summary
    totals = dict(zip(frame["region"], frame["revenue"]))
    assert totals == {"West": 210, "East": 610, "North": 1010}


def test_parquet_export_reexecutes_and_round_trips(api_client, _isolated_db):
    run_id = _seed_run(_isolated_db)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "parquet"})
    assert r.status_code == 200, r.text

    frame = pd.read_parquet(io.BytesIO(r.content))  # requires pyarrow
    assert list(frame.columns) == ["region", "revenue"]
    assert frame.shape == (3, 2)
    totals = dict(zip(frame["region"], frame["revenue"]))
    assert totals == {"West": 210, "East": 610, "North": 1010}


def test_code_export_bytes_equal_generated_code(api_client, _isolated_db):
    run_id = _seed_run(_isolated_db)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "code"})
    assert r.status_code == 200, r.text
    assert r.content == _GENERATED_CODE.encode("utf-8")


def test_report_export_is_html_with_answer(api_client, _isolated_db):
    run_id = _seed_run(_isolated_db)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "report"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    body = r.content.decode("utf-8")
    assert body.strip()
    assert "differ by region" in body      # the answer text is present
    assert "vega-embed" not in body        # no chart → no embed script


def test_report_export_embeds_chart_when_present(api_client, _isolated_db):
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "mark": "bar",
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"},
        },
        "data": {"values": [{"region": "West", "revenue": 210}]},
    }
    run_id = _seed_run(_isolated_db, chart_spec=spec)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "report"})
    assert r.status_code == 200, r.text
    body = r.content.decode("utf-8")
    assert "vega-embed" in body
    assert "vegaEmbed" in body
    assert "region" in body


def test_export_rejects_unknown_kind(api_client, _isolated_db):
    run_id = _seed_run(_isolated_db)
    r = api_client.get(f"/analyses/{run_id}/export", params={"kind": "xml"})
    assert r.status_code == 400, r.text


def test_export_missing_run_is_404(api_client, _isolated_db):
    r = api_client.get("/analyses/does-not-exist/export", params={"kind": "csv"})
    assert r.status_code == 404, r.text


def test_export_module_result_to_frame_shapes():
    """The result_to_frame coercion handles the derived-result kinds directly."""
    from analysis import export as export_mod

    df_in = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert export_mod.result_to_frame(df_in).shape == (2, 2)

    series = pd.Series([10, 20], index=["x", "y"], name="v")
    frame = export_mod.result_to_frame(series)
    assert "v" in frame.columns and len(frame) == 2

    scalar_frame = export_mod.result_to_frame(42)
    assert scalar_frame.iloc[0, 0] == 42
