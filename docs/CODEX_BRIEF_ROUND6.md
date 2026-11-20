# COD-Guard — Codex Mission Brief, Round 6: Close the Re-Review's Residual Defects

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`, main after re-review merge (PR #24).

## Why this round exists

The independent re-review (`docs/PRODUCTION_REVIEW_REREVIEW.md`, 20 Nov
2026) confirmed the three original defects are fixed for their original
failure cases and raised the scores: production readiness 3→5/10,
approach 5→6/10, metrics 8/10 (held), engineering 6→7/10; commercial
2/10 and verdicts 3/10 unchanged — those need a real seller, not code.

But the re-review also reproduced NEW residual defects, all in one
family: **ordering and scope — a later or narrower signal can still
override a newer or broader decision.** Its action 3 budgets 4–7
engineering days. This round closes exactly those findings. Nothing
else. No new features, no new channels.

Muse independently reproduced the parser findings on the reviewed
tree before this brief was written:
"Yes, send the order without the blue shirt" → CONFIRM (reversed a
denial to SHIP in the review's replay); "I would confirm the order" →
CONFIRM; "No, cancel the order after 5pm" → DENY immediately. The two
original strings correctly abstain.

## Workstreams (each: fix + regression test that fails without it + AUDIT.md entry)

### WS-1 — Conservative whole-order reply parsing (re-review §1, row 3)
Only a small, explicit set of unambiguous whole-order phrases may commit
a CONFIRM or DENY that overrides the current decision. Everything else
routes to operator review with the prior decision preserved, including:
- item-scoped modifications ("without the blue shirt", "remove the
  extra item", partial quantities) — a modification is not a
  whole-order confirmation;
- hypothetical/conditional phrasing ("I would confirm", "I will confirm
  tomorrow", "if it arrives by Friday");
- time-scoped instructions ("cancel after 5pm", "deliver after Eid") —
  never an immediate whole-order decision.
Cover scope and time in English, Roman Urdu, and Urdu script. Also fix
the API contract the review flagged: `verified` must not read true
alongside `needs_review` after an unclear reply — define the contract,
then make the code match it.

### WS-2 — Revision-checked apply for queued results (re-review §2, voice ordering)
Any asynchronous result (voice job today; any future queued channel)
applies its decision ONLY if the order's current decision revision
equals the revision the job was submitted against. On mismatch: record
the result as superseded, change nothing, surface it to the operator.
Reproduce the review's barrier case as the regression: earlier "Yes"
queued with commit, newer manual denial saved, inference released →
decision must remain HOLD_CANCEL.

### WS-3 — One bundle per assessment; early version capture (re-review §1, row 2)
- Single-order assessment must load the model bundle ONCE and use that
  bundle's id, threshold, and probabilities together (the review mixed
  model A's id/threshold with model B's probability and returned RED).
  Match the page path's behaviour.
- The standalone trainer captures its expected version BEFORE fitting
  (it currently reads it after fitting and can overwrite a model
  activated during the fit), and its three standalone report files get
  an explicit consistency contract (either written as one versioned set
  or documented as non-atomic diagnostics — choose, implement, test).
- Regression tests with controlled scheduling/fixtures for both races,
  in the style of the review's reproductions.

### WS-4 — Readiness coherence (re-review §2)
`/ready` must also verify that the active evaluation artifacts match
the active model version (today `/ready` returns 200 with the active
evaluation file absent while `/evaluation` 404s). Define the readiness
contract in the API docs, implement, and add the failure-matrix rows as
regressions. Also make voice/retrain job-status loss on process restart
explicit in the operator runbook (the review's under-half-day item).

### WS-5 — Storefront reconciliation (re-review §4, WooCommerce/Shopify)
Connector inserts are insert-only today: an updated, cancelled, or paid
order keeps its stale queue state. Make the source store authoritative:
on webhook/poll updates, reconcile the queued order's status (cancelled
at source → closed in queue with an audit event; paid/prepaid → flagged
out of COD scope), without ever overwriting a committed dispatch
decision or an outcome — conflicts go to the operator, recorded.
Regression: create → cancel-at-source → queue reflects closure;
create → decision committed → cancel-at-source → decision preserved,
operator notified via the audit trail.

### WS-6 — WhatsApp clarification window (re-review §4, WhatsApp row)
An unclear free-text reply currently consumes the verification attempt,
so a buyer's follow-up clarification on the same attempt is never
applied. Keep the attempt open for clarification within the existing
policy window (or hand it explicitly to the operator with the full
thread visible) — choose the behaviour, document it in WHATSAPP.md,
and cover it with fixtures. Do not weaken opt-out/STOP handling.

## Out of scope (needs a seller, not code — do not simulate)

- Daraz live intake (awaits an authorized seller payload).
- Any pilot, savings, or accuracy claim beyond the locked synthetic
  benchmark.
- App Store submission, billing, licence file (business decisions).

## Sequencing and delivery

WS-1 and WS-2 first (they protect the exhibition demo on 27–28 Nov:
a scoped reply or a slow voice result must never flip a decision
live on stage). Then WS-3, WS-4, WS-6, WS-5. Per-workstream PRs,
stacked where dependent, each with its AUDIT.md mapping entry quoting
the re-review section it closes.

## Report back

Per PR: the re-review finding closed, the regression test that fails
without the fix, and full-suite counts. When all six land, state
plainly which re-review findings remain open, if any.
