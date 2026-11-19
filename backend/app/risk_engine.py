"""One dispatch policy shared by serving and offline evaluation.

Two independent adverse signals are required before requesting verification
or holding an order. ML probability is evidence, not a second signal. The
two address measurements count together as one signal.
"""
import math

DEFAULTS = {"phone_fraud_history": 0, "phone_velocity_24h": 0, "phone_valid": 1,
            "customer_past_refusals": 0, "address_words": 10,
            "address_has_landmark": 1, "amount_pkr": 0, "order_hour": 12,
            "customer_past_delivered": 0}


def _values(order):
    values = {}
    for key, default in DEFAULTS.items():
        try:
            value = float(order.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a finite non-negative number") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a finite non-negative number")
        if key != "amount_pkr" and not value.is_integer():
            raise ValueError(f"{key} must be an integer")
        if key in ("phone_valid", "address_has_landmark") and value not in (0, 1):
            raise ValueError(f"{key} must be 0 or 1")
        if key == "order_hour" and value > 23:
            raise ValueError("order_hour must be between 0 and 23")
        values[key] = value
    return values


def _signals(order):
    o = _values(order)
    signals = []

    def add(group, points, reason):
        signals.append({"signal": group, "points": points, "reason": reason})

    if o["phone_fraud_history"] >= 1:
        add("fraud_history", 35, "Phone linked to a previous failed COD order")
    if o["phone_velocity_24h"] >= 3:
        add("velocity", 20, "Same phone placed 3+ orders in 24 hours")
    elif o["phone_velocity_24h"] == 2:
        add("velocity", 10, "Same phone placed 2 orders in 24 hours")
    if not o["phone_valid"]:
        add("phone_format", 25, "Phone number looks invalid")
    if o["customer_past_refusals"] >= 2:
        add("refusal_history", 25, "Customer refused 2+ deliveries before")
    elif o["customer_past_refusals"] == 1:
        add("refusal_history", 10, "Customer refused a delivery before")
    if o["address_words"] < 5:
        add("address", 15, "Address is very short / incomplete")
    if not o["address_has_landmark"]:
        add("address", 5, "Address has no landmark")
    if o["amount_pkr"] > 20000:
        add("amount", 10, "COD value exceeds PKR 20,000")
    if o["order_hour"] <= 4:
        add("time", 5, "Order placed at 0–4 AM")
    if o["customer_past_delivered"] >= 3:
        add("good_history", -20, "3+ successful deliveries reduce risk by 20 points")
    elif o["customer_past_delivered"] >= 1:
        add("good_history", -10, "A successful delivery reduces risk by 10 points")
    return signals


def rule_score(order: dict) -> tuple[int, list[str]]:
    signals = _signals(order)
    return max(0, min(100, sum(s["points"] for s in signals))), [s["reason"] for s in signals]


def zone_for(score: int) -> str:
    return "RED" if score >= 55 else "AMBER" if score >= 25 else "GREEN"


def assess(order: dict, ml_probability=None, threshold=0.60) -> dict:
    signals = _signals(order)
    score = max(0, min(100, sum(s["points"] for s in signals)))
    count = len({s["signal"] for s in signals if s["points"] > 0})
    zone = zone_for(score)
    reasons = [s["reason"] for s in signals]
    if ml_probability is not None:
        if not math.isfinite(ml_probability) or not 0 <= ml_probability <= 1:
            raise ValueError("ML probability must be finite and between 0 and 1")
        if not 0 < threshold < 1:
            raise ValueError("ML threshold must be between 0 and 1")
        if ml_probability >= threshold:
            zone = "RED" if zone == "RED" or ml_probability >= max(0.80, threshold) else "AMBER"
            reasons.append(f"Model estimates {ml_probability:.0%} failure risk (threshold {threshold:.0%})")
    if count < 2:
        zone = "GREEN"
        if count:
            reasons.append("One adverse signal alone cannot stop dispatch; confirmation is still available")
    return {"risk_score": score, "zone": zone, "reasons": reasons,
            "signal_count": count, "signals": signals}
