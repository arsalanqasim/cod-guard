# Merchant platform

Set `COD_GUARD_DATABASE_URL` to enable merchant mode on the FastAPI process.
For the current exhibition and operator-provisioned shadow pilot, use the
[single-host guide](HOSTING.md). Merchant mode provides email-verified
accounts, staff invitations, roles, browser-based channel setup, and workers
for voice review, storefront sync, buyer verification, and courier outcomes.
Deploy the API behind HTTPS with request-body and credential-bearing URL
logging disabled. Environment-backed account settings serve the SQLite pilot.
Merchant accounts configure connections through the portal.

## Provision the database and application

1. Create a dedicated PostgreSQL database, a migration login with schema
   creation rights, and an ordinary login for the API and workers. Grant the
   runtime login database connection access. Provision the schema with
   `python scripts/platform_database.py --runtime-role <runtime-login>`
   using `COD_GUARD_MIGRATION_DATABASE_URL` in the migration environment.
2. Set `COD_GUARD_DATABASE_URL` to the runtime login's DSN in the API and
   worker environments. Use TLS when connecting to a remote database.
   Tenant data uses row-level security. Runtime queries set the active tenant
   within each transaction.
3. Set `COD_GUARD_DATA_KEYS` in the secret manager as a keyring with an
   active ID and 32-byte Base64-encoded keys, for example
   `{"active":"v1","keys":{"v1":"<base64 key>"}}`. Add a new ID to rotate
   future writes and retain prior keys for reads and backup restoration.
   Buyer name, phone, city, traffic attribution, reply text, and voice job
   payloads use authenticated encryption. Back up keys separately from
   database snapshots.
4. Set `COD_GUARD_AUTH_KEY` to a stable, independently generated secret
   of at least 43 characters (for example, `secrets.token_urlsafe(32)`).
   This key binds normalized email addresses to accounts and invitations.
   Keep it with the recovery configuration. Set
   `COD_GUARD_PORTAL_ORIGINS` to a comma-separated list of exact HTTPS
   origins. Set the SMTP host and sender, with credentials where required.
   The application uses STARTTLS. Trust forwarded client IPs only from the
   deployment proxy so per-IP send limits use the right address.
5. Run the API with `uvicorn backend.app.main:app --no-access-log`.
   Keep the API and standalone portal on the same HTTPS origin where
   possible. Browser writes require an allowed `Origin`. Send the code
   received by email and the browser's challenge cookie to complete sign-in.

## Merchant API

The React portal lives in [frontend/portal](../frontend/portal). Run
`npm ci` and `npm run dev` there with Node 22. Vite proxies
`/api/*` to the FastAPI app on port 8000. Set `COD_GUARD_API_PROXY`
in the Vite environment to use a different local API address. Add
`http://localhost:5173` as a portal origin for local development.
For production, run `npm run build`, serve `frontend/portal/dist`
over HTTPS, and reverse proxy `/api/*` to FastAPI with the prefix
removed. Use the portal's exact HTTPS origin in the API configuration.

The standalone portal supports account setup and team invitations, CSV and
connected order sources, order triage, storefront conflict review, verification
and outcomes. It refreshes the queue, order detail, and connection status
while open.

| Route | Purpose |
| --- | --- |
| `POST /auth/email/start` | Send a one-time code to an email address |
| `POST /auth/email/complete` | Exchange the code for a session. New owners supply `store_name`, invited staff supply `invitation` |
| `GET /auth/session` | Load the active merchant and available memberships |
| `POST /auth/session/tenant` | Switch to one of the signed-in user's merchants |
| `DELETE /auth/session` | Revoke the browser session |
| `POST /auth/invitations` | Invite an `ops` or `packer` as the active merchant's owner |

Owners and operations staff use the existing order, CSV, and verification
routes. Packers can list and open explicitly approved, conflict-free
orders awaiting shipment. The packing response includes order, product,
city, and quantity. Buyer contact and verification actions require an
operations or owner role. Exports of retained buyer replies require an
owner. The portal API reads the tenant from the verified session.

## Background workers

Set `COD_GUARD_REDIS_URL` for workers and API processes. Use an isolated,
authenticated Redis instance or namespace with TLS for remote transport.
The API uses Redis for shared rate limiting when configured. On the Linux
worker host, provision the offline Whisper cache and start these processes
under a supervisor.

```text
celery -A backend.app.worker:app worker -Q control --concurrency=1 --hostname=control@%h
celery -A backend.app.worker:app worker -Q voice --concurrency=2 --hostname=voice@%h
celery -A backend.app.worker:app worker -Q integrations --concurrency=2 --hostname=integrations@%h
celery -A backend.app.worker:app beat
```

Run one Beat instance. Voice uploads create a PostgreSQL job for the
merchant and requesting operator. The relay sends identifiers through
Redis and retries outstanding work after a lost broker delivery or expired
worker lease. Workers clear uploaded audio on completion and purge expired
jobs and results. The API returns a transcript for review. The operator
saves a decision separately. Monitor control and voice worker health,
old queued jobs, repeated lease expiry, and PostgreSQL backup restore.

## Connect providers

Rerun the database provisioning command when upgrading a previously provisioned
merchant database. Set `COD_GUARD_PUBLIC_API_BASE` to the externally reachable
HTTPS API base (for example, `https://portal.example.com/api`). Set the same value
for API processes and workers. The owner manages settings under **Connections**.

### Shopify and WooCommerce

- Configure the Shopify app client ID and secret in the platform secret manager.
  Register `<public API base>/providers/shopify/oauth` for standalone OAuth and
  route `/shopify/app` to the FastAPI HTML entry on the portal origin for Shopify
  Admin. Serve the Vite build assets from the same portal origin. The embedded
  view uses App Bridge and Polaris and pairs a Shopify user through a short-lived
  code issued to a COD-Guard owner. Merchant OAuth and App Bridge use expiring
  offline tokens. Verify the exact COD gateway name, requested fulfillment scopes,
  webhook setup, and protected customer data access in a Shopify development
  store before configuring write-back.
