"""Tenant-keyed SQLite records for the local demo and CSV shadow intake."""
import csv
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEMO_TENANT = "demo"
TRAFFIC_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "referring_site")
ORDER_FIELDS = (
    "order_id", "customer_name", "product", "city", "phone", "amount_pkr",
    "phone_valid", "phone_fraud_history", "phone_velocity_24h", "address_words",
    "address_has_landmark", "items_count", "order_hour", "is_repeat_customer",
    "customer_past_delivered", "customer_past_refusals", "label_failed", "data_source",
    *TRAFFIC_FIELDS,
)
SCHEMA = (
    """CREATE TABLE orders (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, customer_name TEXT NOT NULL,
        product TEXT NOT NULL, city TEXT NOT NULL, phone TEXT NOT NULL, amount_pkr REAL,
        phone_valid INTEGER, phone_fraud_history INTEGER, phone_velocity_24h INTEGER,
        address_words INTEGER, address_has_landmark INTEGER, items_count INTEGER,
        order_hour INTEGER, is_repeat_customer INTEGER, customer_past_delivered INTEGER,
        customer_past_refusals INTEGER, label_failed INTEGER, data_source TEXT NOT NULL,
        utm_source TEXT, utm_medium TEXT, utm_campaign TEXT, referring_site TEXT,
        PRIMARY KEY (tenant_id, order_id))""",
    """CREATE TABLE decisions (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, revision INTEGER NOT NULL,
        at TEXT, actor TEXT NOT NULL, decision TEXT NOT NULL, why TEXT, intent TEXT,
        zone TEXT, model_id TEXT, default_snapshot INTEGER NOT NULL DEFAULT 0,
        needs_review INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, order_id, revision))""",
    """CREATE TABLE outcomes (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, revision INTEGER NOT NULL,
        at TEXT, actor TEXT NOT NULL, outcome TEXT NOT NULL, correction INTEGER NOT NULL,
        decision_revision INTEGER, PRIMARY KEY (tenant_id, order_id, revision),
        FOREIGN KEY (tenant_id, order_id, decision_revision)
            REFERENCES decisions(tenant_id, order_id, revision))""",
    """CREATE TABLE messages (
        id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, order_id TEXT NOT NULL,
        text TEXT, source TEXT NOT NULL, intent TEXT, decision TEXT, why TEXT,
        at TEXT, actor TEXT NOT NULL, decision_revision INTEGER)""",
    "CREATE INDEX messages_by_order ON messages(tenant_id, order_id, id)",
    "CREATE INDEX messages_by_retention ON messages(at) WHERE text IS NOT NULL",
    """CREATE TABLE model_versions (
        tenant_id TEXT NOT NULL, model_id TEXT NOT NULL, trained_at TEXT,
        PRIMARY KEY (tenant_id, model_id))""",
    """CREATE TABLE model_feedback (
        tenant_id TEXT NOT NULL, model_id TEXT NOT NULL, order_id TEXT NOT NULL,
        outcome TEXT NOT NULL, PRIMARY KEY (tenant_id, model_id, order_id),
        FOREIGN KEY (tenant_id, model_id) REFERENCES model_versions(tenant_id, model_id))""",
    """CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, actor TEXT NOT NULL,
        action TEXT NOT NULL, order_id TEXT, at TEXT NOT NULL, reference TEXT)""",
    "CREATE INDEX audit_by_tenant ON audit_events(tenant_id, id)",
    """CREATE TABLE imports (
        tenant_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, digest TEXT NOT NULL,
        receipt TEXT NOT NULL, PRIMARY KEY (tenant_id, idempotency_key))""",
    "CREATE TABLE settings (key TEXT PRIMARY KEY)",
)
CONNECTOR_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS external_orders (
        tenant_id TEXT NOT NULL, channel TEXT NOT NULL, account TEXT NOT NULL,
        external_id TEXT NOT NULL, order_id TEXT NOT NULL,
        PRIMARY KEY (tenant_id, channel, account, external_id), UNIQUE (tenant_id, order_id),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id))""",
    """CREATE TABLE IF NOT EXISTS connector_state (
        tenant_id TEXT NOT NULL, channel TEXT NOT NULL, account TEXT NOT NULL,
        cursor TEXT, last_poll TEXT, last_webhook TEXT, last_error TEXT,
        PRIMARY KEY (tenant_id, channel, account))""",
    """CREATE TABLE IF NOT EXISTS storefront_order_status (
        tenant_id TEXT NOT NULL, channel TEXT NOT NULL, account TEXT NOT NULL, external_id TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT, conflict INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (tenant_id, channel, account, external_id))""",
)
WHATSAPP_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS whatsapp_consent (
        tenant_id TEXT NOT NULL, recipient TEXT NOT NULL, opted_in INTEGER NOT NULL,
        source TEXT NOT NULL, changed_at TEXT NOT NULL, PRIMARY KEY (tenant_id, recipient))""",
    """CREATE TABLE IF NOT EXISTS whatsapp_verifications (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, attempt_id TEXT NOT NULL UNIQUE,
        recipient TEXT NOT NULL, started_at TEXT NOT NULL, expires INTEGER NOT NULL,
        message_id TEXT UNIQUE, status TEXT NOT NULL, billable INTEGER, category TEXT,
        estimated_usd_micros INTEGER, replied_at TEXT, PRIMARY KEY (tenant_id, order_id),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id))""",
    """CREATE TABLE IF NOT EXISTS whatsapp_unclear_receipts (
        attempt_id TEXT NOT NULL, reply_key TEXT NOT NULL, PRIMARY KEY (attempt_id, reply_key),
        FOREIGN KEY (attempt_id) REFERENCES whatsapp_verifications(attempt_id) ON DELETE CASCADE)""",
)


