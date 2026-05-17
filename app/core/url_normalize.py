"""URL normalization and repository host classification.

Canonicalizes repository URLs and classifies their hosting platform.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

_FRAGMENT_RE = re.compile(r"[#?]")
_GITHUB_PATH_RE = re.compile(r"github\.com/([^/]+)/([^/\s]+)")


class HostType(StrEnum):
    """Supported repository hosting platforms."""

    GITHUB = "github"
    GITLAB = "gitlab"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


@dataclass(frozen=True)
class NormalizedURL:
    """Result of URL normalization."""

    canonical_url: str
    host: HostType
    owner: str | None
    repo_name: str | None
    is_supported: bool


def normalize_repo_url(raw_url: str | None) -> NormalizedURL:
    """Canonicalize a repository URL and classify its host.

    Args:
        raw_url: Raw repository URL from catalogue metadata.

    Returns:
        NormalizedURL with canonical form and host classification.
    """
    if not raw_url or not raw_url.strip():
        return NormalizedURL(
            canonical_url="",
            host=HostType.INVALID,
            owner=None,
            repo_name=None,
            is_supported=False,
        )

    url = raw_url.strip()

    # Force https
    if url.startswith("http://"):
        url = "https://" + url[7:]

    # Strip trailing slashes and .git suffix
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    url = _FRAGMENT_RE.split(url)[0]

    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if hostname == "github.com" or hostname.endswith(".github.com"):
        return _parse_github_url(url)
    if "gitlab" in hostname:
        return NormalizedURL(
            canonical_url=url,
            host=HostType.GITLAB,
            owner=None,
            repo_name=None,
            is_supported=False,
        )

    return NormalizedURL(
        canonical_url=url,
        host=HostType.UNSUPPORTED,
        owner=None,
        repo_name=None,
        is_supported=False,
    )


def _parse_github_url(url: str) -> NormalizedURL:
    """Parse a GitHub URL into owner and repo name."""
    match = _GITHUB_PATH_RE.search(url)
    if not match:
        return NormalizedURL(
            canonical_url=url,
            host=HostType.GITHUB,
            owner=None,
            repo_name=None,
            is_supported=True,
        )

    owner = match.group(1)
    repo_name = match.group(2).rstrip("/")

    # Reconstruct canonical URL
    canonical = f"https://github.com/{owner}/{repo_name}"

    return NormalizedURL(
        canonical_url=canonical,
        host=HostType.GITHUB,
        owner=owner,
        repo_name=repo_name,
        is_supported=True,
    )
