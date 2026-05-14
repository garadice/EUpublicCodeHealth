from fastapi import FastAPI, Response
from sqlalchemy import text
from app.db import engine

app = FastAPI(title="EU PubliCodeHealth")


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/summary")
def summary():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT COALESCE(status_label, 'Unknown') as status_label, COUNT(*) as cnt
            FROM (
              SELECT DISTINCT ON (project_id) project_id, status_label
              FROM project_status_snapshots
              ORDER BY project_id, observed_at DESC
            ) t
            GROUP BY status_label
            ORDER BY cnt DESC
        """)).mappings().all()
    return {"status_counts": list(rows)}


@app.get("/projects.csv")
def projects_csv():
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT p.project_id, p.name, p.repo_url_raw,
                   COALESCE(ps.status_label, 'Unknown') as status_label,
                   ps.status_reason
            FROM projects p
            LEFT JOIN LATERAL (
              SELECT status_label, status_reason
              FROM project_status_snapshots s
              WHERE s.project_id = p.project_id
              ORDER BY observed_at DESC
              LIMIT 1
            ) ps ON TRUE
            ORDER BY p.name
        """)).mappings().all()

    headers = ["project_id", "name", "repo_url_raw", "status_label", "status_reason"]
    lines = [",".join(headers)]
    for r in rows:
        vals = [str((r.get(h) or "")).replace('"', '""') for h in headers]
        lines.append(",".join(f'"{v}"' for v in vals))
    return Response(content="\n".join(lines), media_type="text/csv")


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
        "endpoints": ["/health", "/summary", "/projects.csv"],
    }
