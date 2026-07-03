"""Persistent session endpoints (Phase 3) — create/list/restore a workspace."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from analysis import sessions as sessions_mod
from api._common import api_error, ok
from db.session import get_session

router = APIRouter()


class SessionCreate(BaseModel):
    title: str | None = None


@router.get("/sessions")
def list_sessions_ep(session: Session = Depends(get_session)) -> dict:
    return ok(sessions_mod.list_sessions(session))


@router.post("/sessions")
def create_session_ep(req: SessionCreate, session: Session = Depends(get_session)) -> dict:
    row = sessions_mod.create_session(session, req.title)
    return ok({"session_id": row.id, "title": row.title})


@router.get("/sessions/{session_id}")
def get_session_ep(session_id: str, session: Session = Depends(get_session)) -> dict:
    data = sessions_mod.restore(session, session_id)
    if data is None:
        raise api_error("NOT_FOUND", f"Session {session_id} not found", 404)
    return ok(data)
