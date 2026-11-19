# COD-Guard — FP/FN evaluation

**SYNTHETIC BENCHMARK — no real merchant records or pilots.**

OrderNation reports approximately 49–57 cash collections per 100 COD orders and 37.3% COD cancellation across different measurement windows at one retailer. The generator uses the low end of the cash-collection range to target 51% expected non-collection. Feature relationships are simulation assumptions.

Generated rows: 6000; empirical failure rate: 50.7000%. Benchmark SHA-256: `b03474a56979d6f86a0b1794ddaefcd2d4925ab63ea1f622942c3211854719b7`.

Model `cg-0328b4106253`: regularized_gradient_boosting, version 1. Training 3552 / validation 1184 / test 1184. 80 demo orders reserved outside all three splits; 0 marked demo outcomes added to training.

## Method

Models and operating thresholds are selected on **validation only**. The test split is untouched during selection. Any AMBER or RED recommendation before a reply counts as a flag. With complete features the serving policy requires two distinct adverse signal groups. Both address checks share one group. ML refines the estimate. Confirmation overrides a flag and a denial overrides a pass.

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

## Round 2A · Verification sensitivity on SYNTHETIC orders

Scenario analysis uses hypothetical recognized intents. It measures neither human behavior nor speech recognition accuracy. The service's existing decision function maps confirmation to SHIP and denial to HOLD_CANCEL. Unclear, ignored or unreachable replies keep the zone's default. The contact plan uses only the zone: every non-GREEN order gets an attempt except in the zero-outreach control. GREEN outreach is uniform at the stated rate, independent of the outcome. This estimates what could happen if otherwise-passing orders also received a confirmation prompt.

The confirm/deny rates are fixed inputs specified below for each synthetic outcome group and applied only after outreach is assigned. No rates are fitted to benchmark labels. Rates apply per attempt to a valid phone. Invalid phones receive no usable intent, but still incur the assumed attempt cost. The remaining probability is no usable reply. Confirmations from failed orders and denials from genuine orders are allowed. Counts and costs are exact expectations under the assumptions, so counts may be fractional. There is no sampling uncertainty estimate for the scenario assumptions.

Illustrative cost includes FP/FN costs and PKR 50 per attempted contact. An unresolved verification request is counted as held at the dispatch decision point.

| Scenario | GREEN outreach | Genuine confirm / deny | Failed confirm / deny | Attempts | Expected FP | Expected FN | FPR | FNR | Cost PKR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no outreach | 0% | 0% / 0% | 0% / 0% | 0.0 | 96.00 | 356.00 | 16.47% | 59.23% | 274,600.00 |
| flags only low | 0% | 35% / 2% | 8% / 10% | 341.0 | 66.60 | 371.04 | 11.42% | 61.74% | 288,196.00 |
| flags only mid | 0% | 60% / 2% | 10% / 25% | 341.0 | 45.60 | 374.80 | 7.82% | 62.36% | 281,190.00 |
| limited green mid | 20% | 60% / 2% | 10% / 25% | 509.6 | 47.47 | 357.50 | 8.14% | 59.48% | 279,215.60 |
| broad outreach mid | 100% | 60% / 2% | 10% / 25% | 1,184.0 | 54.94 | 288.30 | 9.42% | 47.97% | 271,318.00 |
| broad outreach high | 100% | 80% / 1% | 6% / 45% | 1,184.0 | 33.47 | 211.58 | 5.74% | 35.20% | 211,788.50 |
| broad outreach adverse | 100% | 35% / 8% | 30% / 8% | 1,184.0 | 103.96 | 384.72 | 17.83% | 64.01% | 356,050.00 |

Across these six outreach assumptions, FPR is **5.74% to 17.83%**, FNR is **35.20% to 64.01%**, and illustrative cost is **PKR 211,788.50 to 356,050.00**. Flags-only outreach rescues some genuine holds and lets some failed orders through when they confirm. The passed orders still ship. At the same mid-rate assumptions, broad outreach changes FNR from **62.36%** to **47.97%**. Its cost and errors rise under the adverse reply assumptions.

## Round 2B · Equal flag budgets on SYNTHETIC orders

