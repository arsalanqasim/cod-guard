# Round 10 evaluation

> **Round 11 cost-sensitivity addendum:** See [Cost-Model Sensitivity to Live Pakistan WhatsApp Pricing](COST_SENSITIVITY.md) for these holdout tables re-evaluated at live Meta Pakistan Utility rates (PKR 4.15 and PKR 12.45 vs. the PKR 50 assumption below). No served policy or result below was rewritten.

**Keep the current dispatch policy.** On [PK-REAL], no challenger found a
release threshold on validation, so each matched the incumbent's
modeled cost of **PKR 149,491 per 1,000 orders** on the frozen holdout.
On [PK-SYNTH], ranking orders within the same verification budget
produced **seven fewer false ships**. The paired interval includes
zero. The runner is an offline experiment. [Research and source review](ROUND10_RESEARCH.md)

## What we tested

- **[PK-REAL] Purchase history.** Join each order only to the same
  customer's strictly earlier COD purchase days. Use counts over the
  full history and last 30 and 90 days, number of active purchase days,
  days since the last purchase, and order amount relative to that
  customer's previous mean. Structurally valid baskets contribute
  purchases regardless of terminal status. Same-day and later purchases
  are excluded, and a new customer can have missing recency.
- **[PK-REAL] Basket details.** Test the number of source line items and
  distinct SKUs, largest reported nonnegative line discount, amount per
  item, and day of week. SKU values are counted within the basket.
  Compare these fields alone and combined with purchase history, using
  amount, quantity, and the existing repeat flag as the baseline.
- **[PK-REAL] Outcome proxies.** Add counts and smoothed failure rates
  for earlier terminal labels plus the last eligible day's failure
  fraction, with 30- and 90-day maturity assumptions. Validation can
  use only purchase dates through the end of training for these
  features. Test can use only purchase dates through the end of
  validation. The source lacks actual settlement and ingestion
  timestamps. These variants measure sensitivity to assumed
  availability.
- **[PK-SYNTH] Verification allocation.** Fit separate matched models
  with and without the generated delivered/refusal counts. Preserve
  incumbent holds and actions for invalid phones. Reassign the remaining
  verification slots to the highest estimated failure risks among
  reachable orders the incumbent would ship or verify. Also transfer
  the [PK-REAL] order-slip score and release rule as a portability check.

Each ablation uses the same regularized histogram gradient boosting
learner and logistic probability calibration within its source. Real
models fit on the unchanged 60,628-order training split. The first
3,300 chronological validation rows calibrate the scores, and the
remaining 3,281 choose a release cutoff. The real policy can release
an incumbent verification to shipping between estimated risks of
5% and 27%. It chooses the lowest modeled total cost among cutoffs
with at least 40 buyer clusters and a one-sided 95% cluster-adjusted
upper cost difference below zero on validation. The synthetic models
calibrate on the existing synthetic validation split. The runner
writes the real cutoffs and both split locks before scoring the
challengers on the frozen holdouts. [Real cohort construction](DATA_SOURCES.md) ·
[Synthetic benchmark protocol](METRIC_PROTOCOL.md)

The comparison retains Round 9's assumed costs of PKR 650 per false
ship, PKR 450 per false hold, and PKR 50 per verification. Verification
resolves 60% correctly in the main scenario. An unresolved genuine
order accrues a PKR 450 delay cost. An unresolved failed order stays
deferred. The frozen datasets have no contact or response logs,
so the scenario leaves a non-response unresolved. Under these
assumptions, shipping is cheaper than verification at a calibrated
failure probability below 27.7%. Paired 95% intervals use 2,000
bootstrap draws by customer for [PK-REAL] and by order for [PK-SYNTH].
They describe variation on these holdouts under the stated cost model.
[Round 9 assumptions and incumbent results](ROUND9_EVAL.md)

## [PK-REAL] Ranking improved modestly

6,211 frozen test orders from 4,036 customers, with 2,778 failure
proxies. Each proxy comes from a terminal order status, which can
include cancellation before dispatch. Every action policy verified all 6,211. The incumbent's
missing-evidence fallback did the same. There were zero false holds
and zero automated shipments across the policies.

On policy validation, even the widest release cutoff of 27% selected
between 8 and 44 orders per variant, from at most 33 buyers. The
combined basket and purchase model selected 17 orders from 16 buyers,
of which seven had a failed status. Every cutoff fell below the 40-buyer
minimum, so no candidate changed an action on the real holdout.

