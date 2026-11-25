"""Owner integration management and a scoped machine-to-machine intake API."""
import hashlib
import json
import re
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

import merchant_connectors
import public_https
import service
from address_quality import classify_address
from connector_orders import _store_orders
from merchant_auth import limit_operator
from merchant_events import queue_order_event
from operators import Operator, require_operator, write_operator
from platform_data import database_url
from records import audit, connect, now, write
from risk_engine import validate_features


router = APIRouter()
machine_bearer = HTTPBearer(auto_error=False)
_KEY = re.compile(r"cgk_([A-Za-z0-9_-]{1,64})\.([A-Za-z0-9_-]{43})")


def require_platform():
    if not database_url():
        raise HTTPException(404, "Merchant integrations are unavailable")


def owner_read(operator: Operator = Depends(require_operator)):
    require_platform()
    if operator.role != "owner":
        raise HTTPException(403, "Only a store owner can manage integrations")
    return operator


def owner_write(operator: Operator = Depends(write_operator)):
    return owner_read(operator)


def machine(scope):
    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(machine_bearer)):
        require_platform()
        token = credentials.credentials if credentials else ""
        if match := _KEY.fullmatch(token):
            tenant = match[1]
            digest = hashlib.sha256(token.encode()).digest()
            with connect(service.STATE_PATH, tenant_id=tenant) as db:
                key = db.execute("""SELECT id FROM merchant_api_keys WHERE tenant_id=? AND digest=?
                    AND scope=? AND revoked_at IS NULL""", (tenant, digest, scope)).fetchone()
            if key:
                principal = Operator("key-" + key["id"], tenant, "machine")
                limit_operator(principal)
                return principal
        raise HTTPException(401, "A scoped integration key is required", headers={"WWW-Authenticate": "Bearer"})
    return authenticate


class KeySetup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    scope: Literal["orders:write", "courier:write"] = "orders:write"


class WebhookSetup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=500)


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    order_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    customer_name: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    phone: str = Field(pattern=r"^\+?[0-9][0-9 ()-]{2,39}$")
    city: str = Field(default="", max_length=100)
    address: str = Field(default="", max_length=500)
    amount_pkr: float | None = None
    items_count: int | None = None
    order_hour: int | None = None
    phone_valid: bool | None = None
    address_has_landmark: bool | None = None
    is_repeat_customer: bool | None = None


@router.get("/merchant/connections")
def connections(operator: Operator = Depends(owner_read)):
    with connect(service.STATE_PATH, tenant_id=operator.tenant_id) as db:
        return merchant_connectors.listing(db, operator.tenant_id)


@router.get("/merchant/api-keys")
def keys(operator: Operator = Depends(owner_read)):
    with connect(service.STATE_PATH, tenant_id=operator.tenant_id) as db:
        return [dict(row) for row in db.execute("""SELECT id,name,scope,created_at,revoked_at
            FROM merchant_api_keys WHERE tenant_id=? ORDER BY created_at DESC""", (operator.tenant_id,))]


@router.post("/merchant/api-keys", status_code=201)
def create_key(body: KeySetup, response: Response, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    token = f"cgk_{tenant}.{token_urlsafe(32)}"
    key_id = uuid4().hex
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        db.execute("""INSERT INTO merchant_api_keys (tenant_id,id,digest,name,scope) VALUES (?,?,?,?,?)""",
                   (tenant, key_id, hashlib.sha256(token.encode()).digest(), body.name.strip(), body.scope))
        audit(db, tenant, operator.actor, "api_key_created", reference=key_id)
    response.headers["Cache-Control"] = "no-store"
    return {"id": key_id, "key": token, "scope": body.scope}


@router.delete("/merchant/api-keys/{key_id}", status_code=204)
def revoke(key_id: str, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        revoked = db.execute("""UPDATE merchant_api_keys SET revoked_at=now() WHERE tenant_id=? AND id=?
            AND revoked_at IS NULL""", (tenant, key_id)).rowcount
        if not revoked:
            raise HTTPException(404, "Active API key not found")
        audit(db, tenant, operator.actor, "api_key_revoked", reference=key_id)


@router.post("/merchant/webhooks", status_code=201)
def create_webhook(body: WebhookSetup, response: Response, operator: Operator = Depends(owner_write)):
    try:
        destination = public_https.endpoint(body.url)
        public_https.verify_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    secret = token_urlsafe(32)
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        connector = merchant_connectors.create(db, tenant, "erp_webhook", body.name, destination.netloc, {
            "secret": secret, "url": body.url,
        })
        audit(db, tenant, operator.actor, "webhook_created", reference=connector)
    response.headers["Cache-Control"] = "no-store"
    return {"id": connector, "signing_secret": secret}


@router.delete("/merchant/webhooks/{connector}", status_code=204)
def disable_webhook(connector: str, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        disabled = db.execute("""UPDATE merchant_connectors SET active=false
            WHERE tenant_id=? AND id=? AND kind='erp_webhook' AND active""", (tenant, connector)).rowcount
        if not disabled:
            raise HTTPException(404, "Active webhook not found")
        audit(db, tenant, operator.actor, "webhook_disabled", reference=connector)


@router.get("/merchant/webhook-deliveries")
def deliveries(operator: Operator = Depends(owner_read)):
    with connect(service.STATE_PATH, tenant_id=operator.tenant_id) as db:
        return [dict(row) for row in db.execute("""SELECT id,status,attempts,error,created_at,finished_at
            FROM integration_jobs WHERE tenant_id=? AND kind='erp_webhook' ORDER BY created_at DESC LIMIT 50""",
                                               (operator.tenant_id,))]


@router.post("/v1/orders", status_code=201)
def intake(body: OrderInput, response: Response,
           key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[!-~]+$")],
           operator: Operator = Depends(machine("orders:write"))):
    tenant = operator.tenant_id
    fields = body.model_dump(exclude_none=True)
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    external = fields.pop("order_id")
    address = fields.pop("address")
    try:
        validated = validate_features({name: int(value) if type(value) is bool else value
                                       for name, value in fields.items()
                                       if name not in ("customer_name", "product", "phone", "city")})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        replay = db.execute("SELECT digest,receipt FROM merchant_order_receipts WHERE tenant_id=? AND key=?",
                            (tenant, key)).fetchone()
        if replay:
            if replay["digest"] != digest:
                raise HTTPException(409, "Idempotency key already used for a different order")
            response.status_code = 200
            return json.loads(replay["receipt"])
        details = {name: fields[name] for name in ("customer_name", "product", "phone", "city")}
        details.update(validated, address_issues=classify_address(address, body.city))
        identity = (tenant, "ERP", "merchant")
        if not _store_orders(db, identity, [(external, details)], operator.actor):
            raise HTTPException(409, "This external order ID already exists")
        link = db.execute("""SELECT order_id FROM external_orders WHERE tenant_id=? AND channel=?
            AND account=? AND external_id=?""", (*identity, external)).fetchone()
        order_id = link["order_id"]
        _, assessment = service._assess_in_transaction(db, tenant, order_id)
        receipt = {"order_id": order_id, "external_order_id": external, "revision": 0,
                   **{name: assessment[name] for name in ("decision", "zone", "needs_review", "verified")}}
        db.execute("INSERT INTO merchant_order_receipts VALUES (?,?,?,?)", (tenant, key, digest, json.dumps(receipt)))
        queue_order_event(db, tenant, order_id, "order.accepted", {
            "decision": receipt["decision"], "revision": 0, "at": now(), "verified": False,
        })
    return receipt
