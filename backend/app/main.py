"""Single-instance COD-Guard API for tenant-scoped shadow intake."""
import json
import sys
from pathlib import Path
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import Depends, FastAPI, File, Header, HTTPException, Path as PathParam, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import service
from jobs import JobQueue, QueueFull
from operators import Operator, require_operator, write_operator
from order_intake import MAX_CSV_BYTES, IdempotencyConflict, import_orders
from records import DEMO_TENANT, StateUnavailable
from request_limits import RequestBodyLimit
from verification import (parse_reply, transcribe_voice_note, VOICE_SUFFIXES,
                          VOICE_LIMIT_BYTES, VOICE_WORKERS)
from woo_routes import router as woo_router
from whatsapp_routes import router as whatsapp_router
from courier_routes import router as courier_router
from savings_report import seller_report
from shopify_routes import router as shopify_router
from social_routes import router as social_router
from network_routes import router as network_router
from reply_corrections import CorrectionConflict, export_page

app = FastAPI(title="COD-Guard — shadow intake", version="0.3")
app.add_middleware(RequestBodyLimit, limit=VOICE_LIMIT_BYTES + 1024 * 1024)
app.include_router(woo_router)
app.include_router(whatsapp_router)
app.include_router(courier_router)
app.include_router(shopify_router)
app.include_router(social_router)
app.include_router(network_router)
voice_jobs = JobQueue(workers=VOICE_WORKERS, capacity=4, ttl_seconds=600)


def _order(order_id, operator):
    try:
        return service.get_order(order_id, operator.tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Order not found") from None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(StateUnavailable)
def state_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "State store is unavailable", "error": "state_unavailable"})


@app.get("/ready")
def ready():
    service.check_state()
    error = service.model_readiness_error()
    if error:
        detail = {"model_unavailable": "Risk model is unavailable",
                  "evaluation_unavailable": "Active evaluation artifacts are missing or inconsistent"}[error]
        return JSONResponse(status_code=503, content={"detail": detail, "error": error})
    return {"status": "ready"}


