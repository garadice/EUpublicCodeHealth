"""Streamlit dashboard for EU PubliCodeHealth.

Displays repository activity monitoring data for EU public-sector
open-source software with filtering, charts, and CSV export.

NOTE: This dashboard measures repository activity only. It does NOT
assess software quality, security, or vulnerability status.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.status import StatusLabel
from app.db.models import (
    PipelineRun,
    Project,
    ProjectStatusSnapshot,
    Repository,
    RepositoryMetricsSnapshot,
)
from app.db.session import get_session_factory

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EU_BLUE = "#003399"
EU_GOLD = "#D4A017"
EU_LIGHT_GREY = "#F5F5F5"

STATUS_COLORS: dict[str, str] = {
    StatusLabel.ACTIVE: "#28A745",
    StatusLabel.SLOW: "#FFC107",
    StatusLabel.STALE: "#DC3545",
    StatusLabel.ARCHIVED: "#6C757D",
    StatusLabel.DATA_ERROR: "#E83E8C",
    StatusLabel.UNKNOWN: "#6F42C1",
}

STATUS_ORDER: list[str] = [
    StatusLabel.ACTIVE,
    StatusLabel.SLOW,
    StatusLabel.STALE,
    StatusLabel.ARCHIVED,
    StatusLabel.DATA_ERROR,
    StatusLabel.UNKNOWN,
]

STATUS_CELL_STYLE: dict[str, str] = {
    StatusLabel.ACTIVE: "background-color: #d4edda; color: #155724; font-weight: bold",
    StatusLabel.SLOW: "background-color: #fff3cd; color: #856404; font-weight: bold",
    StatusLabel.STALE: "background-color: #f8d7da; color: #721c24; font-weight: bold",
    StatusLabel.ARCHIVED: "background-color: #e2e3e5; color: #383d41; font-weight: bold",
    StatusLabel.DATA_ERROR: "background-color: #f5c6cb; color: #721c24; font-weight: bold",
    StatusLabel.UNKNOWN: "background-color: #e2d5f1; color: #563d7c; font-weight: bold",
}

# Priority for deduplicating multi-repo projects (lower = higher priority).
# Matches AGENTS.md: Archived(1) > Data error(2) > Unknown(3) > Active(4) > Slow(5) > Stale(6)
DEDUP_PRIORITY: dict[str, int] = {
    StatusLabel.ARCHIVED: 0,
    StatusLabel.DATA_ERROR: 1,
    StatusLabel.UNKNOWN: 2,
    StatusLabel.ACTIVE: 3,
    StatusLabel.SLOW: 4,
    StatusLabel.STALE: 5,
}

# ---------------------------------------------------------------------------
# Page configuration (must be the first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    layout="wide",
    page_title="EU PubliCodeHealth",
    page_icon="\U0001f4ca",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_logger = logging.getLogger(__name__)


def _inject_css() -> None:
    """Inject EU-themed custom CSS."""
    st.markdown(
        f"""
        <style>
        .eu-header {{
            background-color: {EU_BLUE};
            color: white;
            padding: 1.5rem 2rem;
            border-radius: 0.5rem;
            margin-bottom: 1.5rem;
        }}
        .eu-header h1 {{
            color: white;
            margin: 0;
            font-size: 1.8rem;
            font-weight: 700;
        }}
        .eu-header p {{
            color: #ccd9ff;
            margin: 0.3rem 0 0 0;
            font-size: 1rem;
        }}
        .eu-note {{
            font-size: 0.85rem;
            color: #666;
            font-style: italic;
            margin-top: 1rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _get_session() -> Session:
    """Create a new database session for Streamlit usage."""
    factory = get_session_factory()
    return factory()


def _format_date(dt: datetime | None) -> str:
    """Format a datetime as a human-readable string."""
    if dt is None:
        return "N/A"
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError):
        return str(dt)


def _style_status_cell(val: str) -> str:
    """Return inline CSS for a status-label table cell."""
    return STATUS_CELL_STYLE.get(val, "")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300, show_spinner="Loading dashboard data...")
