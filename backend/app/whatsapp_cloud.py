"""Opt-in WhatsApp Cloud verification with durable delivery accounting."""

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from time import time
from uuid import uuid4

import httpx

import service
from pakistan_phone import normalize_phone
from platform_data import database_url
from records import DEMO_TENANT, audit, connect, now, select_orders, write
from storage import update_state
from verification import opening_message, parse_reply


TEMPLATE_BODY = "Please confirm or cancel cash-on-delivery order {{1}}. To stop WhatsApp order messages, reply STOP."
BUTTONS = {"CONFIRM": "Confirm", "DENY": "Cancel"}
STOP = frozenset({"stop", "unsubscribe", "opt out", "opt-out", "band karo", "بند کریں", "پیغامات بند کریں"})
REPLY_TTL = 24 * 60 * 60
SEND_LOCK = Lock()
STATUS_RANK = {"submitting": 0, "unconfirmed": 0, "accepted": 1, "sent": 2, "failed": 3,
               "delivered": 4, "read": 5}
PAKISTAN_UTILITY_MICROS = 15_000


class CloudError(RuntimeError):
    pass


@dataclass(frozen=True)
class Account:
    tenant_id: str
    waba_id: str
    phone_number_id: str
    template_id: str
    token: str = field(repr=False)
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)
    signing_key: str = field(repr=False)
    api_version: str = "v27.0"
    business_verified: bool = False


@lru_cache(maxsize=1)
def _accounts(raw):
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Invalid WhatsApp configuration")
    accounts = {}
    phones = set()
    for tenant_id, values in payload.items():
        account = Account(tenant_id=tenant_id, **values)
        if (tenant_id == DEMO_TENANT or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tenant_id)
                or not all(re.fullmatch(r"[0-9]{1,32}", value)
                           for value in (account.waba_id, account.phone_number_id, account.template_id))
                or not re.fullmatch(r"v[0-9]{2}\.0", account.api_version)
                or not all(isinstance(value, str) and len(value) >= 16 and value.isascii()
                           for value in (account.token, account.app_secret, account.verify_token))
                or not isinstance(account.signing_key, str) or len(account.signing_key) < 32
                or type(account.business_verified) is not bool or account.phone_number_id in phones):
            raise ValueError("Invalid WhatsApp configuration")
        phones.add(account.phone_number_id)
        if account.business_verified:
            accounts[tenant_id] = account
    return accounts


def accounts():
    if database_url():
        return {}
    try:
        return _accounts(os.environ.get("COD_GUARD_WHATSAPP", "{}"))
    except (TypeError, ValueError, KeyError):
        raise CloudError("WhatsApp configuration is invalid") from None


def _digest(account, purpose, value):
    return hmac.new(account.signing_key.encode(), f"{purpose}:{account.tenant_id}:{value}".encode(),
                    hashlib.sha256).hexdigest()


def _recipient(account, phone):
    return _digest(account, "recipient", phone)


def advice_contacts(db, tenant, orders):
    try:
        account = accounts().get(tenant)
    except CloudError:
        return {}
    if account is None:
        return {}
    recipients = {order["order_id"]: _recipient(account, phone) for order in orders
                  if (phone := normalize_phone(order["phone"]))}
    if not recipients:
        return {}
    recipient_keys = tuple(set(recipients.values()))
    slots = ", ".join("?" for _ in recipient_keys)
    consent = {row["recipient"]: bool(row["opted_in"]) for row in db.execute(f"""SELECT recipient, opted_in
        FROM whatsapp_consent WHERE tenant_id=? AND recipient IN ({slots})""", (tenant, *recipient_keys))}
    result = {order_id: {"opted_in": consent.get(recipient)} for order_id, recipient in recipients.items()}
    slots = ", ".join("?" for _ in recipients)
    attempts = db.execute(f"""SELECT order_id, recipient, status, started_at, expires FROM whatsapp_verifications
        WHERE tenant_id=? AND order_id IN ({slots}) AND replied_at IS NULL""", (tenant, *recipients))
    for attempt in attempts:
        order_id = attempt["order_id"]
        if attempt["recipient"] == recipients[order_id]:
            result[order_id].update(status=attempt["status"], started_at=attempt["started_at"], expires=attempt["expires"])
    return result


