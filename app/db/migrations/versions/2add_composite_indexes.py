"""Add composite indexes for snapshot tables.

These indexes were defined in __table_args__ on the ORM models but
were not generated in the initial migration. They support the core
query pattern: latest snapshot per entity (GROUP BY id, MAX observed_at).

Revision ID: 2add_composite_indexes
Revises: 1bcf05100e7e
Create Date: 2026-05-18
"""

from alembic import op

revision = "2add_composite_indexes"
down_revision = "1bcf05100e7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_rms_repository_id_observed_at",
        "repository_metrics_snapshots",
        ["repository_id", "observed_at"],
    )
    op.create_index(
        "ix_pss_project_id_observed_at",
        "project_status_snapshots",
        ["project_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_rms_repository_id_observed_at", table_name="repository_metrics_snapshots")
    op.drop_index("ix_pss_project_id_observed_at", table_name="project_status_snapshots")