| Signal family | Average precision | ROC AUC | Recall at top 20% | Brier score |
| --- | ---: | ---: | ---: | ---: |
| Order slip and repeat flag | 0.5657 | 0.5958 | 27.80% | 0.2383 |
| Add purchase history | 0.5665 | 0.5951 | 27.66% | 0.2382 |
| Add basket details | 0.5753 | 0.6041 | 28.06% | 0.2377 |
| Add basket details and purchase history | **0.5788** | **0.6065** | **28.37%** | 0.2371 |
| Purchase history plus 30-day outcome proxies | 0.5718 | 0.6021 | 27.93% | **0.2367** |
| Purchase history plus 90-day outcome proxies | 0.5667 | 0.6010 | 27.92% | 0.2374 |

Basket details plus purchase history gave the highest observed average
precision, up **1.31 percentage points** from the order slip, with
**0.57 points** more recall at the same screening fraction. Purchase
history alone moved average precision from 0.5547 to 0.5592 among
2,727 orders with prior observed COD purchases. For the 3,484 orders
on a buyer's first observed COD day, average precision moved from
0.5728 to 0.5694. The 30-day outcome proxy reached 0.5780 on returning
orders. The observed effect was smaller with a 90-day lag. “First
observed” describes the archive's coverage.

## [PK-SYNTH] The same queue captured more failures in replay

1,184 frozen test orders with 601 generated failures. The incumbent
used 200 verification slots. The two re-rankers held that capacity and
kept the 141 holds, including 27 false holds, fixed.

| Policy | Ship / Verify / Hold | False ships | False holds | Modeled PKR per 1,000 | Paired delta vs incumbent (95% interval) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Incumbent | 843 / 200 / 141 | 356 | 27 | 224,637 | — |
| Transferred [PK-REAL] order-slip release rule | 843 / 200 / 141 | 356 | 27 | 224,637 | 0 (0 to 0) |
| Re-rank without customer outcomes | 843 / 200 / 141 | 351 | 27 | 221,132 | −3,505 (−12,936 to +6,901) |
| Re-rank with customer outcomes | 843 / 200 / 141 | 349 | 27 | **219,730** | **−4,907 (−15,043 to +5,305)** |
| Verify all, unconstrained reference | 0 / 1,184 / 0 | 0 | 0 | 138,632 | −86,005 (−106,073 to −65,667) |

Adding generated outcome counts raised average precision from 0.7022
to 0.7160 and recall at the top 20% from 29.78% to 30.62%. The
outcome-aware policy moved 77 orders into verification and released 77
to shipping. Of the releases, 45 were generated failures. Its modeled
cost delta stayed negative at the four tested resolution rates.
The verify-all reference uses 984 more slots than the incumbent.

| [PK-SYNTH] Correct verification resolution assumption | 20% | 40% | 60% | 80% |
| --- | ---: | ---: | ---: | ---: |
| Outcome-aware re-ranking delta, modeled PKR per 1,000 | −5,971 | −5,439 | −4,907 | −4,375 |

The portable order-slip scores ranked near chance on [PK-SYNTH]
(ROC AUC 0.4961). The real and synthetic ablations measured different
history features. In particular, the synthetic generator supplies
prior outcomes, while the archive supports reliably dated purchases
and assumed maturity for outcome proxies.

## What evidence would move the decision

The real data points to richer basket signals for first-observed buyers
and outcome history for returning buyers. The practical hypothesis is
that tiering a finite verification queue with **timestamped,
seller-local outcomes** can beat the current allocation. A merchant
dataset would need orders as observed at intake, settlement and
ingestion times, verification attempts, replies, dispatch actions, and
terminal courier or payment outcomes. Linkage through verified contact
keys would require separately authorized data. Test any linkage lift
on a later time window with isolated identity components.

Measure live interventions against a documented seller baseline, with
assignment recorded and existing safety rules in both groups. Track
verification capacity, false holds, delivered orders per eligible
order, and cost including non-response and late resolution. Graph
links, partial payments, and message changes remain unmeasured on
these holdouts. [Research and intervention evidence](ROUND10_RESEARCH.md)

## Reproduce

Use the project requirements and the private Kaggle version 2 archive
from Round 9. The licence is unstated. Keep the archive and private
evaluation files outside Git.

```text
python scripts/evaluate_round10.py PATH_TO_PRIVATE_KAGGLE_ZIP --output-dir PATH_TO_NEW_PRIVATE_DIRECTORY
python scripts/build_demo.py --verify-only
```

The evaluator checks both existing locks and writes aggregate
`plan.json` and `results.json` to a new directory. The verification
command uses the local demo artifacts. A clean checkout can create
those artifacts and run all checks with `python scripts/build_demo.py`.
Two local runs produced identical `results.json` bytes with Python
3.13.3 and the pinned dependencies. The SHA-256 was
`95350cb8072adc92f4e8ab91c05ccbcec06fa94972cd529a9edccf319f8a3a86`.
