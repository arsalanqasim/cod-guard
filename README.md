# COD-Guard — Pre-Dispatch Intelligence for Cash-on-Delivery Orders

COD-Guard checks every cash-on-delivery order **before** it ships: it scores
the order's refusal risk, verifies risky orders with the buyer on WhatsApp,
and learns from what couriers actually deliver or return — so a seller stops
paying courier charges for orders that were never going to be collected.

Built for how Pakistan actually sells: one queue across **Shopify,
WooCommerce, Daraz, independent websites, and Instagram/WhatsApp DM orders**,
with buyer verification in English, Roman Urdu and Urdu script, including
Urdu voice notes.

> **Transparency.** COD-Guard publishes its evaluation instead of hiding
> it: the [public benchmark](docs/BENCHMARK.md) is generated from a
> hash-locked test split under a written metric protocol, with method and
> limitations attached. The bundled benchmark runs on a documented
> synthetic dataset while seller pilots are onboarded; no merchant
> results are claimed until they are measured.

## Why it exists

In the OrderNation *State of Online Shopping Pakistan 2026* study
(~170,000 orders, one large retailer), 37.3% of COD orders were cancelled
and 19.4% of shipped value came back — roughly **49 of every 100 COD orders
ended in cash collected**. Sellers pay courier charges both ways on the
rest. Existing tools confirm orders; COD-Guard is built around the full
loop: **score → verify → decide → ship → learn from the outcome.**

## What makes it different

- **One queue for every channel.** Shopify and WooCommerce connect by
  signed webhooks; DM orders are pasted or sheet-imported with
  review-before-save; Daraz orders are scored and queued (buyer phone
  availability on Daraz is unverified, so Daraz buyers are not promised
  WhatsApp verification — see [the Daraz spike](docs/DARAZ_SPIKE.md)).
- **A closed courier-outcome loop.** Delivered / returned / refused
  outcomes — from courier feeds or CSV — retrain the model and re-score
  future orders. Tracking alone doesn't do this; learning does.
- **Published, reproducible accuracy.** The benchmark is generated from a
  hash-locked test split under a written [metric protocol](docs/METRIC_PROTOCOL.md).
  Error rates are published, not hidden behind marketing percentages.
- **Urdu voice-note verification.** Buyers reply the way they actually
  talk; voice notes are transcribed offline (Whisper) and understood
  alongside typed replies.
- **Decisions that can't be quietly reversed.** Only unambiguous
  whole-order replies commit. Scoped ("without the blue shirt"),
  conditional ("I would confirm"), or time-bound ("cancel after 5pm")
  replies go to a human. Every decision is frozen with revision, time
  and actor; a late voice result can never overwrite a newer decision.

## How it works

```text
orders ──► intake ──► risk scoring ──► decision gate ──► courier
(Shopify,    (one      (rules + ML,     (SHIP / HOLD /     │ delivered
 Woo, Daraz,  queue)    GREEN/AMBER/RED) VERIFY_FIRST)      │ returned
 DMs, CSV)        ▲            │              ▲            ▼
                  │            ▼              │        outcomes
                  └── model ◄── retraining ◄──┴──────────┘
                              (versioned, atomic publish)
```

Risky orders are verified on WhatsApp first (buttons, free text, or voice).
A confirmation can release a flagged order; a denial can stop a passed one.
The first recorded outcome freezes the current decision revision for
evaluation. Later corrections retain that revision.

## Measured performance (synthetic benchmark)

Baseline v1 uses a threshold of 0.50 on 1,184 held-out synthetic orders.
AMBER or RED counts as a flag before any reply.

**false-positive rate 16.47%** (96 of 583 genuine orders flagged),
**false-negative rate 59.23%** (356 of 601 failed orders passed).
Illustrative cost PKR 274,600 vs PKR 390,650 for shipping everything —
and PKR 259,800 for an aggressive block-on-any-signal policy, which the
served policy does **not** beat on raw cost. Low false positives *and*
low false negatives have **not** been established; verification, not
scoring alone, is where the design expects its gains, and the scenario
analysis in [the evaluation report](docs/EVAL_REPORT.md) says exactly
what is assumed. Failed labels mean non-collection, not proven fraud.

The generator targets 51% expected non-collection — the upper end of one
modelled scenario informed by the OrderNation funnel (49–57 collections
per 100 COD orders, one retailer, mixed measurement windows). Language
support means tested sample phrases in English, Roman Urdu and Urdu
script; coverage is unmeasured and known scope failures are handled by
routing to a human, not by guessing.

## Quick start (local demo)

