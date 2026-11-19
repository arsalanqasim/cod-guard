"""Generate the COD-Guard benchmark dataset.

SYNTHETIC data, calibrated to published Pakistani COD statistics
(OrderNation study of ~170k orders from one Pakistani retailer:
37.3% of COD orders cancelled; only ~49 of 100 COD orders end in cash
collected). This is NOT real merchant data and must never be presented
as such. It exists so the risk engine can be trained and its false
positives / false negatives measured honestly.

Structure (how fake COD orders actually behave): a minority cluster of
organised fake orders (fraud phone history, several orders in a day,
thin address, late-night placement) that fail ~85% of the time, plus
ordinary orders whose failures are refusals/cancellations driven by
weaker signals. Label: 1 = failed/fake/refused, 0 = delivered.

Run:  python data/generate_benchmark.py
Out:  data/benchmark_orders.csv
"""
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
N = 6000

CITIES = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad",
          "Multan", "Peshawar", "Quetta", "Hyderabad", "Sialkot"]
CITY_RISK = np.array([0.55, 0.50, 0.35, 0.45, 0.55, 0.55, 0.60, 0.65, 0.55, 0.50])

city_idx = RNG.integers(0, len(CITIES), N)
fraud_cluster = RNG.random(N) < 0.13

is_repeat = RNG.random(N) < 0.35
past_delivered = np.where(is_repeat, RNG.integers(1, 12, N), 0)
past_refusals = np.where(is_repeat, RNG.poisson(0.4, N), 0)
phone_valid = RNG.random(N) < 0.93
phone_fraud_history = (RNG.random(N) < 0.05).astype(int)
phone_velocity = RNG.poisson(0.6, N)
address_words = np.clip(RNG.normal(9, 4, N), 1, 25).astype(int)
address_landmark = (RNG.random(N) < 0.55).astype(int)
amount = np.clip(RNG.lognormal(mean=8.0, sigma=0.7, size=N), 500, 60000).round(0)
items = RNG.integers(1, 7, N)
hour = RNG.integers(0, 24, N)

# Fraud-cluster orders carry clustered bad signals.
fc = fraud_cluster
phone_fraud_history[fc] = (RNG.random(fc.sum()) < 0.70).astype(int)
phone_velocity[fc] = RNG.poisson(3.2, fc.sum())
address_words[fc] = np.clip(RNG.normal(4.5, 1.8, fc.sum()), 1, 25).astype(int)
address_landmark[fc] = (RNG.random(fc.sum()) < 0.25).astype(int)
phone_valid[fc] = RNG.random(fc.sum()) < 0.80
hour[fc] = RNG.choice([0, 1, 2, 3, 13, 21, 22, 23], fc.sum())
past_delivered[fc] = 0

late_night = ((hour >= 0) & (hour <= 4)).astype(int)

logit = np.where(
    fc,
    1.75 + RNG.normal(0, 0.35, N),                       # organised fakes: fail ~85%
    -0.70                                                # ordinary orders: base ~33% fail
    + 0.35 * past_refusals
    + 0.9 * (past_refusals >= 2)
    + 1.0 * (~phone_valid).astype(float)
    - 0.30 * np.minimum(past_delivered, 6)
    - 0.06 * address_words
    - 0.35 * address_landmark
    + 0.70 * (CITY_RISK[city_idx] - 0.5)
    + 0.30 * (amount > 20000)
    + 0.25 * late_night
    + RNG.normal(0, 0.40, N),
)
p_fail = 1 / (1 + np.exp(-logit))
label = (RNG.random(N) < p_fail).astype(int)

df = pd.DataFrame({
    "order_id": [f"CG-{i:05d}" for i in range(N)],
    "city": [CITIES[i] for i in city_idx],
    "phone_valid": phone_valid.astype(int),
    "phone_fraud_history": phone_fraud_history,
    "phone_velocity_24h": phone_velocity,
    "address_words": address_words,
    "address_has_landmark": address_landmark,
    "amount_pkr": amount.astype(int),
    "items_count": items,
    "order_hour": hour,
    "is_repeat_customer": is_repeat.astype(int),
    "customer_past_delivered": past_delivered,
    "customer_past_refusals": past_refusals,
    "label_failed": label,
})
df.to_csv("data/benchmark_orders.csv", index=False)
print(f"rows={len(df)}  failed_rate={df.label_failed.mean():.3f}  "
      f"delivered_rate={1 - df.label_failed.mean():.3f}")
print("Saved data/benchmark_orders.csv  (SYNTHETIC, calibrated to OrderNation stats)")
