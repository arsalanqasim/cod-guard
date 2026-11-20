# Exhibition-readiness audit — 19 November 2026

Authority: `docs/CODEX_BRIEF.md`, pulled at `d829df0`. The fixed honesty and
decision rules are retained. The implementation keeps FastAPI, Streamlit and
scikit-learn; replacing the UI framework would not repair the missing learning,
voice, or evaluation paths. `docs/BUILD_SPEC.md` is unchanged.

## Round 5 — WS-A: Daraz feasibility

The read-only Pakistan client covers the three proposed order routes and
HMAC-SHA256 signing. Mocked tests cover request construction and safe error
reporting. [The spike](DARAZ_SPIKE.md) records the primary sources and the
missing authorized capture. Design mode is score-and-queue only; no runtime
intake or buyer verification is enabled.

## Verified starting point

Python 3.13.3, Windows x64. Existing repository was clean at `c2e95f2` before the
brief pull. Ordered baseline commands all exited 0 after repairing installation:

| Command | Exact relevant result |
|---|---|
| `python data/generate_benchmark.py` | `rows=6000  failed_rate=0.275  delivered_rate=0.725` |
| `python backend/app/train_model.py` | threshold 0.60; TP=156, FP=53, FN=257, TN=1034; FPR=0.04875804967801288, FNR=0.6222760290556901; illustrative cost PKR 190900 |
| `python scripts/seed_demo.py` | `Seeded 80 demo orders -> data/demo_orders.csv (failed ground-truth rate 0.29)` |
| `python tests/test_risk_engine.py` | `3/3 tests passed` |
| `python tests/test_verification.py` | `5/5 tests passed` |
| `streamlit run frontend/dashboard.py` | Opened and checked Orders, Verification, Metrics tabs |

The brief's ~0.87 recall referred to a feature-pattern subset, not overall recall.
Overall baseline recall was 0.37772397094430993. The brief's low-FP headline did
not establish strength on both error types.

## Findings and resulting changes

| Finding | Consequence | Resolution |
|---|---|---|
| Negated dispatch such as `مت بھیجیں` or `Please do not confirm` matched positive substrings | A refusal could ship; polite denials could be treated as unclear | Unicode-normalised word/phrase rules, negation handling, scoped denials and conservative questions/future promises; explicit regression cases |
| An unclear follow-up replaced an earlier denial | A GREEN order could revert from HOLD_CANCEL to SHIP | Retain the latest explicit answer until another explicit answer changes it |
| ML could elevate a single phone-history flag to RED | Violated the professor's single-signal rule | Shared serving/evaluation policy requires two distinct adverse signal groups; address checks count together; ML is not a separate signal |
| Live metrics read `label_failed`, ignoring marked delivered/returned/refused | Displayed outcomes could contradict the recorded outcome | Use observed marks and freeze the recommendation when an outcome is first recorded |
| Unverified orders vanished from metrics; order decisions were initially blank | A saved outcome could appear to do nothing | Expose default recommendations and capture them on outcome marking |
| Read/modify/write JSON was unprotected across API/dashboard processes | Concurrent updates could overwrite replies/outcomes | Transactional SQLite, one-time non-destructive legacy JSON import, concurrent-write regression |
| Arbitrary outcomes and unknown IDs were accepted or caused `.iloc[0]` errors | Corrupt labels or HTTP 500 for missing orders | Validate outcomes/replies, use 404 for unknown IDs, bound voice input |
| Model deserialised for every order; errors silently became `None` | Slow scoring and invisible fallback | Cache by model file signature and expose unavailable-model status |
| Chosen threshold was tuned on test labels and not used by serving | Optimistic report and serving/report mismatch | Separate training/validation/test; compare model candidates on validation cost; evaluate the exact served policy and saved threshold |
| Original generator yielded 27.5% failure while claiming calibration to ~49% cash collection | Aggregate calibration claim conflicted with evidence | Explicitly target 51% expected non-collection, separately from 37.3% cancellation; report the empirical rate and synthetic assumptions |
| Outcomes were stored but never consumed by training | Closed-loop claim was unbuilt | Reserve all 80 demo orders outside train/validation/test; retrain from their marked labels, publish versioned models, report pending/consumed counts |
| Voice helper existed but dashboard/API could not use it; no real audio check | Urdu voice claim could not be demonstrated at the stall | Cached offline Whisper, upload/record/preview/apply flow, API, attributed real Urdu clip, CLI and exact transcript in VOICE_TEST.md |
| Unpinned dependencies resolved incompatible PyAV 19 | Real voice decoding failed | Pin tested dependencies, including PyAV 16.1.0; actual decoder regression |
| Demo script claimed low-FP performance and that competitors never learned | Unsupported comparative/accuracy claims | Show both overall rates, all baseline costs and limitations; name competitors without asserting their capabilities |

