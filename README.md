# MePage QR Store Builder

Small businesses photograph their menu or price list. AI pulls out the items and prices, the owner checks them, picks a design and publishes. They get a store at `https://<store>.mepage.in` and a QR code with MePage branding. Customers browse on their phone and send enquiries to the store's WhatsApp, either about one item or as a list.

It runs **as a sibling service of `portfolio-builder/`** and reuses that service's pieces instead of duplicating them:

| Concern | Reused from portfolio-builder |
|---|---|
| Signup, login, WhatsApp OTP, sessions, refresh rotation, logout | `/api/auth/*` (same users, same tokens: the JWT secret is shared) |
| Verifying a *different* business WhatsApp number | New `/api/auth/number-verification/*` built on the same OTP table, provider and limits |
| AI provider | Same `LLM_PROVIDER` / `ANTHROPIC_*` / `AZURE_OPENAI_*` settings |
| Payments / upgrades | `/api/billing/*` (Razorpay signature-verified or admin-reviewed UPI) with new product `qr_store_pro` |
| Database | Same PostgreSQL. This service owns only `qr_*` tables, with its own Alembic version table |
| Hosting | Same `published_sites` directory and wildcard `*.BASE_DOMAIN` host that serves portfolio sites |
| Audit log, design tokens, admin roles | `audit_logs`, `global.css`, `admin` / `super_admin` roles |

---

## Local development (Docker)

```bash
cd deploy
# Optional: put secrets in deploy/.env (git-ignored), e.g.
#   ANTHROPIC_API_KEY=...        QR_STORE_PRO_PRICE_RUPEES=499
docker compose -f docker-compose.local.yml up --build
```

| URL | What |
|---|---|
| http://localhost:5175 | Store Builder owner app (sign up with any 10-digit number; dev OTP `123456`) |
| http://localhost:8002/api/qr/health | QR backend health |
| http://`<slug>`.localhost:8081 | Published storefronts (no DNS setup needed, since `*.localhost` resolves locally) |

Without an AI key, set `QR_LLM_PROVIDER=disabled`. The upload step then shows a clear "add items manually" message, and the rest of the flow still works.

### Native (no Docker)
```bash
# portfolio-builder must be running and migrated first (it owns `users`).
cd qrcode-builder/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # match DATABASE_URL / JWT_SECRET_KEY to portfolio-builder
alembic upgrade head && python -m app.db.seed
uvicorn app.main:app --reload --port 8002

cd ../frontend && npm install && npm run dev     # http://localhost:5175
```

---

## Architecture

```
 Owner app (React, :5175) ──/api/qr/*──► qr-backend (FastAPI)
        │                                   │  ├─ ai/       per-page multimodal extraction jobs (thread pool, DB-tracked)
        └──/api/auth,/api/billing──►        │  ├─ services/ stores, catalogue, plans/quota, publishing, qr, slugs, media, whatsapp
           portfolio-backend                │  └─ templates/storefront/  5 Jinja designs + shared store.js/store.css
                    │                       ▼
                    └──────────► PostgreSQL (users … + qr_* tables)
                                            │ publish
                                            ▼
                          PUBLISHED_SITES_DIR/<slug>/index.html, assets/   ◄── Nginx  *.mepage.in (wildcard TLS)
                                            ▲                                   └─ /api/qr/public/* → anonymous counters
                               Customer phone (QR scan) ──► WhatsApp click-to-chat (wa.me)
```

**Key decisions**
- **Structured catalogue, rendered statically.** The AI fills `qr_catalogue_items`. It never writes HTML. Publishing renders those rows through the chosen template into a static site, so switching designs never re-runs the AI, and customer traffic never touches the API. Writes are atomic: the site is rendered into a temp dir and then swapped in.
- **One AI pass per page.** It returns category evidence, business details read verbatim from the page, and the items. The server then re-checks everything: a numeric price is accepted only if that exact number appears in the printed price text, and anything unclear is flagged `needs_review`. Publishing is blocked until the owner has reviewed every flagged item.
- **Background jobs** run on an in-process thread pool (the platform has no queue broker). They are durable through the DB: per-page progress, heartbeats, explicit timeouts, exponential-backoff retries for transient errors only, retry of failed pages only, and recovery of stale jobs at startup.
- **Templates are data.** `app/catalog/registry.py` lists the categories (terminology, icons, recommended designs, AI cues) and the templates. Adding one is a registry entry plus a Jinja file; the wizard and API need no changes.
- **Multi-store ready.** `qr_stores.owner_id` is not unique. `MAX_STORES_PER_USER` (default 1) controls the limit, and a `custom_domain` column is reserved.

