from datetime import datetime, timezone
from sqlalchemy import text
from app.db import engine
from connectors.catalog_source import fetch_publiccode_project
from connectors.github_client import parse_github, fetch_repo


def classify(pushed_at, archived, has_repo):
    if archived:
        return "Archived", "Repository archived flag is true"
    if not has_repo or pushed_at is None:
        return "Unknown", "Repository missing or could not be queried"
    days = (datetime.now(timezone.utc) - pushed_at).days
    if days <= 90:
        return "Active", f"Last push {days} days ago"
    if days <= 365:
        return "Slow", f"Last push {days} days ago"
    return "Stale", f"Last push {days} days ago"


def run():
    with engine.begin() as conn:
        run_id = conn.execute(text("INSERT INTO pipeline_runs(status) VALUES ('running') RETURNING run_id")).scalar_one()
        try:
            p = fetch_publiccode_project()
            conn.execute(text("""
                INSERT INTO catalog_sources(source_id,name,url)
                VALUES (:sid,:name,:url)
                ON CONFLICT (source_id) DO UPDATE SET name=EXCLUDED.name,url=EXCLUDED.url
            """), {"sid": p["source_id"], "name": p["source_name"], "url": p["source_url"]})

            conn.execute(text("""
                INSERT INTO projects(project_id,source_id,name,repo_url_raw,license)
                VALUES (:pid,:sid,:name,:repo,:lic)
                ON CONFLICT (project_id) DO UPDATE SET name=EXCLUDED.name,repo_url_raw=EXCLUDED.repo_url_raw,license=EXCLUDED.license
            """), {"pid": p["project_id"], "sid": p["source_id"], "name": p["name"], "repo": p["repo_url"], "lic": p["license"]})

            owner, repo = parse_github(p.get("repo_url") or "")
            repo_id = f"github:{owner}/{repo}" if owner and repo else f"github:unknown:{p['project_id']}"
            conn.execute(text("""
                INSERT INTO repositories(repository_id,project_id,host,owner,repo_name,repo_url_canonical)
                VALUES (:rid,:pid,'github',:owner,:repo,:url)
                ON CONFLICT (repository_id) DO UPDATE SET owner=EXCLUDED.owner,repo_name=EXCLUDED.repo_name,repo_url_canonical=EXCLUDED.repo_url_canonical
            """), {"rid": repo_id, "pid": p["project_id"], "owner": owner, "repo": repo, "url": p.get("repo_url")})

            data = fetch_repo(owner, repo) if owner and repo else None
            pushed_at = None
            archived = None
            if data and data.get("pushed_at"):
                pushed_at = datetime.fromisoformat(data["pushed_at"].replace("Z", "+00:00"))
                archived = bool(data.get("archived", False))
            conn.execute(text("""
                INSERT INTO repository_metrics_snapshots(repository_id,pushed_at,archived,stars,forks,open_issues,default_branch)
                VALUES (:rid,:pushed,:arch,:stars,:forks,:issues,:branch)
            """), {
                "rid": repo_id,
                "pushed": pushed_at,
                "arch": archived,
                "stars": data.get("stargazers_count") if data else None,
                "forks": data.get("forks_count") if data else None,
                "issues": data.get("open_issues_count") if data else None,
                "branch": data.get("default_branch") if data else None,
            })

            status, reason = classify(pushed_at, archived, bool(data))
            conn.execute(text("""
                INSERT INTO project_status_snapshots(project_id,repository_id,status_label,status_reason)
                VALUES (:pid,:rid,:status,:reason)
            """), {"pid": p["project_id"], "rid": repo_id, "status": status, "reason": reason})

            conn.execute(text("UPDATE pipeline_runs SET status='success', ended_at=NOW() WHERE run_id=:id"), {"id": run_id})
        except Exception as exc:
            conn.execute(text("UPDATE pipeline_runs SET status='failed', ended_at=NOW(), error_summary=:e WHERE run_id=:id"), {"id": run_id, "e": str(exc)[:4000]})
            raise


if __name__ == "__main__":
    run()
