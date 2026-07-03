"""On-disk dataset store.

Owns ``./data/uploads/``. Persists raw uploaded files, loads them to
DataFrames, and computes a bounded schema+sample *profile* — which is
exactly (and only) what the LLM is ever allowed to see.

``load_df`` is the ONLY function that reads the full file, and only the
executor calls it. Everything upstream of local execution uses the profile.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pandas as pd

from config.settings import get_settings


@dataclass
class ColumnMeta:
    name: str
    dtype: str


@dataclass
class DatasetMeta:
    """Schema + bounded samples ONLY. Never carries a DataFrame."""

    dataset_id: str
    filename: str
    row_count: int
    columns: list[ColumnMeta] = field(default_factory=list)
    sample_rows: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "filename": self.filename,
            "row_count": self.row_count,
            "columns": [{"name": c.name, "dtype": c.dtype} for c in self.columns],
            "sample_rows": self.sample_rows,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DatasetMeta":
        return cls(
            dataset_id=d.get("dataset_id", ""),
            filename=d.get("filename", ""),
            row_count=int(d.get("row_count", 0)),
            columns=[ColumnMeta(name=c["name"], dtype=c["dtype"]) for c in d.get("columns", [])],
            sample_rows=list(d.get("sample_rows", [])),
        )


def _uploads_dir() -> Path:
    d = Path(get_settings().uploads_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(dataset_id: str) -> Path:
    """Absolute path to a stored dataset file."""
    return _uploads_dir() / f"{dataset_id}.csv"


def save(upload_bytes: bytes, filename: str) -> str:
    """Persist raw bytes under ./data/uploads/<dataset_id>.csv and return the id.

    The original filename is not used on disk (avoids path traversal); it is
    carried in the DatasetRow metadata instead.
    """
    dataset_id = str(uuid4())
    dest = path(dataset_id)
    dest.write_bytes(upload_bytes)
    return dataset_id


def load_df(dataset_id: str) -> pd.DataFrame:
    """Read the FULL csv into a DataFrame. The ONLY full-file read; called
    exclusively by the local executor."""
    p = path(dataset_id)
    if not p.exists():
        raise FileNotFoundError(f"Dataset {dataset_id} not found at {p}")
    return pd.read_csv(p)


def _cap_cell(value: object, cap: int) -> object:
    """Bound a single cell so wide/long cells cannot smuggle bulk data."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) > cap:
        return text[:cap] + "…"
    return text


def profile(dataset_id: str, filename: str | None = None) -> DatasetMeta:
    """Compute schema (columns+dtypes), row count, and ≤sample_rows head
    sample rows with a per-cell char cap. Deterministic head sampling."""
    settings = get_settings()
    df = load_df(dataset_id)

    columns = [ColumnMeta(name=str(c), dtype=str(df[c].dtype)) for c in df.columns]

    n = max(0, settings.sample_rows)
    cap = settings.sample_cell_chars
    head = df.head(n)
    sample_rows: list[dict] = []
    for _, row in head.iterrows():
        sample_rows.append({str(col): _cap_cell(row[col], cap) for col in df.columns})

    return DatasetMeta(
        dataset_id=dataset_id,
        filename=filename or f"{dataset_id}.csv",
        row_count=int(len(df)),
        columns=columns,
        sample_rows=sample_rows,
    )
