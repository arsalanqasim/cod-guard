"""Receive Shopify compliance requests and apply tenant-scoped data minimization."""
import base64
import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import merchant_shopify as shopify
import service
from integration_jobs import enqueue
from merchant_auth import _private_lookup
from merchant_integration_routes import owner_read, owner_write, require_platform
from operators import Operator
from pakistan_phone import normalize_phone
from platform_data import decrypt, encrypt
from records import audit, connect, reply_text, seal_order, select_orders, write


router = APIRouter()
DATA_REQUEST = "customers/data_request"
CUSTOMER_REDACT = "customers/redact"
SHOP_REDACT = "shop/redact"
TOPIC_FIELDS = {DATA_REQUEST: "orders_requested", CUSTOMER_REDACT: "orders_to_redact", SHOP_REDACT: None}


def _requested_orders(topic, data):
    if not isinstance(data, dict) or type(data.get("shop_id")) is not int or data["shop_id"] <= 0:
        raise ValueError("Invalid Shopify privacy event")
    field = TOPIC_FIELDS[topic]
    if field is None:
        if set(data) != {"shop_id", "shop_domain"}:
            raise ValueError("Invalid Shopify shop redaction body")
        return []
    if (not isinstance(data.get("customer"), dict) or
            (topic == CUSTOMER_REDACT and "data_request" in data)):
        raise ValueError("Invalid Shopify customer privacy event")
    if topic == DATA_REQUEST and (not isinstance(data.get("data_request"), dict)
                                  or type(data["data_request"].get("id")) is not int):
        raise ValueError("Missing Shopify data request identifier")
    orders = data.get(field)
    if not isinstance(orders, list) or any(type(item) is not int or not 0 < item < 2**64 for item in orders):
        raise ValueError("Invalid Shopify order list")
    return sorted({str(item) for item in orders})


