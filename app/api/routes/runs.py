"""Pipeline runs API routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import PipelineRunItem, PipelineRunsResponse
from app.db.models import PipelineRun
from app.db.session import get_db

router = APIRouter(prefix="/api")

DB_SESSION = Depends(get_db)


@router.get("/runs", response_model=PipelineRunsResponse)
def list_runs(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = DB_SESSION,
) -> PipelineRunsResponse:
    rows = db.query(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit).all()

    items = [
        PipelineRunItem(
            id=r.id,
            started_at=r.started_at,
            finished_at=r.finished_at,
            status=r.status,
            source_name=r.source_name,
            records_seen=r.records_seen,
            records_loaded=r.records_loaded,
            errors_count=r.errors_count,
            error_summary=r.error_summary,
        )
        for r in rows
    ]

    return PipelineRunsResponse(data=items)
