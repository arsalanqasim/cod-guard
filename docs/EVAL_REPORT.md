# COD-Guard — FP/FN evaluation

**SYNTHETIC BENCHMARK — no real merchant records or pilots.**

Reference figures supplied in the mission brief: OrderNation (~170k orders), 37.3% COD cancelled and ~49/100 cash collected. These are different measures. We target 51% expected non-collection, not 37.3% cancellation. Individual feature relationships remain synthetic assumptions.

Generated rows: 6000; empirical failure rate: 50.7000%. Benchmark SHA-256: `b03474a56979d6f86a0b1794ddaefcd2d4925ab63ea1f622942c3211854719b7`.

Model `cg-0328b4106253`: regularized_gradient_boosting, version 1. Training 3552 / validation 1184 / test 1184. 80 demo orders reserved outside all three splits; 0 marked demo outcomes added to training.

## Method

Models and operating thresholds are selected on **validation only**. The test split is untouched during selection. The reported flag is the actual serving policy: rules + the saved ML threshold + the two-independent-signal guard. Both address checks count as one signal. A lone signal cannot hold or require verification; ML alone is not another independent signal. Confirmation overrides a flag; denial overrides a pass.

Cost assumptions: false negative PKR 650; false positive PKR 450. These are illustrative costs, not measured merchant losses. Any non-GREEN recommendation is counted as flagged, even though verification can later recover a genuine order.

## Frozen operating point on the test split

Validation-selected threshold **0.50**. TP=245, FP=96, FN=356, TN=487. FPR **16.47%**; FNR **59.23%**; precision 71.85%; recall 40.77%. Illustrative cost PKR 274,600.

## Baselines on the same test orders

| Policy | TP | FP | FN | TN | FPR | FNR | Illustrative cost PKR |
|---|---:|---:|---:|---:|---:|---:|---:|
| ship_everything | 0 | 0 | 601 | 583 | 0.000 | 1.000 | 390,650 |
| block_any_adverse_signal | 490 | 417 | 111 | 166 | 0.715 | 0.185 | 259,800 |
| rules_only_two_signal_policy | 194 | 65 | 407 | 518 | 0.111 | 0.677 | 293,800 |
| serving_policy | 245 | 96 | 356 | 487 | 0.165 | 0.592 | 274,600 |

## Test threshold trade-off (diagnostic, not used to select the threshold)

| Threshold | TP | FP | FN | TN | FPR | FNR | Illustrative cost PKR |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.25 | 269 | 130 | 332 | 453 | 0.223 | 0.552 | 274,300 |
| 0.30 | 262 | 116 | 339 | 467 | 0.199 | 0.564 | 272,550 |
| 0.35 | 257 | 110 | 344 | 473 | 0.189 | 0.572 | 273,100 |
| 0.40 | 252 | 110 | 349 | 473 | 0.189 | 0.581 | 276,350 |
| 0.45 | 247 | 106 | 354 | 477 | 0.182 | 0.589 | 277,800 |
| 0.50 | 245 | 96 | 356 | 487 | 0.165 | 0.592 | 274,600 |
| 0.55 | 233 | 93 | 368 | 490 | 0.160 | 0.612 | 281,050 |
| 0.60 | 226 | 81 | 375 | 502 | 0.139 | 0.624 | 280,200 |
| 0.65 | 209 | 73 | 392 | 510 | 0.125 | 0.652 | 287,650 |
| 0.70 | 202 | 67 | 399 | 516 | 0.115 | 0.664 | 289,500 |
| 0.75 | 198 | 65 | 403 | 518 | 0.111 | 0.671 | 291,200 |
| 0.80 | 195 | 65 | 406 | 518 | 0.111 | 0.676 | 293,150 |
| 0.85 | 194 | 65 | 407 | 518 | 0.111 | 0.677 | 293,800 |

## Validation candidate comparison

| Model | Selected threshold | Validation FPR | Validation FNR | Validation cost PKR |
|---|---:|---:|---:|---:|
| regularized_gradient_boosting | 0.50 | 0.163 | 0.571 | 265,700 |
| gradient_boosting | 0.45 | 0.170 | 0.569 | 266,850 |
| logistic_regression | 0.55 | 0.153 | 0.582 | 267,550 |

## Pattern and city checks

The fraud-linked-phone / 3+ orders-per-day segment is an observable pattern, not ground truth that an order is deliberately fraudulent.
Pattern n=233, recall=0.919, FNR=0.081.

| City | Rows | FPR | FNR |
|---|---:|---:|---:|
| Faisalabad | 129 | 0.111 | 0.627 |
| Hyderabad | 113 | 0.185 | 0.542 |
| Islamabad | 127 | 0.127 | 0.656 |
| Karachi | 107 | 0.250 | 0.582 |
| Lahore | 126 | 0.103 | 0.588 |
| Multan | 129 | 0.232 | 0.483 |
| Peshawar | 89 | 0.163 | 0.700 |
| Quetta | 134 | 0.151 | 0.492 |
| Rawalpindi | 112 | 0.143 | 0.694 |
| Sialkot | 118 | 0.188 | 0.600 |

## Limits and brief conflicts

- All examples are synthetic; there are no merchant pilots or production accuracy claims.
- Failed labels combine non-collection/refusal/cancellation; they do not establish deliberate fraud.
- Benchmark generator and cost assumptions do not reproduce any merchant population.
- Verification overrides are demonstrated by functional tests, not simulated as perfect human responses.
- Marked demo outcomes are demonstrations, not prospectively collected field evidence.
- The original generator produced 27.5% failure despite its calibration claim; its 4.88% FPR / 62.23% FNR report selected a threshold on test data and did not evaluate the served policy. The new calibration and split differ, so old and new percentages are not a like-for-like improvement claim.
- No low-FP-and-low-FN production claim is supported. Unpredictable refusals remain a material false-negative risk.
- Competitors: Tasdeek, Botaura, OrderWitness, DukaanFlow. No claim of being first or of competitor capabilities.
