# Cost-Model Sensitivity to Live Pakistan WhatsApp Pricing

**No served policy or threshold changes in this round.** This document tests how the Round 9 and Round 10 modeled cost comparisons behave when the assumed verification attempt cost (`A = PKR 50`) is replaced with live Meta WhatsApp Business Platform Utility template pricing for Pakistan (`A = PKR 4.15` for one delivered message, and `A = PKR 12.45` for a three-message sequence).

## Derivation and verify-optimal probability bands

Round 9 and Round 10 evaluate three dispatch actions using the same scenario loss assumptions: false ship cost `C_FN = PKR 650`, false operator hold cost `C_FP = PKR 450`, verification resolution rate `r = 0.60`, and verification attempt cost `A`. Unresolved cases stay deferred, so an unresolved genuine order incurs `C_FP = PKR 450` (expected unresolved penalty `(1 - r) * 450 = PKR 180` per genuine verified order):

- `E[Ship(p)] = 650 * p`
- `E[Hold(p)] = 450 * (1 - p)`
- `E[Verify(p)] = A + 180 * (1 - p)`

Solving `E[Ship(p)] = E[Verify(p)]` and `E[Hold(p)] = E[Verify(p)]` yields the lower release threshold `p_low = (A + 180) / (650 + 180)` and upper auto-hold threshold `p_high = 1 - A / (0.60 * 450)`:

| Verification attempt cost (`A`) | Scenario basis | `p_low` (ship below) | `p_high` (hold above) | Verify-optimal band width |
| --- | --- | ---: | ---: | ---: |
| **PKR 4.15** | 1 Meta Pakistan Utility template ($0.0150 at ~PKR 276.7/USD, Oct 2026) | **22.19%** | **98.46%** | **76.28 pp** |
| **PKR 12.45** | 3 Meta Pakistan Utility templates (initial + 2 reminders) | **23.19%** | **95.39%** | **72.20 pp** |
| **PKR 50.00** | Round 9 / Round 10 baseline assumption | **27.71%** | **81.48%** | **53.77 pp** |

Lowering `A` from PKR 50 to PKR 4.15 widens the verify-optimal probability band from `[27.7%, 81.5%]` to `[22.2%, 98.5%]`.

## Round 9 holdout sensitivity

Re-evaluating the frozen Round 9 action assignments (`[PK-REAL]` `N = 6,211`, 3,433 genuine / 2,778 failed; `[PK-SYNTH]` `N = 1,184`, 583 genuine / 601 failed) across all three attempt costs:

| Holdout | Policy | Ship / Verify / Hold | Expected PKR / 1,000 (`A = 4.15`) | Expected PKR / 1,000 (`A = 12.45`) | Expected PKR / 1,000 (`A = 50.00`) |
| --- | --- | ---: | ---: | ---: | ---: |
| `[PK-REAL]` | Current rules-first | 0 / 6,211 / 0 | 103,641.23 | 111,941.23 | 149,491.23 |
| `[PK-REAL]` | Model-first | 0 / 6,211 / 0 | 103,641.23 | 111,941.23 | 149,491.23 |
| `[PK-SYNTH]` | Current rules-first | 843 / 200 / 141 | 216,891.89 | 218,293.92 | 224,636.82 |
| `[PK-SYNTH]` | Model-first (verify all) | 0 / 1,184 / 0 | 92,781.76 | 101,081.76 | 138,631.76 |

- **Ranking change on Round 9:** None. On `[PK-REAL]`, both policies still tie at every attempt cost. On `[PK-SYNTH]`, the model-first policy's modeled advantage over the incumbent comes from deferring all 1,184 orders (`+984` verification slots) and grows from `-86,005.07` PKR/1,000 at `A = 50` to `-117,212.16` at `A = 12.45` and **`-124,110.14`** at `A = 4.15`.

## Round 10 holdout sensitivity

### `[PK-REAL]` (`N = 6,211`, frozen holdout)

Every Round 10 challenger matched the incumbent's `0 / 6,211 / 0` actions because on validation even the widest 27% release cutoff selected only 8–44 orders from at most 33 buyers (below the 40-buyer minimum gate). Because lowering `A` from PKR 50 to PKR 12.45 or PKR 4.15 *lowers* the release break-even threshold from `27.71%` to `23.19%` and `22.19%` respectively, any candidate cutoff permitted at the lower attempt costs is a strict subset of the `<= 27%` validation orders that already failed the 40-buyer gate. Therefore no `[PK-REAL]` challenger passes validation or changes rank at PKR 12.45 or PKR 4.15; all match the incumbent at **PKR 111,941.23 / 1,000** (`A = 12.45`) and **PKR 103,641.23 / 1,000** (`A = 4.15`). *(Note: the private Kaggle archive stays outside Git and was not re-ingested for this sensitivity table; the validation-gate invariance follows directly from monotonic subsetting of the release threshold.)*

### `[PK-SYNTH]` (`N = 1,184`, frozen holdout)

| Policy | Ship / Verify / Hold | `A = 4.15` PKR / 1,000 (Δ vs inc.) | `A = 12.45` PKR / 1,000 (Δ vs inc.) | `A = 50.00` PKR / 1,000 (Δ vs inc.) |
| --- | ---: | ---: | ---: | ---: |
| Incumbent | 843 / 200 / 141 | 216,891.89 (0.00) | 218,293.92 (0.00) | 224,636.82 (0.00) |
| Transferred `[PK-REAL]` rule | 843 / 200 / 141 | 216,891.89 (0.00) | 218,293.92 (0.00) | 224,636.82 (0.00) |
| Re-rank without customer outcomes | 843 / 200 / 141 | 213,386.82 (−3,505.07) | 214,788.85 (−3,505.07) | 221,131.76 (−3,505.07) |
| Re-rank with customer outcomes | 843 / 200 / 141 | **211,984.80 (−4,907.09)** | **213,386.82 (−4,907.09)** | **219,729.73 (−4,907.09)** |
| Verify all (unconstrained, +984 slots) | 0 / 1,184 / 0 | 92,781.76 (−124,110.14) | 101,081.76 (−117,212.16) | 138,631.76 (−86,005.07) |

- **Ranking change on Round 10:** None. Because the budget-matched re-rankers hold `n_verify = 200` constant, every equal-budget policy shifts by the exact same constant `(200 / 1,184) * 1,000 * (A - 50)`, leaving all paired deltas (`-3,505.07` and `-4,907.09` PKR/1,000, whose 95% CIs span zero) completely unchanged. Meanwhile, lowering `A` widens the gap between unconstrained verify-all and every 200-slot policy.

## What this does and does not change

- **What it weakens:** *"ML risk triage saves WhatsApp messaging spend"* is not a credible value proposition at live Pakistan Utility rates (~PKR 4.15 per message). If direct messaging cost were the only friction, verifying almost every order (`22.2%–98.5%`) would dominate selective triage under the assumed resolution rate.
- **What it strengthens:** The real economic role of a risk model is managing **unmeasured buyer drop-off, dispatch delay friction, and human/IVR verification effort**—choosing which orders can safely bypass friction, which merit cheap WhatsApp confirmation, and which warrant higher-friction interventions (partial prepayment or Urdu IVR calls).
- **What remains unmeasured:** Actual buyer drop-off from verification, true resolution rates on Pakistani COD traffic, and Meta template reclassification risk (Utility `$0.0150` vs. Marketing `$0.0473`). None of these can be established without real pilot sellers and a randomized holdout control group.