@router.post("/providers/shopify/privacy")
async def webhook(request: Request):
    require_platform()
    _, secret = shopify.app_credentials()
    body = await request.body()
    provided = request.headers.get("X-Shopify-Hmac-Sha256", "")
    expected = base64.b64encode(hmac.digest(secret.encode(), body, "sha256")).decode()
    if not provided.isascii() or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid Shopify privacy signature")
    topic = request.headers.get("X-Shopify-Topic", "")
    if topic not in TOPIC_FIELDS:
        raise HTTPException(422, "Unsupported Shopify privacy topic")
    try:
        document = json.loads(body)
        orders = _requested_orders(topic, document)
        domain = document["shop_domain"]
        if not isinstance(domain, str) or not shopify.DOMAIN.fullmatch(domain):
            raise ValueError("Invalid Shopify shop domain")
        if request.headers.get("X-Shopify-Shop-Domain") != domain:
            raise ValueError("Shopify shop header does not match the signed request")
    except (KeyError, ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Invalid Shopify privacy payload") from None
    event_key = hashlib.sha256(topic.encode() + b"." + body).hexdigest()
    await run_in_threadpool(_record, domain, topic, orders, event_key)
    return {"accepted": True}


def _record(domain, topic, orders, event_key):
    tenant = shopify._tenant(domain)
    if not tenant:
        return
    request_id = uuid4().hex
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        installation = db.execute("""SELECT installation_id FROM merchant_shopify_routes
            WHERE shop=? AND tenant_id=?""", (domain, tenant)).fetchone()
        if installation is None:
            return
        event_key = hashlib.sha256(f"{installation['installation_id']}:{event_key}".encode()).hexdigest()
        row = db.execute("""INSERT INTO shopify_privacy_requests (tenant_id,id,shop,topic,event_key,orders,status)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(tenant_id,event_key) DO NOTHING RETURNING id""",
                         (tenant, request_id, domain, topic, event_key,
                          encrypt(json.dumps(orders), tenant, request_id, "shopify.privacy.orders"),
                          "ready" if topic == DATA_REQUEST else "pending")).fetchone()
        if row and topic != DATA_REQUEST:
            enqueue(db, tenant, "shopify_privacy", event_key, {"request_id": request_id})


def _order_links(db, tenant, shop, orders):
    rows = db.execute("""SELECT external_id,order_id FROM external_orders
        WHERE tenant_id=? AND channel='SHOPIFY' AND account=?""", (tenant, shop)).fetchall()
    return [row for row in rows if orders is None or row["external_id"] in orders]


def _request(db, tenant, request_id):
    row = db.execute("SELECT * FROM shopify_privacy_requests WHERE tenant_id=? AND id=?", (tenant, request_id)).fetchone()
    if row is None:
        raise KeyError(request_id)
    value = dict(row)
    value["orders"] = set(json.loads(decrypt(row["orders"], tenant, request_id, "shopify.privacy.orders"))) if row["orders"] else set()
    return value


@router.get("/merchant/shopify/privacy")
def requests(operator: Operator = Depends(owner_read)):
    tenant = operator.tenant_id
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        return [dict(row) for row in db.execute("""SELECT id,shop,topic,status,created_at,completed_at
            FROM shopify_privacy_requests WHERE tenant_id=? ORDER BY created_at DESC LIMIT 50""", (tenant,))]


@router.get("/merchant/shopify/privacy/{request_id}/export")
def export(request_id: str, operator: Operator = Depends(owner_read)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            request = _request(db, tenant, request_id)
        except KeyError:
            raise HTTPException(404, "Shopify data request not found") from None
        if request["topic"] != DATA_REQUEST:
            raise HTTPException(404, "Shopify data request not found")
        data = []
        for link in _order_links(db, tenant, request["shop"], request["orders"]):
            order, = select_orders(db, tenant, order_id=link["order_id"])
            messages = db.execute("""SELECT text,at,source FROM messages WHERE tenant_id=? AND order_id=?
                AND text IS NOT NULL ORDER BY id""", (tenant, link["order_id"])).fetchall()
            data.append({"external_order_id": link["external_id"],
                         **{key: order[key] for key in ("customer_name", "phone", "city", "utm_source",
                                                        "utm_medium", "utm_campaign", "referring_site")},
                         "replies": [{**row, "text": reply_text(db, tenant, link["order_id"], row["text"])}
                                     for row in messages]})
        audit(db, tenant, operator.actor, "shopify_privacy_export", reference=request_id)
    return JSONResponse({"shop": request["shop"], "orders": data}, headers={
        "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="shopify-customer-data.json"',
    })


@router.post("/merchant/shopify/privacy/{request_id}/complete")
def complete_data_request(request_id: str, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        changed = db.execute("""UPDATE shopify_privacy_requests SET status='done',completed_at=COALESCE(completed_at,now())
            WHERE tenant_id=? AND id=? AND topic=?""", (tenant, request_id, DATA_REQUEST)).rowcount
        if not changed:
            raise HTTPException(404, "Shopify data request not found")
        audit(db, tenant, operator.actor, "shopify_privacy_data_request_completed", reference=request_id)
    return {"status": "done"}


def _remove_contact(db, tenant, order_id):
    order, = select_orders(db, tenant, order_id=order_id)
    if phone := normalize_phone(order["phone"]):
        recipient = _private_lookup("buyer-verification", f"{tenant}:{phone}")
        db.execute("DELETE FROM merchant_contact_consent WHERE tenant_id=? AND recipient=?", (tenant, recipient))
    for table in ("merchant_verification_attempts", "merchant_voice_jobs", "whatsapp_verifications",
                  "network_contributions"):
        db.execute(f"DELETE FROM {table} WHERE tenant_id=? AND order_id=?", (tenant, order_id))


def _redact_customer(db, tenant, shop, orders):
    db.executemany("""INSERT INTO shopify_redacted_orders VALUES (?,?,?)
        ON CONFLICT DO NOTHING""", ((tenant, shop, external_id) for external_id in orders))
    for row in _order_links(db, tenant, shop, orders):
        order_id = row["order_id"]
        _remove_contact(db, tenant, order_id)
        fields = seal_order(db, tenant, order_id, {"customer_name": "Redacted", "phone": "", "city": ""})
        db.execute("""UPDATE orders SET customer_name=?,phone=?,city=?,utm_source=NULL,utm_medium=NULL,
            utm_campaign=NULL,referring_site=NULL WHERE tenant_id=? AND order_id=?""",
                   (fields["customer_name"], fields["phone"], fields["city"], tenant, order_id))
        db.execute("UPDATE messages SET text=NULL WHERE tenant_id=? AND order_id=?", (tenant, order_id))
        db.execute("""INSERT INTO storefront_order_status (tenant_id,channel,account,external_id,status,conflict)
            VALUES (?,'SHOPIFY',?,?,'closed_at_source',0)
            ON CONFLICT(tenant_id,channel,account,external_id) DO UPDATE SET status='closed_at_source',conflict=0""",
                   (tenant, shop, row["external_id"]))


def _erase_shop(db, tenant, shop):
    active = db.execute("""SELECT 1 FROM merchant_connectors WHERE tenant_id=? AND id=? AND kind='shopify' AND active""",
                        (tenant, shop)).fetchone()
    if active:
        # A delayed event must not delete data from a reinstalled app.
        return False
    for row in _order_links(db, tenant, shop, None):
        order_id = row["order_id"]
        _remove_contact(db, tenant, order_id)
        for table in ("courier_outcome_evidence", "merchant_shipments", "risk_shadow_decisions", "outcomes",
                      "decisions", "messages", "model_feedback", "audit_events", "external_orders", "orders"):
            db.execute(f"DELETE FROM {table} WHERE tenant_id=? AND order_id=?", (tenant, order_id))
        db.execute("""DELETE FROM integration_jobs WHERE tenant_id=? AND kind='shopify_writeback'
            AND starts_with(dedupe,?)""", (tenant, order_id + ":"))
    for table in ("storefront_order_status", "connector_state"):
        db.execute(f"DELETE FROM {table} WHERE tenant_id=? AND channel='SHOPIFY' AND account=?", (tenant, shop))
    db.execute("DELETE FROM shopify_redacted_orders WHERE tenant_id=? AND shop=?", (tenant, shop))
    db.execute("DELETE FROM merchant_connectors WHERE tenant_id=? AND id=? AND kind='shopify'", (tenant, shop))
    db.execute("DELETE FROM merchant_shopify_routes WHERE tenant_id=? AND shop=?", (tenant, shop))
    return True


def process(tenant, payload):
    request_id = payload["request_id"]
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            event = _request(db, tenant, request_id)
        except KeyError:
            return
        if event["status"] != "pending":
            return
        topic, shop = event["topic"], event["shop"]
        if topic == CUSTOMER_REDACT:
            _redact_customer(db, tenant, shop, event["orders"])
            success = True
        elif topic == SHOP_REDACT:
            success = _erase_shop(db, tenant, shop)
        else:
            return
        status = "done" if success else "review"
        db.execute("""UPDATE shopify_privacy_requests SET status=?,completed_at=now(),orders=NULL
            WHERE tenant_id=? AND id=?""", (status, tenant, request_id))
        if success and topic == SHOP_REDACT:
            db.execute("""UPDATE shopify_privacy_requests SET orders=NULL
                WHERE tenant_id=? AND shop=?""", (tenant, shop))
        audit(db, tenant, "shopify-privacy", "shopify_redaction_" + status, reference=request_id)