The initial regression harness failed with **16 failures and 1 error**. Subsequent
targeted tests also reproduced stale-denial erasure and the PyAV decoder breakage
before their fixes. The full post-fix suite contains **26 unittest tests**, plus
the original **3/3** and **5/5** scripts. Dashboard integration exercises both
decision overrides and the visible pending outcome; the learning integration
actually fits a new model and verifies unchanged holdout identities after restart.

## Current measured result

The generated SYNTHETIC benchmark has 6,000 rows, failure rate **0.507**. Splits:
3,552 training, 1,184 validation, 1,184 test, 80 reserved demo orders. Validation
selects regularised gradient boosting and threshold **0.50**. Test result:

| TP | FP | FN | TN | FPR | FNR | Precision | Recall | Illustrative cost PKR |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 245 | 96 | 356 | 487 | 16.47% | 59.23% | 71.85% | 40.77% | 274600 |

Ship-everything costs PKR **390650**; the aggressive any-adverse-signal baseline
costs PKR **259800**; rules-only two-signal policy costs PKR **293800**. The served
model beats ship-everything and rules-only, but **does not beat the aggressive
baseline on illustrative cost**. Low FP and low FN are not established. The
generator, prevalence and split changed, so the old/new rates are not evidence of
a like-for-like accuracy improvement. Cost assumptions remain FN=PKR 650,
FP=PKR 450; these are not measured merchant losses.

## Actual browser and voice evidence

In an isolated state/model profile, the live dashboard transcribed the bundled
Urdu sample offline, displayed its imperfect transcript verbatim, and returned
UNCLEAR without altering the dispatch decision. See `docs/VOICE_TEST.md` and
`docs/screenshots/voice-transcript.jpg`.

Marking CG-00203 delivered, then clicking retrain, published model
`cg-e4f2793699c8` (v2) from `cg-0328b4106253` (v1): training rows **3552 → 3553**,
recorded/consumed/pending **1 / 1 / 0**. The selected test confusion matrix stayed
unchanged after this one example. The threshold curve did change; no improvement
is claimed. See `docs/screenshots/learning-outcome.jpg`. Baseline model/state
artifacts were isolated from these browser marks.

## Exact operational errors repaired

- Initial package access reported `No matching distribution found for fastapi`
  and later `No matching distribution found for streamlit`; a direct HTTPS
  probe timed out. The venv-only pip bundled-certificate setting restored the
  same index query (exit 0 in 2.22 seconds), and all packages installed. No TLS
  validation was disabled.
- Real audio decoding failed with `TypeError: open() got an unexpected keyword
  argument 'metadata_errors'`. PyAV 16.1.0 repaired the same decoder/audio test.
- A running old Streamlit process retained its original service module and
  showed `AttributeError: module 'service' has no attribute 'model_status'` after
  source changes. A fresh server loaded the new modules; restart after pulling
  backend/dependency changes.
- The Wikimedia sample lookup failed with `[Errno 11001] getaddrinfo failed`;
  the separately attributed Google FLEURS clip was used instead.

## Remaining limitations and next priorities

1. **Prediction remains weak on ordinary refusals.** High overall FNR and the
   aggressive-baseline cost failure are visible in the report/UI. More threshold
   tuning on the same test set would not establish generalisation. Next evidence
   should be consented, prospectively collected merchant outcomes and a fresh
   evaluation split; there are no pilots now.