def load_dashboard_data() -> dict[str, Any]:
    """Load all dashboard data from the database.

    Returns a dict with keys:
        combined_df     - merged project / status / repo / metrics DataFrame
        pipeline_info   - dict of latest PipelineRun fields
        data_quality    - dict with no_repo_url, unsupported_hosts, api_errors
        total_projects  - int

    Raises:
        Exception: propagated when the database is unreachable.
    """
    session = _get_session()
    try:
        return _assemble_dashboard(session)
    finally:
        session.close()


def _assemble_dashboard(session: Session) -> dict[str, Any]:
    """Execute queries and assemble the dashboard payload."""

    # ── Projects ──────────────────────────────────────────────────────────
    project_rows = session.query(
        Project.id,
        Project.name,
        Project.development_status,
        Project.license.label("project_license"),
        Project.source_url,
    ).all()
    projects_df = (
        pd.DataFrame(
            project_rows, columns=["project_id", "name", "development_status", "project_license", "source_url"]
        )
        if project_rows
        else pd.DataFrame(columns=["project_id", "name", "development_status", "project_license", "source_url"])
    )

    # ── Latest status per project ─────────────────────────────────────────
    status_df = pd.DataFrame(columns=["project_id", "repository_id", "status_label", "reason"])
    if not projects_df.empty:
        latest_status_sq = (
            session.query(
                ProjectStatusSnapshot.project_id,
                func.max(ProjectStatusSnapshot.observed_at).label("max_observed_at"),
            )
            .group_by(ProjectStatusSnapshot.project_id)
            .subquery()
        )
        status_rows = (
            session.query(
                ProjectStatusSnapshot.project_id,
                ProjectStatusSnapshot.repository_id,
                ProjectStatusSnapshot.status_label,
                ProjectStatusSnapshot.reason,
            )
            .join(
                latest_status_sq,
                and_(
                    ProjectStatusSnapshot.project_id == latest_status_sq.c.project_id,
                    ProjectStatusSnapshot.observed_at == latest_status_sq.c.max_observed_at,
                ),
            )
            .all()
        )
        if status_rows:
            status_df = pd.DataFrame(status_rows, columns=["project_id", "repository_id", "status_label", "reason"])
            # A project may have several repos each with its own status snapshot.
            # Keep the highest-priority status (lowest index in STATUS_ORDER).
            if status_df["project_id"].duplicated().any():
                status_df["_priority"] = status_df["status_label"].map(DEDUP_PRIORITY).fillna(len(DEDUP_PRIORITY))
                status_df = (
                    status_df.sort_values("_priority")
                    .drop_duplicates(subset=["project_id"], keep="first")
                    .drop(columns=["_priority"])
                )

    # ── Repositories ──────────────────────────────────────────────────────
    repo_rows = session.query(
        Repository.id,
        Repository.project_id,
        Repository.host,
        Repository.canonical_url,
        Repository.is_supported,
    ).all()
    repos_df = (
        pd.DataFrame(repo_rows, columns=["repo_id", "project_id", "host", "canonical_url", "is_supported"])
        if repo_rows
        else pd.DataFrame(columns=["repo_id", "project_id", "host", "canonical_url", "is_supported"])
    )

    # ── Latest metrics per repository ─────────────────────────────────────
    metrics_df = pd.DataFrame(columns=["repo_id", "stars", "forks", "pushed_at", "license_key", "api_status"])
    if not repos_df.empty:
        latest_metrics_sq = (
            session.query(
                RepositoryMetricsSnapshot.repository_id,
                func.max(RepositoryMetricsSnapshot.observed_at).label("max_observed_at"),
            )
            .group_by(RepositoryMetricsSnapshot.repository_id)
            .subquery()
        )
        metrics_rows = (
            session.query(
                RepositoryMetricsSnapshot.repository_id,
                RepositoryMetricsSnapshot.stars,
                RepositoryMetricsSnapshot.forks,
                RepositoryMetricsSnapshot.pushed_at,
                RepositoryMetricsSnapshot.license_key,
                RepositoryMetricsSnapshot.api_status,
            )
            .join(
                latest_metrics_sq,
                and_(
                    RepositoryMetricsSnapshot.repository_id == latest_metrics_sq.c.repository_id,
                    RepositoryMetricsSnapshot.observed_at == latest_metrics_sq.c.max_observed_at,
                ),
            )
            .all()
        )
        if metrics_rows:
            metrics_df = pd.DataFrame(
                metrics_rows,
                columns=["repo_id", "stars", "forks", "pushed_at", "license_key", "api_status"],
            )

    # ── Latest pipeline run ───────────────────────────────────────────────
    last_run = session.query(PipelineRun).order_by(PipelineRun.started_at.desc()).first()
    pipeline_info: dict = {}
    if last_run:
        pipeline_info = {
            "started_at": last_run.started_at,
            "finished_at": last_run.finished_at,
            "status": last_run.status,
            "records_seen": last_run.records_seen,
            "records_loaded": last_run.records_loaded,
            "errors_count": last_run.errors_count,
            "error_summary": last_run.error_summary,
        }

    # ── Assemble combined DataFrame ───────────────────────────────────────
    combined_df = projects_df.copy()

    # Merge latest status
    if not status_df.empty:
        combined_df = combined_df.merge(
            status_df[["project_id", "status_label", "reason", "repository_id"]],
            on="project_id",
            how="left",
        )
    else:
        combined_df["status_label"] = None
        combined_df["reason"] = None
        combined_df["repository_id"] = None

    # Fill missing repository_id from the repos table (first repo per project)
    if not repos_df.empty:
        needs_repo = combined_df["repository_id"].isna()
        if needs_repo.any():
            first_repo = (
                repos_df[["project_id", "repo_id"]]
                .drop_duplicates(subset=["project_id"], keep="first")
                .rename(columns={"repo_id": "fill_repo_id"})
            )
            combined_df = combined_df.merge(first_repo, on="project_id", how="left")
            combined_df["repository_id"] = combined_df["repository_id"].fillna(combined_df["fill_repo_id"])
            combined_df = combined_df.drop(columns=["fill_repo_id"])

    # Merge repository info
    if not repos_df.empty:
        repo_info = repos_df[["repo_id", "host", "canonical_url", "is_supported"]].rename(
            columns={"repo_id": "repository_id"}
        )
        combined_df = combined_df.merge(repo_info, on="repository_id", how="left")
    else:
        combined_df["host"] = None
        combined_df["canonical_url"] = None
        combined_df["is_supported"] = None

    # Merge metrics
    if not metrics_df.empty:
        metrics_info = metrics_df.rename(columns={"repo_id": "repository_id"})
        combined_df = combined_df.merge(metrics_info, on="repository_id", how="left")
    else:
        combined_df["stars"] = None
        combined_df["forks"] = None
        combined_df["pushed_at"] = None
        combined_df["license_key"] = None
        combined_df["api_status"] = None

    # Derived columns
    combined_df["license_display"] = combined_df["license_key"].fillna(combined_df["project_license"])
    combined_df["status_label"] = combined_df["status_label"].fillna("Unknown")

    # ── Data quality counts ───────────────────────────────────────────────
    total_projects = len(projects_df)
    project_ids_with_repo = set(repos_df["project_id"].unique()) if not repos_df.empty else set()
    all_project_ids = set(projects_df["project_id"].unique()) if not projects_df.empty else set()
    no_repo_count = len(all_project_ids - project_ids_with_repo)

    unsupported_count = 0
    api_error_count = 0
    if not repos_df.empty:
        unsupported_count = int(repos_df[~repos_df["is_supported"]]["project_id"].nunique())
    if not metrics_df.empty:
        api_error_count = int(metrics_df[metrics_df["api_status"] != "success"]["repo_id"].nunique())

    return {
        "combined_df": combined_df,
        "pipeline_info": pipeline_info,
        "data_quality": {
            "no_repo_url": no_repo_count,
            "projects_unsupported_host": unsupported_count,
            "api_errors": api_error_count,
        },
        "total_projects": total_projects,
    }


