"""WooCommerce COD order intake and operator-triggered outcome write-back."""

import base64
import hmac
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from connector_orders import connection_state, ingest, linked_order, record_poll_error
from records import DEMO_TENANT, connect
from risk_engine import validate_features


CHANNEL = "WOOCOMMERCE"
MAX_BODY = 4 * 1024 * 1024
PAGE_SIZE = 50
MAX_PAGES = 20
_poll_lock = Lock()
_writeback_lock = Lock()
OUTCOMES = ("delivered", "returned", "refused")
STATUS_OPTIONS = ("completed", "cancelled", "on-hold")


class WooCommerceError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@dataclass(frozen=True)
class Store:
    account: str
    tenant_id: str
    url: str
    key: str = field(repr=False)
    secret: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    auth_mode: str = "basic"
    outcome_statuses: dict = field(default_factory=dict)

    @property
    def identity(self):
        return self.tenant_id, CHANNEL, self.account


@lru_cache(maxsize=1)
def _stores(raw):
    config = json.loads(raw)
    if not isinstance(config, dict):
        raise ValueError("Expected an object of WooCommerce stores")
    stores = {}
    for account, record in config.items():
        store = Store(account=account, **record)
        if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) for value in (account, store.tenant_id)):
            raise ValueError("Invalid store or tenant identifier")
        url = urlsplit(store.url)
        if (store.tenant_id == DEMO_TENANT or url.scheme != "https" or not url.hostname
                or url.username is not None or url.query or url.fragment or store.auth_mode not in ("basic", "query")):
            raise ValueError("WooCommerce requires HTTPS and a non-demo tenant")
        if not store.key or not store.secret or len(store.webhook_secret) < 24:
            raise ValueError("Missing WooCommerce credentials or a strong webhook secret")
        if any(secret == store.webhook_secret for secret in (item.webhook_secret for item in stores.values())):
            raise ValueError("Each WooCommerce store needs a distinct webhook secret")
        if not isinstance(store.outcome_statuses, dict) or any(
            outcome not in OUTCOMES or status not in STATUS_OPTIONS for outcome, status in store.outcome_statuses.items()
        ):
            raise ValueError("Invalid WooCommerce outcome status mapping")
        stores[account] = store
    return stores


def configured_stores():
    try:
        return _stores(os.environ.get("COD_GUARD_WOOCOMMERCE", "{}"))
    except (ValueError, TypeError, KeyError):
        raise WooCommerceError("WooCommerce configuration is invalid") from None


def signed_webhook(store, body, signature):
    expected = base64.b64encode(hmac.digest(store.webhook_secret.encode(), body, "sha256")).decode()
    return isinstance(signature, str) and signature.isascii() and hmac.compare_digest(expected, signature)


