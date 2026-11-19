# COD-Guard — Comprehensive independent review (prompt for Codex)

You are now the independent reviewer, not the builder. In Rounds 1–2 you built
COD-Guard (this repo) under a mission brief. Forget that you wrote it. Review
it the way a hostile-but-fair senior engineer, an ML reviewer, and a buyer
doing due diligence would — all three. Every claim in this review must be
backed by evidence you actually gathered: read the code, run the tests, run
the pipeline, run the demo. Cite files and line numbers. If you did not check
something, say "not checked" — never fill gaps with plausible language.

Write the full report to `docs/PRODUCTION_REVIEW.md` and open a PR with only
that file (plus small fixes only if they are one-line and obviously correct —
list them separately; do not refactor during a review).

## 1. Production readiness — is this real production software?

Go subsystem by subsystem (API, service layer, storage, dashboard, risk
engine, verification, training pipeline, evaluation) and judge:
- Correctness under failure: bad input, missing model, corrupt state,
  concurrent writes, partial failures. What actually happens — run it, don't
  guess.
- Security: injection, path handling on uploads, unbounded inputs, secrets,
  authentication/authorization (or their absence), PII handling of customer
  phone numbers and outcomes.
- Scalability and limits: SQLite under real order volume, model loading,
  per-request cost. Where exactly does it break first, at what scale?
- Operability: logging, observability, configuration, deployment story,
  reproducibility (clean clone → running system), CI quality.
- Code quality: structure, duplication, dead code, test quality — do the
  tests test behaviour or just mirror the implementation? What is untested
  that matters?
End this section with a blunt verdict: could this be deployed tomorrow for
one real seller? For ten? What breaks first in each case?

## 2. Interrogate every approach — why X, why not Y

For each major decision, state the decision, the strongest alternative, and
whether the choice survives scrutiny. Where the alternative is better, say so
and estimate what switching would cost.
- Gradient boosting vs logistic regression vs XGBoost/LightGBM vs a small
  neural net vs LLM-based scoring — for THIS data size and feature type.
- Rules + ML hybrid vs pure ML vs pure rules.
- Deterministic reply parser vs LLM intent classification (accuracy, cost,
  latency, offline behaviour, failure modes in Urdu/Roman Urdu code-switching).
- Whisper small, local and offline, vs a hosted ASR API.
- Streamlit dashboard vs a real web frontend; FastAPI + SQLite vs Postgres +
  a job queue.
- Synthetic benchmark vs any obtainable real dataset; the calibration target
  (51% non-collection); the cost model (FN PKR 650 / FP PKR 450) — are these
  defensible, and what happens to every conclusion if they are off by 2×?
- The two-signal rule and customer-override design vs simpler or stricter
  dispatch policies.
- Threshold selection on validation + served-policy evaluation vs the
  alternatives. Is the evaluation methodology itself sound? Hunt for leakage,
  split contamination, and oracle misuse yourself — assume the builder (you)
  made at least one mistake and try to find it.

## 3. The metrics, re-derived

Independently recompute the headline numbers from the committed artifacts
(FPR/FNR, capacity comparison, ceiling analysis). Do they reproduce? Does
anything in the demo script or README overstate what the evaluation supports?
List every overstatement you find, however small.

## 4. Can we sell this? Can we earn from it?

Answer as a business analyst with the technical facts from sections 1–3:
- Who exactly is the buyer (which seller segment, what order volume, what
  current pain and current spend)? Name the competitors again — Tasdeek,
  Botaura, OrderWitness, DukaanFlow — and state honestly what they already
  provide and what, if anything, COD-Guard has that they don't.
- Unit economics: cost per verified order (WhatsApp Cloud API pricing,
  hosting, ASR), realistic price per order or per month in PKR, margin at
  100 / 1,000 / 10,000 orders per month.
- What is missing before anyone can be charged: Shopify/other platform
  integration, real WhatsApp Cloud API, multi-tenancy, billing, onboarding,
  support burden, data agreements. Estimate the gap in weeks of work, as
  ranges with reasoning, not false precision.
- Realistic earning paths ranked: (a) SaaS to Pakistani sellers, (b)
  productised service / done-for-you verification, (c) licensing the risk
  engine, (d) selling the project/IP outright, (e) portfolio value only.
  Give each a probability-weighted honest assessment, including the
  possibility that the correct answer is "this earns nothing directly."
- The professor's bar was "a product with real worth around PKR 1M". Does
  this meet it — as revenue, as asset value, or not at all? Justify.

## 5. Level judgement

Grade the engineering honestly: what level is this work — student project,
junior, mid, senior, staff/L8? Judge design, evaluation rigour, testing,
documentation, and operational thinking separately; a single blended grade
hides the truth. Then list the specific gaps that separate it from genuine
production-grade / L8-level work, ordered by how much each gap matters.

## 6. Verdicts (one line each, then the evidence pointer)

- Exhibition-ready (Nov 27–28)?
- Pilot-ready with one real seller's orders?
- Charge-money-ready?
- Production-grade?
- Worth continuing after the exhibition, or park it? Under what conditions
  would your answer change?

## Rules

- Honesty constraints from `docs/CODEX_BRIEF.md` still bind: synthetic data
  is synthetic, no invented pilots, no invented market numbers — where you
  need market facts (WhatsApp pricing, competitor features), either verify
  them from sources you cite or label them as unverified assumptions.
- No grade inflation and no cruelty theatre: every criticism must come with
  the evidence and, where fixable, the fix's rough cost.
- Score each section /10 with a one-line justification. End with the five
  highest-leverage next actions, in order.
