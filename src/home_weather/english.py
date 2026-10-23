"""English presentation for the same weather data used by Japanese summaries."""

from datetime import datetime
from .native import rain_code, heat_category

WEATHER = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 66: "Light freezing rain",
    67: "Heavy freezing rain", 71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

WARNINGS = {
    "Hourly details are unavailable; returning the daily forecast.": "時間別の詳細は取得できませんでした。日別予報を返します。",
    "No hourly data is available for this period; rain timing is unknown.": "対象時間帯の時間別データがありません。雨の時間帯は不明です。",
    "Rain data is missing for some hours; intervals cover available data only.": "一部の時間帯で雨のデータが欠損しています。雨の時間帯は取得できた範囲のみです。",
}


def english_summary(result):
    daily = result["daily"]
    parts = [f"{'Today' if result['target'] == 'today' else 'Tomorrow'}: {WEATHER.get(daily['weather_code'], 'Unknown')}."]
    high, low = daily["temperature_2m_max"], daily["temperature_2m_min"]
    for label, value in (("High", high), ("Low", low)):
        if value is not None:
            parts.append(f"{label}: {value:.0f}°C.")
    chance = daily["precipitation_probability_max"]
    if chance is not None:
        parts.append(f"Maximum daily precipitation probability: {chance:.0f}%.")
    if result["rain_intervals"]:
        intervals = []
        for interval in result["rain_intervals"]:
            start, end = (datetime.fromisoformat(interval[key]) for key in ("start", "end"))
            ending = "00:00 next day" if end.date() != start.date() else end.strftime("%H:%M")
            intervals.append(f"{start:%H:%M}–{ending}")
        parts.append("Rain is possible around " + ", ".join(intervals) + ". Bring an umbrella.")
    elif not result["hourly_detail_available"] and (rain_code(daily["weather_code"]) or (chance is not None and chance >= 50)):
        parts.append("Rain is possible, but timing is unknown. Bring an umbrella.")
    if high is not None:
        parts.append(("Very cold; dress warmly.", "It looks cold.", "Mild temperatures expected.", "It looks hot.", "Very hot; take care when going out.")[heat_category(high)])
    temperature = result["temperature_range"]
    if temperature["is_large"]:
        parts.append(f"The daily temperature range is {temperature['value_c']:.0f}°C.")
    return " ".join(parts)


def localize(result, language):
    result["language"] = language
    if "daily" in result:
        result["summary_en"] = english_summary(result)
        result["summary"] = result[f"summary_{language}"]
        result["rain_scope"] = ("remaining hours" if result["target"] == "today" else "whole day") if language == "en" else result["rain_scope"]
    if language == "en":
        for item in [result["current"], *([result["daily"]] if "daily" in result else []), *result.get("hourly", [])]:
            item["weather"] = WEATHER.get(item.get("weather_code"), "Unknown")
    else:
        result["warnings"] = [WARNINGS.get(warning, warning) for warning in result["warnings"]]
    return result
