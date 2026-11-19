"""Sensitivity and oracle diagnostics for the frozen SYNTHETIC benchmark."""
import hashlib

import numpy as np

from risk_engine import assess
from verification import apply_reply

VERIFY_COST = 50
BUDGETS = (10, 20, 30)
CHARGES = (0, VERIFY_COST, 100)
UTILIZATION = (0, 25, 50, 75, 100)
SCENARIOS = {
    # Rates are fixed assumptions for each group, conditional on an attempt
    # to a valid phone. An invalid phone has zero usable replies.
    # (GREEN outreach, genuine confirm, genuine deny, failed confirm, failed deny)
    "no_outreach": (0, 0, 0, 0, 0),
    "flags_only_low": (0, .35, .02, .08, .10),
    "flags_only_mid": (0, .60, .02, .10, .25),
    "limited_green_mid": (.20, .60, .02, .10, .25),
    "broad_outreach_mid": (1, .60, .02, .10, .25),
    "broad_outreach_high": (1, .80, .01, .06, .45),
    "broad_outreach_adverse": (1, .35, .08, .30, .08),
}

# Use the actual verification rule even when no reply arrives.
INTENTS = ("CONFIRM", "DENY", "UNCLEAR")
HOLDS = {zone: [apply_reply(zone, intent)["decision"] != "SHIP" for intent in INTENTS]
         for zone in ("GREEN", "AMBER", "RED")}


def contact_plan(zones, green_rate):
    return np.where(zones == "GREEN", green_rate, 1.0)


def final_hold_probabilities(zones, labels, valid_phone, attempts, response_rates):
    """Integrate assumed intent rates exactly rather than simulating draws.

    Labels select an assumption group only after contact has been planned.
    The dispatch and contact policies receive no outcome labels.
    """
    genuine_confirm, genuine_deny, failed_confirm, failed_deny = response_rates
    usable_attempts = attempts * valid_phone
    confirm = usable_attempts * np.where(labels, failed_confirm, genuine_confirm)
    deny = usable_attempts * np.where(labels, failed_deny, genuine_deny)
    intent_probabilities = np.column_stack((confirm, deny, 1 - confirm - deny))
    decisions = np.array([HOLDS[zone] for zone in zones])
    return (intent_probabilities * decisions).sum(axis=1)


def expected_metrics(labels, holds, attempts, miss_cost, false_flag_cost, charge):
    tp = float(holds[labels].sum())
    fp = float(holds[~labels].sum())
    fn = float((1 - holds[labels]).sum())
    tn = float((1 - holds[~labels]).sum())
    contacts = float(attempts.sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "fp_rate": fp / (fp + tn) if fp + tn else None,
            "fn_rate": fn / (fn + tp) if fn + tp else None,
            "contact_attempts": contacts, "contact_rate": contacts / len(labels),
            "total_cost": fp * false_flag_cost + fn * miss_cost + contacts * charge}


def verification_sensitivity(zones, labels, valid_phone, miss_cost, false_flag_cost):
    results = {}
    for name, (green_rate, *intents) in SCENARIOS.items():
        attempts = (np.zeros(len(zones)) if name == "no_outreach"
                    else contact_plan(zones, green_rate))
        holds = final_hold_probabilities(zones, labels, valid_phone, attempts, intents)
        results[name] = {"green_attempt_rate": green_rate,
                         "genuine_confirm": intents[0], "genuine_deny": intents[1],
                         "failed_confirm": intents[2], "failed_deny": intents[3],
                         **expected_metrics(labels, holds, attempts, miss_cost,
                                            false_flag_cost, VERIFY_COST)}
    return results


def priority_order(scores, eligible, order_ids):
    # Use a deterministic tie-break with neither labels nor row order.
    return sorted(np.flatnonzero(eligible),
                  key=lambda i: (-scores[i], hashlib.sha256(order_ids[i].encode()).digest()))


def take_flags(ranking, size, limit):
    flags = np.zeros(size, dtype=bool)
    flags[ranking[:limit]] = True
    return flags


