"""Persist owner-scoped job submission idempotency."""

import sqlalchemy as sa
from alembic import op

revision = "0003_job_idempotency"
down_revision = "0002_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(128), nullable=True))
    op.add_column("jobs", sa.Column("payload_sha256", sa.String(64), nullable=True))
    op.execute(
        "UPDATE jobs SET idempotency_key = 'legacy-' || id::text, payload_sha256 = repeat('0', 64)"
    )
    op.alter_column("jobs", "idempotency_key", nullable=False)
    op.alter_column("jobs", "payload_sha256", nullable=False)
    op.create_unique_constraint(
        "uq_jobs_owner_idempotency_key", "jobs", ["owner_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_jobs_owner_idempotency_key", "jobs", type_="unique")
    op.drop_column("jobs", "payload_sha256")
    op.drop_column("jobs", "idempotency_key")
