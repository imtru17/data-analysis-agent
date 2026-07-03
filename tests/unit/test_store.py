"""Dataset store — save -> profile -> load_df round trip. No LLM key needed."""
import pandas as pd

from analysis import store


def _csv_bytes(n_rows: int) -> bytes:
    df = pd.DataFrame(
        {
            "region": ["West", "East", "North", "South"] * n_rows,
            "revenue": [100.0, 200.0, 300.0, 400.0] * n_rows,
        }
    )
    return df.to_csv(index=False).encode("utf-8")


def test_save_then_load_df_round_trip():
    dataset_id = store.save(_csv_bytes(3), "sales.csv")

    df = store.load_df(dataset_id)

    assert list(df.columns) == ["region", "revenue"]
    assert len(df) == 12
    assert store.path(dataset_id).exists()


def test_profile_reports_schema_and_row_count():
    dataset_id = store.save(_csv_bytes(5), "sales.csv")

    meta = store.profile(dataset_id, filename="sales.csv")

    assert meta.row_count == 20
    assert [c.name for c in meta.columns] == ["region", "revenue"]
    assert meta.columns[1].dtype.startswith("float")


def test_profile_sample_rows_bounded_to_setting():
    from config.settings import get_settings

    dataset_id = store.save(_csv_bytes(10), "sales.csv")

    meta = store.profile(dataset_id)

    assert len(meta.sample_rows) <= get_settings().sample_rows
    assert len(meta.sample_rows) == get_settings().sample_rows  # 40 rows > cap


def test_profile_caps_wide_cell(monkeypatch):
    monkeypatch.setenv("AGENT_SAMPLE_CELL_CHARS", "10")
    import config.settings as m
    m._settings = None

    big = "x" * 500
    df = pd.DataFrame({"note": [big, "small"]})
    dataset_id = store.save(df.to_csv(index=False).encode("utf-8"), "notes.csv")

    meta = store.profile(dataset_id)

    assert len(str(meta.sample_rows[0]["note"])) <= 12  # 10 + ellipsis
    assert big not in str(meta.sample_rows[0]["note"])
