"""COD-Guard seller dashboard (exhibition demo).
Run:  streamlit run frontend/dashboard.py
Tabs: Orders (risk colours + reasons) · Verification (WhatsApp-style chat
simulation) · Metrics (live FP/FN + outcome marking = closed loop)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
import streamlit as st
import service

st.set_page_config(page_title="COD-Guard", layout="wide")
st.title("COD-Guard — AI Pre-Dispatch Intelligence for COD Orders")
st.caption("Verify first, score the risk, ship only real orders. "
           "Demo data: synthetic, calibrated to published Pakistani COD statistics.")

df = service.load_orders()
orders = {row["order_id"]: row.to_dict() for _, row in df.iterrows()}

tab1, tab2, tab3 = st.tabs(["📦 Orders & Risk", "💬 Verification Chat", "📊 FP/FN Metrics & Outcomes"])

with tab1:
    rows = []
    for oid, o in orders.items():
        a = service.assess_order(o)
        rows.append({"Order": oid, "Customer": o["customer_name"], "Product": o["product"],
                     "City": o["city"], "Amount (PKR)": o["amount_pkr"],
                     "Risk score": a["rule_score"],
                     "ML fail-prob": a["ml_probability"],
                     "Zone": {"GREEN": "🟢 GREEN", "AMBER": "🟡 AMBER", "RED": "🔴 RED"}[a["zone"]],
                     "Decision": a["decision"] or "—",
                     "Why flagged": "; ".join(a["reasons"]) or "No risk signals"})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.info("🟢 ship it · 🟡 verify with the customer first · 🔴 hold — do not dispatch "
            "without confirmation. No single signal can flag an order alone.")

with tab2:
    oid = st.selectbox("Choose an order to verify", list(orders.keys()))
    o = orders[oid]
    a = service.assess_order(o)
    st.write(f"**Risk zone:** {a['zone']} · score {a['rule_score']} · "
             f"ML fail-probability {a['ml_probability']}")
    st.chat_message("assistant").write(service.opening_message(o))
    reply = st.chat_input("Type the customer's reply (English / Roman Urdu / اردو)…")
    if reply:
        st.chat_message("user").write(reply)
        res = service.verify_reply(o, reply)
        st.chat_message("assistant").write(
            f"Understood as: **{res['intent']}** → Decision: **{res['decision']}** — {res['why']}")
    st.caption("Try: 'Ji theek hai, bhej dein' (rescues even a 🔴 order) or "
               "'Nahi, mera order nahi hai' (stops even a 🟢 order).")

with tab3:
    st.subheader("Live confusion matrix (marked outcomes)")
    m = service.live_metrics()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("TP — fake caught", m["tp"]); c2.metric("FP — genuine held", m["fp"])
    c3.metric("FN — fake shipped", m["fn"]); c4.metric("TN — genuine shipped", m["tn"])
    st.write(f"Marked outcomes so far: **{m['marked']}** · "
             f"FP rate: {m['fp_rate'] if m['fp_rate'] is not None else '—'} · "
             f"FN rate: {m['fn_rate'] if m['fn_rate'] is not None else '—'}")
    st.caption("Full offline evaluation (threshold sweep, baselines, segment check) "
               "is in docs/EVAL_REPORT.md.")
    st.divider()
    st.subheader("Close the loop — record what actually happened")
    oid2 = st.selectbox("Order", list(orders.keys()), key="outcome_order")
    outcome = st.radio("Actual outcome", ["delivered", "returned", "refused"], horizontal=True)
    if st.button("Save outcome"):
        service.mark_outcome(oid2, outcome)
        st.success(f"Outcome saved for {oid2}. These outcomes retrain the next model version.")
