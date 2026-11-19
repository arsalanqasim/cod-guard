"""Seed the exhibition demo orders: 80 sampled benchmark orders dressed
with synthetic customer names and products. The original generated label
is retained for provenance. Marked operator outcomes drive live demo metrics.
Run: python scripts/seed_demo.py
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ["Ali Raza", "Fatima Noor", "Usman Tariq", "Ayesha Khan", "Bilal Ahmed",
         "Zainab Bibi", "Hassan Javed", "Mahnoor Aslam", "Omar Farooq", "Hira Shahid",
         "Danish Ali", "Sana Iqbal", "Talha Mehmood", "Iqra Naseem", "Shahzaib Anwar"]
PRODUCTS = ["Wireless Earbuds", "Winter Jacket", "Skincare Set", "Running Shoes",
            "Smart Watch", "Cotton Kurti", "Phone Cover + Glass", "Hair Dryer",
            "Kitchen Blender", "Prayer Mat Set", "Leather Wallet", "Abaya"]

df = pd.read_csv(ROOT / "data/benchmark_orders.csv").sample(80, random_state=3).reset_index(drop=True)
df["customer_name"] = [NAMES[i % len(NAMES)] for i in range(len(df))]
df["product"] = [PRODUCTS[i % len(PRODUCTS)] for i in range(len(df))]
df["phone"] = [("03" + str(200000000 + i * 137913)[:9]) if row.phone_valid else "invalid-demo-phone"
               for i, row in df.iterrows()]
df.to_csv(ROOT / "data/demo_orders.csv", index=False)
print(f"Seeded {len(df)} demo orders -> data/demo_orders.csv "
      f"(failed ground-truth rate {df.label_failed.mean():.2f})")
