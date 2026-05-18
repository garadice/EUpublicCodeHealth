"""Pipeline step: Enrich repositories with GitHub metrics.

For each GitHub-hosted repository in the database, fetches current metrics
from the GitHub API and stores them as append-only snapshots. Non-GitHub
repositories are skipped (they will be classified as Unknown in Phase 5).

Features:
- Batch processing with configurable batch size for checkpointing
- Append-only snapshots (never overwrites historical data)
- Graceful handling of rate limits, 404s, and network errors
- Pipeline run tracking with counts and error summaries
- Concurrent GitHub API requests with semaphore limiting
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.sanitize import build_error_summary
from app.db.models import PipelineRun, Repository, RepositoryMetricsSnapshot
from connectors.github_client import (
    GitHubRepoMetrics,
    fetch_repo_metrics,
    make_github_client,
)

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 50
"""Number of repositories to process before committing a checkpoint."""

CONCURRENT_REQUESTS = 10
"""Maximum number of concurrent GitHub API requests."""


@dataclass
class EnrichResult:
    """Result of the enrichment pipeline step."""

    total_repos: int = 0
    github_repos: int = 0
    non_github_repos: int = 0
    success_count: int = 0
    not_found_count: int = 0
    rate_limited_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


def _create_snapshot(
    session: Session,
    repository_id: str,
    run_id: int,
    metrics: GitHubRepoMetrics,
) -> None:
    """Create a RepositoryMetricsSnapshot from fetched metrics.

    Snapshots are always appended — never updated or deleted.
    """
    snapshot = RepositoryMetricsSnapshot(
        repository_id=repository_id,
        run_id=run_id,
        stars=metrics.stars if metrics.api_status == "success" else None,
        forks=metrics.forks if metrics.api_status == "success" else None,
        open_issues=metrics.open_issues if metrics.api_status == "success" else None,
        archived=metrics.archived if metrics.api_status == "success" else None,
        pushed_at=metrics.pushed_at if metrics.api_status == "success" else None,
        latest_commit_at=None,  # Requires separate API call, deferred post-MVP
        license_key=metrics.license_key if metrics.api_status == "success" else None,
        topics=json.dumps(metrics.topics) if metrics.api_status == "success" else None,
        api_status=metrics.api_status,
    )
    session.add(snapshot)


def _update_repository_status(
    session: Session,
    repository_id: str,
    api_status: str,
) -> None:
    """Update the repository's last_resolution_status field."""
    repo = session.get(Repository, repository_id)
    if repo is not None:
        repo.last_resolution_status = api_status
    else:
        logger.warning("Repository %s not found for status update", repository_id)


def _track_outcome(
    result: EnrichResult,
    metrics: GitHubRepoMetrics,
) -> None:
    """Track the outcome of a single repo enrichment in result counters."""
    if metrics.api_status == "success":
        result.success_count += 1
    elif metrics.api_status == "not_found":
        result.not_found_count += 1
    elif metrics.api_status == "rate_limited":
        result.rate_limited_count += 1
        result.errors.append(f"Rate limited: {metrics.owner}/{metrics.repo_name}")
    else:
        result.error_count += 1
        error_msg = metrics.error_message or "Unknown error"
        result.errors.append(f"{metrics.owner}/{metrics.repo_name}: {error_msg}")


