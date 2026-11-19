# Daraz order API spike (WS-A)

Pakistan market. Public documentation reviewed on 2026-11-19.

**Verdict: phone unverified. Gate: score-and-queue only.** No authorized
Pakistan seller token or console test account was available to this run.
No authenticated calls were made. This is not evidence that every Daraz
app receives masked numbers; it is insufficient evidence to enable or
promise WhatsApp verification for Daraz. The spike does not ship live
ingestion or an active scheduler.

## Order schema and phone exposure

- Daraz maps `GetOrder` to `/order/get` and `GetOrders` to `/orders/get`. Its SDK example uses `GET /order/get` with `order_id` and a seller access token. Seller OAuth authorization and the app's API permission group govern access to order data. [API name mapping](https://developer.alibaba.com/docs/doc.htm?articleId=120243&docType=1&treeId=754) · [SDK example](https://developer.alibaba.com/docs/doc.htm?articleId=120241&docType=1&treeId=754) · [Seller authorization](https://developer.alibaba.com/docs/doc.htm?articleId=120222&docType=1&treeId=754) · [API permission groups](https://developer.alibaba.com/docs/doc.htm?articleId=120220&docType=1&treeId=754)
- Daraz classifies customer names, contact information, and order and line-item details as sensitive business data. Its sensitive access guide describes default masking based on security evaluation and a separate DataMoat review through **Sensitive Data Privilege → Apply Unmask**. Daraz Pakistan identifies buyer phone numbers, email, and billing and delivery addresses as personal contact data. [Sensitive data access](https://developer.alibaba.com/docs/doc.htm?articleId=120233&docType=1&treeId=754) · [Daraz Pakistan Privacy Agreement](https://www.daraz.pk/wow/i/pk/help/privacy-agreement?hybrid=1)
- **Response schema gap.** The Daraz API Reference stayed on its loading screen. Daraz's readable documentation confirms the routes and masking policy, but leaves the exact phone field paths, the difference between list and detail responses, and the conditions for missing, masked, or usable values unverified for Pakistan. A seller token alone does not establish access to a usable buyer number. [Daraz API Reference](https://open.daraz.com/doc/api.htm) · [Sensitive data access](https://developer.alibaba.com/docs/doc.htm?articleId=120233&docType=1&treeId=754)

## Sandbox access

- Daraz's March 2022 testing guide documents a loaned seller account through **App Console → Test Tools → Test Account → Loan New Account**. The application asks for a country and business requirements. **Sandbox Test → Test Case** supports test orders, and **Get Token** issues a sandbox access token. The guide leaves current Pakistan account availability, app eligibility, the sandbox base URL, and whether sandbox masking matches production unverified. [Test your application](https://developer.alibaba.com/docs/doc.htm?articleId=120236&docType=1&treeId=754)
- Daraz's April 2024 API Explorer guide says Explorer queries production data and gives `https://api.daraz.pk/rest` in its Pakistan example. The console sandbox workflow and API Explorer are separate testing paths. [Daraz API Explorer](https://open.daraz.com/doc/doc.htm?docId=118729&nodeId=27493)

## Payload evidence

No live order payload was observed. The vendor's SDK example documents the
`code`, `data`, and `request_id` envelope on an unrelated API, not the
Pakistan order schema. This is the synthetic stub used to exercise transport,
not a redacted seller capture or evidence of phone absence:

| Route | Synthetic `data` |
| --- | --- |
| `/orders/get` | `{"orders": []}` |
| `/order/get` | `{"order_id": 42}` |
| `/order/items/get` | `[]` |

## Connector handoff

- The read-only client sends signed HTTPS requests to Daraz Pakistan. It uses
  Daraz's [HMAC-SHA256 signing guide](https://developer.alibaba.com/docs/doc.htm?articleId=120322&docType=1&treeId=754).
  The spike tests the transport with synthetic replies; it does not validate
  the order-specific filters or response fields against a live service.
- Later, poll a bounded updated-order window every 15 minutes. Deduplicate by
  seller and external order ID, paginate, and persist the cursor only after
  processing succeeds. Do not depend on unverified webhooks. Missing or masked
  fields must remain unknown rather than be converted to bad phone signals.
- To close the evidence gap, use a Pakistan console test order and compare list,
  detail, and item responses. Record only field paths, types and whether contact
  values are missing, masked or usable. Confirm app permissions and permitted
  use for external verification with Daraz before enabling messaging. Do not
  attach tokens, raw responses, or buyer data to a PR.
