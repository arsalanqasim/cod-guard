"""Project the Kaggle COD line-item archive into isolated order cohorts."""
import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

DATA_FILE = "Pakistan Largest Ecommerce Dataset.csv"
ORDER = "increment_id"
CUSTOMER = "Customer ID"
FIELDS = [ORDER, CUSTOMER, "created_at", "item_id", "status", "grand_total", "qty_ordered", "payment_method"]
LABELS = {"complete": 0, "canceled": 1, "refund": 1, "order_refunded": 1}
FEATURES = ("amount_pkr", "items_count", "is_repeat_customer")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_orders(archive, *, include_purchase_history=False):
    fields = FIELDS + ["sku", "discount_amount"] if include_purchase_history else FIELDS
    with zipfile.ZipFile(archive) as package, package.open(DATA_FILE) as csv:
        lines = pd.read_csv(csv, encoding="latin-1", usecols=fields, dtype="string").dropna(how="all", subset=FIELDS)
    is_cod = lines["payment_method"].str.strip().str.casefold().eq("cod").fillna(False)
    cod = lines.loc[is_cod].copy()
    source = {"raw_lines": len(lines), "raw_orders": lines[ORDER].nunique(),
              "raw_customers": lines[CUSTOMER].nunique(), "cod_lines": len(cod),
              "cod_orders": cod[ORDER].nunique(), "cod_customers": cod[CUSTOMER].nunique()}
    non_cod = set(lines.loc[~is_cod, ORDER].dropna())
    cod["day"] = pd.to_datetime(cod["created_at"], format="mixed", errors="coerce").dt.normalize()
    cod["amount"] = pd.to_numeric(cod["grand_total"], errors="coerce")
    cod["quantity"] = pd.to_numeric(cod["qty_ordered"], errors="coerce")
    cod["label"] = cod["status"].str.strip().str.casefold().map(LABELS)
    cod["valid"] = (cod[CUSTOMER].notna() & cod["day"].notna() & cod["item_id"].notna()
                    & ~cod["item_id"].duplicated(keep=False) & ~cod[ORDER].isin(non_cod)
                    & np.isfinite(cod["amount"]) & (cod["amount"] > 0)
                    & np.isfinite(cod["quantity"]) & (cod["quantity"] > 0) & (cod["quantity"] % 1 == 0)).fillna(False)
    basket_details = {}
    if include_purchase_history:
        cod["discount"] = pd.to_numeric(cod["discount_amount"], errors="coerce")
        cod.loc[~np.isfinite(cod["discount"]) | cod["discount"].lt(0), "discount"] = np.nan
        cod["sku"] = cod["sku"].str.strip().replace("", pd.NA)
        basket_details = {"distinct_skus": ("sku", "nunique"), "max_line_discount": ("discount", "max")}
    orders = cod.groupby(ORDER, sort=True).agg(
        customer_id=(CUSTOMER, "first"), customers=(CUSTOMER, "nunique"),
        order_day=("day", "first"), days=("day", "nunique"),
        amount_pkr=("amount", "min"), max_amount=("amount", "max"), items_count=("quantity", "sum"),
        all_valid=("valid", "all"), lines=("valid", "size"),
        labeled=("label", "count"), label_low=("label", "min"), label_high=("label", "max"), **basket_details,
    ).reset_index(names="order_id")
    structurally_valid = (orders["all_valid"] & orders["customers"].eq(1) & orders["days"].eq(1)
                          & orders["amount_pkr"].eq(orders["max_amount"]))
    orders = orders.loc[structurally_valid].copy()
    first_day = orders.groupby("customer_id")["order_day"].transform("min")
    orders["is_repeat_customer"] = orders["order_day"].gt(first_day).astype(int)
    complete = orders["labeled"].eq(orders["lines"])
    unanimous = orders["label_low"].eq(orders["label_high"])
    source.update(invalid_cod_orders=int((~structurally_valid).sum()),
                  incomplete_label_orders=int((~complete).sum()),
                  mixed_label_orders=int((complete & ~unanimous).sum()))
    result = orders.loc[complete & unanimous, ["order_id", "customer_id", "order_day", *FEATURES]].copy()
    result["label_failed"] = orders.loc[result.index, "label_low"].astype(int)
    result["items_count"] = result["items_count"].astype(int)
    result["amount_pkr"] = result["amount_pkr"].astype(float)
    if include_purchase_history:
        # Purchase history includes structurally valid baskets regardless of terminal status.
        purchases = orders[["order_id", "customer_id", "order_day", "amount_pkr", "lines",
                            "distinct_skus", "max_line_discount"]]
        return result, source, purchases
    return result, source


def split_customers_and_time(orders):
    days = orders["order_day"].value_counts().sort_index().cumsum()
    end_train, end_val = (days.index[days.searchsorted(len(orders) * fraction)] for fraction in (.60, .80))
    if end_train >= end_val or end_val >= days.index[-1]:
        raise ValueError("Need at least three date windows for chronological validation")

    def cohort(customer):
        digest = hashlib.sha256(f"cod-guard-round9-v1:{customer}".encode()).digest()
        bucket = int.from_bytes(digest[:8], "big") % 100
        return 0 if bucket < 60 else 1 if bucket < 80 else 2

    membership = orders["customer_id"].map({key: cohort(key) for key in orders["customer_id"].unique()})
    date = orders["order_day"]
    windows = (date <= end_train, (date > end_train) & (date <= end_val), date > end_val)
    splits = [orders.loc[window & membership.eq(index)].sort_values(["order_day", "order_id"]).reset_index(drop=True)
              for index, window in enumerate(windows)]
    if any(split.empty or split["label_failed"].nunique() < 2 for split in splits):
        raise ValueError("Each chronological, customer-disjoint split must contain both outcomes")
    return splits


def validation_partitions(val):
    days = val["order_day"].value_counts().sort_index().cumsum()
    cutoff = days.index[days.searchsorted(len(val) / 2)]
    return val.loc[val["order_day"] <= cutoff], val.loc[val["order_day"] > cutoff]


def describe(frame):
    # Only the aggregate hash leaves the private evaluation directory.
    body = frame[["order_id", "customer_id", "order_day", *FEATURES, "label_failed"]].to_csv(
        index=False, lineterminator="\n", date_format="%Y-%m-%d")
    return {"orders": len(frame), "customers": frame["customer_id"].nunique(),
            "failed": int(frame["label_failed"].sum()), "start": frame["order_day"].min().date().isoformat(),
            "end": frame["order_day"].max().date().isoformat(),
            "sha256": hashlib.sha256(body.encode()).hexdigest()}


def frozen_manifest(archive, orders, source, splits):
    names = ("train", "validation", "test")
    return {"schema_version": 1, "dataset": "[PK-REAL]", "archive_sha256": sha256(archive),
            "source_counts": {**source, "eligible_orders": len(orders),
                              "discarded_to_isolate_windows": len(orders) - sum(map(len, splits))},
            "splits": {name: describe(split) for name, split in zip(names, splits)}}