2. **Synthetic calibration is aggregate only.** It does not validate feature
   relationships, fairness across cities, intentional fraud labels, or accuracy
   in Pakistan. Costs are assumed, and marked demo comparisons are not actual
   dispatched-order field results. Distinct rule groups are an engineering guard,
   not a proof of statistical independence.
3. **Conversation is deterministic rules.** Slang, complex conditions, code
   switching and ASR errors can remain unclear or be misclassified. Unclear replies
   need follow-up; the project does not claim a validated language-understanding
   model. One real read-speech clip is a smoke test, not ASR accuracy evidence.
4. **Integration is local.** Seeded CSV intake, simulated conversation and manual
   outcome marking are implemented. Shopify/courier webhooks, real WhatsApp,
   authentication, public hosting and multi-merchant isolation are not built.

## Round 2 addendum

The Round 1 test IDs, 6,000 synthetic rows, model ID `cg-0328b4106253`, and
0.50 threshold reproduce exactly. Pre-reply test counts are TP=245, FP=96,
FN=356 and TN=487. Round 2 adds evaluation around the existing served path.

- **Verification:** The test applies the existing reply-to-dispatch rules using
  six fixed response assumptions and a zero-outreach control. Flags-only
  outreach lowers FPR and raises FNR in both variants. The mid-rate comparison
  changes FNR from 62.36% with flags only to 47.97% with all GREEN orders
  contacted. Broad outreach costs more to attempt and can fare worse under
  adverse reply assumptions. The full outreach range is 5.74%–17.83% FPR,
  35.20%–64.01% FNR, and PKR 211,788.50–356,050.00 in illustrative cost.
- **Capacity:** The raw any-signal baseline flags 907 orders (76.60% of the
  batch), including 417 of 583 genuine labels. Equal caps and PKR 50 per
  attempt favor the capped served policy or two-signal ML ranker at all three
  budgets under either shared response setting. At 30% with no reply, the
  best ranking costs PKR 290,950 versus PKR 293,150 for ranked any-signal.
  The narrow PKR 2,200 gap depends on the specified ranking, costs and sample.
  These batch rankings are evaluated separately from the threshold used at
  runtime.
- **Ceiling:** 352 of 356 observed misses fall in the generator's ordinary
  stratum. At equal validation capacity, the served model catches 41.06% of
  expected failures and the two-signal oracle catches 41.58% (0.51 percentage
  points at full precision). A smaller histogram boosting candidate
  (`max_leaf_nodes=4, max_iter=180, learning_rate=.06, min_samples_leaf=45,
  l2_regularization=8, random_state=7`) saved one validation FN at the same
  FP count and slightly reduced expected recall at a 20% ranking budget
  (30.10% versus 30.20%). This small trade-off did not justify replacing the
  model. Across ordinary test orders the oracle leaves 88.78% of the binary
  outcome variance unexplained, and screening about 20% captures 28.75%
  of expected failures. Variance share cannot identify an individual order
  as predictable or unpredictable.

Rebuild with `python scripts/build_demo.py`. During the baseline training step,
the generator provides oracle diagnostics in memory after checking the CSV
against the fixed generator. Model inputs and serialized weights contain
only the existing features. The routine outcome-retraining report continues
to describe its own model and split. The baseline JSON contains the full
Round 2 tables.

## Round 4 addendum

### 1. Reply scope

The review's past-tense negation and item-level cancellation now abstain.
Scoped, conditional and contradictory replies ask the operator to clarify
and retain any previous explicit decision. The order view retains the
review flag until an explicit reply clears it. Direct whole-order instructions
such as “Please do not send it” still stop dispatch.

Regression coverage: `test_negated_scoped_and_contradictory_replies_abstain`
replays the review's exact strings alongside adversarial replies.
`test_ambiguous_scope_routes_to_operator_without_flipping_prior_decision`
checks both directions of the service override on existing decisions.
The dashboard regression checks that the follow-up remains visible. The
storage migration test checks review-flag backfill for existing records.

### 2. Model publication and retraining

