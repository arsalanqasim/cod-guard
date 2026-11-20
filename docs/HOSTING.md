# Single-host deployment

From a clean checkout with Python 3.13, run:

```text
python scripts/run_host.py --bootstrap
```

The launcher installs the pinned dependencies in a project-local virtual
environment, provisions a baseline if necessary, then starts the API
and the exhibition dashboard on separate loopback ports. The API binds
to `127.0.0.1:8000`; the dashboard binds to `127.0.0.1:8501`. Press
Ctrl+C to stop both. For a host with the pinned packages installed,
`python scripts/run_host.py` uses that environment. The
`--smoke` option uses disposable state, checks API readiness and
anonymous access rejection, checks dashboard health, then stops both.

## Host boundary

- Use a local persistent volume for `--data-dir` or `COD_GUARD_DATA_DIR`.
  It holds SQLite and the active model version directory. Keep the
  launcher under a process supervisor with one writer installation.
  Include the model artifacts with the state backup and test a restore
  before relying on it. [State intake and backup](SHADOW_INTAKE.md)
- Use the host’s HTTPS reverse proxy in front of the API for a remote
  installation. Keep the exhibition dashboard loopback-only or behind
  operator-controlled access. It opens fresh synthetic state, forces
  offline mode, and disables the opt-in features. The backend and
  dashboard use distinct state and model directories.
- Inject operator and connector secrets through the host’s secret
  store. Keep env files and artifacts outside the repository. The
  launcher disables API access logs. In proxy logs, omit authorization
  headers, bodies, and query strings, including the Meta webhook
  challenge token. Keep the process account and the persistent volume
  restricted to the host operator.
- Default order list and detail responses mask phones. Detail also masks
  recognizable Pakistani mobile numbers in replies. An authenticated
  `GET /orders/{id}?reveal_phone=true` explicitly reveals phones and writes
  a `phone_read` audit event for that tenant. Order responses opt out of
  caching. Treat the separately authorized corrections export as private
  because buyers can type identifying details.
- Keep the live WhatsApp gate off while onboarding. [Meta checklist and configuration](WHATSAPP_CLOUD.md)

This is a single-host native package. Merchant throughput, uptime and
monthly hosting cost remain unmeasured on a paid host.

## Seller-scoped risk shadow

Train with an authorized seller’s own settled COD orders. Supply private
UTF-8 CSV with one row per order and these exact columns:

```text
order_id,customer_id,order_day,amount_pkr,items_count,label_failed
```

Use seller-local stable IDs, ISO purchase dates, positive item counts,
and a binary resolved COD label. The trainer derives the repeat flag
from strictly earlier purchase days and holds out customers and time
windows. Register the existing seller’s real repeat flag and other
purchase-time features when orders enter the API. The model uses the
raw purchase-time values and abstains from scoring incomplete rows.

```text
python scripts/train_seller_risk.py --tenant seller-a --seller-csv PATH_TO_PRIVATE_CSV --output PATH_TO_PRIVATE_ARTIFACT
```

Point `COD_GUARD_RISK_SHADOW` at the trusted local artifact, with optional
seller-adjustable thresholds. Each artifact must match the authenticated
tenant. The loader accepts seller artifacts built by the trainer. Only
an administrator should install these local Python model files.

```json
{
  "seller-a": {
    "artifact": "/srv/cod-guard/private/seller-a.pkl",
    "bands": {"verify_at": 0.35, "hold_at": 0.85}
  }
}
```

The order queue includes a model-first shadow preview. `GET
/orders/{id}/risk-shadow` returns the current preview and recorded
decision revisions, with an optional `after` cursor. Each revision shows
the actual decision, proposed decision, calibrated probability, band,
policy constraints, and the leading additive drivers. The audit stores
the thresholds and model ID used at the time of the decision.
The failed [PK-REAL] and [PK-SYNTH] gate keeps this advisory.
[Round 9 evaluation](ROUND9_EVAL.md)
