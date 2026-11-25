import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "app"))
from risk_engine import assess

def test_clean_order_is_green():
    o = {"phone_valid": 1, "phone_fraud_history": 0, "phone_velocity_24h": 0,
         "address_words": 12, "address_has_landmark": 1, "amount_pkr": 3500,
         "order_hour": 14, "customer_past_delivered": 4, "customer_past_refusals": 0}
    r = assess(o)
    assert r["zone"] == "GREEN", r

def test_single_weak_signal_does_not_block():
    o = {"phone_valid": 1, "phone_fraud_history": 0, "phone_velocity_24h": 0,
         "address_words": 3, "address_has_landmark": 0, "amount_pkr": 2500,
         "order_hour": 15, "customer_past_delivered": 0, "customer_past_refusals": 0}
    r = assess(o)
    assert r["zone"] in ("GREEN", "AMBER"), r   # short address alone never RED

def test_fraud_phone_plus_refusals_is_red():
    o = {"phone_valid": 1, "phone_fraud_history": 1, "phone_velocity_24h": 3,
         "address_words": 8, "address_has_landmark": 1, "amount_pkr": 9000,
         "order_hour": 13, "customer_past_delivered": 0, "customer_past_refusals": 2}
    r = assess(o)
    assert r["zone"] == "RED", r
    assert r["reasons"], "every flag must explain itself"

if __name__ == "__main__":
    test_clean_order_is_green()
    test_single_weak_signal_does_not_block()
    test_fraud_phone_plus_refusals_is_red()
    print("3/3 tests passed")
