"""Persist manual benchmark and formal evaluation documents."""

import sqlalchemy as sa
from alembic import op

revision = "0007_benchmark_persistence"
down_revision = "0006_memory_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, finalized in (("manual_benchmark_runs", True), ("evaluation_runs", False)):
        columns = [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("document", sa.dialects.postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        ]
        if finalized:
            columns.append(
                sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        op.create_table(name, *columns)


def downgrade() -> None:
    op.drop_table("evaluation_runs")
    op.drop_table("manual_benchmark_runs")
