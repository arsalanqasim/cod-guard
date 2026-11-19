"""Normalize Pakistan mobile numbers without inferring a missing number."""

import re


def normalize_phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9][0-9 ()-]{8,39}", value):
        return None
    digits = re.sub(r"[^0-9]", "", value)
    if digits.startswith("0092"):
        digits = digits[2:]
    if digits.startswith("03"):
        digits = "92" + digits[1:]
    return digits if re.fullmatch(r"923[0-9]{9}", digits) else None
