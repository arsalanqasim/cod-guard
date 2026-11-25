"""Durable, tenant-scoped voice jobs. Broker messages contain IDs only."""
import json
import os
from uuid import uuid4

from jobs import QueueFull
from platform_data import DataEncryptionError, connection, decrypt, encrypt, seal, unseal
from records import StateUnavailable, audit, connect, write
from verification import parse_reply, transcribe_voice_note


MAX_ACTIVE_PER_TENANT = 8
MAX_ATTEMPTS = 3
LEASE_SECONDS = 180
RELAY_SECONDS = 30


def broker_url():
    return os.environ.get("COD_GUARD_REDIS_URL", "")


def enqueue_voice(path, tenant_id, order_id, actor, suffix, audio):
    job_id = uuid4().hex
    with write(path, tenant_id=tenant_id) as db:
        active = db.execute("""SELECT COUNT(*) FROM merchant_voice_jobs
            WHERE tenant_id=? AND status IN ('queued', 'running') AND deadline > now()""", (tenant_id,)).fetchone()[0]
        if active >= MAX_ACTIVE_PER_TENANT:
            raise QueueFull("The voice queue is busy")
        db.execute("""INSERT INTO merchant_voice_jobs (id, tenant_id, order_id, actor, suffix, audio)
            VALUES (?, ?, ?, ?, ?, ?)""", (job_id, tenant_id, order_id, actor, suffix,
                                         seal(audio, tenant_id, job_id, "voice.audio")))
        audit(db, tenant_id, actor, "voice_requested", order_id=order_id, reference=job_id)
    return {"job_id": job_id, "status": "queued"}


def voice_status(path, tenant_id, order_id, actor, job_id):
    with connect(path, tenant_id=tenant_id) as db:
        row = db.execute("""SELECT status, result, error FROM merchant_voice_jobs
            WHERE tenant_id=? AND order_id=? AND actor=? AND id=?""",
                         (tenant_id, order_id, actor, job_id)).fetchone()
    if row is None:
        raise KeyError(job_id)
    response = {"job_id": job_id, "status": row["status"]}
    if row["result"] is not None:
        try:
            response["result"] = json.loads(decrypt(row["result"], tenant_id, job_id, "voice.result"))
        except (DataEncryptionError, ValueError) as exc:
            raise StateUnavailable("Voice result is unavailable") from exc
    if row["error"]:
        response["error"] = row["error"]
    return response


def relay(path, publish):
    with connection() as db:
        tenants = [row["id"] for row in db.execute("SELECT id FROM merchant_accounts")]
    for tenant_id in tenants:
        with write(path, tenant_id=tenant_id) as db:
            db.execute("""UPDATE merchant_voice_jobs SET status='failed', audio=NULL, claim=NULL,
                error='Voice processing expired. Upload the note again.', finished_at=now()
                WHERE tenant_id=? AND status IN ('queued', 'running')
                AND (deadline <= now() OR (status='running' AND attempts >= ? AND lease_until <= now()))""",
                       (tenant_id, MAX_ATTEMPTS))
            db.execute("""DELETE FROM merchant_voice_jobs WHERE tenant_id=?
                AND finished_at < now() - interval '1 day'""", (tenant_id,))
            pending = db.execute("""UPDATE merchant_voice_jobs SET relay_at=now() + make_interval(secs => ?)
                WHERE tenant_id=? AND relay_at <= now() AND deadline > now()
                AND (status='queued' OR (status='running' AND lease_until <= now()))
                RETURNING id""", (RELAY_SECONDS, tenant_id)).fetchall()
        for row in pending:
            publish(tenant_id, row["id"])


def purge_expired_auth():
    with connection() as db:
        for table in ("merchant_challenges", "merchant_invitations", "merchant_sessions", "merchant_auth_limits"):
            db.execute(f"DELETE FROM {table} WHERE expires <= now()")


def run_voice(path, tenant_id, job_id):
    claim = uuid4().hex
    with write(path, tenant_id=tenant_id) as db:
        job = db.execute("""UPDATE merchant_voice_jobs SET status='running', claim=?,
            lease_until=now() + make_interval(secs => ?), attempts=attempts+1
            WHERE tenant_id=? AND id=? AND deadline > now() AND attempts < ?
            AND (status='queued' OR (status='running' AND lease_until <= now()))
            RETURNING audio, suffix""", (claim, LEASE_SECONDS, tenant_id, job_id, MAX_ATTEMPTS)).fetchone()
    if job is None:
        return
    audio = unseal(job["audio"], tenant_id, job_id, "voice.audio")
    transcript = transcribe_voice_note(audio, suffix=job["suffix"])
    result = error = None
    status = "done"
    if transcript["ok"]:
        intent = parse_reply(transcript["text"]) if not transcript.get("warning") else "UNCLEAR"
        result = encrypt(json.dumps({**transcript, "intent": intent, "applied": False,
                                     "superseded": False, "needs_review": True}),
                         tenant_id, job_id, "voice.result")
    else:
        status = "failed"
        error = transcript["reason"]
    with write(path, tenant_id=tenant_id) as db:
        db.execute("""UPDATE merchant_voice_jobs SET status=?, result=?, error=?, audio=NULL, claim=NULL,
            finished_at=now() WHERE tenant_id=? AND id=? AND claim=? AND deadline > now()""",
                   (status, result, error, tenant_id, job_id, claim))
