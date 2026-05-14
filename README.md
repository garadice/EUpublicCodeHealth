# EU PubliCodeHealth

MVP data product to monitor repository activity health of OSS projects from EU/public-sector catalogues.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

App: http://localhost:8000

## Run pipeline manually

```bash
docker compose exec app python -m pipelines.run_pipeline
```

## Endpoints
- `/health` - health check
- `/summary` - latest status counts
- `/projects.csv` - latest project export as CSV

## Configuration
- `SOURCE_CATALOG_URL`: single publiccode.yml URL fallback.
- `SOURCE_CATALOG_URLS`: JSON array for multi-source ingestion.
  Example:
  ```json
  [
    {"id":"source1","name":"Source One","url":"https://.../publiccode.yml"},
    {"id":"source2","name":"Source Two","url":"https://.../publiccode.yml"}
  ]
  ```

## Notes
- MVP is GitHub-only enrichment.
- Daily scheduling is configured via `scheduler` service in Docker Compose.