async def enrich_repositories(
    session: Session,
    run_id: int,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> EnrichResult:
    """Enrich all GitHub repositories with current metrics.

    Queries the database for all repositories with ``host='github'``
    and ``is_supported=True``, fetches metrics for each via the GitHub
    API, and stores results as append-only snapshots.

    Processing is committed in batches of ``batch_size`` to allow
    partial progress recovery on failure. Requests are made concurrently
    with a semaphore limiting to ``CONCURRENT_REQUESTS`` in-flight calls.

    Args:
        session: Active SQLAlchemy session.
        run_id: ID of the current pipeline run.
        batch_size: Number of repos to process per checkpoint commit.

    Returns:
        EnrichResult with counts and error details.
    """
    result = EnrichResult()

    repos = session.query(Repository).filter(Repository.host == "github", Repository.is_supported.is_(True)).all()
    result.total_repos = len(repos)
    result.github_repos = len(repos)

    non_github_count = session.query(Repository).filter(~(Repository.host == "github")).count()
    result.non_github_repos = non_github_count

    if not repos:
        logger.info("No GitHub repositories to enrich")
        return result

    logger.info(
        "Enriching %d GitHub repositories (batch_size=%d, concurrency=%d)",
        len(repos),
        batch_size,
        CONCURRENT_REQUESTS,
    )

    # Separate skippable repos (missing owner/name) from fetchable ones
    fetchable: list[Repository] = []
    for repo in repos:
        if not repo.owner or not repo.repo_name:
            logger.warning(
                "Skipping repo %s (id=%s): missing owner/repo_name",
                repo.canonical_url,
                repo.id,
            )
            result.skipped_count += 1
        else:
            fetchable.append(repo)

    if not fetchable:
        logger.info("All repos skipped — nothing to fetch")
        return result

    # Fetch metrics concurrently with semaphore-limited parallelism
    async with make_github_client() as client:
        semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

        async def _fetch_one(repo: Repository) -> GitHubRepoMetrics:
            if repo.owner is None or repo.repo_name is None:
                raise ValueError(f"Missing owner/repo_name for repo {repo.id}")
            async with semaphore:
                return await fetch_repo_metrics(client, repo.owner, repo.repo_name)

        tasks = [_fetch_one(repo) for repo in fetchable]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results in order and checkpoint in batches
    for idx, (repo, raw) in enumerate(zip(fetchable, raw_results, strict=True), 1):
        if repo.owner is None or repo.repo_name is None:
            continue
        if isinstance(raw, BaseException):
            logger.exception(
                "Unexpected error fetching %s/%s",
                repo.owner,
                repo.repo_name,
            )
            error_metrics = GitHubRepoMetrics.error(repo.owner, repo.repo_name, "error", str(raw))
            _create_snapshot(session, repo.id, run_id, error_metrics)
            _update_repository_status(session, repo.id, "error")
            result.error_count += 1
            result.errors.append(f"{repo.owner}/{repo.repo_name}: {raw}")
        else:
            _create_snapshot(session, repo.id, run_id, raw)
            _update_repository_status(session, repo.id, raw.api_status)
            _track_outcome(result, raw)

        if idx % batch_size == 0:
            session.flush()
            session.commit()
            logger.info(
                "Checkpoint: %d/%d repos processed (%d success, %d errors)",
                idx,
                len(fetchable),
                result.success_count,
                result.error_count + result.not_found_count + result.rate_limited_count,
            )

    # Final commit for remaining repos
    session.flush()
    session.commit()

    logger.info(
        "Enrichment complete: %d repos processed — %d success, %d not_found, %d rate_limited, %d errors, %d skipped",
        result.github_repos,
        result.success_count,
        result.not_found_count,
        result.rate_limited_count,
        result.error_count,
        result.skipped_count,
    )

    return result


async def run_enrichment() -> EnrichResult:
    """Run the enrichment pipeline step with its own session.

    Creates a pipeline run record, enriches all GitHub repositories,
    and updates the pipeline run with final counts.
    """
    from app.db.session import get_session_factory

    factory = get_session_factory()
    session = factory()
    run: PipelineRun | None = None
    try:
        run = PipelineRun(
            source_name="github_enrichment",
            status="running",
        )
        session.add(run)
        session.flush()

        run_id = run.id

        result = await enrich_repositories(session, run_id)

        run.records_seen = result.github_repos
        run.records_loaded = result.success_count
        run.errors_count = len(result.errors)
        run.error_summary = build_error_summary(result.errors)
        run.status = "error" if result.error_count > 0 else "success"
        run.finished_at = datetime.now(UTC)
        session.commit()

        return result
    except Exception:
        logger.exception("Enrichment pipeline run failed")
        if run is not None:
            try:
                run.status = "error"
                run.finished_at = datetime.now(UTC)
                run.error_summary = "Enrichment failed with exception"
                session.commit()
            except Exception:
                session.rollback()
        raise
    finally:
        session.close()
