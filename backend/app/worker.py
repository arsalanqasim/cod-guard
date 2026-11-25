"""Celery entry point for merchants' background work."""
import sys
from pathlib import Path

from celery import Celery

sys.path.insert(0, str(Path(__file__).resolve().parent))
import platform_jobs
import integration_jobs
import merchant_events
import merchant_couriers
import merchant_shopify
import merchant_shopify_privacy
import merchant_verification
import merchant_woo
from service import STATE_PATH


if not platform_jobs.broker_url():
    raise RuntimeError("Set COD_GUARD_REDIS_URL before starting merchant workers")

app = Celery("cod_guard", broker=platform_jobs.broker_url())
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 240, "socket_connect_timeout": 3, "socket_timeout": 3},
    task_default_queue="control",
    beat_schedule={
        "relay-merchant-jobs": {"task": "cod_guard.relay", "schedule": 5.0, "options": {"expires": 5}},
        "purge-expired-auth": {"task": "cod_guard.purge_expired_auth", "schedule": 3600.0},
    },
)


@app.task(name="cod_guard.relay")
def relay():
    platform_jobs.relay(STATE_PATH, publish_voice)
    integration_jobs.relay(STATE_PATH, publish_integration)


def publish_voice(tenant_id, job_id):
    voice.apply_async((tenant_id, job_id), queue="voice", ignore_result=True, retry=False)


def publish_integration(tenant_id, job_id):
    integration.apply_async((tenant_id, job_id), queue="integrations", ignore_result=True, retry=False)


@app.task(name="cod_guard.integration", time_limit=150, soft_time_limit=140)
def integration(tenant_id, job_id):
    integration_jobs.run(STATE_PATH, tenant_id, job_id, {
        "erp_webhook": lambda tenant, payload: merchant_events.deliver(STATE_PATH, tenant, payload),
        "shopify_setup": merchant_shopify.setup,
        "shopify_writeback": merchant_shopify.writeback,
        "shopify_privacy": merchant_shopify_privacy.process,
        "woo_setup": lambda tenant, payload: merchant_woo.sync(tenant, payload, setup=True),
        "woo_poll": merchant_woo.sync,
        "woo_writeback": merchant_woo.writeback,
        "buyer_contact": merchant_verification.send,
        "buyer_audio": merchant_verification.transcribe,
        "courier_terminal": merchant_couriers.apply_terminal,
        "tcs_poll": merchant_couriers.poll_tcs,
    })


@app.task(name="cod_guard.purge_expired_auth")
def purge_expired_auth():
    platform_jobs.purge_expired_auth()



@app.task(name="cod_guard.voice", time_limit=150, soft_time_limit=140)
def voice(tenant_id, job_id):
    platform_jobs.run_voice(STATE_PATH, tenant_id, job_id)
