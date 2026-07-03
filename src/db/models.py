from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Float, Integer, Text, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DatasetRow(Base):
    """Metadata for one uploaded dataset. Raw bytes live on disk under
    ./data/uploads/; this row stores only metadata + the schema/sample
    profile (exactly what the LLM is allowed to see)."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False, default="csv")
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    sample_rows_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Phase 2 — richer LOCAL profile (per-column stats) + LLM follow-up
    # suggestions. Both computed once and cached so they are not regenerated on
    # every profile fetch. profile_json is computed locally and NEVER sent to
    # the LLM; followups_json comes from a schema+samples-only LLM call.
    profile_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    followups_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class AnalysisRunRow(Base):
    """The audit trail — one row per completed/failed analysis run."""

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_trace_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 2 — optional Vega-Lite v5 chart spec (JSON) with bounded inline data.
    chart_spec_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 3 — the session this run belongs to + the selected source ids
    # (one for single-source; several for a multi-source join/compare).
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SessionRow(Base):
    """A persistent workspace (Phase 3). Owns datasets, connections, runs,
    messages, and annotations; survives restarts and across days."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New session")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SessionMessageRow(Base):
    """One persisted conversation turn (Phase 3). Content is privacy-safe prose
    only — a user question or the agent's own answer — never raw rows or a DSN."""

    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )


class ConnectionRow(Base):
    """A live SQL DB source (Phase 3). ``dsn`` holds credentials — it lives ONLY
    in this git-ignored SQLite DB, is never logged, never sent to the LLM, and is
    always masked in API responses. Cached schema/samples are LLM-visible."""

    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # postgresql|mysql|sqlite
    dsn: Mapped[str] = mapped_column(Text, nullable=False)
    schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_rows_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class ColumnAnnotationRow(Base):
    """User-authored business meaning for a column of a source (Phase 3).
    Privacy-safe text injected into the LLM context via the choke point.
    One annotation per (source_id, table_name, column) — PUT upserts."""

    __tablename__ = "column_annotations"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    column: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_now, onupdate=_now
    )
