"""Shopify OAuth, App Bridge pairing, webhook setup, and scoped fulfillment holds."""
import base64
import hashlib
import hmac
import html
import json
import os
import re
from pathlib import Path
from secrets import token_urlsafe
from time import time
from typing import Annotated
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import merchant_connectors as settings
import service
from connector_orders import ingest
from integration_jobs import PermanentFailure, enqueue
from merchant_integration_routes import owner_write, require_platform
from operators import Operator
from platform_data import connection
from records import audit, connect, write
from shopify_routes import ORDER_TOPICS, Shop, parse_order


router = APIRouter()
DOMAIN = re.compile(r"[a-z0-9][a-z0-9-]{0,61}\.myshopify\.com")
STATE = re.compile(r"([A-Za-z0-9_-]{1,64})\.([a-f0-9]{32})\.([A-Za-z0-9_-]{43})")
SCOPES = "read_orders,write_merchant_managed_fulfillment_orders,write_third_party_fulfillment_orders"
API_VERSION = "2026-10"
TOPICS = ("ORDERS_CREATE", "ORDERS_UPDATED", "ORDERS_CANCELLED", "ORDERS_PAID", "APP_UNINSTALLED")
HOLD_HANDLE = "cod-guard"


def app_credentials():
    key, secret = (os.environ.get(name, "") for name in
                   ("COD_GUARD_SHOPIFY_CLIENT_ID", "COD_GUARD_SHOPIFY_CLIENT_SECRET"))
    if not key or len(secret) < 24:
        raise HTTPException(503, "Shopify app credentials are unavailable")
    return key, secret


class Install(BaseModel):
    shop: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,61}\.myshopify\.com$")
    cod_gateway: str = Field(default="Cash on Delivery (COD)", min_length=1, max_length=100)
    protected_fields: bool = False


class HoldSettings(BaseModel):
    enforce: bool


class EmbeddedLink(BaseModel):
    code: str = Field(min_length=70, max_length=145)


def _public_base():
    try:
        return settings.public_base()
    except ValueError:
        raise HTTPException(503, "The public API base URL is unavailable") from None


@router.post("/merchant/shopify/authorize")
def authorize(body: Install, operator: Operator = Depends(owner_write)):
    key, _ = app_credentials()
    base = _public_base()
    proof = token_urlsafe(32)
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        pending = settings.create(db, tenant, "shopify_install", body.shop, body.shop, {
            "proof": proof, "expires": int(time()) + 900, "actor": operator.actor,
            "cod_gateway": body.cod_gateway.strip(), "protected_fields": body.protected_fields,
        }, active=False)
    state = f"{tenant}.{pending}.{proof}"
    params = urlencode({"client_id": key, "scope": SCOPES, "state": state,
                        "redirect_uri": f"{base}/providers/shopify/oauth"})
    return {"authorize_url": f"https://{body.shop}/admin/oauth/authorize?{params}", "installation_code": state}


def _oauth_params(request, secret):
    pairs = list(request.query_params.multi_items())
    values = dict(pairs)
    signature = values.pop("hmac", "")
    if (len(values) + 1 != len(pairs) or not re.fullmatch(r"[a-f0-9]{64}", signature)
            or not hmac.compare_digest(signature, hmac.new(secret.encode(), urlencode(sorted(values.items())).encode(),
                                                          hashlib.sha256).hexdigest())):
        raise HTTPException(401, "Invalid Shopify authorization signature")
    try:
        recent = abs(time() - int(values.get("timestamp", ""))) <= 300
    except ValueError:
        recent = False
    if not recent or not DOMAIN.fullmatch(values.get("shop", "")) or not values.get("code"):
        raise HTTPException(400, "Shopify authorization is invalid or expired")
    return values


