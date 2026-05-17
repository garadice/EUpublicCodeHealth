"""Unit tests for API routes using FastAPI TestClient with in-memory SQLite."""

import csv
import io
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.db.models import (
    Base,
    CatalogSource,
    PipelineRun,
    Project,
    ProjectStatusSnapshot,
    Repository,
    RepositoryMetricsSnapshot,
)
from app.db.session import get_db

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _override_get_db():
    db = TestSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _clean_db():
    db = TestSessionLocal()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    finally:
        db.close()


def _insert_test_data():
    db = TestSessionLocal()
    try:
        db.add(CatalogSource(source_id="src1", name="Test Catalog"))
        db.commit()

        db.add(
            PipelineRun(
                id=1,
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 1, tzinfo=UTC),
                status="completed",
                source_name="test-source",
                records_seen=10,
                records_loaded=8,
                errors_count=0,
            )
        )
        db.commit()

        db.add(
            Project(
                id="proj1",
                source_id="src1",
                source_project_id="sp1",
                name="Test Project Alpha",
                description="A test project",
                development_status="stable",
                license="MIT",
            )
        )
        db.add(
            Project(
                id="proj2",
                source_id="src1",
                source_project_id="sp2",
                name="Another Project",
                description="Second test",
            )
        )
        db.commit()

        db.add(
            Repository(
                id="repo1",
                project_id="proj1",
                canonical_url="https://github.com/test/alpha",
                host="github",
                owner="test",
                repo_name="alpha",
                is_supported=True,
            )
        )
        db.add(
            Repository(
                id="repo2",
                project_id="proj2",
                canonical_url="https://gitlab.com/test/beta",
                host="gitlab",
                owner="test",
                repo_name="beta",
                is_supported=False,
            )
        )
        db.commit()

        db.add(
            RepositoryMetricsSnapshot(
                id=1,
                repository_id="repo1",
                run_id=1,
                observed_at=datetime(2025, 1, 1, tzinfo=UTC),
                stars=100,
                forks=20,
                open_issues=5,
                pushed_at=datetime(2024, 12, 1, tzinfo=UTC),
                api_status="success",
            )
        )
        db.commit()

        db.add(
            ProjectStatusSnapshot(
                id=1,
                project_id="proj1",
                repository_id="repo1",
                run_id=1,
                observed_at=datetime(2025, 1, 1, tzinfo=UTC),
                status_label="Active",
                reason="Last push 31 days ago",
            )
        )
        db.add(
            ProjectStatusSnapshot(
                id=2,
                project_id="proj2",
                repository_id="repo2",
                run_id=1,
                observed_at=datetime(2025, 1, 1, tzinfo=UTC),
                status_label="Unknown",
                reason="Repository host not supported in MVP",
            )
        )
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestProjectsEndpoint:
    def test_returns_empty_list_when_no_data(self, client):
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["data"] == []
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_invalid_limit_returns_422(self, client):
        response = client.get("/api/projects", params={"limit": 999})
        assert response.status_code == 422

    def test_invalid_offset_returns_422(self, client):
        response = client.get("/api/projects", params={"offset": -1})
        assert response.status_code == 422

    def test_invalid_status_filter_returns_422(self, client):
        response = client.get("/api/projects", params={"status": "InvalidStatus"})
        assert response.status_code == 422

    def test_valid_status_filter(self, client):
        _insert_test_data()
        response = client.get("/api/projects", params={"status": "Active"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for item in data["data"]:
            assert item["status_label"] == "Active"

    def test_search_filter(self, client):
        _insert_test_data()
        response = client.get("/api/projects", params={"search": "alpha"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any("Alpha" in item["name"] for item in data["data"])

    def test_pagination_params(self, client):
        response = client.get("/api/projects", params={"limit": 10, "offset": 5})
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_projects_with_data(self, client):
        _insert_test_data()
        response = client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        first = data["data"][0]
        assert "project_id" in first
        assert "name" in first
        assert "status_label" in first


class TestSummaryEndpoint:
    def test_returns_zero_counts_when_no_data(self, client):
        response = client.get("/api/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["Archived"] == 0
        assert data["Active"] == 0
        assert data["Slow"] == 0
        assert data["Stale"] == 0
        assert data["Unknown"] == 0
        assert data["total"] == 0

    def test_response_has_all_keys(self, client):
        response = client.get("/api/summary")
        data = response.json()
        expected_keys = {
            "Archived",
            "Data error",
            "Unknown",
            "Active",
            "Slow",
            "Stale",
            "total",
            "total_with_repo",
            "total_without_repo",
            "unsupported_host_count",
        }
        assert set(data.keys()) == expected_keys

    def test_summary_with_data(self, client):
        _insert_test_data()
        response = client.get("/api/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2
        assert data["Active"] >= 1
        assert data["total_with_repo"] >= 2


class TestExportsEndpoint:
    def test_returns_csv_headers(self, client):
        _insert_test_data()
        response = client.get("/exports/projects.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers.get("content-disposition", "")

    def test_csv_has_bom(self, client):
        _insert_test_data()
        response = client.get("/exports/projects.csv")
        content = response.content
        assert content[:3] == b"\xef\xbb\xbf"

    def test_csv_has_columns(self, client):
        _insert_test_data()
        response = client.get("/exports/projects.csv")
        content = response.text
        reader = csv.reader(io.StringIO(content.lstrip("\ufeff")))
        headers = next(reader)
        assert "project_name" in headers
        assert "status" in headers

    def test_csv_with_status_filter(self, client):
        _insert_test_data()
        response = client.get("/exports/projects.csv", params={"status": "Active"})
        assert response.status_code == 200

    def test_csv_empty_data(self, client):
        response = client.get("/exports/projects.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")


class TestRunsEndpoint:
    def test_returns_empty_list_when_no_data(self, client):
        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []

    def test_invalid_limit_returns_422(self, client):
        response = client.get("/api/runs", params={"limit": 999})
        assert response.status_code == 422

    def test_default_limit(self, client):
        _insert_test_data()
        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) >= 1
        first = data["data"][0]
        assert "id" in first
        assert "status" in first
        assert "started_at" in first

    def test_runs_with_limit(self, client):
        _insert_test_data()
        response = client.get("/api/runs", params={"limit": 1})
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) <= 1


class TestExportsEdgeCases:
    """Edge-case tests for CSV export — covers H3 fix and content validation."""

    def test_csv_invalid_status_returns_422(self, client):
        """Invalid status filter on CSV should return 422, not silently ignored."""
        response = client.get("/exports/projects.csv", params={"status": "Banana"})
        assert response.status_code == 422

    def test_csv_content_has_data_rows(self, client):
        """CSV should contain actual data rows matching the test data."""
        _insert_test_data()
        response = client.get("/exports/projects.csv")
        assert response.status_code == 200
        content = response.text
        reader = csv.reader(io.StringIO(content.lstrip("\ufeff")))
        next(reader)
        rows = list(reader)
        assert len(rows) >= 2  # at least 2 test projects

    def test_csv_rows_contain_project_name(self, client):
        """CSV data rows should contain the project name."""
        _insert_test_data()
        response = client.get("/exports/projects.csv")
        content = response.text
        assert "Test Project Alpha" in content
