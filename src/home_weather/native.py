"""Required native core; only Python-to-C ABI validation lives here."""
import ctypes
from pathlib import Path
import sys

_suffix = ".dylib" if sys.platform == "darwin" else ".so"
_path = Path(__file__).with_name("libhome_weather_core" + _suffix)
try:
    _lib = ctypes.CDLL(str(_path))
except OSError as exc:
    raise ImportError("Required Rust weather core missing or incompatible. Rebuild with cargo and uv sync --reinstall-package home-weather-mcp.") from exc
_lib.weather_core_abi.restype = ctypes.c_uint32
if _lib.weather_core_abi() != 1:
    raise ImportError("Incompatible Rust weather core ABI; rebuild this package.")
for _name, _args, _result in [
    ("temperature_range", [ctypes.c_double, ctypes.c_double], ctypes.c_double),
    ("is_large", [ctypes.c_double], ctypes.c_int32),
    ("rain_code", [ctypes.c_double], ctypes.c_int32),
    ("rain_likely", [ctypes.c_double] * 4 + [ctypes.c_uint32], ctypes.c_int32),
    ("heat_category", [ctypes.c_double], ctypes.c_uint32),
]:
    _fn = getattr(_lib, "weather_" + _name)
    _fn.argtypes, _fn.restype = _args, _result


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def scalar(value):
    if not number(value):
        return float("nan")
    if isinstance(value, int) and abs(value) > 2**53:
        raise ValueError("Weather integers must be exactly representable in binary64 (abs <= 2**53)")
    try:
        return float(value)
    except OverflowError:
        return float("nan")


def rain_code(code):
    return bool(_lib.weather_rain_code(scalar(code)))


def rain_likely(code, probability, rain, showers):
    values = (code, probability, rain, showers)
    mask = sum(1 << i for i, value in enumerate(values) if number(value))
    result = _lib.weather_rain_likely(*(scalar(value) for value in values), mask)
    return None if result == -1 else bool(result)


def heat_category(high):
    if not isinstance(high, (int, float)):
        raise TypeError("Temperature must be numeric")
    return _lib.weather_heat_category(scalar(float(high) if isinstance(high, bool) else high))