def _button(account, attempt, action):
    raw = f"{attempt}.{action}"
    return f"{raw}.{_digest(account, 'button', raw)}"


def _consent(connection, account, recipient, enabled, source, actor):
    connection.execute("""INSERT INTO whatsapp_consent VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET
        opted_in=excluded.opted_in, source=excluded.source, changed_at=excluded.changed_at""",
                       (account.tenant_id, recipient, int(enabled), source, now()))
    if not enabled:
        connection.execute("""UPDATE whatsapp_verifications SET expires=MIN(expires, ?)
            WHERE tenant_id=? AND recipient=? AND replied_at IS NULL""",
                           (int(time()), account.tenant_id, recipient))
    audit(connection, account.tenant_id, actor, "whatsapp_opt_in" if enabled else "whatsapp_opt_out")


def _eligible_phone(order):
    if order["data_source"].casefold() in ("synthetic", "daraz"):
        raise ValueError("This order source does not support WhatsApp verification")
    if not (phone := normalize_phone(order["phone"])):
        raise ValueError("A valid Pakistan mobile number is required")
    return phone


def record_consent(account, order, enabled, source, actor):
    recipient = _recipient(account, _eligible_phone(order))
    with SEND_LOCK, write(service.STATE_PATH) as connection:
        _consent(connection, account, recipient, enabled, source, actor)


class CloudTransport:
    def __init__(self, account):
        self.account = account

    def request(self, method, node, *, params=None, payload=None):
        url = f"https://graph.facebook.com/{self.account.api_version}/{node}"
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.request(method, url, headers={"Authorization": f"Bearer {self.account.token}"},
                                          params=params, json=payload)
            return response.raise_for_status().json()
        except (httpx.HTTPError, ValueError):
            raise CloudError("Meta Cloud API did not complete the request; check account and delivery status") from None

    def verify_template(self):
        template = self.request("GET", self.account.template_id,
                                params={"fields": "name,status,category,language,components"})
        if not isinstance(template, dict) or (template.get("status"), template.get("category"),
                                              template.get("language")) != ("APPROVED", "UTILITY", "en_US"):
            raise CloudError("Meta template must be approved as en_US UTILITY")
        expected = [{"type": "QUICK_REPLY", "text": label} for label in BUTTONS.values()]
        actual = template.get("components")
        if not isinstance(actual, list) or len(actual) != 2 or not all(isinstance(item, dict) for item in actual):
            raise CloudError("Meta template differs from the approved COD-Guard copy")
        parts = {component.get("type"): component for component in actual}
        if (parts.get("BODY", {}).get("text") != TEMPLATE_BODY
                or parts.get("BUTTONS", {}).get("buttons") != expected
                or not re.fullmatch(r"[a-z0-9_]{1,128}", str(template.get("name", "")))):
            raise CloudError("Meta template differs from the approved COD-Guard copy")
        return template["name"]

    def send(self, order_id, phone, template, attempt):
        components = [{"type": "body", "parameters": [{"type": "text", "text": order_id}]}]
        for index, action in enumerate(BUTTONS):
            components.append({"type": "button", "sub_type": "quick_reply", "index": str(index),
                               "parameters": [{"type": "payload", "payload": _button(self.account, attempt, action)}]})
        response = self.request("POST", f"{self.account.phone_number_id}/messages", payload={
            "messaging_product": "whatsapp", "to": phone, "type": "template", "biz_opaque_callback_data": attempt,
            "template": {"name": template, "language": {"code": "en_US"}, "components": components},
        })
        try:
            message_id = response["messages"][0]["id"]
            if not isinstance(message_id, str) or not message_id or len(message_id) > 256:
                raise ValueError
            return message_id
        except (KeyError, IndexError, TypeError, ValueError):
            raise CloudError("Meta did not return a WhatsApp message ID; do not resend blindly") from None


