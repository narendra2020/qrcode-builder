"""
Plan entitlements and the monthly catalogue-update quota.

Policy (also documented in README → "Catalogue update quota"):
- A *catalogue update* is one successful, persisted save of a store's
  catalogue (items + categories) made AFTER the store was first
  published. One save may contain any number of item/category changes.
- Not counted: onboarding edits before the first publish, the first
  publish itself, AI imports during onboarding, saves that change
  nothing, failed/rejected saves, reads, previews, branding, template,
  business-info edits and customer cart actions.
- Periods are calendar months in settings.QUOTA_TIMEZONE (Asia/Kolkata):
  the counter resets at 00:00 IST on the 1st. Usage is tracked per store.
- Enforcement is server-side inside the save transaction while holding a
  row lock on the store, so concurrent saves are serialized and cannot
  exceed the limit.

Plan resolution (highest wins): an active admin grant -> an approved
portfolio-builder payment_request for settings.PAID_PLAN_PRODUCT within
PAID_PLAN_DURATION_DAYS of approval -> the free plan. Nothing here ever
marks an upgrade as paid; that only happens through portfolio-builder's
existing (admin-reviewed UPI or signature-verified Razorpay) billing.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import PaymentRequest, Plan, PlanGrant, Store, UsageCounter, User


class QuotaExceeded(Exception):
    def __init__(self, usage: dict):
        super().__init__("Monthly catalogue update limit reached.")
        self.usage = usage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current_period(now: datetime | None = None) -> str:
    local = (now or _now()).astimezone(ZoneInfo(settings.QUOTA_TIMEZONE))
    return f"{local.year:04d}-{local.month:02d}"


def next_reset(now: datetime | None = None) -> datetime:
    tz = ZoneInfo(settings.QUOTA_TIMEZONE)
    local = (now or _now()).astimezone(tz)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=tz)


def _plan(code: str, db: Session) -> Plan:
    plan = db.get(Plan, code)
    if plan:
        return plan
    # Unseeded DB: fall back to config so enforcement never silently disappears.
    if code in (settings.PAID_PLAN_CODE, settings.PRO_SPLIT_PLAN_CODE):
        name = "Pro" if code == settings.PAID_PLAN_CODE else "Pro + Split Bill"
        return Plan(code=code, name=name, monthly_catalogue_updates=settings.QR_PRO_MONTHLY_UPDATES, features=[])
    name = "Split Bill" if code == settings.SPLIT_PLAN_CODE else "Free"
    return Plan(code=code, name=name, monthly_catalogue_updates=settings.QR_FREE_MONTHLY_UPDATES, features=[])


def has_unlimited_split_bill(plan_code: str) -> bool:
    return plan_code in (settings.SPLIT_PLAN_CODE, settings.PRO_SPLIT_PLAN_CODE)


def _compose_plan_code(pro: bool, split: bool) -> str:
    if pro and split:
        return settings.PRO_SPLIT_PLAN_CODE
    if pro:
        return settings.PAID_PLAN_CODE
    if split:
        return settings.SPLIT_PLAN_CODE
    return settings.FREE_PLAN_CODE


def resolve_plan(user: User, db: Session) -> tuple[Plan, datetime | None, str]:
    """Returns (plan, valid_until, source)."""
    now = _now()
    grant = (
        db.query(PlanGrant)
        .filter(
            PlanGrant.user_id == user.id,
            PlanGrant.revoked_at.is_(None),
            or_(PlanGrant.valid_until.is_(None), PlanGrant.valid_until > now),
        )
        .order_by(PlanGrant.created_at.desc())
        .first()
    )
    if grant:
        return _plan(grant.plan_code, db), grant.valid_until, "grant"

    # Paid entitlements are independent: Pro (more catalogue updates) and Split Bill
    # (unlimited bills). Buying both separately, or the bundle, yields "pro_split".
    duration = timedelta(days=settings.PAID_PLAN_DURATION_DAYS)
    payments = (
        db.query(PaymentRequest)
        .filter(
            PaymentRequest.user_id == user.id,
            PaymentRequest.product.in_([settings.PAID_PLAN_PRODUCT, settings.SPLIT_PLAN_PRODUCT,
                                        settings.PRO_SPLIT_PLAN_PRODUCT]),
            PaymentRequest.status == "approved",
            PaymentRequest.reviewed_at > now - duration,
        )
        .order_by(PaymentRequest.reviewed_at.desc())
        .all()
    )
    if not payments:
        return _plan(settings.FREE_PLAN_CODE, db), None, "default"
    pro_until = split_until = None
    for pay in payments:
        end = pay.reviewed_at + duration
        if pay.product in (settings.PAID_PLAN_PRODUCT, settings.PRO_SPLIT_PLAN_PRODUCT):
            pro_until = max(pro_until or end, end)
        if pay.product in (settings.SPLIT_PLAN_PRODUCT, settings.PRO_SPLIT_PLAN_PRODUCT):
            split_until = max(split_until or end, end)
    ends = [d for d in (pro_until, split_until) if d]
    plan = _plan(_compose_plan_code(bool(pro_until), bool(split_until)), db)
    return plan, min(ends), "payment"


def used_this_period(store_id: str, db: Session, period: str | None = None) -> int:
    row = db.get(UsageCounter, (store_id, period or current_period()))
    return row.catalogue_updates if row else 0


def usage_summary(store: Store, db: Session) -> dict:
    plan, valid_until, source = resolve_plan(store.owner, db)
    period = current_period()
    used = used_this_period(store.id, db, period)
    limit = plan.monthly_catalogue_updates
    return {
        "plan": {"code": plan.code, "name": plan.name, "valid_until": valid_until, "source": source},
        "period": period,
        "timezone": settings.QUOTA_TIMEZONE,
        "used": used,
        "limit": limit,
        "unlimited": limit is None,
        "remaining": None if limit is None else max(limit - used, 0),
        "resets_at": next_reset(),
        "counts_now": store.ever_published,
    }


def consume_catalogue_update(store: Store, db: Session) -> tuple[bool, str]:
    """
    Must be called inside the save transaction AFTER locking the store row
    (SELECT ... FOR UPDATE). Raises QuotaExceeded if the save would exceed
    the plan limit; otherwise increments the counter. Returns
    (counted, plan_code). Nothing is persisted until the caller commits,
    so a failed save never consumes quota.
    """
    plan, _, _ = resolve_plan(store.owner, db)
    if not store.ever_published:
        return False, plan.code
    period = current_period()
    db.execute(
        pg_insert(UsageCounter)
        .values(store_id=store.id, period=period, catalogue_updates=0)
        .on_conflict_do_nothing(index_elements=["store_id", "period"])
    )
    counter = (
        db.query(UsageCounter)
        .filter(UsageCounter.store_id == store.id, UsageCounter.period == period)
        .with_for_update()
        .one()
    )
    limit = plan.monthly_catalogue_updates
    if limit is not None and counter.catalogue_updates >= limit:
        raise QuotaExceeded(usage_summary(store, db))
    counter.catalogue_updates += 1
    return True, plan.code


def split_bill_usage(store: Store, db: Session) -> dict:
    """Split bills created this calendar month vs the plan allowance (None limit = unlimited)."""
    from app.models.models import SplitBill  # local: models import order

    plan, _, _ = resolve_plan(store.owner, db)
    tz = ZoneInfo(settings.QUOTA_TIMEZONE)
    local = _now().astimezone(tz)
    start = datetime(local.year, local.month, 1, tzinfo=tz)
    used = db.query(func.count(SplitBill.id)).filter(
        SplitBill.store_id == store.id, SplitBill.created_at >= start).scalar() or 0
    limit = None if has_unlimited_split_bill(plan.code) else settings.SPLIT_BILL_FREE_MONTHLY
    return {"used": used, "limit": limit, "unlimited": limit is None,
            "remaining": None if limit is None else max(limit - used, 0),
            "resets_at": next_reset(), "plan": plan.code}


def plans_out(db: Session) -> list[dict]:
    rows = db.query(Plan).filter(Plan.is_active.is_(True)).order_by(Plan.display_order).all()
    return [
        {"code": p.code, "name": p.name, "description": p.description,
         "monthly_catalogue_updates": p.monthly_catalogue_updates, "price_rupees": p.price_rupees,
         "features": p.features}
        for p in rows
    ]
