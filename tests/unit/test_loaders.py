"""Non-CSV file loaders (Phase 3): Excel/JSON/Parquet/log produce the right
schema + bounded sample; a no-clean-table file degrades to a friendly error
(mapped to 400 BAD_REQUEST at the API), never a crash."""
from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from analysis.sources import loaders


def test_kind_for_filename():
    assert loaders.kind_for_filename("a.csv") == "csv"
    assert loaders.kind_for_filename("a.xlsx") == "excel"
    assert loaders.kind_for_filename("a.json") == "json"
    assert loaders.kind_for_filename("a.parquet") == "parquet"
    assert loaders.kind_for_filename("a.pdf") == "pdf"
    assert loaders.kind_for_filename("a.log") == "log"
    assert loaders.kind_for_filename("a.exe") is None


def test_load_excel(tmp_path):
    df = pd.DataFrame({"region": ["West", "East"], "revenue": [100.0, 200.0]})
    path = tmp_path / "d.xlsx"
    df.to_excel(path, index=False)

    loaded = loaders.load_dataframe(path, "excel")
    assert list(loaded.columns) == ["region", "revenue"]
    assert len(loaded) == 2


def test_load_json_records(tmp_path):
    records = [{"name": "Ann", "age": 30}, {"name": "Bo", "age": 40}]
    path = tmp_path / "d.json"
    path.write_text(json.dumps(records), encoding="utf-8")

    loaded = loaders.load_dataframe(path, "json")
    assert set(loaded.columns) == {"name", "age"}
    assert len(loaded) == 2


def test_load_parquet(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = tmp_path / "d.parquet"
    df.to_parquet(path)

    loaded = loaders.load_dataframe(path, "parquet")
    assert list(loaded.columns) == ["a", "b"]
    assert len(loaded) == 3


def test_load_log_text(tmp_path):
    path = tmp_path / "d.log"
    path.write_text("line one\nline two\nline three\n", encoding="utf-8")

    loaded = loaders.load_dataframe(path, "log")
    assert list(loaded.columns) == ["line"]
    assert len(loaded) == 3


def test_empty_log_raises_loader_error(tmp_path):
    path = tmp_path / "empty.log"
    path.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(loaders.LoaderError):
        loaders.load_dataframe(path, "log")


def test_pdf_with_no_table_degrades_to_loader_error(tmp_path):
    """A PDF with no extractable table must raise LoaderError (-> friendly 400),
    never crash the process."""
    pdfplumber = pytest.importorskip("pdfplumber")
    fitz_check = pytest.importorskip("pypdfium2")  # noqa: F841 — confirms pdf deps installed

    # Build a minimal single-page PDF with only free text (no table) using
    # reportlab-free raw PDF bytes is fragile; instead assert the loader path
    # for a PDF with no table by constructing one via pdfplumber's own writer
    # is unavailable, so we simulate the "no table found" contract directly:
    # any file that yields an empty extract_table() result must raise.
    # A tiny valid, table-less single-page PDF (hand-built minimal PDF bytes).
    minimal_pdf = (
        b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    path = tmp_path / "no_table.pdf"
    path.write_bytes(minimal_pdf)

    with pytest.raises(loaders.LoaderError):
        loaders.load_dataframe(path, "pdf")


def test_unsupported_kind_raises_loader_error(tmp_path):
    path = tmp_path / "x.bin"
    path.write_bytes(b"\x00\x01")
    with pytest.raises(loaders.LoaderError):
        loaders.load_dataframe(path, "bogus")


def test_upload_non_csv_via_api_produces_correct_profile(api_client):
    """Excel upload through the real API dispatches to the loader and returns
    the same profile shape as CSV — schema + bounded sample rows."""
    df = pd.DataFrame({"city": ["NYC", "LA", "SF"], "pop": [8, 4, 1]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)

    r = api_client.post(
        "/datasets",
        files={"file": ("cities.xlsx", buf.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["row_count"] == 3
    names = {c["name"] for c in data["columns"]}
    assert {"city", "pop"} <= names
    assert len(data["sample_rows"]) <= 5


def test_upload_no_table_pdf_returns_bad_request(api_client):
    minimal_pdf = (
        b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    r = api_client.post("/datasets", files={"file": ("no_table.pdf", minimal_pdf, "application/pdf")})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_upload_unsupported_extension_returns_bad_request(api_client):
    r = api_client.post("/datasets", files={"file": ("x.exe", b"\x00\x01", "application/octet-stream")})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"
