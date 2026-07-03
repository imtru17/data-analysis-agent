"""Phase 4 — data workbench endpoints (LOCAL only, no LLM, no network).

Four deterministic endpoints over a dataset's DataFrame:

- ``GET  /datasets/{id}/tiles``                 — profile tiles + PK/FK candidates
- ``GET  /datasets/{id}/columns/{col}/values``  — per-column value-counts drill-in
- ``POST /datasets/{id}/query``                 — bounded DuckDB SQL result table
- ``POST /datasets/{id}/query/download``        — full result as a CSV attachment

Every handler reads the dataset in-process; nothing reaches the LLM or the
network. Any SQL / unknown-column / unreadable-file error becomes a friendly
400 ``BAD_REQUEST`` — never a 500 / stack trace.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from analysis import sql_query, workbench
from api._common import api_error, ok
from config.settings import get_settings
from db.models import DatasetRow
from db.session import get_session

router = APIRouter()


class QueryBody(BaseModel):
    sql: str


def _require_dataset(dataset_id: str, session: Session) -> DatasetRow:
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)
    return row


@router.get("/datasets/{dataset_id}/tiles")
def get_tiles(dataset_id: str, session: Session = Depends(get_session)) -> dict:
    _require_dataset(dataset_id, session)
    try:
        tiles = workbench.build_tiles(dataset_id, session)
    except FileNotFoundError as exc:
        raise api_error("BAD_REQUEST", f"Dataset file is unreadable: {exc}", 400)
    except Exception as exc:  # noqa: BLE001 — unreadable/unparseable file
        raise api_error("BAD_REQUEST", f"Could not profile dataset: {exc}", 400)
    return ok(tiles)


@router.get("/datasets/{dataset_id}/columns/{col}/values")
def get_column_values(
    dataset_id: str, col: str, session: Session = Depends(get_session)
) -> dict:
    _require_dataset(dataset_id, session)
    try:
        values = workbench.column_values(dataset_id, col)
    except ValueError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400)
    except FileNotFoundError as exc:
        raise api_error("BAD_REQUEST", f"Dataset file is unreadable: {exc}", 400)
    return ok(values)


@router.post("/datasets/{dataset_id}/query")
def run_query(
    dataset_id: str, body: QueryBody, session: Session = Depends(get_session)
) -> dict:
    row = _require_dataset(dataset_id, session)
    cap = get_settings().workbench_display_rows
    try:
        result = sql_query.run_query(dataset_id, body.sql, cap, filename=row.filename)
    except sql_query.SqlQueryError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400)
    except FileNotFoundError as exc:
        raise api_error("BAD_REQUEST", f"Dataset file is unreadable: {exc}", 400)
    return ok(result)


@router.post("/datasets/{dataset_id}/query/download")
def download_query(
    dataset_id: str, body: QueryBody, session: Session = Depends(get_session)
):
    row = _require_dataset(dataset_id, session)
    try:
        content = sql_query.query_to_csv(dataset_id, body.sql, filename=row.filename)
    except sql_query.SqlQueryError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400)
    except FileNotFoundError as exc:
        raise api_error("BAD_REQUEST", f"Dataset file is unreadable: {exc}", 400)

    filename = f"query_{dataset_id[:8]}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
