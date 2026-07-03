"""Phase 4 — LOCAL data workbench: profile tiles (PK/FK detection) + per-column
value counts.

Everything here is deterministic, in-process pandas over the dataset's FULL
DataFrame. There is **no** LLM call and **no** network call anywhere in this
module — the privacy invariant holds by construction (nothing leaves the
machine, no prompt is built). It deliberately does not import ``src/llm`` or
``analysis.privacy``.

``build_tiles`` reuses :func:`analysis.profile.compute_profile` for the reported
``row_count`` / per-column ``distinct`` / ``null_count`` (the full-data numbers)
and adds PK-candidate flags plus best-effort FK-candidate detection against the
other datasets in scope.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from analysis import profile as profile_mod
from analysis import store
from analysis.profile import _py  # JSON-safe numpy/pandas scalar coercion
from config.settings import get_settings
from db.models import DatasetRow


def _distinct_set(series: pd.Series) -> frozenset:
    """Non-null distinct values of a column as a JSON-safe, hashable set."""
    return frozenset(_py(v) for v in series.dropna().unique())


def _pk_columns(df: pd.DataFrame) -> dict[str, frozenset]:
    """Map each PK-candidate column (unique + non-null over the FULL frame) to
    its distinct value set. Used as the FK reference side."""
    n = len(df)
    out: dict[str, frozenset] = {}
    if n == 0:
        return out
    for col in df.columns:
        s = df[col]
        if int(s.isna().sum()) == 0 and int(s.nunique(dropna=True)) == n:
            out[str(col)] = _distinct_set(s)
    return out


def _scope_datasets(current: DatasetRow, session: Session) -> list[DatasetRow]:
    """Other datasets to scan for FK references: same-session datasets when the
    current dataset has a ``session_id``; otherwise the most recent
    ``AGENT_WORKBENCH_FK_SCAN`` datasets by ``created_at``. Excludes self."""
    q = session.query(DatasetRow).filter(DatasetRow.id != current.id)
    if current.session_id:
        return q.filter(DatasetRow.session_id == current.session_id).all()
    limit = get_settings().workbench_fk_scan
    return q.order_by(DatasetRow.created_at.desc()).limit(limit).all()


def _name_score(col: str, other_name: str, ref_col: str) -> int:
    """Heuristic ordering signal — a ``<parent>_id`` name that matches the
    referenced dataset/column boosts a candidate. It only orders candidates;
    the subset test is what makes a candidate valid."""
    base = col.lower()
    stem = Path(other_name).stem.lower()
    ref = ref_col.lower()
    score = 0
    if base.endswith("_id"):
        score += 1
        prefix = base[:-3]
        if prefix and (prefix == stem or f"{prefix}s" == stem or stem.startswith(prefix)):
            score += 2
    if ref == "id":
        score += 1
    if base == ref:
        score += 1
    return score


def build_tiles(dataset_id: str, session: Session) -> dict:
    """Profile-tiles payload for a dataset (see spec/api.md GET .../tiles).

    Reuses ``compute_profile`` for the full-data ``row_count`` / ``distinct`` /
    ``null_count``. PK-candidate = ``null_count == 0`` AND ``distinct ==
    row_count``. FK-candidate = a column whose non-null distinct value set is a
    non-empty subset of another in-scope dataset's PK-candidate column's value
    set. FK detection is best-effort: any per-other-dataset load error is
    skipped, never fatal.
    """
    prof = profile_mod.compute_profile(dataset_id)
    row_count = int(prof["row_count"])

    # Full-data frame for this dataset — the value sets used for FK subset tests.
    df = store.load_df(dataset_id)
    cur_sets: dict[str, frozenset] = {str(c): _distinct_set(df[c]) for c in df.columns}

    # Resolve the FK reference scope and precompute each other dataset's PK
    # columns + value sets (best-effort — skip any dataset that won't load).
    current = session.get(DatasetRow, dataset_id)
    others: list[tuple[str, str, dict[str, frozenset]]] = []
    if current is not None:
        for other in _scope_datasets(current, session):
            try:
                odf = store.load_df(other.id)
                pk_cols = _pk_columns(odf)
            except Exception:  # noqa: BLE001 — FK detection is best-effort
                continue
            if pk_cols:
                others.append((other.id, other.filename, pk_cols))

    columns: list[dict] = []
    pk_names: list[str] = []
    fk_top: list[dict] = []

    for col_stat in prof["columns"]:
        name = col_stat["name"]
        distinct = int(col_stat["distinct"])
        null_count = int(col_stat["null_count"])
        is_pk = null_count == 0 and distinct == row_count and row_count > 0
        if is_pk:
            pk_names.append(name)

        cur_set = cur_sets.get(name, frozenset())
        cur_distinct = len(cur_set)
        fk_candidates: list[dict] = []
        if cur_distinct:
            for other_id, other_name, pk_cols in others:
                for pk_col, pk_set in pk_cols.items():
                    # Cheap guard: a larger distinct set cannot be a subset.
                    if cur_distinct > len(pk_set):
                        continue
                    if cur_set <= pk_set:
                        cand = {
                            "references_dataset_id": other_id,
                            "references_dataset_name": other_name,
                            "references_column": pk_col,
                            "_score": _name_score(name, other_name, pk_col),
                        }
                        fk_candidates.append(cand)

        # Order by the name heuristic (highest first), then drop the sort key.
        fk_candidates.sort(key=lambda c: c["_score"], reverse=True)
        for cand in fk_candidates:
            cand.pop("_score", None)

        columns.append(
            {
                "name": name,
                "dtype": col_stat["dtype"],
                "distinct": distinct,
                "null_count": null_count,
                "is_pk_candidate": is_pk,
                "fk_candidates": fk_candidates,
            }
        )
        if fk_candidates:
            best = fk_candidates[0]
            fk_top.append(
                {
                    "column": name,
                    "references_dataset_id": best["references_dataset_id"],
                    "references_dataset_name": best["references_dataset_name"],
                    "references_column": best["references_column"],
                }
            )

    return {
        "row_count": row_count,
        "columns": columns,
        "primary_key_candidates": pk_names,
        "foreign_key_candidates": fk_top,
    }


def column_values(dataset_id: str, col: str) -> dict:
    """Top-N value counts for one column over the FULL data (drill-in).

    Raises ``ValueError`` for an unknown column — the router maps it to 400.
    """
    df = store.load_df(dataset_id)
    if col not in df.columns:
        raise ValueError(f"Unknown column: {col}")

    topn = get_settings().workbench_values_topn
    vc = df[col].value_counts(dropna=True)
    values = [
        {"value": _py(idx), "count": int(cnt)}
        for idx, cnt in vc.head(topn).items()
    ]
    return {
        "column": col,
        "total": int(len(df)),
        "values": values,
        "truncated": int(len(vc)) > topn,
    }
