# COD-Guard — Build Spec (AIC378, Dr. Amir Rashid)

Approved in class Wed 2026-11-18. Fully functional due Wed 2026-11-25; display at EE Flagship Event Fri–Sat 2026-11-27/28 (TechForge).

## What it is
AI-Powered Pre-Dispatch Intelligence for Pakistani COD e-commerce: verify the order with the customer and score its risk BEFORE dispatch, so sellers ship real orders only.

## Team procedure (same as Tech Fest / AI Agents Arena)
- Muse (integrator): writes code on the VM, pushes to GitHub, reviews/merges Codex branches, posts a live task board each phase.
- Codex (builder-executor on Arsalan's laptop): receives prompts from Muse via Arsalan, works on codex/<task> branches, pushes back.
- Arsalan: never edits code. His jobs: create the repo, git pull, run the exact commands Muse sends, handle account approvals/popups.

## Modules
1. Order intake — orders enter via a demo order form / CSV import (Shopify-shaped fields: name, phone, address, city, items, amount, COD). Designed so a real Shopify webhook can replace the form later.
2. Risk engine — two layers:
   - Rules v0 (transparent signals: phone format/repeat-fraud number, address completeness, city risk, order-value pattern, repeat customer history, order velocity).
   - ML score trained on the benchmark dataset (below). Output = score 0–100 + zone: GREEN (ship), AMBER (verify first), RED (hold / do not ship without confirmation).
   - No single signal blocks an order alone (sir's FP/FN requirement).
3. Verification agent — WhatsApp-style chat (Urdu/English, LLM) that confirms the order with the customer; Urdu voice notes transcribed (Whisper). Customer reply updates the risk decision: confirmed → ship even if AMBER; denied/unreachable + high risk → hold.
   - Transport: demo chat UI first (works offline at a stall); real WhatsApp Cloud API is a stretch goal behind the same interface (template approval is the known risk).
4. Seller dashboard — order list with risk colours and reasons ("why flagged" in plain words), FP/FN metrics page, one-click outcome marking (Delivered / Returned / Refused) = the closed learning loop.
5. Evaluation harness (sir's requirement: low FP AND low FN, measured, not claimed)
   - Benchmark dataset: synthetic-but-calibrated orders generated from published Pakistani COD statistics (OrderNation study: ~170k orders, 37.3% COD cancelled, ~49/100 end in cash collected), labelled genuine vs fake/refused. Clearly labelled SYNTHETIC in every report — never presented as real merchant data.
   - Report: confusion matrix, false-positive rate, false-negative rate, precision/recall, and a threshold sweep showing the FP↔FN trade-off curve; operating threshold chosen by cost (FN cost = courier + return charges; FP cost = lost profit on a real sale).
   - Acceptance target: beat the two naive baselines (ship-everything and block-everything-flagged) on total cost.

## Honesty constraints (from verification, 2026-11-17)
- Never claim "first" — competitors (Tasdeek, Botaura, OrderWitness, DukaanFlow) exist and are named in the summary.
- Do NOT claim Arsalan's 25+ Upwork-client stores as pilots; his edge = proven Shopify automation experience only.
- COD problem numbers: 15–40% range + OrderNation study, footnoted. PKR figures labelled "target", not revenue.
- Defensible difference, only if actually built: risk model learns from delivered/returned outcomes (closed loop) + Urdu voice-note verification.

## Stack
FastAPI backend, Streamlit dashboard (matches Arsalan's existing Shopify-tool experience), SQLite for demo data, scikit-learn for the risk model, Whisper for Urdu voice notes, LLM via API for the verification chat.
