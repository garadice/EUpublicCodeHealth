"""Pipeline step: Ingest catalogue data.

Collects, parses, and normalizes project metadata from catalogue sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.publiccode_parser import ParsedPubliccode, parse_publiccode
from app.core.url_normalize import HostType, NormalizedURL, normalize_repo_url
from app.db.models import CatalogSource, PipelineRun, Project, Repository
from app.db.session import get_session_factory
from connectors.developers_italia import fetch_all_software, make_client

logger = get_logger(__name__)


@dataclass
class IngestedProject:
    source_id: str
    source_project_id: str
    raw_url: str
    parsed: ParsedPubliccode
    normalized_url: NormalizedURL
    aliases: list[str]
    active: bool
    created_at: datetime | None
    updated_at: datetime | None
    raw_publiccode_yml: str | None = None


@dataclass
class IngestResult:
    projects: list[IngestedProject]
    total_fetched: int
    total_parsed_ok: int
    parse_errors: int
    github_count: int
    gitlab_count: int
    unsupported_count: int
    invalid_url_count: int
    errors: list[str] = field(default_factory=list)


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_url(entry: dict[str, Any]) -> str:
    raw_url: str | None = entry.get("url")
    if raw_url and isinstance(raw_url, str) and raw_url.strip():
        return raw_url.strip()
    return ""


def _extract_aliases(entry: dict[str, Any]) -> list[str]:
    raw_aliases: Any = entry.get("aliases")
    if not isinstance(raw_aliases, list):
        return []
    aliases: list[str] = []
    for alias in raw_aliases:
        if isinstance(alias, str) and alias.strip():
            aliases.append(alias.strip())
    return aliases


def _process_entry(entry: dict[str, Any]) -> IngestedProject | None:
    source_project_id = str(entry.get("id", ""))
    if not source_project_id:
        logger.warning("Skipping entry with missing id")
        return None

    raw_yaml: str = entry.get("publiccodeYml", "") or ""
    if not isinstance(raw_yaml, str):
        raw_yaml = str(raw_yaml)

    parsed = parse_publiccode(raw_yaml)

    raw_url = _extract_url(entry)
    normalized_url = normalize_repo_url(raw_url)

    if normalized_url.host == HostType.INVALID and parsed.url:
        normalized_url = normalize_repo_url(parsed.url)
        if normalized_url.host != HostType.INVALID:
            raw_url = parsed.url

    aliases = _extract_aliases(entry)

    active = bool(entry.get("active", True))

    created_at = _parse_iso_timestamp(entry.get("createdAt") if isinstance(entry.get("createdAt"), str) else None)
    updated_at = _parse_iso_timestamp(entry.get("updatedAt") if isinstance(entry.get("updatedAt"), str) else None)

    return IngestedProject(
        source_id="developers_italia",
        source_project_id=source_project_id,
        raw_url=raw_url,
        parsed=parsed,
        normalized_url=normalized_url,
        aliases=aliases,
        active=active,
        created_at=created_at,
        updated_at=updated_at,
        raw_publiccode_yml=raw_yaml,
    )


async def ingest_developers_italia(client: httpx.AsyncClient) -> IngestResult:
    fetch_result = await fetch_all_software(client)

    if fetch_result.errors:
        logger.warning(
            "Ingestion finished with errors: %d error(s): %s",
            len(fetch_result.errors),
            "; ".join(fetch_result.errors[:5]),
        )

    if not fetch_result.completed:
        logger.warning("Partial data: pagination did not complete — results may be incomplete")

    projects: list[IngestedProject] = []
    parse_errors = 0
    github_count = 0
    gitlab_count = 0
    unsupported_count = 0
    invalid_url_count = 0

    for entry in fetch_result.entries:
        project = _process_entry(entry)
        if project is None:
            continue

        if project.parsed.parse_error is not None:
            parse_errors += 1
            logger.debug(
                "Parse error for entry %s: %s",
                project.source_project_id,
                project.parsed.parse_error,
            )

        host = project.normalized_url.host
        if host == HostType.GITHUB:
            github_count += 1
        elif host == HostType.GITLAB:
            gitlab_count += 1
        elif host == HostType.UNSUPPORTED:
            unsupported_count += 1
        else:
            invalid_url_count += 1

        projects.append(project)

    total_parsed_ok = sum(1 for p in projects if p.parsed.parse_error is None)

    if fetch_result.errors:
        log_msg = (
            "Ingestion finished with errors: %d projects fetched, %d parsed ok, "
            "%d parse errors, %d github, %d gitlab, %d unsupported, %d invalid"
        )
    else:
        log_msg = (
            "Ingestion complete: %d projects fetched, %d parsed ok, "
            "%d parse errors, %d github, %d gitlab, %d unsupported, %d invalid"
        )

    logger.info(
        log_msg,
        fetch_result.total_fetched,
        total_parsed_ok,
        parse_errors,
        github_count,
        gitlab_count,
        unsupported_count,
        invalid_url_count,
    )

    all_errors = list(fetch_result.errors)

    return IngestResult(
        projects=projects,
        total_fetched=fetch_result.total_fetched,
        total_parsed_ok=total_parsed_ok,
        parse_errors=parse_errors,
        github_count=github_count,
        gitlab_count=gitlab_count,
        unsupported_count=unsupported_count,
        invalid_url_count=invalid_url_count,
        errors=all_errors,
    )


async def run_ingestion() -> IngestResult:
    async with make_client() as client:
        return await ingest_developers_italia(client)


def persist_ingestion_results(session: Session, result: IngestResult) -> None:
    """Persist ingestion results to the database using upserts.

    1. Upsert catalog_source
    2. Upsert projects (on source_id + source_project_id)
    3. Upsert repositories (on canonical_url)
    4. Insert pipeline_run record
    """
    _upsert_catalog_source(session)
    project_id_map = _upsert_projects(session, result.projects)
    _upsert_repositories(session, result.projects, project_id_map)
    _insert_pipeline_run(session, result)
    session.flush()


def _upsert_catalog_source(session: Session) -> None:
    stmt = pg_insert(CatalogSource).values(
        source_id="developers_italia",
        name="Developers Italia",
        country="IT",
        source_type="api",
        api_url="https://api.developers.italia.it/v1/software",
        active=True,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["source_id"])
    session.execute(stmt)


def _upsert_projects(session: Session, projects: list[IngestedProject]) -> dict[str, str]:
    project_id_map: dict[str, str] = {}

    for proj in projects:
        values = {
            "source_id": proj.source_id,
            "source_project_id": proj.source_project_id,
            "name": proj.parsed.name or proj.source_project_id,
            "description": proj.parsed.description,
            "development_status": proj.parsed.development_status,
            "license": proj.parsed.license,
            "software_type": proj.parsed.software_type,
            "raw_publiccode_yml": proj.raw_publiccode_yml,
            "source_url": proj.raw_url or None,
        }
        stmt = (
            pg_insert(Project)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_projects_source_id_source_project_id",
                set_={
                    "name": values["name"],
                    "description": values["description"],
                    "development_status": values["development_status"],
                    "license": values["license"],
                    "software_type": values["software_type"],
                    "raw_publiccode_yml": values["raw_publiccode_yml"],
                    "source_url": values["source_url"],
                    "updated_at": func.now(),
                },
            )
            .returning(Project.id, Project.source_project_id)
        )
        row = session.execute(stmt).fetchone()
        if row is not None:
            project_id_map[row.source_project_id] = row.id

    session.flush()
    return project_id_map


def _upsert_repositories(
    session: Session,
    projects: list[IngestedProject],
    project_id_map: dict[str, str],
) -> None:
    """Upsert repositories for projects with valid normalized URLs."""
    for proj in projects:
        if proj.normalized_url.host == HostType.INVALID:
            continue
        if not proj.normalized_url.canonical_url:
            continue

        db_project_id = project_id_map.get(proj.source_project_id)
        if db_project_id is None:
            logger.warning("Skipping repository for project %s: no DB id found", proj.source_project_id)
            continue

        is_supported = proj.normalized_url.host in (HostType.GITHUB, HostType.GITLAB)

        values = {
            "project_id": db_project_id,
            "canonical_url": proj.normalized_url.canonical_url,
            "host": str(proj.normalized_url.host),
            "owner": proj.normalized_url.owner,
            "repo_name": proj.normalized_url.repo_name,
            "is_supported": is_supported,
        }
        stmt = pg_insert(Repository).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["canonical_url"],
            set_={
                "host": stmt.excluded.host,
                "owner": stmt.excluded.owner,
                "repo_name": stmt.excluded.repo_name,
                "is_supported": stmt.excluded.is_supported,
                "project_id": stmt.excluded.project_id,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)


def _insert_pipeline_run(session: Session, result: IngestResult) -> None:
    parsed_ok_count = sum(1 for p in result.projects if p.parsed.parse_error is None)
    has_errors = bool(result.errors)
    run_status = "partial" if has_errors else "success"

    run = PipelineRun(
        source_name="developers_italia",
        records_seen=result.total_fetched,
        records_loaded=parsed_ok_count,
        errors_count=len(result.errors),
        error_summary="; ".join(result.errors[:5]) if result.errors else None,
        status=run_status,
    )
    session.add(run)


async def run_ingestion_with_persistence() -> IngestResult:
    """Run ingestion and persist results to the database."""
    result = await run_ingestion()
    factory = get_session_factory()
    session = factory()
    try:
        persist_ingestion_results(session, result)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return result
