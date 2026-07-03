"""Persistent session store (Phase 3) — cross-day conversation + sources.

Message content is privacy-safe prose only (a user question or the agent's
own answer prose) — never raw rows or a DSN. See ``analysis.privacy`` for the
choke point that bounds what actually reaches the LLM from ``conversation``.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ConnectionRow, DatasetRow, SessionMessageRow, SessionRow


def create_session(session: Session, title: str | None = None) -> SessionRow:
    row = SessionRow(title=title or "New session")
    session.add(row)
    session.flush()
    return row


def get_or_create(session: Session, session_id: str | None) -> SessionRow:
    if session_id:
        row = session.get(SessionRow, session_id)
        if row is not None:
            return row
    return create_session(session)


def list_sessions(session: Session, limit: int = 50) -> list[dict]:
    rows = (
        session.execute(select(SessionRow).order_by(SessionRow.updated_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    out: list[dict] = []
    for r in rows:
        ds_count = len(
            session.execute(select(DatasetRow).where(DatasetRow.session_id == r.id)).scalars().all()
        )
        run_count = len(
            session.execute(
                select(SessionMessageRow).where(
                    SessionMessageRow.session_id == r.id, SessionMessageRow.role == "user"
                )
            )
            .scalars()
            .all()
        )
        out.append(
            {
                "session_id": r.id,
                "title": r.title,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "dataset_count": ds_count,
                "run_count": run_count,
            }
        )
    return out


def load_conversation(session: Session, session_id: str, memory_turns: int) -> list[dict]:
    rows = (
        session.execute(
            select(SessionMessageRow)
            .where(SessionMessageRow.session_id == session_id)
            .order_by(SessionMessageRow.created_at.asc())
        )
        .scalars()
        .all()
    )
    turns = [{"role": r.role, "content": r.content} for r in rows]
    return turns[-memory_turns * 2 :]


def append_message(
    session: Session, session_id: str, role: str, content: str, run_id: str | None = None
) -> None:
    session.add(SessionMessageRow(session_id=session_id, role=role, content=content, run_id=run_id))


def restore(session: Session, session_id: str) -> dict | None:
    row = session.get(SessionRow, session_id)
    if row is None:
        return None
    from analysis import annotations as ann_mod
    from analysis.db_source import mask_dsn

    datasets = session.execute(select(DatasetRow).where(DatasetRow.session_id == session_id)).scalars().all()
    connections = (
        session.execute(select(ConnectionRow).where(ConnectionRow.session_id == session_id)).scalars().all()
    )
    messages = (
        session.execute(
            select(SessionMessageRow)
            .where(SessionMessageRow.session_id == session_id)
            .order_by(SessionMessageRow.created_at.asc())
        )
        .scalars()
        .all()
    )
    source_ids = [d.id for d in datasets] + [c.id for c in connections]
    anns = ann_mod.list_for_sources(session, source_ids)

    return {
        "session_id": row.id,
        "title": row.title,
        "datasets": [
            {"dataset_id": d.id, "filename": d.filename, "row_count": d.row_count} for d in datasets
        ],
        "connections": [
            {"connection_id": c.id, "name": c.name, "kind": c.kind, "dsn_masked": mask_dsn(c.dsn)}
            for c in connections
        ],
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "run_id": m.run_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "annotations": anns,
    }
