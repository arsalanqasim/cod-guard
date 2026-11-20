"""Operator consent and submission with public, signed Meta callbacks."""

import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, StrictBool
from starlette.concurrency import run_in_threadpool

import service
import whatsapp_cloud as cloud
from operators import Operator, require_operator, write_operator
from records import connect


router = APIRouter(prefix="/integrations/whatsapp")


class Consent(BaseModel):
    opted_in: StrictBool
    evidence_reference: str = Field(min_length=3, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _account(tenant_id):
    try:
        return cloud.accounts().get(tenant_id)
    except cloud.CloudError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _order(operator, order_id):
    try:
        return service.get_order(order_id, operator.tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Order not found") from None


@router.get("/status")
def status(operator: Operator = Depends(require_operator)):
    return {"mode": "cloud" if _account(operator.tenant_id) else "simulated", **cloud.stats(operator.tenant_id)}


@router.get("/orders/{order_id}")
def verification(order_id: str, operator: Operator = Depends(require_operator)):
    _order(operator, order_id)
    with connect(service.STATE_PATH) as db:
        result = db.execute("""SELECT started_at, status, billable, category, estimated_usd_micros, replied_at
            FROM whatsapp_verifications WHERE tenant_id=? AND order_id=?""", (operator.tenant_id, order_id)).fetchone()
    return {"verification": dict(result) if result else None}


@router.post("/orders/{order_id}/consent")
def consent(order_id: str, body: Consent, operator: Operator = Depends(write_operator)):
    order = _order(operator, order_id)
    account = _account(operator.tenant_id)
    if account is None:
        raise HTTPException(status_code=409, detail="WhatsApp is simulated for this tenant")
    try:
        cloud.record_consent(account, order, body.opted_in, body.evidence_reference, operator.actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"opted_in": body.opted_in}


@router.post("/orders/{order_id}/send")
def send(order_id: str, operator: Operator = Depends(write_operator)):
    order = _order(operator, order_id)
    if order["data_source"].casefold() == "daraz":
        raise HTTPException(status_code=409, detail="Daraz is score-and-queue only")
    try:
        account = _account(operator.tenant_id)
        preview = service.prepare_verification(order_id, actor=operator.actor, tenant_id=operator.tenant_id)
        result = cloud.send_verification(account, order, operator.actor)
        if preview is not None:
            result["shadow"] = preview
            if account is None:
                result["preview"] = preview["preview"]
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except cloud.CloudError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/{tenant_id}/webhook")
def challenge(tenant_id: str, request: Request):
    account = _account(tenant_id)
    token = request.query_params.get("hub.verify_token", "")
    challenge_value = request.query_params.get("hub.challenge", "")
    if (not account or request.query_params.get("hub.mode") != "subscribe" or not token.isascii()
            or not hmac.compare_digest(account.verify_token, token) or not challenge_value.isascii()
            or not challenge_value.isdigit() or len(challenge_value) > 128):
        raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")
    return PlainTextResponse(challenge_value)


@router.post("/{tenant_id}/webhook")
async def callback(tenant_id: str, request: Request):
    account = _account(tenant_id)
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="WhatsApp callback too large")
    if not account or not cloud.signed_callback(account, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp callback signature")
    try:
        payload = json.loads(body)
        await run_in_threadpool(cloud.process_callback, account, payload)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise HTTPException(status_code=422, detail="Invalid WhatsApp callback") from None
    return {"ok": True}
