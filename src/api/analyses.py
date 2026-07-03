"""Analysis endpoints: SSE streaming ask + run history (audit trail)."""
from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api._common import api_error, ok
from db.models import AnalysisRunRow, DatasetRow
from db.session import get_session
from domain.analysis import AnalyzeRequest, RunDetail, RunListItem, RunTokens
from graph.runner import stream_analysis

router = APIRouter()


def _sse_frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/analyses")
def create_analysis(req: AnalyzeRequest, session: Session = Depends(get_session)):
    if not req.question.strip():
        raise api_error("BAD_REQUEST", "Question must not be empty.", 400)
    if session.get(DatasetRow, req.dataset_id) is None:
        raise api_error("BAD_REQUEST", f"Unknown dataset_id: {req.dataset_id}", 400)

    def event_stream() -> Iterator[str]:
        try:
            for event in stream_analysis(req.dataset_id, req.question):
                yield _sse_frame(event["event"], event["data"])
        except Exception as exc:  # noqa: BLE001 — never hang; emit terminal error
            yield _sse_frame("error", {"run_id": None, "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _to_detail(run: AnalysisRunRow) -> dict:
    return RunDetail(
        run_id=run.id,
        dataset_id=run.dataset_id,
        question=run.question,
        generated_code=run.generated_code,
        plan=run.plan,
        result_summary=json.loads(run.result_summary_json) if run.result_summary_json else None,
        answer=run.answer,
        status=run.status,
        low_confidence=run.low_confidence,
        retry_count=run.retry_count,
        tokens=RunTokens(prompt=run.prompt_tokens, completion=run.completion_tokens),
        cost_usd=run.cost_usd,
        step_trace=json.loads(run.step_trace_json) if run.step_trace_json else [],
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else None,
    ).model_dump()


@router.get("/analyses/{run_id}")
def get_analysis(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.get(AnalysisRunRow, run_id)
    if run is None:
        raise api_error("NOT_FOUND", f"Run {run_id} not found", 404)
    return ok(_to_detail(run))


@router.get("/analyses")
def list_analyses(
    dataset_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    stmt = select(AnalysisRunRow).order_by(AnalysisRunRow.created_at.desc()).limit(limit)
    if dataset_id:
        stmt = stmt.where(AnalysisRunRow.dataset_id == dataset_id)
    runs = session.execute(stmt).scalars().all()
    items = [
        RunListItem(
            run_id=r.id,
            dataset_id=r.dataset_id,
            question=r.question,
            status=r.status,
            created_at=r.created_at.isoformat() if r.created_at else None,
        ).model_dump()
        for r in runs
    ]
    return ok(items)
