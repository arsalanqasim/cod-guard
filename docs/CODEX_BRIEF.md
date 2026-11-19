# COD-Guard — Mission Brief for Codex (you lead the build)

## The mission
COD-Guard is a university exhibition project (AIC378, COMSATS) with a fixed display date: 27–28 Nov 2026, and a functional deadline of 25 Nov. It is an AI pre-dispatch intelligence system for Pakistani Cash-on-Delivery e-commerce: score every order's fake/refusal risk before dispatch, verify risky orders with the customer over a WhatsApp-style conversation (English / Roman Urdu / Urdu script / Urdu voice notes), and learn from actual delivered/returned outcomes.

## What success looks like at the stall
1. A seller opens the dashboard and sees orders with risk zones and plain-words reasons.
2. A judge can run the verification flow live: a flagged order rescued by a customer confirmation, a clean order stopped by a denial.
3. FP/FN performance is measured and shown (confusion matrix, threshold trade-off), not claimed — the professor explicitly required the system to be strong on BOTH false positives and false negatives.
4. An Urdu voice note gets transcribed and understood.
5. Marking an outcome visibly feeds the learning loop.

## What already exists in this repo (starting point, not a cage)
Risk engine (rules + gradient-boosting model), verification agent core, FastAPI backend, Streamlit dashboard, a 6,000-order synthetic benchmark + evaluation report, tests (3/3 + 5/5 passing), a build spec (docs/BUILD_SPEC.md) and a demo script (docs/DEMO_SCRIPT.md). Baseline measured: FP rate ~4.9% at the chosen threshold, organised-fake recall ~0.87, loss −29% vs ship-everything.

## Your mandate
You lead. Audit what exists; keep, rewrite, restructure or replace anything you judge weak — architecture, models, UI framework, conversation handling, evaluation design are all your call. Improve the FP/FN numbers if you can and show the new measurements. Plan your own steps. Work on codex/<task> branches and open PRs against main; Muse reviews, runs the pipeline independently, and merges — that is the only gate, and it exists because two builders writing main at once corrupts work, not to supervise your engineering.

## Fixed requirements (these come from the professor and from verified facts, not preference)
- Honesty: the benchmark is SYNTHETIC, calibrated to the OrderNation study (~170k real orders; 37.3% COD cancelled, ~49/100 orders end in cash). It must stay labelled synthetic everywhere it appears. Never claim real merchant pilots — none exist.
- Competitors exist and are named openly: Tasdeek, Botaura, OrderWitness, DukaanFlow. Never claim "first". The defensible difference: a risk model that learns from courier delivered/returned outcomes + Urdu voice-note understanding.
- FP/FN design rule: no single signal may block an order on its own, and customer confirmation overrides a flag while a denial overrides a pass — this is the professor's explicit requirement.
- If something in this brief conflicts with what the code or data actually shows, trust the evidence and flag the conflict in your PR.

Report results with exact numbers and exact errors. If a step fails, say so plainly.
