"""Pydantic response models for API endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectItem(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    status_label: str | None = None
    reason: str | None = None
    host: str | None = None
    canonical_url: str | None = None
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    pushed_at: datetime | None = None
    license: str | None = None
    development_status: str | None = None
    last_updated: datetime | None = None


class ProjectsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[ProjectItem]


class SummaryResponse(BaseModel):
    Archived: int = 0
    Data_error: int = Field(default=0, alias="Data error")
    Unknown: int = 0
    Active: int = 0
    Slow: int = 0
    Stale: int = 0
    total: int = 0
    total_with_repo: int = 0
    total_without_repo: int = 0
    unsupported_host_count: int = 0

    model_config = {"populate_by_name": True}


class PipelineRunItem(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    source_name: str | None = None
    records_seen: int | None = None
    records_loaded: int | None = None
    errors_count: int | None = None
    error_summary: str | None = None


class PipelineRunsResponse(BaseModel):
    data: list[PipelineRunItem]
