import uuid

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.models import SplitBill, SplitBillParticipant, Store
from app.services import payments, publishing, whatsapp_cloud
from app.services.split_bill import mask_phone, split_equally, to_paise
from tests.conftest import make_user

PHONES = ["9876543210", "9876543211", "9876543212", "9876543213"]


def body(total="4000", n=4, key=None, **extra):
    return {"request_id": key or uuid.uuid4().hex, "total": total,
            "participants": [{"name": f"P{i}", "phone": PHONES[i]} for i in range(n)], **extra}


# ------------------------------------------------------------ arithmetic ----

@pytest.mark.parametrize("total,n", [(400000, 4), (100001, 3), (999, 7), (1, 1), (1000000, 20), (10001, 6)])
def test_shares_sum_exactly(total, n):
    shares = split_equally(total, n)
    assert sum(shares) == total and len(shares) == n
    assert max(shares) - min(shares) <= 1


@pytest.mark.parametrize("raw,paise", [("4000", 400000), ("1250.5", 125050), ("0.01", 1), ("1,200", 120000)])
def test_to_paise(raw, paise):
    assert to_paise(raw) == paise


@pytest.mark.parametrize("raw", ["", "abc", "0", "-5", "12.345", "nan", "inf", "99999999"])
def test_to_paise_rejects(raw):
    with pytest.raises(HTTPException):
        to_paise(raw)


def test_mask_phone():
    assert mask_phone("+919876543210") == "+91•••••••210"


# ---------------------------------------------------------- public create ----

def test_create_manual_mode(client, store):
    r = client.post("/api/qr/public/stores/abc/split-bills", json=body())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["total_paise"] == 400000 and d["participant_count"] == 4
    assert [p["share_paise"] for p in d["participants"]] == [100000] * 4
    assert d["delivery_mode"] == "manual" and d["access_token"]
    p0 = d["participants"][0]
    assert p0["wa_link"].startswith("https://wa.me/919876543210?text=")
    assert "abcrestaurant%40upi" in p0["wa_link"] and "%E2%82%B91%2C000" in p0["wa_link"]
    assert p0["upi_link"].startswith("upi://pay?pa=abcrestaurant@upi&") and "am=1000.00" in p0["upi_link"]
    assert p0["status"] == "pending" and "919876543210" not in str(p0["phone_masked"])
    assert d["payment"]["upi_id"] == "abcrestaurant@upi" and d["payment"]["amount_prefilled"] is True


def test_uneven_split_keeps_total(client, store):
    d = client.post("/api/qr/public/stores/abc/split-bills", json=body("1000", 3)).json()
    shares = [p["share_paise"] for p in d["participants"]]
    assert sum(shares) == 100000 and sorted(shares) == [33333, 33333, 33334]


def test_idempotent_replay(client, store, db):
    key = uuid.uuid4().hex
    a = client.post("/api/qr/public/stores/abc/split-bills", json=body(key=key))
    b = client.post("/api/qr/public/stores/abc/split-bills", json=body(key=key))
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"] and a.json()["access_token"] == b.json()["access_token"]
    assert db.query(SplitBill).count() == 1


def test_disabled_or_ineligible_is_hidden(client, store, db):
    store.split_bill_enabled = False
    db.commit()
    assert client.post("/api/qr/public/stores/abc/split-bills", json=body()).status_code == 404
    store.split_bill_enabled, store.category_key = True, "retail"
    db.commit()
    assert client.post("/api/qr/public/stores/abc/split-bills", json=body()).status_code == 404


def test_unpublished_store_404(client, store, db):
    from app.models.models import StoreStatusEnum
    store.status = StoreStatusEnum.unpublished
    db.commit()
    assert client.post("/api/qr/public/stores/abc/split-bills", json=body()).status_code == 404


@pytest.mark.parametrize("mutate", [
    lambda b: b["participants"].__setitem__(1, {"phone": "9876543210"}),     # duplicate number
    lambda b: b["participants"].__setitem__(1, {"phone": "12345"}),          # bad number
    lambda b: b.update(total="0"),
    lambda b: b.update(total="2"),                                           # < ₹1 each
    lambda b: b.update(participants=b["participants"][:1]),                  # single person
    lambda b: b.update(request_id="short"),
])
def test_validation(client, store, mutate):
    b = body()
    mutate(b)
    assert client.post("/api/qr/public/stores/abc/split-bills", json=b).status_code == 422


