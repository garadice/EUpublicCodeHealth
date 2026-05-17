"""Integration tests for DB persistence operations.

Tests verify that persist_ingestion_results correctly upserts
catalog_sources, projects, repositories, and pipeline_runs.
"""

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.publiccode_parser import ParsedPubliccode
from app.core.url_normalize import HostType, NormalizedURL
from app.db.models import Base, CatalogSource, PipelineRun, Project, Repository
from pipelines.ingest_catalog import (
    IngestedProject,
    IngestResult,
    persist_ingestion_results,
)

DB_URL = "postgresql+psycopg://eupublicode:eupublicode@localhost:5434/eupublicode_test"


def _reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO eupublicode"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))


def _make_project(
    source_project_id: str = "test-proj-1",
    raw_url: str = "https://github.com/org/repo",
    host: HostType = HostType.GITHUB,
    owner: str | None = "org",
    repo_name: str | None = "repo",
    name: str = "Test Project",
    parse_error: str | None = None,
) -> IngestedProject:
    normalized_url = NormalizedURL(
        canonical_url=f"https://github.com/{owner}/{repo_name}" if host == HostType.GITHUB else raw_url,
        host=host,
        owner=owner,
        repo_name=repo_name,
        is_supported=host == HostType.GITHUB,
    )
    return IngestedProject(
        source_id="developers_italia",
        source_project_id=source_project_id,
        raw_url=raw_url,
        parsed=ParsedPubliccode(
            name=name,
            description="A test project",
            development_status="stable",
            license="MIT",
            software_type="standalone",
            parse_error=parse_error,
        ),
        normalized_url=normalized_url,
        aliases=[],
        active=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 6, 1, tzinfo=UTC),
    )


def _make_result(
    projects: list[IngestedProject] | None = None,
    total_fetched: int | None = None,
    errors: list[str] | None = None,
) -> IngestResult:
    if projects is None:
        projects = [_make_project()]
    return IngestResult(
        projects=projects,
        total_fetched=total_fetched if total_fetched is not None else len(projects),
        total_parsed_ok=sum(1 for p in projects if p.parsed.parse_error is None),
        parse_errors=sum(1 for p in projects if p.parsed.parse_error is not None),
        github_count=sum(1 for p in projects if p.normalized_url.host == HostType.GITHUB),
        gitlab_count=sum(1 for p in projects if p.normalized_url.host == HostType.GITLAB),
        unsupported_count=sum(1 for p in projects if p.normalized_url.host == HostType.UNSUPPORTED),
        invalid_url_count=sum(1 for p in projects if p.normalized_url.host == HostType.INVALID),
        errors=errors or [],
    )


@pytest.fixture()
def db_session() -> Session:
    """Create a fresh test database session with clean tables."""
    engine = create_engine(DB_URL)
    _reset_schema(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    _reset_schema(engine)
    engine.dispose()


class TestUpsertIdempotency:
    def test_persist_same_project_twice_creates_one_row(self, db_session: Session) -> None:
        result = _make_result()
        persist_ingestion_results(db_session, result)
        persist_ingestion_results(db_session, result)

        project_count = db_session.query(Project).count()
        assert project_count == 1

        repo_count = db_session.query(Repository).count()
        assert repo_count == 1

    def test_updated_at_changes_on_upsert(self, db_session: Session) -> None:
        result = _make_result()
        persist_ingestion_results(db_session, result)

        result2 = _make_result(projects=[_make_project(name="Updated Name")])
        persist_ingestion_results(db_session, result2)

        db_session.expire_all()
        updated_project = db_session.query(Project).first()
        assert updated_project is not None
        assert updated_project.name == "Updated Name"


class TestProjectFieldsCorrect:
    def test_all_project_fields_match(self, db_session: Session) -> None:
        project = _make_project(
            source_project_id="proj-abc",
            name="My Cool Project",
        )
        result = _make_result(projects=[project])
        persist_ingestion_results(db_session, result)

        db_project = db_session.query(Project).first()
        assert db_project is not None
        assert db_project.source_id == "developers_italia"
        assert db_project.source_project_id == "proj-abc"
        assert db_project.name == "My Cool Project"
        assert db_project.description == "A test project"
        assert db_project.development_status == "stable"
        assert db_project.license == "MIT"
        assert db_project.software_type == "standalone"
        assert db_project.source_url == "https://github.com/org/repo"

    def test_catalog_source_created(self, db_session: Session) -> None:
        result = _make_result()
        persist_ingestion_results(db_session, result)

        source = db_session.query(CatalogSource).first()
        assert source is not None
        assert source.source_id == "developers_italia"
        assert source.name == "Developers Italia"
        assert source.country == "IT"


class TestRepositoryUpsert:
    def test_repository_created_for_github_project(self, db_session: Session) -> None:
        result = _make_result()
        persist_ingestion_results(db_session, result)

        repo = db_session.query(Repository).first()
        assert repo is not None
        assert repo.canonical_url == "https://github.com/org/repo"
        assert repo.host == "github"
        assert repo.owner == "org"
        assert repo.repo_name == "repo"
        assert repo.is_supported is True

    def test_repository_upsert_updates_fields(self, db_session: Session) -> None:
        project1 = _make_project()
        result1 = _make_result(projects=[project1])
        persist_ingestion_results(db_session, result1)

        db_session.expire_all()
        first_repo = db_session.query(Repository).first()
        assert first_repo is not None
        first_id = first_repo.id

        project2 = IngestedProject(
            source_id="developers_italia",
            source_project_id="test-proj-1",
            raw_url="https://github.com/org/repo",
            parsed=ParsedPubliccode(name="Updated", description="Updated desc"),
            normalized_url=NormalizedURL(
                canonical_url="https://github.com/org/repo",
                host=HostType.GITHUB,
                owner="new-org",
                repo_name="new-repo",
                is_supported=True,
            ),
            aliases=[],
            active=True,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 6, 1, tzinfo=UTC),
        )
        result2 = _make_result(projects=[project2])
        persist_ingestion_results(db_session, result2)

        db_session.expire_all()
        repos = db_session.query(Repository).all()
        assert len(repos) == 1
        assert repos[0].owner == "new-org"
        assert repos[0].repo_name == "new-repo"
        assert repos[0].id == first_id


