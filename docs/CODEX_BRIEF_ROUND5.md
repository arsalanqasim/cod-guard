# COD-Guard — Codex Mission Brief, Round 5: The Sellable Layer

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`, main after Round 4 integration (merge c7f202f).

## Why this round exists

Rounds 1–4 built an honest engine and hardened it. The production review
scored commercial readiness 2/10: nothing a seller can buy yet. Arsalan's
decision (2026-11-19): COD-Guard is to become production-grade and be sold
to real customers across ALL channels — social commerce, independent
websites, Shopify, WooCommerce, Daraz. Standing instructions: deep research
at every step; proceed without asking for confirmation at each step and
report results.

A commissioned competitive study (19 Nov 2026, 20 products, vendor pages
and listings read directly) corrected our assumptions. **The following are
already claimed by rivals and are NOT an edge — never pitch or claim them,
and never claim "first" for any of them:**

- WhatsApp Confirm/Cancel buttons (ConfirmFlow $5/mo, OrderWitness,
  Botaura, others)
- 0–100 risk scores (OrderWitness and many Shopify apps)
- Urdu / Roman Urdu buyer messages (COD Protect, DukaanFlow, ConfirmKaro,
  Botaura, OrderWitness)
- Voice notes as such (COD Protect claims voice-note replies, Shopify-only;
  Botaura offers voice Q&A only on its Rs 9,695/mo tier)
- Cross-seller blacklist as a bare claim (OrderWitness blog claims a
  network blacklist; COD Radar sells cross-store history; GoKwik proves
  the model in India)
- PKR / micro pricing (SendFlow Rs 699/mo, COD Protect Rs 2,500, OrderWitness
  free 50 orders/mo + Rs 999 packs, ConfirmKaro free)
- Evidence PDFs (OrderWitness), prepaid conversion via JazzCash/Easypaisa
  (OrderWitness, Level), courier booking/tracking (ConfirmFlow, Botaura),
  GPS address capture (Botaura)

## The edge we build (from the same study — each is a verified gap)

1. **One queue across every channel, Daraz included.** No competitor lists
   Daraz ingestion; the strongest rival's own Daraz guide positions itself
   for direct orders *alongside* Daraz. A seller's Shopify + WooCommerce +
   Daraz + DM orders in one scored, verified queue is unserved.
2. **A closed courier-outcome learning loop for Pakistani couriers.**
   Rivals track shipments; none verifiably feeds delivered/RTO outcomes
   back into re-scoring by phone, city×courier, and seller automatically.
   (Our outcome-fed retraining exists; this round wires real outcome
   sources into it.)
3. **Published, reproducible accuracy.** No competitor publishes a dataset,
   method, holdout, or false-positive rate — only marketing percentages,
   and at least one rival's claimed rating contradicts its own app-store
   listing (1 review). Our evaluation protocol (Round 4, WS10) becomes a
   public, versioned benchmark report. Trust is the differentiator.
4. **Social-DM-first ingestion.** Social-discovery orders carry the highest
   RTO in the OrderNation data (22.7%). Rivals offer manual forms or
   hosted stores; none verifiably turns a DM conversation into a structured,
   scored order in the same queue.
5. **Urdu voice + free-text confirmation at micro price, on every channel.**
   Voice is locked to Shopify-only or a Rs 9,695 top tier elsewhere. Ours
   ships in the ≤ Rs 2,500 tier, channel-independent.

## Workstreams (each: implementation + tests + AUDIT.md mapping entry)

### WS-A — Daraz feasibility spike (DO FIRST, timebox it)
Build the Daraz Open Platform client skeleton (app key/secret, HMAC-SHA256
signing, `/orders/get`, `/order/get`, `/order/items/get`, polling every
10–15 min — webhooks unverified, design for polling) against a sandbox or
a test seller account if obtainable. The spike's single question: **is a
usable buyer phone number available** (names/addresses are partly masked
unless the app passes Daraz's sensitive-data review; no customer endpoint
exists; a phone field was not confirmed in the captured order shape).
Deliverable: `docs/DARAZ_SPIKE.md` with the observed order payload shape
(redacted), the phone verdict, and the resulting Daraz mode:
- phone available → full verification flow;
- phone masked/absent → Daraz orders are scored and queued for the seller
  with whatever fields exist, and the product must NOT promise buyer
  WhatsApp verification for Daraz. Record which mode we are in; every
  later claim follows it.

### WS-B — WooCommerce connector (easiest real channel)
Seller-generated REST credentials (wc/v3), order webhooks + polling
fallback, outcome write-back (order notes/status), connection health in
the dashboard. Handle the known operational risks: auth-header stripping
(fallback auth modes), WP-Cron delays (polling covers it), HTTPS/permalink
requirements surfaced as setup checks.

### WS-C — Shopify connector (custom-app route first)
Order intake via webhooks for a custom/private app install (per-seller),
protected-customer-data fields handled per Shopify's approval model.
Do NOT submit to the App Store in this round; note in the connector doc
that App Store distribution forces Shopify billing (no PKR/JazzCash for
the app itself) and a production-readiness review — a later business
decision, not an engineering default.

### WS-D — WhatsApp Cloud API, production path
Real sending behind the existing channel interface: approved UTILITY
template with Confirm/Cancel buttons carrying the Round-4 signed payload;
opt-in capture and opt-out honouring; strict template discipline — no
promotional content anywhere in the confirmation template (any promo
content recategorises it as marketing at ~3.16× cost). Cost accounting
per tenant at current Meta Pakistan rates (utility ≈ $0.015 per delivered
message; first 1,000 service messages/number/month free) recorded against
each verification so unit economics are measured, not guessed. When no
Meta credentials are configured, the system runs in the existing simulated
mode and says so in the UI.

### WS-E — Courier outcome loop
Outcome ingestion for PostEx, Leopards, TCS, Trax where a usable status
API exists; a documented CSV outcome import as the universal baseline.
Outcomes auto-label orders delivered / returned / refused, feed the
existing retraining path, and add the features the loop unlocks (phone
outcome history, city×courier rates, per-seller rates) behind the same
hash-locked evaluation protocol — a feature ships only if the locked
evaluation does not regress.

### WS-F — Social-DM ingestion v1
Structured order capture from a pasted DM conversation (Instagram /
WhatsApp / Facebook) into the same queue: extract name, phone, address,
items, amount; show the seller a confirm-before-save screen (extraction
is a draft, never silently trusted). Google Sheet import as the second
route (a rival's sellers already work from sheets). Meta messaging API
ingestion is explicitly later-phase: the legitimate route is inbound-only
(buyer must initiate; App Review + Business Verification; 24h window) —
document that in the connector notes, do not build it yet.

### WS-G — The public benchmark + savings proof
A versioned, reproducible benchmark report generated from the locked
evaluation (per-channel, per-language incl. Urdu voice: precision, recall,
false-positive rate, method, dataset description, limitations) rendered
in-repo (`docs/BENCHMARK.md`, regenerated per model version) and surfaced
in the dashboard. Extend the seller savings report to consume WS-E's real
outcome labels when present (estimated vs measured savings labelled
separately, always).

### WS-H — Reputation network v1, transparent by design
Opt-in cross-seller phone reputation using hashed numbers only. What makes
ours different is governance, published in `docs/NETWORK.md`: consent
basis, what is shared (outcome counts, never order contents), an
appeals/removal path for wrongly flagged buyers, and a live, honest
network-size counter. Never claim "first"; claim "auditable".

## Sequencing

WS-A spike first (it gates every Daraz statement). Then WS-B, WS-D, WS-E,
WS-G in that order; WS-C and WS-F after; WS-H last in this round. Per-
workstream PRs as in Round 4, stacked where they depend.

## Non-negotiables (unchanged, plus)

- The professor's requirements and the honesty rules from Rounds 1–4:
  synthetic stays labelled synthetic; no invented pilots, ratings, or
  savings; estimates always labelled.
- Never claim "first" or "only" for buttons, Urdu, voice, blacklists, or
  PKR pricing — the study shows each is taken.
- Any performance claim the product makes publicly must trace to the
  WS-G benchmark or be removed.
- If the Daraz spike says phones are unavailable, Daraz mode is
  score-and-queue only, and all copy says exactly that.

## Report back

Per PR: what changed, tests, and the AUDIT.md mapping. For WS-A: the spike
report before any Daraz build proceeds past the client skeleton.
