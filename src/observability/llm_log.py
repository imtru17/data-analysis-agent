"""Structured LLM-call + run observability.

structlog to stdout (day one). LangSmith tracing is a no-op unless
``LANGCHAIN_TRACING_V2`` is set in the environment (the langgraph/langchain
runtime picks that up automatically; we do not force it here).
"""
from __future__ import annotations

import time
from contextlib import contextmanager

from observability.events import get_logger

_log = get_logger("analysis")

# Rough Anthropic Claude Sonnet pricing (USD per token). Recorded in Phase 1,
# displayed in Phase 2. Adjust if the model changes.
_PROMPT_USD_PER_TOKEN = 3.0 / 1_000_000
_COMPLETION_USD_PER_TOKEN = 15.0 / 1_000_000


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        prompt_tokens * _PROMPT_USD_PER_TOKEN
        + completion_tokens * _COMPLETION_USD_PER_TOKEN,
        6,
    )


@contextmanager
def timed_llm_call(node: str, run_id: str):
    """Time an LLM call and log its usage. Yields a mutable dict the caller
    fills with token usage; latency + tokens are logged on exit."""
    started = time.perf_counter()
    usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}
    error: str | None = None
    try:
        yield usage
    except Exception as exc:  # noqa: BLE001 — log then re-raise
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        _log.info(
            "llm_call",
            node=node,
            run_id=run_id,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            error=error,
        )


def log_run(run_id: str, **fields) -> None:
    _log.info("analysis_run", run_id=run_id, **fields)
