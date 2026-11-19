# Seller-reviewed social intake (WS-F)

Start the existing shadow API and run `streamlit run frontend/social_intake.py --server.address 127.0.0.1`. The screen connects to `http://127.0.0.1:8000` by default; set `COD_GUARD_INTAKE_API` for a deployment-controlled HTTPS origin. Use a non-demo operator key. Keep the UI restricted to authorized sellers; the public exhibition dashboard stays synthetic.

## Paste a DM

Choose Instagram, WhatsApp or Facebook and paste just the buyer's order details. The offline parser recognizes labeled lines such as `Name:`, `Phone:`, `Address:`, `City:`, `Items:`, and `Total:` (some Urdu/Roman Urdu aliases also work). It does not infer identity from speaker names, guess an amount, or resolve conflicting details. Review/edit the draft, tick the review checkbox, and choose **Confirm and save**. An unstructured or ambiguous chat can be filled manually. This is not a measured extraction-accuracy claim.

`POST /integrations/social/dm/preview` is read-only. `POST /integrations/social/dm/confirm` takes only reviewed fields plus a caller-generated `confirmation_id`; retries with the same tenant, channel and ID do not duplicate the order. No raw transcript is saved. The full shipping address is not stored in this risk queue; its word count is retained. Keep the authoritative delivery address in the original seller system. A phone supplied in a DM is not marketing or verification consent.

## Google Sheets

Keep the sheet private. Download the order tab via **File → Download → Comma-separated values (.csv)**, then upload it in the **Import Google Sheets CSV** tab. The `sheets/import` API reuses [shadow CSV](SHADOW_INTAKE.md) validation, reports row errors, and marks accepted rows `GOOGLE_SHEETS`. Format phone cells as plain text to preserve `+` or leading zeros. The importer never connects to Google, requests public sharing, or retains API credentials. Process the file as sensitive seller data. [Google download help](https://support.google.com/docs/answer/49114) · [Google CSV formats](https://support.google.com/docs/answer/9331167/2.4).

## Later: first-party Meta ingestion

Direct Meta messaging API intake is not implemented. Plan inbound-only order intake: a buyer initiates contact; no scraping, outbound acquisition, history backfill by default, or bypassing permissions. For non-role merchants, budget for App Review/Advanced Access and Business Verification before using approved Page or Instagram professional accounts. Stay within the standard **24-hour** window for ordinary conversations if responding in a later phase. Meta describes special options for certain ad-originated flows and approved human-agent handling; neither expands this connector's scope. WhatsApp Cloud sending, when authorized, remains the separate opt-in [WS-D path](WHATSAPP_CLOUD.md). [Meta access](https://developers.facebook.com/docs/graph-api/reference/message/) · [Verified business](https://developers.facebook.com/docs/graph-api/reference/page/conversations/) · [Window updates](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog/).
