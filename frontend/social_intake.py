"""Separate seller intake screen backed by the authenticated shadow API."""

import hashlib
import os
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import streamlit as st


BASE = os.environ.get("COD_GUARD_INTAKE_API", "http://127.0.0.1:8000").rstrip("/")
FIELDS = (("name", "Buyer name"), ("phone", "Pakistan mobile number"), ("address", "Address"), ("city", "City"),
          ("items", "Items"), ("amount_pkr", "Total in PKR"),
          ("utm_source", "UTM source (optional)"), ("utm_medium", "UTM medium (optional)"),
          ("utm_campaign", "UTM campaign (optional)"), ("referring_site", "Referring site (optional)"))


def send(path, key, **kwargs):
    try:
        response = httpx.post(f"{BASE}/integrations/social/{path}", headers={
            "Authorization": f"Bearer {key}", **kwargs.pop("headers", {})}, timeout=15,
            follow_redirects=False, **kwargs)
        if response.is_success:
            return response.json()
        if response.status_code in (401, 403):
            st.error("Enter a valid key for your shadow tenant.")
        elif response.status_code == 422:
            st.error("The order or CSV was rejected. Check the required fields, format and size.")
        else:
            st.error("Intake could not complete. Check the connection and retry.")
    except (httpx.HTTPError, ValueError):
        st.error("The intake API is unavailable. Check the connection and retry.")
    return None


def discard():
    for key, _ in FIELDS:
        st.session_state.pop(f"draft_{key}", None)
    for key in ("dm_draft", "dm_transcript", "dm_reviewed"):
        st.session_state.pop(key, None)


st.set_page_config(page_title="Seller intake · COD-Guard")
st.title("Seller intake")
st.caption("Shadow queue only. Importing an order does not contact the buyer or record WhatsApp consent.")
target = urlsplit(BASE)
if (not target.hostname or target.username or target.password or target.query or target.fragment
        or (target.scheme != "https" and not (target.scheme == "http" and target.hostname in ("127.0.0.1", "localhost", "::1")))):
    st.error("Configure an HTTPS API or a loopback development API before use.")
    st.stop()
key = st.text_input("Shadow tenant operator key", type="password", key="operator_key", on_change=discard)
if not key:
    st.stop()
if notice := st.session_state.pop("saved_notice", None):
    st.success(notice)
if st.session_state.pop("clear_draft", False):
    discard()

dm, sheets = st.tabs(["Paste a DM", "Import Google Sheets CSV"])
with dm:
    if "dm_draft" not in st.session_state:
        with st.form("extract"):
            channel = st.selectbox("Channel", ["instagram", "whatsapp", "facebook"])
            transcript = st.text_area("Conversation", max_chars=6000, key="dm_transcript",
                                      help="Lines such as Name:, Phone:, Address:, City:, Items: and Total: are easiest to extract.")
            if st.form_submit_button("Extract draft"):
                result = send("dm/preview", key, json={"channel": channel, "transcript": transcript})
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
                    result = send("dm/confirm", key, json={**values, "channel": channel, "confirmed": True,
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
                result = send("sheets/import", key, headers={"Idempotency-Key": hashlib.sha256(contents).hexdigest()},
                              files={"file": ("orders.csv", contents, "text/csv")})
                if result is not None:
                    st.success(f"{result['imported']} imported; {len(result['errors'])} rejected.")
                    if result["errors"]:
                        st.dataframe(result["errors"], hide_index=True)
