"""Live SQL DB connection endpoints (Phase 3).

The raw DSN is stored ONLY in the local SQLite DB (never logged, never sent
to the LLM) and is NEVER echoed back — every response carries ``dsn_masked``.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from analysis.db_source import SUPPORTED_DIALECTS, DbSourceError, dialect_of, introspect, mask_dsn
from api._common import api_error, ok
from db.models import ConnectionRow
from db.session import get_session

router = APIRouter()


class ConnectionCreate(BaseModel):
    name: str = Field(default="connection")
    kind: str
    dsn: SecretStr
    session_id: str | None = None


@router.post("/connections")
def create_connection(req: ConnectionCreate, session: Session = Depends(get_session)) -> dict:
    dialect = dialect_of(req.dsn.get_secret_value())
    if req.kind not in SUPPORTED_DIALECTS or dialect not in SUPPORTED_DIALECTS:
        raise api_error(
            "BAD_REQUEST",
            f"Unsupported or unrecognised DB dialect. Supported: {', '.join(SUPPORTED_DIALECTS)}",
            400,
        )

    try:
        meta = introspect(req.dsn)
    except DbSourceError as exc:
        raise api_error("BAD_REQUEST", str(exc), 400)

    row = ConnectionRow(
        name=req.name,
        kind=req.kind,
        dsn=req.dsn.get_secret_value(),
        schema_json=json.dumps(meta),
        sample_rows_json=None,
        session_id=req.session_id,
    )
    session.add(row)
    session.flush()

    tables_public = [{"table": t["table"], "columns": t["columns"]} for t in meta.get("tables", [])]
    return ok(
        {
            "connection_id": row.id,
            "name": row.name,
            "kind": row.kind,
            "dsn_masked": mask_dsn(row.dsn),
            "tables": tables_public,
        }
    )


@router.get("/connections")
def list_connections(session: Session = Depends(get_session)) -> dict:
    rows = session.execute(select(ConnectionRow).order_by(ConnectionRow.created_at.desc())).scalars().all()
    return ok(
        [
            {
                "connection_id": r.id,
                "name": r.name,
                "kind": r.kind,
                "dsn_masked": mask_dsn(r.dsn),
                "session_id": r.session_id,
            }
            for r in rows
        ]
    )
