"""
SQLAlchemy ORM models for the MePage QR Store Builder.

This service shares portfolio-builder's PostgreSQL database. Tables it
OWNS are prefixed `qr_` and versioned by this service's own Alembic chain
(version table `alembic_version_qr`). Tables it only READS or appends to
(users, payment_requests, published_portfolios, audit_logs) are owned by
portfolio-builder and are mapped here with just the columns this service
needs — never alter them from this service's migrations.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# Tables owned by portfolio-builder. Excluded from this service's migrations
# (see alembic/env.py include_object).
EXTERNAL_TABLES = {"users", "user_profiles", "payment_requests", "published_portfolios", "audit_logs"}


# ---------------------------------------------------------------------------
# Portfolio-builder tables (read / append only)
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    # Holds the verified E.164 mobile number (see portfolio-builder's
    # models.User — "encrypted" is aspirational there, it is plain text).
    mobile_number_encrypted: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="registered_user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped["UserProfile | None"] = relationship("UserProfile", uselist=False)

    @property
    def is_admin(self) -> bool:
        return self.role in ("admin", "super_admin")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)


class PaymentRequest(Base):
    __tablename__ = "payment_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    product: Mapped[str] = mapped_column(String(30), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="upi")
    amount_rupees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PublishedPortfolio(Base):
    __tablename__ = "published_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(63), unique=True, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# QR Store Builder tables
# ---------------------------------------------------------------------------

class StoreStatusEnum(str, enum.Enum):
    draft = "draft"
    published = "published"
    unpublished = "unpublished"
    suspended = "suspended"


class Store(Base):
    """
    One storefront. `owner_id` is not unique — multiple stores per user
    are supported by the schema and gated by settings.MAX_STORES_PER_USER.
    `custom_domain` is reserved for future custom-domain routing; the
    public URL is always derived from `slug` today.
    """
    __tablename__ = "qr_stores"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(63), unique=True, nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(String(253), unique=True, nullable=True)
    status: Mapped[StoreStatusEnum] = mapped_column(
        Enum(StoreStatusEnum, name="qr_store_status_enum"), nullable=False, default=StoreStatusEnum.draft, index=True
    )
    onboarding_step: Mapped[str] = mapped_column(String(30), nullable=False, default="upload")

    category_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category_source: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "ai" | "user"
    template_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    tagline: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(Text, nullable=True)
    maps_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    zomato_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    swiggy_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Payment details (customer-facing payment info for Split Bill). The UPI ID
    # and QR are only ever sent to customers who start a split bill — they are
    # never embedded in the published static site.
    upi_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_qr_media_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_media.id", ondelete="SET NULL"), nullable=True
    )
    split_bill_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Colors / font / logo+banner media ids — see app/services/branding.py.
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Bumped on every catalogue write (AI import or owner save); clients send
    # the version they edited so stale editors get a 409 instead of
    # silently overwriting newer changes.
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship("User")
    categories: Mapped[list["CatalogueCategory"]] = relationship(
        "CatalogueCategory", cascade="all, delete-orphan", order_by="CatalogueCategory.position"
    )
    items: Mapped[list["CatalogueItem"]] = relationship(
        "CatalogueItem", cascade="all, delete-orphan", order_by="CatalogueItem.position"
    )

    @property
    def ever_published(self) -> bool:
        return self.first_published_at is not None


class MediaKindEnum(str, enum.Enum):
    source = "source"          # uploaded menu / catalogue page (private)
    logo = "logo"
    banner = "banner"
    item_image = "item_image"
    payment_qr = "payment_qr"  # merchant's UPI / payment QR (lossless, owner-uploaded)


class Media(Base):
    """
    An uploaded or derived image. Files live under UPLOADS_DIR/qr/<store>/
    and are never statically served: owners fetch them through signed
    URLs (app/api/routes/media.py) and published sites get their own
    copies at publish time. `variants` maps width -> relative path of
    resized WebP renditions used for responsive srcset.
    """
    __tablename__ = "qr_media"
    __table_args__ = (Index("ix_qr_media_store_kind", "store_id", "kind"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[MediaKindEnum] = mapped_column(Enum(MediaKindEnum, name="qr_media_kind_enum"), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")  # upload | catalogue_crop
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    variants: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobStatusEnum(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"   # some pages succeeded, some failed
    failed = "failed"


class ExtractionJob(Base):
    """
    One AI analysis run over a store's source pages. `pages` tracks
    per-page progress so a partial failure can be retried page-by-page:
    [{media_id, status, attempts, error, item_count}]. `result` holds the
    aggregated category suggestion and verbatim business details. The
    extracted items themselves are written straight into qr_items.
    """
    __tablename__ = "qr_extraction_jobs"
    __table_args__ = (Index("ix_qr_jobs_store_created", "store_id", "created_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    status: Mapped[JobStatusEnum] = mapped_column(
        Enum(JobStatusEnum, name="qr_job_status_enum"), nullable=False, default=JobStatusEnum.queued, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CatalogueCategory(Base):
    __tablename__ = "qr_catalogue_categories"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CatalogueItem(Base):
    """
    A structured menu item / product. Prices are exact decimals; `price`
    is null when the source had no readable price — never guessed.
    `needs_review` + `review_reasons` mark low-confidence AI fields; any
    owner edit (or an explicit "looks right") clears them, and publishing
    is refused while any remain (see app/services/publishing.py).
    """
    __tablename__ = "qr_catalogue_items"
    __table_args__ = (Index("ix_qr_items_store_position", "store_id", "position"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_catalogue_categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_text: Mapped[str | None] = mapped_column(String(60), nullable=True)
    variants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    labels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_media_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_media.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")  # ai | manual
    source_media_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Plan(Base):
    """
    Admin-configurable plan entitlements. `monthly_catalogue_updates` null
    means unlimited. `price_rupees` is display-only — the amount actually
    charged comes from portfolio-builder's billing config.
    """
    __tablename__ = "qr_plans"

    code: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_catalogue_updates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_rupees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlanGrant(Base):
    """Admin-granted plan (support cases, promotions). Paid upgrades are
    derived from approved payment_requests instead — see app/services/plans.py."""
    __tablename__ = "qr_plan_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    plan_code: Mapped[str] = mapped_column(String(30), ForeignKey("qr_plans.code"), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageCounter(Base):
    """Counted catalogue updates per store per quota period ("YYYY-MM" in
    settings.QUOTA_TIMEZONE)."""
    __tablename__ = "qr_usage_counters"

    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[str] = mapped_column(String(7), primary_key=True)
    catalogue_updates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CatalogueRevision(Base):
    """One row per successful catalogue save — the quota ledger and history."""
    __tablename__ = "qr_catalogue_revisions"
    __table_args__ = (Index("ix_qr_revisions_store_created", "store_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    plan_code: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    catalogue_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoreDailyStat(Base):
    __tablename__ = "qr_store_daily_stats"

    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_enquiries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cart_enquiries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TableCode(Base):
    """A sitting-area / table label with its own QR code for a store."""
    __tablename__ = "qr_table_codes"
    __table_args__ = (UniqueConstraint("store_id", "table_key", name="uq_qr_table_codes_store_key"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_no: Mapped[str] = mapped_column(String(30), nullable=False)
    table_key: Mapped[str] = mapped_column(String(30), nullable=False)  # casefolded, for uniqueness
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SplitBill(Base):
    """
    A bill split equally among friends. Money is integer paise. The
    customer who creates a bill gets an HMAC-derived capability token (see
    app/services/split_bill.py) to poll status / retry notifications without
    an account. (store_id, idempotency_key) makes create safe to retry — a
    repeat returns the original bill and sends nothing new.
    """
    __tablename__ = "qr_split_bills"
    __table_args__ = (
        UniqueConstraint("store_id", "idempotency_key", name="uq_qr_split_bills_store_idem"),
        Index("ix_qr_split_bills_store_created", "store_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)  # short human reference
    store_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_stores.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    table_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Snapshot of how participants were told to pay (so later settings edits
    # never change what an existing bill shows).
    upi_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_qr_media_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    delivery_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")  # cloud_api | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    participants: Mapped[list["SplitBillParticipant"]] = relationship(
        "SplitBillParticipant", cascade="all, delete-orphan", order_by="SplitBillParticipant.position"
    )


class SplitBillParticipant(Base):
    """
    notification_status: pending | sending | sent | failed | manual
      ("sent" = accepted by the WhatsApp API; it is NOT delivery or payment.)
    payment_status: pending | confirmed — set only by the merchant.
    """
    __tablename__ = "qr_split_bill_participants"
    __table_args__ = (Index("ix_qr_split_participants_phone_created", "phone", "created_at"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    split_bill_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("qr_split_bills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)  # E.164; never returned in full by public APIs
    share_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    notification_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    notification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notification_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    payment_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_confirmed_by: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
