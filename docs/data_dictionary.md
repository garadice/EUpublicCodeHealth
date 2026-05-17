# Data Dictionary — EU PubliCodeHealth

This document describes every table and column in the EU PubliCodeHealth database. Use it as a reference when writing queries, building reports, or extending the schema.

> All timestamp columns store timezone-aware datetimes (`TIMESTAMP WITH TIME ZONE`). String columns use `VARCHAR` unless noted as `TEXT`. Primary keys marked "autoincrement" are database-generated sequences.

---

## 1. `catalog_sources`

Source catalogues that EU PubliCodeHealth ingests project data from (e.g., Developers Italia). Each row represents one external catalogue.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `source_id` | `VARCHAR` | NO | — | Unique identifier for the source catalogue (e.g., `"developers_italia"`). **Primary key.** |
| `name` | `VARCHAR` | NO | — | Human-readable source name (e.g., "Developers Italia") |
| `country` | `VARCHAR` | YES | — | ISO 3166-1 alpha-2 country code (e.g., `"IT"`) |
| `source_type` | `VARCHAR` | YES | — | Type of catalogue (e.g., `"national"`, `"regional"`) |
| `base_url` | `TEXT` | YES | — | URL of the source catalogue website |
| `api_url` | `TEXT` | YES | — | API endpoint URL used for data ingestion |
| `license_url` | `TEXT` | YES | — | URL to the catalogue's licence information |
| `active` | `BOOLEAN` | YES | `TRUE` | Whether this source is currently being ingested by the pipeline |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Row creation timestamp (server-generated) |

**Indexes:** Primary key on `source_id`.

**Foreign keys:** None.

---

## 2. `projects`

Open-source projects discovered from source catalogues. A project groups one or more repositories and carries metadata parsed from its `publiccode.yml`.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `VARCHAR` (UUID) | NO | — | Internal UUID identifying this project. **Primary key.** |
| `source_id` | `VARCHAR` | NO | — | Source catalogue this project was ingested from |
| `source_project_id` | `VARCHAR` | NO | — | Original project identifier in the source catalogue |
| `name` | `VARCHAR` | NO | — | Project name, parsed from `publiccode.yml` |
| `description` | `TEXT` | YES | — | Project description |
| `development_status` | `VARCHAR` | YES | — | Development status from `publiccode.yml` (e.g., `"stable"`, `"beta"`, `"concept"`) |
| `license` | `VARCHAR` | YES | — | SPDX license identifier (e.g., `"AGPL-3.0"`, `"MIT"`) |
| `software_type` | `VARCHAR` | YES | — | Software type classification (e.g., `"standalone"`, `"library"`) |
| `raw_publiccode_yml` | `TEXT` | YES | — | Full raw content of the project's `publiccode.yml` file |
| `source_url` | `TEXT` | YES | — | URL to the project page on the source catalogue |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Row last-updated timestamp; auto-refreshes on every `UPDATE` |

**Table-level constraints:**

- `UNIQUE (source_id, source_project_id)` — prevents duplicate ingestion of the same project from the same catalogue.

**Indexes:**

| Index | Columns | Purpose |
|---|---|---|
| Primary key | `id` | Row lookup |
| `ix_projects_source_id` | `source_id` | FK join, source filtering |
| `ix_projects_name` | `name` | Name search |
| `ix_projects_development_status` | `development_status` | Status filtering |
| `ix_projects_license` | `license` | License filtering |
| Unique | `(source_id, source_project_id)` | Deduplication |

**Foreign keys:**

| Column | References |
|---|---|
| `source_id` | `catalog_sources.source_id` |

---

## 3. `repositories`

