"""Persist bounded incident memory and evaluation records."""

import sqlalchemy as sa
from alembic import op

revision = "0006_memory_evaluation"
down_revision = "0005_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("document", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("incident_id"),
    )
    op.create_index("ix_incident_memory_created_at", "incident_memory", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_incident_memory_created_at", table_name="incident_memory")
    op.drop_table("incident_memory")
