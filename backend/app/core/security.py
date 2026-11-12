"""
JWT verification (tokens are issued by portfolio-builder's auth service,
signed with the shared JWT_SECRET_KEY) and HMAC-signed media URLs.
"""
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


def create_ghost_token(owner_id: str, role: str, admin_id: str) -> str:
    """Short-lived access token for `owner_id` carrying the impersonating admin in `imp`.
    No refresh token is issued, so a ghost session can never outlive its expiry."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.GHOST_SESSION_MINUTES)
    return jwt.encode({"sub": owner_id, "role": role, "type": "access", "imp": admin_id, "exp": exp},
                      settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _media_sig(rel_path: str, exp: int) -> str:
    msg = f"{rel_path}|{exp}".encode()
    return hmac.new(settings.MEDIA_SIGNING_KEY.encode(), msg, hashlib.sha256).hexdigest()


def sign_media_path(rel_path: str, ttl: int | None = None) -> tuple[int, str]:
    exp = int(time.time()) + (ttl or settings.MEDIA_URL_TTL_SECONDS)
    return exp, _media_sig(rel_path, exp)


def verify_media_signature(rel_path: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(_media_sig(rel_path, exp), sig)
