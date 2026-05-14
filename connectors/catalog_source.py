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


def fetch_catalog_projects() -> list[dict[str, Any]]:
    """
    SOURCE_CATALOG_URLS supports JSON array:
    [{"id":"...","name":"...","url":"..."}]
    Fallback: SOURCE_CATALOG_URL single URL.
    """
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
            data = yaml.safe_load(r.text)
            if not isinstance(data, dict):
                continue
            out.append(_parse_publiccode_payload(data, sid, sname, surl))
    return out
            if surl.endswith(".json"):
                payload = r.json()
            else:
                payload = yaml.safe_load(r.text)

            records = _extract_records(payload)
            for idx, rec in enumerate(records):
                out.append(_normalize_record(rec, sid, sname, surl, idx))
    return out
import os
import yaml
import httpx


def fetch_publiccode_project():
    url = os.getenv("SOURCE_CATALOG_URL")
    with httpx.Client(timeout=30) as client:
        r = client.get(url)
        r.raise_for_status()
    data = yaml.safe_load(r.text)
    name = data.get("name", "unknown-project")
    repo = data.get("softwareVersion") or data.get("url") or data.get("landingURL")
    if not repo:
        repo = data.get("developmentStatus")
    project_id = hashlib.md5(f"{name}:{repo}".encode()).hexdigest()
    return {
        "source_id": "publiccode_example",
        "source_name": "Publiccode Example",
        "source_url": url,
        "project_id": project_id,
        "name": name,
        "repo_url": data.get("url") or data.get("landingURL"),
        "license": data.get("legal", {}).get("license") if isinstance(data.get("legal"), dict) else None,
    }
