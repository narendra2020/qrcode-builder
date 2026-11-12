"""QR Store Builder: stores, media, extraction jobs, catalogue, plans, usage, stats

Revision ID: q1a0c3e5f7b9
Revises:
Create Date: 2026-10-25

Requires portfolio-builder's schema (users table) to be migrated first.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q1a0c3e5f7b9"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=False)
JSONB = postgresql.JSONB


def _ts(name: str, nullable: bool = False, default: bool = True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.func.now() if default else None)


def upgrade() -> None:
    store_status = postgresql.ENUM("draft", "published", "unpublished", "suspended", name="qr_store_status_enum")
    media_kind = postgresql.ENUM("source", "logo", "banner", "item_image", name="qr_media_kind_enum")
    job_status = postgresql.ENUM("queued", "running", "succeeded", "partial", "failed", name="qr_job_status_enum")

    op.create_table(
        "qr_stores",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("owner_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120)),
        sa.Column("slug", sa.String(63), unique=True),
        sa.Column("custom_domain", sa.String(253), unique=True),
        sa.Column("status", store_status, nullable=False, server_default="draft"),
        sa.Column("onboarding_step", sa.String(30), nullable=False, server_default="upload"),
        sa.Column("category_key", sa.String(50)),
        sa.Column("category_source", sa.String(10)),
        sa.Column("template_key", sa.String(50)),
        sa.Column("tagline", sa.String(160)),
        sa.Column("description", sa.Text),
        sa.Column("address_line", sa.String(255)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("postal_code", sa.String(20)),
        sa.Column("country", sa.String(100)),
        sa.Column("contact_phone", sa.String(20)),
        sa.Column("whatsapp_number", sa.String(20)),
        sa.Column("whatsapp_verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("email", sa.String(255)),
        sa.Column("opening_hours", sa.Text),
        sa.Column("maps_url", sa.String(500)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("branding", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("catalogue_version", sa.Integer, nullable=False, server_default="1"),
        _ts("published_at", True, False),
        _ts("first_published_at", True, False),
        sa.Column("suspended_reason", sa.String(255)),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_qr_stores_owner_id", "qr_stores", ["owner_id"])
    op.create_index("ix_qr_stores_status", "qr_stores", ["status"])

    op.create_table(
        "qr_media",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", media_kind, nullable=False),
        sa.Column("origin", sa.String(20), nullable=False, server_default="upload"),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("variants", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        _ts("deleted_at", True, False),
        _ts("created_at"),
    )
    op.create_index("ix_qr_media_store_kind", "qr_media", ["store_id", "kind"])

    op.create_table(
        "qr_extraction_jobs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("provider", sa.String(30)),
        sa.Column("model", sa.String(100)),
        sa.Column("pages", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("result", JSONB),
        sa.Column("error_code", sa.String(50)),
        sa.Column("error_message", sa.String(500)),
        _ts("created_at"),
        _ts("started_at", True, False),
        _ts("heartbeat_at", True, False),
        _ts("finished_at", True, False),
    )
    op.create_index("ix_qr_jobs_store_created", "qr_extraction_jobs", ["store_id", "created_at"])
    op.create_index("ix_qr_extraction_jobs_status", "qr_extraction_jobs", ["status"])

    op.create_table(
        "qr_catalogue_categories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_qr_catalogue_categories_store_id", "qr_catalogue_categories", ["store_id"])

    op.create_table(
        "qr_catalogue_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", UUID, sa.ForeignKey("qr_catalogue_categories.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("price_text", sa.String(60)),
        sa.Column("variants", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("labels", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("available", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("image_media_id", UUID, sa.ForeignKey("qr_media.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
        sa.Column("source_media_id", UUID),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("review_reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("user_edited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_qr_item_price_nonneg"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_qr_items_store_position", "qr_catalogue_items", ["store_id", "position"])

    op.create_table(
        "qr_plans",
        sa.Column("code", sa.String(30), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("monthly_catalogue_updates", sa.Integer),
        sa.Column("price_rupees", sa.Integer),
        sa.Column("features", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        _ts("updated_at"),
    )

    op.create_table(
        "qr_plan_grants",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_code", sa.String(30), sa.ForeignKey("qr_plans.code"), nullable=False),
        _ts("valid_until", True, False),
        sa.Column("granted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("note", sa.String(255)),
        _ts("revoked_at", True, False),
        _ts("created_at"),
    )
    op.create_index("ix_qr_plan_grants_user_id", "qr_plan_grants", ["user_id"])

    op.create_table(
        "qr_usage_counters",
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("catalogue_updates", sa.Integer, nullable=False, server_default="0"),
        _ts("updated_at"),
    )

    op.create_table(
        "qr_catalogue_revisions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", UUID, sa.ForeignKey("users.id")),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("counted", sa.Boolean, nullable=False),
        sa.Column("plan_code", sa.String(30), nullable=False),
        sa.Column("summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("catalogue_hash", sa.String(64), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_qr_revisions_store_created", "qr_catalogue_revisions", ["store_id", "created_at"])

    op.create_table(
        "qr_store_daily_stats",
        sa.Column("store_id", UUID, sa.ForeignKey("qr_stores.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("item_enquiries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cart_enquiries", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for table in ("qr_store_daily_stats", "qr_catalogue_revisions", "qr_usage_counters", "qr_plan_grants",
                  "qr_plans", "qr_catalogue_items", "qr_catalogue_categories", "qr_extraction_jobs",
                  "qr_media", "qr_stores"):
        op.drop_table(table)
    for enum in ("qr_job_status_enum", "qr_media_kind_enum", "qr_store_status_enum"):
        op.execute(f"DROP TYPE IF EXISTS {enum}")