def _token(shop, fields):
    key, secret = app_credentials()
    try:
        response = httpx.post(f"https://{shop}/admin/oauth/access_token",
                              data={"client_id": key, "client_secret": secret, **fields},
                              timeout=10, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        return {"access_token": data["access_token"], "refresh_token": data["refresh_token"],
                "expires_at": int(time()) + int(data["expires_in"])}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise RuntimeError("Shopify token exchange failed") from None


def _install(shop, state, fields, *, shop_subject=None):
    match = STATE.fullmatch(state)
    if not match:
        raise HTTPException(401, "Shopify installation code is invalid")
    tenant, pending, proof = match.groups()
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            pending_row = settings.read(db, tenant, pending, "shopify_install", active=False)
        except KeyError:
            raise HTTPException(401, "Shopify installation code has expired or been used") from None
        config = pending_row["credentials"]
        current_owner = db.execute("""SELECT 1 FROM merchant_memberships WHERE tenant_id=? AND user_id=?
            AND role='owner'""", (tenant, config["actor"])).fetchone()
        if (not current_owner or config["expires"] < time() or pending_row["address"] != shop
                or not hmac.compare_digest(proof, config["proof"])):
            raise HTTPException(401, "Shopify installation code does not match the store")
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 1))", (shop,))
        bound = db.execute("SELECT tenant_id FROM merchant_shopify_routes WHERE shop=?", (shop,)).fetchone()
        if bound and bound["tenant_id"] != tenant:
            raise HTTPException(409, "This Shopify store is already connected")
        try:
            credentials = _token(shop, fields)
        except RuntimeError:
            raise HTTPException(502, "Shopify could not issue installation tokens") from None
        try:
            current = settings.read(db, tenant, shop, "shopify")
        except KeyError:
            current = None
        stored = {
            **(current["credentials"] if current else {}),
            **credentials, "cod_gateway": config["cod_gateway"], "protected_fields": config["protected_fields"],
        }
        stored.setdefault("callback_token", token_urlsafe(32))
        if shop_subject:
            stored["shop_subject"] = shop_subject
        if bound:
            db.execute("DELETE FROM merchant_connectors WHERE tenant_id=? AND id=?", (tenant, shop))
        else:
            db.execute("INSERT INTO merchant_shopify_routes (shop,tenant_id) VALUES (?,?)", (shop, tenant))
        settings.create(db, tenant, "shopify", shop, shop, stored, connector_id=shop)
        db.execute("DELETE FROM merchant_connectors WHERE tenant_id=? AND id=?", (tenant, pending))
        enqueue(db, tenant, "shopify_setup", f"{shop}:{pending}", {"connector": shop})
        audit(db, tenant, config["actor"], "shopify_authorized", reference=shop)


@router.get("/providers/shopify/oauth")
def finish(request: Request):
    require_platform()
    _, secret = app_credentials()
    values = _oauth_params(request, secret)
    _install(values["shop"], values.get("state", ""), {"code": values["code"], "expiring": 1})
    return RedirectResponse(settings.portal_home(), status_code=303)


def _session_token(header):
    key, secret = app_credentials()
    try:
        token = header.removeprefix("Bearer ")
        header64, claims64, signature64 = token.split(".")
        def decode(value):
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        jose, claims = json.loads(decode(header64)), json.loads(decode(claims64))
        signature = base64.urlsafe_b64encode(hmac.digest(secret.encode(), f"{header64}.{claims64}".encode(),
                                                        "sha256")).decode().rstrip("=")
        dest = urlsplit(claims["dest"])
        shop = dest.netloc
        if (not header.startswith("Bearer ") or not re.fullmatch(r"[A-Za-z0-9_-]+", signature64)
                or not hmac.compare_digest(signature, signature64) or jose.get("alg") != "HS256"
                or dest.scheme != "https" or dest.path not in ("", "/")
                or dest.query or dest.fragment or not DOMAIN.fullmatch(shop)
                or claims["iss"] != f"https://{shop}/admin" or claims["aud"] != key
                or not isinstance(claims["sub"], str) or not claims["sub"]
                or not int(claims["nbf"]) <= time() < int(claims["exp"])):
            raise ValueError("Invalid session token")
    except (TypeError, ValueError, KeyError, AttributeError):
        raise HTTPException(401, "Shopify session is invalid", headers={
            "X-Shopify-Retry-Invalid-Session-Request": "1",
        }) from None
    return shop, claims["sub"], token


@router.post("/providers/shopify/embedded/link")
def link(body: EmbeddedLink, authorization: Annotated[str, Header()] = ""):
    require_platform()
    shop, subject, token = _session_token(authorization)
    _install(shop, body.code, {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                               "subject_token": token, "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                               "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
                               "expiring": 1}, shop_subject=subject)
    return {"status": "connected"}


def _tenant(shop):
    with connection() as db:
        row = db.execute("SELECT tenant_id FROM merchant_shopify_routes WHERE shop=%s", (shop,)).fetchone()
    return row["tenant_id"] if row else None


