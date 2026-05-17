"""Shared query builders for API routes.

Centralises the "latest snapshot per entity" subquery pattern used by
multiple API endpoints so that bug fixes and schema changes only need
to be applied in one place.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session


def latest_status_subq(db: Session) -> Any:
    """Return a subquery selecting the max observed_at per project."""
    from app.db.models import ProjectStatusSnapshot

    return (
        db.query(
            ProjectStatusSnapshot.project_id,
            func.max(ProjectStatusSnapshot.observed_at).label("max_observed"),
        )
        .group_by(ProjectStatusSnapshot.project_id)
        .subquery()
    )


def latest_metrics_subq(db: Session) -> Any:
    """Return a subquery selecting the max observed_at per repository."""
    from app.db.models import RepositoryMetricsSnapshot

    return (
        db.query(
            RepositoryMetricsSnapshot.repository_id,
            func.max(RepositoryMetricsSnapshot.observed_at).label("max_observed"),
        )
        .group_by(RepositoryMetricsSnapshot.repository_id)
        .subquery()
    )


def primary_repo_subq(db: Session) -> Any:
    """Return a subquery selecting one repository per project (first by id).

    This avoids row multiplication when a project has multiple repos.
    """
    from app.db.models import Repository

    return (
        db.query(
            Repository.project_id,
            func.min(Repository.id).label("primary_repo_id"),
        )
        .group_by(Repository.project_id)
        .subquery()
    )


def apply_project_filters(
    query: Any,
    status_sq: Any,
    *,
    status: str | None = None,
    host: str | None = None,
    search: str | None = None,
) -> Any:
    """Apply status, host, and name search filters to a projects query."""
    from app.db.models import Project, Repository

    if status is not None:
        query = query.filter(status_sq.c.status_label == status)
    if host is not None:
        query = query.filter(Repository.host == host)
    if search is not None:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(Project.name.ilike(f"%{escaped}%", escape="\\"))
    return query


def build_projects_query(db: Session) -> tuple[Any, Any]:
    """Build the base projects query with latest status + metrics, one row per project.

    Returns (query, status_sq) tuple so callers can apply filters on status_sq.
    """
    from app.db.models import (
        Project,
        ProjectStatusSnapshot,
        Repository,
        RepositoryMetricsSnapshot,
    )

    ls_sq = latest_status_subq(db)
    lm_sq = latest_metrics_subq(db)
    pr_sq = primary_repo_subq(db)

    status_sq = (
        db.query(
            ProjectStatusSnapshot.project_id,
            ProjectStatusSnapshot.observed_at,
            ProjectStatusSnapshot.status_label,
            ProjectStatusSnapshot.reason,
        )
        .join(
            ls_sq,
            (ProjectStatusSnapshot.project_id == ls_sq.c.project_id)
            & (ProjectStatusSnapshot.observed_at == ls_sq.c.max_observed),
        )
        .subquery()
    )

    metrics_sq = (
        db.query(
            RepositoryMetricsSnapshot.repository_id,
            RepositoryMetricsSnapshot.observed_at,
            RepositoryMetricsSnapshot.stars,
            RepositoryMetricsSnapshot.forks,
            RepositoryMetricsSnapshot.open_issues,
            RepositoryMetricsSnapshot.pushed_at,
        )
        .join(
            lm_sq,
            (RepositoryMetricsSnapshot.repository_id == lm_sq.c.repository_id)
            & (RepositoryMetricsSnapshot.observed_at == lm_sq.c.max_observed),
        )
        .subquery()
    )

    query = (
        db.query(
            Project.id.label("project_id"),
            Project.name,
            Project.description,
            Project.development_status,
            Project.license,
            Project.updated_at.label("last_updated"),
            status_sq.c.status_label,
            status_sq.c.reason,
            Repository.host,
            Repository.canonical_url,
            metrics_sq.c.stars,
            metrics_sq.c.forks,
            metrics_sq.c.open_issues,
            metrics_sq.c.pushed_at,
        )
        .outerjoin(pr_sq, pr_sq.c.project_id == Project.id)
        .outerjoin(Repository, Repository.id == pr_sq.c.primary_repo_id)
        .outerjoin(status_sq, status_sq.c.project_id == Project.id)
        .outerjoin(metrics_sq, metrics_sq.c.repository_id == Repository.id)
    )

    return query, status_sq
