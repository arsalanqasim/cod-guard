"""Local exhibition API: uvicorn backend.app.main:app --host 127.0.0.1.

The dashboard calls the same service functions directly. This demo API has
no authentication and is intended for localhost, not public deployment.
"""
import sys
import tempfile
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
import service
from verification import (parse_reply, transcribe_voice_note, VOICE_SUFFIXES,
                          VOICE_LIMIT_BYTES)

app = FastAPI(title="COD-Guard — synthetic exhibition demo", version="0.2")


def _order(order_id):
    try:
        return service.get_order(order_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Order not found") from None


@app.get("/health")
def health():
    return {"status": "ok", "data_source": "SYNTHETIC demo", "model": service.model_status()}


@app.get("/orders")
def orders():
    return [{**{key: order[key] for key in ("order_id", "customer_name", "product", "city", "amount_pkr", "phone")},
             **service.assess_order(order), "data_source": "SYNTHETIC"}
            for order in service.load_orders().to_dict("records")]


@app.get("/orders/{order_id}")
def order_detail(order_id: str):
    order = _order(order_id)
    # Evaluation ground-truth labels are deliberately not returned to the seller.
    return {**{key: value for key, value in order.items() if key != "label_failed"},
            **service.assess_order(order), "messages": service.conversation(order_id)}


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reply cannot be blank")
        return value


@app.post("/orders/{order_id}/verify")
def verify(order_id: str, reply: Reply):
    order = _order(order_id)
    return {"order_id": order_id, **service.verify_reply(order, reply.text)}


class Outcome(BaseModel):
    outcome: Literal["delivered", "returned", "refused"]


@app.post("/orders/{order_id}/outcome")
def outcome(order_id: str, body: Outcome):
    _order(order_id)
    service.mark_outcome(order_id, body.outcome)
    return {"ok": True, "metrics": service.live_metrics(), "learning": service.learning_status()}


@app.post("/orders/{order_id}/voice")
def voice(order_id: str, file: UploadFile = File(...), commit_decision: bool = False):
    order = _order(order_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VOICE_SUFFIXES:
        raise HTTPException(status_code=422, detail="Use OGG/MP3/WAV/M4A/WebM audio")
    contents = file.file.read(VOICE_LIMIT_BYTES + 1)
    if not contents or len(contents) > VOICE_LIMIT_BYTES:
        raise HTTPException(status_code=422, detail="Audio must be nonempty and at most 12 MiB")
    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            audio_path = Path(temporary.name)
            temporary.write(contents)
        result = transcribe_voice_note(str(audio_path))
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)
    if not result["ok"]:
        raise HTTPException(status_code=503 if result["error"] == "model_unavailable" else 422,
                            detail=result["reason"])
    applied = commit_decision and not result.get("warning")
    intent = parse_reply(result["text"]) if not result.get("warning") else "UNCLEAR"
    response = {**result, "intent": intent, "applied": applied}
    if applied:
        response.update(service.verify_reply(order, result["text"], source="voice"))
    return response


@app.get("/metrics")
def metrics():
    return service.live_metrics()


@app.get("/evaluation")
def evaluation():
    report = service.latest_evaluation()
    if report is None:
        raise HTTPException(status_code=404, detail="No evaluation matches the current model; run training")
    return report


@app.get("/model")
def model():
    return {**service.model_status(), "learning": service.learning_status()}


@app.post("/model/retrain")
def retrain():
    try:
        return service.retrain_model()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
