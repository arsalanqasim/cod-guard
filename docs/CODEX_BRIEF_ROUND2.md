# COD-Guard — Round 2 brief for Codex (you still lead)

Round 1 (PR #1, merged) built the real system and an honest evaluation. This
round attacks the one measured weakness that matters — **FNR 59.23%** — and
stress-tests whether the headline comparison against COD-Guard is even fair.
Same rules as Round 1: you lead, Muse reviews/merges, the fixed honesty and
decision rules from `docs/CODEX_BRIEF.md` still bind.

## Measured starting point (synthetic holdout, served policy, untouched test)

- FPR 16.47%, FNR 59.23%, precision 71.85%, recall 40.77%
- Illustrative cost PKR 274,600 — beats ship-everything (390,650) and
  rules-only (293,800), loses to the aggressive any-adverse-signal baseline
  (259,800), which flags **71.5% of genuine orders**
- Pattern segment (fraud-linked phone / 3+ orders per day): recall 0.919 —
  the misses are concentrated in ordinary refusals, not organised fakes

## Workstream A — Put the verification layer inside the evaluation

Round 1 evaluated the flagging policy but not the product's actual FN/FP
recovery mechanism: a confirmation rescues a flagged genuine order, a denial
stops a passed fake. Model the full served system (score → zone → verify →
final decision) on the test split under **explicitly labelled customer-response
scenarios** — e.g. genuine customers confirm / fake-order customers deny,
ignore, or are unreachable, at several assumed rates — and report final
FP/FN/cost as a **sensitivity range across scenarios**, never as one number.
Assumptions are assumptions: the report must say these are scenario analyses,
not measured human behaviour. If a scenario needs a response model, derive its
parameters transparently from the scenario definition, not from the labels.

## Workstream B — Capacity-aware baseline comparison

The aggressive baseline "wins" on raw cost only by flagging 71.5% of genuine
orders — no real seller can verify or absorb that. Re-run the baseline
comparison under a **flag-rate budget** (e.g. at most 10%, 20%, 30% of orders
flagged for verification/holding) and under a stated per-verification cost,
and report which policy wins at each budget. If COD-Guard still loses at
realistic budgets, say so plainly and show where.

## Workstream C — Predictability ceiling of the synthetic world

Quantify how much of the ordinary-refusal FN mass is signal vs generator
noise: e.g. an oracle/ceiling analysis using the generator's own structure, or
feature-ablation on validation. The goal is a defensible sentence for the
stall: "of the failures, X% carry detectable pre-dispatch signal; the rest are
only catchable by contacting the customer — which is why verification exists."
If the ceiling analysis shows the model is already near the ceiling, say that;
if it shows headroom, take the headroom (validation-selected changes only).

## Guardrails (unchanged, plus two)

- No threshold or model selection on the test split — validation only, as
  established in Round 1.
- No invented human-response or merchant numbers presented as measurements;
  scenario parameters are labelled assumptions with sensitivity ranges.
- Synthetic stays labelled synthetic; competitors named without capability
  claims; no pilot claims.
- Two-signal rule and customer-decision overrides stay as they are.
- Keep the full test suite green and add tests for anything new that can break.

## Deliverables

One PR against main: updated `docs/EVAL_REPORT.md` (and AUDIT addendum) with
the three analyses, any serving-policy changes they justify, tests, and the
demo script updated only where the new numbers change what we may honestly
say at the stall.
