# Public benchmark

Model `cg-0328b4106253` · Version 1 · Report format 1 · **SYNTHETIC**

## Results

| Cohort | Orders | Precision | Recall | FPR |
| --- | ---: | ---: | ---: | ---: |
| All held-out synthetic orders (pre-reply) | 1184 | 71.85% | 40.77% | 16.47% |
| Channel · WooCommerce | Not evaluated | — | — | — |
| Channel · Shopify | Not evaluated | — | — | — |
| Channel · Daraz | Not evaluated | — | — | — |
| Channel · Social DM / Sheets | Not evaluated | — | — | — |
| Channel · WhatsApp verification | Not evaluated | — | — | — |
| Language · English text | Not evaluated | — | — | — |
| Language · Roman Urdu text | Not evaluated | — | — | — |
| Language · Urdu script text | Not evaluated | — | — | — |
| Language · Urdu voice | Not evaluated | — | — | — |

Confusion matrix: TP 245, FP 96, FN 356, TN 487.
Precision = TP / (TP + FP), recall = TP / (TP + FN), FPR = FP / (FP + TN).

## Method and dataset

Deterministically generated dataset: 6,000 synthetic COD orders. The split has
3,552 training rows (including 0 marked demo outcomes),
1,184 validation orders and 1,184 locked test orders. The 80
demo orders are separately reserved. AMBER or RED counts as a positive before any reply.
The model and 0.50 threshold are selected on validation cost, not test labels.
The positive label is COD failure, not proof of fraud. The checkout and human reply cohorts are not sampled.
The [full evaluation](EVAL_REPORT.md) contains city slices and offline outreach sensitivity scenarios,
not live reply measurements. [Metric protocol](METRIC_PROTOCOL.md).

- Benchmark SHA-256: `b03474a56979d6f86a0b1794ddaefcd2d4925ab63ea1f622942c3211854719b7`
- Holdout IDs SHA-256: `6c114ac0be4bb578a40dcc0a0ea2ce778e0193fc067eb08542170057c5841974`
- Holdout ID/label SHA-256: `4ee23108aa72894f25630057a0ec6cf836651f7164c2558e9a706a64f59bb5ab`

## Reproduce

Install `requirements.txt` and run `python scripts/build_demo.py` to regenerate
the synthetic baseline, including this Markdown. To render the committed evaluation without fitting,
run `python backend/app/public_benchmark.py`. After demo retraining, the dashboard can download the
report rendered from the active model’s matching evaluation. Real courier pilot candidates are not published.

## Limits

No subgroup accuracy, merchant pilot, measured savings, or production lift is established.
Urdu voice is a functional demonstration; transcription or intent accuracy was not evaluated on this holdout.
Channel and language rows are not zeroes: the dataset has neither cohort labels nor recorded conversations.