class TestPipelineRunRecorded:
    def test_pipeline_run_created_on_success(self, db_session: Session) -> None:
        result = _make_result(total_fetched=5)
        persist_ingestion_results(db_session, result)

        run = db_session.query(PipelineRun).first()
        assert run is not None
        assert run.source_name == "developers_italia"
        assert run.records_seen == 5
        assert run.records_loaded == 1
        assert run.errors_count == 0
        assert run.error_summary is None
        assert run.status == "success"

    def test_pipeline_run_partial_with_errors(self, db_session: Session) -> None:
        result = _make_result(
            total_fetched=10,
            errors=["HTTP 500 on page 2", "Timeout on page 3"],
        )
        persist_ingestion_results(db_session, result)

        run = db_session.query(PipelineRun).first()
        assert run is not None
        assert run.status == "partial"
        assert run.errors_count == 2
        assert "HTTP 500" in (run.error_summary or "")


class TestUnsupportedHost:
    def test_unsupported_url_gets_is_supported_false(self, db_session: Session) -> None:
        project = _make_project(
            raw_url="https://bitbucket.org/org/repo",
            host=HostType.UNSUPPORTED,
            owner=None,
            repo_name=None,
        )
        result = _make_result(projects=[project])
        persist_ingestion_results(db_session, result)

        repo = db_session.query(Repository).first()
        assert repo is not None
        assert repo.is_supported is False
        assert repo.host == "unsupported"

    def test_invalid_url_skips_repository(self, db_session: Session) -> None:
        project = _make_project(
            source_project_id="no-url-proj",
            raw_url="",
            host=HostType.INVALID,
            owner=None,
            repo_name=None,
        )
        result = _make_result(projects=[project])
        persist_ingestion_results(db_session, result)

        repo_count = db_session.query(Repository).count()
        assert repo_count == 0


