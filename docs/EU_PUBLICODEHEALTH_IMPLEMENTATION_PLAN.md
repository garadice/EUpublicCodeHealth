# EU PubliCodeHealth — Implementation Plan

## 1. Executive Summary
EU PubliCodeHealth is a public data product that monitors technical activity health of open-source software listed in EU/public-sector catalogues, then publishes transparent status labels (Active/Slow/Stale/Archived/Unknown) with downloadable data.

**Recommendation:** Build it, but with strict MVP scope. This is portfolio-strong for data analyst/engineer roles because it demonstrates ingestion, normalization, API enrichment, data modeling, QA, and deployment.

**Recommended MVP:**
- 1–2 catalogue sources
- GitHub-only enrichment
- 24h data refresh cadence
- Dashboard + CSV export first
- Optional OpenSSF Scorecard if easy to integrate
- No OSV vulnerability claims in MVP

## 2. Research Findings
| Source | What it provides | Access method | Useful for MVP? | Risks / limitations |
|---|---|---|---|---|
| EU OSS Catalogue (Interoperable Europe) | Federated OSS catalogue context, onboarding references | Web pages and linked resources | Yes | Machine-readable access details can be fragmented |
| publiccode.yml standard | Metadata standard fields for software listings | GitHub + docs | Yes | Real-world files may be incomplete/inconsistent |
| code.gouv.fr / catalogi | French public-sector software listing ecosystem | Public website + GitHub repos | Yes | Extraction method may vary by component |
| Developers Italia | Publiccode-based publication model and software catalogue ecosystem | Official docs/API references | Yes | Endpoint/version stability must be validated during build |
| Open CoDE Germany | Publiccode.yml usage for software directory submission | Public docs + GitLab ecosystem | Yes (future expansion) | GitLab integration increases complexity |
| GitHub REST API | Repo activity + metadata (archived, commits, releases, etc.) | Official REST API | Yes (core) | Rate limits and intermittent API failures |
| GitLab API | Public project metadata endpoints | REST API | V2 | Instance-specific behavior/auth differences |
| OpenSSF Scorecard | Security posture signals + API/BigQuery options | scorecard.dev + OSSF repo | Optional | Not equivalent to full security assessment |
| OSV | Vulnerability records and API querying methods | osv.dev API | V2+ | Risky without reliable package/version dependency context |

Source links:
- https://interoperable-europe.ec.europa.eu/eu-oss-catalogue/about
- https://github.com/publiccodeyml/publiccode.yml
- https://developers.italia.it
- https://code.gouv.fr
- https://guide.opencode.de/en/softwareverzeichnis/publiccode.yml-anlegen/
- https://docs.github.com/en/rest
- https://docs.gitlab.com/api/projects/
- https://scorecard.dev
- https://github.com/ossf/scorecard
- https://osv.dev
- https://google.github.io/osv.dev/api/

## 3. Existing Similar Projects
| Existing project/tool | What it does | Similarity | Difference | Risk of duplication |
|---|---|---|---|---|
| EU OSS Catalogue | Project discovery/listing | High | PubliCodeHealth adds technical health layer + status snapshots | Medium |
| Developers Italia catalogue | National OSS listing and metadata ingestion | Medium | PubliCodeHealth adds cross-source normalization and activity labels | Medium |
| Open CoDE software directory | National catalogue workflow | Medium | PubliCodeHealth focuses on comparable health analytics | Medium |
| OpenSSF Scorecard | Security process checks | Partial | PubliCodeHealth focuses on activity/vitality + transparent caveats | Low |

## 4. Final Product Definition
- **Product is:** a transparent, reproducible OSS catalogue health monitor.
- **Product is not:** a full security scanner or legal/compliance certification tool.
- **Primary audience (MVP):** hiring managers/recruiters evaluating portfolio quality.
- **Secondary audience:** public-sector OSS observers and analysts.
- **Problem solved:** “Which public-sector OSS projects are currently active vs stale?”

## 5. User Perspective
1. **Public-sector IT manager**: filters projects by status before evaluation.
2. **Policy analyst**: tracks stale/active share over time.
3. **Integrator/vendor**: screens maintenance activity signals.
4. **Researcher/journalist**: uses open CSV + documented methodology.
5. **Recruiter/hiring manager**: sees end-to-end data engineering capability.

## 6. Developer Perspective
Pipeline steps:
1. Collect catalogue data.
2. Parse and normalize project metadata.
3. Extract repository URLs.
4. Classify repository host.
5. Fetch repository metrics (GitHub MVP).
6. Fetch OpenSSF Scorecard where possible.
7. Keep OSV-ready extension points for later.
8. Store clean data in Postgres.
9. Compute status labels.
10. Build dashboard views.
11. Export CSV (API optional in late MVP).
12. Publish methodology and caveats.

For each step, implement input/output contracts, failure handling, and tests.

## 7. Data Model
Minimum tables:
- `catalog_sources`
- `projects`
- `repositories`
- `repository_metrics_snapshots`
- `scorecard_snapshots`
- `project_status_snapshots`
- `pipeline_runs`

Each table should include created/updated timestamps, source lineage keys, and appropriate indexes for joins and latest-snapshot queries.

## 8. MVP Scope
### Included
- 1–2 catalogue sources
- GitHub-only enrichment
- status labels instead of composite health score
- dashboard + CSV export
- automated daily data refresh

### Excluded
- GitLab integration
- OSV vulnerability reporting
- heavy compute/security scanning
- complex user auth/roles

### Why exclusions matter
Keeps MVP reliable, cheap, and deployable by one person.