### Storefront designs
| Key | For | Character |
|---|---|---|
| `menu-classic` | Restaurants, grocery | Printed-menu rows, dotted price leaders, veg/non-veg marks, sticky section tabs |
| `cafe-cards` | Cafés, bakeries, salons | Photo-first rounded cards, 2-column on phones |
| `boutique-elegant` | Wedding, fashion, jewellery | Serif type, tall portrait cards, gold rules |
| `auto-showroom` | Automobile, electronics | Bold band, wide 16:9 cards, spec/option chips, call strip |
| `retail-grid` | Any shop | Search + dense grid, cart-first |

Items without a photo show the category's icon on a neutral tile, never a stock photo that could be mistaken for the real product. If the AI finds a product photo printed in the catalogue, it is cropped out and used.

---

## Policies

### Catalogue update quota
- **Counted:** one successful save of a **published** store's catalogue (items and categories). One save counts as one update, however many items it changes.
- **Not counted:** anything before the first publish (onboarding, AI import, the first publish itself), saves that change nothing, failed or rejected saves, previews, reads, branding, design, store-info edits, and customer actions.
- **Period:** calendar month in **Asia/Kolkata**. The count resets at 00:00 IST on the 1st. It is tracked per store.
- **Enforcement:** server-side, inside the save transaction, under a `SELECT … FOR UPDATE` lock on the store and its counter, so concurrent saves are serialised. A blocked save returns `402 quota_exceeded`, and the editor keeps the unsaved changes locally.
- **Plans** live in `qr_plans`, and admins can edit them. Free is 5 per month and Pro is unlimited by default (`NULL` = unlimited). The active plan comes from an admin grant, or from an **approved** `payment_requests` row with product `qr_store_pro` (valid `PAID_PLAN_DURATION_DAYS`). A pending claim never unlocks anything.

### WhatsApp
- **Item enquiry:** `https://wa.me/<number>?text=…` carrying the item name, its price (or "price not listed") and the store URL.
- **List enquiry:** numbered lines with each quantity and unit price. An *estimated* subtotal appears only when every line has an exact price, and it is labelled "to be confirmed by the store".
- **Long lists:** URLs over 2000 characters are shortened to the first N items plus a "…and M more" note, and the customer is warned before sending.
- The customer always presses **Send** in WhatsApp themselves. The UI says so and never claims an order was placed. Counters store only daily totals: no IP addresses, cookies or message text.
- **Enquiry number:** the owner's verified login number by default. A different number must pass a WhatsApp OTP first, which issues a signed proof token valid for 15 minutes.

### Split Bill (restaurants, cafés, bakeries, food outlets)
Optional per store; only categories with `supports_split_bill` (currently "Restaurant, café & bakery") can enable it.

- **Merchant:** dashboard → *Split Bill* tab. Set a **UPI ID** and/or upload a **payment QR** (stored on the store, entered once), then flip the switch. The switch refuses to turn on without a payment method, a store name and INR currency. Switching off removes the option from the published page immediately. The tab also lists recent bills; **only the merchant can mark a participant "Payment confirmed"**.
- **Customer:** the storefront shows *"Want to split the bill with friends?"* → details (total, 2–20 people, WhatsApp numbers, optional names) → review → confirm → per-person amounts, UPI ID with *Copy*, an *Open UPI app* link with the amount pre-filled, and the QR. With only a static QR the screen says the amount must be typed.
- **Rounding:** money is integer paise; leftover paise go one each to the first participants, so shares always sum exactly to the total.
- **Statuses:** per participant, *Pending*, *Payment Confirmed* (merchant-only) and *Notification Failed*. "Sent" means WhatsApp accepted the message, never that anyone paid.
- **Safety:** creating a bill is idempotent per request id (retries never re-send); only failed messages are retried (max 5 attempts each, atomically claimed); per-IP, per-store and per-phone daily caps stop the public form being used to spam; phone numbers are masked in every API response and never logged; payment details are never written into the static site.

**WhatsApp setup (optional).** Without it, the customer gets a *Send on WhatsApp* click-to-chat button per person (prefilled message; they press Send). For automatic sending, create and get approved a WhatsApp Business **utility template** (default language `en`) and set `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_SPLIT_BILL_TEMPLATE` (+ `_LANG`). Body, with seven variables in this order:

