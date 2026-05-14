from datetime import datetime, timezone, timedelta
from pipelines.run_pipeline import classify


def test_classify_active():
    pushed = datetime.now(timezone.utc) - timedelta(days=5)
    status, _ = classify(pushed, False, True)
    assert status == "Active"
