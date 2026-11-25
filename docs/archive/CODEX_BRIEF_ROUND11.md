# Round 11 brief — response to the independent frontier-model audit

An independent frontier model audited this repository cold (commit e35834b) and
scored it 4.9/10 with NO verdicts on public launch, pilot, and revenue. Its
report mixes findings this project had already published about itself with
several genuine catches that the integrator has since verified against the
code. This round fixes the verified, bounded items. The large proposals
(Postgres migration, Shopify embedded app and fulfillment holds, live courier
APIs, Raast prepayment, IVR/LLM fallback, cross-merchant identity graph) are
explicitly OUT of scope for code here; WS-7 records them as a roadmap.

Every workstream below was verified against the merged tree before this
brief was written. Acceptance for the round: full unittest suite green,
build_demo checks green, demo rehearsal unchanged, claims tests passing.

## WS-1 — CI must run the test suite (verified gap)

`.github/workflows/verify.yml` currently runs only
`python scripts/build_demo.py` on Ubuntu and Windows. It never executes the
test suite in `tests/`. Add a step that runs the full unittest suite
(`python -m unittest discover -s tests`) on both OSes, after the build_demo
step. The workflow's green status must from now on mean the tests ran.

## WS-2 — SQLite WAL mode (verified gap)

`backend/app/storage.py` sets no journal mode. Enable WAL
(`PRAGMA journal_mode=WAL`) and a sane `busy_timeout` on the storage
connections. Add a test that opens the store and asserts the journal mode is
`wal`, and that a write followed by a concurrent read does not raise
"database is locked" under the test's concurrency pattern.

## WS-3 — Operator key rotation (verified gap)

`backend/app/operators.py` parses `COD_GUARD_OPERATORS` behind
`@lru_cache(maxsize=1)`, so rotated keys take effect only after a process
restart. Remove the staleness: re-read the environment per authentication
call, or add an explicit cache-clearing path used by tests and documented for
operators. Add a test proving that changing `COD_GUARD_OPERATORS` changes
which keys authenticate without recreating the app.

## WS-4 — LICENSE (verified gap)

The repository has no license file. Add an MIT `LICENSE` at the repo root
with the copyright holder "Arsalan Qasim".

## WS-5 — Capture traffic source at intake (verified gap)

The order schema captures no traffic-source fields, although the market
evidence the README itself cites (OrderNation 2026) reports social-discovery
orders fail ~1.6x more often than search-intent orders. Add optional fields
`utm_source`, `utm_medium`, `utm_campaign`, and `referring_site` to the
order record; populate them where the intake channel provides them (Shopify
webhook landing/referrer fields, WooCommerce order meta when present, CSV
columns when present, social-intake form fields); show them on the dashboard
order detail. Do NOT change scoring in this round — capture first, so a
future round can measure the signal on real data. Tests for at least the CSV
and webhook paths.

## WS-6 — Cost-model sensitivity to real WhatsApp pricing (verified arithmetic)

The Round 9/10 policy cost model assumes PKR 50 per verification attempt.
Meta's live Pakistan Utility rate is ~PKR 4.15 per delivered template
message. Under the repo's own loss equations (ship 650p, hold 450(1-p),
verify A + 180(1-p) at the assumed 60% resolution), replacing A=50 with
A=4.15 widens the verify-optimal probability band from [27.7%, 81.5%] to
[22.2%, 98.5%]. Publish `docs/COST_SENSITIVITY.md` that:

- states the derivation and the band at attempt costs PKR 4.15, PKR 12.45
  (three messages), and PKR 50;
- re-runs the Round 9 and Round 10 policy comparisons at those attempt
  costs on the same frozen holdouts and reports whether any ranking changes;
- states plainly what this does and does not change: it weakens "ML triage
  saves messaging spend" as a value claim and strengthens the case that the
  model's role is managing buyer drop-off and effort, which remains
  unmeasured without real users.

No change to the served policy or thresholds in this round. Add a pointer
addendum line at the top of docs/ROUND9_EVAL.md and docs/ROUND10_EVAL.md
referencing the sensitivity doc (do not rewrite their results).

## WS-7 — Roadmap document (no code)

Write `docs/ROADMAP_POST_AUDIT.md` recording the audit's large proposals as
future work, each with its evidence and our current position: Postgres + RLS
+ encrypted PII + RBAC; Shopify embedded app with GraphQL fulfillment holds
and checkout telemetry; live PostEx/TCS/Leopards API adapters (including
re-verifying PostEx's claimed REST/webhook support against our
COURIER_API_EVIDENCE.md); risk-triggered Raast/wallet partial prepayment,
including the FBR withholding differential (2% COD vs 1% digital, Sec
6A/153(2A)) as part of its value case; Urdu IVR escalation and multimodal
audio-LLM fallback behind the existing adoption gate; cross-merchant
identity graph on the existing opt-in reputation network; buyer drop-off
measurement via a holdout control group; courier-side fake-attempt (CNA)
label poisoning and an NDR verification flow. Mark clearly which items were
already known gaps in this repo and which the audit newly contributed.

## Out of scope

No scoring, threshold, parser, or voice changes. No new integrations. No
README pitch changes beyond what the claims tests require. If a workstream
cannot be completed with tests green, land the others and report the failure
honestly in the PR.
