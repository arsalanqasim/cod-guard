# CODEX BRIEF — Round 10: Break the predictability ceiling

You lead this round. Audit, research, experiment, restructure — your call.
The mission is not another model on the same features. The mission is to
find NEW INFORMATION that separates failing COD orders from genuine ones,
measure exactly how much it is worth, and beat the incumbent numbers if —
and only if — the frozen holdouts say so.

## Where we stand (verified, on main)

- Served policy on the synthetic holdout: FPR 16.47%, FNR 59.23%.
- Round 9 head-to-head on the frozen [PK-REAL] holdout (6,211 orders,
  3,433 genuine / 2,778 failed): model-first and rules-first both cost a
  modeled **PKR 149,491.23 per 1,000 orders** — an exact tie. The flip
  stayed in shadow.
- Round 2 oracle analysis: a generator-informed oracle gains only
  ~0.51pp expected recall at equal capacity; 352 of 356 misses sit in the
  ordinary stratum. Every challenger so far (rules, GBDT, MiniLM,
  fastText, ensembles) has read the SAME order-intrinsic fields: name,
  phone, address text, items, price, seller history aggregates already
  in the record.
- Working hypothesis for this round: the ceiling is information-bound,
  not model-bound. A fake buyer and a genuine buyer produce identical
  order slips. What they do NOT produce identically is a past.

Cost model (unchanged everywhere): PKR 650 false ship, PKR 450 false
hold, PKR 50 per verification attempt, verification resolves 60%.

## WS-0 — Feature audit (do first, it is quick)

List exactly which features the Round 9 shadow scorer and the served
policy consume today. Publish the list in docs/ROUND10_EVAL.md. Every
signal family NOT on that list is a candidate for this round. Do not
assume; read the code.

## WS-1 — Research: what do production systems know that we don't?

Write docs/CEILING_RESEARCH.md. Cover, with sources:

- GoKwik, Razorpay, Shopify fraud systems, Stripe Radar, and any
  South-Asian COD-verification vendors: which signals beyond the order
  form do they use? (Cross-merchant identity/reputation graphs,
  phone-number intelligence, address deliverability history, device and
  behavioural signals, courier-side delivery history by address/area.)
- Published RTO / delivery-failure studies: which feature families
  dominate importance rankings, and what performance ranges are
  reported?
- Verification-in-the-loop evidence: measured effect of pre-dispatch
  confirmation (and of the response behaviour itself) on final failure
  rates.
- Intervention evidence: partial prepayment, courier selection,
  address/slot confirmation — measured effects on COD failure.

Mark every number as vendor-claimed or independently measured. For each
signal: is it obtainable by a small third-party tool, or only by a
platform with network scale? Map each obtainable signal to the
experiment below that tests it, or state plainly why it cannot be
tested on our data.

## WS-2 — Customer-history features on [PK-REAL] (the main experiment)

The Kaggle Pakistan dataset holds ~272k COD orders across ~115k
customers. A customer's past is information the order slip does not
contain. Build leakage-safe history features and measure them:

- Feature families: customer prior order count, prior failure rate,
  recency, tenure, order-value trajectory; phone reuse across orders;
  address reuse and address-cluster prior outcome rate; city/area prior
  outcome rate. Every feature for an order computed ONLY from orders
  strictly earlier than it. No exceptions.
- Splits: the existing frozen [PK-REAL] holdout stays frozen and
  untouched during design; development on the train side only, keeping
  the by-customer and by-time discipline from Round 9.
- Ablations, same GBDT + calibration stack as Round 9: (a) intrinsic
  features only (reproduce the tie), (b) history features only,
  (c) both. Report expected cost per 1,000 orders, FPR, FNR at matched
  flagging capacity, on the frozen holdout, for each ablation.
- Also report the cold-start slice separately: first-time customers
  have no history — how much of the holdout are they, and what does
  the policy do with them?

## WS-3 — Measure the decision the seller actually experiences

Pre-reply FNR is not the seller's outcome; the post-verification
dispatch decision is. Using the WS-1 evidence, replace the single
assumed reply-rate set in the scenario analysis with a justified
sensitivity grid, and report final dispatch FPR/FNR and expected cost
after the verification stage, clearly labelled as scenario analysis
with its assumptions. If WS-1 finds no defensible rates, say so and
keep the existing grid — do not invent rates.

