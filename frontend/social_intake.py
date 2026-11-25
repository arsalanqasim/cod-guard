"""Separate seller intake screen backed by the authenticated shadow API."""

import hashlib
import os
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
import streamlit as st


BASE = os.environ.get("COD_GUARD_INTAKE_API", "http://127.0.0.1:8000").rstrip("/")
FIELDS = (("name", "Buyer name"), ("phone", "Pakistan mobile number"), ("address", "Address"), ("city", "City"),
          ("items", "Items"), ("amount_pkr", "Total in PKR"),
          ("utm_source", "UTM source (optional)"), ("utm_medium", "UTM medium (optional)"),
          ("utm_campaign", "UTM campaign (optional)"), ("referring_site", "Referring site (optional)"))


def request(send, path, key, **kwargs):
    try:
        response = send(f"{BASE}{path}", headers={
            "Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}, timeout=15,
            follow_redirects=False, **kwargs)
        if response.is_success:
            return response.json()
        if response.status_code in (401, 403):
            st.error("Enter a valid key for your shadow tenant.")
        elif response.status_code == 409:
            st.error(response.json().get("detail", "Review the current order before retrying."))
        elif response.status_code == 422:
            st.error("Check the required fields and try again.")
        else:
            st.error("The request could not complete. Check the connection and retry.")
    except (httpx.HTTPError, ValueError):
        st.error("The seller API is unavailable. Check the connection and retry.")
    return None


def discard():
    for key, _ in FIELDS:
        st.session_state.pop(f"draft_{key}", None)
    for key in ("dm_draft", "dm_transcript", "dm_reviewed"):
        st.session_state.pop(key, None)


def change_operator():
    discard()
    for key in ("advice_order", "advice_page"):
        st.session_state.pop(key, None)


st.set_page_config(page_title="Seller intake · COD-Guard")
st.title("Seller intake")
st.caption("Shadow queue only. Importing an order does not contact the buyer or record WhatsApp consent.")
target = urlsplit(BASE)
if (not target.hostname or target.username or target.password or target.query or target.fragment
        or (target.scheme != "https" and not (target.scheme == "http" and target.hostname in ("127.0.0.1", "localhost", "::1")))):
    st.error("Configure an HTTPS API or a loopback development API before use.")
    st.stop()
key = st.text_input("Shadow tenant operator key", type="password", key="operator_key", on_change=change_operator)
if not key:
    st.stop()
if notice := st.session_state.pop("saved_notice", None):
    st.success(notice)
if st.session_state.pop("clear_draft", False):
    discard()

dm, sheets, advice = st.tabs(["Paste a DM", "Import Google Sheets CSV", "Next action"],
                             key="seller_tab", on_change="rerun")
with dm:
    if "dm_draft" not in st.session_state:
        with st.form("extract"):
            channel = st.selectbox("Channel", ["instagram", "whatsapp", "facebook"])
            transcript = st.text_area("Conversation", max_chars=6000, key="dm_transcript",
                                      help="Lines such as Name:, Phone:, Address:, City:, Items: and Total: are easiest to extract.")
            if st.form_submit_button("Extract draft"):
                result = request(httpx.post, "/integrations/social/dm/preview", key,
                                 json={"channel": channel, "transcript": transcript})
                if result is not None:
                    st.session_state["dm_draft"] = (channel, uuid4().hex)
                    for field, value in result["draft"].items():
                        st.session_state[f"draft_{field}"] = value
                    st.rerun()
    else:
        st.warning("Review and correct the draft. Missing or ambiguous fields are left blank.")
        channel, confirmation_id = st.session_state["dm_draft"]
        with st.form("review"):
            values = {field: st.text_input(label, key=f"draft_{field}") for field, label in FIELDS}
            reviewed = st.checkbox("I checked these fields against the buyer’s order", key="dm_reviewed")
            if st.form_submit_button("Confirm and save"):
                if not reviewed:
                    st.error("Review the draft before saving.")
                else:
                    result = request(httpx.post, "/integrations/social/dm/confirm", key,
                                     json={**values, "channel": channel, "confirmed": True,
                                           "confirmation_id": confirmation_id})
                    if result is not None:
                        st.session_state["saved_notice"] = "Order saved." if result["queued"] else "Order was already saved."
                        st.session_state["clear_draft"] = True
                        st.rerun()
        st.button("Discard draft", on_click=discard)

with sheets:
    st.write("Download the order tab as CSV from Google Sheets. Keep the original sheet private.")
    st.caption("Required headers: order_id, customer_name, product, phone. Optional: city, amount_pkr and supported risk columns.")
    with st.form("sheets"):
        upload = st.file_uploader("Google Sheets export", type=["csv"])
        if st.form_submit_button("Import into queue"):
            if not upload or not 0 < upload.size <= 1024 * 1024:
                st.error("Choose a nonempty CSV up to 1 MiB.")
            else:
                contents = upload.getvalue()
                result = request(httpx.post, "/integrations/social/sheets/import", key,
                                 headers={"Idempotency-Key": hashlib.sha256(contents).hexdigest()},
                                 files={"file": ("orders.csv", contents, "text/csv")})
                if result is not None:
                    st.success(f"{result['imported']} imported; {len(result['errors'])} rejected.")
                    if result["errors"]:
                        st.dataframe(result["errors"], hide_index=True)

with advice:
    if advice.open:
        page = st.number_input("Order page", min_value=1, max_value=100_000, step=1, key="advice_page")
        st.button("Refresh recommendations")
        orders = request(httpx.get, "/orders", key, params={"limit": 50, "offset": (page - 1) * 50})
        if orders == []:
            st.info("No orders on this page.")
        if orders:
            choices = {order["order_id"]: order for order in orders}
            order_id = st.selectbox("Order", options=choices, key="advice_order",
                                    format_func=lambda oid: f"{oid} · {choices[oid]['product']}")
            action = choices[order_id].get("next_action")
            if action is None:
                st.info("Enable Next action for this tenant to see dispatch recommendations.")
            else:
                order_path = f"/orders/{quote(order_id, safe='')}"
                st.subheader(action["title"])
                st.write(action["reason"])
                if deadline := action.get("deadline"):
                    st.write(f"**Before {deadline}**")
                if advance := action.get("advance"):
                    st.write(f"**PKR {advance['amount_pkr']} today · PKR {advance['remaining_cod_pkr']} at delivery**")
                    st.caption(f"Order total · PKR {advance['order_total_pkr']}")
                st.write(action["next_step"])
                st.caption(action["fallback"])
                if draft := action.get("draft"):
                    st.code(draft, language=None)
                if action["action"] in ("fix_address", "check_address"):
                    with st.form(f"review_address_{order_id}", clear_on_submit=True):
                        address = st.text_input("Corrected delivery address", max_chars=500)
                        saved = st.checkbox("I checked and saved this address in the source order")
                        if st.form_submit_button("Record address review"):
                            result = request(httpx.put, order_path + "/dispatch-address", key,
                                             json={"address": address, "saved_at_source": saved})
                            if result is not None:
                                st.rerun()
                if action["action"] in ("call_buyer", "confirm_whatsapp", "wait_for_reply"):
                    with st.form(f"record_reply_{order_id}", clear_on_submit=True):
                        reply = st.text_input("Buyer’s reply", max_chars=2000)
                        if st.form_submit_button("Record buyer reply"):
                            if request(httpx.post, order_path + "/verify", key, json={"text": reply}) is not None:
                                st.rerun()
