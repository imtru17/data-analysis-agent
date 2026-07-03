"""Per-format file loaders (Phase 3).

Each loader reads a local file into a pandas DataFrame. Heavy/optional deps
(openpyxl, pdfplumber) are imported lazily so a missing extra degrades to a
friendly error instead of an import-time crash.

Graceful degradation: when a format yields no clean tabular data (typically a
PDF with no detectable table, or an empty/unparseable log), the loader raises
``LoaderError`` — the API maps this to a 400 ``BAD_REQUEST`` with a friendly
reason rather than crashing. The privacy invariant is unchanged: only the
schema + a bounded sample of the resulting DataFrame ever reach the LLM.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd


class LoaderError(Exception):
    """A file could not be loaded to a clean tabular DataFrame. Maps to a
    friendly 400 ``BAD_REQUEST`` at the API boundary (never a crash)."""


# File extension → logical ``source_kind`` recorded on the DatasetRow.
_EXT_KIND: dict[str, str] = {
    ".csv": "csv",
    ".xlsx": "excel",
    ".xls": "excel",
    ".json": "json",
    ".parquet": "parquet",
    ".pdf": "pdf",
    ".log": "log",
    ".txt": "log",
}

SUPPORTED_KINDS = tuple(sorted(set(_EXT_KIND.values())))


def kind_for_extension(ext: str) -> str | None:
    return _EXT_KIND.get(ext.lower())


def kind_for_filename(filename: str) -> str | None:
    return kind_for_extension(Path(filename).suffix)


def _load_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not parse CSV: {exc}") from exc


def _load_excel(path: Path) -> pd.DataFrame:
    try:
        # First sheet by default; openpyxl backs .xlsx.
        return pd.read_excel(path, sheet_name=0)
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LoaderError(
            "Excel support requires openpyxl. Install project deps with `uv sync`."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not read the Excel file: {exc}") from exc


def _load_json(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Try records/array first, then a single object, then nested normalization.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # NDJSON / JSON-lines fallback.
        try:
            return pd.read_json(io.StringIO(text), lines=True)
        except Exception as exc:  # noqa: BLE001
            raise LoaderError(f"Could not parse JSON: {exc}") from exc

    try:
        if isinstance(parsed, list):
            return pd.json_normalize(parsed)
        if isinstance(parsed, dict):
            # A dict of equal-length lists → columns; else a single record.
            if parsed and all(isinstance(v, list) for v in parsed.values()):
                return pd.DataFrame(parsed)
            return pd.json_normalize(parsed)
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not flatten JSON to a table: {exc}") from exc
    raise LoaderError("JSON did not contain a table-shaped structure.")


def _load_parquet(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)  # pyarrow
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not read the Parquet file: {exc}") from exc


def _load_pdf(path: Path) -> pd.DataFrame:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise LoaderError(
            "PDF support requires pdfplumber. Install project deps with `uv sync`."
        ) from exc

    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table and len(table) >= 2:
                    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(table[0])]
                    body = table[1:]
                    return pd.DataFrame(body, columns=header)
    except LoaderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not read the PDF: {exc}") from exc

    raise LoaderError(
        "Couldn't find a table in that PDF — try exporting to CSV/Excel/Parquet."
    )


def _load_log(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise LoaderError("The log/text file has no readable lines.")
    return pd.DataFrame({"line": lines})


_LOADERS = {
    "csv": _load_csv,
    "excel": _load_excel,
    "json": _load_json,
    "parquet": _load_parquet,
    "pdf": _load_pdf,
    "log": _load_log,
}


def load_dataframe(path: Path, source_kind: str) -> pd.DataFrame:
    """Load ``path`` to a DataFrame using the loader for ``source_kind``.

    Raises ``LoaderError`` (→ friendly 400) when the format yields no clean
    table. A loaded-but-empty DataFrame (no rows AND no columns) is also treated
    as "no table"."""
    loader = _LOADERS.get(source_kind)
    if loader is None:
        raise LoaderError(f"Unsupported source kind: {source_kind!r}")
    df = loader(path)
    if df is None or (df.shape[0] == 0 and df.shape[1] == 0):
        raise LoaderError("The file contained no tabular data.")
    return df