def test_per_phone_daily_cap(client, store, monkeypatch):
    monkeypatch.setattr(settings, "SPLIT_BILL_MAX_PER_PHONE_PER_DAY", 1)
    assert client.post("/api/qr/public/stores/abc/split-bills", json=body()).status_code == 201
    assert client.post("/api/qr/public/stores/abc/split-bills", json=body()).status_code == 429


def test_status_requires_token(client, store):
    d = client.post("/api/qr/public/stores/abc/split-bills", json=body()).json()
    url = f"/api/qr/public/split-bills/{d['id']}"
    assert client.get(url).status_code == 404
    assert client.get(url, headers={"X-Split-Token": "x" * 40}).status_code == 404
    assert client.get(url, headers={"X-Split-Token": d["access_token"]}).status_code == 200
    assert client.get("/api/qr/public/split-bills/not-a-uuid", headers={"X-Split-Token": d["access_token"]}).status_code == 404


# ----------------------------------------------------------- cloud sending ----

@pytest.fixture()
def cloud(monkeypatch):
    for k, v in dict(WHATSAPP_ACCESS_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="1", WHATSAPP_SPLIT_BILL_TEMPLATE="split_bill").items():
        monkeypatch.setattr(settings, k, v)
    sent = []
    fail = set()

    def fake(to, params, header_image_url=None):
        sent.append((to, params))
        if to in fail:
            return whatsapp_cloud.SendResult(False, error="WhatsApp couldn't deliver the message.", retryable=True)
        return whatsapp_cloud.SendResult(True, message_id=f"wamid.{len(sent)}")

    monkeypatch.setattr(whatsapp_cloud, "send_split_bill", fake)
    return sent, fail


def test_cloud_sends_once_and_retries_only_failures(client, store, cloud, db):
    sent, fail = cloud
    fail.add("+919876543211")
    d = client.post("/api/qr/public/stores/abc/split-bills", json=body()).json()   # background runs in TestClient
    assert d["delivery_mode"] == "cloud_api" and len(sent) == 4
    assert sent[0][1][:6] == ["P0", "ABC Restaurant", "₹4,000", "4", "₹1,000", "abcrestaurant@upi"]

    url = f"/api/qr/public/split-bills/{d['id']}"
    hdr = {"X-Split-Token": d["access_token"]}
    s = client.get(url, headers=hdr).json()
    assert [p["notification_status"] for p in s["participants"]] == ["sent", "failed", "sent", "sent"]
    assert s["participants"][1]["status"] == "notification_failed" and s["participants"][1]["wa_link"]
    assert s["retryable"] is True

    fail.clear()
    assert client.post(url + "/notify", headers=hdr).status_code == 202
    assert len(sent) == 5 and sent[-1][0] == "+919876543211"          # only the failed one re-sent
    s = client.get(url, headers=hdr).json()
    assert all(p["notification_status"] == "sent" for p in s["participants"]) and s["retryable"] is False
    assert client.post(url + "/notify", headers=hdr).status_code == 409   # nothing left to retry
    assert len(sent) == 5


def test_replay_does_not_resend(client, store, cloud):
    sent, _ = cloud
    key = uuid.uuid4().hex
    client.post("/api/qr/public/stores/abc/split-bills", json=body(key=key))
    client.post("/api/qr/public/stores/abc/split-bills", json=body(key=key))
    assert len(sent) == 4


def test_retry_cap(client, store, cloud, db):
    sent, fail = cloud
    fail.add("+919876543211")
    d = client.post("/api/qr/public/stores/abc/split-bills", json=body()).json()
    url, hdr = f"/api/qr/public/split-bills/{d['id']}/notify", {"X-Split-Token": d["access_token"]}
    codes = [client.post(url, headers=hdr).status_code for _ in range(6)]
    assert codes[:4] == [202] * 4 and 409 in codes
    assert db.query(SplitBillParticipant).filter_by(phone="+919876543211").one().notification_attempts == 5


def test_sender_builds_template_payload(monkeypatch):
    for k, v in dict(WHATSAPP_ACCESS_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="1", WHATSAPP_SPLIT_BILL_TEMPLATE="split_bill",
                     WHATSAPP_SPLIT_BILL_IMAGE_HEADER=True).items():
        monkeypatch.setattr(settings, k, v)
    captured = {}

    class R:
        status_code = 200
        def json(self): return {"messages": [{"id": "wamid.X"}]}

    class C:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, json, headers): captured.update(url=url, json=json, headers=headers); return R()

    monkeypatch.setattr(whatsapp_cloud.httpx, "Client", C)
    res = whatsapp_cloud.send_split_bill("+919876543210", ["Rahul", "ABC\nRestaurant"], "https://x/qr.png")
    assert res.ok and res.message_id == "wamid.X"
    j = captured["json"]
    assert j["to"] == "919876543210" and j["template"]["name"] == "split_bill"
    assert j["template"]["components"][0]["type"] == "header"
    assert j["template"]["components"][1]["parameters"][1]["text"] == "ABC Restaurant"   # newline stripped


