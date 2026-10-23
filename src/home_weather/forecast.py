"""Daily/rain summaries adapted from StackChan weather_service concepts.

No scheduler, journal, weather cache, or Hermes imports.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .temperature import temperature_range
from .english import localize
from .native import number, rain_code, rain_likely, heat_category

WEATHER_CODE = {
    0: "快晴", 1: "晴れ", 2: "晴れ時々くもり", 3: "くもり", 45: "霧", 48: "霧",
    51: "小雨", 53: "雨", 55: "強い雨", 56: "弱い着氷性の霧雨", 57: "強い着氷性の霧雨",
    61: "小雨", 63: "雨", 65: "強い雨", 66: "弱い着氷性の雨", 67: "強い着氷性の雨",
    71: "小雪", 73: "雪", 75: "大雪", 77: "霧雪", 80: "にわか雨", 81: "にわか雨",
    82: "強いにわか雨", 85: "にわか雪", 86: "強いにわか雪", 95: "雷雨", 96: "雷雨", 99: "激しい雷雨",
}

def value(series, key, index):
    values = series.get(key, [])
    return values[index] if index < len(values) else None


def weather_text(code):
    return WEATHER_CODE.get(code, "不明")


def hourly_points(data, target_date, now, remaining_only):
    hourly = data.get("hourly", {})
    points = []
    for index, stamp in enumerate(hourly.get("time", [])):
        dt = datetime.fromisoformat(stamp).replace(tzinfo=now.tzinfo)
        if dt.date() != target_date or (remaining_only and dt + timedelta(hours=1) <= now):
            continue
        point = {key: value(hourly, key, index) for key in (
            "weather_code", "temperature_2m", "precipitation_probability", "rain", "showers",
        )}
        point["time"] = dt.isoformat()
        point["weather"] = weather_text(point["weather_code"])
        point["rain_likely"] = rain_likely(point["weather_code"], point["precipitation_probability"], point["rain"], point["showers"])
        points.append(point)
    return points


def rain_intervals(points):
    result = []
    for point in points:
        if not point["rain_likely"]:
            continue
        start = datetime.fromisoformat(point["time"])
        end = start + timedelta(hours=1)
        if result and result[-1]["end"] == start.isoformat():
            result[-1]["end"] = end.isoformat()
        else:
            result.append({"start": start.isoformat(), "end": end.isoformat()})
    return result


def daily_summary(daily, intervals, points, label):
    parts = [f"{label}の天気は{daily['weather']}。"]
    for key, name in (("temperature_2m_max", "最高気温"), ("temperature_2m_min", "最低気温")):
        if number(daily[key]):
            parts.append(f"{name}{daily[key]:.0f}度。")
    probability = daily["precipitation_probability_max"]
    if number(probability):
        parts.append(f"一日の最大降水確率は{probability:.0f}%。")
    if intervals:
        timings = []
        for interval in intervals:
            start, end = (datetime.fromisoformat(interval[k]) for k in ("start", "end"))
            end_label = "翌日0時" if end.date() != start.date() else f"{end.hour}時"
            timings.append(f"{start.hour}時〜{end_label}ごろ")
        parts.append("雨が降りそうな時間帯は" + "、".join(timings) + "。傘を持って行ってね。")
    elif not points and (rain_code(daily["weather_code"]) or (number(probability) and probability >= 50)):
        parts.append("雨の可能性があります。時間帯は不明ですが、傘を持って行ってね。")
    high, low = daily["temperature_2m_max"], daily["temperature_2m_min"]
    if number(high):
        parts.append(("かなり寒いので暖かくしてね。", "寒そうだよ。", "過ごしやすい気温だね。", "暑そうだよ。", "かなり暑いので出かけるときは気をつけてね。")[heat_category(high)])
    temperature = temperature_range(high, low)
    if temperature["is_large"]:
        parts.append(f"寒暖差は{temperature['value_c']:.0f}度あります。")
    return "".join(parts)


def build_result(location, data, warnings, target, include_hourly=False, now=None, language="ja"):
    now = now or datetime.now(ZoneInfo(location["timezone"]))
    target_date = now.date() + timedelta(days=1 if target == "tomorrow" else 0)
    current = data.get("current", {})
    result = {
        "location": location, "fetched_at": now.isoformat(), "timezone": location["timezone"],
        "target": target, "source": "Open-Meteo", "source_url": "https://open-meteo.com/",
        "warnings": list(warnings), "current": {**current, "weather": weather_text(current.get("weather_code"))},
        "current_units": data.get("current_units", {}),
    }
    if target == "current":
        if not current.get("time") or not any(current.get(key) is not None for key in ("temperature_2m", "weather_code")):
            raise ValueError("Current weather data is unavailable.")
        return localize(result, language)
    days = data.get("daily", {})
    if target_date.isoformat() not in days.get("time", []):
        raise ValueError("No forecast for the requested date.")
    index = days["time"].index(target_date.isoformat())
    daily = {key: value(days, key, index) for key in (
        "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max",
    )}
    if not any(item is not None for item in daily.values()):
        raise ValueError("Weather values are missing for the requested date.")
    daily["date"] = target_date.isoformat()
    daily["weather"] = weather_text(daily["weather_code"])
    points = hourly_points(data, target_date, now, target == "today")
    rain_points = [point for point in points if point["rain_likely"] is not None]
    intervals = rain_intervals(points)
    result.update({
        "daily": daily, "daily_units": data.get("daily_units", {}),
        "temperature_range": temperature_range(daily["temperature_2m_max"], daily["temperature_2m_min"]),
        "rain_intervals": intervals, "rain_scope": "このあと" if target == "today" else "一日全体",
        "hourly_detail_available": bool(rain_points),
        "summary_ja": daily_summary(daily, intervals, rain_points, "今日" if target == "today" else "明日"),
    })
    if not rain_points and not warnings:
        result["warnings"].append("No hourly data is available for this period; rain timing is unknown.")
    elif len(rain_points) != len(points):
        result["warnings"].append("Rain data is missing for some hours; intervals cover available data only.")
    if include_hourly:
        result["hourly"] = points
        result["hourly_units"] = data.get("hourly_units", {})
    return localize(result, language)
