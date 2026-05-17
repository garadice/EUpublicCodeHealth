"""SQLAlchemy ORM models for EU PubliCodeHealth.

Tables match the data model from the implementation plan:
- catalog_sources: source catalogue metadata
- projects: normalized software catalogue entries
- repositories: canonical repository identities
- repository_metrics_snapshots: time-series repo metrics (append-only)
- project_status_snapshots: status labels over time (append-only)
- pipeline_runs: audit log for pipeline executions
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _uuid() -> str:
    return str(uuid.uuid4())


class CatalogSource(Base):
    __tablename__ = "catalog_sources"

    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str | None] = mapped_column(String)
    source_type: Mapped[str | None] = mapped_column(String)
    base_url: Mapped[str | None] = mapped_column(Text)
    api_url: Mapped[str | None] = mapped_column(Text)
    license_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("source_id", "source_project_id", name="uq_projects_source_id_source_project_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.source_id"), nullable=False, index=True)
    source_project_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    development_status: Mapped[str | None] = mapped_column(String, index=True)
    license: Mapped[str | None] = mapped_column(String, index=True)
    software_type: Mapped[str | None] = mapped_column(String)
    raw_publiccode_yml: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False, index=True)
    owner: Mapped[str | None] = mapped_column(String)
    repo_name: Mapped[str | None] = mapped_column(String)
    default_branch: Mapped[str | None] = mapped_column(String)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=True)
    last_resolution_status: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RepositoryMetricsSnapshot(Base):
    __tablename__ = "repository_metrics_snapshots"
    __table_args__ = (Index("ix_rms_repository_id_observed_at", "repository_id", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    stars: Mapped[int | None] = mapped_column(Integer)
    forks: Mapped[int | None] = mapped_column(Integer)
    open_issues: Mapped[int | None] = mapped_column(Integer)
    archived: Mapped[bool | None] = mapped_column(Boolean)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_commit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license_key: Mapped[str | None] = mapped_column(String)
    topics: Mapped[str | None] = mapped_column(Text)  # JSON array stored as text
    api_status: Mapped[str] = mapped_column(String, default="success")


class ProjectStatusSnapshot(Base):
    __tablename__ = "project_status_snapshots"
    __table_args__ = (Index("ix_pss_project_id_observed_at", "project_id", "observed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    status_label: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    data_quality_flags: Mapped[str | None] = mapped_column(Text)  # JSON array


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="running")
    source_name: Mapped[str | None] = mapped_column(String)
    records_seen: Mapped[int | None] = mapped_column(Integer, default=0)
    records_loaded: Mapped[int | None] = mapped_column(Integer, default=0)
    errors_count: Mapped[int | None] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
