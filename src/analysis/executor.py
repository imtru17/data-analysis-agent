"""Local, restricted execution of LLM-generated pandas code.

Runs generated code against the FULL DataFrame in a restricted namespace with
a wall-clock timeout. Only ``df``, ``pd``, ``np`` and a curated subset of
builtins are exposed — no ``import``, ``open``, ``eval``, ``exec``, os/sys/
socket/requests. A static pre-check rejects dangerous tokens before running.

Security note: this is defense-in-depth for a TRUSTED single user running the
tool on their own machine — NOT a hostile-multi-tenant sandbox. On Windows
``signal.SIGALRM`` does not exist, so the timeout is enforced by running the
code in a worker thread and abandoning it via ``future.result(timeout=...)``.
A truly runaway pure-CPU thread cannot be force-killed on CPython; the timeout
surfaces an error to the user and the request returns — an accepted limit for
a single trusted user.
"""
from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import redirect_stdout
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config.settings import get_settings

# Tokens that must never appear in generated code (static pre-check).
_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bimport\b", "import statements are not allowed"),
    (r"__", "dunder access is not allowed"),
    (r"\bopen\s*\(", "open() is not allowed"),
    (r"\beval\s*\(", "eval() is not allowed"),
    (r"\bexec\s*\(", "exec() is not allowed"),
    (r"\bcompile\s*\(", "compile() is not allowed"),
    (r"\binput\s*\(", "input() is not allowed"),
    (r"\bos\.", "os module access is not allowed"),
    (r"\bsys\.", "sys module access is not allowed"),
    (r"\bsocket\b", "socket access is not allowed"),
    (r"\brequests\b", "network access is not allowed"),
    (r"\burllib\b", "network access is not allowed"),
    (r"\bsubprocess\b", "subprocess is not allowed"),
    (r"\bgetattr\s*\(", "getattr() is not allowed"),
    (r"\bsetattr\s*\(", "setattr() is not allowed"),
    (r"\bglobals\s*\(", "globals() is not allowed"),
    (r"\blocals\s*\(", "locals() is not allowed"),
    (r"\bto_csv\b", "writing files is not allowed"),
    (r"\bto_parquet\b", "writing files is not allowed"),
    (r"\bread_csv\b", "reading files is not allowed (df is provided)"),
    (r"\bread_parquet\b", "reading files is not allowed (df is provided)"),
]

# Curated safe builtins exposed to generated code.
_SAFE_BUILTINS = {
    "len": len, "sum": sum, "min": min, "max": max, "sorted": sorted,
    "range": range, "round": round, "abs": abs, "list": list, "dict": dict,
    "set": set, "tuple": tuple, "str": str, "int": int, "float": float,
    "bool": bool, "enumerate": enumerate, "zip": zip, "map": map,
    "filter": filter, "any": any, "all": all, "reversed": reversed,
    "print": print, "isinstance": isinstance, "type": type,
}


@dataclass
class ExecResult:
    """Outcome of a local code run. Errors are NON-fatal — returned here so the
    graph's refine loop can retry. ``result_summary`` is the ONLY computed data
    allowed onward to the LLM answer node (scalars pass; tables truncated)."""

    ok: bool = False
    result_summary: dict | None = None
    stdout: str = ""
    error: str | None = None


def static_check(code: str) -> str | None:
    """Return an error message if the code is rejected, else None."""
    for pattern, message in _FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            return f"Rejected by static pre-check: {message}"
    return None


def _summarize(result: object) -> dict:
    """Build a BOUNDED result summary. Scalars pass through; DataFrame/Series
    truncated to ``AGENT_RESULT_ROWS`` rows. This is the only computed data
    that may reach the LLM."""
    settings = get_settings()
    max_rows = settings.result_rows
    cap = settings.sample_cell_chars

    def cap_cell(v: object) -> object:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, (bool, int, float)):
            return v
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        text = str(v)
        return text[:cap] + "…" if len(text) > cap else text

    if result is None:
        return {"kind": "none", "value": None}

    if isinstance(result, pd.DataFrame):
        total = int(len(result))
        head = result.head(max_rows)
        rows = [
            {str(c): cap_cell(head.iloc[i][c]) for c in result.columns}
            for i in range(len(head))
        ]
        return {
            "kind": "dataframe",
            "shape": [total, int(result.shape[1])],
            "columns": [str(c) for c in result.columns],
            "rows": rows,
            "truncated": total > max_rows,
        }

    if isinstance(result, pd.Series):
        total = int(len(result))
        head = result.head(max_rows)
        rows = [{"index": cap_cell(idx), "value": cap_cell(val)} for idx, val in head.items()]
        return {
            "kind": "series",
            "name": None if result.name is None else str(result.name),
            "length": total,
            "rows": rows,
            "truncated": total > max_rows,
        }

    if isinstance(result, (np.integer,)):
        return {"kind": "scalar", "value": int(result)}
    if isinstance(result, (np.floating,)):
        return {"kind": "scalar", "value": float(result)}
    if isinstance(result, (int, float, bool, str)):
        return {"kind": "scalar", "value": cap_cell(result)}
    if isinstance(result, dict):
        return {"kind": "dict", "value": {str(k): cap_cell(v) for k, v in list(result.items())[:max_rows]}}
    if isinstance(result, (list, tuple)):
        seq = list(result)[:max_rows]
        return {"kind": "list", "value": [cap_cell(v) for v in seq], "length": len(result)}

    return {"kind": "repr", "value": cap_cell(repr(result))}