The active pointer selects one immutable directory containing the model, JSON
evaluation and rendered report. Failed writes leave the old pointer and pending
feedback intact. Publishers compare the version they trained against under a
separate short lock. Fitting uses an order-state snapshot while writes continue.
The API and dashboard expose queued, running, done and failed states. Job status
is held by the process that accepted it and is lost on restart. Serving resumes
from the last activated version on disk.

`test_every_publish_write_failure_keeps_old_pair_active_and_feedback_pending`
injects each artifact or pointer write failure. The learning integration test
checks a successful publish and restart. `test_background_training_leaves_order_writes_available`
pauses the fit, verifies API status and duplicate-job rejection, then commits a
reply before the fit resumes and fails.

### 3. Decision snapshots

Outcome marking reads and freezes the latest decision within the transaction.
The decision and outcome trail records revision, time and actor. Outcome
corrections append a revision tied to the original frozen decision. Legacy
outcomes with missing snapshots are counted as unscored.

`test_outcome_freezes_denial_committed_before_outcome_transaction` reproduces
the review's SHIP → denial → outcome interleaving. The correction and legacy
regressions cover durable revision references and unscored outcomes.

### 5. Storage and recovery

Indexed SQLite tables store seeded orders, decision and outcome revisions,
messages, model metadata and audit events. Migration uses the existing SQLite
state when present and otherwise imports the legacy JSON once, then archives
the file. Malformed state leaves the original recoverable. The storage tests
exercise both migration sources, 80 distinct events across eight concurrent
writers, exception rollback, and online backup restored into a new location.

### 4 and 7. API contracts, shadow intake and privacy

`test_pilot_api` injects the review's unusable threshold, wrong model shape,
corrupt SQLite and malformed legacy JSON. It also verifies streamed body
limits, write throttling, authenticated CSV row errors and idempotency,
cross-tenant isolation, masked lists, audited full-phone reads, write actors
and raw reply expiry. `test_empty_order_requires_verification` protects the
unknown-feature path. The dashboard remains limited to the synthetic demo
tenant. See [shadow intake and retention](SHADOW_INTAKE.md).

### 6. Order queue latency

The API and dashboard read a bounded page and its current decision and
outcome projections in one SQLite snapshot, then score the page in one
prediction batch. The API exposes the total in `X-Total-Count`. The 10,000-row
TestClient regression checks the median of five requests for a page of 50
under one second and verifies one prediction batch per request. The dashboard
test checks that changing pages scores only the visible 50 and 30 rows.

### 8. Voice jobs

The API queues bounded audio in memory and returns before inference. Two
workers share one offline Whisper model per process. A barrier regression
checks that two requests can enter inference together and construct the model
once. The API test covers poll authorization, a paused worker, and the preview
and explicit apply flow. PyAV decoding and verbatim transcript tests still run.
The stage budget and fallback are documented in [Voice tests](VOICE_TEST.md).

### 9. Claims and demo copy

The README, demo, dashboard and generated baseline explain the pre-reply
flag, distinguish the synthetic baseline from learned versions, document the
source funnel's range and sampling limits, and give the offline budget results
with actual utilization. The generator docstring describes assumptions. Claim
regressions check the active wording and generated report parity. The original
review and brief retain their wording as historical records.

### 10. Evaluation governance

The committed lock hashes both the test IDs and the ID/label pairs. Training
checks it before fitting and records both digests in every evaluation. The
regressions change IDs and labels separately and assert that neither mutation
reaches fitting. They also check the committed evaluation and require a
separate section for an outcome-fed version. The tuning and reporting rules
are in the [metric protocol](METRIC_PROTOCOL.md).

### Round 4 scope decisions

The pilot remains single-instance. The API scopes orders and writes by
operator and tenant. The dashboard shows the synthetic tenant. The model is
trained on the synthetic benchmark and marked demo outcomes. Real CSV orders
can be reviewed in shadow mode by the tenant's operator. A design partner,
courier integration, consented voice evaluation, field outcomes and pricing
evidence still require separate work. Failed legacy outcomes without a frozen
decision cannot be reconstructed and remain unscored.

### Round 5 — WS-B: WooCommerce connector

