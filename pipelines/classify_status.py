"""Pipeline step: Classify project status.

Applies deterministic status labels to projects based on
the latest repository metrics snapshots. Creates append-only
ProjectStatusSnapshot records for every project-repository pair.

Status labels and priority (from app/core/status.py):
1. Archived — GitHub archived flag is true
2. Data error — supported host returned API error
3. Unknown — unsupported host, missing repo URL
4. Active — latest push within 90 days
5. Slow — latest push 91-365 days ago
6. Stale — latest push >365 days ago
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.status import StatusLabel, classify_status
from app.db.models import Project, ProjectStatusSnapshot, Repository, RepositoryMetricsSnapshot

logger = get_logger(__name__)


@dataclass
class ClassifyResult:
    """Result of the status classification pipeline step."""

    total_projects: int = 0
    classified_count: int = 0
    skipped_count: int = 0
    label_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _classify_repository(
    repo: Repository,
    snapshot: RepositoryMetricsSnapshot | None,
) -> tuple[StatusLabel, str, list[str]]:
    """Classify a single repository based on its latest metrics.

    Returns:
        Tuple of (status_label, reason, data_quality_flags).
    """
    quality_flags: list[str] = []

    # No snapshot at all — depends on host
    if snapshot is None:
        if not repo.is_supported:
            return StatusLabel.UNKNOWN, "Repository host not supported in MVP", ["unsupported_host"]
        return StatusLabel.UNKNOWN, "No metrics snapshot available", ["no_snapshot"]

    # Snapshot exists but API call failed
    if snapshot.api_status in ("not_found", "error", "rate_limited"):
        if snapshot.api_status == "not_found":
            quality_flags.append("repo_not_found")
        elif snapshot.api_status == "rate_limited":
            quality_flags.append("rate_limited")
        else:
            quality_flags.append("api_error")
        return (
            StatusLabel.DATA_ERROR,
            f"Supported host returned API error ({snapshot.api_status})",
            quality_flags,
        )

    # Successful snapshot — apply classification rules
    if snapshot.archived is not None and snapshot.archived:
        quality_flags.append("archived")

    # Unsupported host shouldn't have successful snapshots, but handle defensively
    if not repo.is_supported:
        return StatusLabel.UNKNOWN, "Repository host not supported in MVP", ["unsupported_host"]

    has_repo = True
    pushed_at = snapshot.pushed_at
    archived = snapshot.archived

    label, reason = classify_status(
        pushed_at=pushed_at,
        archived=archived,
        has_repo=has_repo,
    )

    return label, reason, quality_flags


def classify_project_statuses(session: Session, run_id: int) -> ClassifyResult:
    """Classify status for all projects based on latest metrics.

    For each project, finds its primary repository, gets the latest
    metrics snapshot, applies classification rules, and creates a
    ProjectStatusSnapshot record.

    Args:
        session: Active SQLAlchemy session.
        run_id: ID of the current pipeline run.

    Returns:
        ClassifyResult with counts and any errors.
    """
    result = ClassifyResult()

    projects = session.query(Project).all()
    result.total_projects = len(projects)

    if not projects:
        logger.info("No projects to classify")
        return result

    all_repos = session.query(Repository).all()
    repos_by_project: dict[str, list[Repository]] = {}
    for r in all_repos:
        repos_by_project.setdefault(r.project_id, []).append(r)

    latest_sq = (
        session.query(
            RepositoryMetricsSnapshot.repository_id,
            func.max(RepositoryMetricsSnapshot.observed_at).label("max_obs"),
        )
        .group_by(RepositoryMetricsSnapshot.repository_id)
        .subquery()
    )
    latest_metrics_rows = (
        session.query(RepositoryMetricsSnapshot)
        .join(
            latest_sq,
            (RepositoryMetricsSnapshot.repository_id == latest_sq.c.repository_id)
            & (RepositoryMetricsSnapshot.observed_at == latest_sq.c.max_obs),
        )
        .all()
    )
    metrics_by_repo: dict[str, RepositoryMetricsSnapshot] = {m.repository_id: m for m in latest_metrics_rows}

    placeholder_cache: dict[str, str] = {}

    logger.info("Classifying status for %d projects", len(projects))

    for project in projects:
        repos = repos_by_project.get(project.id, [])

        if not repos:
            repo_id = placeholder_cache.get(project.id)
            if repo_id is None:
                repo_id = _placeholder_repo_id(session, project.id)
                placeholder_cache[project.id] = repo_id

            snapshot = ProjectStatusSnapshot(
                project_id=project.id,
                repository_id=repo_id,
                run_id=run_id,
                status_label=StatusLabel.UNKNOWN,
                reason="No repository URL found",
                data_quality_flags=json.dumps(["no_repository"]),
            )
            session.add(snapshot)
            result.classified_count += 1
            result.label_counts["Unknown"] = result.label_counts.get("Unknown", 0) + 1
            continue

        repo = repos[0]
        latest_metrics = metrics_by_repo.get(repo.id)
        label, reason, quality_flags = _classify_repository(repo, latest_metrics)

        quality_json = json.dumps(quality_flags) if quality_flags else None

        snapshot = ProjectStatusSnapshot(
            project_id=project.id,
            repository_id=repo.id,
            run_id=run_id,
            status_label=str(label),
            reason=reason,
            data_quality_flags=quality_json,
        )
        session.add(snapshot)

        result.classified_count += 1
        label_str = str(label)
        result.label_counts[label_str] = result.label_counts.get(label_str, 0) + 1

    session.flush()

    logger.info(
        "Classification complete: %d projects classified — %s",
        result.classified_count,
        ", ".join(f"{k}: {v}" for k, v in sorted(result.label_counts.items())),
    )

    return result


def _placeholder_repo_id(session: Session, project_id: str) -> str:
    """Get a repository ID for projects with no repository.

    Creates a placeholder repository row if needed so the FK
    constraint on ProjectStatusSnapshot is satisfied.
    """
    existing = session.query(Repository).filter(Repository.project_id == project_id, Repository.host == "none").first()
    if existing is not None:
        return existing.id

    placeholder = Repository(
        project_id=project_id,
        canonical_url=f"placeholder://no-repo/{project_id}",
        host="none",
        owner=None,
        repo_name=None,
        is_supported=False,
        last_resolution_status="no_repository",
    )
    session.add(placeholder)
    session.flush()
    return placeholder.id
