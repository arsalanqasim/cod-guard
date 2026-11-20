"""WooCommerce webhooks and tenant-authenticated operations."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

import service
import woocommerce as woo
from connector_orders import connection_state, ingest
from operators import Operator, require_operator, write_operator


router = APIRouter(prefix="/integrations/woocommerce")


def _stores():
    try:
        return woo.configured_stores()
    except woo.WooCommerceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _store(account, operator=None):
    store = _stores().get(account)
    if store is None or (operator and operator.tenant_id != store.tenant_id):
        raise HTTPException(status_code=404, detail="WooCommerce store not found")
    return store


@router.get("/connections")
def connections(operator: Operator = Depends(require_operator)):
    return [{"account": store.account, "auth_mode": store.auth_mode,
             **connection_state(service.STATE_PATH, store.identity)}
            for store in _stores().values() if store.tenant_id == operator.tenant_id]


@router.post("/{account}/webhook")
async def webhook(account: str, request: Request):
    store = _store(account)
    body = await request.body()
    if len(body) > woo.MAX_BODY:
        raise HTTPException(status_code=413, detail="WooCommerce payload too large")
    signature = request.headers.get("X-WC-Webhook-Signature")
    if not signature and re.fullmatch(rb"webhook_id=[0-9]{1,20}", body):
        return Response(status_code=200)
    if not woo.signed_webhook(store, body, signature):
        raise HTTPException(status_code=401, detail="Invalid WooCommerce signature")
    if request.headers.get("X-WC-Webhook-Topic") not in ("order.created", "order.updated"):
        raise HTTPException(status_code=422, detail="Expected a WooCommerce order event")
    try:
        parsed = woo.parse_order(json.loads(body))
        count = await run_in_threadpool(ingest, service.STATE_PATH, store.identity,
                                        [parsed], "woocommerce-webhook", webhook=True)
    except (ValueError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid WooCommerce order payload") from None
    return {"imported": count}


@router.post("/{account}/poll")
def poll(account: str, operator: Operator = Depends(write_operator)):
    store = _store(account, operator)
    try:
        return woo.poll_once(service.STATE_PATH, store)
    except woo.WooCommerceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/{account}/orders/{order_id}/write-outcome")
def write_outcome(account: str, order_id: str, operator: Operator = Depends(write_operator)):
    store = _store(account, operator)
    try:
        result = woo.write_outcome(service.STATE_PATH, store, order_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="WooCommerce order not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except woo.WooCommerceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    service.record_access(operator.tenant_id, operator.actor, "woocommerce_outcome_written", order_id=order_id)
    return result
