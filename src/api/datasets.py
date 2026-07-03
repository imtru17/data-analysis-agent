"""Dataset upload + profile endpoints.

Upload profiles the CSV LOCALLY (rich per-column stats) and caches it. The
follow-up suggestions endpoint is the only place here that calls the LLM, and
it does so ONLY through the privacy choke point (schema + samples).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from analysis import profile as profile_mod
from analysis import store
from analysis.sources.loaders import SUPPORTED_KINDS, LoaderError, kind_for_filename
from api._common import api_error, ok
from config.settings import get_settings
from db.models import DatasetRow
from db.session import get_session

router = APIRouter()


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> dict:
    filename = file.filename or "upload.csv"
    kind = kind_for_filename(filename)
    if kind is None:
        raise api_error(
            "BAD_REQUEST",
            f"Unsupported file type. Supported: {', '.join(SUPPORTED_KINDS)}",
            400,
        )

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

    dataset_id = store.save(raw, filename, source_kind=kind)
    try:
        meta = store.profile(dataset_id, filename=filename)
    except LoaderError as exc:
        try:
            store.path(dataset_id).unlink(missing_ok=True)
        except OSError:
            pass
        raise api_error("BAD_REQUEST", str(exc), 400)
    except Exception as exc:  # noqa: BLE001 — unparseable file
        try:
            store.path(dataset_id).unlink(missing_ok=True)
        except OSError:
            pass
        raise api_error("BAD_REQUEST", f"Could not parse file: {exc}", 400)

    # Rich per-column profile — computed LOCALLY, cached, never sent to the LLM.
    try:
        rich_profile = profile_mod.compute_profile(dataset_id)
    except Exception:  # noqa: BLE001 — never block upload on profiling
        rich_profile = None

    row = DatasetRow(
        id=dataset_id,
        filename=filename,
        source_kind=kind,
        file_path=store.path(dataset_id).name,
        row_count=meta.row_count,
        schema_json=json.dumps([{"name": c.name, "dtype": c.dtype} for c in meta.columns]),
        sample_rows_json=json.dumps(meta.sample_rows, default=str),
        profile_json=json.dumps(rich_profile, default=str) if rich_profile else None,
        session_id=session_id,
    )
    session.add(row)

    return ok(meta.to_dict())


@router.get("/datasets/{dataset_id}/profile")
def get_dataset_profile(
    dataset_id: str,
    session: Session = Depends(get_session),
) -> dict:
    """Return the rich LOCAL profile + 2–3 LLM-suggested follow-up questions.

    Both are cached on the ``DatasetRow`` so they are not regenerated on every
    call. The follow-up LLM call routes through the privacy choke point and
    carries only schema + samples.
    """
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)

    # Rich profile — compute + cache if missing (e.g. legacy rows).
    if row.profile_json:
        rich_profile = json.loads(row.profile_json)
    else:
        try:
            rich_profile = profile_mod.compute_profile(dataset_id)
            row.profile_json = json.dumps(rich_profile, default=str)
        except Exception as exc:  # noqa: BLE001
            raise api_error("INTERNAL", f"Could not profile dataset: {exc}", 500)

    # Follow-ups — generate once via the LLM (privacy-safe), then cache.
    if row.followups_json:
        followups = json.loads(row.followups_json)
    else:
        dataset_meta = {
            "dataset_id": row.id,
            "filename": row.filename,
            "row_count": row.row_count,
            "columns": json.loads(row.schema_json),
            "sample_rows": json.loads(row.sample_rows_json),
        }
        followups, _usage = profile_mod.suggest_followups(dataset_meta, run_id=dataset_id)
        if followups:
            row.followups_json = json.dumps(followups)

    return ok({"profile": rich_profile, "followups": followups})
