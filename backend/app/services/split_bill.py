"""
Split Bill: equal split of a restaurant bill, WhatsApp invitations, and
merchant-confirmed payment tracking.

Invariants
- Money is integer paise; shares always sum exactly to the total (the
  remainder paise go one each to the first participants).
- Creating a bill is idempotent per (store, request id): a retry returns
  the original bill and never sends a second round of messages.
- A message is sent to a participant at most once per successful claim
  (atomic UPDATE ... WHERE status IN (pending, failed)), so concurrent
  retries can't double-send.
- "sent" means accepted by WhatsApp. A payment is "confirmed" ONLY when the
  merchant marks it — a message, link click or QR scan proves nothing.
- Public responses never include other people's full numbers or any
  merchant secret; the UPI ID/QR are shown because that is the point.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger, log_event
from app.db.session import SessionLocal
from app.models.models import SplitBill, SplitBillParticipant, Store
from app.services import payments, plans, whatsapp_cloud
from app.services.audit import audit
from app.services.whatsapp import PhoneError, normalize_phone, split_bill_message, wa_link

logger = get_logger("split_bill")

MAX_SEND_ATTEMPTS = 5
SENDING_STALE = timedelta(minutes=5)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _err(field: str | None, message: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, {"field": field, "message": message} if field else {"message": message})


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- arithmetic ----

def to_paise(raw) -> int:
    """'4000', '1234.5' -> paise. Rejects NaN/inf, >2 decimals, non-positive and over-limit amounts."""
    try:
        value = Decimal(str(raw).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise _err("total", "Enter the bill amount as a number, like 4000 or 1250.50.")
    if not value.is_finite():
        raise _err("total", "Enter a valid bill amount.")
    if value != value.quantize(Decimal("0.01")):
        raise _err("total", "Use at most 2 decimal places.")
    if value <= 0:
        raise _err("total", "The bill amount must be more than ₹0.")
    if value > settings.SPLIT_BILL_MAX_TOTAL_RUPEES:
        raise _err("total", f"The bill amount can be at most ₹{settings.SPLIT_BILL_MAX_TOTAL_RUPEES:,}.")
    return int(value * 100)


def split_equally(total_paise: int, people: int) -> list[int]:
    """Equal shares in paise that sum exactly to total_paise."""
    base, remainder = divmod(total_paise, people)
    return [base + 1 if i < remainder else base for i in range(people)]


def mask_phone(e164: str) -> str:
    return e164[:3] + "•" * max(len(e164) - 6, 3) + e164[-3:]


# ------------------------------------------------------------------ token ----

def access_token(bill_id: str) -> str:
    """Capability for the creating customer. Derived (not stored) so an
    idempotent replay can hand it back after a lost response."""
    return hmac.new(settings.JWT_SECRET_KEY.encode(), f"split-bill|{bill_id}".encode(), hashlib.sha256).hexdigest()[:40]


def load_bill_with_token(bill_id: str, token: str | None, db: Session) -> SplitBill:
    try:
        bill = db.get(SplitBill, bill_id)
    except Exception:  # malformed UUID
        db.rollback()
        bill = None
    if not bill or not token or not hmac.compare_digest(access_token(bill.id), token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Split bill not found")
    return bill


# ----------------------------------------------------------------- create ----

def _clean_participants(raw: list[dict]) -> list[dict]:
    seen, out = set(), []
    for idx, p in enumerate(raw):
        label = f"participants.{idx}"
        try:
            phone = normalize_phone(p.get("phone") or "")
        except PhoneError as exc:
            raise _err(f"{label}.phone", str(exc))
        if phone in seen:
            raise _err(f"{label}.phone", "This number is already in the list.")
        seen.add(phone)
        name = _CTRL.sub("", (p.get("name") or "")).strip()[:60] or None
        out.append({"name": name, "phone": phone})
    return out


def _new_code(db: Session) -> str:
    for _ in range(10):
        code = "SB-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not db.query(SplitBill.id).filter(SplitBill.code == code).first():
            return code
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Please try again.")


def create_split_bill(store: Store, data: dict, db: Session) -> tuple[SplitBill, bool]:
    """Returns (bill, created). created=False means an idempotent replay."""
    if not payments.split_bill_active(store):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Split Bill isn't available at this store.")
    key = data["request_id"]
    if not _KEY_RE.match(key or ""):
        raise _err("request_id", "Invalid request.")

    existing = db.query(SplitBill).filter(SplitBill.store_id == store.id, SplitBill.idempotency_key == key).first()
    if existing:
        return existing, False

    total = to_paise(data["total"])
    people = _clean_participants(data["participants"])
    n = len(people)
    if not 2 <= n <= settings.SPLIT_BILL_MAX_PARTICIPANTS:
        raise _err("participants", f"Split between 2 and {settings.SPLIT_BILL_MAX_PARTICIPANTS} people.")
    if total < n * 100:
        raise _err("total", f"Each person's share must be at least ₹1 — the total must be at least ₹{n}.")

    # Free-plan monthly allowance. Lock the store row so concurrent creates can't both slip under the limit.
    db.query(Store.id).filter(Store.id == store.id).with_for_update().one()
    usage = plans.split_bill_usage(store, db)
    if not usage["unlimited"] and usage["used"] >= usage["limit"]:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, {
            "code": "split_bill_limit",
            "message": "This store has reached its monthly Split Bill limit. Please ask the staff to split the bill.",
        })

    since = _now() - timedelta(hours=24)
    if db.query(func.count(SplitBill.id)).filter(SplitBill.store_id == store.id, SplitBill.created_at >= since).scalar() \
            >= settings.SPLIT_BILL_MAX_PER_STORE_PER_DAY:
        raise _err(None, "This store has reached today's split-bill limit. Please ask the staff for help.",
                   status.HTTP_429_TOO_MANY_REQUESTS)
    for p in people:
        recent = db.query(func.count(SplitBillParticipant.id)).filter(
            SplitBillParticipant.phone == p["phone"], SplitBillParticipant.created_at >= since).scalar()
        if recent >= settings.SPLIT_BILL_MAX_PER_PHONE_PER_DAY:
            raise _err(None, f"{mask_phone(p['phone'])} has received too many split-bill requests today. "
                             "Please remove this number or try again tomorrow.", status.HTTP_429_TOO_MANY_REQUESTS)

    mode = whatsapp_cloud.delivery_mode()
    table_no = " ".join((data.get("table_no") or "").split())[:30] or None
    bill = SplitBill(
        code=_new_code(db), store_id=store.id, idempotency_key=key, total_paise=total, participant_count=n,
        currency=store.currency, table_no=table_no, upi_id=store.upi_id,
        payment_qr_media_id=store.payment_qr_media_id, delivery_mode=mode,
    )
    for i, (p, share) in enumerate(zip(people, split_equally(total, n))):
        bill.participants.append(SplitBillParticipant(
            position=i, name=p["name"], phone=p["phone"], share_paise=share,
            notification_status="pending" if mode == "cloud_api" else "manual",
        ))
    db.add(bill)
    try:
        db.flush()
    except IntegrityError:  # lost an idempotency race
        db.rollback()
        existing = db.query(SplitBill).filter(SplitBill.store_id == store.id, SplitBill.idempotency_key == key).first()
        if existing:
            return existing, False
        raise
    audit(db, None, "qr.split_bill.created", store_id=store.id, split_bill_id=bill.id, people=n,
          total_paise=total, mode=mode)
    db.commit()
    db.refresh(bill)
    return bill, True


# ------------------------------------------------------------- messaging ----

def qr_path(bill: SplitBill) -> str | None:
    return f"/api/qr/public/split-bills/{bill.id}/payment-qr" if bill.payment_qr_media_id else None


def _qr_url(store: Store, bill: SplitBill) -> str | None:
    path = qr_path(bill)
    return f"{settings.public_store_url(store.slug)}{path}" if path else None


def _upi_link(store: Store, bill: SplitBill, p: SplitBillParticipant) -> str | None:
    if not bill.upi_id or bill.currency != "INR":
        return None
    return payments.upi_link(bill.upi_id, store.name or "Restaurant", p.share_paise, f"Split bill {bill.code}")


def _text(store: Store, bill: SplitBill, p: SplitBillParticipant) -> str:
    return split_bill_message(
        name=p.name, store_name=store.name or "the restaurant", total_label=payments.money(bill.total_paise, bill.currency),
        people=bill.participant_count, share_label=payments.money(p.share_paise, bill.currency),
        upi_id=bill.upi_id, upi_link=_upi_link(store, bill, p), qr_url=_qr_url(store, bill),
    )


def _claim(db: Session, participant_id: str) -> bool:
    """Atomically takes the right to send to one participant."""
    stale = _now() - SENDING_STALE
    res = db.execute(
        update(SplitBillParticipant)
        .where(SplitBillParticipant.id == participant_id,
               SplitBillParticipant.notification_attempts < MAX_SEND_ATTEMPTS,
               or_(SplitBillParticipant.notification_status.in_(("pending", "failed")),
                   and_(SplitBillParticipant.notification_status == "sending",
                        SplitBillParticipant.last_attempt_at < stale)))
        .values(notification_status="sending", last_attempt_at=_now(),
                notification_attempts=SplitBillParticipant.notification_attempts + 1)
    )
    db.commit()
    return res.rowcount == 1


def dispatch_notifications(bill_id: str) -> None:
    """Background task: sends each unsent invitation through the Cloud API.
    Uses its own DB session; every participant is committed independently."""
    db = SessionLocal()
    try:
        bill = db.get(SplitBill, bill_id)
        if not bill or bill.delivery_mode != "cloud_api":
            return
        store = db.get(Store, bill.store_id)
        qr_url = _qr_url(store, bill)
        total_label = payments.money(bill.total_paise, bill.currency)
        for p in list(bill.participants):
            if not _claim(db, p.id):
                continue
            db.refresh(p)
            share_label = payments.money(p.share_paise, bill.currency)
            link = _upi_link(store, bill, p)
            if settings.WHATSAPP_SPLIT_BILL_TEMPLATE_VARS >= 7:
                payment = [bill.upi_id or "the payment QR code", qr_url or link or "-"]
            else:  # 6-variable template: {{6}} is the UPI ID, or the QR link when the store has no UPI ID
                payment = [bill.upi_id or qr_url or "-"]
            params = [p.name or "there", store.name or "the restaurant", total_label, str(bill.participant_count),
                      share_label, *payment]
            try:
                result = whatsapp_cloud.send_split_bill(p.phone, params, header_image_url=qr_url)
            except Exception:
                logger.exception("split bill send crashed")
                result = whatsapp_cloud.SendResult(False, error="Something went wrong sending this message.")
            p.notification_status = "sent" if result.ok else "failed"
            p.notification_error = None if result.ok else (result.error or "Delivery failed")[:200]
            p.provider_message_id = result.message_id
            db.commit()
            log_event(logger, "split_bill.notified", split_bill_id=bill.id, participant_id=p.id, ok=result.ok)
    except Exception:
        logger.exception("dispatch_notifications failed")
        db.rollback()
    finally:
        db.close()


def retry_candidates(bill: SplitBill) -> list[SplitBillParticipant]:
    return [p for p in bill.participants
            if p.notification_status in ("pending", "failed") and p.notification_attempts < MAX_SEND_ATTEMPTS]


# ---------------------------------------------------------------- output ----

def display_status(p: SplitBillParticipant) -> str:
    if p.payment_status == "confirmed":
        return "payment_confirmed"
    if p.notification_status == "failed":
        return "notification_failed"
    return "pending"


def _summary(bill: SplitBill) -> dict:
    confirmed = [p for p in bill.participants if p.payment_status == "confirmed"]
    return {
        "paid_count": len(confirmed),
        "confirmed_paise": sum(p.share_paise for p in confirmed),
        "outstanding_paise": bill.total_paise - sum(p.share_paise for p in confirmed),
    }


def public_out(bill: SplitBill, store: Store, token: str | None = None) -> dict:
    """What the customer who created the bill sees."""
    out = {
        "id": bill.id, "code": bill.code, "restaurant": store.name, "currency": bill.currency,
        "total_paise": bill.total_paise, "participant_count": bill.participant_count,
        "created_at": bill.created_at, "delivery_mode": bill.delivery_mode,
        "payment": {
            "upi_id": bill.upi_id, "qr_url": qr_path(bill),
            # With only a static QR the amount can't be prefilled — say so.
            "amount_prefilled": bool(bill.upi_id and bill.currency == "INR"),
            "note": None if bill.upi_id else
            "This restaurant's QR code can't prefill the amount. Enter your exact share before paying.",
        },
        "notifications_in_progress": any(p.notification_status in ("pending", "sending") for p in bill.participants)
        and bill.delivery_mode == "cloud_api",
        "retryable": len(retry_candidates(bill)) > 0 and bill.delivery_mode == "cloud_api"
        and any(p.notification_status == "failed" for p in bill.participants),
        "participants": [],
        "payment_note": "Payments are confirmed by the restaurant — a message or QR scan alone doesn't confirm payment.",
    }
    for p in bill.participants:
        item = {
            "id": p.id, "name": p.name, "phone_masked": mask_phone(p.phone), "share_paise": p.share_paise,
            "notification_status": p.notification_status, "notification_error": None,
            "status": display_status(p), "upi_link": _upi_link(store, bill, p),
        }
        if p.notification_status in ("manual", "failed"):
            item["wa_link"] = wa_link(p.phone, _text(store, bill, p))
        out["participants"].append(item)
    if token:
        out["access_token"] = token
    return out


def owner_out(bill: SplitBill, detail: bool = True) -> dict:
    out = {
        "id": bill.id, "code": bill.code, "total_paise": bill.total_paise, "currency": bill.currency,
        "participant_count": bill.participant_count, "table_no": bill.table_no,
        "created_at": bill.created_at, "delivery_mode": bill.delivery_mode, **_summary(bill),
    }
    if detail:
        out["participants"] = [{
            "id": p.id, "name": p.name, "phone_masked": mask_phone(p.phone), "share_paise": p.share_paise,
            "notification_status": p.notification_status, "notification_error": p.notification_error,
            "payment_status": p.payment_status, "status": display_status(p),
            "payment_confirmed_at": p.payment_confirmed_at,
        } for p in bill.participants]
    return out


# ------------------------------------------------------ merchant actions ----

def set_payment_status(store: Store, bill_id: str, participant_id: str, new_status: str, user_id: str, db: Session) -> SplitBill:
    try:
        p = (db.query(SplitBillParticipant).join(SplitBill)
             .filter(SplitBillParticipant.id == participant_id, SplitBill.id == bill_id, SplitBill.store_id == store.id)
             .with_for_update(of=SplitBillParticipant).first())
    except Exception:
        db.rollback()
        p = None
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Participant not found")
    if p.payment_status != new_status:
        p.payment_status = new_status
        p.payment_confirmed_at = _now() if new_status == "confirmed" else None
        p.payment_confirmed_by = user_id if new_status == "confirmed" else None
        audit(db, user_id, "qr.split_bill.payment_marked", store_id=store.id, split_bill_id=bill_id,
              participant_id=p.id, status=new_status)
    db.commit()
    return db.get(SplitBill, bill_id)
