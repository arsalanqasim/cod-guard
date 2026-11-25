"""Self-serve WooCommerce authorization and tenant-bound order delivery."""
import hmac
import json
from secrets import token_urlsafe
from time import time
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import merchant_connectors as settings
import public_https
import service
import woocommerce as woo
from connector_orders import ingest
from integration_jobs import enqueue
from merchant_integration_routes import owner_write, require_platform
from operators import Operator
from records import audit, connect, write


router = APIRouter()
KIND = "woocommerce"
TOPICS = ("order.created", "order.updated")


class Install(BaseModel):
    url: str = Field(min_length=1, max_length=300)


class IssuedKeys(BaseModel):
    user_id: str | int
    consumer_key: str = Field(pattern=r"^ck_[A-Za-z0-9]{40}$")
    consumer_secret: str = Field(pattern=r"^cs_[A-Za-z0-9]{40}$")
    key_permissions: Literal["read_write"]


class Writeback(BaseModel):
    hold_on_unverified: bool = False
    release_on_confirmed: bool = False
    write_outcomes: bool = False


def store_from(row):
    credentials = row["credentials"]
    return woo.Store(row["id"], row["tenant_id"], row["address"], credentials["key"],
                     credentials["secret"], credentials["webhook_secret"])


@router.post("/merchant/woocommerce/authorize")
def authorize(body: Install, operator: Operator = Depends(owner_write)):
    url = body.url.rstrip("/")
    try:
        parts = public_https.endpoint(url)
        if parts.query:
            raise ValueError("Use the WooCommerce site base URL")
        public_https.verify_url(url)
        base = settings.public_base()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    proof = token_urlsafe(32)
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        connector_id = settings.create(db, tenant, KIND, parts.hostname, url, {
            "proof": proof, "expires": int(time()) + 600, "webhook_secret": token_urlsafe(32),
        }, active=False)
    params = urlencode({"app_name": "COD-Guard", "scope": "read_write", "user_id": connector_id,
                        "return_url": settings.portal_home(),
                        "callback_url": f"{base}/providers/woocommerce/{tenant}/{connector_id}/authorize/{proof}"})
    return {"authorize_url": f"{url}/wc-auth/v1/authorize?{params}"}


def _pending(db, tenant, connector, proof):
    try:
        row = settings.read(db, tenant, connector, KIND, active=False)
    except KeyError:
        raise HTTPException(404, "WooCommerce connection request not found") from None
    fields = row["credentials"]
    if ("proof" not in fields or fields["expires"] < time() or not proof.isascii()
            or not hmac.compare_digest(fields["proof"], proof)):
        raise HTTPException(404, "WooCommerce connection request not found")
    return row


@router.post("/providers/woocommerce/{tenant}/{connector}/authorize/{proof}")
def receive_keys(tenant: str, connector: str, proof: str, body: IssuedKeys):
    require_platform()
    if body.user_id != connector:
        raise HTTPException(400, "WooCommerce connection reference did not match")
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        row = _pending(db, tenant, connector, proof)
    credentials = {"key": body.consumer_key, "secret": body.consumer_secret,
                   "webhook_secret": row["credentials"]["webhook_secret"]}
    store = store_from({**row, "credentials": credentials})
    try:
        data, _ = woo.WooCommerceClient(store).request("orders", params={"per_page": 1, "_fields": "id"})
        if not isinstance(data, list):
            raise woo.WooCommerceError("WooCommerce returned invalid order data")
    except woo.WooCommerceError:
        raise HTTPException(502, "WooCommerce could not verify the generated REST credentials") from None
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        _pending(db, tenant, connector, proof)
        settings.update_credentials(db, tenant, connector, credentials)
        db.execute("UPDATE merchant_connectors SET active=true WHERE tenant_id=? AND id=?", (tenant, connector))
        enqueue(db, tenant, "woo_setup", connector, {"connector": connector})
        audit(db, tenant, "woocommerce", "store_authorized", reference=connector)
    return {"status": "connected"}


