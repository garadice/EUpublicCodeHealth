"""Shared test fixtures for EU PubliCodeHealth."""

import pytest

from app.core.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Return settings configured for testing."""
    return Settings(
        database_url="sqlite:///file::memory:?cache=shared&uri=true",
        github_token="test-token",
        source_catalog_urls="[]",
        debug=True,
    )
