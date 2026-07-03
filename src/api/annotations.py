"""Column annotation endpoints (Phase 3) — user-authored business meaning for
a file-dataset column or a DB-table column. Upserts; flows into the agent's
LLM context via the privacy choke point (schema+samples+annotations)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from analysis import annotations as ann_mod
from api._common import api_error, ok
from db.models import ConnectionRow, DatasetRow
from db.session import get_session

router = APIRouter()


class AnnotationBody(BaseModel):
    note: str


@router.put("/datasets/{dataset_id}/columns/{column}/annotation")
def annotate_dataset_column(
    dataset_id: str, column: str, body: AnnotationBody, session: Session = Depends(get_session)
) -> dict:
    ds = session.get(DatasetRow, dataset_id)
    if ds is None:
        raise api_error("NOT_FOUND", f"Dataset {dataset_id} not found", 404)
    row = ann_mod.upsert(session, source_id=dataset_id, table_name=None, column=column, note=body.note)
    return ok({"source_id": row.source_id, "table_name": row.table_name, "column": row.column, "note": row.note})


@router.put("/connections/{connection_id}/tables/{table}/columns/{column}/annotation")
def annotate_connection_column(
    connection_id: str,
    table: str,
    column: str,
    body: AnnotationBody,
    session: Session = Depends(get_session),
) -> dict:
    conn = session.get(ConnectionRow, connection_id)
    if conn is None:
        raise api_error("NOT_FOUND", f"Connection {connection_id} not found", 404)
    row = ann_mod.upsert(session, source_id=connection_id, table_name=table, column=column, note=body.note)
    return ok({"source_id": row.source_id, "table_name": row.table_name, "column": row.column, "note": row.note})
