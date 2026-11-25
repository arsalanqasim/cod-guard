"""Offline examples that run through the same seller recommendation policy."""

from datetime import datetime, time, timedelta, timezone

import streamlit as st

from address_quality import classify_address
from next_action import Advance, Policy, recommend
from verification import apply_reply, parse_reply


DEMO_TIME = datetime(2026, 11, 25, 10, 30, tzinfo=timezone.utc)
DEMO_POLICY = Policy(call_after_minutes=60, call_minimum_order_pkr=3500, pickup_cutoff_pkt=time(16),
                     advance=Advance(300, 50, 4000, frozenset({"custom embroidered jacket"}), None))


def _example(product, amount, message, address, contact):
    order = {"product": product, "amount_pkr": amount, "city": "Lahore", "phone": "03000000001",
             "data_source": "synthetic"}
    intent = parse_reply(message)
    assessment = {"queue_status": "open", "zone": "AMBER", "intent": intent, **apply_reply("AMBER", intent)}
    return recommend(order, assessment, classify_address(address, order["city"]), contact,
                     DEMO_POLICY, at=DEMO_TIME)


def _card(column, name, summary, action):
    with column.container(border=True):
        st.subheader(name)
        st.caption(summary)
        st.markdown(f"**{action['title']}**")
        st.write(action["reason"])
        st.write(action["next_step"])
        if deadline := action.get("deadline"):
            st.write(f"**Before {deadline}**")
        if advance := action.get("advance"):
            st.write(f"**PKR {advance['amount_pkr']} today · PKR {advance['remaining_cod_pkr']} at delivery**")
            st.caption(f"Order total · PKR {advance['order_total_pkr']}")
        st.caption(action["fallback"])


def _reset():
    for key in ("demo_address_checked", "demo_buyer_confirmed"):
        st.session_state.pop(key, None)


def render():
    st.subheader("What should the seller do next?")
    st.caption("Synthetic orders · Simulated messages and payments · 15:30 PKT")
    st.button("Reset examples", on_click=_reset)
    address_checked = st.session_state.get("demo_address_checked", False)
    buyer_confirmed = st.session_state.get("demo_buyer_confirmed", False)
    address_column, call_column, advance_column = st.columns(3)
    complete_address = "House 12, Street 4, Gulberg, Lahore"

    address = complete_address if address_checked else "Near Sample Mosque, Lahore"
    address_action = _example("Two cotton shirts", 4500, "Ji theek hai, bhej dein", address, {})
    address_status = "Address reviewed" if address_checked else "Address needs checking"
    _card(address_column, "Order 2047", f"Buyer confirmed · {address_status}", address_action)
    address_column.button("Review the corrected address", disabled=address_checked,
                          on_click=st.session_state.__setitem__, args=("demo_address_checked", True))

    attempt = {"status": "delivered", "started_at": (DEMO_TIME - timedelta(minutes=90)).isoformat()}
    call_action = _example("Kitchen set", 5500, "Ji theek hai, bhej dein" if buyer_confirmed else "",
                           complete_address, attempt)
    _card(call_column, "Order 2048", "Pickup at 16:00 · " + ("Buyer confirmed" if buyer_confirmed else "Message unanswered"),
          call_action)
    call_column.button("Record buyer confirmation", disabled=buyer_confirmed,
                       on_click=st.session_state.__setitem__, args=("demo_buyer_confirmed", True))

    advance_action = _example("Custom embroidered jacket", 4500, "Ji theek hai, bhej dein", complete_address, {})
    _card(advance_column, "Order 2049", "Buyer confirmed · Made-to-order product", advance_action)