class TestMigrationSchema:
    def _reset_and_migrate(self) -> Engine:
        import os

        import app.core.config
        import app.db.session

        engine = create_engine(DB_URL)
        _reset_schema(engine)

        original_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = DB_URL
        app.core.config.get_settings.cache_clear()
        app.db.session._engine = None

        try:
            alembic_cfg = AlembicConfig("alembic.ini")
            command.upgrade(alembic_cfg, "head")
        finally:
            if original_db_url is not None:
                os.environ["DATABASE_URL"] = original_db_url
            else:
                os.environ.pop("DATABASE_URL", None)
            app.core.config.get_settings.cache_clear()
            if app.db.session._engine is not None:
                app.db.session._engine.dispose()
            app.db.session._engine = None

        return engine

    def _cleanup(self, engine: Engine) -> None:
        _reset_schema(engine)
        engine.dispose()

    def test_migration_creates_all_tables(self) -> None:
        engine = self._reset_and_migrate()
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())

            expected = {
                "catalog_sources",
                "projects",
                "repositories",
                "repository_metrics_snapshots",
                "project_status_snapshots",
                "pipeline_runs",
                "alembic_version",
            }
            assert expected.issubset(tables)
        finally:
            self._cleanup(engine)

    def test_key_columns_exist(self) -> None:
        engine = self._reset_and_migrate()
        try:
            inspector = inspect(engine)

            project_columns = {col["name"] for col in inspector.get_columns("projects")}
            assert "id" in project_columns
            assert "source_id" in project_columns
            assert "source_project_id" in project_columns
            assert "name" in project_columns

            repo_columns = {col["name"] for col in inspector.get_columns("repositories")}
            assert "id" in repo_columns
            assert "project_id" in repo_columns
            assert "canonical_url" in repo_columns
            assert "host" in repo_columns
        finally:
            self._cleanup(engine)

    def test_unique_constraints_exist(self) -> None:
        engine = self._reset_and_migrate()
        try:
            inspector = inspect(engine)

            project_constraints = inspector.get_unique_constraints("projects")
            project_uc_names = {uc["name"] for uc in project_constraints}
            assert "uq_projects_source_id_source_project_id" in project_uc_names

            repo_constraints = inspector.get_unique_constraints("repositories")
            repo_uc_names = {uc["name"] for uc in repo_constraints}
            assert any("canonical_url" in uc["column_names"] for uc in repo_constraints)
            assert any("canonical_url" in name for name in repo_uc_names)
        finally:
            self._cleanup(engine)

    def test_foreign_keys_exist(self) -> None:
        engine = self._reset_and_migrate()
        try:
            inspector = inspect(engine)

            project_fks = inspector.get_foreign_keys("projects")
            assert any(
                "source_id" in fk["constrained_columns"] and fk["referred_table"] == "catalog_sources"
                for fk in project_fks
            )

            repo_fks = inspector.get_foreign_keys("repositories")
            assert any(
                "project_id" in fk["constrained_columns"] and fk["referred_table"] == "projects" for fk in repo_fks
            )
        finally:
            self._cleanup(engine)


class TestEmptyIngestResult:
    def test_empty_result_creates_pipeline_run(self, db_session: Session) -> None:
        result = _make_result(projects=[], total_fetched=0)
        persist_ingestion_results(db_session, result)

        run = db_session.query(PipelineRun).first()
        assert run is not None
        assert run.records_seen == 0
        assert run.records_loaded == 0
        assert run.status == "success"

        project_count = db_session.query(Project).count()
        assert project_count == 0


class TestMultipleProjects:
    def test_multiple_projects_in_single_result(self, db_session: Session) -> None:
        projects = [
            _make_project(source_project_id="proj-1", name="Project One"),
            _make_project(
                source_project_id="proj-2",
                name="Project Two",
                raw_url="https://github.com/org2/repo2",
                owner="org2",
                repo_name="repo2",
            ),
            _make_project(
                source_project_id="proj-3",
                name="Project Three",
                raw_url="https://github.com/org3/repo3",
                owner="org3",
                repo_name="repo3",
            ),
        ]
        result = _make_result(projects=projects, total_fetched=3)
        persist_ingestion_results(db_session, result)

        all_projects = db_session.query(Project).order_by(Project.source_project_id).all()
        assert len(all_projects) == 3
        assert all_projects[0].name == "Project One"
        assert all_projects[1].name == "Project Two"
        assert all_projects[2].name == "Project Three"

        repo_count = db_session.query(Repository).count()
        assert repo_count == 3

        run = db_session.query(PipelineRun).first()
        assert run is not None
        assert run.records_loaded == 3


class TestMixedHostTypes:
    def test_github_and_unsupported_in_same_batch(self, db_session: Session) -> None:
        github_proj = _make_project(
            source_project_id="gh-proj",
            raw_url="https://github.com/org/repo",
            host=HostType.GITHUB,
            owner="org",
            repo_name="repo",
        )
        unsupported_proj = _make_project(
            source_project_id="unsup-proj",
            raw_url="https://bitbucket.org/x/y",
            host=HostType.UNSUPPORTED,
            owner=None,
            repo_name=None,
        )
        result = _make_result(projects=[github_proj, unsupported_proj], total_fetched=2)
        persist_ingestion_results(db_session, result)

        all_projects = db_session.query(Project).order_by(Project.source_project_id).all()
        assert len(all_projects) == 2

        repos = db_session.query(Repository).order_by(Repository.host).all()
        assert len(repos) == 2

        github_repo = db_session.query(Repository).filter_by(host="github").first()
        assert github_repo is not None
        assert github_repo.canonical_url == "https://github.com/org/repo"
        assert github_repo.is_supported is True

        unsupported_repo = db_session.query(Repository).filter_by(host="unsupported").first()
        assert unsupported_repo is not None
        assert unsupported_repo.is_supported is False
