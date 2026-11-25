# COD-Guard — Codex Mission Brief, Round 8: The Five-Day Build

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`, main after Round 7 (6b24d03).

## Why this round exists

Rounds 1–7 were built in essentially one day. Five days remain before
the functional deadline (Wed 25 Nov) and the public display (27–28
Nov). This round spends them on the three things that most raise the
product's real value: closing the unverified claims, giving the
decision models a fair rematch, and building the next three decisions
— in shadow, measured, behind the same gates as everything else.

Workstreams in priority order. WS-A and WS-B protect the deadline;
WS-C is the rematch; WS-D/E/F are the new decisions.

## WS-A — Exhibition hardening (first, non-negotiable)

- Rehearse `docs/DEMO_SCRIPT.md` end-to-end on a clean checkout:
  every step timed, every fallback exercised (text reply when voice
  is slow, offline with the decision-model path disabled).
- Voice weights pre-cached via `scripts/prepare_voice.py`; demo state
  disposable and resettable in one command; prove the reset works.
- Any step that fails or exceeds its script timing is a defect: fix
  or cut the step from the script. Report the rehearsal timings.

## WS-B — Measure Urdu voice accuracy (close the unverified claim)

Voice is a headline feature whose accuracy has never been measured.

- Build a labelled Urdu voice set from FLEURS `ur_pk` test clips
  beyond the single sample already used: reference transcripts plus
  the intent each transcript should produce through the existing
  pipeline (Whisper → rules).
- Report word error rate and end-to-end intent accuracy, with every
  failure listed. Publish as `docs/VOICE_ACCURACY.md`.
- README/demo copy may cite voice accuracy only from this document.

## WS-C — Reply-model rematch (the gate does not move)

Round 7's contenders lost on committed errors. Give them a fair,
honest rematch — tuning on train/validation only, the frozen test
split touched once, at the end:

- fastText: sweep word/character n-grams, learning rate, epochs.
- MiniLM: more epochs, per-language operating thresholds.
- **Ensemble policy (new):** a model may commit only when it agrees
  with the rules, or when the rules abstain AND model confidence
  clears a higher, validation-chosen bar. Measure committed-error
  rate of the *policy*, not the raw model.
- Adoption gate unchanged: zero committed errors on the trap
  families, no worse than rules overall. Report as an addendum to
  `docs/DECISION_MODEL_EVAL.md`, win or lose.

## WS-D — Prepaid-conversion offers (shadow)

The biggest lever in the market data is not judging orders better —
it is converting risky COD orders to prepaid (COD cancellation
37.3% vs prepaid ~2.8% at the studied retailer).

- For AMBER orders, a decision policy chooses: no offer, or a prepaid
  discount offer (seller-configured %, JazzCash/Easypaisa wording)
  attached to the verification message.
- v1 is **shadow + simulation**: the queue shows the offer the policy
  would send; a simulation on the synthetic benchmark reports
  projected conversion under *stated, adjustable* reply/conversion
  assumptions — labelled simulation everywhere, never as savings.
- Outcome fields exist from day one (offer sent / accepted / paid),
  so a real seller's data can replace assumptions without a rebuild.

## WS-E — Courier-choice recommendation (shadow)

- From courier outcome data already imported, compute per
  courier × city return rates with shrinkage toward the seller's
  overall rate (small samples must not produce confident nonsense).
- At dispatch, the queue shows the recommended courier for the order
  with its evidence ("Leopards returned 12% to Lahore vs TCS 21%,
  n=…"). Recommendation only — never auto-applied.
- Evaluation: replay on synthetic outcomes; report how often the
  recommendation matched the courier that actually collected, and
  the counterfactual return-rate difference, labelled synthetic.

## WS-F — Address-quality decision

A share of returns are not fake buyers but undeliverable addresses.

- v1 classifier over address text: missing house/street identifier,
  landmark-only, city-name mismatch or misspelling, too-short.
  Rules + features are fine; a trained model only if labelled data
  justifies it.
- A flagged address triggers one clarification request in the
  verification flow and shows in the queue as its own reason —
  separate from buyer risk, because the fix is different.
- Build a small labelled synthetic address set, freeze and hash it
  like the reply corpus, and report accuracy in the eval addendum.

## Non-negotiables (unchanged, all rounds)

- Synthetic stays labelled synthetic; simulations carry their
  assumptions; no invented pilots, savings, or accuracy.
- The Round 7 adoption gate and the conservative reply contract do
  not move. Shadow features never affect a dispatch decision.
- The demo must run fully offline with every new feature disabled.

## Report back

Per workstream: what was built, the measured numbers, and the full
test count. WS-A rehearsal results first.
