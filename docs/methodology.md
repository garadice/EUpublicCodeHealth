# Methodology

## 1. Overview

EU PubliCodeHealth monitors the **repository activity** of open-source software listed in EU public-sector catalogues. It ingests catalogue metadata, enriches GitHub-hosted repositories with activity metrics from the GitHub REST API, classifies each project into a health status label, and exposes the results through a FastAPI API and Streamlit dashboard.

This methodology document describes the data sources, ingestion pipeline, enrichment process, classification rules, and known limitations of the system.

**What this project measures:** Repository-level activity indicators — commit frequency, release cadence, archival status, and basic GitHub engagement metrics.

**What this project does NOT measure:** Code quality, security vulnerabilities, dependency health, license compliance, community well-being, or fitness for any particular procurement decision. See [Section 9](#9-what-this-project-does-not-measure) for the full list of exclusions.

---

## 2. Data Sources

### Developers Italia Software Catalogue

**Endpoint:** `https://api.developers.italia.it/v1/software`

The primary data source is the Developers Italia API, which indexes open-source software used or produced by Italian public administrations.

| Property | Detail |
|---|---|
| Pagination | Cursor-based (`cursor` query parameter) |
| Total entries | ~518 software records |
| Key field | `publiccodeYml` — embedded YAML string containing project metadata |
| Entry metadata | Name, description, URLs, development status, license, software type |

Each software entry contains an embedded `publiccodeYml` field (a [publiccode.yml](https://publiccode.yml/) document as a string) that holds structured metadata about the project, including repository URLs.

---

## 3. Ingestion Process

The ingestion pipeline fetches catalogue data and normalises it into the local database. The process is idempotent — re-running it produces the same result.

1. **Fetch all software entries.** The pipeline iterates through the Developers Italia API using cursor-based pagination until no further results are returned.

2. **Parse the embedded publiccode.yml.** Each entry's `publiccodeYml` string field is parsed with `yaml.safe_load()`. Parsing is defensive: failures never raise exceptions. Instead, a quality flag is stored indicating parse failure, and ingestion continues with whatever metadata is available from the top-level API fields.

3. **Extract repository URLs.** The pipeline reads the `url` and `landingURL` fields from the parsed publiccode.yml document. These point to the project's source code repository.

4. **Canonicalise URLs.** Before storage, all URLs are normalised:
   - Strip `.git` suffix
   - Strip trailing slashes
   - Force `https://` scheme
   - Lowercase the hostname

5. **Classify the host.** Each URL is categorised by inspecting the hostname:
   - `github` — hostname contains `github.com`
   - `gitlab` — hostname contains `gitlab`
   - `unsupported` — any other host

6. **Extract the owner/repo slug.** For GitHub URLs, the path segment is parsed into an `owner/repo` pair (e.g., `italia/design-kit`).

7. **Upsert into PostgreSQL.** Records are written using `INSERT ... ON CONFLICT DO UPDATE`, making the ingestion step idempotent. Re-running the pipeline updates existing entries rather than duplicating them.

---

## 4. Repository Enrichment

After ingestion, the pipeline enriches GitHub-hosted repositories with live metrics from the GitHub REST API. **Only GitHub repositories are enriched in the current MVP.** GitLab and other hosts are skipped and classified as `Unknown`.

### Authentication

All GitHub API requests use an authenticated token (`GITHUB_TOKEN`) to increase rate limits and access repository metadata.

### Metrics Collected

For each GitHub repository, the following metrics are fetched and stored:

| Metric | Source |
|---|---|
| Stars | Repository endpoint |
| Forks | Repository endpoint |
| Open issues count | Repository endpoint |
| Archived flag | Repository endpoint |
| Default branch name | Repository endpoint |
| Latest push date | Repository endpoint |
| Latest commit date | Commits endpoint (default branch) |
| Latest release date | Releases endpoint |
| License key (SPDX) | Repository endpoint |
| Topics | Repository endpoint (stored as JSON array text) |

### Error Handling

| Condition | Response |
|---|---|
| **404 Not Found** | Store `api_status: "not_found"` |
| **429 Rate Limited** | Exponential backoff with jitter; retry up to 3 times |
| **5xx Server Error** | Retry with backoff |
| **Timeout** | Store `api_status: "error"` |

### Storage

Enrichment results are written to the `repository_metrics_snapshots` table as **append-only** records. Each pipeline run creates one snapshot row per repository. Historical snapshots are never overwritten or deleted.

### Batch Checkpointing

Progress is saved periodically (every N repositories) so that a failed run can resume without re-fetching already-enriched repositories.

---

## 5. Status Classification Rules

Each project is assigned exactly one status label based on deterministic rules. Labels are applied in **priority order** — the first matching rule wins.

| Priority | Label | Rule |
|---|---|---|
| 1 (highest) | **Archived** | GitHub `archived` flag is `true` |
| 2 | **Data error** | Supported host (GitHub) but the API returned an error (404, timeout, etc.) |
| 3 | **Unknown** | Unsupported host (GitLab, self-hosted), no repository URL, or cannot otherwise classify |
| 4 | **Active** | Latest commit is within **90 days** of the pipeline run |
| 5 | **Slow** | Latest commit is between **91 and 365 days** ago |
| 6 (lowest) | **Stale** | Latest commit is more than **365 days** ago |

### Multi-Repository Projects

When a software entry has multiple repositories, the **worst status wins** — that is, the label with the highest priority number across all repositories is assigned to the project.

**Example:** A project with one `Active` repository and one `Stale` repository receives the `Stale` label.

### Thresholds

The 90-day and 365-day thresholds are intentionally simple and documented here for transparency. They are arbitrary but provide a consistent, reproducible basis for classification.

---

## 6. Data Quality Handling

The pipeline accounts for various data quality issues without failing:

| Condition | Classification | Reason stored |
|---|---|---|
| No repository URL in the catalogue entry | `Unknown` | `no_repository_url` |
| Repository on an unsupported host (GitLab, self-hosted, etc.) | `Unknown` | `unsupported_host_mvp` |
| Invalid or malformed URL | `Unknown` | `invalid_url` |
| GitHub API returns an error (404, timeout, etc.) | `Data error` | HTTP status or error description |
| Invalid YAML in publiccode.yml | Ingestion continues | Quality flag stored on the record |

In all cases, the pipeline logs the issue and continues processing. No single bad record can halt the pipeline.

---

## 7. Known Limitations

- **GitHub-only enrichment.** Repositories hosted on GitLab, Bitbucket, or self-hosted instances are not enriched and are classified as `Unknown`. GitLab support is a planned future improvement.
- **Single catalogue source.** The MVP ingests data only from Developers Italia. Additional EU public-sector catalogues may be added later.
- **No vulnerability or security scanning.** This project does not scan dependencies, check for known CVEs, or assess security posture in any way.
- **No composite health score.** Status labels are deliberately simple. There is no weighted index, letter grade, or numerical score combining multiple metrics.
- **URL host classification relies on parsed hostnames.** URLs are parsed with `urlparse().hostname` and matched against known hosts (e.g., `github.com`). Subdomains of known hosts (like `github.mycompany.com`) are not matched, but entirely unknown hosting platforms are.
- **Threshold dates are arbitrary.** The 90-day and 365-day boundaries are documented choices, not derived from statistical analysis.
- **Rate limits may cause partial runs.** On large pipeline runs, GitHub API rate limits may cause some repositories to remain un-enriched. The checkpointing mechanism mitigates this.
- **Dashboard deduplication.** The Streamlit dashboard may select a different "primary" repository for display than the API's default, potentially showing slightly different metrics for multi-repository projects.

---

## 8. Reproducibility

The pipeline is designed to produce consistent, reproducible results:

- **Deterministic classification.** Given the same input data and the same `observed_at` timestamp, the pipeline will assign identical status labels.
- **Public data sources.** All input comes from public APIs (Developers Italia, GitHub). No proprietary or restricted data is used.
- **Containerised environment.** Docker Compose provides an identical runtime environment across machines.
- **Versioned schema.** Alembic migrations track all database schema changes. The schema version is recorded alongside the data.
- **Pipeline run tracking.** Every pipeline execution creates a record in the `pipeline_runs` table, logging start time, end time, counts, and outcomes.

---

## 9. What This Project Does NOT Measure

This section is intentionally explicit. EU PubliCodeHealth measures **repository activity** — nothing more. The following are explicitly outside scope:

- **Software quality** — fitness for purpose, correctness, reliability
- **Code quality** — style, complexity, test coverage, documentation quality
- **Security vulnerabilities** — known CVEs, dependency vulnerabilities, insecure patterns
- **Dependency health** — outdated or abandoned transitive dependencies
- **License compliance** — compatibility with procurement rules or other licences
- **Community health** — beyond basic GitHub metrics (stars, forks), the project does not assess contributor diversity, governance, or sustainability
- **Suitability for procurement** — a project labelled `Active` is not endorsed or recommended for use

These limitations are by design. Repository activity is a narrow, factual signal. Consumers of this data should not infer broader quality judgements from the status labels alone.
