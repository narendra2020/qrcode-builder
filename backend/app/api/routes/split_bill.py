"""
Split Bill APIs.

owner_router  — merchant dashboard (authenticated, tenant-scoped through
                load_owned_store): payment settings, bill list, and the only
                place a payment can be marked confirmed.
public_router — customer storefront (unauthenticated): create a bill, poll
                it, retry failed WhatsApp sends. Customers prove ownership of
                a bill with the capability token returned at creation.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_owned_store, load_owned_store
from app.api.routes.public import published_store
from app.api.routes.stores import upload_limit, write_limit
from app.core.config import settings
from app.core.ratelimit import limit_by_ip
from app.db.session import get_db
from app.models.models import Media, MediaKindEnum, SplitBill, Store, User
from app.schemas import PaymentIn, PaymentStatusIn, SplitBillIn
from app.services import media as media_service
from app.services import payments, split_bill, stores
from app.services.audit import audit

owner_router = APIRouter(prefix="/api/qr", tags=["qr-split-bill"])
public_router = APIRouter(prefix="/api/qr/public", tags=["qr-split-bill-public"])


# ------------------------------------------------------------ owner ----

@owner_router.put("/stores/{store_id}/payment")
def update_payment(store_id: str, payload: PaymentIn, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = payments.update_payment(store, current_user, payload.model_dump(exclude_unset=True), db)
    return stores.store_out(store, db)


@owner_router.post("/stores/{store_id}/payment/qr")
def upload_payment_qr(store_id: str, file: UploadFile = File(...), current_user: User = Depends(upload_limit),
                      db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    raw = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    store = payments.set_payment_qr(store, current_user, raw, db)
    return stores.store_out(store, db)


@owner_router.delete("/stores/{store_id}/payment/qr")
def delete_payment_qr(store_id: str, current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    store = load_owned_store(store_id, current_user, db, for_update=True)
    store = payments.remove_payment_qr(store, current_user, db)
    return stores.store_out(store, db)


@owner_router.get("/stores/{store_id}/split-bills")
def list_split_bills(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                     store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    q = db.query(SplitBill).filter(SplitBill.store_id == store.id)
    total = q.count()
    rows = q.order_by(SplitBill.created_at.desc()).offset(offset).limit(limit).all()
    return {"total": total, "bills": [split_bill.owner_out(b) for b in rows]}


def _owned_bill(store: Store, bill_id: str, db: Session) -> SplitBill:
    try:
        bill = db.query(SplitBill).filter(SplitBill.id == bill_id, SplitBill.store_id == store.id).first()
    except Exception:  # malformed UUID
        db.rollback()
        bill = None
    if not bill:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Split bill not found")
    return bill


@owner_router.get("/stores/{store_id}/split-bills/{bill_id}")
def get_split_bill(bill_id: str, store: Store = Depends(get_owned_store), db: Session = Depends(get_db)):
    return split_bill.owner_out(_owned_bill(store, bill_id, db))


@owner_router.put("/stores/{store_id}/split-bills/{bill_id}/participants/{participant_id}/payment")
def mark_payment(store_id: str, bill_id: str, participant_id: str, payload: PaymentStatusIn,
                 current_user: User = Depends(write_limit), db: Session = Depends(get_db)):
    """The only way a payment becomes 'confirmed': the merchant says so."""
    store = load_owned_store(store_id, current_user, db)
    bill = split_bill.set_payment_status(store, bill_id, participant_id, payload.status, current_user.id, db)
    return split_bill.owner_out(bill)


# ----------------------------------------------------------- public ----

@public_router.post("/stores/{slug}/split-bills", status_code=status.HTTP_201_CREATED,
                    dependencies=[Depends(limit_by_ip("split-create", 8, 3600))])
def create_split_bill(slug: str, payload: SplitBillIn, response: Response, background: BackgroundTasks,
                      db: Session = Depends(get_db)):
    store = published_store(slug[:63], db)
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    bill, created = split_bill.create_split_bill(store, payload.model_dump(), db)
    if created and bill.delivery_mode == "cloud_api":
        background.add_task(split_bill.dispatch_notifications, bill.id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return split_bill.public_out(bill, store, split_bill.access_token(bill.id))


@public_router.get("/split-bills/{bill_id}", dependencies=[Depends(limit_by_ip("split-read", 240, 60))])
def read_split_bill(bill_id: str, x_split_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    bill = split_bill.load_bill_with_token(bill_id, x_split_token, db)
    return Response(
        content=_json(split_bill.public_out(bill, db.get(Store, bill.store_id))),
        media_type="application/json", headers={"Cache-Control": "no-store"},
    )


@public_router.post("/split-bills/{bill_id}/notify", dependencies=[Depends(limit_by_ip("split-retry", 12, 3600))])
def retry_notifications(bill_id: str, background: BackgroundTasks, x_split_token: str | None = Header(default=None),
                        db: Session = Depends(get_db)):
    """Re-sends ONLY participants whose message failed; sent ones are never repeated."""
    bill = split_bill.load_bill_with_token(bill_id, x_split_token, db)
    if bill.delivery_mode != "cloud_api":
        raise HTTPException(status.HTTP_409_CONFLICT, "Automatic WhatsApp messages aren't enabled for this bill.")
    if not any(p.notification_status == "failed" for p in bill.participants):
        raise HTTPException(status.HTTP_409_CONFLICT, "There are no failed messages to retry.")
    if not split_bill.retry_candidates(bill):
        raise HTTPException(status.HTTP_409_CONFLICT, "We've retried as many times as we can. Use the WhatsApp links to send manually.")
    audit(db, None, "qr.split_bill.retry", store_id=bill.store_id, split_bill_id=bill.id)
    db.commit()
    background.add_task(split_bill.dispatch_notifications, bill.id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@public_router.get("/split-bills/{bill_id}/payment-qr", include_in_schema=False,
                   dependencies=[Depends(limit_by_ip("split-qr", 120, 60))])
def payment_qr(bill_id: str, db: Session = Depends(get_db)):
    """The merchant's payment QR as captured on this bill. The bill id is an
    unguessable UUID shared with the people invited to pay."""
    try:
        bill = db.get(SplitBill, bill_id)
    except Exception:
        db.rollback()
        bill = None
    media = db.get(Media, bill.payment_qr_media_id) if bill and bill.payment_qr_media_id else None
    if not media or media.store_id != bill.store_id or media.kind != MediaKindEnum.payment_qr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    try:
        path = media_service.abs_path(media.path)
    except media_service.MediaError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


def _json(data: dict) -> bytes:
    from fastapi.encoders import jsonable_encoder
    import json
    return json.dumps(jsonable_encoder(data)).encode()