def rank_policies(ids, scores, signal_counts, model_probabilities, zones):
    return {
        "ship_everything": [],
        "any_signal_ranked": priority_order(scores, signal_counts >= 1, ids),
        "two_signal_rules_ranked": priority_order(scores, signal_counts >= 2, ids),
        "served_capped": priority_order(model_probabilities, zones != "GREEN", ids),
        "cod_guard_ml_ranked": priority_order(model_probabilities, signal_counts >= 2, ids),
    }


def capacity_metrics(batch, policy, budget, utilization, intents, miss_cost, false_flag_cost, charge):
    labels = batch["labels"]
    cap = len(labels) * budget // 100
    flags = take_flags(batch["rankings"][policy], len(labels), cap * utilization // 100)
    # AMBER and RED have the same held/shipped outcome for every reply intent.
    zones = np.where(flags, "AMBER", "GREEN")
    holds = final_hold_probabilities(zones, labels, batch["valid_phone"], flags, intents)
    return {"flagged": int(flags.sum()), "flag_rate": float(flags.mean()),
            **expected_metrics(labels, holds, flags, miss_cost, false_flag_cost, charge)}


def capacity_comparison(validation, test, miss_cost, false_flag_cost):
    """Tune budget utilization on validation, and enforce the hard cap in both batches."""
    rows = []
    for reception in ("no_usable_reply", "flags_only_mid"):
        intents = SCENARIOS["flags_only_mid"][1:] if reception == "flags_only_mid" else (0, 0, 0, 0)
        for budget in BUDGETS:
            for charge in CHARGES:
                policies = {}
                for name, ranking in validation["rankings"].items():
                    options = UTILIZATION if ranking else (0,)
                    args = (intents, miss_cost, false_flag_cost, charge)
                    utilization, val = min(
                        ((u, capacity_metrics(validation, name, budget, u, *args)) for u in options),
                        key=lambda candidate: (candidate[1]["total_cost"], candidate[0]),
                    )
                    policies[name] = {"validation_utilization_pct": utilization,
                                      "validation_cost": val["total_cost"],
                                      **capacity_metrics(test, name, budget, utilization, *args)}
                lowest = min(entry["total_cost"] for entry in policies.values())
                val_lowest = min(entry["validation_cost"] for entry in policies.values())
                winners = [name for name, entry in policies.items()
                           if np.isclose(entry["total_cost"], lowest, rtol=0, atol=1e-7)]
                val_winners = [name for name, entry in policies.items()
                               if np.isclose(entry["validation_cost"], val_lowest, rtol=0, atol=1e-7)]
                rows.append({"budget_pct": budget, "verification_charge": charge,
                             "reception": reception, "observed_test_winners": winners,
                             "validation_winners": val_winners, "policies": policies})
    return rows


def predictability_ceiling(batch, oracle_rows):
    probability = oracle_rows["oracle_probability"].to_numpy()
    ordinary = ~oracle_rows["latent_cluster"].to_numpy()
    flags = batch["zones"] != "GREEN"
    ids = batch["ids"]
    capacity = int(flags.sum())
    eligible = batch["signal_counts"] >= 2
    oracle = take_flags(priority_order(probability, eligible, ids), len(ids), capacity)
    unlimited_signals = take_flags(priority_order(probability, np.ones(len(ids), dtype=bool), ids),
                                  len(ids), capacity)
    eligible_ordinary = priority_order(probability, ordinary, ids)
    ordinary_capacity = int(ordinary.sum()) // 5
    ordinary_top = take_flags(eligible_ordinary, len(ids), ordinary_capacity)
    ordinary_probability = probability[ordinary]
    ordinary_mean = ordinary_probability.mean()
    total_variance = ordinary_mean * (1 - ordinary_mean)
    # Law of total variance splits Bernoulli outcome variance into risk
    # differences and irreducible variance conditional on the oracle's inputs.
    noise_share = (ordinary_probability * (1 - ordinary_probability)).mean() / total_variance
    strata = {}
    for name, mask in (("ordinary", ordinary), ("latent_cluster", ~ordinary)):
        failures = mask & batch["labels"]
        missed = mask & ~flags
        strata[name] = {"orders": int(mask.sum()), "observed_failures": int(failures.sum()),
                        "observed_fn": int((failures & ~flags).sum()),
                        "expected_failures": float(probability[mask].sum()),
                        "expected_fn": float(probability[missed].sum())}
    return {"flag_count": capacity, "flag_rate": float(flags.mean()),
            "served_expected_recall": float(probability[flags].sum() / probability.sum()),
            "oracle_two_signal_expected_recall": float(probability[oracle].sum() / probability.sum()),
            "oracle_unrestricted_expected_recall": float(probability[unlimited_signals].sum() / probability.sum()),
            "ordinary_noise_variance_share": float(noise_share),
            "ordinary_signal_variance_share": float(1 - noise_share),
            "ordinary_oracle_at_20_pct_recall": float(probability[ordinary_top].sum() / ordinary_probability.sum()),
            "ordinary_outreach_rate": ordinary_capacity / int(ordinary.sum()),
            "strata": strata}


def evaluation_batch(frame, probabilities, threshold):
    rows = frame.to_dict("records")
    risks = [assess(order, float(p), threshold) for order, p in zip(rows, probabilities, strict=True)]
    zones = np.array([risk["zone"] for risk in risks])
    counts = np.array([risk["signal_count"] for risk in risks])
    scores = np.array([risk["risk_score"] for risk in risks])
    ids = frame["order_id"].to_numpy()
    return {"zones": zones, "signal_counts": counts, "ids": ids,
            "labels": frame["label_failed"].to_numpy(dtype=bool),
            "valid_phone": frame["phone_valid"].to_numpy(dtype=bool),
            "rankings": rank_policies(ids, scores, counts, probabilities, zones)}


def analyze_round2(validation, test, val_probs, test_probs, threshold, oracle, miss_cost, false_flag_cost):
    val_batch = evaluation_batch(validation, val_probs, threshold)
    test_batch = evaluation_batch(test, test_probs, threshold)
    return {
        "data_source": "SYNTHETIC",
        "verification_charge": VERIFY_COST,
        "verification_sensitivity": verification_sensitivity(
            test_batch["zones"], test_batch["labels"], test_batch["valid_phone"],
            miss_cost, false_flag_cost),
        "capacity_comparison": capacity_comparison(val_batch, test_batch, miss_cost, false_flag_cost),
        "predictability": {
            "validation": predictability_ceiling(val_batch, oracle.loc[validation["order_id"]]),
            "test": predictability_ceiling(test_batch, oracle.loc[test["order_id"]]),
        },
    }


POLICY_LABELS = {
    "ship_everything": "Ship everything",
    "any_signal_ranked": "Any signal",
    "two_signal_rules_ranked": "Two-signal rules",
    "served_capped": "Capped served policy",
    "cod_guard_ml_ranked": "Two-signal ML ranking",
}


def render_round2(report):
    scenarios = report["verification_sensitivity"]
    charge = report["verification_charge"]
    lines = ["", "## Round 2A · Verification sensitivity on SYNTHETIC orders", "",
             "Scenario analysis uses hypothetical recognized intents. It measures neither human behavior nor "
             "speech recognition accuracy. The service's existing decision function maps confirmation to SHIP and "
             "denial to HOLD_CANCEL. Unclear, ignored or unreachable replies keep the zone's default. "
             "The contact plan uses only the zone: every non-GREEN order gets an attempt except in the zero-outreach "
             "control. GREEN outreach is uniform at the stated rate, independent of the outcome. This estimates "
             "what could happen if otherwise-passing orders also received a confirmation prompt.", "",
             "The confirm/deny rates are fixed inputs specified below for each synthetic outcome group and applied "
             "only after outreach is assigned. No rates are fitted to benchmark labels. Rates apply per attempt "
             "to a valid phone. Invalid phones receive no usable intent, but still incur the assumed attempt cost. "
             "The remaining probability is no usable reply. Confirmations from failed orders and denials from "
             "genuine orders are allowed. Counts and costs are exact expectations under the assumptions, so "
             "counts may be fractional. There is no sampling uncertainty estimate for the scenario assumptions.", "",
             f"Illustrative cost includes FP/FN costs and PKR {charge} per attempted contact. An unresolved "
             "verification request is counted as held at the dispatch decision point.", "",
             "| Scenario | GREEN outreach | Genuine confirm / deny | Failed confirm / deny | Attempts | Expected FP | Expected FN | FPR | FNR | Cost PKR |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, row in scenarios.items():
        lines.append(f"| {name.replace('_', ' ')} | {row['green_attempt_rate']:.0%} | "
                     f"{row['genuine_confirm']:.0%} / {row['genuine_deny']:.0%} | "
                     f"{row['failed_confirm']:.0%} / {row['failed_deny']:.0%} | {row['contact_attempts']:,.1f} | "
                     f"{row['fp']:.2f} | {row['fn']:.2f} | {row['fp_rate']:.2%} | {row['fn_rate']:.2%} | "
                     f"{row['total_cost']:,.2f} |")
    outreach = [row for name, row in scenarios.items() if name != "no_outreach"]
    low_fpr, high_fpr = min(r["fp_rate"] for r in outreach), max(r["fp_rate"] for r in outreach)
    low_fnr, high_fnr = min(r["fn_rate"] for r in outreach), max(r["fn_rate"] for r in outreach)
    low_cost, high_cost = min(r["total_cost"] for r in outreach), max(r["total_cost"] for r in outreach)
    lines += ["", f"Across these six outreach assumptions, FPR is **{low_fpr:.2%} to {high_fpr:.2%}**, "
              f"FNR is **{low_fnr:.2%} to {high_fnr:.2%}**, and illustrative cost is "
              f"**PKR {low_cost:,.2f} to {high_cost:,.2f}**. Flags-only outreach rescues some genuine holds "
              "and lets some failed orders through when they confirm. The passed orders still ship. "
              "At the same mid-rate assumptions, broad outreach changes FNR from "
              f"**{scenarios['flags_only_mid']['fn_rate']:.2%}** to "
              f"**{scenarios['broad_outreach_mid']['fn_rate']:.2%}**. Its cost and errors rise under "
              "the adverse reply assumptions.", "",
              "## Round 2B · Equal flag budgets on SYNTHETIC orders", "",
              "Every flag consumes one attempted verification. Caps are 10%, 20%, and 30% of orders, rounded "
              "down separately in each batch. For each policy, cap, price and response setting, validation chooses "
              "among 0%, 25%, 50%, 75%, and 100% of its permitted slots. The choice is frozen before scoring the "
              "test batch. Rankings use available pre-dispatch features only, with SHA-256 of order ID as a "
              "deterministic tie-break. The test winners are retrospective comparisons. Validation winners are "
              "listed separately.", "",
              "Any signal ranks orders with at least one adverse group by rule points. Two-signal rules uses the "
              "same points with a two-group minimum. The capped served policy ranks its existing AMBER/RED pool "
              "by model probability. Two-signal ML ranking gives the model the entire two-group pool to rank. "
              "These are batch comparisons. The service still uses its original threshold and decision rules.", "",
              "PKR 0, 50 and 100 per flag are illustrative. Each policy faces the same two response settings. "
              "With no usable reply, flags remain held. With the flags-only mid assumption from A, every flag "
              "can receive an override at the same assumed rates, including the baseline flags. Passed orders "
              "receive no contact in B.", "",
              "| Response setting | Cap | Charge PKR | Validation winner(s) | Test winner(s) | Test cost PKR |",
              "|---|---:|---:|---|---|---:|"]
    budgets = report["capacity_comparison"]
    for row in budgets:
        observed = row['observed_test_winners']
        val_winners = ', '.join(POLICY_LABELS[name] for name in row['validation_winners'])
        winners = ', '.join(POLICY_LABELS[name] for name in observed)
        cost = row['policies'][observed[0]]['total_cost']
        lines.append(f"| {row['reception'].replace('_', ' ')} | {row['budget_pct']}% | "
                     f"{row['verification_charge']} | {val_winners} | {winners} | {cost:,.2f} |")
    lines += ["", f"Results at PKR {charge} per attempt:", "",
              "| Response setting | Cap | Policy | Flags (% of orders) | FPR | FNR | Cost PKR |",
              "|---|---:|---|---:|---:|---:|---:|"]
    for row in budgets:
        if row['verification_charge'] != charge:
            continue
        for name, policy in row['policies'].items():
            lines.append(f"| {row['reception'].replace('_', ' ')} | {row['budget_pct']}% | {POLICY_LABELS[name]} | "
                         f"{policy['flagged']} ({policy['flag_rate']:.2%}) | {policy['fp_rate']:.2%} | "
                         f"{policy['fn_rate']:.2%} | {policy['total_cost']:,.2f} |")
    lines += ["", "The evaluation JSON contains per-policy counts and validation utilization for every charge. "
              "These comparisons depend on the specified rankings, sample, cost weights and assumed responses.", "",
              "## Round 2C · Generator-based predictability ceiling", "",
              "The optimistic oracle knows the generator's latent cluster and structural logit, including its fixed "
              "calibration offset. It integrates out the private per-order Gaussian draw with 24-point "
              "Gauss–Hermite quadrature and cannot see the final Bernoulli draw. Its risk ranking is optimal "
              "for expected failures caught at a fixed budget. Latent cluster membership is unavailable in "
              "serving. Oracle data is reconstructed separately from the generator, checked against the "
              "benchmark, and excluded from fitting, model selection and the model bundle.", "",
              "| Split | Served flags | Served expected recall | Oracle, two-signal eligible | Oracle, unrestricted |",
              "|---|---:|---:|---:|---:|"]
    for split, ceiling in report["predictability"].items():
        lines.append(f"| {split} | {ceiling['flag_count']} ({ceiling['flag_rate']:.2%}) | "
                     f"{ceiling['served_expected_recall']:.2%} | {ceiling['oracle_two_signal_expected_recall']:.2%} | "
                     f"{ceiling['oracle_unrestricted_expected_recall']:.2%} |")
    validation = report['predictability']['validation']
    gap = (validation['oracle_two_signal_expected_recall'] - validation['served_expected_recall']) * 100
    test = report['predictability']['test']
    lines += ["", f"On validation, the equal-capacity oracle gains **{gap:.2f} percentage points** under "
              "the existing guard. This small gap supports keeping the served model and threshold.", "",
              "| Generator stratum on test | Orders | Observed failures | Observed FN | Expected failures | Expected FN |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, row in test['strata'].items():
        lines.append(f"| {name.replace('_', ' ')} | {row['orders']} | {row['observed_failures']} | "
                     f"{row['observed_fn']} | {row['expected_failures']:.2f} | {row['expected_fn']:.2f} |")
    lines += ["", f"Within ordinary synthetic orders, structural risk differences explain "
              f"**{test['ordinary_signal_variance_share']:.2%}** of generated binary-outcome variance. "
              f"**{test['ordinary_noise_variance_share']:.2%}** remains conditional variance even with oracle "
              "information. This is a variance decomposition, not a count of inherently detectable orders.", "",
              f"A defensible stall claim: with a budget to screen about 20% of ordinary orders, even our "
              f"generator-informed oracle captures only **{test['ordinary_oracle_at_20_pct_recall']:.2%}** of their "
              f"expected failures, compared with **{test['ordinary_outreach_rate']:.2%}** for random screening "
              "at the same budget. The remaining expected failures are outside that screen. Useful new "
              "information such as a customer denial can help. It does not guarantee recovery."]
    return lines
