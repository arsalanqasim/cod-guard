"""COD-Guard local exhibition dashboard; all displayed orders are SYNTHETIC."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/app"))
import service
from records import StateUnavailable
from jobs import QueueFull
from verification import transcribe_voice_note, parse_reply
from woocommerce import WooCommerceError, configured_stores
from connector_orders import connection_state

st.set_page_config(page_title="COD-Guard", page_icon="🛡️", layout="wide")
st.markdown("""<style>
.block-container {padding-top:2rem; padding-bottom:2rem; max-width:1450px;}
h1 {letter-spacing:-0.04em; margin-bottom:0;}
[data-testid="stMetric"] {background:white; border:1px solid #E2E8F0; border-radius:12px; padding:14px;}
[data-testid="stChatMessage"] {border:1px solid #E2E8F0; border-radius:12px;}
textarea {unicode-bidi:plaintext; font-size:1rem !important; line-height:1.7 !important;}
textarea:disabled {-webkit-text-fill-color:#17253C; opacity:1;}
</style>""", unsafe_allow_html=True)

st.caption("AIC378 · EXHIBITION DEMO · SYNTHETIC ORDERS")
st.title("COD-Guard")
st.write("Verify before dispatch. Learn from outcomes.")
notice = st.session_state.pop("notice", None)
if notice:
    st.success(notice)

try:
    page_size = 50
    page = st.session_state.get("dispatch_page", 1)
    page_rows, page_scores, total = service.order_page(limit=page_size, offset=(page - 1) * page_size)
    orders = {row["order_id"]: row for row in page_rows}
    assessments = {score["order_id"]: score for score in page_scores}
    model = service.model_status()
    learning = service.learning_status()
except (FileNotFoundError, StateUnavailable, ValueError) as exc:
    st.error(f"Demo setup is incomplete: {exc}")
    st.code("python data/generate_benchmark.py\npython backend/app/train_model.py\npython scripts/seed_demo.py")
    st.stop()

if not orders:
    st.info("No demo orders are available on this page.")
    st.stop()

with st.sidebar:
    st.subheader("Exhibition control")
    st.caption("WHATSAPP MODE: SIMULATED · EXHIBITION TENANT")
    st.number_input("Order page", min_value=1, max_value=max(1, (total + page_size - 1) // page_size),
                    step=1, key="dispatch_page")
    st.write("No WhatsApp messages are sent. Reply intent uses offline rules; Urdu audio uses Whisper.")
    st.divider()
    st.write("**Risk model**")
    if model["available"]:
        st.code(model["model_id"])
        st.caption(f"Version {model.get('version', 0)} · ML threshold {model['threshold']:.0%}")
    else:
        st.warning(model["reason"])
    st.write(f"**{learning['pending']}** outcome(s) pending learning")
    st.caption("Mark an outcome, then retrain in Metrics & learning.")
    st.divider()
    st.write("**Demo honesty**")
    st.caption("All orders and benchmark labels are SYNTHETIC. No merchant pilots or production accuracy claims.")
    st.caption("Competitors: Tasdeek, Botaura, OrderWitness, DukaanFlow.")
    if os.environ.get("COD_GUARD_WOO_HEALTH_LOCAL") == "1":
        with st.expander("WooCommerce connection health"):
            try:
                stores = configured_stores()
                if not stores:
                    st.caption("No stores configured.")
                for account, store in stores.items():
                    state = connection_state(service.STATE_PATH, store.identity)
                    st.text(account)
                    st.caption(f"Last poll: {state['last_poll'] or 'Not yet run'}")
                    st.caption(f"Last webhook: {state['last_webhook'] or 'None received'}")
                    if state["last_error"]:
                        st.warning(state["last_error"])
            except (StateUnavailable, WooCommerceError):
                st.warning("WooCommerce connection health is unavailable.")

counts = {decision: sum(a["decision"] == decision for a in assessments.values())
          for decision in ["SHIP", "VERIFY_FIRST", "HOLD", "HOLD_CANCEL"]}
st.caption(f"Orders {(page - 1) * page_size + 1}–{min(page * page_size, total)} of {total}")
for column, label, count in zip(st.columns(3),
                               ["Ready to ship on page", "Verify first on page", "Held / cancelled on page"],
                               [counts["SHIP"], counts["VERIFY_FIRST"], counts["HOLD"] + counts["HOLD_CANCEL"]]):
    column.metric(label, count)

order_ids = list(orders)

def order_label(oid):
    return f"{oid} · {orders[oid]['customer_name']} · {assessments[oid]['zone']}"


def percent(value):
    return "—" if value is None else f"{value:.1%}"


def decision_message(assessment):
    text = f"{assessment['zone']} · {assessment['decision']} — {assessment['decision_why']}"
    if assessment["decision"] == "SHIP":
        st.success(text)
    elif assessment["decision"] == "VERIFY_FIRST":
        st.warning(text)
    else:
        st.error(text)
    if assessment["needs_review"]:
        st.warning("Clarify the last reply with the customer.")


tab_orders, tab_verification, tab_metrics = st.tabs(
    ["Orders & risk", "Verification", "Metrics & learning"], key="active_tab", on_change="rerun")

with tab_orders:
    st.subheader("Dispatch queue")
    st.caption("A lone adverse signal cannot hold an order or require verification. Both address checks count together as one signal.")
    filter_column, search_column = st.columns([1, 2])
    zones = filter_column.multiselect("Risk zones", ["GREEN", "AMBER", "RED"], default=["GREEN", "AMBER", "RED"])
    search = search_column.text_input("Search this page", placeholder="Order ID, customer, product or city").casefold()
    rows = []
    for oid, order in orders.items():
        risk = assessments[oid]
        if risk["zone"] not in zones or search not in " ".join(str(order[key]) for key in ["order_id", "customer_name", "product", "city"]).casefold():
            continue
        rows.append({"Order": oid, "Customer": order["customer_name"], "Product": order["product"],
                     "City": order["city"], "PKR": order["amount_pkr"], "Rule score": risk["rule_score"],
                     "ML estimate": risk["ml_probability"], "Zone": risk["zone"],
                     "Decision": risk["decision"], "Follow-up": "Clarify reply" if risk["needs_review"] else "",
                     "Outcome": risk["outcome"] or "Unmarked"})
    if rows:
        frame = pd.DataFrame(rows)
        colors = {"GREEN": "background-color:#E5F4EB;color:#17613B", "AMBER": "background-color:#FFF2D5;color:#805500", "RED": "background-color:#FDE7E7;color:#963431"}
        st.dataframe(frame.style.map(lambda value: colors.get(value, ""), subset=["Zone"]),
                     width="stretch", hide_index=True,
                     column_config={"ML estimate": st.column_config.NumberColumn(format="%.3f"),
                                    "PKR": st.column_config.NumberColumn(format="%d")})
    else:
        st.info("No orders match these filters.")
    detail_id = st.selectbox("Explain an order", order_ids, format_func=order_label, key="detail_order")
    detail = assessments[detail_id]
    left, right = st.columns([1, 2])
    with left:
        decision_message(detail)
        st.write(f"**{detail['signal_count']} distinct adverse signal groups**")
        st.caption(f"Rule score {detail['rule_score']}/100 · ML failure estimate {percent(detail['ml_probability'])}")
    with right:
        st.write("**Why this recommendation?**")
        for reason in detail["reasons"] or ["No adverse signals detected"]:
            st.write("• " + reason)
        st.caption("A rule score is not a probability. Model estimates come from synthetic training data.")

with tab_verification:
    st.subheader("Customer verification")
    oid = st.selectbox("Choose an order to verify", order_ids, format_func=order_label, key="verify_order")
    order = orders[oid]
    decision_message(assessments[oid])
    st.caption("A clear confirmation ships even a flagged order. A denial stops even a GREEN order. Unclear replies never erase an earlier explicit answer.")
    with st.chat_message("assistant"):
        st.write(service.opening_message(order))
    for message in service.conversation(oid):
        with st.chat_message("user"):
            st.write(message["text"] or "Reply text expired")
            st.caption("Urdu voice transcript" if message["source"] == "voice" else "Customer text reply")
        with st.chat_message("assistant"):
            st.write(f"**{message['intent']} → {message['decision']}**")
            st.write(message["why"])
    reply = st.chat_input("Customer reply: English / Roman Urdu / اردو", key=f"reply_{oid}")
    if reply:
        service.verify_reply(order, reply)
        st.rerun()
    st.caption("Try: Ji theek hai, bhej dein · جی نہیں · Please do not send it")
    st.divider()
    st.write("**Urdu voice note**")
    source = st.radio("Voice source", ["Upload", "Record", "Bundled Urdu sample"], horizontal=True, key="voice_source")
    audio_bytes = None
    suffix = ".wav"
    if source == "Upload":
        uploaded = st.file_uploader("Upload an Urdu voice note (60 seconds / 12 MiB maximum)",
                                    type=["ogg", "mp3", "wav", "m4a", "webm"], key=f"voice_upload_{oid}")
        if uploaded:
            audio_bytes, suffix = uploaded.getvalue(), Path(uploaded.name).suffix.lower()
    elif source == "Record":
        recorded = st.audio_input("Record a short Urdu reply", key=f"voice_recording_{oid}")
        if recorded:
            audio_bytes = recorded.getvalue()
    else:
        sample = ROOT / "data/voice_samples/fleurs_ur_pk_test_0.ogg"
        if sample.exists():
            audio_bytes, suffix = sample.read_bytes(), ".ogg"
        st.caption("Google FLEURS Urdu/Pakistan test row 0 · CC BY 4.0. General read speech, not an order confirmation.")
    fingerprint = hashlib.sha256(audio_bytes).hexdigest() if audio_bytes else None
    if audio_bytes:
        st.audio(audio_bytes, format={".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".webm": "audio/webm"}.get(suffix, "audio/wav"))
    if st.button("Transcribe Urdu", disabled=not audio_bytes, key="transcribe_voice"):
        with st.spinner("Transcribing locally with cached Whisper weights…"):
            result = transcribe_voice_note(audio_bytes, suffix=suffix)
        st.session_state["voice_result"] = {"order_id": oid, "fingerprint": fingerprint, "result": result}
    preview = st.session_state.get("voice_result", {})
    if preview.get("order_id") == oid and preview.get("fingerprint") == fingerprint:
        result = preview["result"]
        if not result["ok"]:
            st.error(result["reason"])
        else:
            st.text_area("Transcript (verbatim)", value=result["text"], disabled=True, height=160,
                         key=f"transcript_{oid}_{fingerprint}")
            st.write(f"Understood as: **{parse_reply(result['text']) if not result.get('warning') else 'UNCLEAR'}**")
            if result.get("warning"):
                st.warning(result["warning"])
            elif st.button("Apply transcript to this order", key="apply_voice"):
                service.verify_reply(order, result["text"], source="voice")
                st.rerun()
            st.caption("Previewing/transcribing does not change the dispatch decision. Apply the transcript explicitly.")

with tab_metrics:
    st.subheader("Held-out SYNTHETIC benchmark")
    report = service.latest_evaluation()
    if report:
        chosen = report["chosen"]
        report_label = "Baseline v1" if not report["split"]["feedback"] else f"Outcome-fed version {report['version']}"
        st.caption(f"{report_label} · AMBER and RED count as pre-reply flags.")
        for column, label, value in zip(st.columns(4), ["False-positive rate", "False-negative rate", "Precision", "Recall"],
                                       [chosen["fp_rate"], chosen["fn_rate"], chosen["precision"], chosen["recall"]]):
            column.metric(label, percent(value))
        split = report["split"]
        st.caption(f"{split['test']} test orders · {split['validation']} validation orders · {split['training']} training rows · "
                   f"threshold {chosen['threshold']:.2f} chosen on validation only · model {report['model_id']}")
        matrix, chart = st.columns([1, 2])
        with matrix:
            st.write("**Confusion matrix**")
            st.dataframe(pd.DataFrame([[chosen["tn"], chosen["fp"]], [chosen["fn"], chosen["tp"]]],
                                      index=["Delivered label", "Failed label"], columns=["Pass", "Flag"]), width="stretch")
        with chart:
            st.write("**FP / FN threshold trade-off**")
            st.line_chart(pd.DataFrame(report["test_threshold_sweep"]).set_index("threshold")[["fp_rate", "fn_rate"]],
                          height=220, x_label="ML threshold", y_label="Error rate")
        costs = [{"Policy": name.replace("_", " "), "FP": entry["fp"], "FN": entry["fn"], "Illustrative cost (PKR)": entry["total_cost"]}
                 for name, entry in {**report["baselines"], "serving_policy": chosen}.items()]
        st.dataframe(costs, hide_index=True, width="stretch")
        st.caption("Assumed cost: FN PKR 650, FP PKR 450. These are illustrative costs, not real merchant losses.")
        if chosen["total_cost"] >= report["baselines"]["block_any_adverse_signal"]["total_cost"]:
            st.warning("This operating point does not beat the aggressive any-signal baseline on illustrative cost. Both error rates are shown above; ordinary refusals remain difficult to predict.")
        with st.expander("Method and limitations"):
            st.write("Serving and evaluation share the same two-signal policy. All 80 demo orders are reserved outside training/validation/test. Marked outcomes join training only.")
            for limitation in report["limitations"]:
                st.write("• " + limitation)
        st.download_button("Download evaluation (JSON)", json.dumps(report, indent=2),
                           file_name=f"synthetic-evaluation-{report['model_id']}.json", mime="application/json")
    else:
        st.warning("No evaluation matches the active model. Run python backend/app/train_model.py.")
    st.divider()
    st.subheader("Marked demo outcomes")
    metrics = service.live_metrics()
    for column, label, value in zip(st.columns(4), ["TP · failed held", "FP · delivered held", "FN · failed passed", "TN · delivered passed"],
                                   [metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]]):
        column.metric(label, value)
    st.caption(f"{metrics['marked']} scored outcomes · {metrics['unscored']} without a frozen decision · "
               f"FPR {percent(metrics['fp_rate'])} · FNR {percent(metrics['fn_rate'])}. "
               "Each scored outcome uses the decision revision saved with its first outcome.")
    outcome_order = st.selectbox("Order outcome to record", order_ids, format_func=order_label, key="outcome_order")
    selected_outcome = st.radio("Actual demo outcome", service.OUTCOMES, horizontal=True, key="outcome_value")
    if st.button("Save outcome", key="save_outcome"):
        service.mark_outcome(outcome_order, selected_outcome)
        st.session_state["notice"] = f"Saved {selected_outcome} for {outcome_order}. Outcome is pending learning."
        st.rerun()
    st.divider()
    st.subheader("Learn from marked outcomes")
    st.write(f"**{learning['recorded']} recorded · {learning['trained_outcomes']} in the model · {learning['pending']} pending**")
    st.caption("Retraining consumes marked demo outcomes and publishes a new version. The evaluation holdout stays fixed; metrics may improve or worsen.")
    active_job = st.session_state.get("training_job")
    if st.button("Retrain from marked outcomes", disabled=learning["pending"] == 0 or bool(active_job),
                 key="retrain", type="primary"):
        try:
            job = service.RETRAIN_JOBS.submit(service.retrain_model)
            st.session_state["training_job"] = job["job_id"]
            st.session_state.pop("training_error", None)
            st.rerun()
        except QueueFull as exc:
            st.error(str(exc))

    @st.fragment(run_every=1 if active_job else None)
    def show_training_job():
        if not active_job:
            return
        try:
            job = service.RETRAIN_JOBS.get(active_job)
        except KeyError:
            job = {"status": "failed", "error": "Job status expired. Check the active model before retrying."}
        if job["status"] in ("queued", "running"):
            st.info(f"Retraining {job['status']}")
            return
        del st.session_state["training_job"]
        if job["status"] == "done":
            st.session_state["last_training"] = job["result"]
            st.session_state["notice"] = f"Published {job['result']['model_id']} (v{job['result']['version']})."
        else:
            st.session_state["training_error"] = job["error"]
        st.rerun()

    show_training_job()
    if "training_error" in st.session_state:
        st.error(st.session_state["training_error"])
    if "last_training" in st.session_state:
        result = st.session_state["last_training"]
        st.info(f"Last run: {result['model_id']} · {result['training_rows']} training rows · "
                f"test FPR {percent(result['test']['fp_rate'])} / FNR {percent(result['test']['fn_rate'])}")
