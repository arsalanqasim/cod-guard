"""Consent-bound outbound WhatsApp and Urdu keypad verification."""
import base64
import hmac
import json
import os
import re
from secrets import token_urlsafe
from uuid import uuid4
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field, SecretStr, StrictBool
from starlette.concurrency import run_in_threadpool

import merchant_connectors as settings
import public_https
import service
import whatsapp_cloud as cloud
from integration_jobs import PermanentFailure, enqueue
from merchant_auth import _private_lookup
from merchant_integration_routes import owner_write, require_platform
from operators import Operator, require_operator, write_operator
from pakistan_phone import normalize_phone
from records import audit, connect, write
from storage import update_state
from verification import VOICE_LIMIT_BYTES, parse_reply, transcribe_voice_note


router = APIRouter()
WA, CALLS = "whatsapp", "calls"
ACTIONABLE = ("submitting", "accepted", "unconfirmed", "waiting_review")


def enabled():
    return os.environ.get("COD_GUARD_LIVE_BUYER_CONTACT") == "1"


class WhatsAppSetup(BaseModel):
    waba_id: str = Field(pattern=r"^[0-9]{1,32}$")
    phone_number_id: str = Field(pattern=r"^[0-9]{1,32}$")
    template_id: str = Field(pattern=r"^[0-9]{1,32}$")
    token: SecretStr = Field(min_length=24, max_length=8192)
    app_secret: SecretStr = Field(min_length=16, max_length=128)
    business_verified: StrictBool


class CallsSetup(BaseModel):
    account_sid: str = Field(pattern=r"^AC[0-9A-Fa-f]{32}$")
    auth_token: SecretStr = Field(min_length=16, max_length=128)
    from_number: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    prompt_url: str = Field(min_length=10, max_length=500)


class Consent(BaseModel):
    opted_in: StrictBool
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,95}$")


def _channel(value):
    if value not in (WA, CALLS):
        raise HTTPException(404, "Verification channel not found")
    return value


def _config(db, tenant, channel):
    return settings.read(db, tenant, channel, channel)["credentials"]


def _configure(tenant, actor, channel, fields):
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            previous = _config(db, tenant, channel)
        except KeyError:
            settings.create(db, tenant, channel, "WhatsApp" if channel == WA else "Urdu calls",
                            "", fields, connector_id=channel)
        else:
            if channel == WA and previous["phone_number_id"] != fields["phone_number_id"]:
                raise HTTPException(409, "Disconnect the existing WhatsApp sender before changing its phone number")
            fields.update({k: previous[k] for k in ("signing_key", "verify_token") if k in previous})
            settings.update_credentials(db, tenant, channel, fields)
        audit(db, tenant, actor, "verification_channel_configured", reference=channel)


@router.post("/merchant/channels/whatsapp")
def whatsapp_setup(body: WhatsAppSetup, response: Response, operator: Operator = Depends(owner_write)):
    if not body.business_verified:
        raise HTTPException(422, "Confirm the Meta business and utility template are approved")
    try:
        callback = f"{settings.public_base()}/providers/whatsapp/{operator.tenant_id}"
    except ValueError:
        raise HTTPException(503, "Configure a public API base URL first") from None
    fields = body.model_dump(exclude={"token", "app_secret"})
    fields.update(token=body.token.get_secret_value(), app_secret=body.app_secret.get_secret_value(),
                  signing_key=token_urlsafe(32), verify_token=token_urlsafe(32))
    _configure(operator.tenant_id, operator.actor, WA, fields)
    response.headers["Cache-Control"] = "no-store"
    return {"callback_url": callback, "verify_token": fields["verify_token"], "live_enabled": enabled()}


@router.post("/merchant/channels/calls")
def calls_setup(body: CallsSetup, operator: Operator = Depends(owner_write)):
    try:
        parts = public_https.endpoint(body.prompt_url)
        if parts.query:
            raise ValueError("Use a public HTTPS URL for the Urdu audio prompt")
        public_https.verify_url(body.prompt_url)
        settings.public_base()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _configure(operator.tenant_id, operator.actor, CALLS,
               body.model_dump(exclude={"auth_token"}) | {"auth_token": body.auth_token.get_secret_value()})
    return {"status": "configured", "live_enabled": enabled()}


def _recipient(tenant, phone):
    return _private_lookup("buyer-verification", f"{tenant}:{phone}")


