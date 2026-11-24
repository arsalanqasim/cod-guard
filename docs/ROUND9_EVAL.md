# Round 9 evaluation

> **Round 11 cost-sensitivity addendum:** See [Cost-Model Sensitivity to Live Pakistan WhatsApp Pricing](COST_SENSITIVITY.md) for these holdout tables re-evaluated at live Meta Pakistan Utility rates (PKR 4.15 and PKR 12.45 vs. the PKR 50 assumption below). No served policy or result below was rewritten.

**The model-first policy stays in shadow.** It met the false-hold bound
and tied the incumbent’s modeled cost on [PK-REAL]. The gate requires
lower expected cost on both holdouts. The [PK-REAL] licence is unstated
and limits this work to development evaluation. The packaged shadow
path is for tenant-bound artifacts from the seller’s own data.
[Source and projection](DATA_SOURCES.md)

## Method and validation

[PK-REAL] Fit gradient boosting on the frozen 60,628-order train cohort.
Use the first 3,300 chronological validation orders to fit Platt and
isotonic calibration and the next 3,281 to select by Brier score and set
policy bands. Isotonic scored **0.23685** versus **0.23771** for Platt.
The incumbent put every validation order into verification because the
source lacks the serving evidence fields. Its false-hold rate set the
bound at **0%** of genuine orders. Under that bound, validation picked
the lowest modeled cost on a fixed threshold grid. The selected bands
start verification at **0.0%** and operator hold at **97.5%**. Both
holdouts use exactly those bands and the same calibrated model.

The [PK-REAL] incumbent uses the served rules and unknown-feature
fallback with the mapped fields actually present. Its learned score is
unavailable on this projection. The [PK-SYNTH] incumbent uses the served
rules-first model fitted on the benchmark’s original training split.
The candidate’s explicit unreachable-phone rule uses the field wherever
available. Historic inputs contain no buyer confirmations or denials.

For both [PK-REAL] and [PK-SYNTH], the cost model assumes PKR 650 per
false ship, PKR 450 per false operator hold, and PKR 50 per verification
attempt. It assumes verification correctly resolves 60% of cases.
Unresolved cases stay deferred. Genuine unresolved cases incur the
same PKR 450 delay penalty. These are made-up scenario costs and
resolution assumptions. Committed error uses only SHIP and HOLD as
its denominator. A false hold is a genuine order assigned HOLD. A
false ship is a failed order assigned SHIP.

## Holdout results

| Holdout | Policy | Ship / Verify / Hold | Committed errors | False holds | False ships | Expected PKR per 1,000 | ECE / Brier |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| [PK-REAL] | Current rules-first | 0 / 6,211 / 0 | Undefined, zero commits | 0/3,433 genuine | 0/2,778 failed | 149,491.23 | Unavailable |
| [PK-REAL] | Model-first | 0 / 6,211 / 0 | Undefined, zero commits | 0/3,433 genuine | 0/2,778 failed | 149,491.23 | 0.02527 / 0.24091 |
| [PK-SYNTH] | Current rules-first | 843 / 200 / 141 | 383/984 (38.92%) | 27/583 genuine | 356/601 failed | 224,636.82 | 0.02608 / 0.20679 |
| [PK-SYNTH] | Model-first | 0 / 1,184 / 0 | Undefined, zero commits | 0/583 genuine | 0/601 failed | 138,631.76 | 0.12439 / 0.26569 |

[PK-REAL] The cost difference was zero. [PK-SYNTH] The cost difference
comes from deferring every order and assuming the stated verification
effectiveness. The comparison gives no evidence of better automatic
shipping. The candidate assigned no scores in the 0.75–0.85 range on
either holdout, so the observed failure rate around 0.8 is unmeasured.
The higher [PK-SYNTH] ECE also indicates calibration drift when crossing
from real data to the synthetic distribution.

## Shadow behavior

The seller-specific score bands are configurable. Confirmed denial
holds the order. An unreachable phone routes to verification and a
verified confirmation releases a verification hold when phone and
storefront policy allow it. Risk reasons are additive movements in
the gradient-boosted model’s raw log odds along its tree paths. A
positive or negative contribution indicates model influence. The
calibrated score, band, fired policy constraints, contribution reasons,
model ID, active thresholds and actual dispatch decision appear in the
authenticated revision history. The existing dispatch decision continues
to serve after the failed gate. [Hosting and tenant configuration](HOSTING.md)

## Reproduce

```text
python scripts/evaluate_round9.py PATH_TO_PRIVATE_KAGGLE_ZIP --report PATH_TO_PRIVATE_JSON_RESULT
```

The repository ships the frozen lock. The command verifies it before
training. The raw data stays local under the unstated licence.
