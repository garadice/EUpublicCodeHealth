# Deployment Guide

This guide covers deploying EU PubliCodeHealth locally with Docker Compose and outlines steps for a future production deployment.

## 1. Prerequisites

- **Docker Engine 24+** with the Docker Compose plugin (`docker compose version`)
- **GitHub Personal Access Token** with `public_repo` scope ([create one here](https://github.com/settings/tokens))
- **Git**
- **2 GB RAM** minimum (4 GB recommended)
- **10 GB disk** free

## 2. Quick Start (Local Development)

```bash
git clone <repo-url>
cd EUcheck
cp .env.example .env
# Edit .env and add your GITHUB_TOKEN
docker compose up --build -d
# The API container auto-runs alembic migrations on startup.
# Wait ~30 seconds for all services to report healthy.
docker compose exec api python -m pipelines.run_all
```

Access the services:

| Service | URL |
|---|---|
| API health check | http://localhost:8000/health |
| API docs (Swagger) | http://localhost:8000/docs |
| Streamlit dashboard | http://localhost:8501 |

## 3. Environment Variables

Copy `.env.example` to `.env` and fill in the values. All configuration is loaded through pydantic-settings — never hardcode secrets.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql+psycopg://eupublicode:eupublicode@db:5432/eupublicode` | SQLAlchemy connection string |
| `GITHUB_TOKEN` | Yes | *(empty)* | GitHub PAT for API enrichment |
| `POSTGRES_DB` | Docker only | `eupublicode` | PostgreSQL database name |
| `POSTGRES_USER` | Docker only | `eupublicode` | PostgreSQL user |
| `POSTGRES_PASSWORD` | Docker only | `eupublicode` | PostgreSQL password |
| `SOURCE_CATALOG_URLS` | No | `[]` | JSON array of additional catalogue source configs |
| `INGEST_INTERVAL_SECONDS` | No | `86400` | Scheduler pipeline run interval (seconds) |
| `DEBUG` | No | `false` | Enable debug logging |

> **Note:** Inside Docker, `DATABASE_URL` uses the service name `db` as the host. When connecting from the host machine (e.g. with `psql`), use `localhost` and port `5434`.

## 4. Docker Services

The stack consists of four services defined in `docker-compose.yml`:

### db (PostgreSQL 16)

- Persistent data via a Docker volume (`pgdata`)
- Health check: `pg_isready` every 5 seconds
- Bound to `127.0.0.1:5434:5432` (localhost only, port 5434 to avoid conflicts with local PostgreSQL)

### api (FastAPI)

- Serves the REST API on port **8000**
- Entrypoint auto-runs `alembic upgrade head` before starting Uvicorn
- Health check: `GET /health` every 30 seconds (timeout: 10s, retries: 3)
- `restart: unless-stopped`

### dashboard (Streamlit)

- Runs the Streamlit dashboard on port **8501**
- Depends on the database being healthy (reads directly from PostgreSQL)
- `restart: unless-stopped`

### scheduler (Pipeline Runner)

- Runs `pipelines.run_all` on a configurable interval (`INGEST_INTERVAL_SECONDS`, default 24 hours)
- Waits for the API health endpoint before starting its loop
- Depends on the API service being healthy
- `restart: unless-stopped`

## 5. Running the Pipeline

**Automatic** — The scheduler service runs the pipeline on the interval set by `INGEST_INTERVAL_SECONDS`.

**Manual** — Trigger a one-off run at any time:

```bash
docker compose exec api python -m pipelines.run_all
```

The pipeline is idempotent: re-running it is safe and will refresh data without duplicating records.

## 6. Backup and Restore

```bash
# Create a compressed backup
docker compose exec db pg_dump -U eupublicode eupublicode | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore from a backup
gunzip -c backup_20250101.sql.gz | docker compose exec -T db psql -U eupublicode eupublicode
```

## 7. Monitoring

| What | How |
|---|---|
| API + DB health | `GET http://localhost:8000/health` — returns JSON with status of API and database connection |
| Pipeline runs | `GET http://localhost:8000/api/runs` — lists recent runs with timestamps, status, and error counts |
| Dashboard status | The Streamlit dashboard shows the latest pipeline run timestamp on the overview page |
| Container logs | `docker compose logs -f <service>` — tail logs for any service |

## 8. Troubleshooting

### "Port 5434 already in use"

Another PostgreSQL instance is listening on that port. Either stop it or change the host-side port mapping in `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:5434:5432"   # use 5434 instead
```

### "API health check fails"

Check the API container logs for the error:

```bash
docker compose logs api
```

The most common cause is the database not being ready yet. Wait a few seconds and the health check will retry.

### "GitHub rate limited"

Verify `GITHUB_TOKEN` is set in `.env`. Without a token the anonymous rate limit is 60 requests/hour; with a token it is 5,000/hour.

### "Alembic migration fails"

Confirm that `DATABASE_URL` inside the container matches the `POSTGRES_*` variables. Check the current migration state:

```bash
docker compose exec api alembic current
```

If the database is in a bad state, you can re-create it:

```bash
docker compose down -v   # WARNING: deletes the database volume
docker compose up -d
```

### "Dashboard shows no data"

Run the pipeline first:

```bash
docker compose exec api python -m pipelines.run_all
```

Then refresh the dashboard.

## 9. Production Deployment (Future: Hetzner VPS)

This is an outline for a future production deployment.

1. **Provision a VPS** — Ubuntu LTS with at least 2 GB RAM (Hetzner CX22 or equivalent).
2. **Firewall** — Allow SSH (22), HTTP (80), and HTTPS (443) only. Block direct access to PostgreSQL (5432/5434) and internal ports.
3. **Install Docker** — Follow the [official Docker docs](https://docs.docker.com/engine/install/ubuntu/) for Ubuntu.
4. **Clone and configure**:

   ```bash
   git clone <repo-url> /opt/eucheck
   cd /opt/eucheck
   cp .env.example .env
   # Set strong production values for POSTGRES_PASSWORD, GITHUB_TOKEN, etc.
   ```

5. **Start services**:

   ```bash
   docker compose up -d
   ```

6. **Reverse proxy (optional)** — Add [Caddy](https://caddyserver.com/) for automatic HTTPS:

   ```Caddyfile
   eucheck.example.com {
       reverse_proxy api:8000
   }
   dashboard.eucheck.example.com {
       reverse_proxy dashboard:8501
   }
   ```

7. **Automated backups** — Add a cron job:

   ```cron
   0 3 * * * docker compose -f /opt/eucheck/docker-compose.yml exec -T db pg_dump -U eupublicode eupublicode | gzip > /opt/eucheck/backups/backup_$(date +\%Y\%m\%d).sql.gz
   ```

8. **Uptime monitoring (optional)** — Point [UptimeRobot](https://uptimerobot.com/) or similar at `https://eucheck.example.com/health` for alerts on downtime.