- WooCommerce authorization uses the site's native application authorization
  page. The owner approves REST access and COD-Guard registers order webhooks and
  schedules catch-up polls. Enable order hold or release and private outcome
  notes in the connection's write-back settings. Keep credentials in Basic auth.
- Enable fulfillment holds per store after testing the workflow. Shopify release
  targets the COD-Guard hold IDs only. WooCommerce release checks that COD-Guard
  placed the hold. Keep an operator process to review outstanding holds when
  switching off enforcement.
- In the Shopify Dev Dashboard or app configuration, subscribe
  `customers/data_request`, `customers/redact`, and `shop/redact` to
  `<public API base>/providers/shopify/privacy`. Owners can download data for
  a verified request and record completion after handling it through the
  store's privacy process. Workers redact the linked orders for a customer
  request and remove an uninstalled store's order records on a store redaction.
  Handle any flagged requests, backups, and exported artifacts as part of the
  privacy process. Verify the workflows in a development store before App
  Store review.

### Custom sites and ERPs

Create an `orders:write` key under **ERP and webhooks**. Send a Bearer token,
`Idempotency-Key`, and a JSON body to `POST <public API base>/v1/orders`.
Send `order_id`, `customer_name`, `product`, and `phone`. Include `city`,
`amount_pkr`, `items_count`, and other known risk inputs when available.
The response returns the internal and external IDs, decision, risk band, and
verification flags. Repeating the same key and input returns the original
receipt. A key reused for different input returns HTTP 409.

Add a public HTTPS destination to receive `order.accepted`, `order.decision`,
and `order.outcome`. Verify `X-COD-Guard-Signature` as `sha256=` followed by the
hex HMAC-SHA256 of `<X-COD-Guard-Timestamp>.<raw body>` using the signing
secret shown once at registration. Reject stale timestamps and deduplicate
by event ID. Apply revisions in order per order ID. Duplicate delivery and
out-of-order arrival are possible. The event body omits buyer contact and
reply content. Review delivery attempts in **Connections**.

### Buyer contact

Provision an approved Meta utility template using the exact copy in
[WhatsApp Cloud API](WHATSAPP_CLOUD.md), and subscribe the tenant callback URL
returned during sender setup. For calls, use a verified Twilio account and
number that can reach the target Pakistani mobile numbers. Provide a public
HTTPS recording that identifies the merchant and asks the buyer to press 1
to confirm or 2 to decline. Test both callbacks with provider test accounts.
Set `COD_GUARD_LIVE_BUYER_CONTACT=1` for the API and workers after those checks.

Record the buyer's opt-in separately for each channel. A worker checks consent,
current buyer phone, storefront state, and decision revision before sending.
Verified button taps, clear context-bound text, and keypad choices can update
the decision. Unclear text and audio go to staff review. An uncertain send
is surfaced for review and the worker avoids automatically repeating it.

### Couriers and training inputs

Link each consignment in the order's **Courier tracking** section. TCS polls
the documented tracking endpoint with the merchant token configured in
**Connections**. The direct adapter recognizes delivered events. Confirm the
remaining terminal TCS codes during merchant UAT. For PostEx, Leopards, or
other carriers, an authorized merchant forwarder can submit normalized updates
to `POST <public API base>/v1/courier-events` using a `courier:write` key.
Send `courier`, `tracking`, `event_id`, and the terminal `outcome`
(`delivered`, `returned`, or `refused`). Direct PostEx and Leopards adapters
require carrier-supplied merchant contracts. CSV import remains available.

Training export requires a linked shipment, purchase date, purchase-time
amount and quantity, and matching courier evidence. Staff independently
corroborate refusals before they enter the export. Buyer identifiers are
tenant-scoped pseudonyms. Download the dataset under **Couriers**, or run
`python scripts/train_seller_risk.py --tenant <tenant-id> --from-merchant-database --output <private-artifact>`
in the configured worker environment. The trainer performs seller-scoped,
held-out evaluation and writes a shadow artifact after the data and evaluation
checks pass. Serving continues to use the established decision policy.

## Rehearse a pilot migration

Use [backup_state.py](../scripts/backup_state.py) to take a consistent
SQLite backup. Use a newly provisioned PostgreSQL database. Run
`python scripts/platform_database.py --runtime-role <runtime-login> --import-pilot <backup.sqlite3>`
with the migration DSN and data keys. The import reads the SQLite backup
and reports copied row counts. It preserves order identifiers, decision
and outcome revisions, replies, connector cursors, and consent records.

Assign each imported merchant to its verified owner email with
`python scripts/platform_database.py --runtime-role <runtime-login> --assign-owner <tenant-id> <email>`.
Run it with the auth key used by the API. Ask each owner to verify their
email to access the imported tenant. Existing pilot API keys were
operator credentials. The merchant service uses its own sessions.

Compare counts and representative histories with the backup, confirm phone
masking and ciphertext at rest, and test backup restoration before using
the migrated service. Schedule tenant-scoped reply retention with
`python scripts/purge_replies.py --tenant <tenant-id>`.

The merchant integration suite runs against disposable PostgreSQL and
Redis services in CI. To run it locally, set `COD_GUARD_TEST_ADMIN_DSN`
and `COD_GUARD_TEST_REDIS_URL` to test services and run
`python -m unittest discover -s tests -p test_merchant_platform.py -v`.
The test login creates and drops its own database and role. The Redis
test uses a stub transcript to check job delivery independently of
audio-recognition accuracy.
