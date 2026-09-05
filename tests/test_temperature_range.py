from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from home_weather.forecast import build_result
from home_weather.temperature import temperature_range


@pytest.mark.parametrize("high,low,expected,flag", [
    (26.9, 20, 6.9, False), (27, 20, 7, True), (27.1, 20.1, 7, True),
    (28, 20, 8, True), (20, 20, 0, False),
    (None, 20, None, None), (27, None, None, None),
    (True, 0, None, None), (float("nan"), 20, None, None),
    (float("inf"), 20, None, None), (19, 20, None, None),
])
def test_temperature_threshold_and_unknown(high, low, expected, flag):
    result = temperature_range(high, low)
    assert result == {"basis": "daily_max_minus_min", "value_c": expected,
                      "threshold_c": 7.0, "is_large": flag}


def test_daily_result_contains_signal_and_current_does_not():
    location = {"timezone": "Asia/Tokyo"}
    now = datetime(2026, 9, 5, 12, tzinfo=ZoneInfo("Asia/Tokyo"))
    data = {"daily": {"time": ["2026-09-05", "2026-09-06"],
                      "weather_code": [1, 1], "temperature_2m_max": [27, 30],
                      "temperature_2m_min": [20, 25]},
            "current": {"time": "2026-09-05T12:00", "temperature_2m": 25}}
    today = build_result(location, data, [], "today", now=now)
    tomorrow = build_result(location, data, [], "tomorrow", now=now)
    assert today["temperature_range"]["is_large"] is True
    assert tomorrow["temperature_range"]["value_c"] == 5
    assert tomorrow["temperature_range"]["is_large"] is False
    assert "寒暖差" in today["summary_ja"] and "寒暖差" not in tomorrow["summary_ja"]
    assert "temperature_range" not in build_result(location, data, [], "current", now=now)
    data["daily"]["temperature_2m_min"][0] = None
    unknown = build_result(location, data, [], "today", now=now)
    assert unknown["temperature_range"]["is_large"] is None
