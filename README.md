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

## Notes
- MVP is GitHub-only enrichment.
- Daily scheduling is configured via `scheduler` service in Docker Compose.
