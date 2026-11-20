# Operator reply corrections

The verification tab accepts an operator label for the latest active text reply or applied voice transcript. Open **Correct the latest reply**, choose the final intent, and save. An explicit confirmation releases the order and a denial cancels it. A modification or unclear label requests follow-up and holds dispatch for review. A still-relevant earlier denial stays in effect. The original buyer text and parser label remain linked to the correction.

## API and export

Use the existing bearer-authenticated tenant account. Read the order detail to get the current `decision_revision` and the source reply’s `messages[].decision_revision`. Submit both revisions so a stale screen cannot override a newer reply or storefront update.

```http
POST /orders/{order_id}/replies/{reply_revision}/correction
Content-Type: application/json

{"label":"DENY","expected_revision":3}
```

Accepted labels are `CONFIRM`, `DENY`, `UNCLEAR`, and `MODIFICATION`. On a later amendment, keep the same source reply revision and use the latest order decision revision. HTTP 409 indicates a stale, superseded, closed, expired, or unavailable reply. Signed WhatsApp button taps are excluded from the correction and shadow paths. Historical WhatsApp rows with exact button display text are excluded because their stored source cannot distinguish a tap from typed text.

`GET /reply-corrections/export?after=0&limit=500` downloads version 1 NDJSON for the caller’s tenant. For additional pages, pass the response’s `X-Next-Cursor` as `after`. Each row includes the correction and message IDs, original reply body and parser label, the operator’s final label, a heuristic language guess, and any linked shadow predictions. If an operator amends a label, the log keeps both entries. The existing raw reply retention job removes the source body from the export while preserving decision and correction history. Export reads are audited.

Keep exports in the tenant’s approved storage. A reply body may contain information the buyer typed into the chat.

## Local shadow evaluation

Run an optional benchmark artifact with the [evaluation dependencies](DECISION_MODEL_EVAL.md#reproduce-on-cpu) from the machine that owns the SQLite state. Select a tenant explicitly and use an artifact you built or verified. Each run scores up to 500 retained replies that the artifact has not seen in shadow. Repeat to process a backlog.

```powershell
python scripts/shadow_reply_model.py --tenant seller-tenant --kind fasttext --artifact .venv/round7/run/reply.fasttext.bin
```

The command uses `COD_GUARD_DATA_DIR` or the repository data directory. Pass `--state` to choose a different state path. For `--kind minilm` or `--kind zero-shot`, pass the corresponding model directory. The prediction is joined to the latest human label by message ID. `GET /reply-corrections/shadow` returns predicted, labeled and matched counts and agreement per artifact. A shadow run reads reply text locally, writes predictions and an audit event, and has no dispatch authority. The demo has no automatic shadow job.

## Manual retraining

1. Export one tenant’s corrections, page through all rows, and assemble them as one NDJSON file. Review final labels, remove reply bodies outside the approved training scope, and keep a separate prospective set of merchant replies for evaluation. Keep all variants from the same conversation in the same split.
2. Refit the local models. The evaluator keeps the latest label per source message, excludes exact reserved texts, and uses the export as additional training data. Review near-duplicates before fitting. Use a fresh work directory for each run.

   ```powershell
   python scripts/evaluate_reply_models.py --corrections PATH_TO_REVIEWED_EXPORT --work-dir .venv/round7/candidate --minilm-checkpoint .venv/round7/original
   ```

3. Compare the new candidate with the rules against the frozen regression and test corpus, then run the same metrics on the prospective merchant set. Use shadow evaluation on fresh replies to measure agreement. The training command writes candidate artifacts and metrics locally. Adoption remains subject to the Round 7 gate.
