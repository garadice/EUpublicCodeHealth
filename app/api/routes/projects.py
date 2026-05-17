"""Project and summary API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.queries import apply_project_filters, build_projects_query, latest_status_subq
from app.api.schemas import ProjectItem, ProjectsResponse, SummaryResponse
from app.core.status import VALID_STATUS_LABELS, StatusLabel
from app.db.models import (
    Project,
    ProjectStatusSnapshot,
    Repository,
)
from app.db.session import get_db

router = APIRouter(prefix="/api")

DB_SESSION = Depends(get_db)


def _row_to_project_item(row: Any) -> ProjectItem:
    """Convert a query row to a ProjectItem response model."""
    return ProjectItem(
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        status_label=row.status_label,
        reason=row.reason,
        host=row.host,
        canonical_url=row.canonical_url,
        stars=row.stars,
        forks=row.forks,
        open_issues=row.open_issues,
        pushed_at=row.pushed_at,
        license=row.license,
        development_status=row.development_status,
        last_updated=row.last_updated,
    )


@router.get("/projects", response_model=ProjectsResponse)
def list_projects(
    status: str | None = Query(default=None, description="Filter by status label"),
    host: str | None = Query(default=None, description="Filter by repository host"),
    search: str | None = Query(default=None, description="Case-insensitive name search"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = DB_SESSION,
) -> ProjectsResponse:
    if status is not None and status not in VALID_STATUS_LABELS:
        raise HTTPException(
            status_code=422, detail=f"Invalid status filter. Must be one of: {sorted(VALID_STATUS_LABELS)}"
        )

    query, status_sq = build_projects_query(db)
    query = apply_project_filters(query, status_sq, status=status, host=host, search=search)

    query = query.add_columns(func.count().over().label("_total"))
    rows = query.order_by(Project.name).offset(offset).limit(limit).all()

    total: int = getattr(rows[0], "_total", 0) if rows else 0

    return ProjectsResponse(
        total=total,
        limit=limit,
        offset=offset,
        data=[_row_to_project_item(r) for r in rows],
    )


@router.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = DB_SESSION) -> SummaryResponse:
    ls_sq = latest_status_subq(db)
    status_sq = db.query(ProjectStatusSnapshot).subquery()

    status_counts_raw = (
        db.query(status_sq.c.status_label, func.count(status_sq.c.project_id).label("cnt"))
        .join(ls_sq, ls_sq.c.project_id == status_sq.c.project_id)
        .filter(status_sq.c.observed_at == ls_sq.c.max_observed)
        .group_by(status_sq.c.status_label)
        .all()
    )

    status_counts: dict[str, int] = {s.value: 0 for s in StatusLabel}
    for label, cnt in status_counts_raw:
        if label in status_counts:
            status_counts[label] = cnt

    total_projects = db.query(func.count(Project.id)).scalar() or 0
    total_with_repo = (
        db.query(func.count(Repository.id)).join(Project, Project.id == Repository.project_id).scalar()
    ) or 0
    total_without_repo = total_projects - total_with_repo
    unsupported_count = (
        db.query(func.count(Repository.id))
        .join(Project, Project.id == Repository.project_id)
        .filter(Repository.is_supported.is_(False))
        .scalar()
    ) or 0

    return SummaryResponse(
        Archived=status_counts[StatusLabel.ARCHIVED],
        **{"Data error": status_counts[StatusLabel.DATA_ERROR]},
        Unknown=status_counts[StatusLabel.UNKNOWN],
        Active=status_counts[StatusLabel.ACTIVE],
        Slow=status_counts[StatusLabel.SLOW],
        Stale=status_counts[StatusLabel.STALE],
        total=total_projects,
        total_with_repo=total_with_repo,
        total_without_repo=total_without_repo,
        unsupported_host_count=unsupported_count,
    )
