"""API contract tests — no LLM key required (graph is not invoked)."""
import io

import pandas as pd


def _csv_upload(client, n_rows: int = 4):
    df = pd.DataFrame({"region": ["W", "E"] * n_rows, "revenue": [10.0, 20.0] * n_rows})
    files = {"file": ("sales.csv", df.to_csv(index=False).encode("utf-8"), "text/csv")}
    return client.post("/datasets", files=files)


def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_upload_csv_returns_profile(api_client):
    r = _csv_upload(api_client, n_rows=3)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["row_count"] == 6
    assert [c["name"] for c in data["columns"]] == ["region", "revenue"]
    assert len(data["sample_rows"]) <= 5
    assert data["dataset_id"]


def test_upload_unsupported_extension_rejected(api_client):
    # Phase 3 supports .csv/.xlsx/.json/.parquet/.pdf/.log/.txt (see
    # tests/unit/test_loaders.py for the non-CSV formats); an extension with
    # no matching loader is still rejected.
    files = {"file": ("notes.exe", b"hello", "application/octet-stream")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_upload_txt_log_accepted_as_log_source(api_client):
    files = {"file": ("notes.txt", b"line one\nline two\n", "text/plain")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["row_count"] == 2


def test_upload_empty_file_rejected(api_client):
    files = {"file": ("empty.csv", b"", "text/csv")}
    r = api_client.post("/datasets", files=files)
    assert r.status_code == 400


def test_analyses_unknown_dataset_rejected(api_client):
    r = api_client.post("/analyses", json={"dataset_id": "nope", "question": "hi"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_REQUEST"


def test_analyses_empty_question_rejected(api_client):
    r = api_client.post("/analyses", json={"dataset_id": "x", "question": ""})
    assert r.status_code == 422  # pydantic min_length


def test_get_analysis_not_found(api_client):
    r = api_client.get("/analyses/does-not-exist")
    assert r.status_code == 404


def test_list_analyses_empty(api_client):
    r = api_client.get("/analyses")
    assert r.status_code == 200
    assert r.json()["data"] == []
