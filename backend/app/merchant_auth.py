"""Email-verified merchant access and opaque, server-side browser sessions."""
import hashlib
import hmac
import os
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache
from secrets import token_urlsafe
from typing import Literal
from uuid import uuid4

import psycopg
import redis
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from platform_data import connection, database_url
from records import StateUnavailable


router = APIRouter(prefix="/auth")
SESSION = "__Host-cod-guard-session"
CHALLENGE = "__Host-cod-guard-challenge"
SESSION_SECONDS = 12 * 60 * 60
CHALLENGE_SECONDS = 15 * 60
EMAIL_PATTERN = r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"


def portal_origins():
    return [origin.strip() for origin in os.environ.get("COD_GUARD_PORTAL_ORIGINS", "").split(",")
            if origin.strip() and origin.strip() != "*"]


def require_portal_origin(request):
    if request.headers.get("origin") not in portal_origins():
        raise HTTPException(403, "Unrecognized portal origin")


def _digest(value):
    return hashlib.sha256(value.encode()).digest()


def _private_lookup(kind, value):
    key = os.environ.get("COD_GUARD_AUTH_KEY", "")
    if len(key) < 43:
        raise StateUnavailable("Merchant authentication is unavailable")
    return hmac.digest(key.encode(), f"{kind}:{value}".encode(), "sha256")


def _platform_request(request):
    if not database_url():
        raise HTTPException(404, "Merchant authentication is unavailable")
    require_portal_origin(request)


def _set_cookie(response, name, value, ttl):
    response.set_cookie(name, value, max_age=ttl, secure=True, httponly=True, samesite="lax", path="/")


def _clear_cookie(response, name):
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def _mail(to, subject, message):
    host = os.environ.get("COD_GUARD_SMTP_HOST")
    sender = os.environ.get("COD_GUARD_SMTP_FROM")
    if not host or not sender:
        raise StateUnavailable("Merchant email is unavailable")
    email = EmailMessage()
    email["From"], email["To"], email["Subject"] = sender, to, subject
    email.set_content(message)
    try:
        port = int(os.environ.get("COD_GUARD_SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=8) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if user := os.environ.get("COD_GUARD_SMTP_USER"):
                smtp.login(user, os.environ["COD_GUARD_SMTP_PASSWORD"])
            smtp.send_message(email)
    except (OSError, ValueError, KeyError) as exc:
        raise StateUnavailable("Merchant email is unavailable") from exc


def _limit(purpose, value, maximum, window):
    bucket = _private_lookup(purpose, value)
    redis_url = os.environ.get("COD_GUARD_REDIS_URL")
    if redis_url:
        try:
            count, ttl = _redis(redis_url).eval("""local count = redis.call('INCR', KEYS[1])
                if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
                return {count, redis.call('TTL', KEYS[1])}""", 1, f"cod-guard:limits:{bucket.hex()}", window)
        except (redis.RedisError, OSError, ValueError) as exc:
            raise StateUnavailable("Merchant rate limits are unavailable") from exc
    else:
        count, ttl = _database_limit(bucket, maximum, window)
    if count > maximum:
        raise HTTPException(429, "Request limit exceeded", headers={"Retry-After": str(max(1, ttl))})


@lru_cache(maxsize=2)
def _redis(url):
    return redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)


def _database_limit(bucket, maximum, window):
    with connection() as db:
        row = db.execute("""INSERT INTO merchant_auth_limits AS limits (bucket, expires, requests)
            VALUES (%s, now() + make_interval(secs => %s), 1)
            ON CONFLICT (bucket) DO UPDATE SET
            requests = CASE WHEN limits.expires <= now() THEN 1 ELSE LEAST(limits.requests + 1, %s) END,
            expires = CASE WHEN limits.expires <= now() THEN EXCLUDED.expires ELSE limits.expires END
            RETURNING requests, CAST(ceil(extract(epoch FROM (expires - now()))) AS integer) AS ttl""",
                         (bucket, window, maximum + 1)).fetchone()
    return row["requests"], row["ttl"]


def _session(db, request):
    token = request.cookies.get(SESSION, "")
    if len(token) != 43:
        return None
    return db.execute("""SELECT s.user_id, s.tenant_id, m.role, a.name
        FROM merchant_sessions s JOIN merchant_memberships m USING (tenant_id, user_id)
        JOIN merchant_accounts a ON a.id = s.tenant_id
        WHERE s.digest = %s AND s.expires > now()""", (_digest(token),)).fetchone()


def require_session(request):
    with connection() as db:
        session = _session(db, request)
    if session is None:
        raise HTTPException(401, "Sign in to your merchant account")
    return session


def limit_operator(session):
    _limit("operator", f"{session.tenant_id}:{session.actor}", 60, 60)


def _new_session(db, request, response, user_id, tenant_id):
    token = token_urlsafe(32)
    if old := request.cookies.get(SESSION):
        db.execute("DELETE FROM merchant_sessions WHERE digest = %s", (_digest(old),))
    db.execute("""INSERT INTO merchant_sessions VALUES (%s, %s, %s, now() + make_interval(secs => %s))""",
               (_digest(token), user_id, tenant_id, SESSION_SECONDS))
    _set_cookie(response, SESSION, token, SESSION_SECONDS)


def _memberships(db, user_id):
    return db.execute("""SELECT m.tenant_id, m.role, a.name FROM merchant_memberships m
        JOIN merchant_accounts a ON a.id = m.tenant_id WHERE m.user_id = %s
        ORDER BY a.created_at, a.id""", (user_id,)).fetchall()


class Email(BaseModel):
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)


