"""Opt-in seller intake with transient drafts and explicit confirmed writes."""

import re
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictBool

import service
from address_quality import classify_address
from connector_orders import ingest
from operators import Operator, write_operator
from order_intake import IdempotencyConflict, MAX_CSV_BYTES, import_orders
from records import DEMO_TENANT
from risk_engine import validate_features
from pakistan_phone import normalize_phone


router = APIRouter(prefix="/integrations/social")
LABELS = {"name": "name", "customer name": "name", "naam": "name", "نام": "name", "phone": "phone",
          "mobile": "phone", "فون": "phone", "address": "address", "pata": "address", "پتہ": "address",
          "city": "city", "shehar": "city", "شہر": "city", "items": "items", "product": "items",
          "amount": "amount_pkr", "total": "amount_pkr", "رقم": "amount_pkr"}
Channel = Literal["instagram", "facebook", "whatsapp"]


class Preview(BaseModel):
    channel: Channel
    transcript: str = Field(min_length=1, max_length=6000)


class ConfirmedOrder(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    channel: Channel
    confirmation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    confirmed: StrictBool
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=40)
    address: str = Field(min_length=1, max_length=500)
    city: str = Field(default="", max_length=100)
    items: str = Field(min_length=1, max_length=200)
    amount_pkr: Decimal = Field(gt=0, le=10000000, decimal_places=2, allow_inf_nan=False)
    utm_source: str = Field(default="", max_length=200)
    utm_medium: str = Field(default="", max_length=200)
    utm_campaign: str = Field(default="", max_length=200)
    referring_site: str = Field(default="", max_length=500)


def _require_shadow(operator):
    if operator.tenant_id == DEMO_TENANT:
        raise HTTPException(403, "Social intake requires a separate shadow tenant")


def extract(transcript):
    candidates = {field: set() for field in LABELS.values()}
    for line in transcript.splitlines():
        label, colon, value = line.strip().partition(":")
        key = LABELS.get(label.strip().casefold())
        value = value.strip()
        if colon and key and value:
            candidates[key].add(value)
    draft = {key: next(iter(values)) if len(values) == 1 else "" for key, values in candidates.items()}
    draft["phone"] = normalize_phone(draft["phone"]) or ""
    matched = re.fullmatch(r"(?:PKR\s*|Rs\.?\s*)?([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(\.[0-9]{1,2})?",
                           draft["amount_pkr"], re.IGNORECASE)
    draft["amount_pkr"] = matched[1].replace(",", "") + (matched[2] or "") if matched else ""
    for key, limit in {"name": 200, "city": 100, "items": 200, "address": 500, "amount_pkr": 11}.items():
        if len(draft[key]) > limit:
            draft[key] = ""
    return draft


@router.post("/dm/preview")
def preview(body: Preview, operator: Operator = Depends(write_operator)):
    _require_shadow(operator)
    return {"draft": extract(body.transcript), "saved": False}


@router.post("/dm/confirm", status_code=201)
def confirm(body: ConfirmedOrder, operator: Operator = Depends(write_operator)):
    _require_shadow(operator)
    if not body.confirmed:
        raise HTTPException(422, "Review and confirm the draft before saving")
    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(422, "Enter a valid Pakistan mobile number")
    features = validate_features({"address_words": len(body.address.split()), "amount_pkr": float(body.amount_pkr)})
    source = f"DM_{body.channel.upper()}"
    order = {"customer_name": body.name, "phone": phone, "city": body.city, "product": body.items,
             "address_issues": classify_address(body.address, body.city),
             "utm_source": body.utm_source or None, "utm_medium": body.utm_medium or None,
             "utm_campaign": body.utm_campaign or None, "referring_site": body.referring_site or None,
             **features}
    queued = ingest(service.STATE_PATH, (operator.tenant_id, source, "seller-confirmed"),
                    [(body.confirmation_id, order)], operator.actor)
    return {"queued": queued}


@router.post("/sheets/import", status_code=201)
def import_sheet(file: UploadFile = File(...),
                 idempotency_key: str = Header(min_length=1, max_length=128, pattern=r"^[!-~]+$"),
                 operator: Operator = Depends(write_operator)):
    _require_shadow(operator)
    contents = file.file.read(MAX_CSV_BYTES + 1)
    if not (file.filename or "").lower().endswith(".csv") or not contents or len(contents) > MAX_CSV_BYTES:
        raise HTTPException(422, "Upload a nonempty Google Sheets CSV export up to 1 MiB")
    try:
        return import_orders(service.STATE_PATH, operator.tenant_id, operator.actor, f"sheets:{idempotency_key}",
                             contents, source="GOOGLE_SHEETS")
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
