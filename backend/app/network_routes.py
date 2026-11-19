"""Seller consent and advisory reputation; no arbitrary phone lookup."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool

import reputation_network as network
import service
from operators import Operator, write_operator


router = APIRouter(prefix="/network")


class OptIn(BaseModel):
    enabled: StrictBool


class Consent(OptIn):
    evidence_reference: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{2,95}$")


def _order(operator, order_id):
    try:
        return service.get_order(order_id, operator.tenant_id)
    except KeyError:
        raise HTTPException(404, "Order not found") from None


@router.get("/size")
def size():
    return network.size(service.STATE_PATH)


@router.put("/enrollment")
def enroll(body: OptIn, operator: Operator = Depends(write_operator)):
    try:
        network.seller_enrollment(service.STATE_PATH, operator.tenant_id, operator.actor, body.enabled)
    except network.NetworkUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    return {"enrolled": body.enabled}


@router.put("/orders/{order_id}/consent")
def consent(order_id: str, body: Consent, operator: Operator = Depends(write_operator)):
    order = _order(operator, order_id)
    try:
        network.buyer_consent(service.STATE_PATH, operator.tenant_id, operator.actor, order,
                              body.enabled, body.evidence_reference)
    except network.NetworkUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
    return {"consent_recorded": body.enabled}


@router.get("/orders/{order_id}/counts")
def counts(order_id: str, operator: Operator = Depends(write_operator)):
    order = _order(operator, order_id)
    try:
        result = network.counts(service.STATE_PATH, operator.tenant_id, order)
    except network.NetworkUnavailable:
        result = None
    return {"counts": result, "advisory_only": True}
