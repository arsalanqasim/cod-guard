# COD-Guard — FP/FN Evaluation Report

Dataset: SYNTHETIC benchmark calibrated to OrderNation stats (~170k real orders: 37.3% COD cancelled, ~49/100 end in cash). Held-out test split: 25%.

Cost assumptions: FN (fake order shipped) = PKR 650; FP (genuine order blocked) = PKR 450.

## Baselines (test split)
- Ship everything: FP=0, FN=413, total cost = PKR 268,450
- Flag at loose threshold 0.30: FP=228, FN=183, total cost = PKR 221,550

## Threshold sweep (FP vs FN trade-off)

| threshold | TP | FP | FN | TN | FP rate | FN rate | precision | recall | total cost (PKR) |
|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 230 | 228 | 183 | 859 | 0.210 | 0.443 | 0.502 | 0.557 | 221,550 |
| 0.35 | 213 | 175 | 200 | 912 | 0.161 | 0.484 | 0.549 | 0.516 | 208,750 |
| 0.40 | 199 | 134 | 214 | 953 | 0.123 | 0.518 | 0.598 | 0.482 | 199,400 |
| 0.45 | 187 | 107 | 226 | 980 | 0.098 | 0.547 | 0.636 | 0.453 | 195,050 |
| 0.50 | 176 | 89 | 237 | 998 | 0.082 | 0.574 | 0.664 | 0.426 | 194,100 |
| 0.55 | 167 | 69 | 246 | 1018 | 0.063 | 0.596 | 0.708 | 0.404 | 190,950 |
| 0.60 | 156 | 53 | 257 | 1034 | 0.049 | 0.622 | 0.746 | 0.378 | 190,900 |
| 0.65 | 145 | 45 | 268 | 1042 | 0.041 | 0.649 | 0.763 | 0.351 | 194,450 |
| 0.70 | 133 | 40 | 280 | 1047 | 0.037 | 0.678 | 0.769 | 0.322 | 200,000 |
| 0.75 | 116 | 32 | 297 | 1055 | 0.029 | 0.719 | 0.784 | 0.281 | 207,450 |
| 0.80 | 101 | 24 | 312 | 1063 | 0.022 | 0.755 | 0.808 | 0.245 | 213,600 |

## Chosen operating point: threshold 0.60 (lowest total cost)

Confusion matrix: TP=156, FP=53, FN=257, TN=1034. vs ship-everything, total loss falls from PKR 268,450 to PKR 190,900 on the test split (29% reduction).

Segment check - organised-fake pattern orders (fraud-linked phone or 3+ orders/day, n=269): recall 0.87, FN rate 0.13. Ordinary refusals are intrinsically harder to predict pre-dispatch; those are what the verification agent exists to catch.

Note: AMBER-zone orders are verified with the customer before any block, so a model FP does not automatically lose the sale — the verification step is the FP-recovery path, and a denied/unreachable confirmation on a high-risk order is the FN-recovery path.