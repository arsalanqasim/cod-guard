import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from verification import parse_reply, apply_reply, opening_message

def test_parse_replies():
    assert parse_reply("Yes confirm") == "CONFIRM"
    assert parse_reply("Ji theek hai, bhej dein") == "CONFIRM"
    assert parse_reply("جی ٹھیک ہے") == "CONFIRM"
    assert parse_reply("No, I didn't order this") == "DENY"
    assert parse_reply("Nahi, mera order nahi hai") == "DENY"
    assert parse_reply("نہیں") == "DENY"
    assert parse_reply("Kal bataunga") == "UNCLEAR"

def test_confirmation_rescues_flagged_order():
    # FP recovery: model said RED, customer confirms -> SHIP
    assert apply_reply("RED", "CONFIRM")["decision"] == "SHIP"

def test_denial_stops_clean_order():
    # FN recovery: model said GREEN, customer denies -> HOLD_CANCEL
    assert apply_reply("GREEN", "DENY")["decision"] == "HOLD_CANCEL"

def test_unclear_amber_waits():
    assert apply_reply("AMBER", "UNCLEAR")["decision"] == "VERIFY_FIRST"
    assert apply_reply("RED", "UNCLEAR")["decision"] == "HOLD"
    assert apply_reply("GREEN", "UNCLEAR")["decision"] == "SHIP"

def test_opening_message_mentions_order():
    m = opening_message({"customer_name": "Ali", "order_id": "CG-1",
                         "amount_pkr": 3500, "items_count": 2})
    assert "CG-1" in m and "3500" in m and "YES" in m

if __name__ == "__main__":
    test_parse_replies()
    test_confirmation_rescues_flagged_order()
    test_denial_stops_clean_order()
    test_unclear_amber_waits()
    test_opening_message_mentions_order()
    print("5/5 tests passed")
