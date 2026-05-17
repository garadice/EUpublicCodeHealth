"""Tests for configuration module."""

from app.core.config import Settings


class TestSettings:
    def test_default_values(self) -> None:
        s = Settings()
        assert s.app_title == "EU PubliCodeHealth"
        assert s.debug is False
        assert s.ingest_interval_seconds == 86400

    def test_custom_values(self) -> None:
        s = Settings(database_url="sqlite:///test.db", github_token="ghp_test123", debug=True)
        assert s.database_url == "sqlite:///test.db"
        assert s.github_token == "ghp_test123"
        assert s.debug is True
