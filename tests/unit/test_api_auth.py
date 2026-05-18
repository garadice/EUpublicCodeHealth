"""Unit tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.main import app
from app.core.config import Settings, get_settings
from app.db.models import Base
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


PROTECTED_ENDPOINTS = [
    "/api/projects",
    "/api/summary",
    "/api/runs",
    "/exports/projects.csv",
]

PUBLIC_ENDPOINTS = [
    "/health",
]

VALID_KEY = "test-secret-key-abc123"
WRONG_KEY = "wrong-key-xyz789"


def _make_client_with_key(api_key: str) -> TestClient:
    """Create a TestClient with a specific API key setting.

    We must override get_settings to return a Settings instance
    with the desired api_key, and also clear the lru_cache so
    the new value is picked up.
    """
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(api_key=api_key)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_settings, None)
    get_settings.cache_clear()


@pytest.fixture()
def client_no_auth():
    return _make_client_with_key("")


@pytest.fixture()
def client_with_auth():
    return _make_client_with_key(VALID_KEY)


class TestAuthDisabled:
    """When API_KEY is empty, all endpoints should be accessible without a key."""

    def test_protected_endpoints_work_without_key(self, client_no_auth):
        for endpoint in PROTECTED_ENDPOINTS:
            response = client_no_auth.get(endpoint)
            assert response.status_code == 200, f"Failed for {endpoint}"

    def test_health_works_without_key(self, client_no_auth):
        for endpoint in PUBLIC_ENDPOINTS:
            response = client_no_auth.get(endpoint)
            assert response.status_code == 200, f"Failed for {endpoint}"


class TestAuthEnabled:
    """When API_KEY is set, protected endpoints require the correct key."""

    def test_protected_endpoints_reject_no_key(self, client_with_auth):
        for endpoint in PROTECTED_ENDPOINTS:
            response = client_with_auth.get(endpoint)
            assert response.status_code == 401, f"Expected 401 for {endpoint}"

    def test_protected_endpoints_reject_wrong_key(self, client_with_auth):
        for endpoint in PROTECTED_ENDPOINTS:
            response = client_with_auth.get(endpoint, headers={"X-API-Key": WRONG_KEY})
            assert response.status_code == 401, f"Expected 401 for {endpoint}"

    def test_protected_endpoints_accept_valid_key(self, client_with_auth):
        for endpoint in PROTECTED_ENDPOINTS:
            response = client_with_auth.get(endpoint, headers={"X-API-Key": VALID_KEY})
            assert response.status_code == 200, f"Expected 200 for {endpoint}"

    def test_health_still_public_with_auth_enabled(self, client_with_auth):
        for endpoint in PUBLIC_ENDPOINTS:
            response = client_with_auth.get(endpoint)
            assert response.status_code == 200, f"Expected 200 for {endpoint}"

    def test_health_works_without_key_even_when_auth_enabled(self, client_with_auth):
        response = client_with_auth.get("/health")
        assert response.status_code == 200

    def test_error_message_on_missing_key(self, client_with_auth):
        response = client_with_auth.get("/api/projects")
        assert response.status_code == 401
        assert "Missing" in response.json()["detail"]

    def test_error_message_on_wrong_key(self, client_with_auth):
        response = client_with_auth.get("/api/projects", headers={"X-API-Key": WRONG_KEY})
        assert response.status_code == 401
        assert "Invalid" in response.json()["detail"]


class TestAuthKeySecurity:
    """Verify the API key uses constant-time comparison."""

    def test_key_comparison_not_vulnerable_to_timing(self):
        """Ensure verify_api_key uses secrets.compare_digest, not ==."""
        import ast
        import inspect

        from app.api.auth import verify_api_key

        source = inspect.getsource(verify_api_key)
        assert "secrets.compare_digest" in source
        # Make sure we're not using == for key comparison
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    if isinstance(op, ast.Eq):
                        pytest.fail("Found == comparison in auth code — use secrets.compare_digest instead")
