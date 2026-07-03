"""Phase 2 export builders.

Four export kinds for a completed run:

- ``csv`` / ``parquet`` — RE-EXECUTE the run's stored ``generated_code`` locally
  against the FULL dataset and serialize the complete derived result. This is a
  local file for the local user, so it is the full result (not the bounded
  summary). No new data reaches any LLM here — this is pure local computation.
- ``code`` — the exact ``generated_code`` as a ``.py`` file.
- ``report`` — a self-contained HTML report (question + answer + result table +
  embedded Vega-Lite chart if present).

Errors are raised as ``ExportError`` and mapped to HTTP status by the router.
"""
from __future__ import annotations

import html
import io
import json
import re

import numpy as np
import pandas as pd

from analysis import store
from analysis.executor import run_code_raw


class ExportError(Exception):
    """Raised when an export cannot be produced. ``status`` maps to HTTP."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def result_to_frame(result: object) -> pd.DataFrame:
    """Coerce an arbitrary computed result into a DataFrame for serialization."""
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, pd.Series):
        name = result.name if result.name is not None else "value"
        return result.rename(name).reset_index()
    if isinstance(result, dict):
        # dict of scalars → one-row frame; dict of sequences → columns.
        if result and all(np.isscalar(v) or v is None for v in result.values()):
            return pd.DataFrame([result])
        return pd.DataFrame(result)
    if isinstance(result, (list, tuple)):
        return pd.DataFrame({"value": list(result)})
    # Scalar / other → single cell.
    return pd.DataFrame({"value": [result]})


def _rerun_full_result(generated_code: str, dataset_id: str) -> pd.DataFrame:
    df = store.load_df(dataset_id)
    try:
        result = run_code_raw(generated_code, df)
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"Could not re-run analysis code: {exc}", 500) from exc
    return result_to_frame(result)


def build_csv(generated_code: str, dataset_id: str) -> bytes:
    frame = _rerun_full_result(generated_code, dataset_id)
    return frame.to_csv(index=False).encode("utf-8")


def build_parquet(generated_code: str, dataset_id: str) -> bytes:
    frame = _rerun_full_result(generated_code, dataset_id)
    buf = io.BytesIO()
    try:
        frame.to_parquet(buf, index=False)  # requires pyarrow
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"Could not write parquet: {exc}", 500) from exc
    return buf.getvalue()


def build_code(generated_code: str) -> bytes:
    return generated_code.encode("utf-8")


# ── HTML report ──────────────────────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """Minimal, self-contained markdown → HTML (escape + bold/italic/code +
    paragraphs). Avoids a runtime markdown dependency."""
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped)
    paragraphs = [p.strip().replace("\n", "<br>") for p in escaped.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{p}</p>" for p in paragraphs)


def _summary_to_table(summary: dict | None) -> str:
    if not summary:
        return "<p><em>No tabular result.</em></p>"
    kind = summary.get("kind")
    if kind == "dataframe":
        cols = summary.get("columns", [])
        rows = summary.get("rows", [])
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>"
            for r in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    if kind == "series":
        rows = summary.get("rows", [])
        body = "".join(
            f"<tr><td>{html.escape(str(r.get('index', '')))}</td>"
            f"<td>{html.escape(str(r.get('value', '')))}</td></tr>"
            for r in rows
        )
        return f"<table><thead><tr><th>index</th><th>value</th></tr></thead><tbody>{body}</tbody></table>"
    if kind == "scalar":
        return f"<p class='scalar'>{html.escape(str(summary.get('value')))}</p>"
    return f"<pre>{html.escape(json.dumps(summary, indent=2, default=str))}</pre>"


def build_report(
    question: str,
    answer: str | None,
    result_summary: dict | None,
    chart_spec: dict | None,
) -> bytes:
    """Assemble a single self-contained HTML report. When a chart spec exists it
    is embedded and rendered client-side via the vega-embed CDN."""
    answer_html = _md_to_html(answer or "")
    table_html = _summary_to_table(result_summary)

    if chart_spec:
        spec_json = json.dumps(chart_spec, default=str)
        chart_block = f"""
  <h2>Chart</h2>
  <div id="chart"></div>
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
  <script>
    vegaEmbed('#chart', {spec_json});
  </script>"""
    else:
        chart_block = ""

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Analysis report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    h1 {{ font-size: 1.4rem; }}
    h2 {{ font-size: 1.1rem; margin-top: 1.6rem; }}
    table {{ border-collapse: collapse; margin-top: .5rem; }}
    th, td {{ border: 1px solid #ddd; padding: .35rem .6rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .scalar {{ font-size: 1.4rem; font-weight: 600; }}
    code {{ background: #f2f2f2; padding: .1rem .3rem; border-radius: 3px; }}
    footer {{ margin-top: 2rem; color: #888; font-size: .8rem; }}
  </style>
</head>
<body>
  <h1>{html.escape(question)}</h1>
  <h2>Answer</h2>
  {answer_html}
  <h2>Result</h2>
  {table_html}{chart_block}
  <footer>Generated locally by the Data Analysis Agent — raw data never left this machine.</footer>
</body>
</html>"""
    return doc.encode("utf-8")


# Media types + filename suffixes per export kind.
EXPORT_MEDIA = {
    "csv": ("text/csv", "csv"),
    "parquet": ("application/octet-stream", "parquet"),
    "code": ("text/x-python", "py"),
    "report": ("text/html", "html"),
}
