"""Phase 2 — richer LOCAL profiling + privacy-safe follow-up suggestions.

Two clearly-separated concerns:

1. ``compute_profile`` builds a RICH per-column statistical profile from the
   FULL DataFrame — null counts, distinct counts, numeric min/max/mean,
   categorical top values. This is computed LOCALLY and shown in the UI; it is
   **never** sent to the LLM. (It reads the full file via ``store.load_df`` —
   the same local-only read path the executor uses.)

2. ``suggest_followups`` asks the LLM for 2–3 natural-language follow-up
   questions. Its prompt is built ONLY through ``analysis.privacy`` (schema +
   bounded samples) — the same single choke point every other LLM call uses —
   so it carries no raw data.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import privacy, store
from config.settings import get_settings
from llm.client import LLMClient
from observability.llm_log import estimate_cost, timed_llm_call

_PROMPTS = Path(__file__).parent.parent / "prompts"

# How many distinct categorical values to surface per column.
_TOP_VALUES = 5


def _py(value: object) -> object:
    """Coerce numpy/pandas scalars to plain JSON-serialisable Python types."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        f = float(value)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _column_stats(series: pd.Series, total: int) -> dict:
    null_count = int(series.isna().sum())
    stat: dict = {
        "name": str(series.name),
        "dtype": str(series.dtype),
        "null_count": null_count,
        "null_pct": round(100.0 * null_count / total, 2) if total else 0.0,
        "distinct": int(series.nunique(dropna=True)),
    }

    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        non_null = series.dropna()
        if len(non_null):
            stat["min"] = _py(non_null.min())
            stat["max"] = _py(non_null.max())
            stat["mean"] = round(float(non_null.mean()), 4)
        else:
            stat["min"] = stat["max"] = stat["mean"] = None
    else:
        # Categorical / object / bool — surface the most common values.
        vc = series.dropna().value_counts().head(_TOP_VALUES)
        stat["top_values"] = [
            {"value": _py(idx), "count": int(cnt)} for idx, cnt in vc.items()
        ]

    return stat


def compute_profile(dataset_id: str) -> dict:
    """Compute a rich per-column profile from the FULL dataset. LOCAL only —
    the returned dict is displayed in the UI and cached, never sent to the LLM.
    """
    df = store.load_df(dataset_id)
    total = int(len(df))
    columns = [_column_stats(df[col], total) for col in df.columns]
    return {"row_count": total, "columns": columns}


def _load_prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8").strip()


def _parse_followups(text: str) -> list[str]:
    """Extract 2–3 follow-up question strings from the model output.

    Accepts a JSON array (preferred, per the prompt) or falls back to parsing
    non-empty lines (stripping list markers/numbering)."""
    text = text.strip()
    # Preferred: a JSON array somewhere in the response.
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            arr = json.loads(text[start : end + 1])
            items = [str(x).strip() for x in arr if str(x).strip()]
            if items:
                return items[:3]
        except (json.JSONDecodeError, TypeError):
            pass

    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*0123456789. )").strip().strip('"')
        if line:
            lines.append(line)
    return lines[:3]


def suggest_followups(dataset_meta: dict, run_id: str = "") -> tuple[list[str], dict]:
    """Ask the LLM for 2–3 follow-up questions. Prompt built ONLY via the
    privacy choke point (schema + bounded samples) — no raw data leaves.

    Returns ``(followups, usage_dict)``. Degrades to ``([], usage)`` on failure.
    """
    ctx = privacy.build_context(dataset_meta, question="")
    system = _load_prompt("profile.md")
    try:
        with timed_llm_call("followups", run_id) as usage:
            text, u = LLMClient().call_with_usage(
                privacy.render_context(ctx), system=system
            )
            usage.update(u)
    except Exception:  # noqa: BLE001 — follow-ups are best-effort, never fatal
        return [], {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

    followups = _parse_followups(text)
    cost = estimate_cost(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    return followups, {
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "cost_usd": cost,
    }
