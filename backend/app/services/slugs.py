"""
Store slug (subdomain label) generation, validation and availability.

Slugs share one namespace with portfolio-builder's published_portfolios
(both are served as <slug>.<BASE_DOMAIN> by the same wildcard host), so
availability checks both tables. Uniqueness is ultimately enforced by the
unique index on qr_stores.slug; publish catches the IntegrityError.
"""
import re

from slugify import slugify
from sqlalchemy.orm import Session

from app.models.models import PublishedPortfolio, Store

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
MIN_LEN, MAX_LEN = 3, 63

# System hostnames, infrastructure labels and brand-confusable names.
RESERVED_SLUGS = frozenset("""
www app api admin administrator dashboard static assets cdn media uploads img images files
mail email smtp imap pop ftp sftp ssh vpn ns ns1 ns2 dns mx autodiscover autoconfig webmail
login logout signup signin register auth oauth sso account accounts billing pay payment payments
checkout cart order orders invoice support help docs status blog news about contact terms privacy
legal security abuse root system sys internal test testing dev development staging stage prod
production preview demo sandbox beta alpha localhost host server node web site sites store stores
shop shops qr qrcode qr-code mepage me-page mepagein official verify verification whatsapp wa
portfolio portfolios resume resumes builder default null undefined
""".split())


class SlugError(ValueError):
    pass


def normalize_slug(raw: str) -> str:
    """Lowercase ASCII, hyphens only, collapsed and trimmed, max 63 chars."""
    slug = slugify(raw or "", max_length=MAX_LEN, word_boundary=True, separator="-")
    return slug.strip("-")


def validate_slug(slug: str) -> None:
    if not slug or len(slug) < MIN_LEN:
        raise SlugError("Store address must be at least 3 characters.")
    if len(slug) > MAX_LEN:
        raise SlugError("Store address must be at most 63 characters.")
    if not SLUG_RE.match(slug) or "--" in slug:
        raise SlugError("Use lowercase letters, numbers and single hyphens only (no hyphen at the start or end).")
    if slug in RESERVED_SLUGS or slug.startswith("xn--") or slug.startswith("preview-"):
        raise SlugError("That store address is reserved. Please choose another.")


def is_taken(slug: str, db: Session, exclude_store_id: str | None = None) -> bool:
    query = db.query(Store.id).filter(Store.slug == slug)
    if exclude_store_id:
        query = query.filter(Store.id != exclude_store_id)
    if query.first():
        return True
    return db.query(PublishedPortfolio.id).filter(PublishedPortfolio.slug == slug).first() is not None


def suggest_alternatives(base: str, db: Session, exclude_store_id: str | None = None, count: int = 3) -> list[str]:
    base = normalize_slug(base)[: MAX_LEN - 6] or "my-store"
    if len(base) < MIN_LEN:
        base = f"{base}-store"
    candidates = [f"{base}-store", f"{base}-online", f"the-{base}"] + [f"{base}-{n}" for n in range(2, 30)]
    out: list[str] = []
    for candidate in candidates:
        candidate = candidate[:MAX_LEN].strip("-")
        try:
            validate_slug(candidate)
        except SlugError:
            continue
        if not is_taken(candidate, db, exclude_store_id):
            out.append(candidate)
        if len(out) >= count:
            break
    return out


def check_availability(raw: str, db: Session, exclude_store_id: str | None = None) -> dict:
    slug = (raw or "").strip().lower()
    try:
        validate_slug(slug)
    except SlugError as exc:
        return {"slug": slug, "available": False, "reason": "invalid", "message": str(exc),
                "suggestions": suggest_alternatives(normalize_slug(raw) or "my-store", db, exclude_store_id)}
    if is_taken(slug, db, exclude_store_id):
        return {"slug": slug, "available": False, "reason": "taken",
                "message": "That store address is already taken.",
                "suggestions": suggest_alternatives(slug, db, exclude_store_id)}
    return {"slug": slug, "available": True, "reason": None, "message": None, "suggestions": []}
