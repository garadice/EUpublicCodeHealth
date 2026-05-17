"""Integration tests for the status classification pipeline step.

Tests verify that classify_project_statuses correctly creates
ProjectStatusSnapshot records based on repository metrics.

Requires a running PostgreSQL instance on port 5434.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Base,
    CatalogSource,
    PipelineRun,
    Project,
    ProjectStatusSnapshot,
    Repository,
    RepositoryMetricsSnapshot,
)
from pipelines.classify_status import classify_project_statuses

DB_URL = "postgresql+psycopg://eupublicode:eupublicode@localhost:5434/eupublicode_test"

_seed_counter = 0


def _reset_schema(engine: Engine) -> None:
    db_name = str(engine.url).rsplit("/", 1)[-1]
    if "test" not in db_name:
        raise RuntimeError(f"Refusing to drop schema on non-test database: {engine.url}")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO eupublicode"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def _seed_project_with_repo(
    session: Session,
    *,
    host: str = "github",
    owner: str = "org",
    repo_name: str = "repo",
    is_supported: bool = True,
) -> tuple[Project, Repository]:
    """Insert a project + repository for testing."""
    global _seed_counter
    _seed_counter += 1

    source = session.get(CatalogSource, "developers_italia")
    if source is None:
        source = CatalogSource(source_id="developers_italia", name="Developers Italia", country="IT")
        session.add(source)
        session.flush()

    project = Project(
        source_id="developers_italia",
        source_project_id=f"classify-test-{_seed_counter}",
        name=f"Test Project {_seed_counter}",
    )
    session.add(project)
    session.flush()

    repo = Repository(
        project_id=project.id,
        canonical_url=f"https://github.com/{owner}/{repo_name}-{_seed_counter}",
        host=host,
        owner=owner,
        repo_name=repo_name,
        is_supported=is_supported,
    )
    session.add(repo)
    session.flush()
    session.commit()
    return project, repo


def _add_metrics_snapshot(
    session: Session,
    repo: Repository,
    run_id: int,
    *,
    api_status: str = "success",
    archived: bool = False,
    pushed_at: datetime | None = None,
    stars: int = 10,
) -> RepositoryMetricsSnapshot:
    snap = RepositoryMetricsSnapshot(
        repository_id=repo.id,
        run_id=run_id,
        api_status=api_status,
        archived=archived,
        pushed_at=pushed_at,
        stars=stars,
        forks=5,
        open_issues=3,
    )
    session.add(snap)
    session.flush()
    return snap


@pytest.fixture()
def db_session() -> Session:
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


class TestActiveClassification:
    def test_active_project_gets_active_label(self, db_session: Session) -> None:
        project, repo = _seed_project_with_repo(db_session, owner="active-org", repo_name="active-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _add_metrics_snapshot(db_session, repo, run.id, pushed_at=datetime.now(UTC) - timedelta(days=30))

        result = classify_project_statuses(db_session, run.id)

        assert result.classified_count == 1
        assert result.label_counts.get("Active") == 1

        snapshot = db_session.query(ProjectStatusSnapshot).first()
        assert snapshot is not None
        assert snapshot.status_label == "Active"
        assert snapshot.project_id == project.id
        assert snapshot.repository_id == repo.id
        assert snapshot.run_id == run.id


class TestSlowAndStaleClassification:
    def test_slow_project(self, db_session: Session) -> None:
        _project, repo = _seed_project_with_repo(db_session, owner="slow-org", repo_name="slow-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _add_metrics_snapshot(db_session, repo, run.id, pushed_at=datetime.now(UTC) - timedelta(days=200))

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Slow") == 1

    def test_stale_project(self, db_session: Session) -> None:
        _project, repo = _seed_project_with_repo(db_session, owner="stale-org", repo_name="stale-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _add_metrics_snapshot(db_session, repo, run.id, pushed_at=datetime.now(UTC) - timedelta(days=500))

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Stale") == 1


class TestArchivedClassification:
    def test_archived_overrides_active(self, db_session: Session) -> None:
        _seed_project_with_repo(db_session, owner="archived-org", repo_name="archived-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _, repo = _get_latest_project_repo(db_session)
        _add_metrics_snapshot(db_session, repo, run.id, archived=True, pushed_at=datetime.now(UTC) - timedelta(days=5))

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Archived") == 1

        snapshot = db_session.query(ProjectStatusSnapshot).first()
        assert snapshot is not None
        assert "archived" in (snapshot.data_quality_flags or "")


class TestUnknownClassification:
    def test_no_repository_creates_unknown_with_placeholder(self, db_session: Session) -> None:
        source = CatalogSource(source_id="developers_italia", name="Developers Italia", country="IT")
        db_session.add(source)
        db_session.flush()

        project = Project(source_id="developers_italia", source_project_id="no-repo-proj", name="No Repo")
        db_session.add(project)
        db_session.commit()

        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Unknown") == 1

        snapshot = db_session.query(ProjectStatusSnapshot).first()
        assert snapshot is not None
        assert snapshot.status_label == "Unknown"
        assert "no_repository" in (snapshot.data_quality_flags or "")

    def test_unsupported_host_no_snapshot(self, db_session: Session) -> None:
        _seed_project_with_repo(db_session, host="gitlab", is_supported=False, owner="gl-org", repo_name="gl-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Unknown") == 1


class TestDataErrorClassification:
    def test_not_found_api_status(self, db_session: Session) -> None:
        _seed_project_with_repo(db_session, owner="nf-org", repo_name="nf-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _, repo = _get_latest_project_repo(db_session)
        _add_metrics_snapshot(db_session, repo, run.id, api_status="not_found")

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Data error") == 1

        snapshot = db_session.query(ProjectStatusSnapshot).first()
        assert snapshot is not None
        assert "repo_not_found" in (snapshot.data_quality_flags or "")

    def test_error_api_status(self, db_session: Session) -> None:
        _seed_project_with_repo(db_session, owner="err-org", repo_name="err-repo")
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _, repo = _get_latest_project_repo(db_session)
        _add_metrics_snapshot(db_session, repo, run.id, api_status="error")

        result = classify_project_statuses(db_session, run.id)
        assert result.label_counts.get("Data error") == 1


class TestAppendOnlyStatusSnapshots:
    def test_running_twice_creates_two_snapshots(self, db_session: Session) -> None:
        _seed_project_with_repo(db_session, owner="append-org", repo_name="append-repo")
        run1 = PipelineRun(source_name="test", status="running")
        db_session.add(run1)
        db_session.flush()

        _, repo = _get_latest_project_repo(db_session)
        _add_metrics_snapshot(db_session, repo, run1.id, pushed_at=datetime.now(UTC) - timedelta(days=5))

        classify_project_statuses(db_session, run1.id)

        # Second run
        run2 = PipelineRun(source_name="test", status="running")
        db_session.add(run2)
        db_session.flush()

        classify_project_statuses(db_session, run2.id)

        snapshots = db_session.query(ProjectStatusSnapshot).all()
        assert len(snapshots) == 2
        assert snapshots[0].run_id != snapshots[1].run_id


class TestMultipleProjects:
    def test_mixed_labels_across_projects(self, db_session: Session) -> None:
        # Active project
        _p1, r1 = _seed_project_with_repo(db_session, owner="active", repo_name="repo1")
        # Stale project
        _p2, r2 = _seed_project_with_repo(db_session, owner="stale", repo_name="repo2")
        # No repo project
        source = db_session.get(CatalogSource, "developers_italia")
        if source is None:
            source = CatalogSource(source_id="developers_italia", name="Developers Italia", country="IT")
            db_session.add(source)
            db_session.flush()
        p3 = Project(source_id="developers_italia", source_project_id="no-repo-multi", name="No Repo Multi")
        db_session.add(p3)
        db_session.commit()

        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        _add_metrics_snapshot(db_session, r1, run.id, pushed_at=datetime.now(UTC) - timedelta(days=10))
        _add_metrics_snapshot(db_session, r2, run.id, pushed_at=datetime.now(UTC) - timedelta(days=400))

        result = classify_project_statuses(db_session, run.id)

        assert result.total_projects == 3
        assert result.classified_count == 3
        assert result.label_counts.get("Active") == 1
        assert result.label_counts.get("Stale") == 1
        assert result.label_counts.get("Unknown") == 1


class TestEmptyDatabase:
    def test_no_projects_returns_empty(self, db_session: Session) -> None:
        run = PipelineRun(source_name="test", status="running")
        db_session.add(run)
        db_session.flush()

        result = classify_project_statuses(db_session, run.id)

        assert result.total_projects == 0
        assert result.classified_count == 0
        assert result.label_counts == {}


def _get_latest_project_repo(session: Session) -> tuple[Project, Repository]:
    """Get the most recently created project and its repo."""
    repo = session.query(Repository).order_by(Repository.created_at.desc()).first()
    assert repo is not None
    project = session.get(Project, repo.project_id)
    assert project is not None
    return project, repo
