"""Tenant-scoped prepaid, courier and address guidance without dispatch authority."""
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from address_quality import CLARIFICATION, REASONS, city_key
import next_action as next_actions
from records import audit, now

PAYMENT_METHODS = ("JazzCash", "Easypaisa")
OFFER_STAGES = ("sent", "accepted", "paid")
PRIOR_ORDERS = 20
MIN_CITY_ORDERS = 5


@dataclass(frozen=True)
class Settings:
    prepaid: tuple[int, str] | None = None
    courier_choice: bool = False
    address_quality: bool = False
    next_action: next_actions.Policy | None = None


@lru_cache(maxsize=8)
def _configured(raw, tenant):
    try:
        tenants = json.loads(raw)
    except ValueError:
        return Settings()
    config = tenants.get(tenant) if isinstance(tenants, dict) else None
    if not isinstance(config, dict):
        return Settings()
    offer = config.get("prepaid")
    if isinstance(offer, dict):
        percent, method = offer.get("discount_pct"), offer.get("payment_method")
        if type(percent) is int and 1 <= percent <= 99 and method in PAYMENT_METHODS:
            prepaid = (percent, method)
        else:
            prepaid = None
    else:
        prepaid = None
    return Settings(prepaid, config.get("courier_choice") is True, config.get("address_quality") is True,
                    next_actions.policy(config.get("next_action")))


def settings(tenant_id):
    if os.environ.get("COD_GUARD_EXHIBITION") == "1":
        return Settings()
    return _configured(os.environ.get("COD_GUARD_DISPATCH_EXPERIMENTS", "{}"), tenant_id)


def prepaid_offer(assessment, offer):
    if not offer or assessment["zone"] != "AMBER" or assessment["decision"] != "VERIFY_FIRST":
        return None
    if assessment["queue_status"] != "open":
        return None
    percent, method = offer
    return {"mode": "shadow", "discount_pct": percent, "payment_method": method,
            "text": f"Switch to prepaid via {method} for {percent}% off this order."}


def _records(db, table, tenant, order_ids, *columns):
    if not order_ids:
        return {}
    names = ", ".join(("order_id", *columns))
    slots = ", ".join("?" for _ in order_ids)
    return {row["order_id"]: {col: row[col] for col in columns}
            for row in db.execute(f"SELECT {names} FROM {table} WHERE tenant_id=? AND order_id IN ({slots})",
                                  (tenant, *order_ids))}


def courier_history(db, tenant):
    return db.execute("""SELECT o.city, e.courier, COUNT(*) AS n,
        SUM(COALESCE((SELECT terminal.outcome FROM outcomes AS terminal
            WHERE terminal.tenant_id=e.tenant_id AND terminal.order_id=e.order_id
            ORDER BY terminal.revision DESC LIMIT 1), e.outcome)='returned') AS returns
        FROM courier_outcome_evidence AS e JOIN orders AS o USING (tenant_id, order_id)
        WHERE e.tenant_id=? GROUP BY o.city, e.courier""", (tenant,)).fetchall()


def courier_rates(history):
    total, returned = 0, 0
    groups = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for row in history:
        count, failures = row["n"], row["returns"]
        total += count
        returned += failures
        if city_key(row["city"]) and row["courier"] != "other":
            cohort = groups[city_key(row["city"])][row["courier"]]
            cohort[0] += count
            cohort[1] += failures
    if not total:
        return {}
    prior = returned / total
    return {city: sorted(({"courier": courier, "n": n, "returned": failures,
                           "raw_return_rate": failures / n,
                           "return_rate": (failures + PRIOR_ORDERS * prior) / (n + PRIOR_ORDERS)}
                          for courier, (n, failures) in values.items() if n >= MIN_CITY_ORDERS),
                         key=lambda row: (row["return_rate"], -row["n"], row["courier"]))
            for city, values in groups.items()}


def recommend_courier(rates, city):
    evidence = rates.get(city_key(city), [])
    if len(evidence) < 2 or evidence[0]["return_rate"] == evidence[1]["return_rate"]:
        return None
    return {"mode": "shadow", "courier": evidence[0]["courier"], "evidence": evidence,
            "prior_orders": PRIOR_ORDERS}


