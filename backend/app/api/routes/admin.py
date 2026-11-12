"""
Admin operations (admin / super_admin of the shared MePage platform):
store lookup, suspend / restore, quota inspection, plan configuration,
plan grants, AI job failures and service diagnostics. Every mutating
action is audited.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.ai import jobs
from app.ai.providers import AiError, get_analyzer
from app.api.deps import get_ghost_admin_id, get_current_user, require_admin
from app.core.config import settings
from app.core.security import create_ghost_token
from app.db.session import get_db
from app.models.models import (
    AuditLog,
    CatalogueRevision,
    ExtractionJob,
    JobStatusEnum,
    Plan,
    PlanGrant,
    Store,
    StoreStatusEnum,
    User,
)
from app.schemas import GrantIn, PlanUpdateIn, SuspendIn
from app.services import plans, publishing, stores
from app.services.audit import audit

router = APIRouter(prefix="/api/qr/admin", tags=["qr-admin"])


@router.get("/stores")
def list_stores(
    q: str | None = Query(None, max_length=100),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Store).join(User, Store.owner_id == User.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Store.name.ilike(like), Store.slug.ilike(like), User.full_name.ilike(like)))
    if status_filter:
        try:
            query = query.filter(Store.status == StoreStatusEnum(status_filter))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown status")
    total = query.count()
    rows = query.order_by(Store.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "stores": [
            {**stores.store_summary(s), "owner": {"id": s.owner.id, "name": s.owner.full_name},
             "used_this_month": plans.used_this_period(s.id, db), "plan": plans.resolve_plan(s.owner, db)[0].code}
            for s in rows
        ],
    }


@router.get("/stores/{store_id}")
def store_detail(store_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    revisions = (
        db.query(CatalogueRevision).filter(CatalogueRevision.store_id == store.id)
        .order_by(CatalogueRevision.created_at.desc()).limit(50).all()
    )
    history = (
        db.query(AuditLog)
        .filter(AuditLog.action.like("qr.%"), AuditLog.meta["store_id"].astext == store.id)
        .order_by(AuditLog.created_at.desc()).limit(100).all()
    )
    job = jobs.latest_job(store.id, db)
    return {
        **stores.store_summary(store),
        "owner": {"id": store.owner.id, "name": store.owner.full_name},
        "suspended_reason": store.suspended_reason,
        "usage": plans.usage_summary(store, db),
        "item_count": len(store.items),
        "job": jobs.job_out(job),
        "revisions": [{"at": r.created_at, "counted": r.counted, "period": r.period, "plan": r.plan_code,
                       "summary": r.summary} for r in revisions],
        "audit": [{"at": a.created_at, "action": a.action, "actor_id": a.actor_id, "meta": a.meta} for a in history],
    }


@router.post("/stores/{store_id}/suspend")
def suspend_store(store_id: str, payload: SuspendIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).with_for_update().first()
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    publishing.remove_site(store.slug)
    store.status, store.suspended_reason = StoreStatusEnum.suspended, payload.reason
    audit(db, admin.id, "qr.admin.store_suspended", store_id=store.id, reason=payload.reason)
    db.commit()
    return stores.store_summary(store)


@router.post("/stores/{store_id}/restore")
def restore_store(store_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    store = db.query(Store).filter(Store.id == store_id).with_for_update().first()
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    if store.status != StoreStatusEnum.suspended:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Store is not suspended.")
    store.status, store.suspended_reason = StoreStatusEnum.unpublished, None
    audit(db, admin.id, "qr.admin.store_restored", store_id=store.id)
    db.commit()
    return stores.store_summary(store)


@router.get("/plans")
def admin_plans(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(Plan).order_by(Plan.display_order).all()
    return [{"code": p.code, "name": p.name, "description": p.description,
             "monthly_catalogue_updates": p.monthly_catalogue_updates, "price_rupees": p.price_rupees,
             "features": p.features, "is_active": p.is_active} for p in rows]


@router.put("/plans/{code}")
def update_plan(code: str, payload: PlanUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    plan = db.get(Plan, code)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    data = payload.model_dump(exclude_unset=True)
    before = {"monthly_catalogue_updates": plan.monthly_catalogue_updates, "price_rupees": plan.price_rupees}
    if data.pop("unlimited", False):
        plan.monthly_catalogue_updates = None
    elif "monthly_catalogue_updates" in data:
        plan.monthly_catalogue_updates = data.pop("monthly_catalogue_updates")
    for key, value in data.items():
        setattr(plan, key, value)
    audit(db, admin.id, "qr.admin.plan_updated", plan=code, before=before,
          after={"monthly_catalogue_updates": plan.monthly_catalogue_updates, "price_rupees": plan.price_rupees})
    db.commit()
    return {"code": plan.code, "monthly_catalogue_updates": plan.monthly_catalogue_updates}


@router.post("/grants", status_code=status.HTTP_201_CREATED)
def grant_plan(payload: GrantIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not db.get(User, payload.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not db.get(Plan, payload.plan_code):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    valid_until = None
    if payload.valid_until:
        try:
            valid_until = datetime.fromisoformat(payload.valid_until)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "valid_until must be an ISO date.")
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
    grant = PlanGrant(user_id=payload.user_id, plan_code=payload.plan_code, valid_until=valid_until,
                      granted_by=admin.id, note=payload.note)
    db.add(grant)
    db.flush()
    audit(db, admin.id, "qr.admin.plan_granted", user_id=payload.user_id, plan=payload.plan_code,
          valid_until=valid_until.isoformat() if valid_until else None, grant_id=grant.id)
    db.commit()
    return {"id": grant.id}


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    grant = db.get(PlanGrant, grant_id)
    if not grant or grant.revoked_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    grant.revoked_at = datetime.now(timezone.utc)
    audit(db, admin.id, "qr.admin.plan_revoked", grant_id=grant.id, user_id=grant.user_id)
    db.commit()
    return {"ok": True}


@router.get("/jobs")
def failed_jobs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.status.in_([JobStatusEnum.failed, JobStatusEnum.partial]))
        .order_by(ExtractionJob.created_at.desc()).limit(100).all()
    )
    return [{**jobs.job_out(j), "store_id": j.store_id, "provider": j.provider, "model": j.model} for j in rows]


@router.post("/jobs/{job_id}/retry")
def admin_retry(job_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    job = db.get(ExtractionJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    store = db.get(Store, job.store_id)
    job = jobs.retry_job(store, db)
    audit(db, admin.id, "qr.admin.job_retried", store_id=store.id, job_id=job.id)
    db.commit()
    return jobs.job_out(job)


@router.get("/diagnostics")
def diagnostics(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    counts = dict(db.query(Store.status, func.count()).group_by(Store.status).all())
    job_counts = dict(db.query(ExtractionJob.status, func.count()).group_by(ExtractionJob.status).all())
    try:
        analyzer = get_analyzer()
        ai = {"configured": True, "provider": analyzer.provider, "model": analyzer.model}
    except AiError as exc:
        ai = {"configured": False, "message": exc.message}
    return {
        "stores": {k.value: v for k, v in counts.items()},
        "jobs": {k.value: v for k, v in job_counts.items()},
        "ai": ai,
        "quota_timezone": settings.QUOTA_TIMEZONE,
        "current_period": plans.current_period(),
        "base_domain": settings.BASE_DOMAIN,
        "upgrade_price_configured": settings.QR_STORE_PRO_PRICE_RUPEES > 0,
    }


# ---------------------------------------------------------- ghost login ----

@router.post("/stores/{store_id}/ghost-login")
def ghost_login(store_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db),
                imp: str | None = Depends(get_ghost_admin_id)):
    """Lets an admin manage a store as its owner. Issues a short-lived owner token that
    carries the admin in `imp` (no refresh token). Every audit event written during the
    session is stamped `impersonated_by`. Admin accounts can't be impersonated."""
    if imp:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Exit the current ghost session first.")
    store = db.get(Store, store_id)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    owner = store.owner
    if owner.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin accounts can't be impersonated.")
    if not owner.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "This owner's account is deactivated.")
    audit(db, admin.id, "qr.admin.ghost_login_started", store_id=store.id, owner_id=owner.id)
    db.commit()
    return {
        "access_token": create_ghost_token(owner.id, owner.role, admin.id),
        "expires_in": settings.GHOST_SESSION_MINUTES * 60,
        "store_id": store.id,
        "user": {"id": owner.id, "full_name": owner.full_name, "role": owner.role, "is_active": owner.is_active},
    }


@router.post("/ghost-exit")
def ghost_exit(user: User = Depends(get_current_user), imp: str | None = Depends(get_ghost_admin_id),
               db: Session = Depends(get_db)):
    """Called with the ghost token when the admin leaves, to close the audit trail."""
    if not imp:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a ghost session.")
    audit(db, imp, "qr.admin.ghost_login_ended", owner_id=user.id)
    db.commit()
    return {"ok": True}
