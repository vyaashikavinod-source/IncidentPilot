"""Add read-only deployment history source."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_deployments"
down_revision = "0001_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("service", sa.String(63), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("git_sha", sa.String(64), nullable=False),
        sa.Column("image_reference", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("deployment_metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_deployments_service", "deployments", ["service"])
    op.create_index("ix_deployments_environment", "deployments", ["environment"])
    op.create_index("ix_deployments_deployed_at", "deployments", ["deployed_at"])
    op.execute(
        "INSERT INTO deployments VALUES "
        "('afca0b9e-b853-4346-a86c-0edc14d13b4a', 'sandbox', 'phase1-observability', "
        "'afca0b9eb853d346a86c0edc14d13b4a82e49ba9', 'incidentpilot-compose:afca0b9', "
        "'local', '2026-09-09T13:56:00Z', 'succeeded', '{\"source\": \"verified_commit\"}')"
    )


def downgrade() -> None:
    op.drop_table("deployments")
