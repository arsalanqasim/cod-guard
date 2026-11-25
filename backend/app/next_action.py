"""Explain the next seller action using order and contact evidence."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from address_quality import CLARIFICATION, REASONS, normalized
from pakistan_phone import normalize_phone


PKT = timezone(timedelta(hours=5))
PAISA = Decimal("0.01")


@dataclass(frozen=True)
class Advance:
    delivery_fee_pkr: int
    percent: int
    minimum_order_pkr: int
    made_to_order_products: frozenset[str]
    minimum_prior_refusals: int | None


@dataclass(frozen=True)
class Policy:
    call_after_minutes: int = 60
    call_minimum_order_pkr: int = 3500
    pickup_cutoff_pkt: time | None = None
    advance: Advance | None = None


def _integer(config, key, default, low, high):
    value = config.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(key)
    return value


def _advance_policy(raw):
    if not isinstance(raw, dict):
        return None
    products = raw.get("made_to_order_products", [])
    if not isinstance(products, list) or any(not isinstance(item, str) or not item.strip() for item in products):
        return None
    try:
        return Advance(
            _integer(raw, "delivery_fee_pkr", None, 1, 100_000),
            _integer(raw, "percent", 50, 1, 100),
            _integer(raw, "minimum_order_pkr", 3500, 1, 10_000_000),
            frozenset(normalized(item) for item in products),
            _integer(raw, "minimum_prior_refusals", None, 2, 100)
            if "minimum_prior_refusals" in raw else None,
        )
    except ValueError:
        return None


def policy(raw):
    if not isinstance(raw, dict):
        return None
    try:
        cutoff = (datetime.strptime(raw["pickup_cutoff_pkt"], "%H:%M").time()
                  if "pickup_cutoff_pkt" in raw else None)
        return Policy(_integer(raw, "call_after_minutes", 60, 1, 1440),
                      _integer(raw, "call_minimum_order_pkr", 3500, 1, 10_000_000),
                      cutoff, _advance_policy(raw.get("advance")))
    except (TypeError, ValueError):
        return None


def _action(code, title, reason, next_step, fallback, **details):
    return {"action": code, "title": title, "reason": reason, "next_step": next_step,
            "fallback": fallback, **details}


def _advance_action(order, config):
    if config is None or not (0 < (order.get("amount_pkr") or 0) <= 10_000_000):
        return None
    total = Decimal(str(order["amount_pkr"])).quantize(PAISA, rounding=ROUND_HALF_UP)
    amount = (Decimal(config.delivery_fee_pkr) * config.percent / 100).quantize(PAISA, rounding=ROUND_HALF_UP)
    if total < max(config.minimum_order_pkr, config.delivery_fee_pkr) or total <= amount:
        return None
    if normalized(order.get("product")) in config.made_to_order_products:
        reason = "The buyer confirmed a product your store marks as made to order."
    elif (config.minimum_prior_refusals is not None
          and (order.get("customer_past_refusals") or 0) >= config.minimum_prior_refusals):
        reason = "The order meets your store’s advance policy for recorded buyer refusals."
    else:
        return None
    return _action("offer_advance", "Offer a credited advance", reason,
                   "Show the buyer the split and refund terms. Verify receipt with your payment provider before packing.",
                   "Offer pickup or another payment option if your store supports it.",
                   advance={"amount_pkr": str(amount), "remaining_cod_pkr": str(total - amount),
                            "order_total_pkr": str(total)})


def _contact_action(order, contact, config, at):
    status = contact.get("status")
    if contact.get("opted_in") is False:
        return _action("review_contact", "Review contact options", "The buyer opted out of WhatsApp order messages.",
                       "Check whether an approved callback channel is available.",
                       "Leave the order for staff review if the buyer cannot be reached.")
    if not status:
        return _action("confirm_whatsapp", "Ask for WhatsApp confirmation", "This order has no recorded buyer confirmation.",
                       "Send the approved confirmation once the buyer’s WhatsApp consent is recorded.",
                       "Review before pickup if the buyer has not replied.")
    expired = "expires" in contact and at.timestamp() >= contact["expires"]
    if status == "failed" or expired:
        reason = ("The WhatsApp confirmation failed to deliver." if status == "failed"
                  else "The WhatsApp reply window ended without a confirmation.")
        ready_for_call = True
    else:
        reason = "The WhatsApp confirmation is still awaiting a reply."
        elapsed = at - datetime.fromisoformat(contact["started_at"])
        ready_for_call = status in ("delivered", "read") and elapsed >= timedelta(minutes=config.call_after_minutes)
        if ready_for_call:
            reason = "WhatsApp shows delivery and the time since submission exceeds your store’s waiting period."
    local = at.astimezone(PKT)
    if config.pickup_cutoff_pkt and local.time() >= config.pickup_cutoff_pkt:
        return _action("next_pickup", "Review for the next pickup", "Today’s configured pickup cutoff has passed.",
                       "Confirm the order before the next dispatch window.",
                       "Ask whether the buyer wants to keep the order if the delay changes their plans.")
    if ready_for_call and (order.get("amount_pkr") or 0) >= config.call_minimum_order_pkr:
        deadline = config.pickup_cutoff_pkt.strftime("%H:%M PKT") if config.pickup_cutoff_pkt else None
        return _action("call_buyer", "Call the buyer", reason,
                       "Make one approved callback to confirm the order and delivery details.",
                       "If unanswered, review the order for the next dispatch window.", deadline=deadline)
    if status == "failed" or expired:
        return _action("review_contact", "Review contact options", reason,
                       "Check the number or another approved way to reach the buyer.",
                       "Leave the order for staff review if the buyer cannot be reached.")
    return _action("wait_for_reply", "Wait for a reply", reason,
                   "Allow the current WhatsApp attempt to resolve.",
                   "Review the order before pickup if the buyer still has not replied.")


def recommend(order, assessment, address_issues, contact, config, *, at):
    if assessment.get("storefront_conflict"):
        return _action("review_order", "Review the storefront change", "The source order changed after a recorded decision.",
                       "Reconcile the latest order in the storefront before taking any dispatch action.",
                       "Keep it in staff review until the conflict is resolved.")
    if assessment["queue_status"] != "open" or assessment.get("outcome") or assessment["decision"] == "HOLD_CANCEL":
        reason = ("The order is outside the active dispatch queue." if assessment["queue_status"] != "open" else
                  "A terminal outcome is already recorded." if assessment.get("outcome") else
                  "The buyer declined or cancelled this order.")
        return _action("stop", "Leave out of dispatch", reason,
                       "Check the order history for the final status.", "Review any later change in the source order.")
    if assessment.get("needs_review") or order.get("data_source", "").casefold() == "daraz":
        return _action("review_order", "Review the order", "A staff member needs to resolve the reply or check the source order.",
                       "Confirm the current order details through the seller’s approved workflow.",
                       "Keep it in review while details remain unclear.")
    if address_issues:
        return _action("fix_address", "Ask for the missing address details", " ".join(
            REASONS[issue] + "." for issue in address_issues),
            "Record the corrected address in the source order and have staff check it.",
            "Arrange an approved callback if the buyer cannot clarify by message.", draft=CLARIFICATION)
    if assessment.get("intent") == "CONFIRM" and assessment["decision"] == "SHIP":
        if address_issues is None:
            return _action("check_address", "Check the delivery address", "The buyer confirmed, and the address check is still unavailable.",
                           "Verify the delivery address in the source order.", "Ask the buyer for any missing details.")
        if offer := _advance_action(order, config.advance):
            return offer
        return _action("dispatch", "Ready to dispatch", "The buyer confirmed and the address check is clear.",
                       "Proceed with the seller’s usual dispatch checks.", "Recheck if the buyer or storefront changes the order.")
    if (assessment["decision"] == "SHIP" and address_issues == [] and normalize_phone(order.get("phone"))
            and order.get("phone_valid") != 0
            and (order.get("customer_past_delivered") or 0) >= 3 and order.get("customer_past_refusals") == 0
            and not contact.get("status") and not _advance_action(order, config.advance)):
        return _action("dispatch", "Dispatch as usual", "This buyer has successful deliveries and the address check is clear.",
                       "Use your usual dispatch workflow, including any store-required confirmation.",
                       "Recheck if the buyer or storefront changes the order.")
    if order.get("phone_valid") == 0 or not normalize_phone(order.get("phone")):
        return _action("review_contact", "Check the buyer’s contact details", "A usable mobile number has not been established.",
                       "Verify contact details in the source order.", "Review the order before making a dispatch decision.")
    return _contact_action(order, contact, config, at)
