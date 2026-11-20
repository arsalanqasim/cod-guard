"""Opt-in seller artifacts and durable model-first decision previews."""
import json
import logging
import os
import pickle
import re
from functools import lru_cache
from math import isfinite
from pathlib import Path

import pandas as pd

from records import DEMO_TENANT, select_orders
from risk_candidate import Bands, CalibratedRisk, FEATURES, decide

LOGGER = logging.getLogger(__name__)
SOURCE = "[SELLER]"


@lru_cache(maxsize=8)
def _config(raw):
    try:
        values = json.loads(raw)
    except ValueError:
        return {}
    return values if isinstance(values, dict) else {}


@lru_cache(maxsize=8)
def _load(path, version, size):
    with path.open("rb") as source:
        artifact = pickle.load(source)
    if (artifact["version"] != 1 or artifact["source"] != SOURCE
            or not re.fullmatch(r"seller-r9-[0-9a-f]{16}", artifact["model_id"])
            or not isinstance(artifact["estimator"], CalibratedRisk)
            or tuple(artifact["estimator"].model.feature_names_in_) != FEATURES
            or artifact["estimator"].method not in ("platt", "isotonic")):
        raise ValueError("Unsupported seller shadow artifact")
    return artifact, Bands(**artifact["bands"])


def configuration(tenant):
    if tenant == DEMO_TENANT or os.environ.get("COD_GUARD_EXHIBITION") == "1":
        return None
    config = _config(os.environ.get("COD_GUARD_RISK_SHADOW", "{}")).get(tenant)
    if not isinstance(config, dict):
        return None
    try:
        path = Path(config["artifact"])
        if not path.is_absolute():
            raise ValueError("Expected an absolute trusted artifact path")
        stat = path.stat()
        artifact, bands = _load(path, stat.st_mtime_ns, stat.st_size)
        if artifact["tenant"] != tenant:
            return None
        if "bands" in config:
            bands = Bands(**config["bands"])
    except (AttributeError, EOFError, ImportError, KeyError, OSError, TypeError, ValueError, pickle.PickleError):
        LOGGER.warning("Seller risk shadow configuration is unavailable")
        return None
    return artifact, bands


def _values(order):
    try:
        values = [float(order[key]) for key in FEATURES]
    except (KeyError, TypeError, ValueError):
        return None
    if (not all(isfinite(value) for value in values) or values[0] < 0
            or values[1] < 1 or not values[1].is_integer() or values[2] not in (0, 1)):
        return None
    return values


def project(config, orders, intents):
    artifact, bands = config
    estimator = artifact["estimator"]
    rows = [_values(order) for order in orders]
    observed = [values for values in rows if values is not None]
    if observed:
        probabilities = estimator.predict(pd.DataFrame(observed, columns=FEATURES))
        if len(probabilities) != len(observed) or any(not 0 <= p <= 1 for p in probabilities):
            raise ValueError("Invalid calibrated probability")
        scores = iter(probabilities)
    else:
        scores = iter(())
    items = []
    for order, intent, values in zip(orders, intents, rows):
        probability = float(next(scores)) if values is not None else None
        output = decide(probability, bands, intent=intent, phone_valid=order.get("phone_valid"),
                        queue_status=order.get("queue_status", "open"))
        items.append({"mode": "shadow", "source": SOURCE, "model_id": artifact["model_id"],
                      "thresholds": {"verify_at": bands.verify_at, "hold_at": bands.hold_at},
                      "contributors": estimator.explain(values) if values is not None else [], **output})
    return items


def predictions(config, orders, intents):
    try:
        return project(config, orders, intents)
    except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError):
        LOGGER.warning("Seller risk shadow inference is unavailable")
        return [None] * len(orders)


def record(db, tenant, order_id, event):
    config = configuration(tenant)
    if config is None:
        return
    orders = select_orders(db, tenant, order_id=order_id)
    if not orders:
        return
    advisory, = predictions(config, orders, [event.get("intent")])
    if advisory is not None:
        db.execute("INSERT INTO risk_shadow_decisions VALUES (?,?,?,?)",
                   (tenant, order_id, event["revision"], json.dumps(advisory)))


def history(db, tenant, order_id, after):
    return [{"revision": row["revision"], "recorded_decision": row["decision"], "at": row["at"],
             "actor": row["actor"], **json.loads(row["advisory"])}
            for row in db.execute("""SELECT r.revision, d.decision, d.at, d.actor, r.advisory
                FROM risk_shadow_decisions AS r JOIN decisions AS d USING (tenant_id, order_id, revision)
                WHERE r.tenant_id=? AND r.order_id=? AND r.revision>?
                ORDER BY r.revision LIMIT 100""", (tenant, order_id, after))]
