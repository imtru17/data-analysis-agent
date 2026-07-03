"""Phase 3 — pluggable data-source loaders.

A *source* is either a **file source** (CSV/Excel/JSON/Parquet/PDF/log — loaded
to a pandas DataFrame and executed locally) or a **DB source** (a live SQL
database reached over SQLAlchemy, executed by ``analysis.db_source``). This
package owns the per-format file loaders; the same privacy invariant holds for
every format — only schema + a bounded sample ever reach the LLM.
"""
from analysis.sources.loaders import (
    LoaderError,
    SUPPORTED_KINDS,
    kind_for_filename,
    load_dataframe,
)

__all__ = [
    "LoaderError",
    "SUPPORTED_KINDS",
    "kind_for_filename",
    "load_dataframe",
]