[WooCommerce setup](WOOCOMMERCE.md) maps HTTPS/permalink/auth checks, WP-Cron
fallback, signed webhooks, polling and tenant-scoped health. The order identity
table deduplicates webhook/poll deliveries. Outcome write-back is an explicit
operator action against the linked store. Tests use fixtures, not merchant data.

### Round 5 — WS-D: WhatsApp Cloud verification

[WhatsApp setup and evidence gaps](WHATSAPP_CLOUD.md) map approval, consent,
suppression, callback authentication, and tenant-scoped delivery accounting.
Mocked API tests verify deduplication, reply scope, costs, and simulation;
list-rate estimates are not reconciled charges. Daraz stays score-and-queue.

### Round 5 — WS-E: Courier outcome loop

[Courier outcomes](COURIERS.md) maps tenant-scoped atomic CSV import, TCS
evidence limits, the audited correction path, and non-publishing outcome-fed
evaluation. Tests exercise replay, tenant isolation, tracking and the locked
trainer. No courier credentials or field labels were used during verification.

### Round 5 — WS-G: Public benchmark and savings evidence

[Public benchmark](BENCHMARK.md) identifies the model and both holdout hashes,
and leaves unobserved channel/language cohorts unevaluated. The dashboard
renders its active matching report. The tenant savings endpoint separates
synthetic estimates, observed outcomes and statement charges from savings,
which remain unavailable without a counterfactual comparison.

### Round 5 — WS-C: Shopify custom app intake

[Shopify setup](SHOPIFY.md) maps custom installation, protected fields, raw
signature verification, merchant/order deduplication and distribution limits.
Fixture tests cover redacted payloads, the COD filter and tenant isolation.
No live store installed, App Store submission, or billing integration.

### Round 5 — WS-F: Seller-reviewed social intake

[Social intake](SOCIAL_INTAKE.md) maps transient extraction, editable review,
explicit save, scoped CSV ingestion from a private Sheets export, and the
deferred Meta review path. Tests exercise API storage and the review screen.

### Round 5 — WS-H: Auditable reputation network

[Network governance](NETWORK.md) maps opt-in, HMAC pseudonymization,
tenant/consent scope, count suppression, expiry, corrections and appeals.
The size counter counts actual contributors in the selected deployment.
Shadow-only counts cannot alter a score or hold an order.

### Round 6 — WS-1: Whole-order reply scope

[Re-review §1, “Negated confirmation and item-scoped cancellation”](PRODUCTION_REVIEW_REREVIEW.md#1-the-three-original-defects).
Only complete approved replies can change a dispatch decision. Other replies
preserve the previous decision and request review. The order API reports
`verified=false` while a reply needs review. The reply and service regressions
cover the three review examples, scope and time in three text forms, and
preservation of a saved denial.

### Round 6 — WS-2: Queued voice ordering

[Re-review §2, “Queued voice ordering”](PRODUCTION_REVIEW_REREVIEW.md#storage-latency-and-voice).
A queued apply compares its captured decision revision inside the write
transaction. The paused-inference API regression queues a confirmation,
records a newer manual denial and releases inference. The completed job
reports supersession and the denial remains in effect.

### Round 6 — WS-3: Model consistency

[Re-review §1, “Unusable threshold and partial model publication”](PRODUCTION_REVIEW_REREVIEW.md#1-the-three-original-defects).
Single-order scoring uses one bundle for identity, threshold and inference.
Standalone training captures the expected pointer before fitting and only
exports the non-atomic baseline diagnostics after activation. Controlled
activation tests cover both races and assert that a rejected fit leaves
prior diagnostics intact. [Consistency contract](METRIC_PROTOCOL.md).

### Round 6 — WS-4: Readiness coherence

[Re-review §2, “API failure matrix”](PRODUCTION_REVIEW_REREVIEW.md#api-failure-matrix).
`/ready` checks the active bundle, corresponding JSON identity, version,
training timestamp and threshold, and the Markdown generated from that JSON.
The failure matrix covers each missing or mismatched artifact while health
continues to report liveness. [The operator runbook](SHADOW_INTAKE.md)
describes recovery after voice and retrain job status is lost on restart.
