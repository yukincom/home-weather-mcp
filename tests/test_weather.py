import asyncio
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from home_weather.api import WeatherAPI
from home_weather.forecast import build_result
from home_weather.locations import LocationStore
from home_weather.server import create_server


@pytest.fixture(autouse=True)
def empty_initial_settings(monkeypatch):
    monkeypatch.setattr("home_weather.locations.DEFAULT_LOCATIONS", [])


def place(alias="Home", aliases=None):
    return {"alias": alias, "additional_aliases": aliases or ["Tokyo"], "place_name": "Tokyo, Japan",
            "latitude": 35.6895, "longitude": 139.69171, "timezone": "Asia/Tokyo"}


def payload():
    return {
        "current": {"time": "2026-09-05T14:00", "temperature_2m": 28, "weather_code": 1},
        "current_units": {"temperature_2m": "°C", "wind_speed_10m": "m/s"},
        "daily": {"time": ["2026-09-05", "2026-09-06"], "weather_code": [61, 1],
                  "temperature_2m_max": [30, 28], "temperature_2m_min": [20, 20],
                  "precipitation_probability_max": [80, 10]},
        "hourly": {"time": ["2026-09-05T08:00", "2026-09-05T15:00", "2026-09-05T16:00",
                             "2026-09-05T18:00", "2026-09-05T23:00"],
                   "weather_code": [61, 61, 61, 61, 61], "rain": [1, 1, 1, 1, 1]},
    }


def test_alias_default_limit_and_update(tmp_path):
    store = LocationStore(tmp_path / "locations.json")
    store.set(place())
    assert store.get()["alias"] == store.get("Tokyo")["alias"] == "Home"
    store.set(place("Office", ["Osaka"]))
    store.set(place("Travel", ["Kyoto"]))
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="[Aa]t most 3"):
        store.set(place("Fourth", ["Fourth alias"]))
    assert store.path.read_bytes() == before
    store.update("Kyoto", {"place_name": "Another place", "latitude": 35, "longitude": 140})
    assert len(store.list()) == 3
    assert store.get("Travel")["latitude"] == 35
    assert store.get("Kyoto")["place_name"] == "Another place"
    store.update("Osaka", {"is_default": True})
    assert store.get()["alias"] == "Office"
    store.update("Office", {"alias": "Work", "additional_aliases": ["workplace"]})
    assert store.get()["alias"] == "Work"
    with pytest.raises(ValueError, match="Unknown location"):
        store.get("Osaka")


def test_alias_collision_does_not_modify_settings(tmp_path):
    store = LocationStore(tmp_path / "locations.json")
    store.set(place())
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.set(place("Tokyo", ["Second"]))
    assert store.path.read_bytes() == before
    store.set(place("Office", ["Osaka"]))
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.update("Osaka", {"additional_aliases": ["Tokyo"]})
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("latitude", [float("nan"), float("inf"), 91, True])
def test_invalid_coordinates_rejected(tmp_path, latitude):
    store = LocationStore(tmp_path / "locations.json")
    with pytest.raises(ValueError):
        store.set({**place(), "latitude": latitude})
    assert not store.path.exists()


def test_remove_default_and_corrupt_settings(tmp_path):
    store = LocationStore(tmp_path / "locations.json")
    store.set(place())
    store.set(place("Office", ["Osaka"]))
    store.remove("Tokyo")
    assert store.get()["alias"] == "Office"
    store.path.write_text("{bad json")
    with pytest.raises(ValueError):
        store.set(place())
    assert store.path.read_text() == "{bad json"