COURIER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS courier_outcome_evidence (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, courier TEXT NOT NULL,
        tracking_number TEXT NOT NULL, outcome TEXT NOT NULL, source TEXT NOT NULL,
        recorded_at TEXT NOT NULL, billed_fee_paisa INTEGER,
        PRIMARY KEY (tenant_id, order_id), UNIQUE (tenant_id, courier, tracking_number),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id))""",
)


NETWORK_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS network_metadata (
        id INTEGER PRIMARY KEY CHECK (id=1), key_tag TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS network_sellers (tenant_id TEXT PRIMARY KEY)""",
    """CREATE TABLE IF NOT EXISTS network_consents (
        tenant_id TEXT NOT NULL, phone_key TEXT NOT NULL, expires INTEGER NOT NULL,
        evidence_reference TEXT NOT NULL, PRIMARY KEY (tenant_id, phone_key),
        FOREIGN KEY (tenant_id) REFERENCES network_sellers(tenant_id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS network_contributions (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, phone_key TEXT NOT NULL, outcome TEXT NOT NULL,
        expires INTEGER NOT NULL, PRIMARY KEY (tenant_id, order_id),
        FOREIGN KEY (tenant_id, phone_key) REFERENCES network_consents(tenant_id, phone_key) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id))""",
    "CREATE INDEX IF NOT EXISTS network_phone ON network_contributions(phone_key, tenant_id)",
    "CREATE TABLE IF NOT EXISTS network_suppressions (phone_key TEXT PRIMARY KEY)",
)
REPLY_CORRECTION_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS reply_corrections (
        id INTEGER PRIMARY KEY, tenant_id TEXT NOT NULL, message_id INTEGER NOT NULL,
        label TEXT NOT NULL CHECK(label IN ('CONFIRM','DENY','UNCLEAR','MODIFICATION')),
        language TEXT NOT NULL, decision_revision INTEGER NOT NULL,
        at TEXT NOT NULL, actor TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS corrections_by_tenant ON reply_corrections(tenant_id, id)",
    "CREATE INDEX IF NOT EXISTS corrections_by_message ON reply_corrections(message_id, id)",
    """CREATE TABLE IF NOT EXISTS reply_shadow_predictions (
        tenant_id TEXT NOT NULL, message_id INTEGER NOT NULL, model TEXT NOT NULL,
        label TEXT NOT NULL CHECK(label IN ('CONFIRM','DENY','UNCLEAR','MODIFICATION')),
        confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1), at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, model, message_id),
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS reply_shadows_by_message ON reply_shadow_predictions(tenant_id, message_id)",
)
DISPATCH_ADVICE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS address_findings (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, issues TEXT NOT NULL,
        PRIMARY KEY (tenant_id, order_id),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS address_clarifications (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, drafted_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, order_id),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id) ON DELETE CASCADE)""",
    """CREATE TABLE IF NOT EXISTS prepaid_offer_outcomes (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, discount_pct INTEGER NOT NULL,
        payment_method TEXT NOT NULL, sent_at TEXT NOT NULL, accepted_at TEXT, paid_at TEXT,
        PRIMARY KEY (tenant_id, order_id),
        FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, order_id) ON DELETE CASCADE)""",
)
RISK_SHADOW_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS risk_shadow_decisions (
        tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, revision INTEGER NOT NULL, advisory TEXT NOT NULL,
        PRIMARY KEY (tenant_id, order_id, revision),
        FOREIGN KEY (tenant_id, order_id, revision) REFERENCES decisions(tenant_id, order_id, revision))""",
)
STATE_SCHEMA_VERSION = 13


class StateUnavailable(RuntimeError):
    """The state store cannot be read or written."""


def now():
    return datetime.now(timezone.utc).isoformat()


def audit(connection, tenant_id, actor, action, *, order_id=None, reference=None):
    connection.execute("""INSERT INTO audit_events
        (tenant_id, actor, action, order_id, at, reference) VALUES (?, ?, ?, ?, ?, ?)""",
        (tenant_id, actor, action, order_id, now(), reference))


def insert_order(connection, tenant_id, order):
    fields = ", ".join(("tenant_id", *ORDER_FIELDS))
    parameters = ", ".join("?" for _ in range(len(ORDER_FIELDS) + 1))
    connection.execute(f"INSERT INTO orders ({fields}) VALUES ({parameters})",
                       (tenant_id, *(order.get(field) for field in ORDER_FIELDS)))
    if order.get("address_issues") is not None:
        store_address_finding(connection, tenant_id, order["order_id"], order["address_issues"])


def store_address_finding(connection, tenant_id, order_id, issues):
    if issues is None:
        connection.execute("DELETE FROM address_findings WHERE tenant_id=? AND order_id=?", (tenant_id, order_id))
    else:
        connection.execute("""INSERT INTO address_findings VALUES (?, ?, ?)
            ON CONFLICT(tenant_id, order_id) DO UPDATE SET issues=excluded.issues""",
                           (tenant_id, order_id, json.dumps(issues)))


def add_decision(connection, tenant_id, order_id, event):
    review = (event.get("intent") == "UNCLEAR" or (event.get("why") or "").startswith("Reply unclear;"))
    connection.execute("""INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       (tenant_id, order_id, event["revision"], event.get("at"), event["actor"],
                        event["decision"], event.get("why"), event.get("intent"), event.get("zone"),
                        event.get("model_id"), int(event.get("default_snapshot", False)),
                        int(event.get("needs_review", review))))


