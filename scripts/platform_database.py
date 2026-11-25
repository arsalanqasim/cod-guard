"""Provision the merchant schema using a migration account, separate from the API account."""
import argparse
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import records
from merchant_auth import _private_lookup
from platform_data import TenantConnection, encrypt


_VERSION = 3
_SOURCE_VERSION = 13
_SERIAL_TABLES = ("audit_events", "messages", "reply_corrections")
_SCOPED_TABLES = {
    "orders", "decisions", "outcomes", "messages", "model_versions", "model_feedback", "audit_events",
    "imports", "external_orders", "connector_state", "storefront_order_status", "whatsapp_consent",
    "whatsapp_verifications", "courier_outcome_evidence", "network_sellers", "network_consents",
    "network_contributions", "reply_corrections", "reply_shadow_predictions", "address_findings",
    "address_clarifications", "prepaid_offer_outcomes", "risk_shadow_decisions",
}
_WORK_SCHEMA = (
    """CREATE TABLE merchant_voice_jobs (
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), order_id TEXT NOT NULL,
        actor TEXT NOT NULL, suffix TEXT NOT NULL, audio TEXT, status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'done', 'failed')),
        result TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, claim TEXT,
        lease_until TIMESTAMPTZ, relay_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        deadline TIMESTAMPTZ NOT NULL DEFAULT now() + interval '1 hour',
        finished_at TIMESTAMPTZ,
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders (tenant_id, order_id))""",
    """CREATE INDEX merchant_voice_relay ON merchant_voice_jobs (tenant_id, relay_at)
        WHERE status IN ('queued', 'running')""",
)
_AUTH_SCHEMA = (
    """CREATE TABLE merchant_accounts (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE merchant_users (
        id TEXT PRIMARY KEY, email_key BYTEA NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE merchant_memberships (
        tenant_id TEXT REFERENCES merchant_accounts(id), user_id TEXT REFERENCES merchant_users(id),
        role TEXT NOT NULL CHECK(role IN ('owner', 'ops', 'packer')),
        PRIMARY KEY (tenant_id, user_id))""",
    """CREATE TABLE merchant_invitations (
        digest BYTEA PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), email_key BYTEA NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('ops', 'packer')), expires TIMESTAMPTZ NOT NULL,
        created_by TEXT NOT NULL REFERENCES merchant_users(id))""",
    """CREATE TABLE merchant_challenges (
        digest BYTEA PRIMARY KEY, email_key BYTEA NOT NULL, browser_key BYTEA NOT NULL,
        expires TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE merchant_sessions (
        digest BYTEA PRIMARY KEY, user_id TEXT NOT NULL, tenant_id TEXT NOT NULL, expires TIMESTAMPTZ NOT NULL,
        FOREIGN KEY (tenant_id, user_id) REFERENCES merchant_memberships(tenant_id, user_id) ON DELETE CASCADE)""",
    """CREATE TABLE merchant_auth_limits (
        bucket BYTEA PRIMARY KEY, expires TIMESTAMPTZ NOT NULL, requests INTEGER NOT NULL)""",
    "CREATE INDEX merchant_memberships_user ON merchant_memberships(user_id, tenant_id)",
    "CREATE INDEX merchant_sessions_expiry ON merchant_sessions(expires)",
    "CREATE INDEX merchant_challenges_expiry ON merchant_challenges(expires)",
    "CREATE INDEX merchant_invitations_expiry ON merchant_invitations(expires)",
    "CREATE INDEX merchant_auth_limits_expiry ON merchant_auth_limits(expires)",
)
_INTEGRATION_SCHEMA = (
    """CREATE TABLE merchant_connectors (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), id TEXT NOT NULL,
        kind TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '',
        credentials TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id, id))""",
    """CREATE TABLE merchant_api_keys (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), id TEXT NOT NULL,
        digest BYTEA NOT NULL, name TEXT NOT NULL, scope TEXT NOT NULL, revoked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id, id),
        UNIQUE (tenant_id, digest))""",
    """CREATE TABLE integration_jobs (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), id TEXT NOT NULL,
        kind TEXT NOT NULL, dedupe TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, relay_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        run_after TIMESTAMPTZ NOT NULL DEFAULT now(), lease_until TIMESTAMPTZ, claim TEXT,
        error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
        PRIMARY KEY (tenant_id, id), UNIQUE(tenant_id, kind, dedupe))""",
    """CREATE INDEX integration_job_relay ON integration_jobs (tenant_id, relay_at, run_after)
        WHERE status IN ('queued','running')""",
    """CREATE TABLE merchant_order_receipts (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), key TEXT NOT NULL, digest TEXT NOT NULL,
        receipt TEXT NOT NULL, PRIMARY KEY (tenant_id, key))""",
    """CREATE TABLE merchant_shopify_routes (
        shop TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id))""",
    """CREATE TABLE merchant_contact_consent (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), channel TEXT NOT NULL, recipient BYTEA NOT NULL,
        opted_in BOOLEAN NOT NULL, evidence TEXT NOT NULL, changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id,channel,recipient))""",
    """CREATE TABLE merchant_verification_attempts (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), id TEXT NOT NULL,
        order_id TEXT NOT NULL, channel TEXT NOT NULL, connector_id TEXT NOT NULL, actor TEXT NOT NULL,
        recipient BYTEA NOT NULL, expected_revision BIGINT NOT NULL, status TEXT NOT NULL,
        provider_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (tenant_id,id), FOREIGN KEY (tenant_id,order_id) REFERENCES orders(tenant_id,order_id),
        UNIQUE(tenant_id,order_id,channel,expected_revision), UNIQUE(tenant_id,channel,provider_id))""",
    """CREATE TABLE merchant_shipments (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), order_id TEXT NOT NULL,
        courier TEXT NOT NULL, tracking TEXT NOT NULL, order_day DATE, terminal TEXT,
        evidence_reference TEXT, last_poll TIMESTAMPTZ,
        PRIMARY KEY(tenant_id,order_id), UNIQUE(tenant_id,courier,tracking),
        FOREIGN KEY(tenant_id,order_id) REFERENCES orders(tenant_id,order_id))""",
)
_INTEGRATION_TABLES = ("merchant_connectors", "merchant_api_keys", "integration_jobs", "merchant_order_receipts",
                       "merchant_contact_consent", "merchant_verification_attempts", "merchant_shipments")
