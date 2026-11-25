"""Consent-scoped advisory counts; this module does not score or hold orders."""

import hmac
import os
import re
from time import time

from pakistan_phone import normalize_phone
from platform_data import database_url
from records import DEMO_TENANT, audit, connect, write


DAYS = 90
TTL = DAYS * 24 * 60 * 60
MIN_OTHER_SELLERS = 3
OUTCOMES = ("delivered", "returned", "refused")


class NetworkUnavailable(ValueError):
    pass


def configuration():
    if database_url():
        return None, ()
    secret = os.environ.get("COD_GUARD_NETWORK_KEY", "")
    tenants = tuple(sorted({part.strip() for part in os.environ.get("COD_GUARD_NETWORK_TENANTS", "").split(",")
                            if part.strip()}))
    if (not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret) or not 1 <= len(tenants) <= 500
            or DEMO_TENANT in tenants or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", tenant) for tenant in tenants)):
        return None, ()
    return secret.encode(), tenants


def phone_key(secret, phone):
    return hmac.digest(secret, f"cod-guard-network-v1:{phone}".encode(), "sha256").hex()


def _order_key(secret, order):
    if order["data_source"].casefold() in ("synthetic", "daraz"):
        return None
    phone = normalize_phone(order["phone"])
    return phone_key(secret, phone) if phone else None


def _allowed(tenant_id):
    secret, tenants = configuration()
    if tenant_id not in tenants:
        raise NetworkUnavailable("Reputation network is not enabled for this tenant")
    return secret, tenants


def _matches_key(db, secret, *, bind=False):
    tag = hmac.digest(secret, b"cod-guard-network-key-check", "sha256").hex()
    if bind:
        db.execute("INSERT OR IGNORE INTO network_metadata VALUES (1, ?)", (tag,))
    record = db.execute("SELECT key_tag FROM network_metadata WHERE id=1").fetchone()
    return record is None or hmac.compare_digest(record["key_tag"], tag)


def seller_enrollment(path, tenant_id, actor, enabled):
    if database_url():
        raise NetworkUnavailable("Reputation network is not enabled for this tenant")
    if enabled:
        secret, _ = _allowed(tenant_id)
    with write(path) as db:
        if enabled:
            if not _matches_key(db, secret, bind=True):
                raise NetworkUnavailable("Reputation network key does not match stored data")
            db.execute("INSERT OR IGNORE INTO network_sellers VALUES (?)", (tenant_id,))
        else:
            db.execute("DELETE FROM network_sellers WHERE tenant_id=?", (tenant_id,))
        audit(db, tenant_id, actor, "network_enrolled" if enabled else "network_withdrawn")


def buyer_consent(path, tenant_id, actor, order, enabled, evidence):
    if database_url():
        raise NetworkUnavailable("Reputation network is not enabled for this tenant")
    secret, tenants = configuration()
    if not secret or (enabled and tenant_id not in tenants):
        raise NetworkUnavailable("Reputation network is not enabled for this tenant")
    key = _order_key(secret, order)
    if not key:
        raise NetworkUnavailable("No eligible mobile number for this order")
    current = int(time())
    with write(path) as db:
        if not _matches_key(db, secret):
            raise NetworkUnavailable("Reputation network key does not match stored data")
        if enabled:
            if not db.execute("SELECT 1 FROM network_sellers WHERE tenant_id=?", (tenant_id,)).fetchone():
                raise NetworkUnavailable("Seller has not joined the network")
            if db.execute("SELECT 1 FROM network_suppressions WHERE phone_key=?", (key,)).fetchone():
                raise NetworkUnavailable("Consent could not be recorded; contact the network steward")
            db.execute("DELETE FROM network_consents WHERE tenant_id=? AND phone_key=? AND expires<=?",
                       (tenant_id, key, current))
            db.execute("""INSERT INTO network_consents VALUES (?, ?, ?, ?) ON CONFLICT DO UPDATE SET
                expires=excluded.expires, evidence_reference=excluded.evidence_reference""",
                       (tenant_id, key, current + TTL, evidence))
        else:
            db.execute("DELETE FROM network_consents WHERE tenant_id=? AND phone_key=?", (tenant_id, key))
        audit(db, tenant_id, actor, "network_consent_granted" if enabled else "network_consent_revoked")