def add_outcome(connection, tenant_id, order_id, event):
    connection.execute("""INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                       (tenant_id, order_id, event["revision"], event.get("at"), event["actor"],
                        event["outcome"], int(event.get("correction", False)), event.get("decision_revision")))


def add_message(connection, tenant_id, order_id, message):
    connection.execute("""INSERT INTO messages
        (tenant_id, order_id, text, source, intent, decision, why, at, actor, decision_revision)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, order_id, message.get("text"), message.get("source", "text"),
         message.get("intent"), message.get("decision"), message.get("why"),
         message.get("at"), message.get("actor", "legacy"), message.get("decision_revision")))


def add_model_version(connection, tenant_id, training):
    connection.execute("INSERT OR IGNORE INTO model_versions VALUES (?, ?, ?)",
                       (tenant_id, training["model_id"], training.get("trained_at")))
    connection.executemany("INSERT OR IGNORE INTO model_feedback VALUES (?, ?, ?, ?)",
                           ((tenant_id, training["model_id"], order_id, outcome)
                            for order_id, outcome in training.get("feedback", {}).items()))


def _migrate_payload(connection, payload):
    if not isinstance(payload, dict):
        raise ValueError("State must be a JSON object")
    decisions, outcomes, snapshots, messages, events = (
        payload.get(field, {}) for field in ("decisions", "outcomes", "outcome_decisions", "messages", "events"))
    if any(not isinstance(field, dict) for field in (decisions, outcomes, snapshots, messages, events)):
        raise ValueError("Invalid legacy state field")

    for order_id in sorted(set(decisions) | set(outcomes) | set(events)):
        history = events.get(order_id, [])
        if history:
            for original in history:
                event = original.copy()
                if event["kind"] == "decision":
                    if (event["revision"] == snapshots.get(order_id, {}).get("revision")
                            and event["revision"] != decisions.get(order_id, {}).get("revision")
                            and event.get("intent") is None):
                        event["default_snapshot"] = True
                    add_decision(connection, DEMO_TENANT, order_id, event)
                elif event["kind"] == "outcome":
                    add_outcome(connection, DEMO_TENANT, order_id, event)
            if order_id in outcomes and not any(event["kind"] == "outcome" for event in history):
                add_outcome(connection, DEMO_TENANT, order_id,
                            {"revision": 0, "actor": "legacy", "outcome": outcomes[order_id]})
            continue

        if order_id in snapshots:
            add_decision(connection, DEMO_TENANT, order_id,
                         {**snapshots[order_id], "revision": 1, "actor": "legacy", "default_snapshot": True})
        if order_id in outcomes:
            add_outcome(connection, DEMO_TENANT, order_id,
                        {"revision": 2, "actor": "legacy", "outcome": outcomes[order_id],
                         "decision_revision": 1 if order_id in snapshots else None})
        if order_id in decisions:
            add_decision(connection, DEMO_TENANT, order_id,
                         {**decisions[order_id], "revision": 3, "actor": "legacy"})

    for order_id, history in messages.items():
        for message in history:
            add_message(connection, DEMO_TENANT, order_id, message)
    if payload.get("training"):
        add_model_version(connection, DEMO_TENANT, payload["training"])