_PRIVACY_SCHEMA = (
    "ALTER TABLE merchant_shopify_routes ADD COLUMN installation_id TEXT NOT NULL DEFAULT gen_random_uuid()::text",
    """CREATE TABLE shopify_privacy_requests (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), id TEXT NOT NULL, shop TEXT NOT NULL,
        topic TEXT NOT NULL, event_key TEXT NOT NULL, orders TEXT,
        status TEXT NOT NULL CHECK(status IN ('pending','ready','done','review')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
        PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,event_key))""",
    """CREATE TABLE shopify_redacted_orders (
        tenant_id TEXT NOT NULL REFERENCES merchant_accounts(id), shop TEXT NOT NULL, external_id TEXT NOT NULL,
        PRIMARY KEY(tenant_id,shop,external_id))""",
)


def _tenant_policy(db, name, predicate):
    table = sql.Identifier("cod_guard", name)
    db.execute(sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(table))
    db.execute(sql.SQL("ALTER TABLE {} FORCE ROW LEVEL SECURITY").format(table))
    db.execute(sql.SQL("CREATE POLICY tenant_isolation ON {} USING ({}) WITH CHECK ({})")
               .format(table, sql.SQL(predicate), sql.SQL(predicate)))


def _state_schema():
    if records.STATE_SCHEMA_VERSION != _SOURCE_VERSION:
        raise RuntimeError("The PostgreSQL state schema must be reviewed for this SQLite schema version")
    for statement in (
        *records.SCHEMA, *records.CONNECTOR_SCHEMA, *records.WHATSAPP_SCHEMA, *records.COURIER_SCHEMA,
        *records.NETWORK_SCHEMA, *records.REPLY_CORRECTION_SCHEMA, *records.DISPATCH_ADVICE_SCHEMA,
        *records.RISK_SHADOW_SCHEMA,
    ):
        table = re.match(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", statement)
        if table and table[1] in _SERIAL_TABLES:
            statement = statement.replace("id INTEGER PRIMARY KEY", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
        statement = re.sub(r"\bmessage_id INTEGER\b", "message_id BIGINT", statement)
        statement = re.sub(r"\b(revision|decision_revision|expires|estimated_usd_micros) INTEGER\b",
                           r"\1 BIGINT", statement)
        yield re.sub(r"\bREAL\b", "DOUBLE PRECISION", statement)


def migrate(db, runtime_role):
    role = sql.Identifier(runtime_role)
    unsafe_role = db.execute("""SELECT rolsuper OR rolbypassrls OR rolcreaterole
        OR pg_has_role(rolname, current_user, 'MEMBER') FROM pg_roles WHERE rolname=%s""",
                             (runtime_role,)).fetchone()
    if unsafe_role is None or unsafe_role[0]:
        raise ValueError("Use a dedicated, unprivileged PostgreSQL runtime role")
    db.execute("SELECT pg_advisory_xact_lock(579032610055)")
    db.execute("CREATE SCHEMA IF NOT EXISTS cod_guard")
    db.execute("SET LOCAL search_path TO pg_catalog, cod_guard")
    db.execute("CREATE TABLE IF NOT EXISTS cod_guard.schema_version (version INTEGER PRIMARY KEY)")
    current = db.execute("SELECT version FROM cod_guard.schema_version").fetchone()
    current_tenant = "NULLIF(current_setting('cod_guard.tenant_id', true), '')"
    if current is None:
        # Creation uses the merchant schema, and runtime queries give pg_catalog precedence.
        db.execute("SET LOCAL search_path TO cod_guard, pg_catalog")
        for statement in (*_state_schema(), *_AUTH_SCHEMA, *_WORK_SCHEMA):
            db.execute(statement)
        db.execute("INSERT INTO merchant_accounts (id, name) VALUES ('demo', 'COD-Guard demo')")
        db.execute("ALTER TABLE messages ADD UNIQUE (tenant_id, id)")
        for name in ("reply_corrections", "reply_shadow_predictions"):
            table = sql.Identifier(name)
            db.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}")
                       .format(table, sql.Identifier(f"{name}_message_id_fkey")))
            db.execute(sql.SQL("""ALTER TABLE {} ADD FOREIGN KEY (tenant_id, message_id)
                REFERENCES messages (tenant_id, id) ON DELETE CASCADE""").format(table))
        predicates = {table: f"tenant_id = {current_tenant}" for table in _SCOPED_TABLES | {"merchant_voice_jobs"}}
        predicates["whatsapp_unclear_receipts"] = (
            "EXISTS (SELECT 1 FROM cod_guard.whatsapp_verifications AS v "
            "WHERE v.attempt_id = whatsapp_unclear_receipts.attempt_id "
            f"AND v.tenant_id = {current_tenant})"
        )
        for name, predicate in sorted(predicates.items()):
            _tenant_policy(db, name, predicate)
        db.execute("INSERT INTO cod_guard.schema_version (version) VALUES (1)")
    elif not 1 <= current[0] <= _VERSION:
        raise ValueError("Unsupported merchant schema version")
    previous = current[0] if current else 1
    if previous < 2 <= _VERSION:
        db.execute("SET LOCAL search_path TO cod_guard, pg_catalog")
        for statement in _INTEGRATION_SCHEMA:
            db.execute(statement)
        for table in _INTEGRATION_TABLES:
            _tenant_policy(db, table, f"tenant_id = {current_tenant}")
    if previous < 3 <= _VERSION:
        db.execute("SET LOCAL search_path TO cod_guard, pg_catalog")
        for statement in _PRIVACY_SCHEMA:
            db.execute(statement)
        for table in ("shopify_privacy_requests", "shopify_redacted_orders"):
            _tenant_policy(db, table, f"tenant_id = {current_tenant}")
    if previous < _VERSION:
        db.execute("UPDATE cod_guard.schema_version SET version = %s", (_VERSION,))
    db.execute(sql.SQL("GRANT USAGE ON SCHEMA cod_guard TO {}").format(role))
    db.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA cod_guard TO {}").format(role))
    db.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA cod_guard TO {}").format(role))
    db.execute(sql.SQL("REVOKE INSERT, UPDATE, DELETE ON cod_guard.schema_version FROM {}").format(role))