def _order(db, tenant, order_id):
    order, assessment = service._assess_in_transaction(db, tenant, order_id)
    if order["data_source"].casefold() in ("synthetic", "daraz"):
        raise ValueError("This order source does not support buyer contact")
    phone = normalize_phone(order["phone"])
    if not phone:
        raise ValueError("A valid Pakistan mobile number is required")
    return order, assessment, phone


def _is_open(order, assessment):
    return order["queue_status"] == "open" and not order["storefront_conflict"] and not assessment["outcome"]


def _consent(db, tenant, channel, recipient, opt_in, evidence, actor):
    db.execute("""INSERT INTO merchant_contact_consent (tenant_id,channel,recipient,opted_in,evidence)
        VALUES (?,?,?,?,?) ON CONFLICT(tenant_id,channel,recipient) DO UPDATE SET
        opted_in=excluded.opted_in,evidence=excluded.evidence,changed_at=now()""",
               (tenant, channel, recipient, opt_in, evidence))
    if not opt_in:
        db.execute("""UPDATE merchant_verification_attempts SET status='cancelled'
            WHERE tenant_id=? AND channel=? AND recipient=? AND status IN
            ('queued','submitting','accepted','unconfirmed','waiting_review')""", (tenant, channel, recipient))
    audit(db, tenant, actor, "contact_opt_in" if opt_in else "contact_opt_out", reference=channel)


def _permitted(db, tenant, channel, recipient):
    row = db.execute("""SELECT opted_in FROM merchant_contact_consent
        WHERE tenant_id=? AND channel=? AND recipient=?""", (tenant, channel, recipient)).fetchone()
    return bool(row and row["opted_in"])


