"""QR Store Builder: payment details on stores + Split Bill tables

Revision ID: q3c2e5a7b9d1
Revises: q2b1d4f6a8c0
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q3c2e5a7b9d1"
down_revision = "q2b1d4f6a8c0"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE qr_media_kind_enum ADD VALUE IF NOT EXISTS 'payment_qr'")

    op.add_column("qr_stores", sa.Column("upi_id", sa.String(100), nullable=True))
    op.add_column("qr_stores", sa.Column("payment_qr_media_id", UUID, sa.ForeignKey("qr_media.id", ondelete="SET NULL"), nullable=True))
    op.add_column("qr_stores", sa.Column("split_bill_enabled", sa.Boolean, nullable=False, server_default=sa.false()))

    op.create_table(
        "qr_split_bills",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(12), nullable=False, unique=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("total_paise", sa.BigInteger, nullable=False),
        sa.Column("participant_count", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("table_no", sa.String(30), nullable=True),
        sa.Column("upi_id", sa.String(100), nullable=True),
        sa.Column("payment_qr_media_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(12), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "idempotency_key", name="uq_qr_split_bills_store_idem"),
        sa.CheckConstraint("total_paise > 0", name="ck_qr_split_bills_total_positive"),
    )
    op.create_index("ix_qr_split_bills_store_created", "qr_split_bills", ["store_id", "created_at"])

    op.create_table(
        "qr_split_bill_participants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("split_bill_id", UUID, sa.ForeignKey("qr_split_bills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("name", sa.String(60), nullable=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("share_paise", sa.BigInteger, nullable=False),
        sa.Column("notification_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("notification_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notification_error", sa.String(200), nullable=True),
        sa.Column("provider_message_id", sa.String(100), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("payment_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_confirmed_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("share_paise > 0", name="ck_qr_split_participants_share_positive"),
    )
    op.create_index("ix_qr_split_bill_participants_split_bill_id", "qr_split_bill_participants", ["split_bill_id"])
    op.create_index("ix_qr_split_participants_phone_created", "qr_split_bill_participants", ["phone", "created_at"])


def downgrade() -> None:
    op.drop_table("qr_split_bill_participants")
    op.drop_table("qr_split_bills")
    op.drop_column("qr_stores", "split_bill_enabled")
    op.drop_column("qr_stores", "payment_qr_media_id")
    op.drop_column("qr_stores", "upi_id")
    # The 'payment_qr' enum value is left in place (Postgres cannot drop enum values).
