"""
Pydantic request models. Responses are plain dicts built by the services
(store_out / catalogue_out / job_out ...) to keep one serializer per entity.
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StoreCreateIn(_In):
    name: Optional[str] = Field(default=None, max_length=120)


class StoreUpdateIn(_In):
    """Partial update; only fields present are changed."""
    name: Optional[str] = Field(default=None, max_length=120)
    slug: Optional[str] = Field(default=None, max_length=63)
    category_key: Optional[str] = Field(default=None, max_length=50)
    template_key: Optional[str] = Field(default=None, max_length=50)
    tagline: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    address_line: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    postal_code: Optional[str] = Field(default=None, max_length=20)
    country: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=25)
    whatsapp_number: Optional[str] = Field(default=None, max_length=25)
    email: Optional[str] = Field(default=None, max_length=255)
    opening_hours: Optional[str] = Field(default=None, max_length=500)
    maps_url: Optional[str] = Field(default=None, max_length=500)
    zomato_url: Optional[str] = Field(default=None, max_length=500)
    swiggy_url: Optional[str] = Field(default=None, max_length=500)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    onboarding_step: Optional[Literal["upload", "category", "business", "template", "catalogue", "branding", "review", "done"]] = None


class TableCodeIn(_In):
    table_no: str = Field(min_length=1, max_length=30)


class CatalogueSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: Optional[int] = None
    categories: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


class ImportIn(_In):
    mode: Literal["replace", "append"] = "replace"


class BrandingIn(_In):
    primary: Optional[str] = None
    secondary: Optional[str] = None
    background: Optional[str] = None
    text: Optional[str] = None
    font: Optional[str] = None
    logo_media_id: Optional[str] = None
    banner_media_id: Optional[str] = None
    tagline: Optional[str] = Field(default=None, max_length=160)
    reset: bool = False


class WhatsappProofIn(_In):
    proof_token: str = Field(max_length=2000)


class SourceOrderIn(_In):
    media_ids: list[str]


class EventIn(BaseModel):
    slug: str = Field(max_length=63)
    kind: Literal["view", "item_enquiry", "cart_enquiry"]


class PlanUpdateIn(_In):
    name: Optional[str] = Field(default=None, max_length=60)
    description: Optional[str] = None
    monthly_catalogue_updates: Optional[int] = Field(default=None, ge=0)
    unlimited: bool = False
    price_rupees: Optional[int] = Field(default=None, ge=0)
    features: Optional[list[str]] = None
    is_active: Optional[bool] = None


class GrantIn(_In):
    user_id: str
    plan_code: str
    valid_until: Optional[str] = None  # ISO date/datetime; null = no expiry
    note: Optional[str] = Field(default=None, max_length=255)


class SuspendIn(_In):
    reason: str = Field(min_length=3, max_length=255)


class PaymentIn(_In):
    upi_id: Optional[str] = Field(default=None, max_length=100)
    split_bill_enabled: Optional[bool] = None


class SplitParticipantIn(_In):
    name: Optional[str] = Field(default=None, max_length=60)
    phone: str = Field(min_length=5, max_length=25)


class SplitBillIn(_In):
    request_id: str = Field(min_length=16, max_length=64)  # client-generated; makes retries idempotent
    total: str = Field(min_length=1, max_length=14)         # rupees, e.g. "4000" or "1250.50"
    table_no: Optional[str] = Field(default=None, max_length=30)
    participants: list[SplitParticipantIn] = Field(min_length=2, max_length=50)


class PaymentStatusIn(_In):
    status: Literal["pending", "confirmed"]
