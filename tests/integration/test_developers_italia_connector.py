"""Integration tests for the Developers Italia API connector.

Uses pytest-httpx to mock HTTP responses and exercises the full
fetch pipeline including pagination, error handling, and retry logic.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from connectors.developers_italia import (
    DEFAULT_BASE_URL,
    FetchResult,
    fetch_all_software,
    make_client,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _patch_base_url(monkeypatch):
    monkeypatch.setattr(
        "connectors.developers_italia._get_base_url",
        lambda: DEFAULT_BASE_URL,
    )


async def _fetch() -> FetchResult:
    async with make_client() as client:
        return await fetch_all_software(client)


class TestFetchSinglePage:
    def test_returns_entries_from_one_page(self, httpx_mock) -> None:
        page = _load_fixture("developers_italia_page1.json")
        page["links"]["next"] = None

        httpx_mock.add_response(url=DEFAULT_BASE_URL, json=page)

        result = asyncio.run(_fetch())

        assert result.total_fetched == 25
        assert result.pages_fetched == 1
        assert len(result.entries) == 25
        assert result.errors == []


class TestFetchTwoPages:
    def test_follows_cursor_pagination(self, httpx_mock) -> None:
        page1 = _load_fixture("developers_italia_page1.json")
        page2 = _load_fixture("developers_italia_page2.json")

        cursor = page1["links"]["next"]
        page2["links"]["next"] = None

        httpx_mock.add_response(url=DEFAULT_BASE_URL, json=page1)
        httpx_mock.add_response(url=f"{DEFAULT_BASE_URL}{cursor}", json=page2)

        result = asyncio.run(_fetch())

        assert result.total_fetched == 50
        assert result.pages_fetched == 2
        assert len(result.entries) == 50
        assert result.errors == []


class TestFetchEmptyPage:
    def test_returns_zero_entries(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=DEFAULT_BASE_URL,
            json={"data": [], "links": {"prev": None, "next": None}},
        )

        result = asyncio.run(_fetch())

        assert result.total_fetched == 0
        assert result.pages_fetched == 1
        assert result.entries == []
        assert result.errors == []


class TestFetchHandles500WithRetry:
    def test_retries_on_server_error_then_succeeds(self, httpx_mock) -> None:
        page = _load_fixture("developers_italia_page1.json")
        page["links"]["next"] = None

        httpx_mock.add_response(url=DEFAULT_BASE_URL, status_code=500)
        httpx_mock.add_response(url=DEFAULT_BASE_URL, json=page)

        with patch("connectors.developers_italia.asyncio.sleep"):
            result = asyncio.run(_fetch())

        assert result.total_fetched == 25
        assert result.pages_fetched == 1
        assert result.errors == []


class TestFetchHandles404Immediately:
    def test_captures_client_error_without_retry(self, httpx_mock) -> None:
        httpx_mock.add_response(url=DEFAULT_BASE_URL, status_code=404)

        result = asyncio.run(_fetch())

        assert result.total_fetched == 0
        assert result.pages_fetched == 0
        assert len(result.errors) == 1
        assert "404" in result.errors[0]


class TestFetchHandlesNetworkError:
    def test_captures_connection_error_gracefully(self, httpx_mock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))

        result = asyncio.run(_fetch())

        assert result.total_fetched == 0
        assert result.pages_fetched == 0
        assert len(result.errors) == 1
        assert "Network error" in result.errors[0]


class TestFetchHandlesMalformedResponse:
    def test_captures_missing_data_field(self, httpx_mock) -> None:
        httpx_mock.add_response(url=DEFAULT_BASE_URL, json={"not_data": []})

        result = asyncio.run(_fetch())

        assert result.total_fetched == 0
        assert result.pages_fetched == 0
        assert len(result.errors) == 1
        assert "Malformed" in result.errors[0]
