# COD-Guard — Codex Mission Brief: Repository Cleanup

Owner: Arsalan Qasim. Integrator/reviewer: Muse. Executor: Codex.
Repo: `arsalanqasim/cod-guard`, main after the README upgrade.

## Purpose

The repository's front door is now product-facing (upgraded README).
The working papers of how it was built — briefs written for Codex,
review prompts, the two production reviews, the audit log, the original
build spec — are development history, not product documentation. They
remain permanently available in git history; they should no longer sit
in the tree a seller, investor, or examiner browses.

## Delete exactly these files

```text
docs/CODEX_PROMPT_1.md
docs/CODEX_REVIEW_PROMPT.md
docs/CODEX_BRIEF.md
docs/CODEX_BRIEF_ROUND2.md
docs/CODEX_BRIEF_ROUND4.md
docs/CODEX_BRIEF_ROUND5.md
docs/CODEX_BRIEF_ROUND6.md
docs/CODEX_BRIEF_REREVIEW.md
docs/PRODUCTION_REVIEW.md
docs/PRODUCTION_REVIEW_REREVIEW.md
docs/AUDIT.md
docs/BUILD_SPEC.md
```

Delete nothing else. In particular keep: BENCHMARK.md, EVAL_REPORT.md,
METRIC_PROTOCOL.md, DEMO_SCRIPT.md, VOICE_TEST.md, DARAZ_SPIKE.md,
COURIERS.md, COURIER_API_EVIDENCE.md, NETWORK.md, SHADOW_INTAKE.md,
SHOPIFY.md, SOCIAL_INTAKE.md, WHATSAPP.md, WHATSAPP_CLOUD.md,
WOOCOMMERCE.md, docs/screenshots/.

## Fix every inbound reference

Grep the whole tree (code, tests, docs, README, scripts) for:
`PRODUCTION_REVIEW`, `AUDIT.md`, `CODEX_BRIEF`, `CODEX_PROMPT`,
`BUILD_SPEC`. For each hit, either remove the reference or repoint it
to a surviving document that carries the same information (e.g. a
review verdict that the README or BENCHMARK.md now states). No link in
the tree may point at a deleted file. Where a test asserts the presence
of a deleted document, update the test to assert the surviving
equivalent or remove that assertion with a note in the PR description —
do not weaken any behavioural test.

## Conventions changed by this brief

- The "every PR adds an AUDIT.md entry" convention ends here; the PR
  description carries the change mapping from now on.
- This brief file itself (`docs/CODEX_BRIEF_CLEANUP.md`) is deleted in
  the same PR, after its instructions are executed.

## Verify and deliver

- `python scripts/build_demo.py` passes end to end; full unittest suite
  green (98 tests at the time of writing, plus/minus test updates made
  strictly per the reference rule above).
- A final grep for the deleted filenames across the tree returns hits
  only in git history, not in any tracked file.
- One PR, titled "Repository cleanup: remove development-history docs",
  whose description lists the deleted files and every reference that
  was repointed or removed.
