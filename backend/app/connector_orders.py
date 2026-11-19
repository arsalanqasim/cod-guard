"""Shared tenant-scoped external-order identity and connector health."""

import hashlib

from records import audit, connect, insert_order, now, write


def connection_state(path, identity):
    with connect(path) as connection:
        row = connection.execute("""SELECT cursor, last_poll, last_webhook, last_error FROM connector_state
            WHERE tenant_id=? AND channel=? AND account=?""", identity).fetchone()
    return dict(row) if row else dict.fromkeys(("cursor", "last_poll", "last_webhook", "last_error"))


def linked_order(path, identity, order_id):
    with connect(path) as connection:
        row = connection.execute("""SELECT external_id FROM external_orders
            WHERE tenant_id=? AND channel=? AND account=? AND order_id=?""", (*identity, order_id)).fetchone()
    return row["external_id"] if row else None


def _store_orders(connection, identity, orders, actor):
    tenant_id, channel, account = identity
    inserted = 0
    for external_id, order in orders:
        if connection.execute("""SELECT 1 FROM external_orders
            WHERE tenant_id=? AND channel=? AND account=? AND external_id=?""",
                              (*identity, external_id)).fetchone():
            continue
        digest = hashlib.sha256(f"{channel}:{account}:{external_id}".encode()).hexdigest()[:32]
        order_id = f"{channel.lower()}-{digest}"
        if connection.execute("SELECT 1 FROM orders WHERE tenant_id=? AND order_id=?",
                              (tenant_id, order_id)).fetchone():
            raise ValueError("External order ID collides with an imported order")
        insert_order(connection, tenant_id, {**order, "order_id": order_id, "data_source": channel})
        connection.execute("INSERT INTO external_orders VALUES (?, ?, ?, ?, ?)", (*identity, external_id, order_id))
        audit(connection, tenant_id, actor, "connector_order_intake", order_id=order_id, reference=channel)
        inserted += 1
    return inserted


def ingest(path, identity, orders, actor, *, cursor=None, webhook=False):
    with write(path) as connection:
        inserted = _store_orders(connection, identity, orders, actor)
        if webhook:
            connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, last_webhook)
                VALUES (?, ?, ?, ?) ON CONFLICT DO UPDATE SET last_webhook=excluded.last_webhook""",
                               (*identity, now()))
        elif cursor is not None:
            connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, cursor, last_poll)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT DO UPDATE SET cursor=excluded.cursor,
                last_poll=excluded.last_poll, last_error=NULL WHERE excluded.cursor >= connector_state.cursor
                OR connector_state.cursor IS NULL""", (*identity, cursor, now()))
        return inserted


def record_poll_error(path, identity, message):
    with write(path) as connection:
        connection.execute("""INSERT INTO connector_state (tenant_id, channel, account, last_error)
            VALUES (?, ?, ?, ?) ON CONFLICT DO UPDATE SET last_error=excluded.last_error""", (*identity, message))
