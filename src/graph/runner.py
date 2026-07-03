"""Analysis runner — drives the LangGraph agent and streams SSE step events.

Creates an ``AnalysisRunRow`` (status ``running``) at start, streams a step
event per node advance, and finalizes the row (``completed``/``failed``) at the
end. Also exposes a non-streaming ``run_analysis`` helper for tests.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

from db.models import AnalysisRunRow, DatasetRow
from db.session import create_db_session
from graph.agent import agentic_ai
from graph.state import AgentState
from observability.llm_log import log_run

# node name → human label for the live trace
_STEP_LABELS = {
    "plan": "Planning",
    "generate_code": "Writing code",
    "execute_locally": "Running locally",
    "verify": "Verifying",
    "answer": "Answering",
    "chart_spec": "Charting",
}


class DatasetNotFound(Exception):
    pass


def _load_dataset_meta(dataset_id: str) -> dict:
    with create_db_session() as session:
        row = session.get(DatasetRow, dataset_id)
        if row is None:
            raise DatasetNotFound(dataset_id)
        return {
            "dataset_id": row.id,
            "filename": row.filename,
            "row_count": row.row_count,
            "columns": json.loads(row.schema_json),
            "sample_rows": json.loads(row.sample_rows_json),
        }


def _create_run_row(dataset_id: str, question: str) -> str:
    with create_db_session() as session:
        run = AnalysisRunRow(dataset_id=dataset_id, question=question, status="running")
        session.add(run)
        session.flush()
        return run.id


def _initial_state(
    run_id: str, dataset_id: str, question: str, dataset_meta: dict, want_chart: bool
) -> AgentState:
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "question": question,
        "dataset_meta": dataset_meta,
        "want_chart": want_chart,
        "retry_count": 0,
        "low_confidence": False,
        "step_trace": [],
        "tokens": {"prompt": 0, "completion": 0},
        "cost_usd": 0.0,
        "error": None,
        "status": "running",
    }


def _persist_final(run_id: str, state: AgentState) -> None:
    exec_result = state.get("execution_result") or {}
    tokens = state.get("tokens", {}) or {}
    with create_db_session() as session:
        run = session.get(AnalysisRunRow, run_id)
        if run is None:
            return
        run.plan = state.get("plan")
        run.generated_code = state.get("generated_code")
        summary = exec_result.get("result_summary")
        run.result_summary_json = json.dumps(summary) if summary is not None else None
        run.answer = state.get("answer")
        run.status = state.get("status", "completed")
        run.low_confidence = bool(state.get("low_confidence", False))
        run.retry_count = int(state.get("retry_count", 0))
        run.step_trace_json = json.dumps(state.get("step_trace", []))
        chart = state.get("chart_spec")
        run.chart_spec_json = json.dumps(chart) if chart is not None else None
        run.prompt_tokens = int(tokens.get("prompt", 0))
        run.completion_tokens = int(tokens.get("completion", 0))
        run.cost_usd = float(state.get("cost_usd", 0.0))
        run.error_message = state.get("error")


def _done_payload(run_id: str, state: AgentState) -> dict:
    exec_result = state.get("execution_result") or {}
    tokens = state.get("tokens", {}) or {}
    return {
        "run_id": run_id,
        "status": state.get("status", "completed"),
        "answer": state.get("answer", ""),
        "generated_code": state.get("generated_code", ""),
        "result_summary": exec_result.get("result_summary"),
        "chart_spec": state.get("chart_spec"),
        "step_trace": state.get("step_trace", []),
        "low_confidence": bool(state.get("low_confidence", False)),
        "tokens": {"prompt": tokens.get("prompt", 0), "completion": tokens.get("completion", 0)},
        "cost_usd": state.get("cost_usd", 0.0),
    }


def stream_analysis(
    dataset_id: str, question: str, want_chart: bool = False
) -> Iterator[dict]:
    """Yield SSE event dicts: {"event": "step"|"done"|"error", "data": {...}}.

    Raises ``DatasetNotFound`` before any event if the dataset is unknown, so
    the API can return a JSON 400 before the stream opens.
    """
    dataset_meta = _load_dataset_meta(dataset_id)   # may raise DatasetNotFound
    run_id = _create_run_row(dataset_id, question)
    initial = _initial_state(run_id, dataset_id, question, dataset_meta, want_chart)

    accumulated: AgentState = dict(initial)
    try:
        for update in agentic_ai.stream(initial, stream_mode="updates"):
            for node_name, delta in update.items():
                if not isinstance(delta, dict):
                    continue
                accumulated.update(delta)
                if node_name in _STEP_LABELS:
                    trace = delta.get("step_trace") or accumulated.get("step_trace") or []
                    last = trace[-1] if trace else {}
                    yield {
                        "event": "step",
                        "data": {
                            "run_id": run_id,
                            "step": node_name,
                            "label": _STEP_LABELS[node_name],
                            "status": last.get("status", "done"),
                            "detail": last.get("detail", ""),
                        },
                    }
    except Exception as exc:  # noqa: BLE001 — surface as terminal SSE error
        accumulated["status"] = "failed"
        accumulated["error"] = f"{type(exc).__name__}: {exc}"
        _persist_final(run_id, accumulated)
        log_run(run_id, status="failed", error=accumulated["error"])
        yield {"event": "error", "data": {"run_id": run_id, "message": accumulated["error"]}}
        return

    _persist_final(run_id, accumulated)
    log_run(
        run_id,
        status=accumulated.get("status"),
        low_confidence=accumulated.get("low_confidence", False),
        retry_count=accumulated.get("retry_count", 0),
        prompt_tokens=(accumulated.get("tokens") or {}).get("prompt", 0),
        completion_tokens=(accumulated.get("tokens") or {}).get("completion", 0),
        cost_usd=accumulated.get("cost_usd", 0.0),
    )

    if accumulated.get("status") == "failed" or accumulated.get("error"):
        yield {
            "event": "error",
            "data": {"run_id": run_id, "message": accumulated.get("error", "Analysis failed")},
        }
    else:
        yield {"event": "done", "data": _done_payload(run_id, accumulated)}


def run_analysis(dataset_id: str, question: str, want_chart: bool = False) -> dict:
    """Non-streaming helper (used by integration tests). Returns the terminal
    payload dict, with an extra ``run_id`` key."""
    terminal: dict = {}
    for event in stream_analysis(dataset_id, question, want_chart):
        if event["event"] in ("done", "error"):
            terminal = event["data"]
    return terminal
