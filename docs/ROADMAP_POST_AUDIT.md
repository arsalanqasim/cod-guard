# Post-Audit Technical & Product Roadmap

This roadmap records the large architectural, integration, ML, and market-strategy proposals raised during the Round 11 independent audit (`commit e35834b`). All items below are explicitly out of scope for Round 11 code and are tracked here with their supporting evidence, current repository position, and provenance (**Already known** vs. **Newly contributed by audit**).

## 1. PostgreSQL + Row-Level Security (RLS) + Encrypted PII + RBAC

- **Provenance:** **Already a known gap** (single-node SQLite limit documented in `docs/HOSTING.md`), **expanded by audit** (plaintext PII in `orders`, missing RBAC in `operators.py`, in-memory rate limits).
- **Evidence:** `docs/HOSTING.md` notes SQLite restricts deployment to one writer installation; `backend/app/records.py` stores `customer_name`, `phone`, and `city` in plaintext; `backend/app/operators.py` grants identical read/write scope to every tenant operator and stores rate-limit windows in process memory. Pakistan's PECA Amendment 2025 and draft Personal Data Protection Bill heighten compliance expectations for customer phone/address storage.
- **Current position:** Round 11 enables SQLite WAL mode + `busy_timeout` (WS-2) and live env-var key rotation (WS-3) as bounded pilot hardening. Multi-tenant Postgres with RLS, envelope/column encryption for PII, staff RBAC (owner / ops / packer), and Redis-backed rate limiting/job queues remain required before multi-merchant production hosting.

## 2. Shopify Embedded App with GraphQL Fulfillment Holds & Checkout Telemetry

- **Provenance:** **Already a known gap** (Shopify App Store distribution listed on roadmap in `README.md`; webhook-only scope documented in `docs/SHOPIFY.md`), **expanded by audit** (explicit GraphQL `fulfillmentOrderHold` write-back and checkout Web Pixel telemetry).
- **Evidence:** `backend/app/shopify_routes.py` is currently an inbound webhook receiver with no outbound Shopify Admin API calls, so a 3PL or warehouse team can still ship an unconfirmed order. Competitors (`CodVerify`, `ConfirmFlow`) enforce real Shopify fulfillment holds.
- **Current position:** Round 11 captures `utm_source`, `utm_medium`, `utm_campaign`, and `referring_site` from Shopify webhooks (WS-5). Next phase: Shopify OAuth embedded app (Polaris/App Bridge), GraphQL `fulfillmentOrderHold` / `fulfillmentOrderRelease`, and a checkout Web Pixel capturing dwell time, autofill, and session attribution.

## 3. Live Multi-Courier API Adapters (PostEx, TCS, Leopards) + Payout Reconciliation

- **Provenance:** **Already a known gap** (`docs/COURIER_API_EVIDENCE.md` documents TCS as an unverified candidate and PostEx/Leopards/Trax as CSV-only), **expanded by audit** (evidence of live PostEx REST/webhook modules and CPR payout reconciliation as a primary merchant retention hook).
- **Evidence:** Public third-party integrations (e.g., Odoo PostEx Courier modules) claim live PostEx REST shipment creation and push webhooks, and Pakistani competitors (`ConfirmFlow`, `Courierify`) bundle 1-click multi-courier booking with automated Cash Payment Receipt (CPR) reconciliation.
- **Current position:** Re-verify PostEx's official Pakistan merchant API and webhook contract directly against `docs/COURIER_API_EVIDENCE.md` with merchant sandbox credentials, then ship live booking/status webhooks for PostEx, TCS, and Leopards alongside CPR + FBR WHT variance reconciliation to automate the outcome-learning loop.

## 4. Risk-Triggered Raast / Mobile Wallet Partial Prepayment (with FBR WHT Value Case)