def test_rain_intervals_remaining_gaps_and_midnight():
    result = build_result(place(), payload(), [], "today", True,
                          datetime(2026, 9, 5, 14, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert len(result["rain_intervals"]) == 3
    assert result["rain_intervals"][0] == {"start": "2026-09-05T15:00:00+09:00", "end": "2026-09-05T17:00:00+09:00"}
    assert result["rain_intervals"][-1]["end"] == "2026-09-06T00:00:00+09:00"
    assert all("T08:" not in row["start"] for row in result["rain_intervals"])
    assert "傘" in result["summary_ja"] and "寒暖差" in result["summary_ja"]


def test_tomorrow_by_date_not_array_index():
    data = payload()
    for key in data["daily"]:
        data["daily"][key].reverse()
    result = build_result(place(), data, [], "tomorrow", now=datetime(2026, 9, 5, 23, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert result["daily"]["date"] == "2026-09-06"
    assert result["daily"]["temperature_2m_max"] == 28


def test_missing_values_and_wrong_date_are_not_sunny():
    data = payload()
    data["daily"]["precipitation_probability_max"] = [None, None]
    result = build_result(place(), data, [], "today", now=datetime(2026, 9, 5, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert result["daily"]["precipitation_probability_max"] is None
    assert "降水確率は0%" not in result["summary_ja"]
    with pytest.raises(ValueError):
        build_result(place(), data, [], "today", now=datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Tokyo")))


def test_missing_hourly_rain_is_unknown():
    data = payload()
    data["hourly"] = {"time": ["2026-09-05T15:00"], "weather_code": [None], "rain": [None]}
    result = build_result(place(), data, [], "today", True,
                          datetime(2026, 9, 5, 14, tzinfo=ZoneInfo("Asia/Tokyo")))
    assert result["hourly"][0]["rain_likely"] is None
    assert not result["hourly_detail_available"]
    assert result["warnings"] and "傘" in result["summary_ja"]


def test_retry_fresh_calls_and_hourly_failure():
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("timeout")
        if "hourly" in request.url.params:
            return httpx.Response(503)
        assert request.url.params["temperature_unit"] == "celsius"
        assert request.url.params["wind_speed_unit"] == "ms"
        assert request.url.params["timezone"] == "Asia/Tokyo"
        return httpx.Response(200, json=payload())
    api = WeatherAPI(httpx.Client(transport=httpx.MockTransport(handler)))
    first, warnings = api.forecast(place())
    assert first["daily"] and warnings
    count = len(requests)
    api.forecast(place(), "current")
    assert len(requests) == count + 1




class FakeAPI:
    candidates = [{"id": 1, "latitude": 35, "longitude": 139, "timezone": "Asia/Tokyo"}]
    calls = 0
    def search(self, *_):
        return copy.deepcopy(self.candidates)
    def forecast(self, *args):
        self.calls += 1
        return payload(), []


def invoke(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return result[1] if isinstance(result, tuple) else json.loads(result[0].text)


def test_mcp_registration_ambiguity_and_change(tmp_path):
    api = FakeAPI()
    server = create_server(tmp_path / "locations.json", api)
    api.candidates = api.candidates * 2
    result = invoke(server, "weather_set_location", {"alias": "Home", "place_name": "Somewhere"})
    assert not result["registered"]
    assert not (tmp_path / "locations.json").exists()
    api.candidates = api.candidates[:1]
    invoke(server, "weather_set_location", {"alias": "Home", "place_name": "Tokyo市", "additional_aliases": ["Tokyo"]})
    before = (tmp_path / "locations.json").read_bytes()
    api.candidates *= 2
    result = invoke(server, "weather_update_location", {"alias": "Tokyo", "place_name": "Another place"})
    assert not result["updated"] and (tmp_path / "locations.json").read_bytes() == before
    api.candidates = api.candidates[:1]
    result = invoke(server, "weather_update_location", {"alias": "Tokyo", "place_name": "New place"})
    assert result["location"]["additional_aliases"] == ["Tokyo"]
    assert result["location"]["is_default"]


def test_get_does_not_write_or_cache_weather(tmp_path):
    api = FakeAPI()
    server = create_server(tmp_path / "locations.json", api)
    invoke(server, "weather_set_location", {"alias": "Home", "place_name": "Tokyo市"})
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    for _ in range(2):
        result = invoke(server, "weather_get", {"target": "current"})
        assert result["current"]["temperature_2m"] == 28
    assert api.calls == 2
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_tool_annotations_and_schema(tmp_path):
    server = create_server(tmp_path / "locations.json", FakeAPI())
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert len(tools) == 6
    assert tools["weather_get"].annotations.readOnlyHint
    assert tools["weather_update_location"].annotations.destructiveHint
    assert not tools["weather_set_location"].annotations.readOnlyHint
    assert "alias" not in tools["weather_get"].inputSchema.get("required", [])


def test_geocoding_normalization_and_ward_fallback():
    def handler(request):
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.params["name"] == "新宿区, 東京都"
            return httpx.Response(200, json={})
        assert request.url.host == "msearch.gsi.go.jp"
        return httpx.Response(200, json=[{"geometry": {"type": "Point", "coordinates": [139.7034, 35.6938]},
                                         "properties": {"title": "東京都新宿区"}}])
    api = WeatherAPI(httpx.Client(transport=httpx.MockTransport(handler)))
    rows = api.search("東京都新宿区")
    assert len(rows) == 1 and rows[0]["latitude"] == 35.6938
    assert rows[0]["source"] == "Geospatial Information Authority of Japan"
