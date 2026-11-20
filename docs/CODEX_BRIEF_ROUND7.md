# COD-Guard — Codex Mission Brief, Round 7: Decision Models for Reply Understanding

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex (lead).
Repo: `arsalanqasim/cod-guard`, main after Round 6 + cleanup.

## Why this round exists

Buyer-reply understanding is currently conservative rules over tested
phrases. That is safe but narrow: coverage beyond the tested phrases is
unmeasured, and everything unlisted falls to the operator.

A new model category fits this exact job: **decision models** —
specialised models that output *calibrated probabilities over a known
set of choices in a single forward pass*, built for cheap, fast,
accurate decisions at scale (Artificial Analysis, Decision Index v2.1).
Our choice set is known and small: CONFIRM / DENY / UNCLEAR /
MODIFICATION. Calibrated probabilities plug directly into the existing
contract: commit only above a confidence threshold, abstain to the
operator below it.

Candidates from the Decision Index (scores and costs as published by
Artificial Analysis, 20 Nov 2026 — their private benchmarks, English
decision tasks; treat as leads, not evidence for our data):

| Model | Provider | Decision Index | Cost / 1M tasks |
| --- | --- | ---: | ---: |
| d1.2-ultra | Liquid AI | 75 | $133 |
| Jev 1.14 | TypeSafe | 66 | $156 |
| Celeris-1.1 Decision | Celeris | 62 | $14 |

At these prices a decision costs a fraction of a rupee (≈ Rs 0.04 for
Jev) against ≈ Rs 4 for the WhatsApp message itself — API cost is not
the constraint. Language coverage is: none of the published benchmarks
test Roman Urdu or Urdu script. Our corpus decides.

**Cost order of preference (owner's instruction): free and local first.**
A local model has zero marginal cost, works offline (the exhibition
demo and sellers on bad connections), and sends no buyer text to any
provider. An API model is adopted only if every local contender fails
the WS-2 gate and the API contender passes it — and even then the
cheapest passing API wins, not the highest leaderboard score.

## WS-1 — Evaluation spike FIRST (gates everything else)

Build the reply-understanding benchmark before integrating anything:

- Corpus: every phrase already exercised by the parser tests and both
  reviews (the original traps, the Round 6 scope/time/hypothetical
  set), plus generated variations, in English, Roman Urdu and Urdu
  script, labelled CONFIRM / DENY / UNCLEAR / MODIFICATION. Freeze it
  as a versioned file with a hash, in the spirit of the test-split lock.
- Contenders, in the cost order above:
  1. **Local, free:** a trained fastText classifier; a fine-tuned
     multilingual MiniLM (ONNX, CPU) trained on the corpus's training
     portion; a zero-shot multilingual classifier (e.g. mDeBERTa-v3
     zero-shot) with no training; a small local model via Ollama
     (Llama 3.2 1B/3B or Qwen 2.5 small class) constrained to the
     choice set, if it runs acceptably on CPU.
  2. **Very-low-rate API:** Celeris-1.1 ($14 / 1M tasks).
  3. **Premium API (only if the above fail the gate):** Jev 1.14,
     d1.2-ultra — keys only if obtainable without payment commitments.
  4. The current rules parser, as the standing baseline every contender
     must beat.
- Metrics per contender, overall and per language: accuracy, Brier
  score / calibration, and **abstention quality** — at the operating
  threshold, how often a committed decision is wrong (the only number
  that can lose a seller money), plus coverage (how much operator load
  it actually removes).
- Deliverable: `docs/DECISION_MODEL_EVAL.md` with the full table and a
  recommendation. No integration in this workstream.

## WS-2 — Integration (only if WS-1 clears the gate)

Adoption gate: a contender may commit decisions only if, on the frozen
corpus, its committed-decision error rate is **zero on the DENY→SHIP
and CONFIRM→HOLD trap families** and no worse than rules overall, with
calibration good enough that the abstention threshold is meaningful.

- Architecture: decision model as an advisor inside the existing
  verification path. Order of authority stays: signed button taps →
  model/rules agreement above threshold → operator. Rules remain the
  offline fallback; if the provider is unreachable, behaviour is
  exactly today's.
- The conservative contract is unchanged: scoped, conditional and
  time-bound content never auto-commits, whatever the model says —
  enforce by construction (choice-set design + post-checks), not by
  trusting the model.
- Privacy and cost: send reply text only (no names, phones, addresses,
  order contents); per-tenant call accounting in PKR at the provider's
  published rate, alongside the WhatsApp cost ledger; tenant-level
  opt-in, off for the demo tenant by default so the exhibition flow
  stays fully offline.
- Regression: the full Round 1–6 parser/voice/decision suites must pass
  with the model path disabled and enabled (fixture provider).

## WS-3 — DM extraction assessment (report only)

Assess a decision model or small LLM for the social-intake extractor
(name/phone/address/items from pasted DM chats) against the current
narrow parser on a small labelled set of synthetic DM conversations.
Report accuracy and failure modes in the same eval document. No
integration in this round.

## Non-negotiables

- Published Decision Index scores are vendor-benchmark leads; the only
  claims COD-Guard may make come from WS-1's frozen corpus results.
- No buyer PII to any provider beyond the reply text itself.
- The exhibition demo must remain fully functional offline with the
  model path disabled.

## Report back

WS-1 eval document first, with the recommendation and the gate verdict,
before any WS-2 code. Per-PR: tests and full-suite counts as usual.