- **Provenance:** **Partially known** (shadow prepaid offer text exists in `backend/app/dispatch_advice.py`), **newly expanded by audit** (live Raast P2M / PayFast / Safepay payment-link execution and Pakistan's 2025–2026 FBR withholding tax differential).
- **Evidence:** Under Section 6A and Section 153(2A) of Pakistan's Income Tax Ordinance, 2001 (Finance Act 2025), couriers withhold **2% WHT on COD** (4% non-ATL) versus **1% on digital payments** (2% non-ATL), alongside a separate 2% e-commerce sales tax. Raast P2M processed 55.9M transactions in Q1 2026, and local gateways (PayFast, Safepay) support Raast/wallet links. Note: Shopify Basic's 2% third-party gateway fee must be weighed alongside the 1% WHT reduction and RTO savings.
- **Current position:** Currently shadow-only offer drafts with manual outcome tracking. Next phase: trigger real Raast/JazzCash/Easypaisa deposit or full-prepayment links inside WhatsApp for AMBER/RED orders and measure net delivered GMV and tax-adjusted margin via A/B test.

## 5. Urdu IVR Escalation & Multimodal Audio-LLM Fallback

- **Provenance:** **Partially known** (`docs/ROUND9_VOICE.md` and `docs/DECISION_MODEL_EVAL.md` already proved local `faster-whisper` `small` at 89.47% WER on short synthetic Urdu replies and fine-tuned MiniLM at 53.1% wrong-commit rate), **newly contributed by audit** (replacing local CPU Whisper/MiniLM with schema-constrained multimodal audio-LLM fallback plus Urdu IVR auto-dialer escalation matching local incumbents).
- **Evidence:** `ConfirmFlow` and `Courierify` already ship automated Urdu IVR calling ("press 1 to confirm, 2 to cancel") for non-responders; local CPU `faster-whisper` `small` abstained on 7/7 explicit synthetic Urdu replies, and the stronger local comparator (Urdu Sukhan) carries a non-commercial `CC BY-NC 4.0` license.
- **Current position:** Keep the existing deterministic interactive-button-first core and adoption gate. Gate any multimodal LLM or Urdu IVR integration on `>= 200` real anonymized buyer replies with `< 1%` wrong-commit rate (especially `CONFIRM -> HOLD`).

## 6. Cross-Merchant Identity Graph on the Opt-In Reputation Network

- **Provenance:** **Already a known gap** (`backend/app/reputation_network.py`, `docs/NETWORK.md`, and `docs/ROUND10_RESEARCH.md` already built a consent-gated, k-anonymous phone-hash ledger and cited Meesho AAAI 2026 / Flipkart WWW 2023 identity-graph literature).
- **Evidence:** Single-merchant order-slip features plateaued at ~0.6065 ROC AUC on `[PK-REAL]` (`docs/ROUND10_EVAL.md`). Cross-merchant graphs (e.g., GoKwik's shared RTO network) break that single-store ceiling once sufficient merchant density exists.
- **Current position:** `reputation_network.py` remains disabled by default and advisory-only (`MIN_OTHER_SELLERS = 3`). Activate as a model feature only after onboarding enough consenting pilot merchants to satisfy k-anonymity and evaluating on a temporal, component-disjoint holdout.

## 7. Buyer Drop-Off Measurement via Randomized Holdout Control Group

- **Provenance:** **Newly contributed by audit** (and reinforced by WS-6 `docs/COST_SENSITIVITY.md`).
- **Evidence:** At live Pakistan WhatsApp Utility pricing (~PKR 4.15/message), the current cost equations make verifying almost every order appear optimal (`22.2%–98.5%`) because they do not model legitimate buyers who abandon or cancel due to verification friction or dispatch delay.
- **Current position:** No live control group exists. Pilot deployments must include a documented randomized holdout (keeping hard safety guardrails active) measuring net delivered orders per placed order, buyer drop-off, and delay-induced cancellations.

## 8. Courier-Side Fake-Attempt (CNA) Label Poisoning & NDR Verification Flow

- **Provenance:** **Newly contributed by audit**.
- **Evidence:** In Pakistani COD logistics, rider-side fake "Customer Not Available" (CNA) or "Consignee Refused" scans frequently trigger RTOs when no real delivery attempt occurred. Feeding raw courier RTO statuses directly into model retraining poisons buyer-risk labels by attributing courier failure to genuine customers.
- **Current position:** `courier_outcomes.py` currently treats courier-reported `returned`/`refused` as ground-truth buyer outcomes. Next phase: add an automated WhatsApp Non-Delivery Report (NDR) check ("Did the rider contact you today?") before writing an RTO into buyer-level training labels or cross-merchant reputation counts.