def _run_in_namespace(code: str, df: pd.DataFrame) -> tuple[object, str]:
    restricted_globals = {
        "__builtins__": _SAFE_BUILTINS,
        "df": df,
        "pd": pd,
        "np": np,
    }
    local_ns: dict = {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        compiled = compile(code, "<generated_code>", "exec")
        exec(compiled, restricted_globals, local_ns)  # noqa: S102 — restricted ns by design
    result = local_ns.get("result", restricted_globals.get("result"))
    return result, buf.getvalue()


def run_code_raw(code: str, df: pd.DataFrame) -> object:
    """Execute generated code and return the FULL raw ``result`` object.

    Unlike ``run_code`` (which returns a bounded summary), this returns the
    complete result — used ONLY for local exports the local user downloads to
    their own machine. Applies the same static pre-check and restricted
    namespace, and enforces the wall-clock timeout. Raises ``ValueError`` on
    rejection / missing result and re-raises any execution error.
    """
    rejection = static_check(code)
    if rejection is not None:
        raise ValueError(rejection)

    timeout = get_settings().exec_timeout
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run_in_namespace, code, df)
        result, _stdout = future.result(timeout=timeout)
    except FutureTimeout:
        pool.shutdown(wait=False)
        raise TimeoutError(f"Execution exceeded the {timeout}s wall-clock timeout.")
    finally:
        pool.shutdown(wait=False)

    if result is None and "result" not in code:
        raise ValueError("Code did not assign to `result`.")
    return result


def run_code(code: str, df: pd.DataFrame) -> ExecResult:
    """Execute generated code against ``df`` in a restricted namespace with a
    wall-clock timeout. Errors are captured (non-fatal) into ``ExecResult.error``."""
    rejection = static_check(code)
    if rejection is not None:
        return ExecResult(ok=False, error=rejection)

    timeout = get_settings().exec_timeout

    # NOTE: we do NOT use `with ThreadPoolExecutor(...)` — its __exit__ calls
    # shutdown(wait=True), which would BLOCK until a runaway thread finishes,
    # defeating the timeout. We shut the pool down with wait=False so a timeout
    # returns control to the user immediately. A pure-CPU runaway thread cannot
    # be force-killed on CPython; it keeps running in the background until it
    # finishes on its own — an accepted limit for a single trusted local user.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run_in_namespace, code, df)
        result, stdout = future.result(timeout=timeout)
    except FutureTimeout:
        pool.shutdown(wait=False)
        return ExecResult(
            ok=False,
            error=f"Execution exceeded the {timeout}s wall-clock timeout.",
        )
    except Exception as exc:  # noqa: BLE001 — surface any code error to the refine loop
        pool.shutdown(wait=False)
        return ExecResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    else:
        pool.shutdown(wait=False)

    if result is None and "result" not in code:
        return ExecResult(
            ok=False,
            stdout=stdout,
            error="Code did not assign to `result`.",
        )

    return ExecResult(ok=True, result_summary=_summarize(result), stdout=stdout)


# Public alias — Phase 3 nodes summarize an already-computed intermediate
# (e.g. a DB pushdown result) without re-running code.
summarize_result = _summarize


def run_combine(code: str, variables: dict[str, object]) -> ExecResult:
    """Run a LOCAL pandas snippet that combines already-computed per-source
    intermediates (Phase 3 multi-source). ``variables`` maps a safe variable
    name to each source's already-bounded/aggregated intermediate (never a
    full raw table — each per-source code block already reduced its data).
    Same restricted namespace + static pre-check + wall-clock timeout as
    ``run_code``; only additional globals are the given variables."""
    rejection = static_check(code)
    if rejection is not None:
        return ExecResult(ok=False, error=rejection)

    timeout = get_settings().exec_timeout

    def _run() -> tuple[object, str]:
        restricted_globals = {
            "__builtins__": _SAFE_BUILTINS,
            "pd": pd,
            "np": np,
            **variables,
        }
        local_ns: dict = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            compiled = compile(code, "<combine_code>", "exec")
            exec(compiled, restricted_globals, local_ns)  # noqa: S102 — restricted ns by design
        result = local_ns.get("result", restricted_globals.get("result"))
        return result, buf.getvalue()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run)
        result, stdout = future.result(timeout=timeout)
    except FutureTimeout:
        pool.shutdown(wait=False)
        return ExecResult(
            ok=False, error=f"Combine execution exceeded the {timeout}s wall-clock timeout."
        )
    except Exception as exc:  # noqa: BLE001 — surface any combine error to the refine loop
        pool.shutdown(wait=False)
        return ExecResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    else:
        pool.shutdown(wait=False)

    if result is None and "result" not in code:
        return ExecResult(ok=False, stdout=stdout, error="Combine code did not assign to `result`.")

    return ExecResult(ok=True, result_summary=_summarize(result), stdout=stdout)