Every flag consumes one attempted verification. Caps are 10%, 20%, and 30% of orders, rounded down separately in each batch. For each policy, cap, price and response setting, validation chooses among 0%, 25%, 50%, 75%, and 100% of its permitted slots. The choice is frozen before scoring the test batch. Rankings use available pre-dispatch features only, with SHA-256 of order ID as a deterministic tie-break. The test winners are retrospective comparisons. Validation winners are listed separately.

Any signal ranks orders with at least one adverse group by rule points. Two-signal rules uses the same points with a two-group minimum. The capped served policy ranks its existing AMBER/RED pool by model probability. Two-signal ML ranking gives the model the entire two-group pool to rank. These are batch comparisons. The service still uses its original threshold and decision rules.

PKR 0, 50 and 100 per flag are illustrative. Each policy faces the same two response settings. With no usable reply, flags remain held. With the flags-only mid assumption from A, every flag can receive an override at the same assumed rates, including the baseline flags. Passed orders receive no contact in B.

| Response setting | Cap | Charge PKR | Validation winner(s) | Test winner(s) | Test cost PKR |
|---|---:|---:|---|---|---:|
| no usable reply | 10% | 0 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 332,650.00 |
| no usable reply | 10% | 50 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 338,550.00 |
| no usable reply | 10% | 100 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 344,450.00 |
| no usable reply | 20% | 0 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 293,350.00 |
| no usable reply | 20% | 50 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 305,150.00 |
| no usable reply | 20% | 100 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 316,950.00 |
| no usable reply | 30% | 0 | Two-signal ML ranking | Two-signal ML ranking | 273,200.00 |
| no usable reply | 30% | 50 | Two-signal ML ranking | Two-signal ML ranking | 290,950.00 |
| no usable reply | 30% | 100 | Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 308,700.00 |
| flags only mid | 10% | 0 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 333,895.00 |
| flags only mid | 10% | 50 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 339,795.00 |
| flags only mid | 10% | 100 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 345,695.00 |
| flags only mid | 20% | 0 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 290,525.00 |
| flags only mid | 20% | 50 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 302,325.00 |
| flags only mid | 20% | 100 | Capped served policy, Two-signal ML ranking | Capped served policy, Two-signal ML ranking | 314,125.00 |
| flags only mid | 30% | 0 | Two-signal ML ranking | Two-signal ML ranking | 261,100.00 |
| flags only mid | 30% | 50 | Two-signal ML ranking | Two-signal ML ranking | 278,850.00 |
| flags only mid | 30% | 100 | Two-signal ML ranking | Two-signal ML ranking | 296,600.00 |

Results at PKR 50 per attempt:

| Response setting | Cap | Policy | Flags (% of orders) | FPR | FNR | Cost PKR |
|---|---:|---|---:|---:|---:|---:|
| no usable reply | 10% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| no usable reply | 10% | Any signal | 118 (9.97%) | 3.95% | 84.19% | 345,150.00 |
| no usable reply | 10% | Two-signal rules | 118 (9.97%) | 3.95% | 84.19% | 345,150.00 |
| no usable reply | 10% | Capped served policy | 118 (9.97%) | 2.92% | 83.19% | 338,550.00 |
| no usable reply | 10% | Two-signal ML ranking | 118 (9.97%) | 2.92% | 83.19% | 338,550.00 |
| no usable reply | 20% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| no usable reply | 20% | Any signal | 236 (19.93%) | 10.46% | 70.88% | 316,150.00 |
| no usable reply | 20% | Two-signal rules | 236 (19.93%) | 10.12% | 70.55% | 313,950.00 |
| no usable reply | 20% | Capped served policy | 236 (19.93%) | 8.75% | 69.22% | 305,150.00 |
| no usable reply | 20% | Two-signal ML ranking | 236 (19.93%) | 8.75% | 69.22% | 305,150.00 |
| no usable reply | 30% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| no usable reply | 30% | Any signal | 355 (29.98%) | 18.01% | 58.40% | 293,150.00 |
| no usable reply | 30% | Two-signal rules | 355 (29.98%) | 19.38% | 59.73% | 301,950.00 |
| no usable reply | 30% | Capped served policy | 341 (28.80%) | 16.47% | 59.23% | 291,650.00 |
| no usable reply | 30% | Two-signal ML ranking | 355 (29.98%) | 17.67% | 58.07% | 290,950.00 |
| flags only mid | 10% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| flags only mid | 10% | Any signal | 118 (9.97%) | 2.20% | 85.37% | 345,175.00 |
| flags only mid | 10% | Two-signal rules | 118 (9.97%) | 2.20% | 85.37% | 345,175.00 |
| flags only mid | 10% | Capped served policy | 118 (9.97%) | 1.68% | 84.34% | 339,795.00 |
| flags only mid | 10% | Two-signal ML ranking | 118 (9.97%) | 1.68% | 84.34% | 339,795.00 |
| flags only mid | 20% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| flags only mid | 20% | Any signal | 236 (19.93%) | 5.42% | 72.91% | 310,850.00 |
| flags only mid | 20% | Two-signal rules | 236 (19.93%) | 5.28% | 72.63% | 309,385.00 |
| flags only mid | 20% | Capped served policy | 236 (19.93%) | 4.43% | 71.40% | 302,325.00 |
| flags only mid | 20% | Two-signal ML ranking | 236 (19.93%) | 4.43% | 71.40% | 302,325.00 |
| flags only mid | 30% | Ship everything | 0 (0.00%) | 0.00% | 100.00% | 390,650.00 |
| flags only mid | 30% | Any signal | 355 (29.98%) | 8.95% | 61.51% | 281,545.00 |
| flags only mid | 30% | Two-signal rules | 355 (29.98%) | 9.81% | 62.78% | 288,735.00 |
| flags only mid | 30% | Capped served policy | 341 (28.80%) | 7.82% | 62.36% | 281,190.00 |
| flags only mid | 30% | Two-signal ML ranking | 355 (29.98%) | 8.20% | 61.33% | 278,850.00 |

