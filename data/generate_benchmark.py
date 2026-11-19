"""Generate the COD-Guard benchmark dataset.

SYNTHETIC data, calibrated to published Pakistani COD statistics
(OrderNation's single-retailer funnel reports approximately 49–57 cash
collections per 100 COD orders across different measurement windows and
37.3% COD cancellation). The low end sets the simulation's non-collection
target. The generated records support synthetic model evaluation.

The generator assumes a small high-risk cluster with correlated phone,
velocity, address, and timing features, plus ordinary orders with weaker
features. Label 1 represents simulated non-collection. Label 0 represents
simulated delivery.

Run:  python data/generate_benchmark.py
Out:  data/benchmark_orders.csv
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_FAILURE_RATE = 0.51  # Low cash-collection estimate implies 51% non-collection.

N = 6000

CITIES = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad",
          "Multan", "Peshawar", "Quetta", "Hyderabad", "Sialkot"]
CITY_RISK = np.array([0.55, 0.50, 0.35, 0.45, 0.55, 0.55, 0.60, 0.65, 0.55, 0.50])

def generate_benchmark():
    """Return the original benchmark and separate, evaluation-only oracle data."""
    RNG = np.random.default_rng(42)
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

    # Keep the original random draw order for the committed benchmark.
    cluster_noise = RNG.normal(0, 0.35, N)
    ordinary_mean = (
        -0.70
        + 0.35 * past_refusals
        + 0.9 * (past_refusals >= 2)
        + 1.0 * (~phone_valid).astype(float)
        - 0.30 * np.minimum(past_delivered, 6)
        - 0.06 * address_words
        - 0.35 * address_landmark
        + 0.70 * (CITY_RISK[city_idx] - 0.5)
        + 0.30 * (amount > 20000)
        + 0.25 * late_night
    )
    ordinary_noise = RNG.normal(0, 0.40, N)
    logit = np.where(fc, 1.75 + cluster_noise, ordinary_mean + ordinary_noise)
    # Calibrate expected aggregate non-collection to 51%, keeping the latent
    # organised cluster unchanged. This is a synthetic modelling assumption,
    # not a fit to individual merchant records or a claim about fraud prevalence.
    low, high = -10.0, 10.0
    for _ in range(70):
        offset = (low + high) / 2
        p_fail = 1 / (1 + np.exp(-np.where(fc, logit, logit + offset)))
        if p_fail.mean() < TARGET_FAILURE_RATE:
            low = offset
        else:
            high = offset
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
        "data_source": "SYNTHETIC",
    })
    # Integrate out each order's private Gaussian draw before the Bernoulli label.
    # The oracle knows the latent cluster and formula, but never sees those draws.
    nodes, weights = np.polynomial.hermite.hermgauss(24)
    mean = np.where(fc, 1.75, ordinary_mean + offset)
    scale = np.where(fc, 0.35, 0.40)
    logits = mean[:, None] + np.sqrt(2) * scale[:, None] * nodes
    oracle_probability = (1 / (1 + np.exp(-logits))) @ weights / np.sqrt(np.pi)
    audit = pd.DataFrame({"order_id": df["order_id"], "latent_cluster": fc,
                          "oracle_probability": oracle_probability})
    return df, audit


def main():
    df, _ = generate_benchmark()
    df.to_csv(ROOT / "data/benchmark_orders.csv", index=False)
    print(f"rows={len(df)}  failed_rate={df.label_failed.mean():.3f}  "
          f"delivered_rate={1 - df.label_failed.mean():.3f}")
    print(f"Expected non-collection target={TARGET_FAILURE_RATE:.3f}; all records and labels are SYNTHETIC")
    print("Saved data/benchmark_orders.csv  (SYNTHETIC, calibrated to OrderNation stats)")


if __name__ == "__main__":
    main()