def send_verification(account, order, actor):
    if account is None or not account.business_verified:
        return {"mode": "simulated", "preview": opening_message(order), "sent": False}
    phone = _eligible_phone(order)
    recipient = _recipient(account, phone)
    order_id = order["order_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", order_id):
        raise ValueError("Order ID is not valid for the confirmation template")
    if not SEND_LOCK.acquire(blocking=False):
        raise ValueError("WhatsApp is busy; retry after the active send or consent change completes")
    try:
        with connect(service.STATE_PATH) as db:
            existing = db.execute("SELECT status FROM whatsapp_verifications WHERE tenant_id=? AND order_id=?",
                                  (account.tenant_id, order_id)).fetchone()
            if existing:
                return {"mode": "cloud", "status": existing["status"], "already_submitted": True}
            consent = db.execute("SELECT opted_in FROM whatsapp_consent WHERE tenant_id=? AND recipient=?",
                                 (account.tenant_id, recipient)).fetchone()
        if not consent or not consent["opted_in"]:
            raise ValueError("The buyer has not opted into WhatsApp order messages")
        transport = CloudTransport(account)
        template = transport.verify_template()
        attempt = uuid4().hex
        with write(service.STATE_PATH) as db:
            reservation = db.execute("""INSERT OR IGNORE INTO whatsapp_verifications
                (tenant_id, order_id, attempt_id, recipient, started_at, expires, status)
                VALUES (?, ?, ?, ?, ?, ?, 'submitting')""",
                                     (account.tenant_id, order_id, attempt, recipient, now(), int(time()) + REPLY_TTL))
            if not reservation.rowcount:
                return {"mode": "cloud", "already_submitted": True}
            audit(db, account.tenant_id, actor, "whatsapp_submission_reserved", order_id=order_id)
        try:
            message_id = transport.send(order_id, phone, template, attempt)
        except CloudError:
            with write(service.STATE_PATH) as db:
                db.execute("UPDATE whatsapp_verifications SET status='unconfirmed' WHERE attempt_id=? AND status='submitting'",
                           (attempt,))
            raise
        with write(service.STATE_PATH) as db:
            db.execute("""UPDATE whatsapp_verifications SET message_id=COALESCE(message_id, ?),
                status=CASE WHEN status='submitting' THEN 'accepted' ELSE status END WHERE attempt_id=?""",
                       (message_id, attempt))
        return {"mode": "cloud", "status": "accepted", "sent": True}
    finally:
        SEND_LOCK.release()


def signed_callback(account, body, header):
    expected = "sha256=" + hmac.digest(account.app_secret.encode(), body, "sha256").hex()
    return isinstance(header, str) and header.isascii() and hmac.compare_digest(expected, header)


def _pricing(status):
    pricing = status.get("pricing") or {}
    if not isinstance(pricing, dict) or not isinstance(pricing.get("category"), str):
        return None, None, None
    category = pricing["category"].lower()
    pricing_type = pricing.get("type")
    billable = pricing.get("billable")
    if pricing_type == "regular":
        billable = True
    elif pricing_type in ("free_customer_service", "free_entry_point"):
        billable = False
    elif pricing_type is not None:
        return None, category, None
    if type(billable) is not bool:
        return None, category, None
    if not billable:
        return 0, category, 0
    try:
        delivered = datetime.fromtimestamp(int(status["timestamp"]), timezone.utc).date().isoformat()
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        delivered = ""
    rate = PAKISTAN_UTILITY_MICROS if category == "utility" and "2026-10-01" <= delivered < "2027-01-01" else None
    return 1, category, rate


def _record_delivery(db, account, event):
    state, message_id = event.get("status"), event.get("id")
    if state not in ("sent", "failed", "delivered", "read") or not isinstance(message_id, str) or not 0 < len(message_id) <= 256:
        return
    if not (phone := normalize_phone(event.get("recipient_id"))):
        return
    attempt = db.execute("""SELECT * FROM whatsapp_verifications WHERE tenant_id=? AND recipient=? AND
        (message_id=? OR (message_id IS NULL AND attempt_id=?))""",
                         (account.tenant_id, _recipient(account, phone), message_id,
                          str(event.get("biz_opaque_callback_data", "")))).fetchone()
    if not attempt:
        return
    next_state = state if STATUS_RANK[state] > STATUS_RANK[attempt["status"]] else attempt["status"]
    billable, category, cost = _pricing(event) if state in ("delivered", "read") else (None, None, None)
    if attempt["billable"] is not None:
        billable, category, cost = attempt["billable"], attempt["category"], attempt["estimated_usd_micros"]
    db.execute("""UPDATE whatsapp_verifications SET status=?, message_id=COALESCE(message_id, ?),
        billable=?, category=?, estimated_usd_micros=? WHERE attempt_id=?""",
               (next_state, message_id, billable, category, cost, attempt["attempt_id"]))


