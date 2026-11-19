"""COD-Guard verification agent core.

Transport-agnostic: the same logic drives the demo chat UI now and the
real WhatsApp Cloud API later. The agent's job in the FP/FN design:
  - customer CONFIRMS  -> ship, even if the model flagged the order
                          (false-positive recovery)
  - customer DENIES    -> hold/cancel, even if the model passed it
                          (false-negative recovery)
  - no clear reply     -> the risk zone decides; AMBER stays held

Reply understanding is rule-based v0 over English, Roman Urdu and Urdu
script (deterministic and testable at a stall, no API key needed). An
LLM classifier can be layered behind parse_reply() later without
changing the decision logic.
"""
import re

CONFIRM_PATTERNS = [
    r"\byes\b", r"\bconfirm", r"\bok\b", r"\btheek\b", r"\bthik\b", r"\bji\b",
    r"\bhan\b", r"\bhaan\b", r"\bbhej\b", r"\bsend\b", r"\bdeliver\b",
    "جی", "ٹھیک", "ہاں", "بھیج",
]
DENY_PATTERNS = [
    r"\bno\b", r"\bcancel\b", r"\bnot mine\b", r"\bdidn'?t order\b", r"\bnahi\b",
    r"\bnahin\b", r"\bmat bhej", r"\bstop\b", r"\bfake\b",
    "نہیں", "منسوخ", "کینسل",
]

def parse_reply(text: str) -> str:
    """Return CONFIRM, DENY or UNCLEAR for a customer reply."""
    t = f" {text.strip().lower()} "
    deny = any(re.search(p, t) or p in t for p in DENY_PATTERNS)
    confirm = any(re.search(p, t) or p in t for p in CONFIRM_PATTERNS)
    if deny and not confirm:
        return "DENY"
    if confirm and not deny:
        return "CONFIRM"
    return "UNCLEAR"

def opening_message(order: dict) -> str:
    """WhatsApp-style first message (Urdu + English, as sellers actually send)."""
    return (
        f"Assalam-o-Alaikum {order.get('customer_name', 'Customer')}! "
        f"Your order {order.get('order_id', '')} of PKR {order.get('amount_pkr', '')} "
        f"({order.get('items_count', 1)} item(s)) is ready to dispatch. "
        f"Kya aap apna order confirm karte hain? Reply YES to confirm, "
        f"NO agar aap ne order nahi kiya. "
        f"(You can also reply with a voice note in Urdu.)"
    )

def apply_reply(zone: str, intent: str) -> dict:
    """Combine the risk zone with the customer's answer into a final decision."""
    if intent == "CONFIRM":
        return {"decision": "SHIP", "why": "Customer confirmed the order on WhatsApp"}
    if intent == "DENY":
        return {"decision": "HOLD_CANCEL",
                "why": "Customer says they did not place this order"}
    # UNCLEAR / no reply
    if zone == "GREEN":
        return {"decision": "SHIP", "why": "Low risk; no denial received"}
    if zone == "AMBER":
        return {"decision": "VERIFY_FIRST",
                "why": "Medium risk and no clear confirmation — verify before dispatch"}
    return {"decision": "HOLD", "why": "High risk and no confirmation — do not dispatch"}

def transcribe_voice_note(path: str) -> dict:
    """Transcribe an Urdu voice note with Whisper (faster-whisper).

    Setup (on the demo machine):  pip install faster-whisper
    Returns {"ok": False, "reason": ...} instead of crashing when the
    package or model is unavailable, so the chat flow never breaks.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"ok": False, "reason": "faster-whisper not installed on this machine"}
    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(path, language="ur")
        return {"ok": True, "text": "".join(s.text for s in segments).strip()}
    except Exception as e:  # model download / file errors must not kill the flow
        return {"ok": False, "reason": f"transcription failed: {e}"}
