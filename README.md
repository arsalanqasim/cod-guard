# COD-Guard — local exhibition demo

Score COD orders before dispatch, verify replies in English / Roman Urdu / Urdu
script, transcribe Urdu voice notes, and learn from marked delivery outcomes.
AIC378, COMSATS. Functional deadline: **25 Nov 2026**; exhibition: **27–28 Nov**.

**All bundled orders and benchmark labels are SYNTHETIC. No real merchant pilots
or production accuracy are claimed.** Competitors include Tasdeek, Botaura,
OrderWitness and DukaanFlow. This project makes no claim of being first.

The dashboard is a local WhatsApp-style simulator. It sends no messages and
classifies text with conservative offline rules, not an LLM API.

## Setup (Windows PowerShell, Python 3.13)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe scripts/build_demo.py
.\.venv\Scripts\python.exe -m streamlit run frontend/dashboard.py
```

Open the URL printed by Streamlit (normally `http://127.0.0.1:8501`). On Linux,
use `.venv/bin/python` in place of `.venv\Scripts\python.exe`.
Stop and restart Streamlit after pulling backend or dependency changes so it
loads the new modules rather than retaining the old service in memory.
`build_demo.py` regenerates the synthetic benchmark, trains a baseline model,
seeds 80 demo orders, runs both original test scripts, runs the regression / API /
dashboard / learning tests, and checks dependencies. It reports the failed command
and exits on error. Rebuilding replaces the baseline model; previously marked
outcomes remain saved and can be learned again. Use `--verify-only` to check
existing generated artifacts without rebuilding them.

The individual commands remain available, in order:

```text
python data/generate_benchmark.py
python backend/app/train_model.py
python scripts/seed_demo.py
python tests/test_risk_engine.py
python tests/test_verification.py
python -m unittest discover -s tests -p "test_*.py" -v
streamlit run frontend/dashboard.py
```

## Voice setup (once, while online)

```powershell
.\.venv\Scripts\python.exe scripts/prepare_voice.py
.\.venv\Scripts\python.exe scripts/test_voice.py
# Or use your own short Urdu reply:
.\.venv\Scripts\python.exe scripts/test_voice.py C:\path\to\reply.ogg
```

Public multilingual Whisper `small` weights download to ignored `data/whisper/`.
Inference then defaults to **offline**, CPU/int8. Allow several hundred MB for the
weights. The dashboard accepts an upload or microphone recording, shows the
unaltered transcript, and requires an explicit apply action. Notes must be at most
60 seconds / 12 MiB. Silence and low-confidence results ask for another reply.

The bundled clip is general Urdu speech from Google FLEURS (CC BY 4.0), not a
customer recording. Attribution is in `data/voice_samples/ATTRIBUTION.md`;
[the actual imperfect transcript and dependency fix](docs/VOICE_TEST.md) are recorded.
PyAV **16.1.0 is pinned** because PyAV 19 breaks faster-whisper 1.2.1's decoder.
The model is cached in memory after its first use in each process.

## What to demonstrate

- **Orders & risk.** The paginated queue shows reasons, rule score, ML estimate,
  current decision and risk zones. With complete features, the pre-reply policy
  requires two distinct adverse signal groups to flag an order. The address
  checks share a group. ML refines the estimate. Missing features require
  verification, and a customer denial can also stop a GREEN order.
- **Verification:** select a RED order and confirm it → SHIP. Select a GREEN
  order and deny it → HOLD_CANCEL. History is durable; an unclear follow-up cannot
  erase an explicit answer. Upload, record, or transcribe the attributed Urdu sample.
- **Metrics & learning:** [locked public benchmark](docs/BENCHMARK.md), both error rates, confusion matrix, test threshold
  trade-off, and baseline costs are visible. Mark an outcome, then click
  **Retrain from marked outcomes**. A new version visibly consumes the label and
  re-evaluates the same held-out orders. Metrics may improve or worsen.

## Measured performance and limits

See [the generated evaluation](docs/EVAL_REPORT.md) and `data/evaluation.json`.
**Baseline v1** on 1,184 synthetic test orders has **FPR 16.47% and FNR
59.23%** at validation-selected threshold 0.50. A flag is any AMBER or RED
recommendation before a reply. The counts were TP=245, FP=96, FN=356 and TN=487.
Illustrative loss is PKR 274,600, versus PKR 390,650 for shipping everything and
PKR 259,800 for blocking on any adverse signal. **It does not beat that aggressive
baseline on cost, and low FP plus low FN has not been established.** The dashboard
shows this limitation openly. Failed labels cover non-collection, not proven fraud.

The generator produces 50.7% failed labels and targets 51% expected
non-collection. It uses the low end of OrderNation's approximate range of
49–57 cash collections per 100 COD orders. The study reflects one retailer
and mixes measurement windows. Its 37.3% cancellation figure measures a
different stage of the funnel. Feature relationships are simulation assumptions.

Model/threshold selection uses validation only. Evaluation calls the same policy
as serving. All 80 demo orders are reserved outside training/validation/test, so
marked demo outcomes can enter training without leaking into the holdout. The
marked-outcome comparison uses the decision revision frozen with the first
outcome. Corrections retain that revision. Older records without a frozen
decision remain unscored. These are retrospective demo measurements.

## Optional API and local state

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open the API docs at `http://127.0.0.1:8000/docs`. Configure operator keys
and a separate tenant for authenticated CSV intake. Voice returns a job ID to
poll for the transcript. The default is preview, and `commit_decision=true`
applies an eligible transcript. [Shadow intake and retention](docs/SHADOW_INTAKE.md)

The API and synthetic dashboard share transactional SQLite state in
`data/state.sqlite3`. An existing `data/state.json` is imported once and
archived. The reserved `demo` tenant uses the bundled seed. The API runs on
loopback for a single-instance shadow workflow with human review.

For isolated checks, set `COD_GUARD_DATA_DIR` and `COD_GUARD_MODEL_PATH` to an
alternate state directory and a copy of a trained model. Set the same variables
for API and dashboard when they should share the profile.

On this Windows machine, pip's default certificate path timed out and produced
misleading `No matching distribution` errors. The following venv-only setting
made the same index query succeed; HTTPS verification remains enabled:

```powershell
.\.venv\Scripts\python.exe -m pip config --site set global.use-deprecated legacy-certs
.\.venv\Scripts\python.exe -m pip install --timeout 60 --retries 3 -r requirements.txt
```

CI rebuilds and tests the demo on Windows and Linux. The real cached-weight voice
smoke test is separate: `python scripts/build_demo.py --verify-only --voice`.
