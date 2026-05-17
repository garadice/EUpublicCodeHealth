"""Status label classification logic.

Implements deterministic rules for classifying project health
based on repository activity metrics.

Label priority (highest to lowest):
1. Archived — GitHub archived flag is true
2. Data error — supported host returned API error
3. Unknown — unsupported host, missing repo URL
4. Active — latest commit within 90 days
5. Slow — latest commit 91-365 days ago
6. Stale — latest commit >365 days ago

NEVER claim this measures software quality or security.
We measure repository activity only.
"""

from datetime import UTC, datetime
from enum import StrEnum


class StatusLabel(StrEnum):
    """Allowed status label values."""

    ARCHIVED = "Archived"
    DATA_ERROR = "Data error"
    UNKNOWN = "Unknown"
    ACTIVE = "Active"
    SLOW = "Slow"
    STALE = "Stale"


VALID_STATUS_LABELS: frozenset[str] = frozenset(s.value for s in StatusLabel)


def classify_status(
    pushed_at: datetime | None,
    archived: bool | None,
    has_repo: bool,
    api_error: bool = False,
    unsupported_host: bool = False,
) -> tuple[StatusLabel, str]:
    """Classify project status based on repository metrics.

    Args:
        pushed_at: Last push timestamp (UTC), or None if unavailable.
        archived: GitHub archived flag, or None if unknown.
        has_repo: Whether a repository was found.
        api_error: Whether the API returned an error for a supported host.
        unsupported_host: Whether the repository host is not supported.

    Returns:
        Tuple of (StatusLabel, reason string).
    """
    # Priority 1: Archived
    if archived is True:
        return StatusLabel.ARCHIVED, "Repository archived flag is true"

    # Priority 2: Data error
    if api_error:
        return StatusLabel.DATA_ERROR, "Supported host returned API error"

    # Priority 3: Unknown (unsupported host or missing repo)
    if unsupported_host:
        return StatusLabel.UNKNOWN, "Repository host not supported in MVP"
    if not has_repo:
        return StatusLabel.UNKNOWN, "No repository URL found"
    if pushed_at is None:
        return StatusLabel.UNKNOWN, "Repository exists but push date unavailable"

    # Priority 4-6: Activity-based (require valid push date)
    now = datetime.now(UTC)
    if pushed_at.tzinfo is None:
        pushed_at = pushed_at.replace(tzinfo=UTC)

    days_since_push = (now - pushed_at).days

    if days_since_push <= 90:
        return StatusLabel.ACTIVE, f"Last push {days_since_push} days ago"
    if days_since_push <= 365:
        return StatusLabel.SLOW, f"Last push {days_since_push} days ago"
    return StatusLabel.STALE, f"Last push {days_since_push} days ago"
