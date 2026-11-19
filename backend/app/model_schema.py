"""Validate the trusted estimator bundle before publishing model availability."""
from numbers import Real

import numpy as np
import pandas as pd

from risk_engine import DEFAULTS, OPTIONAL_MODEL_FEATURES


def probabilities(bundle, frame):
    result = np.asarray(bundle["model"].predict_proba(frame))
    if (result.shape != (len(frame), 2) or not np.isfinite(result).all()
            or (result < 0).any() or (result > 1).any()):
        raise ValueError("Model prediction must have two finite probability columns")
    return result[:, 1]


def validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise ValueError("Model bundle must be a dictionary")
    threshold = bundle.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, Real) or not 0 < threshold < 1:
        raise ValueError("Model threshold must be numeric and between zero and one")
    columns, model = bundle.get("columns"), bundle.get("model")
    features = DEFAULTS.keys() | OPTIONAL_MODEL_FEATURES
    if (not isinstance(columns, (list, tuple)) or not all(isinstance(key, str) for key in columns)
            or len(set(columns)) != len(columns) or not features.issubset(columns)
            or any(key not in features and not key.startswith("city_") for key in columns)
            or list(getattr(model, "feature_names_in_", ())) != list(columns)
            or getattr(model, "n_features_in_", None) != len(columns)
            or list(getattr(model, "classes_", ())) != [0, 1]):
        raise ValueError("Model schema does not match the published feature columns and classes")
    probabilities(bundle, pd.DataFrame([[0] * len(columns)], columns=columns))
    return bundle
