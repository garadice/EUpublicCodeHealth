"""Developers Italia API connector.

Fetches software catalogue entries from the Developers Italia API
with cursor-based pagination.

API docs: https://api.developers.italia.it/v1/software
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.developers.italia.it/v1/software"
"""Default Developers Italia software API endpoint."""

DEFAULT_TIMEOUT = 30.0
"""Default HTTP request timeout in seconds."""

MAX_RETRIES = 3
"""Maximum number of retry attempts for transient server errors."""

BACKOFF_BASE = 1.0
"""Base delay in seconds for exponential backoff."""


@dataclass
class FetchResult:
    """Result of fetching all software entries from the API."""

    entries: list[dict[str, Any]]
    total_fetched: int
    pages_fetched: int
    errors: list[str] = field(default_factory=list)
    completed: bool = True


def _get_base_url() -> str:
    return get_settings().developers_italia_base_url


def make_client(*, timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    """Create a pre-configured ``httpx.AsyncClient`` for the API.

    Args:
        timeout: Request timeout in seconds.

    Returns:
        An ``AsyncClient`` ready for use with :func:`fetch_all_software`.
        The caller must close the client when done (or use it as a
        context manager).
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        headers={"Accept": "application/json"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=60),
    )


async def _fetch_page(
    client: httpx.AsyncClient,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch a single page from the API.

    Args:
        client: Shared httpx async client.
        cursor: Opaque cursor from a previous ``links.next`` value, or
            ``None`` to fetch the first page.

    Returns:
        A tuple of (entries_on_page, next_cursor_or_None).

    Raises:
        httpx.HTTPStatusError: On non-retryable HTTP errors.
        ValueError: If the response body is malformed.
    """
    base_url = _get_base_url()
    url = f"{base_url}{cursor}" if cursor else base_url

    response = await client.get(url)
    response.raise_for_status()

    body = response.json()

    if not isinstance(body, dict):
        raise ValueError(f"Expected JSON object, got {type(body).__name__}")

    data = body.get("data")
    if data is None:
        raise ValueError("Response missing required 'data' field")

    if not isinstance(data, list):
        raise ValueError(f"Expected 'data' to be a list, got {type(data).__name__}")

    # Extract next cursor from links.next (relative URL like "?page[after]=abc")
    links = body.get("links", {})
    next_link: str | None = None
    if isinstance(links, dict):
        raw_next = links.get("next")
        if isinstance(raw_next, str) and raw_next:
            next_link = raw_next

    return data, next_link


async def _fetch_page_with_retry(
    client: httpx.AsyncClient,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch a single page with retry on transient 5xx errors.

    Retries up to :data:`MAX_RETRIES` times with exponential backoff for
    server errors (5xx). Client errors (4xx) and malformed responses are
    not retried.

    Args:
        client: Shared httpx async client.
        cursor: Opaque pagination cursor, or ``None`` for the first page.

    Returns:
        A tuple of (entries_on_page, next_cursor_or_None).

    Raises:
        httpx.HTTPStatusError: If all retries are exhausted for 5xx,
            or immediately on 4xx errors.
        ValueError: If the response body is malformed.
    """
    last_error: httpx.HTTPStatusError | None = None

    for attempt in range(MAX_RETRIES):
        try:
            return await _fetch_page(client, cursor)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = float(exc.response.headers.get("retry-after", BACKOFF_BASE * (2**attempt)))
                logger.warning("Rate limited (429), waiting %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                last_error = exc
                continue
            if exc.response.status_code < 500:
                raise
            last_error = exc
            wait_time = BACKOFF_BASE * (2**attempt) * (0.5 + random.random())  # noqa: S311
            logger.warning(
                "Retryable server error on attempt %d/%d (status=%d), waiting %.1fs before retry",
                attempt + 1,
                MAX_RETRIES,
                exc.response.status_code,
                wait_time,
            )
            await asyncio.sleep(wait_time)
        except ValueError:
            raise

    # Loop exhausted — last_error is guaranteed set because the only
    # path that continues the loop is a 5xx HTTPStatusError catch.
    if last_error is None:
        logger.error("Retry loop ended without capturing an error")
        raise RuntimeError("Unexpected state: retry loop ended without an error")

    raise last_error


async def fetch_all_software(client: httpx.AsyncClient) -> FetchResult:
    """Fetch all software entries from Developers Italia API.

    Follows cursor-based pagination via ``links.next`` until the API
    signals no more pages (``next`` is ``null``).

    Args:
        client: A pre-configured ``httpx.AsyncClient``. Use
            :func:`make_client` to create one, or supply your own.
            The caller is responsible for closing the client.

    Returns:
        A :class:`FetchResult` containing all collected entries, page
        counts, and any non-fatal error messages encountered along
        the way.
    """
    all_entries: list[dict[str, Any]] = []
    pages_fetched = 0
    errors: list[str] = []
    cursor: str | None = None
    completed = False

    base_url = _get_base_url()
    logger.info("Starting Developers Italia software fetch from %s", base_url)

    while True:
        try:
            entries, next_cursor = await _fetch_page_with_retry(client, cursor)
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code} fetching page (cursor={cursor!r}): {exc.response.text[:200]}"
            logger.error(msg)
            errors.append(msg)
            break
        except httpx.RequestError as exc:
            msg = f"Network error fetching page (cursor={cursor!r}): {exc}"
            logger.error(msg)
            errors.append(msg)
            break
        except ValueError as exc:
            msg = f"Malformed response fetching page (cursor={cursor!r}): {exc}"
            logger.error(msg)
            errors.append(msg)
            break

        pages_fetched += 1
        entry_count = len(entries)
        all_entries.extend(entries)
        logger.info(
            "Fetched page %d: %d entries (total so far: %d)",
            pages_fetched,
            entry_count,
            len(all_entries),
        )

        if not next_cursor:
            logger.info(
                "Pagination complete: %d entries across %d pages",
                len(all_entries),
                pages_fetched,
            )
            completed = True
            break

        cursor = next_cursor

    return FetchResult(
        entries=all_entries,
        total_fetched=len(all_entries),
        pages_fetched=pages_fetched,
        errors=errors,
        completed=completed,
    )
