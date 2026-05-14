from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from app.db import engine

app = FastAPI(title="EU PubliCodeHealth")


def _latest_projects(limit: int = 100):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT p.project_id, p.name, p.repo_url_raw,
                   COALESCE(ps.status_label, 'Unknown') as status_label,
                   COALESCE(ps.status_reason, '') as status_reason
            FROM projects p
            LEFT JOIN LATERAL (
              SELECT status_label, status_reason
              FROM project_status_snapshots s
              WHERE s.project_id = p.project_id
              ORDER BY observed_at DESC
              LIMIT 1
            ) ps ON TRUE
            ORDER BY p.name
            LIMIT :limit
        """), {"limit": limit}).mappings().all()


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/runs")
def runs(limit: int = 20):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT run_id, started_at, ended_at, status, COALESCE(error_summary,'') as error_summary
            FROM pipeline_runs
            ORDER BY run_id DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return {"runs": list(rows)}


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
    rows = _latest_projects(limit=5000)
    headers = ["project_id", "name", "repo_url_raw", "status_label", "status_reason"]
    lines = [",".join(headers)]
    for r in rows:
        vals = [str((r.get(h) or "")).replace('"', '""') for h in headers]
        lines.append(",".join(f'"{v}"' for v in vals))
    return Response(content="\n".join(lines), media_type="text/csv")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    rows = _latest_projects(limit=200)
    counts = {}
    for row in rows:
        counts[row["status_label"]] = counts.get(row["status_label"], 0) + 1

    cards = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in sorted(counts.items()))
    trs = "".join(
        f"<tr><td>{r['name']}</td><td>{r['status_label']}</td><td>{r['status_reason']}</td><td>{r['repo_url_raw'] or ''}</td></tr>"
        for r in rows
    )
    html = f"""
    <html><head><title>EU PubliCodeHealth Dashboard</title>
    <style>body{{font-family:Arial;margin:2rem}} table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:.4rem}}</style>
    </head><body>
      <h1>EU PubliCodeHealth</h1>
      <p>Latest status snapshot (first 200 projects).</p>
      <ul>{cards}</ul>
      <p><a href='/projects.csv'>Download CSV</a> | <a href='/summary'>JSON Summary</a> | <a href='/runs'>Pipeline Runs</a></p>
      <table><thead><tr><th>Project</th><th>Status</th><th>Reason</th><th>Repo URL</th></tr></thead><tbody>{trs}</tbody></table>
    </body></html>
    """
    return HTMLResponse(content=html)


@app.get("/")
def home():
    rows = _latest_projects(limit=100)
    return {
        "project": "EU PubliCodeHealth",
        "count": len(rows),
        "projects": list(rows),
        "endpoints": ["/health", "/summary", "/projects.csv", "/dashboard", "/runs"],
    }
