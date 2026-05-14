from fastapi import FastAPI
from sqlalchemy import text
from app.db import engine

app = FastAPI(title="EU PubliCodeHealth")


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/")
def home():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.name, COALESCE(ps.status_label, 'Unknown') as status
            FROM projects p
            LEFT JOIN LATERAL (
              SELECT status_label
              FROM project_status_snapshots s
              WHERE s.project_id = p.project_id
              ORDER BY observed_at DESC
              LIMIT 1
            ) ps ON TRUE
            ORDER BY p.name
            LIMIT 100
        """)).mappings().all()
    return {
        "project": "EU PubliCodeHealth",
        "count": len(rows),
        "projects": list(rows),
    }