def import_pilot(db, path):
    """Copy a consistent, current SQLite backup into an unused merchant schema."""
    source = Path(path).resolve(strict=True)
    db.execute("SELECT pg_advisory_xact_lock(579032610055)")
    db.execute("SET LOCAL search_path TO pg_catalog, cod_guard")
    db.execute("LOCK TABLE merchant_accounts IN SHARE ROW EXCLUSIVE MODE")
    if (db.execute("SELECT 1 FROM merchant_accounts WHERE id <> 'demo'").fetchone()
            or db.execute("SELECT 1 FROM settings").fetchone()):
        raise ValueError("Pilot import requires a newly provisioned merchant database")
    counts = {}
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as pilot:
        pilot.row_factory = sqlite3.Row
        pilot.execute("BEGIN")
        if pilot.execute("PRAGMA user_version").fetchone()[0] != _SOURCE_VERSION:
            raise ValueError(f"Pilot backup must use schema version {_SOURCE_VERSION}")
        if pilot.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Pilot backup contains inconsistent references")
        tables = [table[1] for statement in _state_schema()
                  if (table := re.match(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", statement))]
        tenant_ids = {row[0] for table in tables if table in _SCOPED_TABLES
                      for row in pilot.execute(f"SELECT DISTINCT tenant_id FROM {table}")}
        for tenant_id in sorted(tenant_ids - {"demo"}):
            db.execute("INSERT INTO merchant_accounts (id, name) VALUES (%s, %s)", (tenant_id, tenant_id))
        db.execute("INSERT INTO settings VALUES ('pilot-import-complete')")
        for table in tables:
            cursor = pilot.execute(f"SELECT * FROM {table}")
            count = 0
            columns = [column[0] for column in cursor.description]
            statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns))
            for row in cursor:
                values = dict(row)
                tenant_id = values.get("tenant_id")
                if table == "whatsapp_unclear_receipts":
                    tenant_id = pilot.execute("SELECT tenant_id FROM whatsapp_verifications WHERE attempt_id=?",
                                              (values["attempt_id"],)).fetchone()[0]
                if tenant_id is not None:
                    db.execute("SELECT set_config('cod_guard.tenant_id', %s, true)", (tenant_id,))
                if table == "orders":
                    values = records.seal_order(TenantConnection(db), tenant_id, values["order_id"], values)
                elif table == "messages":
                    values["text"] = encrypt(values["text"], tenant_id, values["order_id"], "message.text")
                db.execute(statement, tuple(values.values()))
                count += 1
            counts[table] = count
            if table in _SERIAL_TABLES and count:
                last = pilot.execute(f"SELECT max(id) FROM {table}").fetchone()[0]
                db.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s)", (f"cod_guard.{table}", last))
    return counts


