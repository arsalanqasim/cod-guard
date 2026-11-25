# Round 10 — Break the ceiling (open brief)

This is not a task list. This is our code, our problem, and our goal.
How you attack it — research directions, methods, experiments, order of
work — is entirely yours. You are the frontier model on this team; we
are not going to pretend we know the route better than you do.

## The product

COD-Guard is a pre-dispatch intelligence platform for Pakistani
e-commerce sellers who ship cash-on-delivery. It scores orders before
dispatch, verifies risky ones with the buyer over WhatsApp (text and
Urdu voice), learns from courier outcomes, and gives the seller a
dispatch decision with plain-words reasons. The full system is in this
repo: risk engine, verification agent, courier outcome loop, Daraz /
WooCommerce / Shopify / social-DM intake, dashboard, benchmark suite.
Read it. Audit it. Restructure anything you think is wrong.

## The ceiling we keep hitting

Every approach we have tried lands in the same place:

- Served policy on our synthetic holdout: false-positive rate 16.47%,
  false-negative rate 59.23%.
- On a frozen holdout of 6,211 real Pakistani e-commerce orders
  (3,433 genuine / 2,778 failed), a gradient-boosting model-first
  policy and our rules-first policy cost a modeled PKR 149,491 per
  1,000 orders — an exact tie.
- An oracle experiment (a model told the true data-generating process)
  gained only ~0.51 percentage points of recall at equal capacity;
  352 of 356 misses are ordinary-looking orders.
- Every challenger — rules, GBDT, fine-tuned MiniLM, fastText,
  ensembles, a specialised Urdu speech model — has been measured on
  frozen test sets and none has beaten the incumbent on the decisions
  that cost money. Details are in docs/BENCHMARK.md, docs/EVAL_REPORT.md
  and docs/ROUND9_EVAL.md.

Our current belief is that the ceiling is in the information, not the
model: a fake buyer and a genuine buyer produce identical order slips,
and everything we have built reads the slip. That belief is a
hypothesis, not a law. Prove it wrong if you can.

## The goal

Cross the ceiling. Find the edge our competitors do not have — every
Pakistani rival we studied sells workflow (confirmation messages,
dashboards) and not one publishes a measured accuracy evaluation. We
want a platform that is genuinely incredible: measurably better at the
decision that costs sellers money, sellable on real worth, not on
claims. Do your own deep research — production systems, papers,
whatever you can find — and bring back insights and measured results
on how this project breaks through.

## What you have to work with

- This repo and its full history, including every failed challenger
  and why it failed.
- A public Pakistani e-commerce dataset held locally outside git
  (~1.05M rows, ~272k COD orders, ~115k customers, median order
  ~Rs 1,960). Its licence is unstated — research and evaluation use
  only. Round 9 built leakage-safe splits (by customer and by time)
  and a frozen, hash-locked holdout from it; see docs/DATA_SOURCES.md
  and docs/ROUND9_EVAL.md.
- A frozen 493-reply trilingual buyer-reply corpus, a 24-clip Urdu
  voice evaluation set, and the synthetic benchmark generator.
- The cost model used throughout: PKR 650 per false ship, PKR 450 per
  false hold, PKR 50 per verification attempt.

## The only non-negotiables

These are not method limits; they are the honesty rules this product
is sold on, and they are the professor's requirements:

- No invented numbers, pilots, savings, or accuracy. If a claim is
  measured, say on what; if it is a vendor's claim, label it as one.
- Real vs synthetic stays labelled everywhere ([PK-REAL] / [PK-SYNTH]
  tags exist for this).
- A claimed win has to survive the frozen holdouts — that is what
  makes it a win and not a story. How you earn it is up to you.

Everything else is open: new signals, new model classes, new problem
framings, interventions instead of predictions, things we have not
thought of. Surprise us.

## One research lead, offered not assigned

An independent research pass (2026-11-21) found the strongest
published ceiling-breaker to be Meesho's TRUST system (AAAI 2026): an
identity graph linking buyers by shared phone/email/device, plus order
history, beat their XGBoost baseline by ~10 points of precision, and
helped even buyers with no failure history — though their best model
is still far from perfect. Flipkart's WWW'23 work points the same way:
history features carry the lift. Verify, extend, or ignore this as
your own research dictates.

## Deliverable

A PR against main with whatever you build and measure, plus a written
account a sceptical professor cannot pull apart: what you tried, what
the frozen holdouts said, and what you now believe the edge is. If
nothing crosses the ceiling, the precise map of how far each attempt
got is itself a deliverable — but aim higher than that.
