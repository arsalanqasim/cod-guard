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
import os
import threading
from functools import lru_cache
from pathlib import Path

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

    negated_cancel = (
        r"(?:(?:don't|do not|never)\s+cancel(?:\s+(?:it|the order|my order))?"
        r"|cancel\s+(?:mat|na|nahi|nahin|nhi)\s*(?:kar\w*)?"
        r"|(?:کینسل|منسوخ)\s+(?:مت|نہ|نہیں)\s*(?:کریں|کرنا|کرو)?)"
    )
    keep_order = matches(negated_cancel, t)
    t = re.sub(r"(?<!\w)" + negated_cancel + r"(?!\w)", " ", t)
    reassurance = r"no (?:problems?|issues?|worries)|not fake|(?:کوئی\s+)?(?:مسئلہ|دقت|اعتراض)\s+نہیں"
    t = re.sub(r"(?<!\w)(?:" + reassurance + r")(?!\w)", " ", t).strip()

    negated_dispatch = (
        r"(?:don't|do not|never|cannot|can't)\s+(?:please\s+)?(?:send|confirm|deliver|dispatch)\w*"
        r"|(?:mat|na|nahi|nahin|nhi)\s+(?:bhej\w*|confirm\w*)"
        r"|(?:confirm(?:ed)?|bhej\w*|theek|thik|send|deliver|dispatch)\s+(?:nahi|nahin|nhi|nai|mat)"
        r"|(?:مت|نہ)\s+بھیج\w*|(?:بھیج\w*|کنفرم|ٹھیک)\s+(?:مت|نہیں|نہ)"
    )
    denial = (
        r"cancel(?:led)?|stop|not mine|not my order|منسوخ|کینسل"
        r"|(?:didn't|did not|never)\s+(?:place\s+)?(?:this\s+)?order(?:ed)?"
        r"|(?:don't|do not)\s+want\s+(?:it|(?:my|the|this)\s+order)"
    )
    question = re.match(r"^(?:can|could|would|what|when|where|how|is|are|did|have|کیا|کب|کیسے)(?!\w)", t)
    if question and not matches(r"cancel|منسوخ|کینسل", t):
        return "UNCLEAR"
    direct_negative = re.match(r"^(?:(?:ji|جی|haan|yes|ہاں|bhai)\s*[,،]?\s*)*(?:no|nahi|nahin|nhi|nai|نہیں)(?!\w)", t)
    order_negative = (matches(r"no|nahi|nahin|nhi|nai|نہیں", t)
                      and matches(r"order\w*|آرڈر|منگو\w*|منگوا\w*|mangw\w*", t))
    # A clear denial wins over politeness and positive tokens elsewhere.
    if direct_negative or order_negative or matches(negated_dispatch, t) or matches(denial, t):
        return "DENY"

    uncertainty = (
        r"if|unless|maybe|perhaps|later|tomorrow|wait|agar|kal|baad|اگر|شاید|کل|بعد"
        r"|will confirm|not sure|پتا نہیں"
    )
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

VOICE_LIMIT_BYTES = 12 * 1024 * 1024
VOICE_LIMIT_SECONDS = 60
VOICE_SUFFIXES = {".ogg", ".mp3", ".wav", ".m4a", ".webm"}
_VOICE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _whisper_model(name, cache, offline):
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8",
                        download_root=cache, local_files_only=offline)


def prepare_voice_model(offline=False):
    """Download once explicitly; runtime defaults to cached/offline weights."""
    name = os.environ.get("COD_GUARD_WHISPER_MODEL", "small")
    cache = Path(os.environ.get("COD_GUARD_WHISPER_CACHE",
                               Path(__file__).resolve().parents[2] / "data/whisper"))
    cache.mkdir(parents=True, exist_ok=True)
    with _VOICE_LOCK:
        return _whisper_model(name, str(cache), offline)


def transcribe_voice_note(path: str) -> dict:
    """Transcribe an Urdu voice note with Whisper (faster-whisper).

    Setup (on the demo machine):  pip install faster-whisper
    Returns {"ok": False, "reason": ...} instead of crashing when the
    package or model is unavailable, so the chat flow never breaks.
    """
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "error": "invalid_audio", "reason": f"Audio file does not exist: {path}"}
    if path.suffix.lower() not in VOICE_SUFFIXES or not 0 < path.stat().st_size <= VOICE_LIMIT_BYTES:
        return {"ok": False, "error": "invalid_audio", "reason": "Use OGG/MP3/WAV/M4A/WebM audio up to 12 MiB"}
    try:
        import av
    except ImportError as exc:
        return {"ok": False, "error": "model_unavailable",
                "reason": f"{type(exc).__name__}: {exc}. Install requirements.txt first."}
    try:
        with av.open(str(path)) as audio:
            if not audio.streams.audio or audio.duration is None:
                raise ValueError("Cannot determine audio duration; use a short OGG, MP3 or WAV clip")
            duration = audio.duration / av.time_base
            if duration > VOICE_LIMIT_SECONDS:
                raise ValueError("Voice notes must be 60 seconds or shorter; audio is never silently truncated")
    except Exception as exc:
        return {"ok": False, "error": "invalid_audio", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        offline = os.environ.get("COD_GUARD_OFFLINE", "1") != "0"
        model = prepare_voice_model(offline=offline)
    except Exception as exc:
        return {"ok": False, "error": "model_unavailable",
                "reason": f"{type(exc).__name__}: {exc}. Run python scripts/prepare_voice.py while online."}
    try:
        with _VOICE_LOCK:
            segments, _info = model.transcribe(str(path), language="ur", vad_filter=True,
                                               condition_on_previous_text=False)
            segments = list(segments)
        text = "".join(segment.text for segment in segments).strip()
        warning = None
        if not text:
            warning = "No audible speech detected; ask the customer to repeat"
        elif any(segment.avg_logprob < -1.0 for segment in segments):
            warning = "Low transcription confidence; ask the customer to repeat or type their answer"
        return {"ok": True, "text": text, "duration_seconds": round(duration, 2),
                "language": "ur", "warning": warning}
    except Exception as exc:
        return {"ok": False, "error": "transcription_failed", "reason": f"{type(exc).__name__}: {exc}"}