## WS-4 — Intervention, not just prediction

Extend the Round 8 shadow work: using courier outcome history by
address cluster and the prepaid-offer simulation, estimate which
orders are persuadable rather than merely risky. Simulation only,
assumptions stated, labelled [PK-SYNTH] / [PK-REAL] as applicable.
No live behaviour changes.

## The gate — what "breaking the ceiling" means

A challenger breaks the ceiling only if, on the frozen [PK-REAL]
holdout, expected cost per 1,000 orders falls by at least 10% versus
PKR 149,491.23 at no worse false-hold rate, AND it improves
non-degenerately on [PK-SYNTH] (a win obtained by deferring every
order to verification does not count — Round 9 already caught that).

- If a challenger passes: promote it through the Round 9 flip protocol
  (shadow → served, full audit trail: score, band, fired rules, top
  factors in plain words).
- If none passes: docs/ROUND10_EVAL.md reports the measured lift of
  each signal family separately — a partial, real lift is a result —
  names the closest challenger, and states what data would be needed
  next. A precise negative is a deliverable; an inflated positive is
  a defect.

## Addendum (2026-11-21) — independent web research, fold into WS-1

A parallel research pass over production systems and papers landed the
same day as this brief. Treat its findings as leads to verify in WS-1,
not as settled fact — but two results are strong enough to shape the
experiments now:

- **Meesho TRUST (AAAI 2026 paper + engineering blog):** a heterogeneous
  identity graph (users linked by shared phone/email/device/bank IDs)
  plus a sequence model over order history beat XGBoost on the same
  task: precision 68.3% vs 58.7%, AUCPR 0.47 vs 0.34. Critically, the
  graph helped even users with ZERO prior failures (AUCPR 0.27 → 0.36)
  and cold-start users (0.28 → 0.34) — linkage itself is information.
  Note their best AUCPR is still 0.47: the ceiling is real everywhere;
  the graph moves it, it does not remove it.
- **Flipkart (WWW'23):** history features (user/product/seller/pincode
  RTO ratios) were the base model; adding external features lifted
  recall ~20pp at similar precision. History features beating
  order-intrinsic features is the consistent pattern across studies;
  reported delivery-failure AUCs cluster at 0.70–0.84.

Consequences for WS-2: build the identifier clusters (phone ↔ address
↔ name) as connected components, and make the splits
**component-disjoint as well as customer- and time-disjoint** — if the
lift only appears under random splits, it is leakage, not signal.
Report the linked vs unlinked slices separately; expect the lift to
concentrate in linked/repeat buyers and to be ~zero for unlinked
first-timers, and say so if that is what the data shows.

One more protocol requirement, for WS-3: non-response is not refusal.
Any honest costing of the verification policy needs a ship-anyway
control slice of non-responders (Flipkart used a 5% no-intervention
control). We cannot run that live, but the scenario analysis must
state what the policy assumes about non-responders and how sensitive
the result is to that assumption.

And a WS-4 lead: the most credible causal intervention found is a
small risk-tiered partial prepayment (one published case: a ₹99
deposit cut RTO from 24.3% to 11% while delivered orders per 1,000
checkouts rose). The raw COD-vs-prepaid gap (7–13×) is mostly
self-selection — never present it as the intervention's effect.

## Non-negotiables

- Frozen splits and hashes unchanged. No feature design, threshold
  choice, or model selection on the test split.
- Every number carries its claim tag: [PK-REAL], [PK-SYNTH], or
  scenario-with-assumptions. The Kaggle dataset's licence is unstated:
  R&D and evaluation use only, and say so in the docs.
- No invented pilots, savings, or accuracy. Vendor claims labelled as
  vendor claims.
- Full test suite green; new measurements reproducible from a clean
  checkout (large data stays out of git, per the existing convention).
- Deliverables: docs/CEILING_RESEARCH.md, docs/ROUND10_EVAL.md, code +
  tests on a codex/round10 branch, PR against main.
