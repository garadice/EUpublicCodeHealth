"""Unit tests for the catalogue ingestion pipeline.

Tests cover _extract_url, _extract_aliases, _process_entry, and the async
ingest_developers_italia orchestrator with mocked fetch results.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.url_normalize import HostType
from connectors.developers_italia import FetchResult
from pipelines.ingest_catalog import (
    IngestResult,
    _extract_aliases,
    _extract_url,
    _process_entry,
    ingest_developers_italia,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

VALID_PUBLICCODE_YML = (
    "name: Test\nurl: https://github.com/org/repo\ndescription:\n  en:\n    shortDescription: A test project\n"
)


def _make_entry(**overrides) -> dict:
    """Helper to create a minimal API entry dict."""
    entry: dict = {
        "id": "test-id-123",
        "url": "https://github.com/org/repo.git",
        "aliases": [],
        "publiccodeYml": VALID_PUBLICCODE_YML,
        "active": True,
        "vitality": None,
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-06-01T00:00:00Z",
    }
    entry.update(overrides)
    return entry


# ── _extract_url ──────────────────────────────────────────────────────────


class TestExtractUrl:
    def test_extract_url_with_valid_url(self) -> None:
        assert _extract_url({"url": "https://github.com/org/repo"}) == "https://github.com/org/repo"

    def test_extract_url_with_none(self) -> None:
        assert _extract_url({}) == ""

    def test_extract_url_with_empty_string(self) -> None:
        assert _extract_url({"url": ""}) == ""

    def test_extract_url_with_whitespace(self) -> None:
        assert _extract_url({"url": "  https://github.com/org/repo  "}) == "https://github.com/org/repo"


# ── _extract_aliases ─────────────────────────────────────────────────────


class TestExtractAliases:
    def test_extract_aliases_with_list(self) -> None:
        assert _extract_aliases({"aliases": ["https://github.com/a", "https://gitlab.com/b"]}) == [
            "https://github.com/a",
            "https://gitlab.com/b",
        ]

    def test_extract_aliases_with_empty_list(self) -> None:
        assert _extract_aliases({"aliases": []}) == []

    def test_extract_aliases_with_none(self) -> None:
        assert _extract_aliases({}) == []

    def test_extract_aliases_filters_empty_strings(self) -> None:
        assert _extract_aliases({"aliases": ["a", "", "  ", "b"]}) == ["a", "b"]

    def test_extract_aliases_with_non_list(self) -> None:
        assert _extract_aliases({"aliases": "not-a-list"}) == []


# ── _process_entry ────────────────────────────────────────────────────────


class TestProcessEntry:
    def test_process_entry_with_github_url(self) -> None:
        project = _process_entry(_make_entry())
        assert project is not None
        assert project.normalized_url.host == HostType.GITHUB
        assert project.normalized_url.owner == "org"
        assert project.normalized_url.repo_name == "repo"

    def test_process_entry_with_gitlab_url(self) -> None:
        project = _process_entry(_make_entry(url="https://gitlab.com/org/repo"))
        assert project is not None
        assert project.normalized_url.host == HostType.GITLAB

    def test_process_entry_with_unsupported_url(self) -> None:
        project = _process_entry(_make_entry(url="https://bitbucket.org/org/repo"))
        assert project is not None
        assert project.normalized_url.host == HostType.UNSUPPORTED

    def test_process_entry_with_missing_id(self) -> None:
        entry = _make_entry()
        del entry["id"]
        assert _process_entry(entry) is None

    def test_process_entry_with_empty_id(self) -> None:
        assert _process_entry(_make_entry(id="")) is None

    def test_process_entry_with_invalid_yaml(self) -> None:
        project = _process_entry(_make_entry(publiccodeYml=":::not{{valid yaml"))
        assert project is not None
        assert project.parsed.parse_error is not None

    def test_process_entry_url_fallback_to_parsed_url(self) -> None:
        project = _process_entry(
            _make_entry(
                url="",
                publiccodeYml="name: Test\nurl: https://github.com/fallback/repo\n",
            )
        )
        assert project is not None
        assert project.normalized_url.host == HostType.GITHUB
        assert project.normalized_url.owner == "fallback"
        assert project.raw_url == "https://github.com/fallback/repo"

    def test_process_entry_with_non_string_publiccode_yml(self) -> None:
        project = _process_entry(_make_entry(publiccodeYml=None))
        assert project is not None
        assert project.parsed.parse_error is not None

    def test_process_entry_with_aliases(self) -> None:
        project = _process_entry(_make_entry(aliases=["https://github.com/org/repo", "https://example.com/mirror"]))
        assert project is not None
        assert project.aliases == ["https://github.com/org/repo", "https://example.com/mirror"]

    def test_process_entry_active_flag_true(self) -> None:
        project = _process_entry(_make_entry(active=True))
        assert project is not None
        assert project.active is True

    def test_process_entry_active_flag_false(self) -> None:
        project = _process_entry(_make_entry(active=False))
        assert project is not None
        assert project.active is False

    def test_process_entry_active_flag_missing(self) -> None:
        entry = _make_entry()
        del entry["active"]
        project = _process_entry(entry)
        assert project is not None
        assert project.active is True

    def test_process_entry_timestamps(self) -> None:
        project = _process_entry(_make_entry(createdAt="2024-01-01T00:00:00Z", updatedAt="2024-06-01T00:00:00Z"))
        assert project is not None
        assert project.created_at == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        assert project.updated_at == datetime(2024, 6, 1, 0, 0, tzinfo=UTC)

    def test_process_entry_with_non_string_timestamps(self) -> None:
        project = _process_entry(_make_entry(createdAt=12345, updatedAt=None))
        assert project is not None
        assert project.created_at is None
        assert project.updated_at is None

    def test_process_entry_source_id_always_developers_italia(self) -> None:
        project = _process_entry(_make_entry())
        assert project is not None
        assert project.source_id == "developers_italia"

    def test_process_entry_url_fallback_stays_invalid_when_parsed_has_no_url(self) -> None:
        project = _process_entry(_make_entry(url="", publiccodeYml="name: NoUrl\n"))
        assert project is not None
        assert project.normalized_url.host == HostType.INVALID


# ── _process_entry with fixture ───────────────────────────────────────────


class TestProcessEntryWithFixture:
    def test_process_entry_with_github_fixture(self) -> None:
        with open(FIXTURES_DIR / "software_entry_github.json") as f:
            entry = json.load(f)
        project = _process_entry(entry)
        assert project is not None
        assert project.source_project_id == "22766c9d-4e6f-43d8-b0a7-f6b376f4830a"
        assert project.normalized_url.host == HostType.GITHUB
        assert project.normalized_url.owner == "Truelite"
        assert project.normalized_url.repo_name == "python-a38"
        assert project.parsed.name == "A38"
        assert project.active is True
        assert project.aliases == ["https://github.com/Truelite/python-a38"]


# ── ingest_developers_italia (async, mocked) ──────────────────────────────


def _run_ingest(entries: list[dict], errors: list[str] | None = None) -> IngestResult:
    """Helper to run ingest_developers_italia with a mocked fetch."""
    total = len(entries)
    mock_result = FetchResult(
        entries=entries,
        total_fetched=total,
        pages_fetched=1,
        errors=errors or [],
    )
    with patch("pipelines.ingest_catalog.fetch_all_software", new_callable=AsyncMock, return_value=mock_result):
        return asyncio.run(ingest_developers_italia(AsyncMock()))


class TestIngestDevelopersItalia:
    def test_ingest_with_successful_fetch(self) -> None:
        entries = [
            _make_entry(id="1"),
            _make_entry(id="2"),
            _make_entry(id="3"),
        ]
        result = _run_ingest(entries)
        assert result.total_fetched == 3
        assert len(result.projects) == 3
        assert result.total_parsed_ok == 3
        assert result.parse_errors == 0
        assert result.errors == []

    def test_ingest_with_parse_errors(self) -> None:
        entries = [
            _make_entry(id="1"),
            _make_entry(id="2", publiccodeYml=":::invalid{{yaml"),
        ]
        result = _run_ingest(entries)
        assert result.total_fetched == 2
        assert result.parse_errors == 1
        assert result.total_parsed_ok == 1

    def test_ingest_with_fetch_errors(self) -> None:
        entries = [_make_entry(id="1")]
        result = _run_ingest(entries, errors=["HTTP 500 on page 2"])
        assert len(result.errors) == 1
        assert "HTTP 500" in result.errors[0]
        assert len(result.projects) == 1

    def test_ingest_host_counts(self) -> None:
        entries = [
            _make_entry(id="gh1", url="https://github.com/a/b"),
            _make_entry(id="gh2", url="https://github.com/c/d"),
            _make_entry(id="gl1", url="https://gitlab.com/e/f"),
            _make_entry(id="unsup", url="https://bitbucket.org/g/h"),
            _make_entry(id="inv", url="", publiccodeYml="name: NoUrl\n"),
        ]
        result = _run_ingest(entries)
        assert result.github_count == 2
        assert result.gitlab_count == 1
        assert result.unsupported_count == 1
        assert result.invalid_url_count == 1

    def test_ingest_with_empty_fetch(self) -> None:
        result = _run_ingest([])
        assert result.total_fetched == 0
        assert len(result.projects) == 0
        assert result.total_parsed_ok == 0
        assert result.parse_errors == 0
        assert result.github_count == 0
        assert result.gitlab_count == 0
        assert result.unsupported_count == 0
        assert result.invalid_url_count == 0

    def test_ingest_skips_entries_with_missing_id(self) -> None:
        no_id_entry = _make_entry()
        del no_id_entry["id"]
        entries = [
            _make_entry(id="valid"),
            _make_entry(id=""),
            no_id_entry,
        ]
        result = _run_ingest(entries)
        assert result.total_fetched == 3
        assert len(result.projects) == 1
        assert result.projects[0].source_project_id == "valid"

    def test_ingest_counts_reflect_only_processed_projects(self) -> None:
        entries = [
            _make_entry(id="1", url="https://github.com/a/b"),
            _make_entry(id=""),  # skipped
            _make_entry(id="2", url="https://gitlab.com/c/d"),
        ]
        result = _run_ingest(entries)
        assert result.github_count == 1
        assert result.gitlab_count == 1
        assert len(result.projects) == 2