## 9. Version 2 Scope
- Add GitLab support
- Add more EU catalogues
- Improve Scorecard coverage handling
- Add historical trend analytics
- Add lightweight public API
- Add stronger dedup/entity matching

## 10. Full Feature Vision
- Multi-country federation and comparisons
- Monthly reports and alerts
- Optional OSV integration where dependency data quality is sufficient
- Downloadable Parquet snapshots
- Methodology microsite + API documentation

## 11. Architecture
Recommended:
- Python + FastAPI
- PostgreSQL
- ETL scripts (Python)
- Docker Compose
- Host Nginx reverse proxy (shared with other projects)
- Cron scheduling (24h data run)
- Basic monitoring (health endpoint + logs)

Avoid overengineering (no Spark/Kafka/Airflow/K8s for MVP).

## 12. Data Quality Strategy
Handle:
- missing/dead repo URLs
- duplicates and renamed repos
- API rate limits and retries
- stale source metadata
- inconsistent license strings
- unknown status outputs

Validation:
- allowed status enum only
- lineage required for every record
- run-level QA report generated on each pipeline execution

## 13. Scoring / Status Logic
Use labels:
- **Active:** commit/push within 90 days
- **Slow:** 91–365 days
- **Stale:** >365 days
- **Archived:** archived flag true
- **Unknown:** no reliable repo check
- **Data error:** parsing/enrichment failure

This is safer and more explainable than a single opaque score.

## 14. Risk Register
| Risk | Severity | Probability | Why it matters | Mitigation |
|---|---|---|---|---|
| Source inaccessible | High | Medium | no ingestion | choose stable source first + fallback |
| API/rate limits | Medium | Medium | incomplete updates | token auth + retries + 24h cadence |
| publiccode inconsistencies | Medium | High | missing fields | nullable schema + quality flags |
| Misread “health” claims | High | Medium | trust risk | strong methodology caveats |
| Scorecard misuse | Medium | Medium | false security impression | present as supplementary signal |
| Too similar to existing catalogues | Medium | Medium | weak differentiation | emphasize cross-source health layer |
| Maintenance burden | Medium | Medium | project decay | keep architecture minimal |

## 15. Blocker Analysis
### Hard blockers
- no reliable machine-readable source access
- no mappable repository URLs

### Soft blockers
- sparse/inconsistent metadata
- temporary API failures
- duplicate identities across catalogues

### Non-blockers
- OSV integration
- GitLab support
- advanced scoring system

## 16. Implementation Phases
0. Research validation
1. Local prototype with one catalogue
2. GitHub enrichment
3. DB schema + ingestion
4. Status classification
5. Dashboard
6. CSV + methodology
7. VPS deployment
8. Automation/monitoring
9. Add second catalogue
10. API
11. Scorecard
12. V2 expansion

Each phase should define acceptance criteria and rollback-safe checkpoints.

## 17. Suggested Repository Structure
```text
eu-publicode-health/
  app/
  pipelines/
  connectors/
  db/
  dashboard/
  docs/
  tests/
  data_samples/
  deploy/
  docker-compose.yml
  README.md
```

## 18. Testing Plan
- Unit tests for parsers/rules
- Fixture tests for sample source payloads
- Integration tests for DB upsert paths
- API tests for response schemas
- Dashboard smoke tests
- Pipeline failure-path tests (rate limit, missing fields)

## 19. Deployment Plan
Hetzner VPS with shared host Nginx:
- deploy via Docker Compose project name `eupublicodehealth`
- internal app port (e.g., 8000), proxied by host Nginx
- Postgres in dedicated container + named volume
- cron-driven daily ingestion
- backups (nightly DB dump)
- logs + health endpoint monitoring

**Prompt template for your server-admin LLM before final deployment:**
1. “List active Nginx server blocks and upstreams for bacimo.net subdomains.”
2. “Reserve new vhost for eupubliccodehealth.bacimo.net and map to Docker service on internal port 8000.”
3. “Confirm no port conflicts with existing containers.”
4. “Set TLS via Let’s Encrypt and HTTP→HTTPS redirect.”
5. “Set restart policies and log rotation for new compose stack.”

## 20. Portfolio Presentation Plan
Include:
- clear README story
- architecture + pipeline diagrams
- methodology + limitations
- live demo link
- downloadable dataset links
- lessons learned + future roadmap

## 21. First 7 Days Plan
- Day 1: source verification + contracts
- Day 2: project scaffold + Docker baseline
- Day 3: first collector
- Day 4: normalization + DB schema
- Day 5: GitHub enrichment
- Day 6: status labels + CSV export
- Day 7: basic dashboard + docs

## 22. First 30 Days Plan
- Week 1: ingest + normalize
- Week 2: enrich + classify + QA
- Week 3: dashboard + exports + docs
- Week 4: deploy + automate + polish for portfolio

## 23. Go / No-Go Decision
**GO (build) with reduced scope.**
This is a realistic, recruiter-friendly project if implemented as a reliable small product with strong transparency and documentation.

## 24. Open Questions
- Which exact catalogue endpoints are stable enough for daily automation?
- Do we include Scorecard in MVP or enable behind feature flag?
- CSV only for MVP or CSV + Parquet?
- How much snapshot history to keep by default?
- Which KPI cards matter most for recruiter-facing demo?

---

## Product Positioning Note
To increase differentiation vs competitors while staying lightweight:
- Focus on **cross-catalogue comparability**, **transparent methodology**, and **time-based trend snapshots**.
- Add low-compute features later: curated tags, change summaries, alerting, and country/source comparison views.
