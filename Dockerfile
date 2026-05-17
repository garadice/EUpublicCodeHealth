FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specification first for layer cache
COPY pyproject.toml .

# Copy application source (needed by pip install .)
COPY app/ app/
COPY connectors/ connectors/
COPY pipelines/ pipelines/
COPY dashboard/ dashboard/
COPY deploy/ deploy/

# Copy Alembic config (migrations are inside app/db/migrations, already copied)
COPY alembic.ini .

# Install package with runtime dependencies only (no dev tools)
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser

# Expose ports for API and dashboard
EXPOSE 8000 8501

# Default: start FastAPI
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