@app.get("/orders")
def orders(response: Response, limit: Annotated[int, Query(ge=1, le=100)] = 50,
           offset: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
           operator: Operator = Depends(require_operator)):
    rows, assessments, total = service.order_page(operator.tenant_id, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return [{**{key: order[key] for key in ("order_id", "customer_name", "product", "city", "amount_pkr", "data_source")},
             "phone": ("••••" + order["phone"][-2:]) if len(order["phone"]) > 2 else "••••",
             **assessment} for order, assessment in zip(rows, assessments)]


@app.post("/orders/import", status_code=201)
def csv_import(file: Annotated[UploadFile, File()],
               idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[!-~]+$")],
               operator: Operator = Depends(write_operator)):
    if operator.tenant_id == DEMO_TENANT:
        raise HTTPException(status_code=403, detail="CSV intake requires a separate shadow tenant")
    if Path(file.filename or "").suffix.lower() != ".csv":
        raise HTTPException(status_code=422, detail="Use a CSV file")
    contents = file.file.read(MAX_CSV_BYTES + 1)
    if not contents or len(contents) > MAX_CSV_BYTES:
        raise HTTPException(status_code=422, detail="CSV must be nonempty and at most 1 MiB")
    try:
        return import_orders(service.STATE_PATH, operator.tenant_id, operator.actor, idempotency_key, contents)
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/orders/{order_id}")
def order_detail(order_id: str, operator: Operator = Depends(require_operator)):
    order = _order(order_id, operator)
    service.record_access(operator.tenant_id, operator.actor, "phone_read", order_id=order_id)
    # Evaluation ground-truth labels are deliberately not returned to the seller.
    return {**{key: value for key, value in order.items() if key != "label_failed"},
            **service.assess_order(order, tenant_id=operator.tenant_id),
            "messages": service.conversation(order_id, operator.tenant_id)}


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reply cannot be blank")
        return value


@app.post("/orders/{order_id}/verify")
def verify(order_id: str, reply: Reply, operator: Operator = Depends(write_operator)):
    order = _order(order_id, operator)
    return {"order_id": order_id, **service.verify_reply(order, reply.text, actor=operator.actor,
                                                         tenant_id=operator.tenant_id)}


class ReplyCorrection(BaseModel):
    label: Literal["CONFIRM", "DENY", "UNCLEAR", "MODIFICATION"]
    expected_revision: int = Field(ge=1, le=2**63 - 1)


@app.post("/orders/{order_id}/replies/{reply_revision}/correction", status_code=201)
def correct_reply(order_id: str, reply_revision: Annotated[int, PathParam(ge=1, le=2**63 - 1)],
                  body: ReplyCorrection, operator: Operator = Depends(write_operator)):
    try:
        return service.correct_reply(order_id, reply_revision, body.expected_revision, body.label,
                                     actor=operator.actor, tenant_id=operator.tenant_id)
    except KeyError:
        raise HTTPException(404, "Order not found") from None
    except CorrectionConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/reply-corrections/export")
def export_reply_corrections(after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
                             limit: Annotated[int, Query(ge=1, le=500)] = 500,
                             operator: Operator = Depends(require_operator)):
    rows = export_page(service.STATE_PATH, operator.tenant_id, operator.actor, after=after, limit=limit)
    return Response("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    media_type="application/x-ndjson",
                    headers={"Cache-Control": "no-store", "X-Next-Cursor": str(rows[-1]["id"] if rows else after),
                             "Content-Disposition": 'attachment; filename="reply-corrections.v1.jsonl"'})


class Outcome(BaseModel):
    outcome: Literal["delivered", "returned", "refused"]


@app.post("/orders/{order_id}/outcome")
def outcome(order_id: str, body: Outcome, operator: Operator = Depends(write_operator)):
    try:
        event = service.mark_outcome(order_id, body.outcome, actor=operator.actor, tenant_id=operator.tenant_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    return {"ok": True, "event": event, "metrics": service.live_metrics(operator.tenant_id),
            "learning": service.learning_status(operator.tenant_id)}


@app.post("/orders/{order_id}/voice", status_code=202)
def voice(order_id: str, file: UploadFile = File(...), commit_decision: bool = False,
          operator: Operator = Depends(write_operator)):
    order = _order(order_id, operator)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VOICE_SUFFIXES:
        raise HTTPException(status_code=422, detail="Use OGG/MP3/WAV/M4A/WebM audio")
    contents = file.file.read(VOICE_LIMIT_BYTES + 1)
    if not contents or len(contents) > VOICE_LIMIT_BYTES:
        raise HTTPException(status_code=422, detail="Audio must be nonempty and at most 12 MiB")
    service.record_access(operator.tenant_id, operator.actor, "voice_requested", order_id=order_id)
    revision = service.verification_revision(operator.tenant_id, order_id) if commit_decision else None

    def transcribe():
        result = transcribe_voice_note(contents, suffix=suffix)
        if not result["ok"]:
            raise ValueError(result["reason"])
        intent = parse_reply(result["text"]) if not result.get("warning") else "UNCLEAR"
        response = {**result, "intent": intent, "applied": False, "superseded": False,
                    "needs_review": intent == "UNCLEAR"}
        if commit_decision and intent != "UNCLEAR":
            response.update(service.apply_queued_verification(
                order, result["text"], intent, "voice", actor=operator.actor,
                tenant_id=operator.tenant_id, expected_revision=revision))
        return response

    try:
        return voice_jobs.submit(transcribe, scope=(operator, order_id))
    except QueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.get("/orders/{order_id}/voice/{job_id}")
def voice_status(order_id: str, job_id: str, operator: Operator = Depends(require_operator)):
    try:
        return voice_jobs.get(job_id, scope=(operator, order_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Voice job not found") from None


@app.get("/metrics")
def metrics(operator: Operator = Depends(require_operator)):
    return service.live_metrics(operator.tenant_id)


@app.get("/reports/savings")
def savings(operator: Operator = Depends(require_operator)):
    return seller_report(operator.tenant_id, service.latest_evaluation())


@app.get("/evaluation")
def evaluation(operator: Operator = Depends(require_operator)):
    report = service.latest_evaluation()
    if report is None:
        raise HTTPException(status_code=404, detail="No evaluation matches the current model; run training")
    return report


@app.get("/model")
def model(operator: Operator = Depends(require_operator)):
    status = service.model_status()
    status.pop("feedback", None)
    return {**status, "learning": service.learning_status(operator.tenant_id)}


@app.post("/model/retrain", status_code=202)
def retrain(operator: Operator = Depends(write_operator)):
    if operator.tenant_id != DEMO_TENANT:
        raise HTTPException(status_code=403, detail="Retraining is restricted to synthetic demo outcomes")
    try:
        return service.RETRAIN_JOBS.submit(lambda: service.retrain_model(actor=operator.actor), scope=operator)
    except QueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.get("/model/retrain/{job_id}")
def retrain_status(job_id: str, operator: Operator = Depends(require_operator)):
    try:
        return service.RETRAIN_JOBS.get(job_id, scope=operator)
    except KeyError:
        raise HTTPException(status_code=404, detail="Retraining job not found") from None
