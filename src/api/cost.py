"""Cost / token accounting endpoint.

Per-query tokens + cost are recorded on every ``AnalysisRunRow`` from the real
Anthropic ``usage``. This endpoint aggregates today's spend (local calendar
date) across those rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import ok
from db.models import AnalysisRunRow
from db.session import get_session

router = APIRouter()


@router.get("/cost/today")
def cost_today(session: Session = Depends(get_session)) -> dict:
    """Sum tokens + cost for runs created today (local calendar date)."""
    # Local midnight today → the equivalent UTC window (created_at is stored in
    # UTC). Range-filter with ORM column expressions (dialect-safe).
    now_local = datetime.now().astimezone()
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    stmt = select(AnalysisRunRow).where(
        AnalysisRunRow.created_at >= start_utc,
        AnalysisRunRow.created_at < end_utc,
    )
    runs = session.execute(stmt).scalars().all()

    prompt_tokens = sum(int(r.prompt_tokens or 0) for r in runs)
    completion_tokens = sum(int(r.completion_tokens or 0) for r in runs)
    cost_usd = round(sum(float(r.cost_usd or 0.0) for r in runs), 6)

    return ok(
        {
            "date": start_local.date().isoformat(),
            "cost_usd": cost_usd,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "run_count": len(runs),
        }
    )
