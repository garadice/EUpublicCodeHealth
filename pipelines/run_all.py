"""Pipeline orchestrator.

Runs the full ingestion pipeline:
1. Ingest catalogue data from Developers Italia
2. Enrich repositories with GitHub metrics
3. Classify project status based on metrics
4. Record pipeline run outcome

Usage:
    python -m pipelines.run_all
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.logging import get_logger
from app.core.sanitize import build_error_summary
from app.db.models import PipelineRun
from app.db.session import get_session_factory

logger = get_logger(__name__)


async def run_full_pipeline() -> None:
    """Run the complete pipeline end-to-end.

    Steps:
    1. Create a pipeline_run record (status="running")
    2. Ingest catalogue data and persist projects/repos
    3. Enrich GitHub repositories with metrics
    4. Classify project statuses
    5. Update pipeline_run with final counts

    Each step commits independently for resilience. On error:
    - Record the error in pipeline_run
    - Previous step data is preserved (already committed)
    - Re-raise for caller to handle
    """
    factory = get_session_factory()
    session = factory()

    run: PipelineRun | None = None

    try:
        # Step 0: Create pipeline run
        run = PipelineRun(
            source_name="full_pipeline",
            status="running",
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()
        logger.info("Pipeline run %d started", run_id)

        # Step 1: Ingest catalogue data
        from pipelines.ingest_catalog import persist_ingestion_results, run_ingestion

        ingest_result = await run_ingestion()
        persist_ingestion_results(session, ingest_result)
        session.commit()
        logger.info(
            "Ingestion complete: %d fetched, %d parsed ok",
            ingest_result.total_fetched,
            ingest_result.total_parsed_ok,
        )

        # Step 2: Enrich repositories
        from pipelines.enrich_repositories import enrich_repositories

        enrich_result = await enrich_repositories(session, run_id)
        session.commit()
        logger.info(
            "Enrichment complete: %d success, %d errors",
            enrich_result.success_count,
            enrich_result.error_count + enrich_result.not_found_count,
        )

        # Step 3: Classify statuses
        from pipelines.classify_status import classify_project_statuses

        classify_result = classify_project_statuses(session, run_id)
        session.commit()
        logger.info(
            "Classification complete: %d projects classified",
            classify_result.classified_count,
        )

        # Step 4: Update pipeline run with final counts
        total_records = ingest_result.total_fetched
        total_loaded = classify_result.classified_count
        all_errors = ingest_result.errors + enrich_result.errors
        has_errors = bool(all_errors) or enrich_result.error_count > 0

        run.records_seen = total_records
        run.records_loaded = total_loaded
        run.errors_count = len(all_errors)
        run.error_summary = build_error_summary(all_errors)
        run.status = "error" if has_errors else "success"
        run.finished_at = datetime.now(UTC)
        session.commit()

        logger.info(
            "Pipeline run %d complete: status=%s, %d records seen, %d classified",
            run_id,
            run.status,
            total_records,
            total_loaded,
        )

    except Exception:
        logger.exception("Pipeline run failed")
        if run is not None:
            try:
                run.status = "error"
                run.finished_at = datetime.now(UTC)
                run.error_summary = "Pipeline failed with exception"
                session.commit()
            except Exception:
                session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    """Entry point for CLI execution."""
    import asyncio

    asyncio.run(run_full_pipeline())


if __name__ == "__main__":
    main()
