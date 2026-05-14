import hashlib
import json
import os
from typing import Any

import httpx
import yaml


def _parse_publiccode_payload(data: dict[str, Any], source_id: str, source_name: str, source_url: str) -> dict[str, Any]:
    name = data.get("name") or data.get("localisedName") or "unknown-project"
    repo_url = data.get("url") or data.get("landingURL")
    license_name = None
    legal = data.get("legal")
    if isinstance(legal, dict):
        license_name = legal.get("license")

    project_id = hashlib.md5(f"{source_id}:{name}:{repo_url}".encode()).hexdigest()
    return {
        "source_id": source_id,
        "source_name": source_name,
        "source_url": source_url,
        "project_id": project_id,
        "name": str(name),
        "repo_url": repo_url,
        "license": license_name,
    }


def fetch_catalog_projects() -> list[dict[str, Any]]:
    """
    SOURCE_CATALOG_URLS supports JSON array:
    [{"id":"...","name":"...","url":"..."}]
    Fallback: SOURCE_CATALOG_URL single URL.
    """
    raw_sources = os.getenv("SOURCE_CATALOG_URLS", "").strip()
    sources: list[dict[str, str]] = []

    if raw_sources:
        sources = json.loads(raw_sources)
    else:
        fallback = os.getenv("SOURCE_CATALOG_URL", "").strip()
        if fallback:
            sources = [{"id": "publiccode_example", "name": "Publiccode Example", "url": fallback}]

    if not sources:
        raise ValueError("No catalogue sources configured. Set SOURCE_CATALOG_URL or SOURCE_CATALOG_URLS.")

    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=30) as client:
        for source in sources:
            sid = source["id"]
            sname = source.get("name", sid)
            surl = source["url"]
            r = client.get(surl)
            r.raise_for_status()
            data = yaml.safe_load(r.text)
            if not isinstance(data, dict):
                continue
            out.append(_parse_publiccode_payload(data, sid, sname, surl))
    return out
