"""Integration tests for the GitHub enrichment pipeline.

Tests verify that enrich_repositories correctly creates
RepositoryMetricsSnapshot records, handles various API responses,
and tracks pipeline run outcomes.

Requires a running PostgreSQL instance on port 5434.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, PipelineRun, Repository, RepositoryMetricsSnapshot
from connectors.github_client import GitHubRepoMetrics
from pipelines.enrich_repositories import enrich_repositories

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

DB_URL = "postgresql+psycopg://eupublicode:eupublicode@localhost:5434/eupublicode_test"


def _reset_schema(engine: Engine) -> None:
    """Reset schema — safety check ensures we only touch test databases."""
    db_name = str(engine.url).rsplit("/", 1)[-1]
    if "test" not in db_name:
        raise RuntimeError(f"Refusing to drop schema on non-test database: {engine.url}")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO eupublicode"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def _success_metrics(owner: str = "org", repo_name: str = "repo") -> GitHubRepoMetrics:
    return GitHubRepoMetrics(
        owner=owner,
        repo_name=repo_name,
        stars=42,
        forks=10,
        open_issues=5,
        archived=False,
        pushed_at=datetime(2024, 10, 15, 9, 0, 0, tzinfo=UTC),
        license_key="MIT",
        topics=["python", "test"],
        default_branch="main",
        html_url=f"https://github.com/{owner}/{repo_name}",
        api_status="success",
    )


def _not_found_metrics(owner: str = "org", repo_name: str = "repo") -> GitHubRepoMetrics:
    return GitHubRepoMetrics(
        owner=owner,
        repo_name=repo_name,
        stars=0,
        forks=0,
        open_issues=0,
        archived=False,
        pushed_at=None,
        license_key=None,
        topics=[],
        default_branch="main",
        html_url="",
        api_status="not_found",
        error_message="Repository not found (HTTP 404)",
    )


def _error_metrics(owner: str = "org", repo_name: str = "repo") -> GitHubRepoMetrics:
    return GitHubRepoMetrics(
        owner=owner,
        repo_name=repo_name,
        stars=0,
        forks=0,
        open_issues=0,
        archived=False,
        pushed_at=None,
        license_key=None,
        topics=[],
        default_branch="main",
        html_url="",
        api_status="error",
        error_message="HTTP 500",
    )


@pytest.fixture()
def db_session() -> Session:
    """Create a fresh test database session with clean tables."""
    global _seed_counter
    _seed_counter = 0
    engine = create_engine(DB_URL)
    _reset_schema(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    _reset_schema(engine)
    engine.dispose()


def _seed_repository(
    session: Session,
    host: str = "github",
    owner: str = "org",
    repo_name: str = "repo",
    is_supported: bool = True,
) -> Repository:
    """Insert a repository directly into the DB for testing."""
    repo = Repository(
        project_id="seed-project-id",
        canonical_url=f"https://github.com/{owner}/{repo_name}",
        host=host,
        owner=owner,
        repo_name=repo_name,
        is_supported=is_supported,
    )
    session.add(repo)
    session.flush()
    return repo


_seed_counter = 0


def _seed_project_and_repo(
    session: Session,
    *,
    host: str = "github",
    owner: str = "org",
    repo_name: str = "repo",
    is_supported: bool = True,
) -> Repository:
    """Insert a minimal project + repository for FK integrity."""
    global _seed_counter
    from app.db.models import CatalogSource, Project

    # Ensure catalog source exists
    source = session.get(CatalogSource, "developers_italia")
    if source is None:
        source = CatalogSource(source_id="developers_italia", name="Developers Italia", country="IT")
        session.add(source)
        session.flush()

    _seed_counter += 1
    project = Project(
        source_id="developers_italia",
        source_project_id=f"test-seed-proj-{_seed_counter}",
        name=f"Seed Project {_seed_counter}",
    )
    session.add(project)
    session.flush()

    repo = Repository(
        project_id=project.id,
        canonical_url=f"https://github.com/{owner}/{repo_name}",
        host=host,
        owner=owner,
        repo_name=repo_name,
        is_supported=is_supported,
    )
    session.add(repo)
    session.flush()
    session.commit()
    return repo


class TestSuccessfulEnrichment:
    @pytest.mark.asyncio
    async def test_creates_snapshot_with_correct_metrics(self, db_session: Session) -> None:
        repo = _seed_project_and_repo(db_session, owner="truelite", repo_name="python-a38")
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        mock_metrics = _success_metrics(owner="truelite", repo_name="python-a38")
        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.success_count == 1
        assert result.total_repos == 1

        snapshot = db_session.query(RepositoryMetricsSnapshot).first()
        assert snapshot is not None
        assert snapshot.repository_id == repo.id
        assert snapshot.run_id == run.id
        assert snapshot.stars == 42
        assert snapshot.forks == 10
        assert snapshot.open_issues == 5
        assert snapshot.archived is False
        assert snapshot.pushed_at == datetime(2024, 10, 15, 9, 0, 0, tzinfo=UTC)
        assert snapshot.license_key == "MIT"
        assert snapshot.api_status == "success"

        topics = json.loads(snapshot.topics) if snapshot.topics else []
        assert topics == ["python", "test"]

    @pytest.mark.asyncio
    async def test_updates_repository_last_resolution_status(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="org", repo_name="repo")
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        mock_metrics = _success_metrics()
        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            await enrich_repositories(db_session, run.id)

        repo = db_session.query(Repository).first()
        assert repo is not None
        assert repo.last_resolution_status == "success"


class TestNotFoundHandling:
    @pytest.mark.asyncio
    async def test_not_found_creates_snapshot_with_status(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="deleted", repo_name="project")
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        mock_metrics = _not_found_metrics(owner="deleted", repo_name="project")
        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.not_found_count == 1

        snapshot = db_session.query(RepositoryMetricsSnapshot).first()
        assert snapshot is not None
        assert snapshot.api_status == "not_found"
        assert snapshot.stars is None  # No metrics for non-success
        assert snapshot.pushed_at is None


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_error_repo_creates_snapshot_with_error_status(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="broken", repo_name="repo")
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        mock_metrics = _error_metrics(owner="broken", repo_name="repo")
        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.error_count == 1

        snapshot = db_session.query(RepositoryMetricsSnapshot).first()
        assert snapshot is not None
        assert snapshot.api_status == "error"


class TestAppendOnlySnapshots:
    @pytest.mark.asyncio
    async def test_running_twice_creates_two_snapshots(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="org", repo_name="repo")
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        mock_metrics = _success_metrics()
        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            await enrich_repositories(db_session, run.id)

        # Second run with a new pipeline run
        run2 = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run2)
        db_session.flush()

        with (
            patch(
                "pipelines.enrich_repositories.fetch_repo_metrics", new_callable=AsyncMock, return_value=mock_metrics
            ) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            await enrich_repositories(db_session, run2.id)

        snapshots = db_session.query(RepositoryMetricsSnapshot).all()
        assert len(snapshots) == 2
        # Both snapshots for the same repository
        assert snapshots[0].repository_id == snapshots[1].repository_id
        # But different run IDs
        assert snapshots[0].run_id != snapshots[1].run_id


class TestSkipReposWithMissingFields:
    @pytest.mark.asyncio
    async def test_repo_without_owner_is_skipped(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="org", repo_name="repo")
        # Manually clear owner
        repo = db_session.query(Repository).first()
        assert repo is not None
        repo.owner = None
        db_session.flush()

        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        with patch("pipelines.enrich_repositories.make_github_client") as mock_make:
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.skipped_count == 1
        assert result.success_count == 0

        snapshot_count = db_session.query(RepositoryMetricsSnapshot).count()
        assert snapshot_count == 0


class TestNonGitHubRepos:
    @pytest.mark.asyncio
    async def test_non_github_repos_are_counted_but_not_enriched(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, host="gitlab", owner="org", repo_name="gl-repo", is_supported=False)
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        with patch("pipelines.enrich_repositories.make_github_client") as mock_make:
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.github_repos == 0
        assert result.non_github_repos == 1
        assert result.success_count == 0

        snapshot_count = db_session.query(RepositoryMetricsSnapshot).count()
        assert snapshot_count == 0


class TestEmptyDatabase:
    @pytest.mark.asyncio
    async def test_no_repos_returns_empty_result(self, db_session: Session) -> None:
        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        with patch("pipelines.enrich_repositories.make_github_client") as mock_make:
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.total_repos == 0
        assert result.github_repos == 0
        assert result.success_count == 0


class TestBatchCheckpointing:
    @pytest.mark.asyncio
    async def test_multiple_repos_are_all_processed(self, db_session: Session) -> None:
        repos_data = [
            ("org1", "repo1"),
            ("org2", "repo2"),
            ("org3", "repo3"),
        ]
        for owner, repo_name in repos_data:
            _seed_project_and_repo(db_session, owner=owner, repo_name=repo_name)

        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        async def mock_fetch(client: object, owner: str, repo_name: str) -> GitHubRepoMetrics:
            return _success_metrics(owner=owner, repo_name=repo_name)

        with (
            patch("pipelines.enrich_repositories.fetch_repo_metrics", side_effect=mock_fetch) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id, batch_size=2)

        assert result.success_count == 3
        assert result.total_repos == 3

        snapshots = db_session.query(RepositoryMetricsSnapshot).all()
        assert len(snapshots) == 3


class TestMixedResults:
    @pytest.mark.asyncio
    async def test_mixed_success_and_not_found(self, db_session: Session) -> None:
        _seed_project_and_repo(db_session, owner="good", repo_name="repo")
        _seed_project_and_repo(db_session, owner="deleted", repo_name="repo")

        run = PipelineRun(source_name="github_enrichment", status="running")
        db_session.add(run)
        db_session.flush()

        call_count = 0

        async def mock_fetch(client: object, owner: str, repo_name: str) -> GitHubRepoMetrics:
            nonlocal call_count
            call_count += 1
            if owner == "good":
                return _success_metrics(owner=owner, repo_name=repo_name)
            return _not_found_metrics(owner=owner, repo_name=repo_name)

        with (
            patch("pipelines.enrich_repositories.fetch_repo_metrics", side_effect=mock_fetch) as _,
            patch("pipelines.enrich_repositories.make_github_client") as mock_make,
        ):
            mock_make.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
            mock_make.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await enrich_repositories(db_session, run.id)

        assert result.success_count == 1
        assert result.not_found_count == 1
        assert result.total_repos == 2

        snapshots = db_session.query(RepositoryMetricsSnapshot).order_by(RepositoryMetricsSnapshot.id).all()
        assert len(snapshots) == 2
        statuses = [s.api_status for s in snapshots]
        assert "success" in statuses
        assert "not_found" in statuses