def assign_owner(db, tenant_id, email):
    """Map a verified email login to an imported merchant account."""
    from uuid import uuid4

    db.execute("SET LOCAL search_path TO pg_catalog, cod_guard")
    if tenant_id == "demo" or not db.execute("SELECT 1 FROM merchant_accounts WHERE id=%s", (tenant_id,)).fetchone():
        raise ValueError("Imported merchant account not found")
    user_id = db.execute("""INSERT INTO merchant_users (id, email_key) VALUES (%s, %s)
        ON CONFLICT (email_key) DO UPDATE SET email_key = EXCLUDED.email_key RETURNING id""",
                         (uuid4().hex, _private_lookup("address", email.casefold()))).fetchone()[0]
    db.execute("""INSERT INTO merchant_memberships VALUES (%s, %s, 'owner')
        ON CONFLICT (tenant_id, user_id) DO UPDATE SET role='owner'""", (tenant_id, user_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-role", required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--import-pilot", type=Path, metavar="SQLITE_BACKUP")
    actions.add_argument("--assign-owner", nargs=2, metavar=("TENANT", "EMAIL"))
    args = parser.parse_args()
    with psycopg.connect(os.environ["COD_GUARD_MIGRATION_DATABASE_URL"], connect_timeout=5) as db:
        migrate(db, args.runtime_role)
        if args.import_pilot:
            counts = import_pilot(db, args.import_pilot)
        if args.assign_owner:
            assign_owner(db, *args.assign_owner)
    print("Merchant schema is ready")
    if args.import_pilot:
        for table, count in counts.items():
            print(f"{table} {count}")


if __name__ == "__main__":
    main()
