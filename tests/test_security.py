import pytest
from home_weather import security
from home_weather.api import WeatherAPI


@pytest.mark.parametrize("installed", ["2026.7.22", "2026.10.18", "2026.10.19rc1"])
def test_unsafe_bundle_rejected_before_client_creation(monkeypatch, installed):
    monkeypatch.setattr(security, "version", lambda _: installed)
    with pytest.raises(RuntimeError, match="certifi"):
        WeatherAPI()


def test_safe_bundle_allowed(monkeypatch):
    monkeypatch.setattr(security, "version", lambda _: "2026.10.19")
    security.require_safe_certifi()