# ------------------------------------------------------------ merchant side ----

def test_owner_marks_payment_and_isolation(client, store, db, Session):
    d = client.post("/api/qr/public/stores/abc/split-bills", json=body()).json()
    pid = d["participants"][0]["id"]
    # A message alone never confirms anything.
    owner_view = client.get(f"/api/qr/stores/{store.id}/split-bills/{d['id']}").json()
    assert owner_view["paid_count"] == 0 and owner_view["outstanding_paise"] == 400000

    url = f"/api/qr/stores/{store.id}/split-bills/{d['id']}/participants/{pid}/payment"
    r = client.put(url, json={"status": "confirmed"})
    assert r.status_code == 200 and r.json()["paid_count"] == 1 and r.json()["confirmed_paise"] == 100000
    assert r.json()["participants"][0]["status"] == "payment_confirmed"
    assert client.put(url, json={"status": "pending"}).json()["paid_count"] == 0
    assert client.put(url, json={"status": "paid"}).status_code == 422

    listing = client.get(f"/api/qr/stores/{store.id}/split-bills").json()
    assert listing["total"] == 1 and "participants" in listing["bills"][0]

    # Another merchant cannot see or touch this store's bills.
    other = make_user(db, "+919876500002", "Other")
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: other
    assert client.get(f"/api/qr/stores/{store.id}/split-bills").status_code == 404
    assert client.put(url, json={"status": "confirmed"}).status_code == 404


# ---------------------------------------------------------- dashboard config ----

def test_enable_requires_payment_method(client, db, owner):
    s = Store(owner_id=owner.id, name="Cafe", slug="cafe", category_key="restaurant", branding={}, currency="INR")
    db.add(s)
    db.commit()
    r = client.put(f"/api/qr/stores/{s.id}/payment", json={"split_bill_enabled": True})
    assert r.status_code == 422 and "UPI" in str(r.json())
    r = client.put(f"/api/qr/stores/{s.id}/payment", json={"split_bill_enabled": True, "upi_id": "cafe@okhdfc"})
    assert r.status_code == 200 and r.json()["payment"]["split_bill"]["active"] is True
    # Can't strip the last payment method while enabled.
    assert client.put(f"/api/qr/stores/{s.id}/payment", json={"upi_id": ""}).status_code == 422
    assert client.put(f"/api/qr/stores/{s.id}/payment", json={"split_bill_enabled": False, "upi_id": ""}).status_code == 200


@pytest.mark.parametrize("upi", ["nope", "a@", "@bank", "a b@bank", "x@y", "a@bank&pa=evil@x", "a@b@c"])
def test_upi_validation(client, store, upi):
    assert client.put(f"/api/qr/stores/{store.id}/payment", json={"upi_id": upi}).status_code == 422


def test_ineligible_category_cannot_enable(client, db, owner):
    s = Store(owner_id=owner.id, name="Shop", slug="shop", category_key="retail", branding={}, currency="INR", upi_id="a@upi")
    db.add(s)
    db.commit()
    assert client.put(f"/api/qr/stores/{s.id}/payment", json={"split_bill_enabled": True}).status_code == 422


def test_storefront_shows_option_only_when_enabled(db, store):
    html = publishing.render_html(store, db, mode="preview")
    assert 'id="split-open"' in html and "Want to split the bill with friends?" in html
    assert '"splitBill"' in html and "/api/qr/public/stores/abc/split-bills" in html
    assert "abcrestaurant@upi" not in html            # payment details never in the static page
    store.split_bill_enabled = False
    db.commit()
    off = publishing.render_html(store, db, mode="preview")
    assert 'id="split-open"' not in off and "Want to split the bill" not in off and 'id="split"' not in off


def test_payment_upload_validation(client, store):
    r = client.post(f"/api/qr/stores/{store.id}/payment/qr", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 422


def test_six_variable_template(client, store, cloud, monkeypatch):
    sent, _ = cloud
    monkeypatch.setattr(settings, "WHATSAPP_SPLIT_BILL_TEMPLATE_VARS", 6)
    client.post("/api/qr/public/stores/abc/split-bills", json=body())
    assert len(sent) == 4 and all(len(params) == 6 for _, params in sent)
    assert sent[0][1][5] == "abcrestaurant@upi"
