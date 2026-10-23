"""Open-Meteo HTTP boundary and Japanese place lookup."""

import re
import hashlib
import httpx
from .locations import clean_name
from .security import require_safe_certifi

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


class WeatherAPI:
    def __init__(self, client=None):
        require_safe_certifi()
        self.client = client or httpx.Client(timeout=10, headers={"User-Agent": "home-weather-mcp/0.2 (personal use)"})

    def get(self, url, params, allow_list=False):
        for attempt in range(2):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if allow_list and isinstance(data, list):
                    return data
                if not isinstance(data, dict) or data.get("error"):
                    raise ValueError("Invalid response from the weather API.")
                return data
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt:
                    raise ValueError("Weather API connection failed or timed out.") from None
            except httpx.HTTPStatusError as exc:
                raise ValueError(f"Weather API returned HTTP {exc.response.status_code}.") from None

    def search(self, place_name: str, country_code: str = "JP"):
        place_name = clean_name(place_name)
        country_code = country_code.upper()
        if not re.fullmatch(r"[A-Z]{2}", country_code):
            raise ValueError("country_code must contain two letters, e.g. JP.")
        # The API searches city names; turn 東京都新宿区 into 新宿区, 東京都.
        match = re.fullmatch(r"(北海道|東京都|京都府|大阪府|.{2,3}県)(.+)", place_name)
        query = f"{match[2]}, {match[1]}" if match else place_name
        data = self.get(GEOCODING_URL, {"name": query, "language": "ja", "count": 10, "countryCode": country_code})
        rows = []
        for row in data.get("results", []):
            # City lookup should not silently pick a park or building with the same prefix.
            if not row.get("feature_code", "").startswith("PPL"):
                continue
            rows.append({key: row.get(key) for key in (
                "id", "name", "country", "country_code", "admin1", "admin2", "admin3",
                "latitude", "longitude", "timezone",
            )})
        if rows:
            return rows
        if country_code == "JP":
            # Ward-level Japanese names are not always indexed in GeoNames.
            features = self.get("https://msearch.gsi.go.jp/address-search/AddressSearch",
                                {"q": place_name}, allow_list=True)
            if not isinstance(features, list):
                raise ValueError("Invalid geocoding response.")
            for feature in features[:10]:
                title = feature.get("properties", {}).get("title", "")
                geometry = feature.get("geometry", {})
                if not title or geometry.get("type") != "Point":
                    continue
                lon, lat = geometry["coordinates"][:2]
                identity = f"{title}:{lat}:{lon}"
                rows.append({"id": "gsi-" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                             "name": title, "latitude": lat, "longitude": lon,
                             "timezone": "Asia/Tokyo", "country_code": "JP", "source": "Geospatial Information Authority of Japan"})
            exact = [row for row in rows if row["name"] == place_name]
            if exact:
                return exact
        return rows

    def forecast(self, location, target="today"):
        params = {
            "latitude": location["latitude"], "longitude": location["longitude"],
            "timezone": location["timezone"], "forecast_days": 2,
            "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm",
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        }
        daily = self.get(FORECAST_URL, params)
        if target == "current":
            return daily, []
        # Preserve StackChan's ability to answer with daily data if hourly detail fails.
        warnings = []
        try:
            hourly = self.get(FORECAST_URL, {
                "latitude": location["latitude"], "longitude": location["longitude"],
                "timezone": location["timezone"], "forecast_days": 2,
                "hourly": "weather_code,temperature_2m,precipitation_probability,rain,showers",
                "temperature_unit": "celsius", "precipitation_unit": "mm",
            })
            daily["hourly"] = hourly.get("hourly", {})
            daily["hourly_units"] = hourly.get("hourly_units", {})
        except ValueError:
            warnings.append("Hourly details are unavailable; returning the daily forecast.")
        return daily, warnings