def contribute(db, tenant_id, order, outcome):
    secret, tenants = configuration()
    if (tenant_id not in tenants or not _matches_key(db, secret) or not (key := _order_key(secret, order))
            or outcome not in OUTCOMES):
        return
    current = int(time())
    db.execute("""INSERT OR IGNORE INTO network_contributions
        SELECT ?, ?, phone_key, ?, MIN(expires, ?) FROM network_consents
        WHERE tenant_id=? AND phone_key=? AND expires>? AND NOT EXISTS
        (SELECT 1 FROM network_suppressions WHERE phone_key=?)""",
               (tenant_id, order["order_id"], outcome, current + TTL, tenant_id, key, current, key))


def counts(path, tenant_id, order):
    secret, tenants = _allowed(tenant_id)
    key = _order_key(secret, order)
    current = int(time())
    if not key:
        return None
    with connect(path) as db:
        db.execute("BEGIN")
        if not _matches_key(db, secret):
            return None
        if not db.execute("""SELECT 1 FROM network_consents WHERE tenant_id=? AND phone_key=? AND expires>?
            AND NOT EXISTS (SELECT 1 FROM network_suppressions WHERE phone_key=?)""",
                          (tenant_id, key, current, key)).fetchone():
            return None
        slots = ",".join("?" for _ in tenants)
        rows = db.execute(f"""SELECT tenant_id, outcome, COUNT(*) AS total FROM network_contributions
            WHERE phone_key=? AND tenant_id<>? AND expires>? AND tenant_id IN ({slots})
            GROUP BY tenant_id, outcome""", (key, tenant_id, current, *tenants)).fetchall()
    if len({row["tenant_id"] for row in rows}) < MIN_OTHER_SELLERS:
        return None
    return {outcome: sum(row["total"] for row in rows if row["outcome"] == outcome) for outcome in OUTCOMES}


def size(path):
    secret, tenants = configuration()
    if not secret:
        return {"enabled": False, "contributing_sellers": 0}
    slots = ",".join("?" for _ in tenants)
    with connect(path) as db:
        db.execute("BEGIN")
        if not _matches_key(db, secret):
            return {"enabled": False, "contributing_sellers": 0}
        total = db.execute(f"""SELECT COUNT(DISTINCT tenant_id) FROM network_contributions WHERE expires>?
            AND tenant_id IN ({slots})""", (int(time()), *tenants)).fetchone()[0]
    return {"enabled": True, "contributing_sellers": total}


def suppress_subject(path, phone, reference):
    secret, _ = configuration()
    if not secret or not (normalized := normalize_phone(phone)):
        raise NetworkUnavailable("Network configuration and a valid mobile number are required")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{2,95}", reference):
        raise ValueError("Use a non-PII appeals case reference")
    key = phone_key(secret, normalized)
    with write(path) as db:
        if not _matches_key(db, secret, bind=True):
            raise NetworkUnavailable("Reputation network key does not match stored data")
        db.execute("INSERT OR IGNORE INTO network_suppressions VALUES (?)", (key,))
        removed = db.execute("DELETE FROM network_consents WHERE phone_key=?", (key,)).rowcount
        audit(db, "network-governance", "network-steward", "network_subject_removed", reference=reference)
    return removed


def purge_expired(path):
    current = int(time())
    with write(path) as db:
        db.execute("DELETE FROM network_contributions WHERE expires<=?", (current,))
        return db.execute("DELETE FROM network_consents WHERE expires<=?", (current,)).rowcount
