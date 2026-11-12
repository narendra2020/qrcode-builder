"""
Shared FastAPI dependencies. Access tokens are issued by portfolio-builder
(/api/auth/*) and validated here with the shared JWT secret — there is no
second login system. Every store-scoped route resolves the store through
get_owned_store(), which filters by owner, so changing an id in the URL
can never reach another tenant's store (it 404s, not 403s, to avoid
confirming the id exists).
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.models import Store, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials")
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials")
    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials")
    return user


def get_ghost_admin_id(token: str = Depends(oauth2_scheme)) -> str | None:
    """The admin behind an impersonation (ghost) token, or None for a normal session."""
    try:
        return decode_token(token).get("imp")
    except ValueError:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")
    return current_user


def load_owned_store(store_id: str, user: User, db: Session, for_update: bool = False) -> Store:
    query = db.query(Store).filter(Store.id == store_id, Store.owner_id == user.id)
    if for_update:
        query = query.with_for_update()
    try:
        store = query.first()
    except Exception:  # malformed UUID -> DataError
        db.rollback()
        store = None
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    return store


def get_owned_store(
    store_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Store:
    return load_owned_store(store_id, current_user, db)