def _initialize(connection, legacy):
    connection.execute("BEGIN IMMEDIATE")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == 0:
        sqlite_state = connection.execute("SELECT 1 FROM sqlite_master WHERE name='app_state'").fetchone()
        for statement in SCHEMA:
            connection.execute(statement)
        if sqlite_state:
            row = connection.execute("SELECT payload FROM app_state WHERE id=1").fetchone()
            if row is None:
                raise ValueError("Missing SQLite state payload")
            payload = json.loads(row[0])
            connection.execute("DROP TABLE app_state")
        elif legacy.is_file():
            payload = json.loads(legacy.read_text(encoding="utf-8"))
        else:
            payload = {}
        _migrate_payload(connection, payload)
        if legacy.is_file():
            connection.execute("INSERT INTO settings VALUES ('archive-legacy')")
    elif version == 1:
        connection.execute("ALTER TABLE decisions ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0")
        connection.execute("""UPDATE decisions SET needs_review=1 WHERE default_snapshot=0
                            AND (intent='UNCLEAR' OR why LIKE 'Reply unclear;%')""")
    if 4 <= version < 9:
        # Older Cloud records used the same source for a signed tap and typed text.
        connection.execute("""UPDATE messages SET source='whatsapp_legacy'
            WHERE source='whatsapp' AND ((text='Confirm' AND intent='CONFIRM') OR (text='Cancel' AND intent='DENY'))""")
    if 0 < version < 13:
        existing_cols = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
        if existing_cols:
            for column in TRAFFIC_FIELDS:
                if column not in existing_cols:
                    connection.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT")
    for statement in (*CONNECTOR_SCHEMA, *WHATSAPP_SCHEMA, *COURIER_SCHEMA, *NETWORK_SCHEMA,
                      *REPLY_CORRECTION_SCHEMA, *DISPATCH_ADVICE_SCHEMA, *RISK_SHADOW_SCHEMA):
        connection.execute(statement)
    connection.execute(f"PRAGMA user_version={STATE_SCHEMA_VERSION}")
    connection.commit()


