"""Calibrated model-first policy and exact additive tree-path explanations."""
from dataclasses import dataclass
from math import isfinite

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

FEATURES = ("amount_pkr", "items_count", "is_repeat_customer")
FEATURE_TITLES = ("Order amount", "Number of items", "Repeat purchase history")


@dataclass(frozen=True)
class Bands:
    verify_at: float
    hold_at: float

    def __post_init__(self):
        values = (self.verify_at, self.hold_at)
        if any(type(value) not in (int, float) or not isfinite(value) for value in values):
            raise ValueError("Policy thresholds must be finite numbers")
        if not 0 <= self.verify_at < self.hold_at <= 1:
            raise ValueError("Policy thresholds must satisfy 0 <= verify_at < hold_at <= 1")


@dataclass(frozen=True)
class CalibratedRisk:
    model: GradientBoostingClassifier
    calibrator: IsotonicRegression | LogisticRegression
    method: str

    def predict(self, frame):
        scores = self.model.decision_function(frame)
        return calibrate(self.calibrator, self.method, scores)

    def explain(self, values):
        deltas = np.zeros(len(FEATURES))
        for tree in self.model.estimators_[:, 0]:
            split = tree.tree_
            node = 0
            while split.children_left[node] != split.children_right[node]:
                feature = split.feature[node]
                child = (split.children_left[node] if np.float32(values[feature]) <= split.threshold[node]
                         else split.children_right[node])
                deltas[feature] += self.model.learning_rate * (split.value[child, 0, 0] - split.value[node, 0, 0])
                node = child
        return [{"feature": FEATURES[index], "log_odds_delta": round(float(deltas[index]), 6),
                 "reason": f"{FEATURE_TITLES[index]} {'raised' if deltas[index] > 0 else 'lowered'} the model estimate"}
                for index in sorted(range(len(deltas)), key=lambda i: -abs(deltas[i]))
                if abs(deltas[index]) >= 0.000001]


def calibrate(calibrator, method, scores):
    values = (calibrator.predict(scores) if method == "isotonic"
              else calibrator.predict_proba(np.asarray(scores).reshape(-1, 1))[:, 1])
    return np.clip(values, 0.000001, 0.999999)


def fit_model(train, calibration, validation):
    model = GradientBoostingClassifier(n_estimators=90, max_depth=2, learning_rate=0.06,
                                       min_samples_leaf=15, random_state=9)
    model.fit(train[list(FEATURES)], train["label_failed"])
    raw = model.decision_function(calibration[list(FEATURES)])
    outcomes = calibration["label_failed"]
    candidates = {
        "platt": LogisticRegression().fit(raw.reshape(-1, 1), outcomes),
        "isotonic": IsotonicRegression(out_of_bounds="clip").fit(raw, outcomes),
    }
    raw_val = model.decision_function(validation[list(FEATURES)])
    errors = {key: float(np.mean((calibrate(predictor, key, raw_val) - validation["label_failed"]) ** 2))
              for key, predictor in candidates.items()}
    method = min(errors, key=errors.get)
    return CalibratedRisk(model, candidates[method], method), errors


def decide(score, bands, *, intent=None, phone_valid=None, queue_status="open"):
    if score is None:
        band, action = "unscored", "VERIFY_FIRST"
    elif score >= bands.hold_at:
        band, action = "operator_hold", "HOLD"
    elif score >= bands.verify_at:
        band, action = "verify", "VERIFY_FIRST"
    else:
        band, action = "auto_dispatch", "SHIP"
    reasons = ["Required model evidence missing"] if score is None else []
    if intent == "DENY":
        action = "HOLD_CANCEL"
        reasons.append("Buyer denial always holds the order")
    elif queue_status != "open":
        action = "HOLD"
        reasons.append("Order is outside the active storefront queue")
    elif phone_valid == 0:
        action = "VERIFY_FIRST"
        reasons.append("Unreachable phone requires another verification channel")
    elif intent == "CONFIRM" and band in ("verify", "unscored"):
        action = "SHIP"
        reasons.append("Buyer confirmation releases the verification hold")
    return {"calibrated_score": score, "band": band, "proposed_decision": action, "policy_rules": reasons}
