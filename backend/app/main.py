"""COD-Guard FastAPI backend. Run: uvicorn backend.app.main:app --reload
(Or skip it — the Streamlit dashboard uses the same service layer.)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import FastAPI
from pydantic import BaseModel
import service

app = FastAPI(title="COD-Guard", version="0.1")

@app.get("/orders")
def orders():
    df = service.load_orders()
    out = []
    for _, row in df.iterrows():
        o = row.to_dict()
        out.append({**{k: o[k] for k in ("order_id", "customer_name", "product",
                                         "city", "amount_pkr", "phone")},
                    **service.assess_order(o)})
    return out

class Reply(BaseModel):
    text: str

@app.post("/orders/{order_id}/verify")
def verify(order_id: str, reply: Reply):
    df = service.load_orders()
    row = df[df.order_id == order_id].iloc[0].to_dict()
    return {"order_id": order_id,
            "opening_message": service.opening_message(row),
            **service.verify_reply(row, reply.text)}

class Outcome(BaseModel):
    outcome: str  # delivered / returned / refused

@app.post("/orders/{order_id}/outcome")
def outcome(order_id: str, body: Outcome):
    service.mark_outcome(order_id, body.outcome)
    return {"ok": True, "metrics": service.live_metrics()}

@app.get("/metrics")
def metrics():
    return service.live_metrics()
