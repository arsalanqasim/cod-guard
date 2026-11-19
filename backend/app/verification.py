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
import unicodedata

def parse_reply(text: str) -> str:
    """Conservative, offline intent rules; this is not an LLM classifier.

    Polite ``ji`` alone is not consent. Negated dispatch is a denial,
    while negated cancellation and idioms such as ``no problem`` are
    handled before looking for denial words. Unhandled questions and
    conditional/future confirmations need a follow-up.
    """
    if not isinstance(text, str) or not text.strip():
        return "UNCLEAR"
    t = unicodedata.normalize("NFKC", text).lower().replace("’", "'")
    t = t.translate(str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"}))
    t = " ".join("".join(c for c in t if not unicodedata.combining(c)).split())

    def matches(pattern, value):
        return re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", value) is not None

    negated_cancel = r"(?:don't|do not|never)\s+cancel(?:\s+(?:it|the order|my order))?"
    keep_order = matches(negated_cancel, t)
    t = re.sub(r"(?<!\w)" + negated_cancel + r"(?!\w)", " ", t)
    t = re.sub(r"(?<!\w)(?:no (?:problem|issue|worries)|not fake)(?!\w)", " ", t)

    negated_dispatch = (
        r"(?:don't|do not|never|cannot|can't)\s+(?:please\s+)?(?:send|confirm|deliver|dispatch)\w*"
        r"|(?:mat|na)\s+bhej\w*|(?:مت|نہ)\s+بھیج\w*|بھیج\w*\s+(?:مت|نہیں)"
    )
    denial = (
        r"no|cancel(?:led)?|stop|fake|not mine|not my order|nahi|nahin|nai|نہیں|منسوخ|کینسل"
        r"|(?:didn't|did not|never)\s+(?:place\s+)?(?:this\s+)?order(?:ed)?"
    )
    # A clear denial wins over politeness and positive tokens elsewhere.
    if matches(negated_dispatch, t) or matches(denial, t):
        return "DENY"

    uncertainty = (
        r"if|unless|maybe|perhaps|later|tomorrow|wait|agar|kal|baad|اگر|شاید|کل|بعد"
        r"|will confirm|not sure|پتا نہیں"
    )
    question = re.match(r"^(?:can|could|would|what|when|where|how|کیا|کب|کیسے)(?!\w)", t)
    if matches(uncertainty, t) or question:
        return "UNCLEAR"
    confirmation = (
        r"yes|confirm(?:ed)?|ok(?:ay)?|theek|thik|han|haan|ہاں|ٹھیک|کنفرم"
        r"|bhej\w*|بھیج\w*|(?:send|deliver|dispatch)\s+(?:it|(?:my|the|this)\s+order)"
    )
    if keep_order or matches(confirmation, t):
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
        return {"decision": "SHIP", "why": "Customer confirmed the order"}
    if intent == "DENY":
        return {"decision": "HOLD_CANCEL",
                "why": "Customer denied or cancelled the order"}
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
