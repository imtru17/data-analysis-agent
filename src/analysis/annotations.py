"""Column annotation store (Phase 3) — user-authored business meaning.

One annotation per (source_id, table_name, column). Content is privacy-safe
prose that flows into the LLM context ONLY via ``analysis.privacy`` — this
module never touches an LLM."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import ColumnAnnotationRow


def upsert(
    session: Session, *, source_id: str, table_name: str | None, column: str, note: str
) -> ColumnAnnotationRow:
    stmt = select(ColumnAnnotationRow).where(
        ColumnAnnotationRow.source_id == source_id,
        ColumnAnnotationRow.table_name == table_name,
        ColumnAnnotationRow.column == column,
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        row = ColumnAnnotationRow(source_id=source_id, table_name=table_name, column=column, note=note)
        session.add(row)
    else:
        row.note = note
    session.flush()
    return row


def list_for_sources(session: Session, source_ids: list[str]) -> list[dict]:
    if not source_ids:
        return []
    stmt = select(ColumnAnnotationRow).where(ColumnAnnotationRow.source_id.in_(source_ids))
    rows = session.execute(stmt).scalars().all()
    return [
        {"source_id": r.source_id, "table_name": r.table_name, "column": r.column, "note": r.note}
        for r in rows
    ]
