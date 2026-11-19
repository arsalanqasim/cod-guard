# WhatsApp Cloud API (WS-D)

Public Meta sources checked 2026-11-19. Account-specific evidence is listed below.

## Pakistan rates and billing

- For recipients with a `+92` number, Meta’s calculator (Pakistan, USD) shows these list rates per billable delivery, effective 2026-10-01 under the Messaging account timezone.

  | Category | USD per billable delivery |
  | --- | ---: |
  | Utility | $0.0150 |
  | Service | $0.0150 |
  | Marketing | $0.0473 |
  | Authentication | $0.0150 |
  | Authentication international | $0.0750 |

  Marketing is about 3.15× the utility list rate. Meta applies volume tiers to utility and authentication. [Meta rate calculator](https://whatsappbusiness.com/products/platform-pricing/#rates) · [Rate cards and volume tiers](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/#rate-cards-and-volume-tiers)
- Since 2026-10-01, utility templates can incur charges even inside the 24-hour customer service window. Each business phone number gets 1,000 delivered service messages free per month, with no rollover. The service rate applies from the 1,001st eligible delivery. Qualifying free-entry-point deliveries are exempt. The calculator page’s introductory free-message copy predates these billing rules. [October pricing changes](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/#effective-october-1-2026) · [Monthly service tier](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/#free-tier-of-monthly-service-messages)
- `value.statuses[].pricing` uses `pricing_model: "PMP"` for per-message pricing. `type: "regular"` is billable. `free_customer_service` and `free_entry_point` are free. Use `type` with `category` because Meta plans to deprecate the boolean `billable` field. The webhook carries no monetary amount. For WS-D accounting, count each outbound `statuses[].id` once on delivery (`read` can imply delivery), and keep missing or unrecognized pricing unknown. A successful send or `sent` status alone establishes no charge. List-rate estimates require reconciliation against Meta billing. [Status webhook reference](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/status/) · [Pricing webhooks](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/#pricing-webhooks)

## Consent and order confirmation

- The recipient must give the business their number or username and opt in to subsequent contact from that named business. Meta permits general opt-in subject to applicable law and recommends setting expectations by message category. Honor block, stop and opt-out requests received on or off WhatsApp, including removal from the contact list. Business-initiated contact requires an approved template. Free-form replies are permitted during the 24-hour window opened or reset by each user message. Outside it, use approved templates. Automated responses in the window require a clear, direct escalation path. [Messaging policy](https://whatsappbusiness.com/policy/) · [Meta opt-in guidance](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in/)
- An order-specific confirmation or cancellation can qualify as `UTILITY`. Keep the template and substituted values transactional. Mixed promotional and utility content is `MARKETING`. Verify both `status: APPROVED` and `category: UTILITY` for the intended template name and language. Meta can assign or change the category during review or after approval. [Template categorization](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization/) · [WABA templates API](https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/message_templates/)
- Define Confirm and Cancel as `QUICK_REPLY` buttons in the template. Send `type: "template"` to `/{phone-number-id}/messages`, with a `template.components` entry per button using `type: "button"`, `sub_type: "quick_reply"`, the zero-based `index` (`"0"` / `"1"`), and `parameters: [{"type":"payload","payload":"<signed action>"}]`. On tap, the incoming `value.messages[]` item has `type: "button"` and returns the developer payload in `button.payload` alongside `button.text`. Use the signed payload to authorize the order action. [Meta Cloud API send example](https://www.postman.com/meta/whatsapp-business-platform/request/lwtlz1k/send-message-template-interactive) · [Meta callback example](https://www.postman.com/meta/whatsapp-business-platform/request/5qal58f/received-callback-from-a-quick-reply-button-click) · [Meta Cloud API button schema](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/types/component_object/)

## Evidence gaps

- WABA template ID, exact approved copy, locale, Confirm/Cancel order, and current `APPROVED` / `UTILITY` state for the target account.
- A current first-party maximum length for the send-time `payload`, plus acceptance and round-trip of the actual signed token for both buttons on the target Graph API version. Meta’s dedicated button webhook and template components pages returned HTTP 429. The Meta Postman examples and archived Cloud API SDK cover the field shape.
- Target-account delivery and pricing callbacks correlated by message ID, actual charges reconciled against Meta billing in the account currency, and end-to-end evidence of seller opt-in capture and suppression after on- and off-WhatsApp opt-outs.

## Operator setup

1. For a non-demo tenant only, set `COD_GUARD_WHATSAPP` to a JSON object keyed by tenant ID. Each entry needs `waba_id`, `phone_number_id`, `template_id`, `token`, `app_secret`, `verify_token` and a unique random `signing_key` (32+ characters); `api_version` is optional. Configure these as secrets. Keep the signing key stable: replacing it without a consent migration loses contact suppression state.
2. Create an English (US) utility template with exactly `Please confirm or cancel cash-on-delivery order {{1}}. To stop WhatsApp order messages, reply STOP.` and two quick replies, `Confirm` then `Cancel`. The connector checks the approved body, language, category and buttons before each submission. Use a token authorized to inspect templates and send on the configured WABA.
3. Subscribe the WABA to `messages` at `GET/POST /integrations/whatsapp/{tenant_id}/webhook` over HTTPS. Disable or redact query-string logs at the application and reverse proxy so webhook handshake tokens are not logged. Deploy one application instance; the send/consent interlock is process-local.
4. Use `POST /integrations/whatsapp/orders/{order_id}/consent` with `opted_in` and a non-PII `evidence_reference` only after the operator records actual buyer consent or a withdrawal. Never infer consent from order intake. `POST /integrations/whatsapp/orders/{order_id}/send` submits once. Accepted is not delivered; an ambiguous timeout blocks automatic resend and can reconcile through a later signed status callback.
5. `GET /integrations/whatsapp/status` reports tenant mode and delivery counters; `GET /integrations/whatsapp/orders/{order_id}` reports the individual attempt. Costs are list-rate estimates, not invoice totals. The code estimates known billable utility deliveries during the October–December rate-card window and leaves other paid amounts unset. The connector does not send outbound service messages or manually decrement a free-service counter.

Missing credentials keep sends simulated. The exhibition dashboard remains explicitly simulated. Daraz is score-and-queue only in both modes. Cloud handles signed quick replies and context-bound text; voice is not ingested by this callback. No live send, template approval, or paid delivery was exercised in this workstream.