@contextmanager
def connect(path):
    legacy = Path(path)
    try:
        legacy.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(legacy.with_suffix(".sqlite3"), timeout=15)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("PRAGMA journal_mode=WAL")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if 0 <= version < STATE_SCHEMA_VERSION:
                    _initialize(connection, legacy)
                elif version != STATE_SCHEMA_VERSION:
                    raise ValueError("Unsupported state schema version")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise StateUnavailable("State migration is unavailable") from exc
            if legacy.is_file() and connection.execute("SELECT 1 FROM settings WHERE key='archive-legacy'").fetchone():
                archive = legacy.with_name(legacy.name + ".archive")
                try:
                    if legacy.exists() and archive.exists():
                        raise StateUnavailable("Legacy archive path is already occupied")
                    legacy.rename(archive)
                except FileNotFoundError:
                    if not archive.is_file():
                        raise
            yield connection
    except (OSError, sqlite3.DatabaseError) as exc:
        raise StateUnavailable("State store is unavailable") from exc


@contextmanager
def write(path):
    with connect(path) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        yield connection


def ensure_seeded(path, seed_path):
    key = "demo-seed"
    with connect(path) as connection:
        if connection.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone():
            return
    with write(path) as connection:
        if connection.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone():
            return
        with Path(seed_path).open(encoding="utf-8", newline="") as source:
            for order in csv.DictReader(source):
                insert_order(connection, DEMO_TENANT, order)
        connection.execute("INSERT INTO settings VALUES (?)", (key,))


_QUEUE_ORDERS = """SELECT orders.*, COALESCE(source.status, 'open') AS queue_status,
    COALESCE(source.conflict, 0) AS storefront_conflict
    FROM orders LEFT JOIN external_orders USING (tenant_id, order_id)
    LEFT JOIN storefront_order_status AS source USING (tenant_id, channel, account, external_id)"""


def select_orders(connection, tenant_id, *, order_id=None):
    query = f"{_QUEUE_ORDERS} WHERE tenant_id=?"
    parameters = (tenant_id,)
    if order_id is not None:
        query += " AND order_id=?"
        parameters += (order_id,)
    return [dict(row) for row in connection.execute(query + " ORDER BY order_id", parameters)]


def select_page(connection, tenant_id, limit, offset, search):
    where = "tenant_id=?"
    params = (tenant_id,)
    if search:
        where += " AND instr(lower(order_id || ' ' || customer_name || ' ' || product || ' ' || city), ?) > 0"
        params += (search.casefold(),)
    total = connection.execute(f"SELECT COUNT(*) FROM orders WHERE {where}", params).fetchone()[0]
    rows = connection.execute(f"{_QUEUE_ORDERS} WHERE {where} ORDER BY order_id LIMIT ? OFFSET ?",
                              (*params, limit, offset))
    return [dict(row) for row in rows], total
