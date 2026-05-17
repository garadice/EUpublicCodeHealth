"""Tests for status classification logic."""

from datetime import UTC, datetime, timedelta

from app.core.status import StatusLabel, classify_status


class TestClassifyActive:
    def test_active_within_90_days(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=5)
        label, reason = classify_status(pushed_at=pushed, archived=False, has_repo=True)
        assert label == StatusLabel.ACTIVE
        assert "5 days ago" in reason

    def test_active_at_exactly_90_days(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=90)
        label, _ = classify_status(pushed_at=pushed, archived=False, has_repo=True)
        assert label == StatusLabel.ACTIVE


class TestClassifySlow:
    def test_slow_at_91_days(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=91)
        label, reason = classify_status(pushed_at=pushed, archived=False, has_repo=True)
        assert label == StatusLabel.SLOW
        assert "91 days ago" in reason

    def test_slow_at_365_days(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=365)
        label, _ = classify_status(pushed_at=pushed, archived=False, has_repo=True)
        assert label == StatusLabel.SLOW


class TestClassifyStale:
    def test_stale_over_365_days(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=400)
        label, reason = classify_status(pushed_at=pushed, archived=False, has_repo=True)
        assert label == StatusLabel.STALE
        assert "400 days ago" in reason


class TestClassifyArchived:
    def test_archived_overrides_active(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=1)
        label, _ = classify_status(pushed_at=pushed, archived=True, has_repo=True)
        assert label == StatusLabel.ARCHIVED

    def test_archived_overrides_stale(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=500)
        label, _ = classify_status(pushed_at=pushed, archived=True, has_repo=True)
        assert label == StatusLabel.ARCHIVED

    def test_archived_reason(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=5)
        _, reason = classify_status(pushed_at=pushed, archived=True, has_repo=True)
        assert "archived" in reason.lower()


class TestClassifyUnknown:
    def test_unknown_when_no_repo(self) -> None:
        label, _ = classify_status(pushed_at=None, archived=False, has_repo=False)
        assert label == StatusLabel.UNKNOWN

    def test_unknown_when_unsupported_host(self) -> None:
        label, _ = classify_status(pushed_at=None, archived=False, has_repo=False, unsupported_host=True)
        assert label == StatusLabel.UNKNOWN

    def test_unknown_when_pushed_at_none_with_repo(self) -> None:
        label, _ = classify_status(pushed_at=None, archived=False, has_repo=True)
        assert label == StatusLabel.UNKNOWN


class TestClassifyDataError:
    def test_data_error_overrides_unknown(self) -> None:
        label, _ = classify_status(pushed_at=None, archived=False, has_repo=True, api_error=True)
        assert label == StatusLabel.DATA_ERROR

    def test_data_error_overrides_active(self) -> None:
        pushed = datetime.now(UTC) - timedelta(days=5)
        label, _ = classify_status(pushed_at=pushed, archived=False, has_repo=True, api_error=True)
        assert label == StatusLabel.DATA_ERROR


class TestTieBreakOrder:
    """Verify priority: Archived > Data error > Unknown > Active > Slow > Stale."""

    def test_archived_beats_data_error(self) -> None:
        label, _ = classify_status(pushed_at=None, archived=True, has_repo=True, api_error=True)
        assert label == StatusLabel.ARCHIVED
