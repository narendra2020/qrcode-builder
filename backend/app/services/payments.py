"""
Merchant payment details (UPI ID + payment QR) and the Split Bill switch.

These are stored once on the store and reused by every feature that needs
to tell a customer how to pay. Nothing here is ever written into the
published static site — customers only receive it through the Split Bill
API after they start a bill.
"""
import re
from urllib.parse import quote

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.catalog.registry import get_category
from app.models.models import Media, MediaKindEnum, SplitBill, Store, User
from app.services import media as media_service
from app.services import plans, publishing, qr
from app.services.audit import audit
from app.services.whatsapp import format_price

# name@handle — the NPCI VPA grammar is loose; this rejects anything that could
# break out of a upi:// query string or look like a different scheme.
UPI_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}@[a-zA-Z][a-zA-Z0-9]{1,31}$")


def _err(field: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"field": field, "message": message})


def split_bill_eligible(store: Store) -> bool:
    return get_category(store.category_key).supports_split_bill


def has_payment_method(store: Store) -> bool:
    return bool(store.upi_id or store.payment_qr_media_id)


def split_bill_blocker(store: Store) -> str | None:
    """Why Split Bill can't be switched on right now (None = it can)."""
    if not split_bill_eligible(store):
        return "Split Bill is available for restaurants, cafés, bakeries and other food businesses."
    if not store.name:
        return "Add your store name first."
    if store.currency != "INR":
        return "Split Bill uses UPI, so your store currency must be INR."
    if not has_payment_method(store):
        return "Add your UPI ID or upload your payment QR code first."
    return None


def split_bill_active(store: Store) -> bool:
    """Whether the customer-facing option should be shown/accepted."""
    return bool(store.split_bill_enabled) and split_bill_blocker(store) is None


def upi_link(upi_id: str, payee: str, amount_paise: int, note: str) -> str:
    """Amount-prefilled UPI deep link. Payee address (`pa`) is always the
    merchant's configured UPI ID, verbatim."""
    amount = f"{amount_paise // 100}.{amount_paise % 100:02d}"
    return (f"upi://pay?pa={quote(upi_id, safe='@._-')}&pn={quote(payee[:40], safe='')}"
            f"&am={amount}&cu=INR&tn={quote(note[:40], safe='')}")


def payment_qr_media(store: Store, db: Session) -> Media | None:
    if not store.payment_qr_media_id:
        return None
    return db.query(Media).filter(Media.id == store.payment_qr_media_id, Media.store_id == store.id,
                                  Media.kind == MediaKindEnum.payment_qr, Media.deleted_at.is_(None)).first()


def payment_out(store: Store, db: Session) -> dict:
    from app.services.whatsapp_cloud import delivery_mode

    media = payment_qr_media(store, db)
    detected = None
    if media:
        try:
            for text in qr.decode_png(media_service.read_bytes(media)):
                m = re.match(r"^upi://pay\?(.*)$", text, re.I)
                if m:
                    pa = dict(p.split("=", 1) for p in m.group(1).split("&") if "=" in p).get("pa")
                    if pa:
                        detected = pa.replace("%40", "@")
                    break
        except Exception:  # decoding is a best-effort hint only
            detected = None
    return {
        "upi_id": store.upi_id,
        "qr": media_service.media_out(media),
        "qr_upi_hint": detected if detected and detected != store.upi_id else None,
        "split_bill": {
            "enabled": bool(store.split_bill_enabled),
            "active": split_bill_active(store),
            "eligible": split_bill_eligible(store),
            "blocker": split_bill_blocker(store),
            "delivery_mode": delivery_mode(),
            "usage": plans.split_bill_usage(store, db),
        },
    }


def update_payment(store: Store, user: User, data: dict, db: Session) -> Store:
    """Partial update of upi_id / split_bill_enabled. Validates the resulting
    state as a whole so Split Bill can never be left on without a way to pay."""
    if "upi_id" in data:
        value = (data["upi_id"] or "").strip()
        if value and not UPI_RE.match(value):
            raise _err("upi_id", "Enter a valid UPI ID like name@bank.")
        store.upi_id = value or None
    if "split_bill_enabled" in data and data["split_bill_enabled"] is not None:
        store.split_bill_enabled = bool(data["split_bill_enabled"])

    if store.split_bill_enabled:
        blocker = split_bill_blocker(store)
        if blocker:
            field = "upi_id" if "payment" in blocker or "UPI" in blocker else "split_bill_enabled"
            raise _err(field, blocker)
    db.flush()
    audit(db, user.id, "qr.payment.updated", store_id=store.id, split_bill=store.split_bill_enabled,
          has_upi=bool(store.upi_id), has_qr=bool(store.payment_qr_media_id))
    publishing.refresh_live_site(store, db)
    db.commit()
    db.refresh(store)
    return store


def _retire_media(media: Media | None, db: Session) -> None:
    """Remove a replaced QR image — unless an existing bill still shows it."""
    if not media:
        return
    in_use = db.query(SplitBill.id).filter(SplitBill.payment_qr_media_id == media.id).first()
    if in_use:
        from datetime import datetime, timezone
        media.deleted_at = datetime.now(timezone.utc)
    else:
        media_service.delete_files(media)
        db.delete(media)


def set_payment_qr(store: Store, user: User, raw: bytes, db: Session) -> Store:
    old = payment_qr_media(store, db)
    try:
        media = media_service.save_image(db, store.id, raw, MediaKindEnum.payment_qr)
    except media_service.MediaError as exc:
        db.rollback()
        raise _err("payment_qr", str(exc))
    store.payment_qr_media_id = media.id
    db.flush()
    _retire_media(old, db)
    audit(db, user.id, "qr.payment.qr_uploaded", store_id=store.id)
    db.commit()
    db.refresh(store)
    return store


def remove_payment_qr(store: Store, user: User, db: Session) -> Store:
    if store.split_bill_enabled and not store.upi_id:
        raise _err("payment_qr", "Split Bill needs a payment method. Add your UPI ID or switch Split Bill off first.")
    old = payment_qr_media(store, db)
    store.payment_qr_media_id = None
    db.flush()
    _retire_media(old, db)
    audit(db, user.id, "qr.payment.qr_removed", store_id=store.id)
    db.commit()
    db.refresh(store)
    return store


def money(paise: int, currency: str = "INR") -> str:
    from decimal import Decimal
    return format_price(Decimal(paise) / 100, currency) or ""