Individual code repositories associated with projects. Each repository is normalised to a canonical URL and classified by host platform.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `VARCHAR` (UUID) | NO | — | Internal UUID. **Primary key.** |
| `project_id` | `VARCHAR` | NO | — | Parent project this repository belongs to |
| `canonical_url` | `TEXT` | NO | — | Canonicalised repository URL (lowercased, trailing slashes removed). **Unique.** |
| `host` | `VARCHAR` | NO | — | Host platform classification: `"github"`, `"gitlab"`, or `"unsupported"` |
| `owner` | `VARCHAR` | YES | — | Repository owner (GitHub username or organisation) |
| `repo_name` | `VARCHAR` | YES | — | Repository name within the host platform |
| `default_branch` | `VARCHAR` | YES | — | Default branch name (e.g., `"main"`, `"master"`) |
| `is_supported` | `BOOLEAN` | YES | `TRUE` | Whether the host platform is supported for metrics enrichment |
| `last_resolution_status` | `VARCHAR` | YES | — | Result of the last API resolution attempt (e.g., `"ok"`, `"not_found"`) |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Row creation timestamp |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Row last-updated timestamp; auto-refreshes on every `UPDATE` |

**Table-level constraints:**

- `UNIQUE (canonical_url)` — each repository URL appears exactly once.

**Indexes:**

| Index | Columns | Purpose |
|---|---|---|
| Primary key | `id` | Row lookup |
| `ix_repositories_project_id` | `project_id` | FK join, project-scoped queries |
| `ix_repositories_host` | `host` | Host filtering |
| Unique | `canonical_url` | URL deduplication |

**Foreign keys:**

| Column | References |
|---|---|
| `project_id` | `projects.id` |

---

## 4. `repository_metrics_snapshots`

Point-in-time activity metrics captured for each repository during a pipeline run. This table is **append-only**: rows are never updated or deleted, preserving a full historical record.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `BIGINT` | NO | autoincrement | Surrogate key. **Primary key.** |
| `repository_id` | `VARCHAR` | NO | — | Repository these metrics belong to |
| `run_id` | `BIGINT` | NO | — | Pipeline run that produced this snapshot |
| `observed_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | When the metric values were observed |
| `stars` | `INTEGER` | YES | — | GitHub star count at observation time |
| `forks` | `INTEGER` | YES | — | GitHub fork count at observation time |
| `open_issues` | `INTEGER` | YES | — | Open issue count at observation time |
| `archived` | `BOOLEAN` | YES | — | Whether the repository is archived on GitHub |
| `pushed_at` | `TIMESTAMP WITH TIME ZONE` | YES | — | Timestamp of the most recent push to the repository |
| `latest_commit_at` | `TIMESTAMP WITH TIME ZONE` | YES | — | Date of the latest commit on the default branch |
| `latest_release_at` | `TIMESTAMP WITH TIME ZONE` | YES | — | Date of the most recent GitHub release |
| `license_key` | `VARCHAR` | YES | — | SPDX license identifier reported by GitHub |
| `topics` | `TEXT` | YES | — | JSON array of GitHub repository topics (e.g., `["open-data","api"]`) |
| `api_status` | `VARCHAR` | YES | `"success"` | Result of the GitHub API call: `"success"`, `"not_found"`, `"rate_limited"`, or `"error"` |

**Table-level notes:**

- **Append-only.** No `UPDATE` or `DELETE` operations are performed. Each pipeline run inserts new rows, enabling full trend analysis over time.

**Indexes:**

| Index | Columns | Purpose |
|---|---|---|
| Primary key | `id` | Row lookup |
| `ix_repo_metrics_repository_id` | `repository_id` | FK join, repository-scoped queries |
| `ix_repo_metrics_run_id` | `run_id` | FK join, run-scoped queries |
| `ix_repo_metrics_observed_at` | `observed_at` | Time-range filtering |
| Composite | `(repository_id, observed_at)` | Efficient latest-snapshot-per-repo queries |

**Foreign keys:**

| Column | References |
|---|---|
| `repository_id` | `repositories.id` |
| `run_id` | `pipeline_runs.id` |

---

## 5. `project_status_snapshots`

Point-in-time health-status classifications for each project. The pipeline computes a status label based on repository activity metrics and records it here. This table is **append-only**: rows are never updated or deleted.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `BIGINT` | NO | autoincrement | Surrogate key. **Primary key.** |
| `project_id` | `VARCHAR` | NO | — | Project this classification applies to |
| `repository_id` | `VARCHAR` | NO | — | Representative repository used to determine the status label |
| `run_id` | `BIGINT` | NO | — | Pipeline run that produced this classification |
| `observed_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | When the status was calculated |
| `status_label` | `VARCHAR` | NO | — | Classification label. One of: `Active`, `Slow`, `Stale`, `Archived`, `Unknown`, `Data error` |
| `reason` | `TEXT` | NO | — | Human-readable explanation of why this label was applied (e.g., "Latest commit was 142 days ago") |
| `data_quality_flags` | `TEXT` | YES | — | JSON array of data quality issues detected (e.g., `["invalid_yaml", "missing_url"]`). `NULL` when no issues found |

