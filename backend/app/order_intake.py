"""Validated, idempotent CSV intake for shadow orders."""
import csv
import hashlib
import io
import json
import re

from address_quality import classify_address
from records import audit, insert_order, write
from risk_engine import validate_features

ORDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
REQUIRED = {"order_id", "customer_name", "product", "phone"}
FEATURES = frozenset(("phone_valid", "phone_fraud_history", "phone_velocity_24h",
                      "address_words", "address_has_landmark", "amount_pkr", "items_count",
                      "order_hour", "is_repeat_customer", "customer_past_delivered",
                      "customer_past_refusals"))
MAX_CSV_BYTES = 1024 * 1024
MAX_ROWS = 2000


class IdempotencyConflict(ValueError):
    pass


def _parse(contents):
    try:
        source = io.StringIO(contents.decode("utf-8-sig"), newline="")
        reader = csv.DictReader(source, strict=True)
        fields = reader.fieldnames or []
        if len(set(fields)) != len(fields) or REQUIRED - set(fields) or set(fields) - (REQUIRED | FEATURES | {"city", "address"}):
            raise ValueError("CSV header must contain order_id, customer_name, product and phone, with optional risk features")
        rows, errors = [], []
        for index, row in enumerate(reader, start=2):
            if index > MAX_ROWS + 1:
                raise ValueError(f"CSV may contain at most {MAX_ROWS} data rows")
            try:
                if None in row or None in row.values():
                    raise ValueError("Row does not match the CSV header")
                row = {field: value.strip() for field, value in row.items()}
                if not ORDER_ID.fullmatch(row["order_id"]):
                    raise ValueError("Invalid order ID")
                if not all(0 < len(row[field]) <= 200 for field in ("customer_name", "product")):
                    raise ValueError("Customer name and product must each be 1–200 characters")
                if not re.fullmatch(r"\+?[0-9][0-9 ()-]{2,39}", row["phone"]):
                    raise ValueError("Invalid phone format")
                city = row.get("city", "")
                if len(city) > 100:
                    raise ValueError("City must be at most 100 characters")
                if len(row.get("address", "")) > 500:
                    raise ValueError("Address must be at most 500 characters")
                values = validate_features({key: row[key] for key in FEATURES if row.get(key)})
                rows.append((index, {**{key: row[key] for key in REQUIRED}, **values,
                                     "city": city, "data_source": "SHADOW",
                                     "address_issues": classify_address(row.get("address"), city)}))
            except ValueError as exc:
                errors.append({"row": index, "error": str(exc)})
        return rows, errors
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("Upload a valid UTF-8 CSV file") from exc


def import_orders(path, tenant_id, actor, key, contents, *, source="SHADOW"):
    digest = hashlib.sha256(contents).hexdigest()
    rows, errors = _parse(contents)
    with write(path) as connection:
        existing = connection.execute("SELECT digest, receipt FROM imports WHERE tenant_id=? AND idempotency_key=?",
                                      (tenant_id, key)).fetchone()
        if existing:
            if existing["digest"] != digest:
                raise IdempotencyConflict("Idempotency key was already used for different content")
            audit(connection, tenant_id, actor, "import_replayed", reference=key)
            return json.loads(existing["receipt"])
        inserted = 0
        for index, row in rows:
            if connection.execute("SELECT 1 FROM orders WHERE tenant_id=? AND order_id=?",
                                  (tenant_id, row["order_id"])).fetchone():
                errors.append({"row": index, "error": "Order ID already exists"})
                continue
            insert_order(connection, tenant_id, {**row, "data_source": source})
            inserted += 1
        receipt = {"imported": inserted, "errors": sorted(errors, key=lambda error: error["row"])}
        connection.execute("INSERT INTO imports VALUES (?, ?, ?, ?)",
                           (tenant_id, key, digest, json.dumps(receipt)))
        audit(connection, tenant_id, actor, "import", reference=key)
        return receipt