@router.post("/providers/woocommerce/{tenant}/{connector}/orders")
async def orders(tenant: str, connector: str, request: Request):
    require_platform()
    def get_store():
        with connect(service.STATE_PATH, tenant_id=tenant) as db:
            return store_from(settings.read(db, tenant, connector, KIND))

    try:
        store = await run_in_threadpool(get_store)
    except KeyError:
        raise HTTPException(404, "WooCommerce store not found") from None
    body = await request.body()
    if len(body) > woo.MAX_BODY:
        raise HTTPException(413, "WooCommerce payload too large")
    signature = request.headers.get("X-WC-Webhook-Signature")
    if not signature and body.startswith(b"webhook_id=") and body[11:].isdigit() and len(body) <= 31:
        return Response(status_code=200)
    if not woo.signed_webhook(store, body, signature):
        raise HTTPException(401, "Invalid WooCommerce signature")
    if request.headers.get("X-WC-Webhook-Topic") not in TOPICS:
        raise HTTPException(422, "Expected a WooCommerce order event")
    try:
        order = woo.parse_order(json.loads(body))
        added = await run_in_threadpool(ingest, service.STATE_PATH, store.identity, [order], "woocommerce", webhook=True)
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid WooCommerce order payload") from None
    return {"imported": added}


@router.put("/merchant/woocommerce/{connector}/writeback")
def configure(connector: str, body: Writeback, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, connector, KIND)
        except KeyError:
            raise HTTPException(404, "WooCommerce connection not found") from None
        settings.update_credentials(db, tenant, connector, row["credentials"] | body.model_dump())
        audit(db, tenant, operator.actor, "store_writeback_configured", reference=connector)
    return body


def sync(tenant, payload, *, setup=False):
    connector = payload["connector"]
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, connector, KIND)
        except KeyError:
            return
    store = store_from(row)
    if setup:
        callback = f"{settings.public_base()}/providers/woocommerce/{tenant}/{connector}/orders"
        client = woo.WooCommerceClient(store)
        existing, _ = client.request("webhooks", params={"per_page": 100})
        for topic in TOPICS:
            if not any(hook.get("topic") == topic and hook.get("delivery_url") == callback for hook in existing):
                client.request("webhooks", method="POST", payload={
                    "name": f"COD-Guard {topic}", "topic": topic, "delivery_url": callback,
                    "secret": store.webhook_secret, "status": "active",
                })
    woo.poll_once(service.STATE_PATH, store)


def writeback(tenant, payload):
    order_id, connector, external = (payload[key] for key in ("order_id", "connector", "external_id"))
    if payload["kind"] == "outcome":
        with connect(service.STATE_PATH, tenant_id=tenant) as db:
            row = settings.read(db, tenant, connector, KIND)
        if row["credentials"].get("write_outcomes"):
            woo.write_outcome(service.STATE_PATH, store_from(row), order_id)
        return
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, connector, KIND)
            order, assessment = service._assess_in_transaction(db, tenant, order_id)
        except KeyError:
            return
        if order["queue_status"] != "open" or order["storefront_conflict"] or assessment["outcome"]:
            return
        cfg = row["credentials"]
        hold = not (assessment["decision"] == "SHIP" and assessment["verified"] and not assessment["needs_review"])
        if not cfg.get("hold_on_unverified" if hold else "release_on_confirmed"):
            return
        client = woo.WooCommerceClient(store_from(row))
        route = f"orders/{external}"
        current, _ = client.request(route)
        if woo.parse_order(current).status != "open":
            return
        if hold and current.get("status") in ("processing", "pending"):
            client.request(route, method="PUT", payload={"status": "on-hold",
                           "meta_data": [{"key": "_cod_guard_hold", "value": connector}]})
        if not hold and current.get("status") == "on-hold" and any(
                item.get("key") == "_cod_guard_hold" and item.get("value") == connector
                for item in current.get("meta_data", []) if isinstance(item, dict)):
            client.request(route, method="PUT", payload={"status": "processing",
                           "meta_data": [{"key": "_cod_guard_hold", "value": ""}]})
