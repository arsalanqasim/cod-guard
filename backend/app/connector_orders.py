"""Shared tenant-scoped external-order identity and connector health."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from records import audit, connect, insert_order, now, open_order, seal_order, store_address_finding, write
from merchant_events import queue_order_event


OPEN = "open"
CANCELLED = "closed_cancelled"
NON_COD = "out_of_cod_scope"
CLOSED = "closed_at_source"
STATUS_RANK = {OPEN: 0, CLOSED: 1, NON_COD: 2, CANCELLED: 3}
SOURCE_FIELDS = ("customer_name", "product", "city", "phone", "amount_pkr", "address_words", "items_count", "utm_source", "utm_medium", "utm_campaign", "referring_site")


@dataclass(frozen=True)
class StorefrontSnapshot:
    external_id: str
    status: str
    updated_at: str | None
    details: dict | None = None


def source_timestamp(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid storefront timestamp")
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    try:
        return date.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except OverflowError as exc:
        raise ValueError("Invalid storefront timestamp") from exc


def connection_state(path, identity):
    with connect(path, tenant_id=identity[0]) as connection:
        row = connection.execute("""SELECT cursor, last_poll, last_webhook, last_error FROM connector_state
            WHERE tenant_id=? AND channel=? AND account=?""", identity).fetchone()
    return dict(row) if row else dict.fromkeys(("cursor", "last_poll", "last_webhook", "last_error"))


def linked_order(path, identity, order_id):
    with connect(path, tenant_id=identity[0]) as connection:
        row = connection.execute("""SELECT external_id FROM external_orders
            WHERE tenant_id=? AND channel=? AND account=? AND order_id=?""", (*identity, order_id)).fetchone()
    return row["external_id"] if row else None


def _record_status(db, identity, snapshot, *, previous_time=None, conflict=False):
    db.execute("""INSERT INTO storefront_order_status VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (tenant_id, channel, account, external_id) DO UPDATE SET status=excluded.status,
        updated_at=excluded.updated_at, conflict=excluded.conflict""",
               (*identity, snapshot.external_id, snapshot.status, snapshot.updated_at or previous_time, int(conflict)))


def _accept_snapshot(previous, snapshot):
    if previous is None:
        return True
    old_status, old_time = previous["status"], previous["updated_at"]
    new_time = snapshot.updated_at
    more_restrictive = STATUS_RANK[snapshot.status] > STATUS_RANK[old_status]
    if old_time and new_time:
        return new_time > old_time or (new_time == old_time and more_restrictive)
    if old_time is None and snapshot.status == old_status:
        return True
    return more_restrictive


def _reconcile(db, identity, order_id, previous, snapshot, actor):
    tenant_id, channel, _ = identity
    old_status = previous["status"] if previous else OPEN
    status_changed = snapshot.status != old_status
    changes = {}
    if snapshot.details is not None:
        current = db.execute("SELECT * FROM orders WHERE tenant_id=? AND order_id=?",
                             (tenant_id, order_id)).fetchone()
        current = open_order(db, current)
        changes = {key: snapshot.details.get(key) for key in SOURCE_FIELDS
                   if current[key] != snapshot.details.get(key)}
    conflict = bool(previous and previous["conflict"])
    if status_changed or changes:
        committed = db.execute("""SELECT EXISTS(SELECT 1 FROM decisions
            WHERE tenant_id=? AND order_id=? AND default_snapshot=0 AND intent IN ('CONFIRM', 'DENY'))
            OR EXISTS(SELECT 1 FROM outcomes WHERE tenant_id=? AND order_id=?)""",
                               (tenant_id, order_id, tenant_id, order_id)).fetchone()[0]
        if changes and not committed:
            assignments = ", ".join(f"{column}=?" for column in changes)
            changes = seal_order(db, tenant_id, order_id, changes)
            db.execute(f"UPDATE orders SET {assignments} WHERE tenant_id=? AND order_id=?",
                       (*changes.values(), tenant_id, order_id))
        reference = f"{channel}:{snapshot.status}"
        if status_changed or not (committed and conflict):
            audit(db, tenant_id, actor, "storefront_order_reconciled", order_id=order_id, reference=reference)
        if committed and (status_changed or not conflict):
            audit(db, tenant_id, actor, "storefront_dispatch_conflict", order_id=order_id, reference=reference)
        conflict = conflict or committed
    if snapshot.details is not None and "address_issues" in snapshot.details and not conflict:
        store_address_finding(db, tenant_id, order_id, snapshot.details["address_issues"])
    _record_status(db, identity, snapshot, previous_time=previous["updated_at"] if previous else None,
                   conflict=conflict)


def _store_orders(connection, identity, orders, actor):
    tenant_id, channel, account = identity
    inserted = 0
    for entry in orders:
        reconcile = isinstance(entry, StorefrontSnapshot)
        if reconcile:
            snapshot = entry
        else:
            # Reviewed social intake remains insert-only for a confirmation ID.
            external_id, details = entry
            snapshot = StorefrontSnapshot(external_id, OPEN, None, details)
        external_id = snapshot.external_id
        if channel == "SHOPIFY" and getattr(connection, "encrypted", False):
            redacted = connection.execute("""SELECT 1 FROM shopify_redacted_orders
                WHERE tenant_id=? AND shop=? AND external_id=?""", (tenant_id, account, external_id)).fetchone()
            if redacted:
                continue
        previous = None
        if reconcile:
            previous = connection.execute("""SELECT status, updated_at, conflict FROM storefront_order_status
                WHERE tenant_id=? AND channel=? AND account=? AND external_id=?""",
                                          (*identity, external_id)).fetchone()
        if not _accept_snapshot(previous, snapshot):
            continue
        linked = connection.execute("""SELECT order_id FROM external_orders
            WHERE tenant_id=? AND channel=? AND account=? AND external_id=?""",
                                    (*identity, external_id)).fetchone()
        if linked:
            if reconcile:
                _reconcile(connection, identity, linked["order_id"], previous, snapshot, actor)
            continue
        if snapshot.status != OPEN:
            if snapshot.updated_at is not None:
                # An older creation event can arrive after an authoritative closure.
                _record_status(connection, identity, snapshot)
            continue
        digest = hashlib.sha256(f"{channel}:{account}:{external_id}".encode()).hexdigest()[:32]
        order_id = f"{channel.lower()}-{digest}"
        if connection.execute("SELECT 1 FROM orders WHERE tenant_id=? AND order_id=?",
                              (tenant_id, order_id)).fetchone():
            raise ValueError("External order ID collides with an imported order")
        insert_order(connection, tenant_id, {**snapshot.details, "order_id": order_id, "data_source": channel})
        connection.execute("INSERT INTO external_orders VALUES (?, ?, ?, ?, ?)", (*identity, external_id, order_id))
        if reconcile:
            _record_status(connection, identity, snapshot)
        audit(connection, tenant_id, actor, "connector_order_intake", order_id=order_id, reference=channel)
        if getattr(connection, "encrypted", False) and channel in ("SHOPIFY", "WOOCOMMERCE"):
            queue_order_event(connection, tenant_id, order_id, "order.accepted", {"revision": 0})
        inserted += 1
    return inserted


def ingest(path, identity, orders, actor, *, cursor=None, webhook=False):
    with write(path, tenant_id=identity[0]) as connection:
        inserted = _store_orders(connection, identity, orders, actor)
        if webhook:
            connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, last_webhook)
                VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, channel, account)
                DO UPDATE SET last_webhook=excluded.last_webhook""",
                               (*identity, now()))
        elif cursor is not None:
            connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, cursor, last_poll)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT (tenant_id, channel, account) DO UPDATE SET cursor=excluded.cursor,
                last_poll=excluded.last_poll, last_error=NULL WHERE excluded.cursor >= connector_state.cursor
                OR connector_state.cursor IS NULL""", (*identity, cursor, now()))
        return inserted


def record_poll_error(path, identity, message):
    with write(path, tenant_id=identity[0]) as connection:
        connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, last_error)
            VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, channel, account)
            DO UPDATE SET last_error=excluded.last_error""", (*identity, message))
