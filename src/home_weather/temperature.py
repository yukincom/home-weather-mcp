"""Deterministic daily temperature-range signal for conversational advice."""

import math

THRESHOLD_C = 7.0


def temperature_range(high, low):
    valid = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value)
        for value in (high, low)
    )
    delta = round(high - low, 10) if valid and high >= low else None
    return {
        "basis": "daily_max_minus_min",
        "value_c": delta,
        "threshold_c": THRESHOLD_C,
        "is_large": delta >= THRESHOLD_C if delta is not None else None,
    }
