# WooCommerce connector (WS-B)

Design reference from WooCommerce documentation and source. Store setup and
validation are pending.

## Connection and authentication

- Use the store's canonical HTTPS URL and non-Plain WordPress permalinks for
  `/wp-json/wc/v3/`. Use a seller-generated WooCommerce REST key with **Read**
  for intake or **Read/Write** for intake plus write-back. The linked WordPress
  user's capabilities also apply. [REST API requirements](https://developer.woocommerce.com/docs/apis/rest-api/#requirements) · [Key permissions](https://developer.woocommerce.com/docs/apis/rest-api/authentication/#rest-api-keys)
- Use HTTP Basic auth with the consumer key as username and consumer secret as
  password. If WooCommerce reports a missing key, check whether the host or proxy
  strips `Authorization`. WooCommerce supports an opt-in HTTPS query-string
  fallback with `consumer_key` and `consumer_secret`. URLs can expose both in
  proxy logs and traces even over HTTPS. Redact them throughout the request path
  before enabling fallback. WooCommerce documents OAuth 1.0a for plain HTTP.
  [Authentication](https://developer.woocommerce.com/docs/apis/rest-api/authentication/) · [URL credential exposure](https://community.owasp.org/vulnerabilities/Information_exposure_through_query_strings_in_url)

## Order polling

- `GET /wp-json/wc/v3/orders` supports `page` (1-based), `per_page`,
  `orderby=id`, `order=asc`, and `status` (defaults to `any`). Use
  `X-WP-TotalPages` to finish the scan. `after` and `before` filter creation
  time. For changes, use ISO 8601 UTC bounds in `modified_after` and
  `modified_before` with `dates_are_gmt=true`. The controller confirms that
  `modified_before` is the upper bound. [Orders](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/#list-all-orders) · [Pagination](https://developer.woocommerce.com/docs/apis/rest-api/#pagination) · [Date filter source](https://woocommerce.github.io/code-reference/files/woocommerce-includes-rest-api-controllers-version3-class-wc-rest-crud-controller.html)
- The connector identifies orders by store and Woo order ID, overlaps the cursor
  by two minutes, and advances it after all pages are saved. Both polling and
  signed webhooks reconcile source status and supported intake fields.
  The poll includes GMT modification and payment timestamps. Read the
  [queue and conflict rules](SHADOW_INTAKE.md#storefront-queue-status) before dispatch.

## Webhooks

- For `order.created` and `order.updated`, the first save as **Active** sends
  a separate unsigned POST with `webhook_id=<id>` as the form body. Return
  `200 OK` for the recognized ping shape, with no order processing. Some
  releases require exactly `200`. [Webhook setup](https://woocommerce.com/document/webhooks/) · [WooCommerce 11.2.0 source (`deliver_ping`)](https://github.com/woocommerce/woocommerce/blob/11.2.0/plugins/woocommerce/includes/class-wc-webhook.php)
- For order deliveries, verify `X-WC-Webhook-Signature` against the
  base64-encoded HMAC-SHA256 of the raw request body using the configured
  webhook secret. Compare in constant time before processing the JSON. Set an
  explicit secret and make intake safe to repeat. [Webhook payload and signature](https://developer.woocommerce.com/docs/apis/rest-api/v3/webhooks/)
- A cancellation closes the queue entry. A recorded payment or a switch away
  from eligible COD marks it out of scope. Other non-dispatchable Woo statuses
  close it at source. [Order statuses and fields](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/).
- Keep polling enabled during webhook delays or failures. Check **WooCommerce →
  Status → Scheduled Actions** for Action Scheduler or WP-Cron lag and
  **Status → Logs** for delivery errors. Repeated failures can disable the
  webhook. [Scheduled actions](https://woocommerce.com/document/understanding-the-woocommerce-system-status-report/scheduled-actions/) · [Webhook logs and disabling](https://woocommerce.com/document/webhooks/)

## Outcome write-back

- `POST /wp-json/wc/v3/orders/{id}/notes` with `note` and `customer_note: false`
  creates an admin-only note. `true` makes it customer-facing and triggers
  notification. Reconcile ambiguous timeouts before retrying to avoid duplicate
  notes. [Order notes](https://developer.woocommerce.com/docs/apis/rest-api/v3/order-notes/)
- `PUT /wp-json/wc/v3/orders/{id}` with `status` changes the order workflow.
  Agree on transitions with the merchant before enabling this path. Status
  changes can affect stock, emails, and fulfillment automation. Check the
  current status before writing and handle the resulting order update without
  repeating write-back. [Order updates](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/#update-an-order) · [Order status effects](https://woocommerce.com/document/managing-orders/order-statuses/) · [WooCommerce email settings](https://woocommerce.com/document/configuring-woocommerce-settings/emails/)

## Store setup and health

1. Provision an operator and non-demo tenant. In server-side secret storage,
   set `COD_GUARD_WOOCOMMERCE` to a JSON object keyed by a stable store alias.
   Each record has `tenant_id`, `url`, `key`, `secret`, `webhook_secret` (24+
   characters, unique per store), optionally `auth_mode` (`basic`, or `query`
   only after enabling URL redaction), and optionally `outcome_statuses`.
   The deployment admin sets the WooCommerce URL; no public endpoint accepts
   URLs or credentials. Do not export these secrets or reuse aliases for other stores.
2. Register both order topics with the same configured secret at
   `POST /integrations/woocommerce/<alias>/webhook`. Use a public TLS endpoint.
   Intake is limited to pending, processing or on-hold PKR orders whose payment
   method is WooCommerce's built-in `cod`. Missing risk inputs stay unknown.
3. Run `python scripts/poll_woocommerce.py` once, then schedule a single
   non-overlapping run every five minutes against the same persistent state
   directory as the API. The first poll looks back one day; a failed or over-limit
   window leaves the cursor unchanged. Busy stores can exceed the 1,000-row cap;
   review the error before using the connector for production dispatch.
4. Operators can call `GET /integrations/woocommerce/connections` for their
   tenant, or trigger `POST /integrations/woocommerce/<alias>/poll`. On a private
   deployment-admin-only Streamlit instance, `COD_GUARD_WOO_HEALTH_LOCAL=1`
   shows last poll, webhook, and poll error for configured stores. Do not enable
   that setting on the public demo or a shared dashboard.
5. After recording an outcome, explicitly call
   `POST /integrations/woocommerce/<alias>/orders/<order_id>/write-outcome`.
   It reconciles the private note by outcome revision before writing, or uses
   the optional outcome-to-status map (`completed`, `cancelled`, `on-hold`).
   No refunds and no automatic status changes are issued.

Before enabling at a store, verify both webhook topics and the poll catch-up
using a test COD order, inspect health, and verify a private write-back note.
The PR uses test fixtures and does not claim a live store or dispatch pilot.
