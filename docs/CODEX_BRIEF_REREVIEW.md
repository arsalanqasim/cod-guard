# COD-Guard — Codex Mission Brief: Independent Re-Review After Rounds 4 + 5

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`. Review target: `main` at `0475e29`
(Round 5 integration merge, PR #23; Daraz spike merged separately as
`c21651e`, PR #22; Round 4 landed as `c7f202f`, PR #13).

DRAFT — prepared by Muse 2026-11-20, not yet handed to Codex. Arsalan's
word triggers the handoff; nothing here has been pushed.

## Why this round exists

`docs/PRODUCTION_REVIEW.md` (independent review of `main` at
`d600c66`, 19 Nov 2026) scored COD-Guard: production readiness 3/10,
approach 5/10, metrics 8/10, commercial 2/10, engineering 6/10,
verdicts 3/10. It named three real defects — stale decision snapshot
under concurrent writes, non-atomic model publication, parser scope
errors on negations — plus 96 s list latency at 10,000 orders and a
commercial case that did not substantiate PKR 1M.

Rounds 4 and 5 claim to have fixed the engineering side of that
review and added a sellable layer. The project is due Wed 25 Nov 2026
and on display at the EE Flagship Event Fri–Sat 27–28 Nov. Before the
exhibition, the review must be re-run by the same hostile-but-fair
standard — not trusted on the builders' word.

## Your role

You are the independent reviewer, not the builder. You built Rounds
1–2 and wrote the first review; forget both. Re-verify every fix the
way a senior engineer and a buyer doing due diligence would: read the
code, run the tests, run the pipeline, reproduce the review's exact
failure cases. Cite files and line numbers. If you did not check
something, say "not checked" — never fill gaps with plausible language.

Write the report to `docs/PRODUCTION_REVIEW_REREVIEW.md` and open a PR
with only that file. No code changes, no refactors, no one-line fixes
in this round — list fixes separately if you find any.

## 1. Re-verify the three defects (Round 4, docs/AUDIT.md "Round 4 addendum")

Reproduce each original failure case against current `main`, then
confirm the fix and its regression test actually covers it:

- Stale decision snapshot: the review's interleaving — outcome
  recording reads `SHIP`, a denial then commits `HOLD_CANCEL`, the
  outcome write still froze `SHIP` (`mark_outcome` computed the
  snapshot before taking the write lock). Claimed fix: outcome marking
  reads and freezes the latest decision within the transaction, with
  revision/time/actor on the decision-and-outcome trail.
- Non-atomic publication: a deserializable bundle with a missing usable
  threshold (`None`) reported `available=true` and made `/orders`
  return 500; failed writes must leave the old pointer and pending
  feedback intact. Claimed fix: the active pointer selects one immutable
  directory (model + JSON evaluation + rendered report); publishers
  compare the trained version under a separate short lock.
- Parser scope errors: "I did not confirm this order" and "Please
  cancel the extra item only" were misread. Claimed fix: both now
  abstain as UNCLEAR; scoped/conditional/contradictory replies ask the
  operator to clarify and retain any previous explicit decision.

For each: does the regression test replay the review's exact strings,
and does it pass on a clean checkout? Any defect that does not
reproduce as fixed stays failed, whatever the audit says.

## 2. Re-run the rest of section 1 (production readiness)

- API failure matrix from the review (`test_pilot_api`): unknown order,
  blank reply, invalid outcome, bad extension, unreadable audio, missing
  model, unusable threshold, corrupt SQLite, malformed legacy JSON.
  Confirm the error mapping is now consistent and `/health` reflects
  readiness, not just liveness.
- Storage: normalized indexed SQLite, migration from legacy JSON,
  restore drill. Confirm the 80-events / 8-writer concurrency case and
  the rollback case still hold.
- Latency: the review measured `/orders` at 96.33 s for 10,000 rows.
  Claimed: 50-order page over 10,000 orders in 13 ms local median
  (Round 4) / under 1 s in the TestClient regression. Re-measure it
  yourself on this machine and report the number.
- Risk engine: empty order must now require verification (unknown-feature
  path), not score GREEN on favourable defaults.
- Voice jobs: bounded audio, queued inference, one offline Whisper model
  per process. Note the accepted limit: job status is process-local and
  resets on restart — confirm it is disclosed, not hidden.
- Evaluation governance: committed lock hashes test IDs and ID/label
  pairs; training checks it before fitting. Try the ID-mutation and
  label-mutation cases yourself.

## 3. Re-derive the metrics (section 3 of the review)

Independently recompute from the committed artifacts: FPR 16.47% /
FNR 59.23% on the synthetic holdout at the frozen 0.50 threshold, the
18 capacity comparisons at PKR 50/attempt, and the verification
scenarios (FPR 5.74–17.83% / FNR 35.20–64.01%). Do they reproduce?
Then check every claim in README, demo script and dashboard against
what the evaluation supports — including the Round 5 benchmark report's
separation of observed courier charges from estimated savings, and the
statement that actual savings and Urdu voice accuracy are unverified.
List every overstatement, however small.

## 4. Check the Round 5 sellable layer honestly (docs/AUDIT.md, Round 5)

For each workstream, verify the claimed boundary — especially where a
feature is deliberately disabled or simulated:

- Daraz: score-and-queue only (`INTAKE_MODE = "score-and-queue-only"`);
  live intake and WhatsApp disabled; buyer phone UNVERIFIED (no live
  seller token). Confirm no code path can live-verify a Daraz buyer.
- WhatsApp Cloud: consent-gated Confirm/Cancel, opt-out, delivery cost
  estimates, labelled simulation fallback. Confirm the API refuses to
  fake-send (no live Meta send yet) and the simulation is labelled
  everywhere it appears.
- WooCommerce: signed webhooks, polling fallback, outcome write-back as
  an explicit operator action. Shopify: custom-app intake, no App Store
  submission, no billing. Social: review-before-save for pasted DMs,
  no direct Meta/Sheets connection. Couriers: CSV import + read-only TCS
  adapter + shadow retraining, no new scoring features promoted.
  Reputation: opt-in, disabled by default, never affects dispatch.
- Benchmark: public report identifies model and both holdout hashes;
  unobserved channel/language cohorts left unevaluated.

## 5. Re-score every section /10

Score production readiness, approach, metrics, commercial case and
engineering again, each with a one-line justification and the evidence
pointer. State explicitly what moved since the first review and what
did not. Do not inflate: commercial and field-evidence scores cannot
rise without a live seller — live merchant validation is still pending
and no real orders exist, so say so and keep those scores honest. The
PKR 1M bar was not substantiated as revenue or asset value in the first
review; re-test it against the Round 5 evidence, not against ambition.

## 6. Verdicts (one line each, then the evidence pointer)

- Exhibition-ready (27–28 Nov)?
- Pilot-ready with one real seller's orders?
- Charge-money-ready?
- Production-grade?
- Worth continuing after the exhibition, or park it? Under what
  conditions would your answer change?

End with the five highest-leverage next actions, in order, with rough
costs. Anything that needs a real seller, real orders, or real money
must be labelled as such — it is not an engineering task.

## Rules

- Honesty constraints from `docs/CODEX_BRIEF.md` still bind: synthetic
  data is synthetic, no invented pilots, no invented market numbers.
  Where you need market facts, verify them from sources you cite or
  label them as unverified assumptions.
- Never claim "first" for any feature. The 20-product competitive study
  (19 Nov 2026) established that buttons, Urdu/voice notes, blacklist,
  0–100 scores and PKR/micro pricing are all already claimed by rivals
  (ConfirmFlow, OrderWitness, Botaura, SendFlow and others).
- No grade inflation and no cruelty theatre: every criticism comes with
  the evidence and, where fixable, the fix's rough cost.
- The original `docs/PRODUCTION_REVIEW.md` keeps its wording as a
  historical record. This re-review is a separate file.
