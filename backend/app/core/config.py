"""
Application configuration, loaded from environment variables / .env file.

The QR Store Builder runs as a sibling service of portfolio-builder and
shares its PostgreSQL database, JWT secret and auth endpoints — so
DATABASE_URL / JWT_SECRET_KEY MUST match portfolio-builder's values.
"""
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Shared with portfolio-builder ---
    DATABASE_URL: str = "postgresql+psycopg2://portfolio:changeme@localhost:5433/portfolio_builder_db"
    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    # Admin "ghost login" (manage a store as its owner): token lifetime, no refresh.
    GHOST_SESSION_MINUTES: int = 60

    # HMAC key for short-lived signed URLs to private (unpublished) media.
    MEDIA_SIGNING_KEY: str = "insecure-dev-media-key-change-me"
    MEDIA_URL_TTL_SECONDS: int = 3600

    # --- CORS ---
    ALLOWED_ORIGINS: str = "http://localhost:5175"

    # --- Storage ---
    UPLOADS_DIR: str = "/app/uploads"
    PUBLISHED_SITES_DIR: str = "/app/published_sites"
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    MAX_SOURCE_IMAGES: int = 8
    # Uploaded menu/catalogue photos are deleted this many days after the
    # store is first published (extraction is done by then). 0 disables.
    SOURCE_IMAGE_RETENTION_DAYS: int = 30

    # --- Public URLs ---
    BASE_DOMAIN: str = "mepage.in"
    PUBLIC_SCHEME: str = "https"
    PUBLIC_PORT: str = ""
    MEPAGE_BRAND_URL: str = "https://mepage.in"

    # --- Stores ---
    MAX_STORES_PER_USER: int = 1
    MAX_CATALOGUE_ITEMS: int = 1000
    MAX_CATALOGUE_CATEGORIES: int = 100

    # --- AI (reuses portfolio-builder's provider settings) ---
    LLM_PROVIDER: Literal["anthropic", "azure_openai", "disabled"] = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = ""
    QR_AI_MODEL: str = "claude-opus-5-5"
    # Server-side refusal fallback (Claude API beta). Turn off if your
    # gateway rejects unknown request fields.
    QR_AI_REFUSAL_FALLBACK: bool = True
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    QR_AI_EFFORT: Literal["low", "medium", "high"] = "medium"
    QR_AI_MAX_TOKENS: int = 16000
    AI_TIMEOUT_SECONDS: float = 180.0
    AI_MAX_ATTEMPTS: int = 3
    AI_RETRY_BASE_SECONDS: float = 2.0
    AI_WORKERS: int = 2
    AI_JOB_STALE_MINUTES: int = 15
    AI_CATEGORY_CONFIDENCE_THRESHOLD: float = 0.6
    AI_FIELD_CONFIDENCE_THRESHOLD: float = 0.7
    # Tests run jobs synchronously instead of on the worker pool.
    AI_RUN_INLINE: bool = False

    # --- Plans / quota ---
    QUOTA_TIMEZONE: str = "Asia/Kolkata"
    FREE_PLAN_CODE: str = "free"
    PAID_PLAN_CODE: str = "pro"
    # PaymentRequest.product used with portfolio-builder's billing APIs.
    PAID_PLAN_PRODUCT: str = "qr_store_pro"
    PAID_PLAN_DURATION_DAYS: int = 365
    # Seed values only — admins edit limits afterwards in qr_plans.
    QR_FREE_MONTHLY_UPDATES: int = 5
    QR_PRO_MONTHLY_UPDATES: Optional[int] = None  # None/empty = unlimited
    # Must match portfolio-builder's QR_STORE_PRO_PRICE_RUPEES. 0 = upgrade not offered.
    QR_STORE_PRO_PRICE_RUPEES: int = 0
    # Split Bill only / Pro + Split Bill bundle. Must match portfolio-builder's values.
    QR_SPLIT_BILL_PRICE_RUPEES: int = 0
    QR_PRO_SPLIT_PRICE_RUPEES: int = 0
    SPLIT_PLAN_CODE: str = "split_bill"
    SPLIT_PLAN_PRODUCT: str = "qr_split_bill"
    PRO_SPLIT_PLAN_CODE: str = "pro_split"
    PRO_SPLIT_PLAN_PRODUCT: str = "qr_pro_split"

    # --- Split Bill ---
    SPLIT_BILL_MAX_PARTICIPANTS: int = 20
    SPLIT_BILL_MAX_TOTAL_RUPEES: int = 1_000_000
    SPLIT_BILL_MAX_PER_STORE_PER_DAY: int = 300
    # Bills a store on the free plan may create per calendar month (QUOTA_TIMEZONE). Paid plans are unlimited.
    SPLIT_BILL_FREE_MONTHLY: int = 20
    # One phone number can be invited to at most this many bills per 24h
    # (stops the public form being used to spam a number).
    SPLIT_BILL_MAX_PER_PHONE_PER_DAY: int = 6

    # --- WhatsApp Business Cloud API (optional; same Meta app as portfolio-builder's OTP) ---
    # Business-initiated messages MUST use a pre-approved template, see README.
    # With these unset, Split Bill falls back to click-to-chat links.
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_API_VERSION: str = "v25.0"
    WHATSAPP_SPLIT_BILL_TEMPLATE: str = ""
    WHATSAPP_SPLIT_BILL_TEMPLATE_LANG: str = "en"
    # Number of {{n}} body variables in the approved template: 7 (with a QR link) or 6 (UPI ID only).
    WHATSAPP_SPLIT_BILL_TEMPLATE_VARS: int = 7
    # Set when the approved template has an IMAGE header (used for the payment QR).
    WHATSAPP_SPLIT_BILL_IMAGE_HEADER: bool = False

    # --- Abuse protection ---
    RATE_LIMIT_ENABLED: bool = True
    TRUST_PROXY_HEADERS: bool = True

    @field_validator("QR_PRO_MONTHLY_UPDATES", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return None if v in ("", None) else v

    @property
    def whatsapp_cloud_enabled(self) -> bool:
        return bool(self.WHATSAPP_ACCESS_TOKEN and self.WHATSAPP_PHONE_NUMBER_ID and self.WHATSAPP_SPLIT_BILL_TEMPLATE)

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    def store_host(self, slug: str) -> str:
        return f"{slug}.{self.BASE_DOMAIN}"

    def public_store_url(self, slug: str) -> str:
        port_suffix = f":{self.PUBLIC_PORT}" if self.PUBLIC_PORT else ""
        return f"{self.PUBLIC_SCHEME}://{self.store_host(slug)}{port_suffix}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
