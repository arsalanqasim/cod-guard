# COD-Guard — AI Pre-Dispatch Intelligence for COD E-Commerce

Verify the order, score the risk, ship only real orders.
AIC378 Speech Processing project (Dr. Amir Rashid) — approved 2026-11-18; exhibition: EE Flagship Event / TechForge, 2026-11-27/28.

## The problem
Only ~49 of every 100 Pakistani COD orders end in cash collected (OrderNation study, ~170k orders; 37.3% cancelled). Sellers pay courier charges both ways on fake/refused orders. COD-Guard attacks the loss **before dispatch**:
1. **Risk engine** — transparent rules + an ML model score every order (GREEN ship / AMBER verify / RED hold), each flag explained in plain words. No single signal blocks an order alone.
2. **Verification agent** — WhatsApp-style confirmation in English / Roman Urdu / Urdu script (+ Urdu voice notes via Whisper). A confirmation rescues a flagged genuine order (kills false positives); a denial stops a passed fake order (kills false negatives).
3. **Closed loop** — sellers record actual outcomes (delivered/returned/refused); outcomes retrain the next model version.

## Quick start (clean clone)
```bash
python -m venv .venv && source .venv/bin/activate   # or use an existing venv
pip install fastapi uvicorn streamlit scikit-learn pandas numpy faster-whisper httpx
python data/generate_benchmark.py        # synthetic benchmark (see honesty note)
python backend/app/train_model.py        # trains model, writes docs/EVAL_REPORT.md
python scripts/seed_demo.py              # 80 demo orders
python tests/test_risk_engine.py         # 3/3
python tests/test_verification.py        # 5/5
streamlit run frontend/dashboard.py      # the demo
# optional API:  uvicorn backend.app.main:app --reload   (run from repo root with backend/app on path — see main.py header)
```

## Honesty note (read before presenting)
- The benchmark dataset is **synthetic**, calibrated to published statistics (OrderNation). It is never real merchant data, and no seller pilots are claimed.
- Competitors exist (Tasdeek, Botaura, OrderWitness, DukaanFlow) and are named in the summary. COD-Guard's difference: the risk model **learns from delivered/returned outcomes** and verification understands **Urdu voice notes**.
- Full method, FP/FN results and the threshold trade-off: `docs/EVAL_REPORT.md`. Build spec: `docs/BUILD_SPEC.md`. Demo script: `docs/DEMO_SCRIPT.md`.
