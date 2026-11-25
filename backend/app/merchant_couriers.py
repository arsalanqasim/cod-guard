"""Bound consignment events, TCS polling, and seller-scoped training inputs."""
import csv
import io
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr, StrictBool

import courier_outcomes
import merchant_connectors as settings
import service
from integration_jobs import PermanentFailure, enqueue
from merchant_auth import _private_lookup
from merchant_integration_routes import machine, owner_read, owner_write, require_platform
from operators import Operator, require_operator, write_operator
from pakistan_phone import normalize_phone
from platform_data import decrypt
from records import audit, connect, open_order, write


router = APIRouter()
Courier = Literal["tcs", "postex", "leopards", "trax", "other"]


class Shipment(BaseModel):
    courier: Courier
    tracking: str = Field(pattern=r"^[A-Za-z0-9-]{3,48}$")
    order_day: date | None = None


class TerminalEvent(BaseModel):
    courier: Courier
    tracking: str = Field(pattern=r"^[A-Za-z0-9-]{3,48}$")
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{3,128}$")
    outcome: Literal["delivered", "returned", "refused"]


class TCSSettings(BaseModel):
    token: SecretStr = Field(min_length=16, max_length=4096)


class RefusalEvidence(BaseModel):
    confirmed: StrictBool
    reference: str = Field(pattern=r"^[A-Za-z0-9_.:-]{3,96}$")


@router.put("/merchant/couriers/tcs")
def tcs_setup(body: TCSSettings, operator: Operator = Depends(owner_write)):
    tenant = operator.tenant_id
    cfg = {"token": body.token.get_secret_value()}
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            settings.read(db, tenant, "tcs", "tcs")
        except KeyError:
            settings.create(db, tenant, "tcs", "TCS tracking", "", cfg, connector_id="tcs")
        else:
            settings.update_credentials(db, tenant, "tcs", cfg)
        audit(db, tenant, operator.actor, "courier_configured", reference="tcs")
    return {"status": "configured"}


@router.get("/merchant/orders/{order_id}/shipment")
def shipment(order_id: str, operator: Operator = Depends(require_operator)):
    require_platform()
    tenant = operator.tenant_id
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        row = db.execute("""SELECT courier,tracking,order_day,terminal,evidence_reference,last_poll
            FROM merchant_shipments WHERE tenant_id=? AND order_id=?""", (tenant, order_id)).fetchone()
    return {"shipment": dict(row) if row else None}


@router.put("/merchant/orders/{order_id}/shipment")
def link(order_id: str, body: Shipment, operator: Operator = Depends(write_operator)):
    require_platform()
    if body.order_day and body.order_day > date.today():
        raise HTTPException(422, "Order date cannot be in the future")
    tenant, tracking = operator.tenant_id, body.tracking.upper()
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            order, assessed = service._assess_in_transaction(db, tenant, order_id)
        except KeyError:
            raise HTTPException(404, "Order not found") from None
        if order["data_source"].casefold() == "synthetic":
            raise HTTPException(409, "Synthetic orders cannot be linked to a courier")
        other = db.execute("""SELECT order_id FROM merchant_shipments
            WHERE tenant_id=? AND courier=? AND tracking=?""", (tenant, body.courier, tracking)).fetchone()
        existing = db.execute("""SELECT courier,tracking,terminal FROM merchant_shipments
            WHERE tenant_id=? AND order_id=?""", (tenant, order_id)).fetchone()
        if ((other and other["order_id"] != order_id)
                or (existing and (existing["courier"], existing["tracking"]) != (body.courier, tracking))):
            raise HTTPException(409, "This order or tracking number already has a shipment link")
        old_evidence = db.execute("""SELECT courier,tracking_number FROM courier_outcome_evidence
            WHERE tenant_id=? AND order_id=?""", (tenant, order_id)).fetchone()
        if old_evidence and (old_evidence["courier"], old_evidence["tracking_number"]) != (body.courier, tracking):
            raise HTTPException(409, "Tracking number does not match the recorded courier outcome")
        db.execute("""INSERT INTO merchant_shipments (tenant_id,order_id,courier,tracking,order_day,terminal)
            VALUES (?,?,?,?,?,?) ON CONFLICT(tenant_id,order_id)
            DO UPDATE SET order_day=COALESCE(merchant_shipments.order_day,excluded.order_day)""",
                   (tenant, order_id, body.courier, tracking, body.order_day, assessed["outcome"]))
        audit(db, tenant, operator.actor, "shipment_linked", order_id=order_id, reference=body.courier)
    return {"courier": body.courier, "tracking": tracking}


