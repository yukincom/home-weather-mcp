"""Independent reference comparisons against pre-migration weather rules."""
import itertools
import math
import random
import pytest
from home_weather.native import rain_likely, heat_category
from home_weather.temperature import temperature_range


def test_range_matches_python_rounding():
    rng = random.Random(20261023)
    pairs = [(rng.uniform(-150, 150), rng.uniform(-150, 150)) for _ in range(10000)]
    pairs += [(7 + offset, 0) for offset in [-1e-9, -5e-11, 0, 5e-11, 1e-9]]
    pairs += [(0.12345678905, 0), (0.12345678915, 0), (1e308, 0)]
    for high, low in pairs:
        expected = round(high - low, 10) if high >= low else None
        actual = temperature_range(high, low)
        assert actual['value_c'] == expected
        assert actual['is_large'] == (expected >= 7 if expected is not None else None)


def test_rain_matches_old_rules():
    codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    def numeric(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    for code, probability, rain, showers in itertools.product(
        [None, False, 0, 61, 61.5, 71, float('nan')],
        [None, True, 0, 49.9, 50, float('nan')],
        [None, False, -1, 0, .1], [None, 0, .1]
    ):
        expected = (code in codes or any(numeric(x) and x > 0 for x in (rain, showers))
                    or (numeric(probability) and probability >= 50))
        if not any(numeric(x) for x in (code, probability, rain, showers)):
            expected = None
        assert rain_likely(code, probability, rain, showers) == expected


@pytest.mark.parametrize('high,category', [(10, 0), (10.1, 1), (18, 1), (18.1, 2), (26, 2), (26.1, 3), (29, 3), (29.1, 4)])
def test_heat_boundaries(high, category):
    assert heat_category(high) == category


def test_overflowing_difference_is_unknown():
    assert temperature_range(1e308, -1e308)['value_c'] is None


def test_missing_library_has_no_python_fallback(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    native = Path(__file__).resolve().parents[1] / 'src/home_weather/native.py'
    isolated = tmp_path / 'native.py'
    isolated.write_text(native.read_text())
    result = subprocess.run([sys.executable, '-I', str(isolated)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Required Rust weather core missing' in result.stderr


def test_large_integer_precision_is_not_silently_lost():
    with pytest.raises(ValueError, match="binary64"):
        temperature_range(2**53 + 1, 2**53)
    with pytest.raises(ValueError, match="binary64"):
        temperature_range(2**53, -1)
    assert temperature_range(2**53, 2**53 - 1)['value_c'] == 1