**Status label priority (highest to lowest):**

| Priority | Label | Rule |
|---|---|---|
| 1 | `Archived` | GitHub `archived` flag is `TRUE` |
| 2 | `Data error` | A supported host returned an API error |
| 3 | `Unknown` | Unsupported host or missing repository URL |
| 4 | `Active` | Latest commit within the last 90 days |
| 5 | `Slow` | Latest commit between 91 and 365 days ago |
| 6 | `Stale` | Latest commit more than 365 days ago |

**Table-level notes:**

- **Append-only.** No `UPDATE` or `DELETE` operations are performed, preserving the full history of status changes.

**Indexes:**

| Index | Columns | Purpose |
|---|---|---|
| Primary key | `id` | Row lookup |
| `ix_project_status_project_id` | `project_id` | FK join, project-scoped queries |
| `ix_project_status_run_id` | `run_id` | FK join, run-scoped queries |
| `ix_project_status_observed_at` | `observed_at` | Time-range filtering |
| `ix_project_status_status_label` | `status_label` | Label filtering |
| Composite | `(project_id, observed_at)` | Efficient latest-status-per-project queries |

**Foreign keys:**

| Column | References |
|---|---|
| `project_id` | `projects.id` |
| `repository_id` | `repositories.id` |
| `run_id` | `pipeline_runs.id` |

---

## 6. `pipeline_runs`

Audit log for every pipeline execution. Each run records start/end times, record counts, and error summaries.

| Column | Type | Nullable | Default | Description |
|---|---|---|---|---|
| `id` | `BIGINT` | NO | autoincrement | Surrogate key. **Primary key.** |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | YES | `now()` | Timestamp when the pipeline run started |
| `finished_at` | `TIMESTAMP WITH TIME ZONE` | YES | — | Timestamp when the pipeline run finished. `NULL` while the run is in progress |
| `status` | `VARCHAR` | YES | `"running"` | Run state: `"running"`, `"completed"`, or `"failed"` |
| `source_name` | `VARCHAR` | YES | — | Name of the source catalogue processed in this run |
| `records_seen` | `INTEGER` | YES | `0` | Total number of records encountered during ingestion |
| `records_loaded` | `INTEGER` | YES | `0` | Number of records successfully loaded into the database |
| `errors_count` | `INTEGER` | YES | `0` | Number of errors encountered during the run |
| `error_summary` | `TEXT` | YES | — | Free-text summary of errors (if any occurred) |

**Indexes:**

| Index | Columns | Purpose |
|---|---|---|
| Primary key | `id` | Row lookup |

**Foreign keys:** None.

---

## Entity-Relationship Summary

```
catalog_sources  1──N  projects  1──N  repositories
                                    │         │
                                    │         └──N  repository_metrics_snapshots  N──1  pipeline_runs
                                    │
                                    └──N  project_status_snapshots  N──1  pipeline_runs
```

- A **catalogue source** contains many **projects**.
- A **project** has many **repositories** (one per code hosting URL).
- Each **repository** accumulates many **metric snapshots** (one per pipeline run).
- Each **project** accumulates many **status snapshots** (one per pipeline run).
- Every snapshot row references the **pipeline run** that created it.
