# CODEX PROMPT #1 — COD-Guard local setup + review (paste into Codex)

You are the builder-executor on a 3-person team (Muse = integrator, Arsalan = owner/runner, you = local builder) building COD-Guard, an AI pre-dispatch verification + risk-scoring system for Pakistani COD e-commerce. It is a university project (AIC378) with a hard exhibition deadline; Muse integrates and merges — you work on branches named codex/<task> and push to this repo.

Step 1 — setup: clone this repo, create a venv, install: fastapi, uvicorn, streamlit, scikit-learn, pandas, numpy, faster-whisper. Run in order and report exact results:
  python data/generate_benchmark.py
  python backend/app/train_model.py
  python scripts/seed_demo.py
  python tests/test_risk_engine.py   (expect 3/3)
  python tests/test_verification.py  (expect 5/5)
  streamlit run frontend/dashboard.py  (confirm it opens; check all 3 tabs)

Step 2 — review (branch codex/review-1): read backend/app/risk_engine.py, verification.py, service.py, train_model.py. Report flaws, edge cases and FP/FN risks you find; fix only clear bugs, each as its own commit with a one-line message. Do NOT redesign, do NOT rename files, do NOT touch docs/BUILD_SPEC.md honesty constraints.

Step 3 — voice notes (branch codex/voice-1): using verification.transcribe_voice_note(), add a small script scripts/test_voice.py that transcribes a sample Urdu voice note file (record one or use any .ogg/.mp3) and prints the transcript + parse_reply() intent for it. Report the transcript verbatim, even if imperfect.

Rules: never present the synthetic benchmark as real merchant data; never claim the product is "first" (competitors Tasdeek/Botaura/OrderWitness/DukaanFlow exist); if a step fails, stop and report the exact error instead of working around it silently.
