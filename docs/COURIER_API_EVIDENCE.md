# Round 5 WS-E — Courier tracking API evidence

Reviewed 2026-11-19 for Pakistan merchant COD shipments. The review used public, first-party material only. It did not use credentials, submit tracking numbers, or call sandbox, production, or private APIs.

| Courier | Public evidence | WS-E disposition |
| --- | --- | --- |
| TCS | Merchant COD tracking request and response documented. The sample supports a delivered outcome. [TCS COD API User Guide, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32) | Documented adapter candidate. Confirm wire details with TCS before production use. |
| PostEx | Public parcel tracker and official Shopify booking integration. [PostEx tracker](https://merchant.postex.pk/track-order), [PostEx app listing](https://apps.shopify.com/postex-official) | CSV baseline. Public Pakistan merchant tracking API contract unverified. |
| Leopards | First-party Shopify merchant tracking and a documented web return status. [Shopify app FAQ](https://www.leopardscourier.com/faqs), [Pakistan tracking FAQ](https://pk.leopardscourier.com/contact/faqs) | CSV baseline. Public merchant tracking API contract unverified. |
| Trax | Sonic tracking and official store integration, with return handling described by SLGTrax. [Sonic tracker](https://www.sonic.pk/tracking), [SLGTrax courier service](https://slgtrax.com/ecommerce/courier) | CSV baseline. Public merchant tracking API contract unverified. |

## TCS

**Published merchant contract**

- The COD guide specifies bearer-authenticated `GET /tracking/api/Tracking/GetDynamicTrackDetail`. The developer host is `devconnect.tcscourier.com` and production is `ociconnect.tcscourier.com`. The request key is `consignee`, whose value represents the TCS consignment number. The example uses a JSON body with an array of strings, `{"consignee":["<TCS CN>"]}`. Authorization is documented separately as `GET /auth/api/auth`. TCS requires successful UAT before production approval. [COD guide, pp. 3–4](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=3), [Tracking, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32)
- The response example exposes `shipmentinfo`, `deliveryinfo`, `checkpoints`, `shipmentsummary`, `message`, and `traceid`. The structured delivery event identifies the CN through `deliveryinfo[].consignmentno` and supplies `status`, `code`, and `datetime`. The invalid-CN example has `message: FAIL` and null event arrays. It supplies no shipment outcome. [Tracking, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32)
- WS-E can map a matching delivery event with `status: Delivered` and `code: OK` to `delivered` in a documentation-based fixture. The same sample contains `Awaiting Receiver Collection` (`SC`) and an `Out For Delivery` checkpoint. Both describe shipment progress. TCS’s customer FAQ defines the web status `Returned to Shipper` as a completed return and lists refusal, address issues, and failed delivery attempts as possible causes. That supports the meaning of the web label. The API examples supply no equivalent return or refusal event. [Tracking, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32), [TCS tracking FAQ](https://tcsweb.tcsexpress.com/customer-services)

**Open questions**

- Confirm request encoding with TCS. The parameter table calls `consignee` a string and the example shows an array in a GET body. Confirm batch limits and per-CN behavior, event ordering and time zone, and lifecycle rules for corrections and conflicting events. [Tracking, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32)
- Confirm exact returned and refused codes, reason fields, and when each becomes final. The guide describes a bearer-authenticated Delivery Status List, but its sample contains delay codes only. Its host labels also reverse the environment pattern used for tracking, so confirm that endpoint’s URLs with TCS. Polling limits and webhook behavior for this COD contract remain unverified. [Delivery Status List, p. 31](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=31), [Tracking, pp. 32–33](https://envio.tcscourier.com/COD-API-UserManual.pdf#page=32)

## PostEx

**Published evidence.** The Pakistan tracker accepts up to 14 tracking numbers in its web UI, and the FAQ describes shipment status updates and return management. The PostEx-published Shopify listing documents booking and consignment number generation. PostEx Global’s developer portal also publishes an OMS reference for XStak order management, inventory, and products. Its published operations do not establish a Pakistan courier consignment tracking contract. [Pakistan tracker](https://merchant.postex.pk/track-order), [Pakistan FAQ](https://postex.pk/faqs), [PostEx app listing](https://apps.shopify.com/postex-official), [OMS API reference](https://docs.postexglobal.com/reference/view)

**Open questions.** Confirm the supported Pakistan merchant tracking endpoint, method, auth, response and error schema, polling/webhook limits, and the terminal status and refusal reason values. The tracker’s 14-number limit applies to the web UI. [PostEx contact](https://postex.pk/contact-us)

## Leopards

**Published evidence.** The official Shopify FAQ describes connecting the merchant account with an API key and password and viewing shipment tracking after booking. The Pakistan FAQ says web tracking shows delivery status and delivery details. It defines `Returned to Shipper` as a completed return and lists refusal and an untraceable address as possible causes. [Shopify app FAQ](https://www.leopardscourier.com/faqs), [Pakistan tracking FAQ](https://pk.leopardscourier.com/contact/faqs)

**Open questions.** Confirm the merchant tracking endpoint, method, how credentials are supplied, response and error schema, and polling/webhook support. The public web label does not establish an API field or code. Returned and refused mappings need carrier confirmation, including whether refusal is a separate outcome or a reason attached to a return. [Shopify app FAQ](https://www.leopardscourier.com/faqs), [Pakistan tracking FAQ](https://pk.leopardscourier.com/contact/faqs)

## Trax

**Published evidence.** Sonic has a public tracking page and a COD merchant sign-in. Trax’s own Shopify listing describes tracking booked orders. SLGTrax advertises API integrations and describes return confirmation and the ability to intercept and redirect a return. A return in progress can therefore still change course. The reviewed sources provide no API status or reason values for delivered, returned, or refused. [Sonic tracker](https://www.sonic.pk/tracking), [Sonic merchant sign-in](https://app.sonic.pk/cod/login), [Trax app listing](https://apps.shopify.com/sonic-trax), [SLGTrax courier service](https://slgtrax.com/ecommerce/courier)

**Open questions.** Confirm the current Sonic merchant endpoint, method, auth, request and response schemas, polling/webhook limits, and how to distinguish a requested, intercepted, or completed return and a consignee refusal. [SLGTrax courier service](https://slgtrax.com/ecommerce/courier)

For the [WS-E outcome loop](CODEX_BRIEF_ROUND5.md#ws-e--courier-outcome-loop), CSV remains the baseline for all four couriers. Leave ambiguous, intermediate, and missing events unlabeled. In particular, a generic return supplies no evidence that the consignee refused the parcel.
