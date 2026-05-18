# EU PubliCodeHealth

> A reproducible data pipeline monitoring repository activity of open-source software listed in EU public-sector catalogues.

![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![Streamlit](https://img.shields.io/badge/Streamlit-1.57-FF4B4B)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![License](https://img.shields.io/badge/License-MIT-yellow)

## What It Does / Doesn't Do

**Measures** — Repository activity: commit frequency, archival status, stars, forks, and basic GitHub engagement metrics. Classifies ~518 open-source projects from Developers Italia into six deterministic status labels.

**Does NOT measure** — Code quality, security vulnerabilities, dependency health, license compliance, or any form of software assessment. This is an activity monitor, not a quality gate.

## Screenshots

<table>
  <tr>
    <td><b>Streamlit Dashboard</b></td>
    <td><b>FastAPI Interactive Docs</b></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/dashboard_overview.png" alt="Dashboard overview with KPI cards, status chart, and project table" width="480"/></td>
    <td><img src="docs/screenshots/api_docs.png" alt="Swagger UI with all API endpoints" width="480"/></td>
  </tr>
</table>

The dashboard shows KPI cards (total projects, active %, stale %, unknown/errors %), an interactive status distribution chart, a searchable/filterable project table with CSV export, data quality metrics, and pipeline run information.

## Architecture

```mermaid
flowchart LR
    DI[Developers Italia API] -->|~518 entries| INGEST[Ingestion Pipeline]
    INGEST --> PG[(PostgreSQL)]
    PG --> API[FastAPI API]
    PG --> DASH[Streamlit Dashboard]
    INGEST -->|GitHub repos| ENRICH[Enrichment Pipeline]
    ENRICH -->|REST API| GH[GitHub REST API]
    ENRICH --> CLASS[Status Classification]
    CLASS --> PG
    API -->|"/api/projects"| CONSUMER[API Consumer]
    API -->|"/api/summary"| CONSUMER
    API -->|"/exports/projects.csv"| CONSUMER
```

## Data Pipeline Flow

```mermaid
flowchart TD
    A[1. Fetch catalogue entries<br/>cursor pagination] --> B[2. Parse publiccode.yml<br/>defensive YAML parsing]
    B --> C[3. Normalize URLs & classify hosts<br/>GitHub / GitLab / unsupported]
    C --> D{Supported host?}
    D -->|Yes - GitHub| E[4. Enrich via GitHub REST API<br/>stars, forks, commits, archived]
    D -->|No| F[Mark as Unknown]
    E --> G[5. Classify status<br/>6 labels, deterministic rules]
    F --> G
    G --> H[6. Store append-only snapshots]
    H --> I[7. Serve via API + Dashboard]
```

## Quick Start

```bash
cp .env.example .env            # Set GITHUB_TOKEN
docker compose up --build       # Starts PostgreSQL + API + Dashboard + Scheduler
# API auto-runs Alembic migrations on startup
docker compose exec api python -m pipelines.run_all   # Run the pipeline
```

| Service | URL |
|---|---|
| API health check | http://localhost:8000/health |
| Interactive docs | http://localhost:8000/docs |
| Dashboard (Docker) | http://localhost:8502 |
| Dashboard (local dev) | http://localhost:8501 |

## Status Labels

| Label | Rule | Color |
|---|---|---|
| Active | Latest commit within 90 days | 🟢 Green |
| Slow | Latest commit 91–365 days ago | 🟡 Yellow |
| Stale | Latest commit >365 days ago | 🔴 Red |
| Archived | GitHub `archived` flag is true | ⚪ Gray |
| Unknown | Unsupported host or no repo URL | 🟣 Purple |
| Data error | API error from supported host | 🩷 Pink |

Labels are assigned by priority: Archived > Data error > Unknown > Active > Slow > Stale.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check + DB connectivity |
| `GET /api/projects` | Project list (filter by status, host, search) |
| `GET /api/summary` | Status distribution counts + totals |
| `GET /exports/projects.csv` | Download CSV export |
| `GET /api/runs` | Pipeline run history |

All endpoints except `/health` require an `X-API-Key` header when `API_KEY` is set in the environment. See [deployment guide](docs/deployment.md) for details.

## Data Model

```mermaid
erDiagram
    catalog_sources ||--o{ projects : "contains"
    projects ||--o{ repositories : "has"
    repositories ||--o{ repository_metrics_snapshots : "tracked by"
    projects ||--o{ project_status_snapshots : "classified in"
    pipeline_runs ||--o{ repository_metrics_snapshots : "produces"
    pipeline_runs ||--o{ project_status_snapshots : "produces"

    catalog_sources {
        string source_id PK
        string name
        string country
        string base_url
        boolean active
    }

    projects {
        string id PK
        string source_id FK
        string name
        string description
        string license
        string source_url
    }

    repositories {
        string id PK
        string project_id FK
        string canonical_url
        string host
        boolean is_supported
    }

    repository_metrics_snapshots {
        bigint id PK
        string repository_id FK
        int run_id FK
        int stars
        int forks
        boolean archived
        datetime latest_commit_at
    }

    project_status_snapshots {
        bigint id PK
        string project_id FK
        string repository_id FK
        int run_id FK
        string status_label
        string reason
    }

    pipeline_runs {
        bigint id PK
        datetime started_at
        string status
        int records_seen
        int errors_count
    }
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| API | FastAPI + Uvicorn |
| Database | PostgreSQL 16 via SQLAlchemy 2.0 + Alembic |
| Dashboard | Streamlit + Altair |
| HTTP | httpx (async) |
| Config | pydantic-settings |
| Testing | pytest + pytest-cov + pytest-httpx |
| Linting | ruff (lint + format) |
| Type checking | mypy (strict) |
| Deployment | Docker Compose |

## Project Structure

```
app/
  api/          FastAPI routes, schemas, query builders
  core/         Config, status logic, URL normalization, sanitize, logging
  db/           SQLAlchemy models, session, Alembic migrations
connectors/     External API clients (Developers Italia, GitHub)
pipelines/      ETL steps (ingest, enrich, classify, orchestrate)
dashboard/      Streamlit dashboard
tests/          Unit + integration tests with fixtures
docs/           Methodology, data dictionary, deployment guide
```

## Testing

```bash
make test              # Full suite with coverage
make lint              # ruff check
make typecheck         # mypy strict
make check             # All of the above
```

## Key Engineering Decisions

**Simple labels, not composite scores.** A single "health score" would hide important nuances. Archived, Active, and Unknown are fundamentally different situations that deserve separate visibility. Composite scores also invite ranking comparisons that the underlying data doesn't support.

**GitHub-only enrichment for now.** GitLab has diverse self-hosted instances with different API versions — some running 14.x, some on 17.x, each with their own authentication setup. Shipping GitHub support first delivers value faster and avoids false promises about coverage.

**Append-only snapshots.** Historical data is never overwritten. Every pipeline run adds new snapshots. This seemed like extra work upfront but paid off quickly — the pipeline can be re-run safely, results are auditable, and trend analysis becomes possible without any extra design work.

**Developers Italia as sole source.** Starting with one well-documented public API avoids the complexity of multiple catalogue formats and lets the pipeline be reliable before expanding.

**No vulnerability scanning.** Catalogue metadata rarely includes exact package versions or SBOMs. Running OSV on incomplete data would produce misleading results that could be misinterpreted as security assessments.

## Documentation

- [Methodology](docs/methodology.md) — Data sources, classification rules, known limitations
- [Data Dictionary](docs/data_dictionary.md) — Every table and column explained
- [Deployment Guide](docs/deployment.md) — Docker setup and production deployment

## Development

```bash
pip install -e ".[dev]"    # Install with dev dependencies
make run                   # FastAPI on :8000
make dashboard             # Streamlit on :8501
make pipeline              # Run ingestion pipeline
make init-db               # Run Alembic migrations
```

## License

MIT
