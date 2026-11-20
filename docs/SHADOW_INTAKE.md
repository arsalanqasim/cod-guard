# Single-instance shadow intake

Run the API on loopback. Set `COD_GUARD_OPERATORS` to a JSON object keyed by
operator name. Each record has a `tenant_id` and a `key` of at least 24
characters. Generate an independent random key for every operator and supply
it as `Authorization: Bearer <key>`. Keep the environment configuration out of
the repo. Use the reserved `demo` tenant for the seeded synthetic orders.

Send a UTF-8 CSV as multipart field `file` to `POST /orders/import` with an
`Idempotency-Key` unique within the tenant. Use a separate shadow tenant. The
required columns are `order_id`, `customer_name`, `product`, and `phone`.
Optional columns are `city`, `phone_valid`, `phone_fraud_history`,
`phone_velocity_24h`, `address_words`, `address_has_landmark`, `amount_pkr`,
`items_count`, `order_hour`, `is_repeat_customer`, `customer_past_delivered`
and `customer_past_refusals`. Empty features require verification. Malformed
values and duplicate IDs are returned with their CSV row numbers. A replay
with the same key and contents returns the same receipt. A changed payload
with that key returns 409. The import accepts 1 MiB and 2,000 data rows.

Order lists mask phone numbers. Authenticated order detail logs full-phone
access. Reply and outcome writes retain the actor and tenant. Reply parsing
requires an approved whole-order answer to the order-specific
prompt. An unclear answer keeps the prior decision and requests review.
On order detail and list, `verified` means an explicit answer is current and
there is no unresolved reply requiring review. `intent` there is the effective
saved intent. The verify response and reply history show the new reply's intent.
Synthetic retraining is restricted to the demo tenant and returns a job ID. Its
submitting operator can poll `GET /model/retrain/{job_id}` in that process.
Voice and retrain job IDs and statuses are process-local and lost on restart.
Check `/model` and its pending feedback before retrying training. An already
activated version remains on disk. Resubmit voice audio for preview if needed.

`/health` reports process liveness. `/ready` returns 200 when SQLite can read
the order, decision and outcome tables and the active pointer selects a
valid model with matching evaluation JSON and rendered Markdown. Readiness
returns 503 with `state_unavailable`, `model_unavailable` or
`evaluation_unavailable` when those checks fail. A legacy model can still
score orders while a missing versioned evaluation leaves the API unready.
This probe covers local reads and artifacts. Provider and worker status
need separate checks. Write requests are limited to 60
per operator per minute in one process. The API accepts at most 13 MiB per
request, including multipart framing.

Run `python scripts/purge_replies.py` daily to clear expired reply bodies and
voice transcripts while preserving decisions and audit metadata. The default
window is 30 days. Set `COD_GUARD_REPLY_RETENTION_DAYS` or pass `--days` to
change it. Raw audio is transient. Apply the same retention policy separately
to SQLite snapshots and the legacy JSON archive. Use a restricted backup
directory and test restoration with `python scripts/backup_state.py SOURCE
DESTINATION` before migration. Shadow recommendations are for human review.
