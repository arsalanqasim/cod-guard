"""Configuration-backed API identities for the single-instance pilot."""
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from merchant_auth import limit_operator, require_portal_origin, require_session
from platform_data import database_url


@dataclass(frozen=True)
class Operator:
    actor: str
    tenant_id: str
    role: str = "pilot"


_bearer = HTTPBearer(auto_error=False)
_limits_lock = Lock()
_write_windows = {}


def _configured_operators(config):
    records = json.loads(config)
    if not isinstance(records, dict):
        raise ValueError("Operator configuration must be an object")
    entries = []
    for actor, record in records.items():
        tenant, key = record["tenant_id"], record["key"]
        if not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)
                   for name in (actor, tenant)) or not isinstance(key, str) or len(key) < 24:
            raise ValueError("Invalid operator configuration")
        digest = hashlib.sha256(key.encode()).digest()
        if any(hmac.compare_digest(digest, other) for other, _ in entries):
            raise ValueError("Each operator must use a distinct key")
        entries.append((digest, Operator(actor, tenant)))
    return entries


def order_reader(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if database_url():
        session = require_session(request)
        return Operator(session["user_id"], session["tenant_id"], session["role"])
    try:
        entries = _configured_operators(os.environ.get("COD_GUARD_OPERATORS", "{}"))
    except (TypeError, ValueError, KeyError):
        raise HTTPException(status_code=503, detail="Operator configuration is unavailable") from None
    if credentials:
        presented = hashlib.sha256(credentials.credentials.encode()).digest()
        for digest, operator in entries:
            if hmac.compare_digest(presented, digest):
                return operator
    raise HTTPException(status_code=401, detail="Operator key required", headers={"WWW-Authenticate": "Bearer"})


def require_operator(operator: Operator = Depends(order_reader)):
    if operator.role == "packer":
        raise HTTPException(403, "This action is restricted to owners and operations staff")
    return operator


def write_operator(request: Request, operator: Operator = Depends(require_operator)):
    if operator.role != "pilot":
        require_portal_origin(request)
        limit_operator(operator)
        return operator
    now = monotonic()
    with _limits_lock:
        started, count = _write_windows.get(operator, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        if count >= 60:
            raise HTTPException(status_code=429, detail="Operator write limit exceeded",
                                headers={"Retry-After": str(max(1, int(61 - (now - started))))})
        _write_windows[operator] = started, count + 1
    return operator
