"""CSV export routes."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.queries import apply_project_filters, build_projects_query
from app.core.status import VALID_STATUS_LABELS
from app.db.models import Project
from app.db.session import get_db

router = APIRouter(prefix="/exports")

DB_SESSION = Depends(get_db)

MAX_EXPORT_ROWS = 10_000

CSV_COLUMNS = [
    "project_name",
    "status",
    "host",
    "repository_url",
    "stars",
    "forks",
    "open_issues",
    "last_push_date",
    "license",
    "development_status",
    "reason",
]


@router.get("/projects.csv")
def export_projects_csv(
    status: str | None = Query(default=None, description="Filter by status label"),
    host: str | None = Query(default=None, description="Filter by repository host"),
    search: str | None = Query(default=None, description="Case-insensitive name search"),
    db: Session = DB_SESSION,
) -> StreamingResponse:
    if status is not None and status not in VALID_STATUS_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter. Must be one of: {sorted(VALID_STATUS_LABELS)}",
        )

    query, status_sq = build_projects_query(db)
    query = apply_project_filters(query, status_sq, status=status, host=host, search=search)

    rows = query.order_by(Project.name).limit(MAX_EXPORT_ROWS).all()

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_NONNUMERIC)
    writer.writeheader()

    for row in rows:
        last_push = row.pushed_at
        if last_push is not None:
            last_push = last_push.isoformat()
        writer.writerow(
            {
                "project_name": row.name,
                "status": row.status_label,
                "host": row.host,
                "repository_url": row.canonical_url,
                "stars": row.stars,
                "forks": row.forks,
                "open_issues": row.open_issues,
                "last_push_date": last_push,
                "license": row.license,
                "development_status": row.development_status,
                "reason": row.reason,
            }
        )

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=projects.csv"},
    )