class EmailProof(BaseModel):
    code: str = Field(pattern=TOKEN_PATTERN)
    store_name: str | None = Field(default=None, min_length=1, max_length=100)
    invitation: str | None = Field(default=None, pattern=TOKEN_PATTERN)


class Invitation(Email):
    role: Literal["ops", "packer"]


class TenantSelection(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)


@router.post("/email/start", status_code=202)
def start_email(body: Email, request: Request, response: Response):
    _platform_request(request)
    response.headers["Cache-Control"] = "no-store"
    email = body.email.casefold()
    _limit("email-ip", request.client.host if request.client else "unknown", 30, 3600)
    _limit("email-address", email, 5, 3600)
    browser, code = token_urlsafe(32), token_urlsafe(32)
    with connection() as db:
        db.execute("""INSERT INTO merchant_challenges VALUES (%s, %s, %s, now() + make_interval(secs => %s))""",
                   (_digest(code), _private_lookup("address", email), _digest(browser), CHALLENGE_SECONDS))
    _mail(email, "Your COD-Guard sign-in code", f"Enter this code in COD-Guard within 15 minutes:\n\n{code}\n")
    _set_cookie(response, CHALLENGE, browser, CHALLENGE_SECONDS)
    return {"status": "code_sent"}


@router.post("/email/complete")
def complete_email(body: EmailProof, request: Request, response: Response):
    _platform_request(request)
    response.headers["Cache-Control"] = "no-store"
    browser = request.cookies.get(CHALLENGE, "")
    if len(browser) != 43:
        raise HTTPException(401, "Start a new email sign-in")
    _limit("proof-browser", browser, 10, 900)
    with connection() as db:
        challenge = db.execute("""DELETE FROM merchant_challenges
            WHERE digest = %s AND browser_key = %s AND expires > now() RETURNING email_key""",
                               (_digest(body.code), _digest(browser))).fetchone()
        if challenge is None:
            raise HTTPException(401, "Sign-in code is invalid or expired")
        email_key = challenge["email_key"]
        user_id = db.execute("""INSERT INTO merchant_users (id, email_key) VALUES (%s, %s)
            ON CONFLICT (email_key) DO UPDATE SET email_key = EXCLUDED.email_key RETURNING id""",
                             (uuid4().hex, email_key)).fetchone()["id"]
        selected = None
        if body.invitation:
            invitation = db.execute("""DELETE FROM merchant_invitations
                WHERE digest = %s AND email_key = %s AND expires > now() RETURNING tenant_id, role""",
                                    (_digest(body.invitation), email_key)).fetchone()
            if invitation is None:
                raise HTTPException(409, "Invitation is invalid or expired")
            selected = invitation["tenant_id"]
            db.execute("INSERT INTO merchant_memberships VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                       (selected, user_id, invitation["role"]))
        memberships = _memberships(db, user_id)
        if not memberships:
            name = (body.store_name or "").strip()
            if not name or any(ord(char) < 32 for char in name):
                raise HTTPException(422, "Enter a valid business name to create your merchant account")
            selected = uuid4().hex
            db.execute("INSERT INTO merchant_accounts (id, name) VALUES (%s, %s)", (selected, name))
            db.execute("INSERT INTO merchant_memberships VALUES (%s, %s, 'owner')", (selected, user_id))
            memberships = _memberships(db, user_id)
        current = next((row for row in memberships if row["tenant_id"] == selected), memberships[0])
        _new_session(db, request, response, user_id, current["tenant_id"])
    _clear_cookie(response, CHALLENGE)
    return {"merchant": current, "memberships": memberships}


@router.get("/session")
def session_info(request: Request, response: Response):
    if not database_url():
        raise HTTPException(404, "Merchant authentication is unavailable")
    response.headers["Cache-Control"] = "no-store"
    with connection() as db:
        session = _session(db, request)
        if session is None:
            raise HTTPException(401, "Sign in to your merchant account")
        memberships = _memberships(db, session["user_id"])
    merchant = {key: session[key] for key in ("tenant_id", "name", "role")}
    return {"merchant": merchant, "memberships": memberships}


@router.post("/session/tenant")
def select_tenant(body: TenantSelection, request: Request, response: Response):
    _platform_request(request)
    response.headers["Cache-Control"] = "no-store"
    with connection() as db:
        session = _session(db, request)
        if session is None:
            raise HTTPException(401, "Sign in to your merchant account")
        memberships = _memberships(db, session["user_id"])
        merchant = next((row for row in memberships if row["tenant_id"] == body.tenant_id), None)
        if merchant is None:
            raise HTTPException(404, "Merchant account not found")
        _new_session(db, request, response, session["user_id"], body.tenant_id)
    return {"merchant": merchant, "memberships": memberships}


@router.delete("/session", status_code=204)
def sign_out(request: Request, response: Response):
    _platform_request(request)
    if token := request.cookies.get(SESSION):
        with connection() as db:
            db.execute("DELETE FROM merchant_sessions WHERE digest = %s", (_digest(token),))
    _clear_cookie(response, SESSION)


@router.post("/invitations", status_code=202)
def invite(body: Invitation, request: Request, response: Response):
    _platform_request(request)
    response.headers["Cache-Control"] = "no-store"
    session = require_session(request)
    if session["role"] != "owner":
        raise HTTPException(403, "Only a store owner can invite staff")
    _limit("invitations", session["tenant_id"], 30, 3600)
    email, code = body.email.casefold(), token_urlsafe(32)
    with connection() as db:
        db.execute("""INSERT INTO merchant_invitations VALUES (%s, %s, %s, %s, now() + interval '24 hours', %s)""",
                   (_digest(code), session["tenant_id"], _private_lookup("address", email),
                    body.role, session["user_id"]))
    _mail(email, "COD-Guard team invitation",
          f'You were invited to join {session["name"]} as {body.role}. '
          f"Use this invitation code when signing in to COD-Guard within 24 hours:\n\n{code}\n")
    return {"status": "invitation_sent"}


def database_error(_request, _exc: psycopg.Error):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": "Merchant database is unavailable",
                                                  "error": "state_unavailable"})