```
Hi {{1}}, you've been invited to split a bill at {{2}}.

Total bill: {{3}}
Number of people: {{4}}
Your share: {{5}}

Pay {{5}} to UPI ID {{6}}, or use the payment QR: {{7}}

This message does not confirm payment. Thank you!
```
{{1}} name (or "there"), {{2}} restaurant, {{3}} total, {{4}} people, {{5}} share, {{6}} UPI ID (or "the payment QR code"), {{7}} QR image link (or the UPI pay link when there is no QR). If your approved template has only `{{1}}`–`{{6}}` (no QR-link line), set `WHATSAPP_SPLIT_BILL_TEMPLATE_VARS=6`: `{{6}}` is then the UPI ID, or the QR link when a store has no UPI ID. If the template has an **image header**, set `WHATSAPP_SPLIT_BILL_IMAGE_HEADER=true` and the merchant's QR is attached. Meta fetches that image from the store's own host (`https://<slug>.<BASE_DOMAIN>/api/qr/public/split-bills/<id>/payment-qr`), so `/api/qr/` must be routed on the wildcard host (it already is for storefront counters).

### Store addresses
- Lowercase letters, digits and single hyphens, 3–63 characters.
- Reserved names (`www`, `api`, `admin`, `mail`, …) and `xn--` / `preview-` prefixes are rejected.
- An address must be unique across **both** QR stores and portfolio sites, since they share one wildcard namespace. Taken names get suggested alternatives.
- The address is **locked after the first publish** so printed QR codes keep working. Admins can handle exceptions.

### Security & privacy
- Every owner route resolves the store through `owner_id`. Another tenant's id returns 404, not 403.
- Uploads are decoded with Pillow, which enforces pixel and size limits, fixes EXIF orientation and **re-encodes** the file, stripping metadata and any appended payload.
- Media is never served statically. Owners get HMAC-signed links that expire, and a published site gets its own copies at publish time.
- Rate limits: per user on uploads, AI and writes, and per IP on public endpoints. These run in-process, plus Nginx `limit_req` in production.
- Logs are structured JSON with a correlation `X-Request-ID`. No OTPs, tokens, phone numbers or message contents are logged. Errors return generic messages.
- Templates are autoescaped, and store data is embedded with `|tojson`. Previews run in a sandboxed iframe without same-origin access.
- Bearer-token auth (`localStorage`, as in portfolio-builder) is not vulnerable to CSRF. CORS is restricted to the owner app's origin.
- **Retention:** run `python -m app.db.cleanup` daily (cron). It deletes source menu photos `SOURCE_IMAGE_RETENTION_DAYS` (30) days after first publish, plus orphaned images.

---

## Production deployment (`deploy/`)

1. **DNS:** an `A` record for `mepage.in`, `*.mepage.in` (wildcard, needed for every store) and `stores.mepage.in` (owner app), all pointing to the server. Check that the wildcard resolves before go-live.
2. **TLS:** a **wildcard** Let's Encrypt certificate via DNS-01 (`deploy/setup-ssl.sh`, IAM policy `iam-policy-route53-dns01.json`). HTTP-01 cannot issue wildcards.
3. **Env:** `cp deploy/.env.prod.example deploy/.env` and fill in the QR section:
   - `QR_SHARED_JWT_SECRET` must equal portfolio-backend's `JWT_SECRET_KEY`.
   - Set `QR_STORE_PRO_PRICE_RUPEES` on **both** backends.
   - Also replace the hard-coded portfolio-backend secrets in the compose files with `${…}` references.
4. **Nginx:** install `deploy/nginx-host.conf`. It adds the `stores.` server block, the `limit_req` zones and the `/api/qr/public/` proxy on the wildcard block. The wildcard root must point at the directory mounted as `PUBLISHED_SITES_DIR` (`./data/portfolio-sites`).
5. `docker compose -f docker-compose.prod.yml up -d --build`. Migration order is handled for you: qr-backend retries until portfolio-backend has migrated.
6. **Cron:** `docker compose exec qr-backend python -m app.db.cleanup` daily, and include `./data/qr-uploads` in `backup.sh`.
7. **Scaling:** AI jobs run in-process. Keep `--workers 1` per container, or move jobs to a queue before scaling out (see limitations).