The evaluation JSON contains per-policy counts and validation utilization for every charge. These comparisons depend on the specified rankings, sample, cost weights and assumed responses.

## Round 2C · Generator-based predictability ceiling

The optimistic oracle knows the generator's latent cluster and structural logit, including its fixed calibration offset. It integrates out the private per-order Gaussian draw with 24-point Gauss–Hermite quadrature and cannot see the final Bernoulli draw. Its risk ranking is optimal for expected failures caught at a fixed budget. Latent cluster membership is unavailable in serving. Oracle data is reconstructed separately from the generator, checked against the benchmark, and excluded from fitting, model selection and the model bundle.

| Split | Served flags | Served expected recall | Oracle, two-signal eligible | Oracle, unrestricted |
|---|---:|---:|---:|---:|
| validation | 353 (29.81%) | 41.06% | 41.58% | 43.12% |
| test | 341 (28.80%) | 40.57% | 41.06% | 42.40% |

On validation, the equal-capacity oracle gains **0.51 percentage points** under the existing guard. This small gap supports keeping the served model and threshold.

| Generator stratum on test | Orders | Observed failures | Observed FN | Expected failures | Expected FN |
|---|---:|---:|---:|---:|---:|
| ordinary | 1024 | 467 | 352 | 471.31 | 357.22 |
| latent cluster | 160 | 134 | 4 | 135.46 | 3.39 |

Within ordinary synthetic orders, structural risk differences explain **11.22%** of generated binary-outcome variance. **88.78%** remains conditional variance even with oracle information. This is a variance decomposition, not a count of inherently detectable orders.

A defensible stall claim: with a budget to screen about 20% of ordinary orders, even our generator-informed oracle captures only **28.75%** of their expected failures, compared with **19.92%** for random screening at the same budget. The remaining expected failures are outside that screen. Useful new information such as a customer denial can help. It does not guarantee recovery.

## Limits and brief conflicts

- All examples are synthetic; there are no merchant pilots or production accuracy claims.
- Failed labels combine non-collection/refusal/cancellation; they do not establish deliberate fraud.
- Benchmark generator and cost assumptions do not reproduce any merchant population.
- Verification overrides are demonstrated by functional tests, not simulated as perfect human responses.
- Marked demo outcomes are demonstrations, not prospectively collected field evidence.
- The original generator produced 27.5% failure despite its calibration claim; its 4.88% FPR / 62.23% FNR report selected a threshold on test data and did not evaluate the served policy. The new calibration and split differ, so old and new percentages are not a like-for-like improvement claim.
- No low-FP-and-low-FN production claim is supported. Unpredictable refusals remain a material false-negative risk.
- Competitors: Tasdeek, Botaura, OrderWitness, DukaanFlow. No claim of being first or of competitor capabilities.
