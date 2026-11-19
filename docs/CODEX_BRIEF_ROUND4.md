# COD-Guard — Round 4: fix everything the review found

Authority: `docs/PRODUCTION_REVIEW.md` (merged, commit 5331bf6). That review
scored production readiness 3/10, approach 5/10, metrics 8/10, commercial
2/10, level 6/10. This round fixes every defect in it that code, tests, or
documentation can fix. You lead, as before. Work in per-workstream PRs
against main (one PR per numbered section below is fine; several small PRs
beat one giant one). Every fix ships with a regression test that would have
caught the defect — the review's own fault injections are your test cases.
Keep the full suite green throughout, and update the AUDIT with a Round 4
addendum mapping each review finding → fix → test.

## 1. Reply parser scope (review §1, Verification)
Reproduced defects: `I did not confirm this order` → CONFIRM (wrong);
`Please cancel the extra item only` → whole-order DENY (wrong scope).
Fix negation scope and partial-scope handling: a cancellation scoped to
part of an order is not a whole-order denial — abstain and route to the
operator. Add the review's exact strings, plus your own adversarial set
(negated denials, scoped confirmations, mixed confirm+cancel), as regression
tests. No autonomous decision may flip on a scoped or negated reply.

## 2. Atomic model publication + retrain job (review §1, Training)
Defect: `publish()` writes model → evaluation → report non-atomically; a
mid-publish failure activates a model with no matching evaluation, while the
UI shows zero pending against a stale training record.
Fix: immutable versioned artifact pairs (model + evaluation written as one
version directory), a single atomic active-version pointer, rollback to the
previous version on any publish failure, and recovery tests that inject a
failure at each write step. Move retraining out of the order-state write
lock: a retrain job with visible status (queued/running/done/failed) that
the dashboard and API can poll. A failed job changes nothing that serving
reads.

## 3. Decision snapshot consistency (review §1, Service)
Defect: `mark_outcome` assesses before taking the write lock, so a decision
committed in between is not the one frozen.
Fix: compute and freeze the decision inside the same transaction that
records the outcome. Decisions/outcomes become an append-only event trail
with revision, timestamp and actor; corrections append, never overwrite.
Add the review's interleaving (outcome reads SHIP → denial commits
HOLD_CANCEL → outcome write) as a concurrency regression test — the frozen
decision must be the latest committed one, or the outcome must record
against the decision revision it names.

## 4. API and intake hardening (review §1, API + Risk engine)
- Strict model-bundle validation at load: a bundle with a missing/unusable
  threshold or shape mismatch reports unavailable and falls back to rules —
  never a 500 on /orders.
- Separate liveness from readiness: /health stays process liveness; add
  /ready that fails when the state store or model cannot be read.
- Consistent error mapping: unreadable/corrupt state → 503 with a stable
  error body, not 500s scattered across endpoints; malformed legacy JSON
  import must not 500 metrics.
- Input contract for orders: no GREEN-by-default on empty/missing features.
  Missing features follow an explicit unknown path (flag for verification),
  with validation errors for malformed values, as the risk engine already
  does for nonbinary flags and hour 24.
- Application-level request body limits on all API routes (not only the
  upload path), and a basic rate limit on write endpoints.
- Order intake v1: an authenticated CSV import endpoint with schema
  validation, idempotency keys, and per-row error reporting — the shadow
  mode intake the review prescribes — replacing the fixed seed file as the
  only order source (seed stays for the demo).

## 5. Storage: normalized records, migration, recovery (review §1, Storage)
Move from one-JSON-row-per-order blobs to normalized, indexed SQLite tables
(orders, decisions, outcomes, messages, model versions, audit events) with
a migration from the current format, the legacy file handled explicitly
(import once, then archive — not silently retained as a live fallback).
Add a backup/restore drill: a script that snapshots the DB and a test that
restores it into a fresh location and verifies counts. Concurrency tests
from the review (8 threads × distinct events; exception rollback) must pass
against the new schema.

## 6. Performance: bounded list cost (review §1, Load)
Measured defect: /orders at 0.78s / 9.37s / 96.33s for 80 / 1,000 / 10,000
rows; dashboard re-reads state per row.
Fix: pagination on the API and dashboard, one shared state snapshot per
request, batched model prediction over the page. Acceptance: /orders page
of 50 at 10,000 stored orders returns in under 1s on the review's class of
machine (same-host TestClient median of 5), and the dashboard no longer
scores the full table on rerun.

## 7. Access control and privacy, single-instance pilot scope (review §1)
- Actor identity on every write (reply decision, outcome, retrain, import):
  an API key per operator, recorded in the audit trail. No write endpoint
  is anonymous.
- Phone numbers masked in list views; full numbers only on the order detail
  for an authenticated operator, and that access is audit-logged.
- Tenant scoping groundwork: a tenant_id on orders and all state, enforced
  in queries, with a test that one tenant's token cannot read or write
  another tenant's orders. (Full multi-tenant operations remain future
  work; the data and auth boundary must exist now.)
- Retention: a documented, configurable retention window for raw replies
  and audio, with a purge job and a test.

## 8. Voice path operability (review §1, Verification)
Keep offline Whisper. Remove the serial-inference bottleneck for the demo
path: one warm shared model instance per process (already partly true —
verify), transcription as a job with status instead of a blocking request
where the API is concerned, and a documented latency budget. Regression:
the PyAV decoder test and the verbatim-transcript test stay green.

## 9. Documentation truth pass (review §3, claim corrections)
Apply every wording correction the review listed, verbatim in spirit:
"baseline v1" labelling with what a flag counts as; "independent adverse
signals" → "two distinct adverse signal groups" everywhere (README, demo
script, UI copy); live-metrics wording qualified until §3 lands, then made
accurate; the 49–57 per-100 funnel range with its single-retailer,
mixed-window caveats; "equal flag cap" framed as a budget comparison, not
an online win; generator docstring no longer claims to model how fake
orders actually behave. Grep the repo for the old phrases and show the
empty result in the PR.

## 10. Evaluation governance (review §2, evaluation row)
- Hash-lock the test split: training/selection code refuses to run if the
  test IDs or labels digest differs from the committed lock, and the lock
  is recorded in evaluation.json.
- A short metric protocol doc: what may be tuned on validation, what the
  test split is for, and the rule that outcome-fed versions get a fresh
  report section instead of overwriting the baseline's.

## Out of scope — do not fake these
The review's commercial and field-evidence gaps are not code: no seller,
no real outcomes, no willingness-to-pay. Do not manufacture them. Where a
fix above enables the pilot path (intake, auth, shadow mode), build it;
the evidence itself comes later, with a real design partner. Scores are
re-earned by the re-review, not asserted by this round.

## Acceptance
- Every numbered section: code + tests + AUDIT mapping entry.
- The review's three reproduced defects (§1–§3 above) demonstrated fixed
  by their regression tests.
- Full pipeline green from a clean clone: build_demo, all tests, voice
  smoke, CI on Windows and Linux.
- A Round 4 addendum in docs/AUDIT.md listing anything in this brief you
  judged wrong or infeasible, with evidence — as you did in Round 1.
