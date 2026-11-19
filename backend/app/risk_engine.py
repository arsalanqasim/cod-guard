"""COD-Guard risk engine: transparent rules layer.

Design rule (sir's FP/FN requirement): no single signal blocks an order
alone. Signals add points; the total maps to a zone:
  GREEN  ship it
  AMBER  verify with the customer first (WhatsApp agent / human)
  RED    hold — do not dispatch without a confirmation
Every flag carries a plain-words reason for the seller dashboard.
"""

def rule_score(order: dict) -> tuple[int, list[str]]:
    score, reasons = 0, []
    if order.get("phone_fraud_history", 0) >= 1:
        score += 35; reasons.append("This phone number was linked to a failed COD order before")
    if order.get("phone_velocity_24h", 0) >= 3:
        score += 20; reasons.append("Same phone placed many orders in 24 hours")
    elif order.get("phone_velocity_24h", 0) == 2:
        score += 10; reasons.append("Same phone placed 2 orders in 24 hours")
    if not order.get("phone_valid", 1):
        score += 25; reasons.append("Phone number looks invalid")
    if order.get("customer_past_refusals", 0) >= 2:
        score += 25; reasons.append("Customer refused 2+ deliveries before")
    elif order.get("customer_past_refusals", 0) == 1:
        score += 10; reasons.append("Customer refused a delivery before")
    if order.get("address_words", 10) < 5:
        score += 15; reasons.append("Address is very short / incomplete")
    if not order.get("address_has_landmark", 1):
        score += 5; reasons.append("No landmark in address")
    if order.get("amount_pkr", 0) > 20000:
        score += 10; reasons.append("High-value COD order (above PKR 20,000)")
    if 0 <= order.get("order_hour", 12) <= 4:
        score += 5; reasons.append("Order placed late at night (0–4 AM)")
    # Protective signals pull the score down: a known good customer is
    # not blocked by one weak signal (false-positive protection).
    if order.get("customer_past_delivered", 0) >= 3:
        score -= 20; reasons.append("Good history: 3+ successful deliveries (−20)")
    elif order.get("customer_past_delivered", 0) >= 1:
        score -= 10; reasons.append("Has a successful delivery before (−10)")
    return max(0, min(100, score)), reasons

def zone_for(score: int) -> str:
    if score >= 55:
        return "RED"
    if score >= 25:
        return "AMBER"
    return "GREEN"

def assess(order: dict) -> dict:
    score, reasons = rule_score(order)
    return {"risk_score": score, "zone": zone_for(score), "reasons": reasons}
