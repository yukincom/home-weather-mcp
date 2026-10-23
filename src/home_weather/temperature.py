"""Public result adapter for the required Rust temperature-range calculation."""
import math
from .native import _lib, scalar

THRESHOLD_C = 7.0


def temperature_range(high, low):
    if type(high) is int and type(low) is int and abs(high - low) > 2**53:
        raise ValueError("Temperature difference exceeds exact binary64 integer range")
    delta = _lib.weather_temperature_range(scalar(high), scalar(low))
    flag = _lib.weather_is_large(delta)
    return {
        "basis": "daily_max_minus_min",
        "value_c": delta if math.isfinite(delta) else None,
        "threshold_c": THRESHOLD_C,
        "is_large": None if flag == -1 else bool(flag),
    }
