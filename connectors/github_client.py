import os
import re
import time
import httpx


def parse_github(url: str):
    if not url:
        return None, None
    m = re.search(r"github\.com/([^/]+)/([^/\s#?]+)", url)
    if not m:
        return None, None
    return m.group(1), m.group(2).replace('.git', '')


def fetch_repo(owner: str, repo: str, retries: int = 3):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    backoff = 1.0
    with httpx.Client(timeout=30, headers=headers) as client:
        for attempt in range(1, retries + 1):
            r = client.get(f"https://api.github.com/repos/{owner}/{repo}")
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt < retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            r.raise_for_status()
            return r.json()
    return None
