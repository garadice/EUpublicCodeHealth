"""Unit tests for the GitHub API client.

Tests cover metric extraction, datetime parsing, rate limit handling,
retry logic, and various HTTP response scenarios using mocked httpx.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from connectors.github_client import (
    RateLimitInfo,
    _extract_repo_metrics,
    _parse_github_datetime,
    _parse_rate_limit_headers,
    fetch_repo_metrics,
    make_github_client,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


# ── _parse_github_datetime ─────────────────────────────────────────────────


class TestParseGithubDatetime:
    def test_parses_zulu_time(self) -> None:
        result = _parse_github_datetime("2024-10-15T09:00:00Z")
        assert result == datetime(2024, 10, 15, 9, 0, 0, tzinfo=UTC)

    def test_parses_with_timezone_offset(self) -> None:
        result = _parse_github_datetime("2024-10-15T11:00:00+02:00")
        assert result is not None
        assert result.hour == 11

    def test_returns_none_for_none(self) -> None:
        assert _parse_github_datetime(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_github_datetime("") is None

    def test_returns_none_for_invalid_string(self) -> None:
        assert _parse_github_datetime("not-a-date") is None


# ── _parse_rate_limit_headers ──────────────────────────────────────────────


class TestParseRateLimitHeaders:
    def test_parses_valid_headers(self) -> None:
        headers = httpx.Headers(
            {
                "x-ratelimit-remaining": "4999",
                "x-ratelimit-limit": "5000",
                "x-ratelimit-reset": "1700000000",
            }
        )
        info = _parse_rate_limit_headers(headers)
        assert info.remaining == 4999
        assert info.limit == 5000
        assert info.reset_at is not None

    def test_defaults_when_headers_missing(self) -> None:
        headers = httpx.Headers({})
        info = _parse_rate_limit_headers(headers)
        assert info.remaining == 5000
        assert info.limit == 5000
        assert info.reset_at is None

    def test_is_exhausted_when_low(self) -> None:
        info = RateLimitInfo(remaining=0, limit=5000, reset_at=None)
        assert info.is_exhausted is True

    def test_is_not_exhausted_when_ok(self) -> None:
        info = RateLimitInfo(remaining=100, limit=5000, reset_at=None)
        assert info.is_exhausted is False


# ── _extract_repo_metrics ──────────────────────────────────────────────────


class TestExtractRepoMetrics:
    def test_extracts_all_fields_from_fixture(self) -> None:
        with open(FIXTURES_DIR / "github_repo_response.json") as f:
            data = json.load(f)
        metrics = _extract_repo_metrics(data, "Truelite", "python-a38")

        assert metrics.owner == "Truelite"
        assert metrics.repo_name == "python-a38"
        assert metrics.stars == 42
        assert metrics.forks == 15
        assert metrics.open_issues == 7
        assert metrics.archived is False
        assert metrics.pushed_at == datetime(2024, 10, 15, 9, 0, 0, tzinfo=UTC)
        assert metrics.license_key == "MIT"
        assert metrics.topics == ["italy", "fiscal-code", "codice-fiscale", "python"]
        assert metrics.default_branch == "main"
        assert metrics.html_url == "https://github.com/Truelite/python-a38"
        assert metrics.api_status == "success"
        assert metrics.error_message is None

    def test_handles_missing_license(self) -> None:
        data = {"stargazers_count": 10, "forks_count": 5, "default_branch": "master"}
        metrics = _extract_repo_metrics(data, "org", "repo")
        assert metrics.license_key is None

    def test_handles_null_license(self) -> None:
        data = {"license": None}
        metrics = _extract_repo_metrics(data, "org", "repo")
        assert metrics.license_key is None

    def test_handles_missing_topics(self) -> None:
        data = {}
        metrics = _extract_repo_metrics(data, "org", "repo")
        assert metrics.topics == []

    def test_handles_archived_repo(self) -> None:
        data = {"archived": True, "pushed_at": "2020-01-01T00:00:00Z"}
        metrics = _extract_repo_metrics(data, "org", "repo")
        assert metrics.archived is True

    def test_defaults_to_zero_counts(self) -> None:
        data = {}
        metrics = _extract_repo_metrics(data, "org", "repo")
        assert metrics.stars == 0
        assert metrics.forks == 0
        assert metrics.open_issues == 0


# ── make_github_client ─────────────────────────────────────────────────────


class TestMakeGithubClient:
    @pytest.mark.asyncio
    async def test_client_has_auth_header_when_token_set(self) -> None:
        with patch("connectors.github_client.get_settings") as mock_settings:
            mock_settings.return_value = type("S", (), {"github_token": "ghp_test123"})()
            async with make_github_client() as client:
                assert "Authorization" in client.headers
                assert client.headers["Authorization"] == "Bearer ghp_test123"

    @pytest.mark.asyncio
    async def test_client_no_auth_header_when_token_empty(self) -> None:
        with patch("connectors.github_client.get_settings") as mock_settings:
            mock_settings.return_value = type("S", (), {"github_token": ""})()
            async with make_github_client() as client:
                assert "Authorization" not in client.headers


# ── fetch_repo_metrics (integration-like with mock transport) ──────────────


def _make_response(
    status_code: int = 200,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Create an httpx.Response for testing."""
    body = json_body or {}
    return httpx.Response(
        status_code=status_code,
        json=body,
        headers=headers or {},
        request=httpx.Request("GET", "https://api.github.com/repos/org/repo"),
    )


class TestFetchRepoMetrics:
    @pytest.mark.asyncio
    async def test_successful_fetch(self) -> None:
        with open(FIXTURES_DIR / "github_repo_response.json") as f:
            fixture_data = json.load(f)

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return _make_response(200, fixture_data)

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "Truelite", "python-a38")

        assert result.api_status == "success"
        assert result.stars == 42
        assert result.forks == 15
        assert result.archived is False
        assert result.license_key == "MIT"
        assert result.topics == ["italy", "fiscal-code", "codice-fiscale", "python"]
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_not_found_returns_status(self) -> None:
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return _make_response(404, {"message": "Not Found"})

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "org", "nonexistent")

        assert result.api_status == "not_found"
        assert result.error_message is not None
        assert "404" in result.error_message

    @pytest.mark.asyncio
    async def test_rate_limited_returns_status(self) -> None:
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return _make_response(
                403,
                {"message": "API rate limit exceeded"},
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-limit": "5000"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "org", "repo")

        assert result.api_status == "rate_limited"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_server_error_retries_then_fails(self) -> None:
        call_count = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _make_response(500, {"message": "Internal Server Error"})

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "org", "repo")

        assert result.api_status == "error"
        assert call_count == 3  # MAX_RETRIES

    @pytest.mark.asyncio
    async def test_network_error_retries_then_fails(self) -> None:
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "org", "repo")

        assert result.api_status == "error"
        assert result.error_message is not None
        assert "Network error" in result.error_message

    @pytest.mark.asyncio
    async def test_5xx_retries_then_succeeds(self) -> None:
        call_count = 0

        async def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _make_response(503, {"message": "Service Unavailable"})
            with open(FIXTURES_DIR / "github_repo_response.json") as f:
                data = json.load(f)
            return _make_response(200, data)

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "Truelite", "python-a38")

        assert result.api_status == "success"
        assert result.stars == 42
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_unexpected_status_returns_error(self) -> None:
        async def mock_handler(request: httpx.Request) -> httpx.Response:
            return _make_response(422, {"message": "Unprocessable"})

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as client:
            result = await fetch_repo_metrics(client, "org", "repo")

        assert result.api_status == "error"
        assert result.error_message is not None
