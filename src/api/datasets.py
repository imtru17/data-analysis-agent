"""Dataset upload + profile endpoint. No LLM call here."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from analysis import store
from api._common import api_error, ok
from config.settings import get_settings
from db.models import DatasetRow
from db.session import get_session

router = APIRouter()


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(".csv"):
        raise api_error("BAD_REQUEST", "Only .csv files are supported in Phase 1.", 400)

    raw = await file.read()
    if not raw:
        raise api_error("BAD_REQUEST", "Uploaded file is empty.", 400)

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise api_error(
            "TOO_LARGE",
            f"File exceeds the {get_settings().max_upload_mb} MB limit.",
            413,
        )

    dataset_id = store.save(raw, filename)
    try:
        meta = store.profile(dataset_id, filename=filename)
    except Exception as exc:  # noqa: BLE001 — unparseable CSV
        # remove the saved file so no orphan/unparseable dataset lingers
        try:
            store.path(dataset_id).unlink(missing_ok=True)
        except OSError:
            pass
        raise api_error("BAD_REQUEST", f"Could not parse CSV: {exc}", 400)

    row = DatasetRow(
        id=dataset_id,
        filename=filename,
        source_kind="csv",
        file_path=f"{dataset_id}.csv",
        row_count=meta.row_count,
        schema_json=json.dumps([{"name": c.name, "dtype": c.dtype} for c in meta.columns]),
        sample_rows_json=json.dumps(meta.sample_rows, default=str),
    )
    session.add(row)

    return ok(meta.to_dict())
