"""Tenant-scoped terminal shipment evidence; no booking or personal details sent."""

import csv
import io
import json
import os
import re
from datetime import datetime
from decimal import Decimal

import httpx

import service
from records import DEMO_TENANT, audit, now, select_orders, write
from storage import update_state


REQUIRED_FIELDS = {"order_id", "courier", "tracking_number", "outcome"}
SUPPORTED_COURIERS = {"postex", "leopards", "tcs", "trax", "other"}
TCS_URL = "https://ociconnect.tcscourier.com/tracking/api/Tracking/GetDynamicTrackDetail"
TCS_TERMINAL = {"delivered": "delivered"}


class OutcomeConflict(ValueError):
    pass


class CourierUnavailable(RuntimeError):
    pass


def parse_csv(contents):
    reader = csv.DictReader(io.StringIO(contents.decode("utf-8-sig"), newline=""), strict=True)
    fields = reader.fieldnames or []
    if set(fields) not in (REQUIRED_FIELDS, REQUIRED_FIELDS | {"billed_fee_pkr"}) or len(fields) != len(set(fields)):
        raise ValueError("Use the four required courier columns and optional billed_fee_pkr")
    orders = set()
    rows = []
    for row in reader:
        if len(rows) >= 500:
            raise ValueError("Courier CSV is limited to 500 records")
        if None in row or None in row.values():
            raise ValueError("Courier CSV row does not match the header")
        order_id, courier, tracking, outcome = (row[field].strip() for field in
                                               ("order_id", "courier", "tracking_number", "outcome"))
        courier, outcome = courier.lower(), outcome.lower()
        fee = row.get("billed_fee_pkr", "").strip()
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", order_id) or order_id in orders
                or courier not in SUPPORTED_COURIERS or outcome not in service.OUTCOMES
                or not re.fullmatch(r"[A-Za-z0-9-]{3,48}", tracking)
                or (fee and not re.fullmatch(r"[0-9]{1,7}(\.[0-9]{1,2})?", fee))):
            raise ValueError(f"Invalid courier record at CSV line {reader.line_num}")
        orders.add(order_id)
        rows.append((order_id, courier, tracking.upper(), outcome, int(Decimal(fee) * 100) if fee else None))
    if not rows:
        raise ValueError("Courier CSV has no records")
    return rows


def store(tenant_id, actor, rows, source):
    if tenant_id == DEMO_TENANT:
        raise ValueError("Courier evidence requires a separate shadow tenant")
    order_ids = [row[0] for row in rows]
    labels = evidence = 0
    with write(service.STATE_PATH) as db, update_state(db, tenant_id, order_ids) as state:
        for order_id, courier, tracking, outcome, fee in rows:
            orders = select_orders(db, tenant_id, order_id=order_id)
            if not orders or orders[0]["data_source"].casefold() == "synthetic":
                raise KeyError("Courier order not found")
            if state["outcomes"].get(order_id) not in (None, outcome):
                raise OutcomeConflict("A different outcome already exists; use the audited order correction")
            previous = db.execute("SELECT * FROM courier_outcome_evidence WHERE tenant_id=? AND order_id=?",
                                  (tenant_id, order_id)).fetchone()
            linked = db.execute("""SELECT order_id FROM courier_outcome_evidence WHERE tenant_id=?
                AND courier=? AND tracking_number=?""", (tenant_id, courier, tracking)).fetchone()
            if ((linked and linked["order_id"] != order_id) or (previous and
                    (previous["courier"], previous["tracking_number"]) != (courier, tracking))):
                raise OutcomeConflict("Tracking reference is already linked to another shipment")
            if order_id not in state["outcomes"]:
                service.apply_outcome(state, orders[0], outcome, actor)
                labels += 1
            if previous and previous["outcome"] == outcome and (fee is None or previous["billed_fee_paisa"] == fee):
                continue
            db.execute("""INSERT INTO courier_outcome_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, order_id) DO UPDATE SET outcome=excluded.outcome, source=excluded.source,
                recorded_at=excluded.recorded_at, billed_fee_paisa=excluded.billed_fee_paisa""",
                       (tenant_id, order_id, courier, tracking, outcome, source, now(), fee))
            audit(db, tenant_id, actor, "courier_evidence", order_id=order_id, reference=source)
            evidence += 1
    return {"labels_added": labels, "evidence_updated": evidence, "rows": len(rows)}


def tcs_status(tracking, token):
    try:
        response = httpx.request("GET", TCS_URL, headers={"Authorization": f"Bearer {token}"},
                                 json={"consignee": [tracking]}, timeout=12, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        if payload.get("message") == "FAIL" and payload.get("shipmentsummary") == "No Data Found/Invalid CN":
            return None
        events = payload["deliveryinfo"]
        if not isinstance(events, list):
            raise ValueError("Invalid tracking history")
        matching = []
        for event in events:
            if event.get("consignmentno") != tracking:
                continue
            date = datetime.strptime(event["datetime"], "%A %b %d, %Y %H:%M")
            matching.append((date, " ".join(event["status"].lower().split())))
        if not matching:
            return None
        latest = max(date for date, _ in matching)
        statuses = {status for date, status in matching if date == latest}
        return TCS_TERMINAL.get(next(iter(statuses))) if len(statuses) == 1 else None
    except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError):
        raise CourierUnavailable("TCS tracking is unavailable") from None


def tcs_token(tenant_id):
    try:
        accounts = json.loads(os.environ.get("COD_GUARD_TCS", "{}"))
        token = accounts.get(tenant_id)
        if token and isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9._~+/=-]{16,4096}", token):
            return token
    except (ValueError, AttributeError):
        pass
    raise CourierUnavailable("TCS tracking is not configured for this tenant")