@router.post("/v1/courier-events", status_code=202)
def intake(body: TerminalEvent, operator: Operator = Depends(machine("courier:write"))):
    tenant = operator.tenant_id
    tracking = body.tracking.upper()
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        shipment = db.execute("""SELECT order_id FROM merchant_shipments WHERE tenant_id=? AND courier=? AND tracking=?""",
                              (tenant, body.courier, tracking)).fetchone()
        if not shipment:
            raise HTTPException(404, "Tracking number is not linked to a merchant order")
        dedupe = f"{body.courier}:{body.event_id}"
        existing = db.execute("""SELECT id,payload FROM integration_jobs WHERE tenant_id=?
            AND kind='courier_terminal' AND dedupe=?""", (tenant, dedupe)).fetchone()
        data = {"order_id": shipment["order_id"], "courier": body.courier,
                "tracking": tracking, "outcome": body.outcome}
        if existing:
            if json.loads(decrypt(existing["payload"], tenant, existing["id"], "integration.payload")) != data:
                raise HTTPException(409, "Courier event ID already used for a different event")
            return {"status": "accepted", "job_id": existing["id"]}
        job = enqueue(db, tenant, "courier_terminal", dedupe, data)
    return {"status": "accepted", "job_id": job}


def apply_terminal(tenant, payload):
    order, courier, tracking, outcome = (payload[k] for k in ("order_id", "courier", "tracking", "outcome"))
    try:
        courier_outcomes.store(tenant, "courier-integration", [(order, courier, tracking, outcome, None)],
                               f"{courier}_live")
    except courier_outcomes.OutcomeConflict:
        raise PermanentFailure("Conflicting terminal outcome requires staff review") from None
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        db.execute("""UPDATE merchant_shipments SET terminal=?,last_poll=now()
            WHERE tenant_id=? AND order_id=? AND courier=? AND tracking=?""",
                   (outcome, tenant, order, courier, tracking))


def poll_tcs(tenant, payload):
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            token = settings.read(db, tenant, "tcs", "tcs")["credentials"]["token"]
        except KeyError:
            return
        row = db.execute("""SELECT order_id,courier,tracking FROM merchant_shipments
            WHERE tenant_id=? AND order_id=? AND courier='tcs' AND terminal IS NULL""",
                         (tenant, payload["order_id"])).fetchone()
    if row is None:
        return
    outcome = courier_outcomes.tcs_status(row["tracking"], token)
    if outcome == "delivered":
        apply_terminal(tenant, dict(row) | {"outcome": outcome})
    else:
        with write(service.STATE_PATH, tenant_id=tenant) as db:
            db.execute("UPDATE merchant_shipments SET last_poll=now() WHERE tenant_id=? AND order_id=?",
                       (tenant, row["order_id"]))


@router.put("/merchant/orders/{order_id}/refusal-evidence")
def corroborate(order_id: str, body: RefusalEvidence, operator: Operator = Depends(write_operator)):
    require_platform()
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        current = db.execute("""SELECT outcome FROM outcomes WHERE tenant_id=? AND order_id=?
            ORDER BY revision DESC LIMIT 1""", (tenant, order_id)).fetchone()
        changed = db.execute("""UPDATE merchant_shipments SET evidence_reference=? WHERE tenant_id=? AND order_id=?""",
                             (body.reference if body.confirmed else None, tenant, order_id)).rowcount
        if not current or current["outcome"] != "refused" or not changed:
            raise HTTPException(409, "A linked shipment with a refusal outcome is required")
        audit(db, tenant, operator.actor, "refusal_corroborated" if body.confirmed else "refusal_evidence_revoked",
              order_id=order_id, reference=body.reference)
    return {"confirmed": body.confirmed}


def seller_dataset(tenant):
    """Produce the documented seller-trainer schema from eligible shipment outcomes."""
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        rows = db.execute("""SELECT o.tenant_id,o.order_id,o.amount_pkr,o.items_count,o.phone,
            s.order_day,s.evidence_reference, outcome.outcome
            FROM merchant_shipments s JOIN orders o USING(tenant_id,order_id)
            JOIN LATERAL (SELECT r.outcome FROM outcomes r WHERE r.tenant_id=s.tenant_id
                          AND r.order_id=s.order_id ORDER BY revision DESC LIMIT 1) AS outcome ON true
            JOIN courier_outcome_evidence e ON e.tenant_id=s.tenant_id AND e.order_id=s.order_id
                AND e.courier=s.courier AND e.tracking_number=s.tracking AND e.outcome=outcome.outcome
            WHERE s.tenant_id=? AND s.order_day IS NOT NULL AND o.amount_pkr IS NOT NULL AND o.items_count>0
              AND (outcome.outcome='delivered' OR (outcome.outcome='refused' AND s.evidence_reference IS NOT NULL))
            ORDER BY s.order_day,o.order_id""", (tenant,))
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(("order_id", "customer_id", "order_day", "amount_pkr", "items_count", "label_failed"))
        count = 0
        for row in rows:
            phone = normalize_phone(open_order(db, row)["phone"])
            if phone:
                writer.writerow((row["order_id"], _private_lookup("training-buyer", f"{tenant}:{phone}").hex(),
                                 row["order_day"], row["amount_pkr"], row["items_count"], int(row["outcome"] == "refused")))
                count += 1
    return buffer.getvalue(), count


@router.get("/merchant/learning/dataset")
def training_dataset(operator: Operator = Depends(owner_read)):
    data, count = seller_dataset(operator.tenant_id)
    with write(service.STATE_PATH, tenant_id=operator.tenant_id) as db:
        audit(db, operator.tenant_id, operator.actor, "seller_dataset_export", reference=str(count))
    return Response(data, media_type="text/csv", headers={
        "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="cod-guard-seller-outcomes.csv"',
    })