def _receive_reply(db, account, message):
    if not (phone := normalize_phone(message.get("from"))):
        return
    recipient = _recipient(account, phone)
    text = (message.get("text") or {}).get("body") if message.get("type") == "text" else None
    if isinstance(text, str) and text.strip().casefold().rstrip(".!؟") in STOP:
        _consent(db, account, recipient, False, "buyer_stop", "whatsapp-webhook")
        return
    context = (message.get("context") or {}).get("id")
    if not isinstance(context, str) or not context:
        return
    attempt = db.execute("""SELECT attempt.* FROM whatsapp_verifications AS attempt
        JOIN whatsapp_consent AS consent USING (tenant_id, recipient)
        WHERE attempt.tenant_id=? AND attempt.recipient=? AND attempt.message_id=?
        AND attempt.replied_at IS NULL AND attempt.expires>? AND consent.opted_in=1""",
                         (account.tenant_id, recipient, context, int(time()))).fetchone()
    if not attempt:
        return
    if message.get("type") == "button":
        payload = (message.get("button") or {}).get("payload")
        if not isinstance(payload, str) or not payload.isascii():
            return
        intent = next((action for action in BUTTONS if hmac.compare_digest(payload, _button(
            account, attempt["attempt_id"], action))), None)
        if intent is None:
            return
        text = BUTTONS[intent]
    elif isinstance(text, str) and 0 < len(text.strip()) <= 2000:
        intent = parse_reply(text)
    else:
        return
    order_id = attempt["order_id"]
    order, = select_orders(db, account.tenant_id, order_id=order_id)
    if normalize_phone(order["phone"]) != phone or order["data_source"].casefold() == "daraz":
        return
    if intent == "UNCLEAR":
        reply_id = message.get("id")
        if not isinstance(reply_id, str) or not 0 < len(reply_id) <= 256:
            return
        receipt = db.execute("""INSERT INTO whatsapp_unclear_receipts VALUES (?, ?)
            ON CONFLICT DO NOTHING""",
                             (attempt["attempt_id"], _digest(account, "unclear-reply", reply_id)))
        if not receipt.rowcount:
            return
    with update_state(db, account.tenant_id, (order_id,)) as state:
        source = "whatsapp_button" if message.get("type") == "button" else "whatsapp"
        service.apply_verification(state, order, text, intent, source, "whatsapp-webhook")
    if intent != "UNCLEAR":
        db.execute("UPDATE whatsapp_verifications SET replied_at=? WHERE attempt_id=?",
                   (now(), attempt["attempt_id"]))
        db.execute("DELETE FROM whatsapp_unclear_receipts WHERE attempt_id=?", (attempt["attempt_id"],))


def process_callback(account, payload):
    if payload.get("object") != "whatsapp_business_account":
        return
    with SEND_LOCK, write(service.STATE_PATH) as db:
        for entry in payload.get("entry", []):
            if entry.get("id") != account.waba_id:
                continue
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages" or value.get("metadata", {}).get("phone_number_id") != account.phone_number_id:
                    continue
                for event in value.get("statuses", []):
                    _record_delivery(db, account, event)
                for message in value.get("messages", []):
                    _receive_reply(db, account, message)


def stats(tenant_id):
    with connect(service.STATE_PATH) as db:
        totals = db.execute("""SELECT COUNT(*) AS attempts,
            COUNT(CASE WHEN status IN ('delivered', 'read') THEN 1 END) AS delivered,
            COUNT(CASE WHEN billable=1 THEN 1 END) AS billable_deliveries,
            COUNT(CASE WHEN status IN ('delivered', 'read') AND estimated_usd_micros IS NULL THEN 1 END) AS unpriced,
            SUM(estimated_usd_micros) AS estimated_usd_micros FROM whatsapp_verifications WHERE tenant_id=?""",
                            (tenant_id,)).fetchone()
    return {**dict(totals), "cost_basis": "Meta delivery signals × list rates; not an invoice"}
