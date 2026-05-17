"""Unit tests for the status classification pipeline step.

Tests _classify_repository logic with mock Repository and Snapshot objects,
verifying all 6 status labels and edge cases.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.core.status import StatusLabel
from pipelines.classify_status import _classify_repository


def _make_repo(
    host: str = "github",
    is_supported: bool = True,
    owner: str = "org",
    repo_name: str = "repo",
) -> MagicMock:
    repo = MagicMock()
    repo.host = host
    repo.is_supported = is_supported
    repo.owner = owner
    repo.repo_name = repo_name
    return repo


def _make_snapshot(
    api_status: str = "success",
    archived: bool | None = False,
    pushed_at: datetime | None = None,
) -> MagicMock:
    snap = MagicMock()
    snap.api_status = api_status
    snap.archived = archived
    snap.pushed_at = pushed_at
    return snap


class TestClassifyRepositorySuccess:
    def test_active_repo(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(pushed_at=datetime.now(UTC) - timedelta(days=5))
        label, reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.ACTIVE
        assert "5 days ago" in reason
        assert flags == []

    def test_slow_repo(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(pushed_at=datetime.now(UTC) - timedelta(days=200))
        label, reason, _flags = _classify_repository(repo, snap)
        assert label == StatusLabel.SLOW
        assert "200 days ago" in reason

    def test_stale_repo(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(pushed_at=datetime.now(UTC) - timedelta(days=500))
        label, reason, _flags = _classify_repository(repo, snap)
        assert label == StatusLabel.STALE
        assert "500 days ago" in reason

    def test_archived_repo(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(archived=True, pushed_at=datetime.now(UTC) - timedelta(days=5))
        label, _reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.ARCHIVED
        assert "archived" in flags


class TestClassifyRepositoryNoSnapshot:
    def test_no_snapshot_supported_host(self) -> None:
        repo = _make_repo(is_supported=True)
        label, _reason, flags = _classify_repository(repo, None)
        assert label == StatusLabel.UNKNOWN
        assert "no_snapshot" in flags

    def test_no_snapshot_unsupported_host(self) -> None:
        repo = _make_repo(host="gitlab", is_supported=False)
        label, _reason, flags = _classify_repository(repo, None)
        assert label == StatusLabel.UNKNOWN
        assert "unsupported_host" in flags


class TestClassifyRepositoryApiErrors:
    def test_not_found_snapshot(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(api_status="not_found")
        label, _reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.DATA_ERROR
        assert "repo_not_found" in flags

    def test_error_snapshot(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(api_status="error")
        label, _reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.DATA_ERROR
        assert "api_error" in flags

    def test_rate_limited_snapshot(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(api_status="rate_limited")
        label, _reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.DATA_ERROR
        assert "rate_limited" in flags


class TestClassifyRepositoryEdgeCases:
    def test_unsupported_host_with_successful_snapshot(self) -> None:
        """Defensive: unsupported host shouldn't have successful snapshot, but handle it."""
        repo = _make_repo(host="gitlab", is_supported=False)
        snap = _make_snapshot(pushed_at=datetime.now(UTC) - timedelta(days=5))
        label, _reason, flags = _classify_repository(repo, snap)
        assert label == StatusLabel.UNKNOWN
        assert "unsupported_host" in flags

    def test_archived_overrides_active(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(archived=True, pushed_at=datetime.now(UTC) - timedelta(days=1))
        label, _reason, _flags = _classify_repository(repo, snap)
        assert label == StatusLabel.ARCHIVED

    def test_archived_overrides_stale(self) -> None:
        repo = _make_repo()
        snap = _make_snapshot(archived=True, pushed_at=datetime.now(UTC) - timedelta(days=500))
        label, _reason, _flags = _classify_repository(repo, snap)
        assert label == StatusLabel.ARCHIVED

    def test_pushed_at_none_with_success_status(self) -> None:
        """Successful API call but pushed_at is None (rare but possible)."""
        repo = _make_repo()
        snap = _make_snapshot(pushed_at=None)
        label, _reason, _flags = _classify_repository(repo, snap)
        # classify_status returns Unknown when pushed_at is None
        assert label == StatusLabel.UNKNOWN
