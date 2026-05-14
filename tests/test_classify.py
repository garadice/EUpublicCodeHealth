from datetime import datetime, timezone, timedelta
from pipelines.run_pipeline import classify


def test_classify_active():
    pushed = datetime.now(timezone.utc) - timedelta(days=5)
    status, _ = classify(pushed, False, True)
    assert status == "Active"


def test_classify_archived_priority():
    pushed = datetime.now(timezone.utc) - timedelta(days=1)
    status, _ = classify(pushed, True, True)
    assert status == "Archived"


def test_classify_unknown_when_missing_repo_data():
    status, _ = classify(None, False, False)
    assert status == "Unknown"
