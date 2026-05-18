"""GitHub REST API client for fetching repository metrics.

Provides authenticated access to the GitHub API with rate limit
handling, retry logic, and exponential backoff.

API docs: https://docs.github.com/en/rest/repos/repos
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GITHUB_API_BASE = "https://api.github.com"
"""Base URL for the GitHub REST API."""

DEFAULT_TIMEOUT = 30.0
"""Default HTTP request timeout in seconds."""

MAX_RETRIES = 3
"""Maximum number of retry attempts for transient server errors."""

BACKOFF_BASE = 1.0
"""Base delay in seconds for exponential backoff."""

RATE_LIMIT_THRESHOLD = 10
"""Warn when remaining rate limit drops below this value."""

MIN_RATE_LIMIT_REMAINING = 1
"""Stop fetching when remaining rate limit drops to this value."""


@dataclass
class GitHubRepoMetrics:
    """Parsed repository metrics from the GitHub API."""

    owner: str
    repo_name: str
    stars: int
    forks: int
    open_issues: int
    archived: bool
    pushed_at: datetime | None
    license_key: str | None
    topics: list[str]
    default_branch: str
    html_url: str
    api_status: str = "success"
    error_message: str | None = None

    @classmethod
    def error(cls, owner: str, repo_name: str, api_status: str, error_message: str) -> GitHubRepoMetrics:
        return cls(
            owner=owner,
            repo_name=repo_name,
            stars=0,
            forks=0,
            open_issues=0,
            archived=False,
            pushed_at=None,
            license_key=None,
            topics=[],
            default_branch="main",
            html_url="",
            api_status=api_status,
            error_message=error_message,
        )


@dataclass
class RateLimitInfo:
    """GitHub API rate limit status parsed from response headers."""

    remaining: int
    limit: int
    reset_at: datetime | None

    @property
    def is_exhausted(self) -> bool:
        return self.remaining <= MIN_RATE_LIMIT_REMAINING


def _parse_github_datetime(value: str | None) -> datetime | None:
    """Parse a GitHub API ISO 8601 datetime string.

    GitHub returns dates like ``2024-01-15T10:30:00Z``.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        logger.warning("Failed to parse GitHub datetime: %s", value)
        return None


def _parse_rate_limit_headers(headers: httpx.Headers) -> RateLimitInfo:
    """Extract rate limit information from GitHub response headers."""
    remaining = int(headers.get("x-ratelimit-remaining", "5000"))
    limit = int(headers.get("x-ratelimit-limit", "5000"))
    reset_unix = headers.get("x-ratelimit-reset")

    reset_at: datetime | None = None
    if reset_unix:
        with contextlib.suppress(ValueError, OSError):
            reset_at = datetime.fromtimestamp(int(reset_unix), tz=UTC)

    return RateLimitInfo(remaining=remaining, limit=limit, reset_at=reset_at)


def _extract_repo_metrics(data: dict[str, Any], owner: str, repo_name: str) -> GitHubRepoMetrics:
    """Extract relevant fields from a GitHub repo API response."""
    license_info = data.get("license")
    license_key: str | None = None
    if isinstance(license_info, dict):
        license_key = license_info.get("spdx_id")

    topics_raw = data.get("topics")
    topics: list[str] = list(topics_raw) if isinstance(topics_raw, list) else []

    return GitHubRepoMetrics(
        owner=owner,
        repo_name=repo_name,
        stars=data.get("stargazers_count", 0),
        forks=data.get("forks_count", 0),
        open_issues=data.get("open_issues_count", 0),
        archived=data.get("archived", False),
        pushed_at=_parse_github_datetime(data.get("pushed_at")),
        license_key=license_key,
        topics=topics,
        default_branch=data.get("default_branch", "main"),
        html_url=data.get("html_url", ""),
        api_status="success",
    )


