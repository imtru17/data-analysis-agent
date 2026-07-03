"""Phase 3 — live SQL DB source (schema introspection + read-only pushdown).

A DB source is a user database reached over a SQLAlchemy engine. The privacy
boundary is unchanged and, if anything, stronger: the only bytes that reach the
LLM are (a) the introspected schema, (b) a ``LIMIT AGENT_SAMPLE_ROWS`` sample,
and (c) the bounded result summary of an executed query. Generated SQL is
**pushed down** — it runs inside the database, so a huge table is filtered/
aggregated in place and only a small result set is fetched back.

Secret hygiene (see harness/rules/secret-hygiene.md):
- The DSN (which may carry credentials) is modelled as a pydantic ``SecretStr``
  in-memory and only reaches the SQLAlchemy engine via ``.get_secret_value()``.
- It is NEVER placed in state, an ``LlmContext``, a log line, an exception
  message, or an API response — every response returns a masked DSN.
- Generated SQL is validated read-only (single ``SELECT``/``WITH``); DML/DDL and
  multiple statements are rejected before execution.
"""
from __future__ import annotations

import re

import pandas as pd
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from config.settings import get_settings

SUPPORTED_DIALECTS = ("postgresql", "mysql", "sqlite")

# Whole-word DML/DDL keywords that must never appear in generated SQL.
_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|"
    r"replace|merge|attach|detach|pragma|vacuum|reindex|call|exec|execute)\b",
    re.IGNORECASE,
)


class DbSourceError(Exception):
    """A DB-source operation failed. The message NEVER embeds the DSN."""


def mask_dsn(dsn: str) -> str:
    """Return a display-safe DSN with the password masked
    (``postgresql://user:***@host:5432/db``). Best-effort — on any parse
    failure returns a fully-masked placeholder rather than leaking."""
    try:
        url = make_url(dsn)
    except Exception:  # noqa: BLE001 — never leak on a parse error
        return "***"
    if url.password:
        url = url.set(password="***")
    # SQLAlchemy renders the password masked when it equals "***"? No — render
    # explicitly and re-mask defensively.
    rendered = url.render_as_string(hide_password=False)
    return rendered


def dialect_of(dsn: str) -> str:
    try:
        return make_url(dsn).get_backend_name()
    except Exception:  # noqa: BLE001
        return "unknown"


def host_of(dsn: str) -> str | None:
    try:
        return make_url(dsn).host
    except Exception:  # noqa: BLE001
        return None


def _engine(dsn: SecretStr):
    return create_engine(dsn.get_secret_value())


def _scrub(message: str, dsn: SecretStr) -> str:
    """Remove the raw DSN and its password from any error text before it can be
    surfaced or logged (defense-in-depth — errors should never carry a secret)."""
    raw = dsn.get_secret_value()
    safe = message.replace(raw, "***")
    try:
        pw = make_url(raw).password
        if pw:
            safe = safe.replace(pw, "***")
    except Exception:  # noqa: BLE001
        pass
    return safe


def _cap_cell(value: object, cap: int) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (bool, int, float)):
        return value
    text_val = str(value)
    return text_val[:cap] + "…" if len(text_val) > cap else text_val


def introspect(dsn: SecretStr) -> dict:
    """Connect, introspect schema, and draw a bounded ``LIMIT N`` sample per
    table. Returns ``{"tables": [{table, columns:[{name,dtype}], sample_rows}]}``.

    Only schema + the bounded sample cross onward — never a full table, never
    the DSN. Raises ``DbSourceError`` (no DSN in the message) on any failure.
    """
    settings = get_settings()
    sample_n = max(0, settings.sample_rows)
    cap = settings.sample_cell_chars

    try:
        engine = _engine(dsn)
        insp = inspect(engine)
        table_names = insp.get_table_names()
    except Exception as exc:  # noqa: BLE001 — sanitise: never surface the DSN
        raise DbSourceError(f"Could not connect or introspect the database ({type(exc).__name__}).") from None

    tables: list[dict] = []
    try:
        with engine.connect() as conn:
            for tname in table_names:
                cols = [
                    {"name": str(c["name"]), "dtype": str(c["type"])}
                    for c in insp.get_columns(tname)
                ]
                sample_rows: list[dict] = []
                if sample_n:
                    try:
                        df = pd.read_sql_query(
                            text(f'SELECT * FROM "{tname}" LIMIT {sample_n}'), conn
                        )
                        for _, row in df.iterrows():
                            sample_rows.append(
                                {str(c): _cap_cell(row[c], cap) for c in df.columns}
                            )
                    except Exception:  # noqa: BLE001 — a sample failure is non-fatal
                        sample_rows = []
                tables.append(
                    {"table": tname, "columns": cols, "sample_rows": sample_rows}
                )
    except Exception as exc:  # noqa: BLE001
        raise DbSourceError(f"Could not read the database schema ({type(exc).__name__}).") from None
    finally:
        engine.dispose()

    if not tables:
        raise DbSourceError("The database has no readable tables.")
    return {"tables": tables}


def validate_read_only(sql: str) -> str | None:
    """Return an error message if ``sql`` is not a single read-only statement,
    else ``None``. Only ``SELECT``/``WITH`` are allowed."""
    stripped = sql.strip()
    if not stripped:
        return "Empty SQL."
    # Strip a single trailing semicolon; any remaining ';' means >1 statement.
    body = stripped[:-1] if stripped.endswith(";") else stripped
    if ";" in body:
        return "Multiple SQL statements are not allowed."
    if _FORBIDDEN_SQL.search(body):
        return "Only read-only SELECT/WITH queries are allowed (DML/DDL rejected)."
    first = re.match(r"\s*([a-zA-Z]+)", body)
    if not first or first.group(1).lower() not in ("select", "with"):
        return "Only read-only SELECT/WITH queries are allowed."
    return None


def run_query(dsn: SecretStr, sql: str) -> pd.DataFrame:
    """Validate + push down a read-only query and fetch a BOUNDED intermediate.

    The query runs inside the DB; a safety ``LIMIT AGENT_SQL_MAX_ROWS`` wraps it
    so a stray ``SELECT *`` cannot pull a whole table into memory. Raises
    ``DbSourceError`` (no DSN in the message) on rejection or execution error.
    """
    rejection = validate_read_only(sql)
    if rejection is not None:
        raise DbSourceError(rejection)

    max_rows = get_settings().sql_max_rows
    body = sql.strip().rstrip(";")
    wrapped = f"SELECT * FROM ({body}) AS _agent_q LIMIT {max_rows}"

    try:
        engine = _engine(dsn)
        try:
            with engine.connect() as conn:
                return pd.read_sql_query(text(wrapped), conn)
        finally:
            engine.dispose()
    except DbSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — sanitise: never surface the DSN
        raise DbSourceError(
            _scrub(f"Query failed ({type(exc).__name__}: {exc}).", dsn)
        ) from None
