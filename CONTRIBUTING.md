# Contributing to COD-Guard

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt ruff
.\.venv\Scripts\python.exe scripts/build_demo.py
```

On Linux/macOS, use `.venv/bin/python`.

## Verification before opening a PR

1. Run the linter:
   ```bash
   ruff check .
   ```
2. Run the full test suite and artifact checks:
   ```bash
   python scripts/build_demo.py --verify-only
   ```
   If you intentionally change the synthetic benchmark generator or report format, run `python scripts/build_demo.py` to regenerate artifacts and verify `tests/test_claims.py` and `tests/test_public_benchmark.py` pass.

## Guardrails

- **Do not modify** `data/test_split.lock.json` or tune thresholds/models on the held-out test split.
- **Do not claim unmeasured merchant accuracy** in docs, UI copy, or README; `tests/test_claims.py` enforces baseline and synthetic disclaimers.
- Keep secrets, operator keys, and buyer phone/address fixtures synthetic in commits and tests.