def queue_context(db, tenant, orders, config):
    order_ids = tuple(order["order_id"] for order in orders)
    contacts = {}
    if config.next_action and orders:
        from whatsapp_cloud import advice_contacts

        contacts = advice_contacts(db, tenant, orders)
    return {
        "rates": courier_rates(courier_history(db, tenant)) if config.courier_choice and order_ids else {},
        "offers": _records(db, "prepaid_offer_outcomes", tenant, order_ids, "discount_pct", "payment_method",
                           "sent_at", "accepted_at", "paid_at") if config.prepaid else {},
        "findings": _records(db, "address_findings", tenant, order_ids, "issues")
        if config.address_quality or config.next_action else {},
        "drafts": _records(db, "address_clarifications", tenant, order_ids, "drafted_at")
        if config.address_quality else {},
        "contacts": contacts,
        "at": datetime.now(timezone.utc),
    }


def annotate(order, assessment, context, config):
    order_id = order["order_id"]
    result = {}
    if config.prepaid:
        result["prepaid_offer"] = prepaid_offer(assessment, config.prepaid)
        result["prepaid_outcome"] = context["offers"].get(order_id)
    if config.courier_choice:
        result["courier_recommendation"] = (
            recommend_courier(context["rates"], order["city"])
            if assessment["decision"] == "SHIP" and assessment["queue_status"] == "open" else None)
    finding = context["findings"].get(order_id)
    issues = json.loads(finding["issues"]) if finding else None
    if config.address_quality:
        result["address_quality"] = {"status": ("flagged" if issues else "clear") if finding else "unavailable",
                                     "reasons": [REASONS[reason] for reason in issues or ()],
                                     "clarification": CLARIFICATION if order_id in context["drafts"] and issues else None}
    if config.next_action:
        result["next_action"] = next_actions.recommend(order, assessment, issues, context["contacts"].get(order_id, {}),
                                                       config.next_action, at=context["at"])
    return result


def draft_address_clarification(db, tenant, actor, assessment, advice):
    if (advice.get("address_quality", {}).get("status") != "flagged"
            or assessment["queue_status"] != "open"):
        return None
    order_id = assessment["order_id"]
    created = db.execute("""INSERT INTO address_clarifications VALUES (?, ?, ?)
        ON CONFLICT DO NOTHING""", (tenant, order_id, now())).rowcount == 1
    if created:
        audit(db, tenant, actor, "address_clarification_drafted", order_id=order_id)
    return {"text": CLARIFICATION, "created": created}


def record_offer(db, tenant, actor, assessment, stage, config):
    if stage not in OFFER_STAGES or not config.prepaid:
        raise ValueError("Prepaid evidence is unavailable for this tenant")
    order_id = assessment["order_id"]
    row = _records(db, "prepaid_offer_outcomes", tenant, (order_id,), "discount_pct", "payment_method",
                   "sent_at", "accepted_at", "paid_at").get(order_id)
    field = f"{stage}_at"
    if row and row[field]:
        return row
    now_at = now()
    if stage == "sent":
        if not prepaid_offer(assessment, config.prepaid):
            raise ValueError("Only an eligible open AMBER order in verification can record a new offer")
        db.execute("INSERT INTO prepaid_offer_outcomes VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                   (tenant, order_id, *config.prepaid, now_at))
        row = {"discount_pct": config.prepaid[0], "payment_method": config.prepaid[1],
               "sent_at": now_at, "accepted_at": None, "paid_at": None}
    else:
        preceding = f"{OFFER_STAGES[OFFER_STAGES.index(stage) - 1]}_at"
        if not row or not row[preceding]:
            raise ValueError(f"Record {preceding.removesuffix('_at')} before {stage}")
        db.execute(f"UPDATE prepaid_offer_outcomes SET {field}=? WHERE tenant_id=? AND order_id=?",
                   (now_at, tenant, order_id))
        row[field] = now_at
    audit(db, tenant, actor, f"prepaid_offer_{stage}", order_id=order_id)
    return row
