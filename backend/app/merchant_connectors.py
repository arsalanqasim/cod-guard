"""Encrypted settings and account metadata for merchant connectors."""
import json
import os
from uuid import uuid4

from platform_data import decrypt, encrypt
from public_https import endpoint


def create(db, tenant, kind, name, address, credentials, *, connector_id=None, active=True):
    connector_id = connector_id or uuid4().hex
    db.execute("""INSERT INTO merchant_connectors (tenant_id, id, kind, name, address, credentials, active)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
               (tenant, connector_id, kind, name, address,
                encrypt(json.dumps(credentials), tenant, connector_id, "connector.credentials"), active))
    return connector_id


def read(db, tenant, connector_id, kind, *, active=True):
    row = db.execute("""SELECT * FROM merchant_connectors WHERE tenant_id=? AND id=? AND kind=? AND active=?""",
                     (tenant, connector_id, kind, active)).fetchone()
    if row is None:
        raise KeyError(connector_id)
    return {**row, "credentials": json.loads(decrypt(row["credentials"], tenant, connector_id, "connector.credentials"))}


def update_credentials(db, tenant, connector_id, fields):
    db.execute("UPDATE merchant_connectors SET credentials=? WHERE tenant_id=? AND id=?",
               (encrypt(json.dumps(fields), tenant, connector_id, "connector.credentials"), tenant, connector_id))


def listing(db, tenant):
    rows = db.execute("""SELECT id, kind, name, address, active, created_at FROM merchant_connectors
        WHERE tenant_id=? AND kind<>'shopify_install' ORDER BY created_at DESC""", (tenant,)).fetchall()
    result = []
    for row in rows:
        entry = dict(row)
        kind = row["kind"]
        if row["active"] and kind in ("shopify", "woocommerce"):
            credentials = read(db, tenant, row["id"], kind)["credentials"]
            entry["options"] = {name: bool(credentials.get(name)) for name in (
                ("enforce",) if kind == "shopify" else
                ("hold_on_unverified", "release_on_confirmed", "write_outcomes")
            )}
            job = db.execute("""SELECT status,error FROM integration_jobs WHERE tenant_id=?
                AND (kind='woo_setup' AND dedupe=? OR kind='shopify_setup' AND starts_with(dedupe,?))
                ORDER BY created_at DESC LIMIT 1""", (tenant, row["id"], row["id"] + ":")).fetchone()
            if job:
                entry["setup"] = dict(job)
        result.append(entry)
    return result


def public_base():
    value = os.environ.get("COD_GUARD_PUBLIC_API_BASE", "").rstrip("/")
    parts = endpoint(value)
    if parts.query:
        raise ValueError("Configure a public HTTPS API base URL for provider callbacks")
    return value


def portal_home():
    parts = endpoint(public_base())
    return f"https://{parts.netloc}/"
