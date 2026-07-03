"""Phase 4 — LOCAL DuckDB SQL runner over a dataset's DataFrame.

The user's raw SQL runs **in-process** via DuckDB against the dataset's pandas
frame — no network, no LLM, nothing leaves the machine. The frame is registered
under the canonical view ``data`` and (when derivable) the sanitized filename
stem, so a query may ``SELECT ... FROM data``.

Any DuckDB parse/execution error is caught and re-raised as
:class:`SqlQueryError` carrying the friendly DuckDB message — the router maps it
to a 400 ``BAD_REQUEST`` so the user never sees a 500 / stack trace.

A fresh connection with per-call view registration is used every time; there is
no shared global DuckDB state.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from analysis import store
from analysis.profile import _py


class SqlQueryError(Exception):
    """A DuckDB parse/execution error, surfaced with a friendly message.
    The router maps this to HTTP 400 (never a 500)."""


def _sanitized_stem(filename: str | None) -> str | None:
    """Turn a filename stem (``orders.csv`` → ``orders``) into a valid DuckDB
    view identifier, or ``None`` if nothing usable / it collides with ``data``."""
    if not filename:
        return None
    stem = Path(filename).stem
    ident = re.sub(r"\W", "_", stem)
    if ident and ident[0].isdigit():
        ident = f"_{ident}"
    if not ident or ident == "data":
        return None
    return ident


def _connect_with_views(df: pd.DataFrame, filename: str | None):
    """Fresh DuckDB connection with ``data`` (and the filename stem) registered."""
    con = duckdb.connect()
    con.register("data", df)
    stem = _sanitized_stem(filename)
    if stem is not None:
        try:
            con.register(stem, df)
        except Exception:  # noqa: BLE001 — the stem view is a convenience only
            pass
    return con


def _execute(df: pd.DataFrame, sql: str, filename: str | None) -> pd.DataFrame:
    con = _connect_with_views(df, filename)
    try:
        result = con.execute(sql).fetchdf()
    except Exception as exc:  # noqa: BLE001 — ALL DuckDB errors → friendly 400
        raise SqlQueryError(str(exc)) from exc
    finally:
        con.close()
    return result


def run_query(dataset_id: str, sql: str, display_cap: int, filename: str | None = None) -> dict:
    """Run ``sql`` locally and return a bounded result table.

    ``rows`` is capped to ``display_cap`` JSON-safe records; ``row_count`` is the
    FULL result length; ``truncated`` is set when the full result exceeds the
    cap.
    """
    df = store.load_df(dataset_id)
    result = _execute(df, sql, filename)

    full_len = int(len(result))
    columns = [str(c) for c in result.columns]
    capped = result.head(display_cap)
    rows = [
        {str(col): _py(row[col]) for col in result.columns}
        for _, row in capped.iterrows()
    ]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": full_len,
        "truncated": full_len > display_cap,
    }


def query_to_csv(dataset_id: str, sql: str, filename: str | None = None) -> bytes:
    """Run the same ``sql`` and return the FULL (uncapped) result as CSV bytes."""
    df = store.load_df(dataset_id)
    result = _execute(df, sql, filename)
    return result.to_csv(index=False).encode("utf-8")
