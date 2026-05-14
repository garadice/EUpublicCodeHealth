import hashlib
import json
import os
from typing import Any

import httpx
import yaml


def _normalize_record(record: dict[str, Any], source_id: str, source_name: str, source_url: str, idx: int = 0) -> dict[str, Any]:
    name = record.get("name") or record.get("localisedName") or record.get("title") or f"unknown-project-{idx}"
    repo_url = record.get("url") or record.get("landingURL") or record.get("repository")
    license_name = None
    legal = record.get("legal")
    if isinstance(legal, dict):
        license_name = legal.get("license")
    elif isinstance(record.get("license"), str):
        license_name = record.get("license")

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


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if "projects" in payload and isinstance(payload["projects"], list):
            return [x for x in payload["projects"] if isinstance(x, dict)]
        return [payload]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def fetch_catalog_projects() -> list[dict[str, Any]]:
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
            if surl.endswith(".json"):
                payload = r.json()
            else:
                payload = yaml.safe_load(r.text)

            records = _extract_records(payload)
            for idx, rec in enumerate(records):
                out.append(_normalize_record(rec, sid, sname, surl, idx))
    return out