Windows PowerShell, Python 3.13:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe scripts/build_demo.py
.\.venv\Scripts\python.exe scripts/run_demo.py
```

On Linux, use `.venv/bin/python`. `build_demo.py` regenerates the
synthetic benchmark, trains the baseline model, seeds 80 demo orders
(reserved outside training/validation/test at baseline), and runs the
full check suite. The demo launcher starts a disposable offline session
with simulated WhatsApp. Close it and rerun the same command to clear
demo decisions, outcomes and learned model state.

Voice (once, while online): `scripts/prepare_voice.py` caches Whisper
`small` weights under `data/whisper/`; inference then runs **offline**.
The bundled sample clip is general Urdu speech from Google FLEURS
(CC BY 4.0). See [the Urdu voice smoke test](docs/VOICE_TEST.md),
[Urdu voice accuracy](docs/VOICE_ACCURACY.md) for the read-speech
measurement, and [Round 9 Urdu voice](docs/ROUND9_VOICE.md) for the
short-reply evaluation.

## Hosting and API

The [merchant platform foundation](docs/MERCHANT_PLATFORM.md) covers
PostgreSQL migrations, browser sessions, merchant roles, and Redis-backed
voice workers. The single-host pilot setup is below.

Run `python scripts/run_host.py --bootstrap` from a clean checkout to
start the loopback API and an isolated exhibition dashboard. Copy
[`.env.example`](.env.example) to configure tenant keys and connectors,
or build the API container from [`Dockerfile`](Dockerfile).
[Host setup, privacy and tenant configuration](docs/HOSTING.md) · [Security policy](SECURITY.md) · [Contributing](CONTRIBUTING.md)

Operators can correct the latest classified reply and export versioned labels
for offline retraining. See [reply corrections and shadow evaluation](docs/REPLY_CORRECTIONS.md)
and the [Round 7 benchmark](docs/DECISION_MODEL_EVAL.md).

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Operator-key authenticated writes, tenant-scoped data, masked phone
numbers in list and detail views, authenticated CSV intake for shadow operation
([SHADOW_INTAKE.md](docs/SHADOW_INTAKE.md)), paginated queue (a 50-order
page over 10,000 stored orders loads in tens of milliseconds), and
`/health` vs `/ready` separation — readiness verifies the database, the
active model bundle, and that its evaluation artifacts match.

The real-data evaluation keeps model-first scoring in seller-specific
shadow mode. [Round 9 metrics](docs/ROUND9_EVAL.md) · [Cost-model sensitivity](docs/COST_SENSITIVITY.md) · [Data provenance](docs/DATA_SOURCES.md)

## Channels and evidence

| Channel | Route | Doc |
| --- | --- | --- |
| WooCommerce | Signed webhooks + polling, outcome write-back, source reconciliation | [WOOCOMMERCE.md](docs/WOOCOMMERCE.md) |
| Shopify | Signed custom-app `orders/create` intake (no App Store flow yet) | [SHOPIFY.md](docs/SHOPIFY.md) |
| Daraz | Read-only spike client; score-and-queue only until a seller payload proves phone access | [DARAZ_SPIKE.md](docs/DARAZ_SPIKE.md) |
| Social / DM | Paste or sheet import, review-before-save, next-action advice & address review | [SOCIAL_INTAKE.md](docs/SOCIAL_INTAKE.md) |
| WhatsApp | Meta Cloud API, utility template, consent + opt-out, per-message cost accounting | [WHATSAPP_CLOUD.md](docs/WHATSAPP_CLOUD.md) |
| Couriers | CSV outcomes + read-only TCS adapter; shadow retraining | [COURIERS.md](docs/COURIERS.md) |
| Dispatch advice | Shadow prepaid offers, courier guidance, address clarification, and next-action recommendations | [DISPATCH_ADVICE.md](docs/DISPATCH_ADVICE.md) |
| Reputation network | Opt-in, hashed, governed, off by default, never affects dispatch | [NETWORK.md](docs/NETWORK.md) |

## Status & roadmap

COD-Guard is in active development toward paid seller pilots. Current
milestone: onboarding design-partner sellers for shadow-mode trials —
COD-Guard scores and verifies alongside the seller's existing process,
and savings are measured on real orders before anything is charged.
Also ahead: Daraz live intake (gated on a seller payload proving
buyer-phone access), Shopify App Store distribution, and the items
tracked in [the post-audit roadmap](docs/ROADMAP_POST_AUDIT.md).

Competitors in this space include ConfirmFlow, OrderWitness, Botaura
and DukaanFlow. COD-Guard claims no "first" — its case rests on the
published benchmark, the outcome learning loop, and covering the
channels above in one queue.
