"""Outbound decision and verification events without buyer information."""
import hashlib
import hmac
import json
from time import time
from uuid import uuid4

import merchant_connectors
import public_https
from integration_jobs import PermanentFailure, enqueue
from records import connect


def queue_order_event(db, tenant, order_id, event_type, fields):
    external = db.execute("""SELECT external_id,channel,account FROM external_orders
        WHERE tenant_id=? AND order_id=?""", (tenant, order_id)).fetchone()
    if external is None:
        return
    storefront_job = {"SHOPIFY": "shopify_writeback", "WOOCOMMERCE": "woo_writeback"}.get(external["channel"])
    if storefront_job:
        enqueue(db, tenant, storefront_job, f"{order_id}:{event_type}:{fields['revision']}", {
            "connector": external["account"], "external_id": external["external_id"], "order_id": order_id,
            "kind": "outcome" if event_type == "order.outcome" else "decision",
        })
    if external["channel"] != "ERP":
        return
    event = {"id": uuid4().hex, "version": 1, "type": event_type, "order_id": order_id,
             "external_order_id": external["external_id"], **fields}
    subscriptions = db.execute("""SELECT id FROM merchant_connectors
        WHERE tenant_id=? AND kind='erp_webhook' AND active""", (tenant,))
    for subscription in subscriptions:
        destination = subscription["id"]
        enqueue(db, tenant, "erp_webhook", f"{destination}:{order_id}:{event_type}:{fields['revision']}",
                {"destination": destination, "event": event})


def deliver(path, tenant, payload):
    with connect(path, tenant_id=tenant) as db:
        try:
            connector = merchant_connectors.read(db, tenant, payload["destination"], "erp_webhook")
        except KeyError:
            return
    event = payload["event"]
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time()))
    secret = connector["credentials"]["secret"].encode()
    digest = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    status, _, _ = public_https.request("POST", connector["credentials"]["url"], headers={
        "Content-Type": "application/json", "X-COD-Guard-Event": event["id"],
        "X-COD-Guard-Timestamp": timestamp, "X-COD-Guard-Signature": "sha256=" + digest,
    }, body=body, limit=65536)
    if 200 <= status < 300:
        return
    if status in (408, 425, 429) or status >= 500:
        raise RuntimeError("Webhook delivery is retryable")
    raise PermanentFailure(f"Webhook rejected the delivery (HTTP {status})")