@router.get("/providers/shopify/embedded/orders")
def embedded_orders(authorization: Annotated[str, Header()] = ""):
    require_platform()
    shop, subject, _ = _session_token(authorization)
    tenant = _tenant(shop)
    if not tenant:
        raise HTTPException(403, "Pair this Shopify store from the merchant portal")
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, shop, "shopify")
        except KeyError:
            raise HTTPException(403, "Shopify is disconnected") from None
        if row["credentials"].get("shop_subject") != subject:
            raise HTTPException(403, "Pair this Shopify user from the merchant portal")
        orders = db.execute("""SELECT o.order_id,e.external_id,o.product,
            COALESCE(s.status,'open') AS queue_status,COALESCE(s.conflict,0) AS storefront_conflict
            FROM external_orders e JOIN orders o USING(tenant_id,order_id)
            LEFT JOIN storefront_order_status s USING(tenant_id,channel,account,external_id)
            WHERE e.tenant_id=? AND e.channel='SHOPIFY' AND e.account=?
            ORDER BY storefront_conflict DESC, o.order_id LIMIT 50""", (tenant, shop)).fetchall()
    return [{**entry, "decision": service.assess_order(service.get_order(entry["order_id"], tenant),
                                                      tenant_id=tenant)["decision"]} for entry in orders]


@router.get("/shopify/app")
def frame(shop: str):
    require_platform()
    if not DOMAIN.fullmatch(shop):
        raise HTTPException(400, "Invalid Shopify shop")
    key, _ = app_credentials()
    dist = Path(os.environ.get("COD_GUARD_PORTAL_DIST", str(Path(__file__).resolve().parents[2] / "frontend/portal/dist")))
    try:
        page = (dist / "index.html").read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(503, "Build the merchant portal before opening Shopify App Home") from None
    bootstrap = (
        f'<meta name="shopify-api-key" content="{html.escape(key, quote=True)}">'
        '<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>'
        '<script src="https://cdn.shopify.com/shopifycloud/polaris.js"></script>'
    )
    return HTMLResponse(page.replace("<head>", "<head>" + bootstrap, 1), headers={
        "Content-Security-Policy": f"frame-ancestors https://{shop} https://admin.shopify.com",
        "Cache-Control": "no-store",
    })


@router.put("/merchant/shopify/{shop}/holds")
def configure(shop: str, body: HoldSettings, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, shop, "shopify")
        except KeyError:
            raise HTTPException(404, "Shopify installation not found") from None
        settings.update_credentials(db, tenant, shop, row["credentials"] | {"enforce": body.enforce})
        audit(db, tenant, operator.actor, "shopify_holds_configured", reference=shop)
    return body


@router.post("/providers/shopify/webhooks/{shop}/{callback_token}")
async def webhook(shop: str, callback_token: str, request: Request):
    require_platform()
    _, secret = app_credentials()
    raw = await request.body()
    signature = request.headers.get("X-Shopify-Hmac-Sha256", "")
    expected = base64.b64encode(hmac.digest(secret.encode(), raw, "sha256")).decode()
    if (not DOMAIN.fullmatch(shop) or request.headers.get("X-Shopify-Shop-Domain") != shop
            or not signature.isascii() or not hmac.compare_digest(signature, expected)):
        raise HTTPException(401, "Invalid Shopify webhook signature")
    topic = request.headers.get("X-Shopify-Topic", "")
    if topic not in ORDER_TOPICS | {"app/uninstalled"}:
        raise HTTPException(422, "Unsupported Shopify webhook topic")
    def handle():
        tenant = _tenant(shop)
        if not tenant:
            return 0
        with connect(service.STATE_PATH, tenant_id=tenant) as db:
            try:
                row = settings.read(db, tenant, shop, "shopify")
            except KeyError:
                return 0
        cfg = row["credentials"]
        if not callback_token.isascii() or not hmac.compare_digest(cfg["callback_token"], callback_token):
            raise HTTPException(401, "Invalid Shopify callback destination")
        if topic == "app/uninstalled":
            with write(service.STATE_PATH, tenant_id=tenant) as db:
                db.execute("UPDATE merchant_connectors SET active=false WHERE tenant_id=? AND id=?", (tenant, shop))
                settings.update_credentials(db, tenant, shop, {})
            return 0
        snapshot = parse_order(Shop(shop, tenant, secret, cfg["cod_gateway"], cfg["protected_fields"]),
                               json.loads(raw), topic)
        return ingest(service.STATE_PATH, (tenant, "SHOPIFY", shop), [snapshot] if snapshot else [],
                      "shopify", webhook=True)
    try:
        return {"imported": await run_in_threadpool(handle)}
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Invalid Shopify order event") from None


