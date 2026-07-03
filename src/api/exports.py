"""Export endpoint — download a run's derived dataset, code, or report."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from analysis import export as export_mod
from api._common import api_error
from db.models import AnalysisRunRow
from db.session import get_session

router = APIRouter()

_KINDS = ("csv", "parquet", "code", "report")


@router.get("/analyses/{run_id}/export")
def export_run(
    run_id: str,
    kind: str = Query(..., description="csv | parquet | code | report"),
    session: Session = Depends(get_session),
):
    if kind not in _KINDS:
        raise api_error("BAD_REQUEST", f"Unknown export kind: {kind}", 400)

    run = session.get(AnalysisRunRow, run_id)
    if run is None:
        raise api_error("NOT_FOUND", f"Run {run_id} not found", 404)

    if kind in ("csv", "parquet", "code") and not run.generated_code:
        raise api_error("BAD_REQUEST", "Run has no generated code to export.", 400)

    media_type, suffix = export_mod.EXPORT_MEDIA[kind]

    try:
        if kind == "csv":
            content = export_mod.build_csv(run.generated_code, run.dataset_id)
        elif kind == "parquet":
            content = export_mod.build_parquet(run.generated_code, run.dataset_id)
        elif kind == "code":
            content = export_mod.build_code(run.generated_code)
        else:  # report
            content = export_mod.build_report(
                question=run.question,
                answer=run.answer,
                result_summary=json.loads(run.result_summary_json)
                if run.result_summary_json
                else None,
                chart_spec=json.loads(run.chart_spec_json) if run.chart_spec_json else None,
            )
    except export_mod.ExportError as exc:
        raise api_error("EXPORT_FAILED", str(exc), exc.status)

    filename = f"analysis_{run_id[:8]}.{suffix}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
