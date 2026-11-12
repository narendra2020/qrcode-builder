"""QR Store Builder: per-table (sitting area) QR codes

Revision ID: q2b1d4f6a8c0
Revises: q1a0c3e5f7b9
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q2b1d4f6a8c0"
down_revision = "q1a0c3e5f7b9"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "qr_table_codes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_no", sa.String(30), nullable=False),
        sa.Column("table_key", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "table_key", name="uq_qr_table_codes_store_key"),
    )
    op.create_index("ix_qr_table_codes_store_id", "qr_table_codes", ["store_id"])


def downgrade() -> None:
    op.drop_table("qr_table_codes")