# ---------------------------------------------------------------------------
# Render functions
# ---------------------------------------------------------------------------


def render_header() -> None:
    """Render the project title and subtitle."""
    st.markdown(
        '<div class="eu-header">'
        "<h1>EU PubliCodeHealth</h1>"
        "<p>Monitoring repository activity of EU public-sector open-source software</p>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_kpi_cards(all_df: pd.DataFrame, total: int) -> None:
    """Render four KPI metric cards using overall (unfiltered) data."""
    if total == 0:
        st.info("No data available yet. Run the pipeline to populate the dashboard.")
        return

    active_count = int((all_df["status_label"] == StatusLabel.ACTIVE).sum())
    stale_count = int((all_df["status_label"] == StatusLabel.STALE).sum())
    unknown_count = int(all_df["status_label"].isin([StatusLabel.UNKNOWN, StatusLabel.DATA_ERROR]).sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Projects", f"{total:,}")
    col2.metric("Active", f"{active_count / total * 100:.1f}%", delta=f"{active_count:,} projects")
    col3.metric("Stale", f"{stale_count / total * 100:.1f}%", delta=f"{stale_count:,} projects")
    col4.metric(
        "Unknown / Errors",
        f"{unknown_count / total * 100:.1f}%",
        delta=f"{unknown_count:,} projects",
        help="Includes 'Unknown' and 'Data error' statuses",
    )


def render_status_chart(df: pd.DataFrame) -> None:
    """Render the status distribution bar chart."""
    st.subheader("Status Distribution")

    if df.empty:
        st.info("No data to display.")
        return

    status_counts = df["status_label"].value_counts().reset_index()
    status_counts.columns = ["status_label", "count"]

    # Ensure every status label appears (even with zero count)
    for label in STATUS_ORDER:
        if label not in status_counts["status_label"].values:
            status_counts = pd.concat(
                [status_counts, pd.DataFrame({"status_label": [label], "count": [0]})],
                ignore_index=True,
            )

    chart = (
        alt.Chart(status_counts)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("status_label:N", title="Status", sort=STATUS_ORDER),
            y=alt.Y("count:Q", title="Number of Projects"),
            color=alt.Color(
                "status_label:N",
                scale=alt.Scale(
                    domain=STATUS_ORDER,
                    range=[STATUS_COLORS[s] for s in STATUS_ORDER],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("status_label:N", title="Status"),
                alt.Tooltip("count:Q", title="Projects"),
            ],
        )
        .properties(width=700, height=350)
    )

    st.altair_chart(chart, use_container_width=True)


def render_filters(df: pd.DataFrame) -> dict[str, Any]:
    """Render sidebar filter widgets and return the current filter state."""
    with st.sidebar:
        st.header("Filters")

        available_statuses = sorted(df["status_label"].dropna().unique().tolist()) if not df.empty else []
        selected_statuses = st.multiselect(
            "Filter by status",
            options=STATUS_ORDER,
            default=[s for s in STATUS_ORDER if s in available_statuses] or STATUS_ORDER,
        )

        available_hosts = sorted(df["host"].dropna().unique().tolist()) if not df.empty else []
        selected_hosts = st.multiselect(
            "Filter by host",
            options=available_hosts,
            default=available_hosts,
        )

        name_search = st.text_input("Search by project name", placeholder="Type to filter...")

        st.divider()
        if st.button("Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    return {
        "statuses": selected_statuses,
        "hosts": selected_hosts,
        "name_search": name_search.strip(),
    }


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """Apply sidebar filter selections to the combined DataFrame."""
    if df.empty:
        return df

    result = df.copy()

    if filters["statuses"]:
        result = result[result["status_label"].isin(filters["statuses"])]

    if filters["hosts"]:
        host_mask = result["host"].isin(filters["hosts"])
        host_mask |= result["host"].isna()
        result = result[host_mask]

    if filters["name_search"]:
        result = result[result["name"].str.contains(filters["name_search"], case=False, na=False, regex=False)]

    return result.reset_index(drop=True)


def render_projects_table(df: pd.DataFrame) -> None:
    """Render the main projects data table with status colour coding."""
    st.subheader("Projects Overview")

    if df.empty:
        st.info("No projects match the current filters.")
        return

    column_map = {
        "name": "Project Name",
        "status_label": "Status",
        "host": "Host",
        "pushed_at": "Last Push",
        "stars": "Stars",
        "forks": "Forks",
        "license_display": "License",
        "development_status": "Dev Status",
    }
    display_df = df[list(column_map.keys())].rename(columns=column_map).copy()

    # Format dates and numbers for display
    display_df["Last Push"] = display_df["Last Push"].apply(lambda x: _format_date(x) if pd.notna(x) else "N/A")
    display_df["Stars"] = display_df["Stars"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")
    display_df["Forks"] = display_df["Forks"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "N/A")

    styled = display_df.style.map(_style_status_cell, subset=["Status"])
    st.dataframe(styled, use_container_width=True, height=500)


def render_csv_download(df: pd.DataFrame) -> None:
    """Render a download button for the filtered data as CSV."""
    if df.empty:
        return

    column_map = {
        "name": "Project Name",
        "status_label": "Status",
        "host": "Host",
        "pushed_at": "Last Push",
        "stars": "Stars",
        "forks": "Forks",
        "license_display": "License",
        "development_status": "Dev Status",
        "canonical_url": "Repository URL",
        "reason": "Status Reason",
    }
    export_df = df[list(column_map.keys())].rename(columns=column_map).copy()
    export_df["Last Push"] = export_df["Last Push"].apply(lambda x: _format_date(x) if pd.notna(x) else "")

    csv_buffer = io.StringIO()
    export_df.to_csv(csv_buffer, index=False, quoting=1)

    st.download_button(
        label="Download filtered data as CSV",
        data=csv_buffer.getvalue(),
        file_name="eupubliccodehealth_export.csv",
        mime="text/csv",
        use_container_width=True,
    )


def render_pipeline_info(pipeline_info: dict) -> None:
    """Render latest pipeline run information in an expander."""
    if not pipeline_info:
        st.markdown("#### Pipeline")
        st.info("No pipeline runs recorded yet.")
        return

    with st.expander("Latest Pipeline Run", expanded=False):
        row1_col1, row1_col2, row1_col3 = st.columns(3)
        row1_col1.metric("Started", _format_date(pipeline_info.get("started_at")))
        row1_col2.metric("Finished", _format_date(pipeline_info.get("finished_at")))
        row1_col3.metric("Run Status", str(pipeline_info.get("status", "N/A")))

        row2_col1, row2_col2, row2_col3 = st.columns(3)
        row2_col1.metric("Records Seen", str(pipeline_info.get("records_seen", "N/A")))
        row2_col2.metric("Records Loaded", str(pipeline_info.get("records_loaded", "N/A")))
        row2_col3.metric("Errors", str(pipeline_info.get("errors_count", 0)))

        error_summary = pipeline_info.get("error_summary")
        if error_summary:
            st.text_area("Error Summary", error_summary, height=80, disabled=True)


def render_data_quality(data_quality: dict, total: int) -> None:
    """Render data quality summary metrics."""
    st.subheader("Data Quality Summary")

    if total == 0:
        st.info("No data available.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "No Repository URL",
        f"{data_quality['no_repo_url']:,}",
        help="Projects with no linked repository",
    )
    col2.metric(
        "Unsupported Hosts",
        f"{data_quality['projects_unsupported_host']:,}",
        help="Projects on platforms not supported in the current pipeline (counted by project)",
    )
    col3.metric(
        "API Errors",
        f"{data_quality['api_errors']:,}",
        help="Repositories where the host API returned an error",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Dashboard entry point."""
    _inject_css()
    render_header()

    # Load data from database
    try:
        data = load_dashboard_data()
    except Exception:
        _logger.exception("Dashboard data load failed")
        st.error("Failed to load dashboard data. Please check server logs or ensure the database is running.")
        return

    full_df = data["combined_df"]
    total = data["total_projects"]

    # Sidebar filters
    filters = render_filters(full_df)
    filtered_df = apply_filters(full_df, filters)

    # KPIs always show overall stats (not filtered)
    render_kpi_cards(full_df, total)

    # Chart and table respond to filters
    render_status_chart(filtered_df)
    render_projects_table(filtered_df)
    render_csv_download(filtered_df)

    # Info sections
    render_pipeline_info(data["pipeline_info"])
    render_data_quality(data["data_quality"], total)

    # Methodology note
    st.markdown("---")
    st.markdown(
        '<p class="eu-note">'
        "Based on Developers Italia catalogue data. See methodology for details. "
        "This dashboard measures repository activity only &mdash; it does NOT assess "
        "software quality or security."
        "</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
