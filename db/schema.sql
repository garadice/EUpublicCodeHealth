CREATE TABLE IF NOT EXISTS catalog_sources (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES catalog_sources(source_id),
  name TEXT NOT NULL,
  repo_url_raw TEXT,
  license TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS repositories (
  repository_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  host TEXT NOT NULL,
  owner TEXT,
  repo_name TEXT,
  repo_url_canonical TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS repository_metrics_snapshots (
  snapshot_id BIGSERIAL PRIMARY KEY,
  repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
  observed_at TIMESTAMPTZ DEFAULT NOW(),
  pushed_at TIMESTAMPTZ,
  archived BOOLEAN,
  stars INTEGER,
  forks INTEGER,
  open_issues INTEGER,
  default_branch TEXT
);

CREATE TABLE IF NOT EXISTS project_status_snapshots (
  status_snapshot_id BIGSERIAL PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id),
  repository_id TEXT NOT NULL REFERENCES repositories(repository_id),
  observed_at TIMESTAMPTZ DEFAULT NOW(),
  status_label TEXT NOT NULL,
  status_reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id BIGSERIAL PRIMARY KEY,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  status TEXT,
  error_summary TEXT
);
