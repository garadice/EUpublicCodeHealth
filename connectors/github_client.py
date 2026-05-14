import os
import re
import httpx


def parse_github(url: str):
    if not url:
        return None, None
    m = re.search(r"github\.com/([^/]+)/([^/\s#?]+)", url)
    if not m:
        return None, None
    return m.group(1), m.group(2).replace('.git', '')


def fetch_repo(owner: str, repo: str):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30, headers=headers) as client:
        r = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
