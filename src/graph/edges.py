"""Conditional edge routers for the analysis graph.

Routing is pure — these functions read state and return the next node name.
State mutation (retry_count increment, low_confidence) happens in the nodes.
"""
from __future__ import annotations

from config.settings import get_settings
from graph.nodes import is_chartable, is_trivial_question
from graph.state import AgentState


def entry_router(state: AgentState) -> str:
    """Fast path: trivial asks skip `plan`. Kept for back-compat; the graph's
    real entry point is now `select_sources` -> `after_select` (Phase 3)."""
    if is_trivial_question(state.get("question", ""), state.get("dataset_meta", {})):
        return "generate_code"
    return "plan"


def after_select(state: AgentState) -> str:
    """Phase-3 entry routing. Multi-source is never trivial; a single source
    still gets the fast-path check against its (now-resolved) dataset_meta."""
    if state.get("error"):
        return "handle_error"
    if state.get("is_multi_source"):
        return "plan"
    dataset_meta = state.get("dataset_meta") or {}
    if is_trivial_question(state.get("question", ""), dataset_meta):
        return "generate_code"
    return "plan"


def after_plan(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "generate_code"


def after_generate(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "execute_locally"


def after_execute(state: AgentState) -> str:
    # Only a file-load failure sets state["error"]; execution errors are
    # non-fatal and captured into execution_result for the refine loop.
    if state.get("error"):
        return "handle_error"
    return "verify"


def after_verify(state: AgentState) -> str:
    verification = state.get("verification") or {}
    exec_result = state.get("execution_result") or {}
    failed = (not verification.get("passed")) or bool(exec_result.get("error"))

    if not failed:
        return "answer"

    max_retries = get_settings().max_retries
    if state.get("retry_count", 0) < max_retries:
        return "generate_code"
    return "answer"


def after_answer(state: AgentState) -> str:
    """Conditionally route to the chart node.

    Charts when the request forced it (``want_chart``) or the result is
    naturally chartable; otherwise go straight to finalize."""
    if state.get("want_chart") or is_chartable(state):
        return "chart_spec"
    return "finalize"