def parse_order(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a WooCommerce order")
    if (payload.get("payment_method") != "cod" or payload.get("currency") != "PKR"
            or payload.get("status") not in ("pending", "processing", "on-hold")):
        return None
    external_id = payload.get("id")
    if type(external_id) is not int or not 0 < external_id < 2**63:
        raise ValueError("Invalid WooCommerce order ID")
    billing = payload.get("billing") or {}
    shipping = payload.get("shipping") or {}
    items = payload.get("line_items") or []
    if not isinstance(billing, dict) or not isinstance(shipping, dict) or not isinstance(items, list):
        raise ValueError("Invalid WooCommerce order fields")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid WooCommerce line item")

    def text(value):
        return value.strip()[:200] if isinstance(value, str) else ""

    name = " ".join(filter(None, (text(billing.get("first_name")), text(billing.get("last_name")))))
    titles = ", ".join(filter(None, (text(item.get("name")) for item in items)))
    quantities = [item.get("quantity") for item in items]
    phone = text(billing.get("phone"))
    phone = phone if re.fullmatch(r"\+?[0-9][0-9 ()-]{2,39}", phone) else ""
    address = " ".join(text(shipping.get(key) or billing.get(key)) for key in ("address_1", "address_2"))
    risk = {}
    if payload.get("total") not in (None, ""):
        risk["amount_pkr"] = payload["total"]
    if address.strip():
        risk["address_words"] = len(address.split())
    if quantities and all(type(value) is int and 0 < value <= 100_000 for value in quantities):
        risk["items_count"] = sum(quantities)
    return str(external_id), {
        "customer_name": name[:200] or "Name unavailable", "product": titles[:200] or "Items unavailable",
        "phone": phone, "city": text(shipping.get("city") or billing.get("city"))[:100],
        **validate_features(risk),
    }


class WooCommerceClient:
    def __init__(self, store):
        self.store = store
        self.opener = build_opener(_NoRedirect())

    def request(self, route, *, method="GET", params=None, payload=None):
        query = dict(params or {})
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.store.auth_mode == "query":
            query.update(consumer_key=self.store.key, consumer_secret=self.store.secret)
        else:
            encoded = base64.b64encode(f"{self.store.key}:{self.store.secret}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        url = f"{self.store.url.rstrip('/')}/wp-json/wc/v3/{route}"
        if query:
            url += f"?{urlencode(query)}"
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                contents = response.read(MAX_BODY + 1)
                pages = response.headers.get("X-WP-TotalPages")
        except HTTPError as exc:
            exc.close()
            detail = {
                401: "Check REST key permissions and Authorization header forwarding",
                403: "Check REST key permissions and firewall rules",
                404: "Check WooCommerce wc/v3 and enable pretty permalinks",
            }.get(exc.code, f"Unexpected WooCommerce HTTP status {exc.code}")
            raise WooCommerceError(detail) from None
        except (URLError, OSError):
            raise WooCommerceError("Check WooCommerce HTTPS connectivity and the TLS certificate") from None
        if len(contents) > MAX_BODY:
            raise WooCommerceError("WooCommerce response exceeds its size limit")
        try:
            return json.loads(contents), (int(pages) if pages is not None else None)
        except (ValueError, RecursionError):
            raise WooCommerceError("WooCommerce returned invalid REST data") from None


def poll_once(path, store, *, clock=lambda: datetime.now(timezone.utc)):
    with _poll_lock:
        try:
            last_cursor = connection_state(path, store.identity)["cursor"]
            until = clock().replace(microsecond=0)
            start = datetime.fromisoformat(last_cursor) if last_cursor else until - timedelta(days=1)
            if start > until:
                raise WooCommerceError("Poll clock is behind the saved WooCommerce cursor")
            until = min(until, start + timedelta(days=1))
            after = start - timedelta(minutes=2)
            client = WooCommerceClient(store)
            added = 0
            for page in range(1, MAX_PAGES + 1):
                payload, total_pages = client.request("orders", params={
                    "modified_after": after.isoformat(), "modified_before": until.isoformat(),
                    "dates_are_gmt": "true", "orderby": "id", "order": "asc",
                    "per_page": PAGE_SIZE, "page": page,
                    "_fields": "id,status,payment_method,currency,billing.first_name,billing.last_name,"
                               "billing.phone,billing.city,billing.address_1,billing.address_2,shipping.city,"
                               "shipping.address_1,shipping.address_2,line_items.name,line_items.quantity,total",
                })
                if not isinstance(payload, list) or len(payload) > PAGE_SIZE:
                    raise WooCommerceError("WooCommerce returned an invalid order page")
                final = page >= total_pages if total_pages is not None else len(payload) < PAGE_SIZE
                parsed = [order for entry in payload if (order := parse_order(entry)) is not None]
                added += ingest(path, store.identity, parsed, "woocommerce-poll",
                                cursor=until.isoformat() if final else None)
                if final:
                    return {"imported": added, **connection_state(path, store.identity)}
            raise WooCommerceError("WooCommerce poll window exceeded the page limit; cursor unchanged")
        except (WooCommerceError, ValueError) as exc:
            message = str(exc) if isinstance(exc, WooCommerceError) else "Invalid WooCommerce order data"
            record_poll_error(path, store.identity, message)
            raise WooCommerceError(message) from None


def write_outcome(path, store, order_id):
    with _writeback_lock:
        external_id = linked_order(path, store.identity, order_id)
        if external_id is None:
            raise KeyError(order_id)
        with connect(path) as connection:
            event = connection.execute("""SELECT outcome, revision FROM outcomes WHERE tenant_id=? AND order_id=?
                ORDER BY revision DESC LIMIT 1""", (store.tenant_id, order_id)).fetchone()
        if event is None:
            raise ValueError("Record an outcome before sending it to WooCommerce")
        client = WooCommerceClient(store)
        route = f"orders/{external_id}"
        outcome = event["outcome"]
        if status := store.outcome_statuses.get(outcome):
            current, _ = client.request(route, params={"_fields": "status"})
            if not isinstance(current, dict) or not isinstance(current.get("status"), str):
                raise WooCommerceError("WooCommerce returned an invalid order status")
            if current["status"] != status:
                client.request(route, method="PUT", payload={"status": status})
            return {"mode": "status", "status": status}
        note = f"COD-Guard outcome: {outcome} (revision {event['revision']})."
        notes, _ = client.request(f"{route}/notes", params={"type": "internal"})
        if not isinstance(notes, list):
            raise WooCommerceError("WooCommerce returned invalid order notes")
        if not any(isinstance(existing, dict) and existing.get("note") == note for existing in notes):
            client.request(f"{route}/notes", method="POST", payload={"note": note, "customer_note": False})
        return {"mode": "private_note", "outcome": outcome}
