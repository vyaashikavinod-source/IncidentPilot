"""Version audit chains and persist signed checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0005_security_hardening"
down_revision = "0004_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "incident_audit_records",
        sa.Column("chain_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "incident_audit_records",
        sa.Column(
            "canonicalization_version",
            sa.String(64),
            server_default="incidentpilot-legacy-json-v1",
            nullable=False,
        ),
    )
    op.create_table(
        "audit_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_version", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("last_record_hash", sa.String(64), nullable=False),
        sa.Column("checkpoint_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signature"),
    )
    op.create_index("ix_audit_checkpoints_incident_id", "audit_checkpoints", ["incident_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_checkpoints_incident_id", table_name="audit_checkpoints")
    op.drop_table("audit_checkpoints")
    op.drop_column("incident_audit_records", "canonicalization_version")
    op.drop_column("incident_audit_records", "chain_version")