@router.put("/merchant/orders/{order_id}/contact-consent/{channel}")
def record_consent(order_id: str, channel: str, body: Consent, operator: Operator = Depends(write_operator)):
    require_platform()
    channel = _channel(channel)
    tenant = operator.tenant_id
    try:
        with write(service.STATE_PATH, tenant_id=tenant) as db:
            _, _, phone = _order(db, tenant, order_id)
            _consent(db, tenant, channel, _recipient(tenant, phone), body.opted_in, body.evidence_reference, operator.actor)
    except KeyError:
        raise HTTPException(404, "Order not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"opted_in": body.opted_in}


@router.get("/merchant/orders/{order_id}/verification")
def status(order_id: str, operator: Operator = Depends(require_operator)):
    require_platform()
    tenant = operator.tenant_id
    with connect(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            _, _, phone = _order(db, tenant, order_id)
        except KeyError:
            raise HTTPException(404, "Order not found") from None
        except ValueError:
            return {"channels": [], "live_enabled": enabled()}
        channels = {row["kind"] for row in db.execute("""SELECT kind FROM merchant_connectors
            WHERE tenant_id=? AND active AND kind IN ('whatsapp','calls')""", (tenant,))}
        result = []
        for channel in sorted(channels):
            attempt = db.execute("""SELECT id,status,created_at FROM merchant_verification_attempts
                WHERE tenant_id=? AND order_id=? AND channel=? ORDER BY created_at DESC LIMIT 1""",
                                 (tenant, order_id, channel)).fetchone()
            result.append({"channel": channel, "opted_in": _permitted(db, tenant, channel, _recipient(tenant, phone)),
                           "attempt": dict(attempt) if attempt else None})
    return {"channels": result, "live_enabled": enabled()}


@router.post("/merchant/orders/{order_id}/verification/{channel}", status_code=202)
def dispatch(order_id: str, channel: str, operator: Operator = Depends(write_operator)):
    require_platform()
    channel = _channel(channel)
    if not enabled():
        raise HTTPException(409, "Live buyer contact is disabled for this deployment")
    tenant = operator.tenant_id
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        try:
            order, assessment, phone = _order(db, tenant, order_id)
        except KeyError:
            raise HTTPException(404, "Order not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        try:
            _config(db, tenant, channel)
        except KeyError:
            raise HTTPException(409, "Configure this verification channel first") from None
        recipient = _recipient(tenant, phone)
        if not _is_open(order, assessment) or assessment["verified"]:
            raise HTTPException(409, "This order does not need automated verification")
        if not _permitted(db, tenant, channel, recipient):
            raise HTTPException(409, "Record the buyer’s opt-in before contacting them")
        revision = assessment["decision_revision"] or 0
        existing = db.execute("""SELECT id,status FROM merchant_verification_attempts
            WHERE tenant_id=? AND order_id=? AND channel=? AND expected_revision=?""",
                              (tenant, order_id, channel, revision)).fetchone()
        if existing:
            return dict(existing)
        attempt = uuid4().hex
        ttl = "24 hours" if channel == WA else "15 minutes"
        db.execute("""INSERT INTO merchant_verification_attempts
            (tenant_id,id,order_id,channel,connector_id,actor,recipient,expected_revision,status,expires_at)
            VALUES (?,?,?,?,?,?,?,?,'queued',now()+CAST(? AS interval))""",
                   (tenant, attempt, order_id, channel, channel, operator.actor, recipient, revision, ttl))
        enqueue(db, tenant, "buyer_contact", attempt, {"attempt": attempt})
        audit(db, tenant, operator.actor, "contact_queued", order_id=order_id, reference=channel)
    return {"id": attempt, "status": "queued"}


def _attempt(db, tenant, attempt):
    return db.execute("""SELECT *,expires_at>now() AS current FROM merchant_verification_attempts
        WHERE tenant_id=? AND id=?""", (tenant, attempt)).fetchone()


def _valid(db, tenant, attempt, phone=None):
    if not attempt["current"] or not _permitted(db, tenant, attempt["channel"], attempt["recipient"]):
        return None
    try:
        order, assessment, current_phone = _order(db, tenant, attempt["order_id"])
    except (ValueError, KeyError):
        return None
    if (not _is_open(order, assessment) or _recipient(tenant, current_phone) != attempt["recipient"]
            or (phone and current_phone != phone) or (assessment["decision_revision"] or 0) != attempt["expected_revision"]):
        return None
    return order, current_phone


def _change(db, tenant, attempt, status, provider=None):
    db.execute("""UPDATE merchant_verification_attempts SET status=?,provider_id=COALESCE(provider_id,?)
        WHERE tenant_id=? AND id=?""", (status, provider, tenant, attempt))


def send(tenant, payload):
    attempt_id = payload["attempt"]
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        attempt = _attempt(db, tenant, attempt_id)
        if not attempt or attempt["status"] not in ("queued", "submitting"):
            return
        if attempt["status"] == "submitting":
            _change(db, tenant, attempt_id, "unconfirmed")
            return
        if not enabled() or not _valid(db, tenant, attempt):
            _change(db, tenant, attempt_id, "cancelled")
            return
        _change(db, tenant, attempt_id, "submitting")
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        attempt = _attempt(db, tenant, attempt_id)
        if attempt["status"] != "submitting":
            return
        validated = _valid(db, tenant, attempt)
        if not enabled() or not validated:
            _change(db, tenant, attempt_id, "cancelled")
            return
        order, phone = validated
        try:
            cfg = _config(db, tenant, attempt["channel"])
            if attempt["channel"] == WA:
                sender = cloud.CloudTransport(cloud.Account(tenant_id=tenant, **cfg))
                template = sender.verify_template()
                provider_id = sender.send(order["source_order_id"] or order["order_id"], phone, template, attempt_id)
            else:
                provider_id = _call(tenant, attempt_id, cfg, phone)
        except (cloud.CloudError, httpx.HTTPError, ValueError, KeyError, RuntimeError):
            # Provider acceptance is uncertain after a transport error. Never submit a second contact.
            _change(db, tenant, attempt_id, "unconfirmed")
            return
        _change(db, tenant, attempt_id, "accepted", provider_id)


def _call_base(tenant, attempt):
    return f"{settings.public_base()}/providers/calls/{tenant}/{attempt}"


def _call(tenant, attempt, cfg, phone):
    callback = _call_base(tenant, attempt)
    twiml = ET.Element("Response")
    gather = ET.SubElement(twiml, "Gather", input="dtmf", numDigits="1", timeout="8",
                           action=f"{callback}/answer", method="POST", actionOnEmptyResult="true")
    ET.SubElement(gather, "Play").text = cfg["prompt_url"]
    ET.SubElement(twiml, "Hangup")
    result = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{cfg['account_sid']}/Calls.json",
                        auth=(cfg["account_sid"], cfg["auth_token"]), data={
                            "From": cfg["from_number"], "To": "+" + phone,
                            "Twiml": ET.tostring(twiml, encoding="unicode"),
                            "StatusCallback": f"{callback}/status", "StatusCallbackMethod": "POST",
                        }, timeout=10, follow_redirects=False)
    result.raise_for_status()
    sid = result.json()["sid"]
    if not re.fullmatch(r"CA[0-9A-Fa-f]{32}", sid):
        raise ValueError("Invalid call identifier")
    return sid


def _apply(db, tenant, attempt, text, intent, source, phone=None):
    if attempt["status"] not in ACTIONABLE:
        return
    validated = _valid(db, tenant, attempt, phone)
    if not validated:
        _change(db, tenant, attempt["id"], "waiting_review")
        return
    order, _ = validated
    with update_state(db, tenant, (order["order_id"],)) as state:
        service.apply_verification(state, order, text, intent, source, "verification-worker")
    _change(db, tenant, attempt["id"], {"CONFIRM": "confirmed", "DENY": "denied"}.get(intent, "waiting_review"))


@router.post("/providers/calls/{tenant}/{attempt_id}/{action}")
async def call_callback(tenant: str, attempt_id: str, action: str, request: Request):
    require_platform()
    if action not in ("status", "answer"):
        raise HTTPException(404, "Unknown call callback")
    form = await request.form()
    if any(not isinstance(value, str) for _, value in form.multi_items()):
        raise HTTPException(400, "Invalid Twilio callback data")
    def process():
        with write(service.STATE_PATH, tenant_id=tenant) as db:
            try:
                cfg = _config(db, tenant, CALLS)
            except KeyError:
                raise HTTPException(404, "Call configuration not found") from None
            url = f"{_call_base(tenant, attempt_id)}/{action}"
            signed = url + "".join(key + value for key in sorted(form)
                                   for value in sorted(set(form.getlist(key))))
            expected = base64.b64encode(hmac.digest(cfg["auth_token"].encode(), signed.encode(), "sha1")).decode()
            signature = request.headers.get("X-Twilio-Signature", "")
            if (not signature.isascii() or not hmac.compare_digest(signature, expected)
                    or form.get("AccountSid") != cfg["account_sid"]):
                raise HTTPException(401, "Invalid Twilio callback")
            attempt = _attempt(db, tenant, attempt_id)
            provider = form.get("CallSid", "")
            contact = normalize_phone(form.get("To"))
            if (not attempt or attempt["channel"] != CALLS or not contact
                    or _recipient(tenant, contact) != attempt["recipient"]
                    or not re.fullmatch(r"CA[0-9A-Fa-f]{32}", provider)
                    or attempt["provider_id"] not in (None, provider) or attempt["status"] not in ACTIONABLE):
                return
            if action == "answer":
                digit = form.get("Digits", "")
                intent = {"1": "CONFIRM", "2": "DENY"}.get(digit, "UNCLEAR")
                _apply(db, tenant, attempt, {"1": "Buyer pressed 1 to confirm", "2": "Buyer pressed 2 to cancel"}
                       .get(digit, "No clear keypad response"), intent, "urdu_call", contact)
            elif form.get("CallStatus") in ("busy", "no-answer", "failed", "canceled", "completed"):
                _change(db, tenant, attempt_id, "waiting_review", provider)
    await run_in_threadpool(process)
    return Response("<Response><Hangup /></Response>", media_type="application/xml")


def _wa(tenant):
    try:
        with connect(service.STATE_PATH, tenant_id=tenant) as db:
            return cloud.Account(tenant_id=tenant, **_config(db, tenant, WA))
    except KeyError:
        raise HTTPException(404, "WhatsApp sender not found") from None


@router.get("/providers/whatsapp/{tenant}")
def whatsapp_challenge(tenant: str, request: Request):
    require_platform()
    account = _wa(tenant)
    token = request.query_params.get("hub.verify_token", "")
    value = request.query_params.get("hub.challenge", "")
    if (request.query_params.get("hub.mode") != "subscribe" or not token.isascii()
            or not hmac.compare_digest(account.verify_token, token) or not re.fullmatch(r"[0-9]{1,128}", value)):
        raise HTTPException(401, "Invalid WhatsApp verification challenge")
    return PlainTextResponse(value)


def _wa_messages(tenant, account, payload):
    if payload.get("object") != "whatsapp_business_account":
        return
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        for entry in payload.get("entry", []):
            if entry.get("id") != account.waba_id:
                continue
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages" or value.get("metadata", {}).get("phone_number_id") != account.phone_number_id:
                    continue
                for event in value.get("statuses", []):
                    _wa_status(db, tenant, event)
                for message in value.get("messages", []):
                    _wa_message(db, tenant, account, message)


def _wa_status(db, tenant, event):
    phone = normalize_phone(event.get("recipient_id"))
    provider = event.get("id")
    if (not phone or not isinstance(provider, str) or not 1 <= len(provider) <= 256
            or event.get("status") not in ("sent", "delivered", "read", "failed")):
        return
    db.execute("""UPDATE merchant_verification_attempts SET provider_id=COALESCE(provider_id,?),
        status=CASE WHEN ?='failed' THEN 'waiting_review' WHEN status='unconfirmed' THEN 'accepted' ELSE status END
        WHERE tenant_id=? AND channel='whatsapp' AND recipient=? AND (provider_id=? OR
        (provider_id IS NULL AND id=?)) AND status IN ('submitting','accepted','unconfirmed')""",
               (provider, event.get("status"), tenant, _recipient(tenant, phone), provider,
                event.get("biz_opaque_callback_data", "")))


def _wa_message(db, tenant, account, message):
    phone = normalize_phone(message.get("from"))
    if not phone:
        return
    recipient = _recipient(tenant, phone)
    kind = message.get("type")
    text = (message.get("text") or {}).get("body")
    if kind == "text" and isinstance(text, str) and text.strip().casefold().rstrip(".!؟") in cloud.STOP:
        _consent(db, tenant, WA, recipient, False, "buyer_stop", "whatsapp")
        return
    context = (message.get("context") or {}).get("id")
    if kind == "button":
        button = (message.get("button") or {}).get("payload", "")
        if not isinstance(button, str) or not button.isascii():
            return
        attempt_id = button.split(".", 1)[0]
        if not re.fullmatch(r"[a-f0-9]{32}", attempt_id):
            return
        attempt = _attempt(db, tenant, attempt_id)
        if (not attempt or attempt["channel"] != WA or attempt["recipient"] != recipient
                or (context and attempt["provider_id"] not in (None, context))):
            return
        for intent, label in cloud.BUTTONS.items():
            if hmac.compare_digest(button, cloud._button(account, attempt_id, intent)):
                _apply(db, tenant, attempt, label, intent, "whatsapp_button", phone)
                return
        return
    if not isinstance(context, str) or not context:
        return
    attempt = db.execute("""SELECT *,expires_at>now() AS current FROM merchant_verification_attempts
        WHERE tenant_id=? AND channel='whatsapp' AND recipient=? AND provider_id=?""",
                         (tenant, recipient, context)).fetchone()
    if not attempt or attempt["status"] not in ACTIONABLE:
        return
    if kind == "text" and isinstance(text, str) and 0 < len(text.strip()) <= 2000:
        _apply(db, tenant, attempt, text, parse_reply(text), "whatsapp", phone)
    elif kind == "audio":
        media_id = (message.get("audio") or {}).get("id")
        if isinstance(media_id, str) and re.fullmatch(r"[0-9]{1,32}", media_id) and _valid(db, tenant, attempt, phone):
            enqueue(db, tenant, "buyer_audio", f"{attempt['id']}:{media_id}",
                    {"attempt": attempt["id"], "media": media_id})


@router.post("/providers/whatsapp/{tenant}")
async def whatsapp_callback(tenant: str, request: Request):
    require_platform()
    account = await run_in_threadpool(_wa, tenant)
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(413, "WhatsApp callback is too large")
    if not cloud.signed_callback(account, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Invalid WhatsApp callback signature")
    try:
        await run_in_threadpool(_wa_messages, tenant, account, json.loads(body))
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise HTTPException(422, "Invalid WhatsApp callback") from None
    return {"ok": True}


def transcribe(tenant, payload):
    account = _wa(tenant)
    media = cloud.CloudTransport(account).request("GET", payload["media"])
    url = media.get("url", "")
    parsed = public_https.endpoint(url)
    if parsed.hostname != "lookaside.fbsbx.com":
        raise PermanentFailure("Meta audio URL was outside the media host")
    status, _, audio = public_https.request("GET", url, headers={"Authorization": f"Bearer {account.token}"},
                                            limit=VOICE_LIMIT_BYTES)
    if status != 200:
        raise RuntimeError("Meta audio download failed")
    result = transcribe_voice_note(audio, suffix=".ogg")
    text = result["text"][:2000] if result["ok"] else "Voice note could not be transcribed"
    with write(service.STATE_PATH, tenant_id=tenant) as db:
        attempt = _attempt(db, tenant, payload["attempt"])
        if attempt:
            _apply(db, tenant, attempt, text, "UNCLEAR", "whatsapp_voice_review")
