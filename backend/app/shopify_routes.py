"""Signed, merchant-specific Shopify order intake and reconciliation."""

import base64
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

import service
from address_quality import classify_address
from connector_orders import CANCELLED, CLOSED, NON_COD, OPEN, StorefrontSnapshot, connection_state, ingest, source_timestamp
from operators import Operator, require_operator
from records import DEMO_TENANT
from risk_engine import validate_features


router = APIRouter(prefix="/integrations/shopify")
ORDER_TOPICS = {"orders/create", "orders/updated", "orders/cancelled", "orders/paid"}


@dataclass(frozen=True)
class Shop:
    shop: str
    tenant_id: str
    secret: str = field(repr=False)
    cod_gateway: str
    allow_protected_fields: bool = False

    @property
    def identity(self):
        return (self.tenant_id, "SHOPIFY", self.shop)


@lru_cache(maxsize=1)
def _shops(raw):
    configs = json.loads(raw)
    if not isinstance(configs, dict):
        raise ValueError("Expected a shop mapping")
    shops = {}
    secrets = set()
    for domain, data in configs.items():
        shop = Shop(domain, **data)
        if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}\.myshopify\.com", domain)
                or shop.tenant_id == DEMO_TENANT or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", shop.tenant_id)
                or not isinstance(shop.secret, str) or len(shop.secret) < 24 or shop.secret in secrets
                or not isinstance(shop.cod_gateway, str) or not shop.cod_gateway.strip()
                or type(shop.allow_protected_fields) is not bool):
            raise ValueError("Invalid Shopify configuration")
        secrets.add(shop.secret)
        shops[domain] = shop
    return shops


def configured_shops():
    try:
        return _shops(os.environ.get("COD_GUARD_SHOPIFY", "{}"))
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, "Shopify configuration is unavailable") from None


def _text(value):
    return value.strip()[:200] if isinstance(value, str) else ""


def parse_order(shop, payload, topic):
    if not isinstance(payload, dict):
        raise ValueError("Expected Shopify order payload")
    if payload.get("test") is True:
        return None
    external_id = payload.get("id")
    if type(external_id) is not int or not 0 < external_id < 2**64:
        raise ValueError("Invalid Shopify order ID")
    updated_at = source_timestamp(payload.get("updated_at") or payload.get("cancelled_at"))
    if payload.get("cancelled_at") is not None:
        return StorefrontSnapshot(str(external_id), CANCELLED, updated_at)
    if topic == "orders/cancelled":
        raise ValueError("Missing signed Shopify cancellation status")
    if topic == "orders/paid":
        if payload.get("financial_status") != "paid":
            raise ValueError("Missing signed Shopify payment status")
        return StorefrontSnapshot(str(external_id), NON_COD, updated_at)
    gateways = payload.get("payment_gateway_names")
    if (not isinstance(gateways, list) or not isinstance(payload.get("currency"), str)
            or not isinstance(payload.get("financial_status"), str) or payload.get("test") is not False):
        raise ValueError("Missing Shopify lifecycle fields")
    if (len(gateways) != 1 or _text(gateways[0]).casefold() != shop.cod_gateway.strip().casefold()
            or payload["currency"] != "PKR" or payload["financial_status"] != "pending"):
        return StorefrontSnapshot(str(external_id), NON_COD, updated_at)
    if payload.get("fulfillment_status") is not None or payload.get("closed_at") is not None:
        return StorefrontSnapshot(str(external_id), CLOSED, updated_at)
    shipping = (payload.get("shipping_address") or {}) if shop.allow_protected_fields else {}
    items = payload.get("line_items") or []
    if not isinstance(shipping, dict) or not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid Shopify order fields")
    phone = _text(shipping.get("phone") or (payload.get("phone") if shop.allow_protected_fields else None))
    if not re.fullmatch(r"\+?[0-9][0-9 ()-]{2,39}", phone):
        phone = ""
    address = " ".join(_text(shipping.get(key)) for key in ("address1", "address2"))
    flags = {}
    if payload.get("total_price") not in (None, ""):
        flags["amount_pkr"] = payload["total_price"]
    if address.strip():
        flags["address_words"] = len(address.split())
    amounts = [item.get("quantity") for item in items]
    if amounts and all(type(amount) is int and 0 < amount <= 100_000 for amount in amounts):
        flags["items_count"] = sum(amounts)
    city = _text(shipping.get("city"))[:100]
    return StorefrontSnapshot(str(external_id), OPEN, updated_at, {
        "customer_name": _text(shipping.get("name")) or "Name unavailable",
        "product": ", ".join(filter(None, (_text(item.get("title")) for item in items)))[:200] or "Items unavailable",
        "city": city, "phone": phone, **validate_features(flags),
        "address_issues": classify_address(address, city) if address.strip() else None,
    })


@router.get("/status")
def status(operator: Operator = Depends(require_operator)):
    return {name: {"last_webhook": connection_state(service.STATE_PATH, shop.identity)["last_webhook"],
                   "protected_fields_enabled": shop.allow_protected_fields}
            for name, shop in configured_shops().items() if shop.tenant_id == operator.tenant_id}


@router.post("/webhooks/{domain}")
async def webhook(domain: str, request: Request):
    shop = configured_shops().get(domain)
    body = await request.body()
    signature = request.headers.get("X-Shopify-Hmac-Sha256", "")
    if (not shop or request.headers.get("X-Shopify-Shop-Domain") != domain or not signature.isascii()
            or not hmac.compare_digest(base64.b64encode(hmac.digest(shop.secret.encode(), body, "sha256")).decode(), signature)):
        raise HTTPException(401, "Invalid Shopify webhook authentication")
    topic = request.headers.get("X-Shopify-Topic")
    if topic not in ORDER_TOPICS:
        raise HTTPException(422, "Unsupported Shopify webhook topic")
    try:
        order = parse_order(shop, json.loads(body), topic)
        inserted = await run_in_threadpool(ingest, service.STATE_PATH, shop.identity,
                                           [order] if order else [], "shopify-webhook", webhook=True)
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Invalid Shopify order payload") from None
    return {"queued": inserted}
