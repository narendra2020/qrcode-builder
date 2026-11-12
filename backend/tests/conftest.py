"""Test fixtures: an in-memory SQLite database standing in for PostgreSQL."""
import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("UPLOADS_DIR", "/tmp/qr-test-uploads")
os.environ.setdefault("PUBLISHED_SITES_DIR", "/tmp/qr-test-sites")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.db import session as db_session
from app.db.session import Base, get_db
from app.main import app
from app.models.models import Store, StoreStatusEnum, User


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture()
def Session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    # Background dispatch opens its own session via SessionLocal.
    monkeypatch.setattr("app.services.split_bill.SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def db(Session):
    s = Session()
    yield s
    s.close()


def make_user(db, mobile="+919876500001", name="Owner"):
    u = User(mobile_number_encrypted=mobile, full_name=name)
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def owner(db):
    return make_user(db)


@pytest.fixture()
def store(db, owner):
    s = Store(owner_id=owner.id, name="ABC Restaurant", slug="abc", status=StoreStatusEnum.published,
              category_key="restaurant", template_key="menu-classic", branding={}, currency="INR",
              upi_id="abcrestaurant@upi", split_bill_enabled=True)
    db.add(s)
    db.commit()
    return s


@pytest.fixture()
def client(Session, owner):
    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: owner
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