def make_github_client(*, timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Create a pre-configured ``httpx.AsyncClient`` for GitHub API.

    Args:
        timeout: Request timeout in seconds.

    Returns:
        An ``AsyncClient`` with authentication headers. The caller
        must close the client when done (or use as context manager).
    """
    settings = get_settings()
    headers: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    return httpx.AsyncClient(
        base_url=GITHUB_API_BASE,
        timeout=httpx.Timeout(timeout),
        headers=headers,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60),
    )


async def fetch_repo_metrics(
    client: httpx.AsyncClient,
    owner: str,
    repo_name: str,
) -> GitHubRepoMetrics:
    """Fetch metrics for a single GitHub repository.

    Handles rate limits, retries on 5xx errors, and returns structured
    results with ``api_status`` indicating the outcome.

    Args:
        client: Authenticated httpx async client.
        owner: Repository owner (user or org).
        repo_name: Repository name.

    Returns:
        GitHubRepoMetrics with parsed data or error information.
    """
    url = f"/repos/{owner}/{repo_name}"
    last_error_msg: str | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(url)
        except httpx.RequestError as exc:
            last_error_msg = f"Network error: {exc}"
            logger.warning(
                "Request error for %s/%s (attempt %d/%d): %s",
                owner,
                repo_name,
                attempt + 1,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE * (2**attempt) * (0.5 + random.random())  # noqa: S311
                await asyncio.sleep(wait)
            continue

        # Check rate limit headers
        rate_limit = _parse_rate_limit_headers(response.headers)
        if rate_limit.remaining <= RATE_LIMIT_THRESHOLD:
            logger.warning(
                "GitHub rate limit low: %d/%d remaining (reset at %s)",
                rate_limit.remaining,
                rate_limit.limit,
                rate_limit.reset_at,
            )

        # Success
        if response.status_code == 200:
            data = response.json()
            return _extract_repo_metrics(data, owner, repo_name)

        # Not found — do not retry
        if response.status_code == 404:
            logger.info("Repository %s/%s not found (404)", owner, repo_name)
            return GitHubRepoMetrics.error(owner, repo_name, "not_found", "Repository not found (HTTP 404)")

        # Rate limited — wait and retry
        if response.status_code == 403:
            rate_limit = _parse_rate_limit_headers(response.headers)
            if rate_limit.is_exhausted:
                wait_until = rate_limit.reset_at
                if wait_until:
                    wait_seconds = max(0, (wait_until - datetime.now(UTC)).total_seconds() + 1)
                    logger.warning(
                        "GitHub rate limit exhausted for %s/%s. Waiting %.0fs until reset.",
                        owner,
                        repo_name,
                        wait_seconds,
                    )
                    await asyncio.sleep(min(wait_seconds, 3600))
                    continue
                else:
                    # No reset time — use exponential backoff instead
                    if attempt < MAX_RETRIES - 1:
                        wait = BACKOFF_BASE * (2**attempt) * (0.5 + random.random())  # noqa: S311
                        logger.warning(
                            "Rate limit exhausted, no reset time. Backing off %.1fs (attempt %d/%d)",
                            wait,
                            attempt + 1,
                            MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue
            # Other 403 (e.g. repo access blocked) — do not retry
            body_preview = response.text[:200]
            logger.warning("GitHub 403 for %s/%s: %s", owner, repo_name, body_preview)
            return GitHubRepoMetrics.error(owner, repo_name, "rate_limited", f"HTTP 403: {body_preview}")

        # 5xx — retry with backoff
        if response.status_code >= 500:
            last_error_msg = f"HTTP {response.status_code}"
            logger.warning(
                "Server error for %s/%s (attempt %d/%d, status=%d)",
                owner,
                repo_name,
                attempt + 1,
                MAX_RETRIES,
                response.status_code,
            )
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE * (2**attempt) * (0.5 + random.random())  # noqa: S311
                await asyncio.sleep(wait)
            continue

        # Other non-success — do not retry
        last_error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
        logger.warning(
            "Unexpected status %d for %s/%s: %s",
            response.status_code,
            owner,
            repo_name,
            response.text[:200],
        )
        break

    # All retries exhausted or unexpected error
    return GitHubRepoMetrics.error(owner, repo_name, "error", last_error_msg or "All retries exhausted")