### Migrations
- `qrcode-builder/backend/alembic/versions/q1a_qr_store_builder.py` creates all `qr_*` tables. Its version table is `alembic_version_qr`.
- `portfolio-builder/backend/alembic/versions/q3f5a7c9e1b2_otp_purpose_number_verification.py` adds `otp_transactions.purpose` and `requested_by_user_id`.

---

## API summary (`/api/qr`, bearer token from `/api/auth`)

| Method & path | Purpose |
|---|---|
| `GET /meta`, `GET /plans` | Categories, templates, fonts, labels; plans and upgrade info |
| `GET/POST /stores`, `GET/PATCH /stores/{id}` | List, create, read, update a store |
| `GET /stores/{id}/slug-availability`, `/slug-suggestion` | Live address check and suggestion |
| `POST /stores/{id}/whatsapp/verify` | Apply a number-verification proof token |
| `POST/DELETE/PUT /stores/{id}/sources[...]` | Upload, remove, reorder menu photos |
| `POST /stores/{id}/analysis[/retry]`, `GET /analysis` | Start, retry and poll AI extraction |
| `GET/PUT /stores/{id}/catalogue`, `POST /catalogue/import` | Read, save (bulk, versioned, quota-enforced), import AI results |
| `POST /stores/{id}/media` | Item image, logo or banner upload (optional crop) |
| `PUT /stores/{id}/branding` | Colours, font, logo, banner, tagline |
| `GET /stores/{id}/templates`, `GET /preview?template=` | Gallery and exact HTML preview |
| `POST /stores/{id}/publish`, `/unpublish` | Publish (server-validated) or take down |
| `GET /stores/{id}/qr?format=png\|svg&layout=card\|plain&size=digital\|print` | Branded QR download |
| `PUT /stores/{id}/payment`, `POST/DELETE /stores/{id}/payment/qr` | UPI ID, Split Bill switch, payment QR |
| `GET /stores/{id}/split-bills[/{bill}]`, `PUT .../participants/{p}/payment` | Merchant bill list; mark a payment confirmed/pending |
| `POST /public/stores/{slug}/split-bills`, `GET /public/split-bills/{id}`, `POST .../notify` | Customer: create (idempotent), poll, retry failed sends (`X-Split-Token` capability) |
| `GET /stores/{id}/usage`, `/activity` | Quota usage and 30-day counters |
| `GET /public/resolve`, `POST /public/events`, `GET /media/file/...` | Host resolution, anonymous counters, signed media |
| `/admin/*` | Store lookup, suspend/restore, plan limits, grants, failed jobs + retry, diagnostics |

portfolio-builder additions: `POST /api/auth/number-verification/start|confirm`, and billing product `qr_store_pro` (enabled when `QR_STORE_PRO_PRICE_RUPEES > 0`).

---

## Testing status

Split Bill has a pytest suite (`backend/tests`, run `pytest` from `backend/`; it uses in-memory SQLite, so PostgreSQL-specific behaviour such as row locks and the enum migration is **not** covered). The rest of the service has no automated tests and has not been run. Before release, at minimum:
- run `alembic upgrade head` on a PostgreSQL copy and exercise Split Bill with real WhatsApp credentials (template approval, QR header image, a number that isn't on WhatsApp);
- check that the backend imports (`python -m compileall app`) and the frontend builds (`npm run build`);
- run the end-to-end journey against a test database with a mocked or disabled AI provider;
- check that QR codes scan on real phones (the server also decodes every PNG it generates);
- check WhatsApp hand-off on Android, iOS and WhatsApp Web;
- check that a sixth catalogue save in a month is blocked and that concurrent saves stay within the limit.

## Known limitations
- AI jobs run in a thread pool inside the API process. A restart marks running jobs as failed (retryable). For several API instances, move `ai/jobs.run_job` to a real queue.
- Rate limits are per process. Nginx `limit_req` provides the global limit.
- Storefronts are static: a catalogue save re-renders the whole site, which is fine up to `MAX_CATALOGUE_ITEMS` (1000). Very large catalogues would need pagination or a dynamic renderer.
- Only Indian (+91) login numbers are supported, because portfolio-builder's signup is India-only. Business WhatsApp numbers can be international.
- Custom domains are modelled (`custom_domain`) but not routed or certified yet.
- Activity counts measure taps that opened WhatsApp, not delivered messages. 
