"""Transactional integration jobs relayed through Celery with bounded retries."""
import json
from time import time
from uuid import uuid4

from platform_data import connection, decrypt, encrypt
from records import write

MAX_ATTEMPTS = 8


class PermanentFailure(RuntimeError):
    pass


def enqueue(db, tenant, kind, dedupe, payload):
    job = uuid4().hex
    db.execute("""INSERT INTO integration_jobs (tenant_id,id,kind,dedupe,payload)
        VALUES (?,?,?,?,?) ON CONFLICT (tenant_id,kind,dedupe) DO NOTHING""",
               (tenant, job, kind, dedupe,
                encrypt(json.dumps(payload, separators=(",", ":")), tenant, job, "integration.payload")))
    return job


def relay(path, publish):
    with connection() as db:
        tenants = [row["id"] for row in db.execute("SELECT id FROM merchant_accounts")]
    for tenant in tenants:
        with write(path, tenant_id=tenant) as db:
            interval = int(time()) // 300
            db.execute("""DELETE FROM integration_jobs WHERE tenant_id=? AND kind IN ('woo_poll','tcs_poll')
                AND finished_at<now()-interval '2 days'""", (tenant,))
            db.execute("""UPDATE merchant_verification_attempts SET status='expired' WHERE tenant_id=?
                AND expires_at<=now() AND status IN ('queued','submitting','accepted','unconfirmed')""", (tenant,))
            for store in db.execute("""SELECT id FROM merchant_connectors WHERE tenant_id=?
                AND kind='woocommerce' AND active""", (tenant,)):
                enqueue(db, tenant, "woo_poll", f"{store['id']}:{interval}", {"connector": store["id"]})
            if interval % 3 == 0:
                tracked = db.execute("""SELECT s.order_id FROM merchant_shipments s
                    JOIN merchant_connectors c ON c.tenant_id=s.tenant_id AND c.kind='tcs' AND c.active
                    WHERE s.tenant_id=? AND s.courier='tcs' AND s.terminal IS NULL
                    ORDER BY s.last_poll NULLS FIRST,s.order_id LIMIT 100""", (tenant,))
                for item in tracked:
                    enqueue(db, tenant, "tcs_poll", f"{item['order_id']}:{interval}", dict(item))
            db.execute("""UPDATE integration_jobs SET status='failed', claim=NULL, finished_at=now(),
                error='Job exhausted its retry budget' WHERE tenant_id=? AND status='running'
                AND lease_until<=now() AND attempts>=?""", (tenant, MAX_ATTEMPTS))
            jobs = db.execute("""UPDATE integration_jobs SET relay_at=now() + interval '30 seconds'
                WHERE id IN (SELECT id FROM integration_jobs WHERE tenant_id=? AND relay_at<=now()
                    AND run_after<=now() AND (status='queued' OR (status='running' AND lease_until<=now()))
                    ORDER BY run_after, created_at LIMIT 100)
                AND tenant_id=? RETURNING id""", (tenant, tenant)).fetchall()
        for job in jobs:
            publish(tenant, job["id"])


def run(path, tenant, job_id, handlers):
    claim = uuid4().hex
    with write(path, tenant_id=tenant) as db:
        job = db.execute("""UPDATE integration_jobs SET status='running', claim=?, attempts=attempts+1,
            lease_until=now()+interval '180 seconds' WHERE tenant_id=? AND id=? AND run_after<=now()
            AND attempts<? AND (status='queued' OR (status='running' AND lease_until<=now()))
            RETURNING kind,payload,attempts""", (claim, tenant, job_id, MAX_ATTEMPTS)).fetchone()
    if job is None:
        return
    status, error = "done", None
    try:
        payload = json.loads(decrypt(job["payload"], tenant, job_id, "integration.payload"))
        handlers[job["kind"]](tenant, payload)
    except PermanentFailure as exc:
        status, error = "failed", str(exc)
    except Exception:
        status, error = ("failed" if job["attempts"] >= MAX_ATTEMPTS else "queued"), "Integration request failed"
    delay = min(30 * 2 ** (job["attempts"] - 1), 3600) if status == "queued" else 0
    with write(path, tenant_id=tenant) as db:
        db.execute("""UPDATE integration_jobs SET status=?, error=?, claim=NULL, relay_at=now(),
            run_after=now()+make_interval(secs=>?),
            finished_at=CASE WHEN ?='queued' THEN NULL ELSE now() END
            WHERE tenant_id=? AND id=? AND claim=?""",
                   (status, error, delay, status, tenant, job_id, claim))