def _graphql(row, query, variables):
    cfg = row["credentials"]
    shop = row["address"]
    reply = httpx.post(f"https://{shop}/admin/api/{API_VERSION}/graphql.json",
                       headers={"X-Shopify-Access-Token": cfg["access_token"]},
                       json={"query": query, "variables": variables}, timeout=10, follow_redirects=False)
    reply.raise_for_status()
    document = reply.json()
    if document.get("errors") or not isinstance(document.get("data"), dict):
        raise RuntimeError("Shopify GraphQL request failed")
    return document["data"]


def _refresh(tenant, shop):
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, shop, "shopify")
        except KeyError:
            return False
        cfg = row["credentials"]
        if cfg["expires_at"] <= time() + 60:
            cfg.update(_token(shop, {"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"]}))
            # Commit the rotated refresh token before any further provider operations.
            settings.update_credentials(db, tenant, shop, cfg)
    return True


def setup(tenant, payload):
    shop = payload["connector"]
    if not _refresh(tenant, shop):
        return
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, shop, "shopify")
        except KeyError:
            return
        callback = f"{settings.public_base()}/providers/shopify/webhooks/{shop}/{row['credentials']['callback_token']}"
        current = _graphql(row, """query($uri: String!) {
            webhookSubscriptions(first:50, uri:$uri) { nodes { topic uri } }
        }""", {"uri": callback})["webhookSubscriptions"]["nodes"]
        topics = {item["topic"] for item in current if item["uri"] == callback}
        for topic in sorted(set(TOPICS) - topics):
            result = _graphql(row, """mutation($topic: WebhookSubscriptionTopic!, $uri: String!) {
                webhookSubscriptionCreate(topic:$topic,webhookSubscription:{uri:$uri,format:JSON}) {
                    userErrors { message } webhookSubscription { id }
                }
            }""", {"topic": topic, "uri": callback})["webhookSubscriptionCreate"]
            if result["userErrors"]:
                raise PermanentFailure("Shopify could not register order webhooks. Check app scopes.")


def writeback(tenant, payload):
    if payload["kind"] == "outcome":
        return
    order_id, shop, external = (payload[key] for key in ("order_id", "connector", "external_id"))
    if not _refresh(tenant, shop):
        return
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            row = settings.read(db, tenant, shop, "shopify")
            order, assessment = service._assess_in_transaction(db, tenant, order_id)
        except KeyError:
            return
        if (not row["credentials"].get("enforce") or order["queue_status"] != "open"
                or order["storefront_conflict"] or assessment["outcome"]):
            return
        release = assessment["decision"] == "SHIP" and assessment["verified"] and not assessment["needs_review"]
        cursor = None
        while True:
            remote = _graphql(row, """query($id:ID!, $after:String) {
                order(id:$id) { cancelledAt closedAt displayFinancialStatus
                  fulfillmentOrders(first:50, after:$after) {
                    pageInfo { hasNextPage endCursor }
                    nodes { id status supportedActions { action } fulfillmentHolds { id handle heldByRequestingApp } }
                  }
                }
            }""", {"id": f"gid://shopify/Order/{external}", "after": cursor})["order"]
            if (not remote or remote["cancelledAt"] or remote["closedAt"]
                    or remote["displayFinancialStatus"] != "PENDING"):
                return
            page = remote["fulfillmentOrders"]
            if not page["nodes"] and cursor is None:
                raise RuntimeError("Waiting for Shopify fulfillment routing")
            for fulfillment in page["nodes"]:
                _set_hold(row, fulfillment, release)
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]


def _set_hold(row, fulfillment, release):
    own = [hold["id"] for hold in fulfillment["fulfillmentHolds"]
           if hold["heldByRequestingApp"] and hold["handle"] == HOLD_HANDLE]
    actions = {item["action"] for item in fulfillment["supportedActions"]}
    values = {"id": fulfillment["id"]}
    if release and own and "RELEASE_HOLD" in actions:
        mutation, query = "fulfillmentOrderReleaseHold", """mutation($id:ID!,$holds:[ID!]) {
            fulfillmentOrderReleaseHold(id:$id,holdIds:$holds) { userErrors { message } }
        }"""
        values["holds"] = own
    elif not release and not own and "HOLD" in actions:
        mutation, query = "fulfillmentOrderHold", """mutation($id:ID!,$hold:FulfillmentOrderHoldInput!) {
            fulfillmentOrderHold(id:$id,fulfillmentHold:$hold) { userErrors { message } }
        }"""
        values["hold"] = {"handle": HOLD_HANDLE, "reason": "OTHER", "reasonNotes": "Awaiting COD verification"}
    else:
        return
    if _graphql(row, query, values)[mutation]["userErrors"]:
        raise RuntimeError("Shopify did not accept the fulfillment update")
