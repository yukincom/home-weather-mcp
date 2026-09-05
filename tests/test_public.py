import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from home_weather.locations import LocationStore
from home_weather.server import create_server
from home_weather.forecast import build_result


def test_tokyo_default_is_read_only_and_can_be_changed(tmp_path):
    path = tmp_path / "locations.json"
    store = LocationStore(path)
    assert store.get()["alias"] == "Tokyo"
    assert store.get("東京")["place_name"] == "Tokyo, Japan"
    assert not path.exists()
    store.update("東京", {"alias": "Home", "additional_aliases": ["自宅"]})
    assert store.get()["alias"] == "Home"
    assert len(store.list()) == 1
    store.remove("Home")
    assert store.list() == []  # Explicitly empty settings must not restore Tokyo.


def test_english_and_japanese_use_same_data(tmp_path):
    location = LocationStore(tmp_path / "locations.json").get()
    data = {"daily": {"time": ["2026-09-05"], "weather_code": [61],
                      "temperature_2m_max": [30], "temperature_2m_min": [20],
                      "precipitation_probability_max": [80]},
            "current": {"time": "2026-09-05T12:00", "weather_code": 61, "temperature_2m": 28}}
    now = datetime(2026, 9, 5, 12, tzinfo=ZoneInfo("Asia/Tokyo"))
    en = build_result(location, data, [], "today", now=now, language="en")
    ja = build_result(location, data, [], "today", now=now, language="ja")
    assert en["summary"] == en["summary_en"] == ja["summary_en"]
    assert ja["summary"] == en["summary_ja"]
    assert "umbrella" in en["summary"] and "傘" in ja["summary"]
    assert en["daily"]["weather"] == "Slight rain"
    assert ja["daily"]["weather"] == "小雨"
    assert en["daily"]["temperature_2m_max"] == ja["daily"]["temperature_2m_max"]
    assert "unknown" in en["warnings"][0]
    assert "不明" in ja["warnings"][0]


def test_mcp_language_default_and_override(tmp_path):
    class API:
        def forecast(self, *args):
            return {"current": {"time": "2026-09-05T12:00", "weather_code": 1, "temperature_2m": 20}}, []
    server = create_server(tmp_path / "locations.json", API(), language="en")
    def call(args):
        result = asyncio.run(server.call_tool("weather_get", args))
        return json.loads(result[0].text)
    assert call({"target": "current"})["current"]["weather"] == "Mainly clear"
    assert call({"target": "current", "language": "ja"})["current"]["weather"] == "晴れ"
    assert not (tmp_path / "locations.json").exists()
