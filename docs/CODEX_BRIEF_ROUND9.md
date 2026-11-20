# COD-Guard — Codex Mission Brief, Round 9: Real Data, Right-Side Up

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`. Direction set by the owner 20 Nov 2026:
**a sellable, deployed, production-ready system — not a classroom demo.**

## Why this round exists

The decision audit (research, 20 Nov) found the system's three real
weaknesses — none of them is "the model is too simple":

1. **The layering is upside down.** Production fraud systems (Stripe,
   Shopify, Razorpay pattern) score with a calibrated ML model first,
   band the score into actions, and keep rules as a thin policy layer
   on top. COD-Guard does the reverse: rules predict, models whisper.
2. **Training is synthetic-only.** A real Pakistani e-commerce dataset
   exists on Kaggle: ~272,000 real COD orders from ~115,000 real
   customers, PKR amounts, real cancellation/return outcomes.
3. **No live path.** Mapped in the audit (WhatsApp ≈ Rs 4.15 per
   confirmation on Meta's PK rate card; platform ≈ $30–80/month;
   Meta business verification is the long pole) — this round builds
   the foundations that don't depend on Meta.

## WS-0 — Land Round 8 first

Round 8 exists on local branch `codex/round8` (cc6b756). Open its PR,
the integrator verifies and merges it, and Round 9 branches from the
merged main. Do not stack Round 9 work on an unmerged Round 8.

## WS-A — The real dataset (handle with licence honesty)

- Acquire the Kaggle Pakistani e-commerce dataset (~272k orders).
  Record source, retrieval date, and licence status in
  `docs/DATA_SOURCES.md`. **Its licence is unstated**: development and
  evaluation use only. Never describe a model trained on it as
  production-ready; the production story stays per-seller training.
  Large files go to the Drive folder, never into git.
- Map its fields onto the COD-Guard order schema; document every
  mapping and every field that has no counterpart (ours or theirs).
- Splits must be leakage-safe: **by customer and by time** (a
  customer's later orders never train a model tested on their earlier
  ones). Freeze the test split, hash it, lock it — same discipline as
  the reply corpus.
- Our synthetic benchmark stays untouched as the second test set.
  Every reported number carries its tag: [PK-REAL] or [PK-SYNTH].

## WS-B — Flip the layers

- The trained model (gradient boosting, as today) becomes the primary
  scorer. Calibrate its probabilities (isotonic or Platt, chosen on
  validation) — a score of 0.8 must mean ~80% failure, measurably.
- Three action bands over the calibrated score: auto-dispatch /
  verify with buyer / hold for operator review. Band thresholds are
  chosen on validation by expected cost under the stated PKR cost
  assumptions, and are seller-adjustable policy, not constants.
- Rules are demoted to a **policy layer** on top: hard constraints
  only (a buyer's confirmed denial always holds; a verified
  confirmation releases a verification hold; an unreachable phone
  always routes to verify). Rules no longer produce the risk score.
- Every decision records: calibrated score, band, policy rules that
  fired, and the top contributing factors in plain words (SHAP-style
  attributions rendered as seller-readable reasons). The audit trail
  is a feature, not a log file.

## WS-C — The head-to-head (adoption gate)

- Contenders: the current rules-first system vs the flipped system.
- Test sets: BOTH the frozen [PK-REAL] holdout and the [PK-SYNTH]
  benchmark. Report per set, never blended.
- Metrics: committed-decision error rate, false holds, false ships,
  expected cost per 1,000 orders under the stated assumptions,
  calibration error.
- Gate: the flipped system is adopted only if it does not increase
  false holds beyond the bound set on validation AND reduces expected
  cost on both sets. Otherwise the flip ships in shadow and the
  report says why. Publish `docs/ROUND9_EVAL.md` either way.

## WS-D — Urdu voice: try the fine-tune

- Evaluate the Urdu fine-tuned Whisper variant identified in the
  audit against the stock model on the Round 8 voice set plus a new
  set of short confirmation-style clips (one-to-two-word replies are
  the production shape; the audit cites error on short utterances
  dropping from ~89% to ~24% with the fine-tune — verify, don't cite).
- Report WER and end-to-end intent accuracy per model. Adopt the
  better one; the demo stays offline either way.

## WS-E — Production foundations (the parts Meta can't block)

- Deployment packaging: the backend and dashboard run from a clean
  checkout via one documented command (container or equivalent),
  suitable for a $30–80/month host. Prove it from a clean clone.
- Tenant isolation and secrets audit: no cross-tenant reads, no
  secrets in the repo or logs, phone numbers masked by default —
  re-run the Round 4/6 checks against the flipped architecture.
- WhatsApp live sending stays gated on Meta business verification:
  ship the checklist and the configuration surface, not a fake send.

## Non-negotiables (unchanged, all rounds)

- Claim tags on every number; licence status stated wherever the
  Kaggle data is used; synthetic labelled synthetic.
- Gates are gates: a failed adoption gate means shadow mode and an
  honest report, never a quiet threshold edit.
- Exhibition mode still disables new features; the demo runs offline.

## Report back

WS-0 merge first. Then per workstream: what was built, the measured
numbers with their tags, and the full test count.
