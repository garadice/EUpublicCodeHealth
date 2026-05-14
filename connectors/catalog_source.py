import hashlib
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
