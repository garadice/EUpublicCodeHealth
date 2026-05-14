# EU PubliCodeHealth

MVP data product to monitor repository activity health of OSS projects from EU/public-sector catalogues.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

App: http://localhost:8000

## Initialize DB schema manually (if needed)

```bash
docker compose exec app python -m pipelines.init_db
```

## Run pipeline manually

```bash
docker compose exec app python -m pipelines.run_pipeline
```

## Endpoints
- `/health` - health check
- `/summary` - latest status counts
- `/projects.csv` - latest project export as CSV
- `/dashboard` - lightweight HTML dashboard
- `/runs` - recent ingestion run history

## Configuration
- `SOURCE_CATALOG_URL`: single source URL fallback (`.yml`, `.yaml`, or `.json`).
- `SOURCE_CATALOG_URLS`: JSON array for multi-source ingestion.
- Source payload formats currently supported:
  1. single-object publiccode-like YAML/JSON
  2. JSON/YAML object with `projects: []`
  3. JSON/YAML list of project objects

## Notes
- MVP is GitHub-only enrichment.
- Daily scheduling is configured via `scheduler` service in Docker Compose.
