//! Calendar-aware bilingual forecast rendering; no network or persistence.
use crate::{
    labels::weather, weather_heat_category, weather_is_large, weather_rain_code,
    weather_rain_likely, weather_temperature_range,
};
use anyhow::{ensure, Context, Result};
use chrono::{DateTime, Duration, FixedOffset, NaiveDateTime, Offset, TimeZone, Timelike, Utc};
use chrono_tz::Tz;
use serde_json::{json, Value};

pub const MISSING_HOURLY: &str =
    "No hourly data is available for this period; rain timing is unknown.";
pub const PARTIAL_HOURLY: &str =
    "Rain data is missing for some hours; intervals cover available data only.";
fn value(series: &Value, key: &str, index: usize) -> Value {
    series[key]
        .as_array()
        .and_then(|a| a.get(index))
        .cloned()
        .unwrap_or(Value::Null)
}
fn numeric(value: &Value) -> f64 {
    value.as_f64().unwrap_or(f64::NAN)
}
pub fn temperature(high: &Value, low: &Value) -> Value {
    let delta = weather_temperature_range(numeric(high), numeric(low));
    json!({"basis":"daily_max_minus_min","value_c":if delta.is_finite(){Some(delta)}else{None},"threshold_c":7.0,"is_large":match weather_is_large(delta){-1=>None,n=>Some(n==1)}})
}
fn local_offset(naive: NaiveDateTime, zone: Tz) -> Result<FixedOffset> {
    if let Some(offset) = zone.offset_from_local_datetime(&naive).earliest() {
        return Ok(offset.fix());
    }
    // Python ZoneInfo's fold=0 uses the pre-transition offset in a DST gap.
    for minutes in 1..=24 * 60 {
        if let Some(offset) = zone
            .offset_from_local_datetime(&(naive - Duration::minutes(minutes)))
            .earliest()
        {
            return Ok(offset.fix());
        }
    }
    anyhow::bail!("Cannot resolve local forecast time.")
}
fn iso(naive: NaiveDateTime, zone: Tz) -> Result<String> {
    Ok(iso_fixed(naive, local_offset(naive, zone)?))
}
fn iso_fixed(naive: NaiveDateTime, offset: FixedOffset) -> String {
    let base = naive.format("%Y-%m-%dT%H:%M:%S").to_string();
    let fraction = if naive.nanosecond() != 0 {
        format!(".{:06}", naive.nanosecond() / 1000)
    } else {
        String::new()
    };
    format!("{base}{fraction}{offset}")
}
fn parse_local(stamp: &str) -> Result<NaiveDateTime> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(stamp) {
        return Ok(dt.naive_local());
    }
    NaiveDateTime::parse_from_str(stamp, "%Y-%m-%dT%H:%M:%S%.f")
        .or_else(|_| NaiveDateTime::parse_from_str(stamp, "%Y-%m-%dT%H:%M"))
        .context("Invalid hourly timestamp.")
}
fn rain(point: &Value) -> Value {
    let keys = [
        "weather_code",
        "precipitation_probability",
        "rain",
        "showers",
    ];
    let mask = keys.iter().enumerate().fold(0, |mask, (i, key)| {
        mask | if point[key].is_number() { 1 << i } else { 0 }
    });
    match weather_rain_likely(
        numeric(&point[keys[0]]),
        numeric(&point[keys[1]]),
        numeric(&point[keys[2]]),
        numeric(&point[keys[3]]),
        mask,
    ) {
        -1 => Value::Null,
        n => json!(n == 1),
    }
}
fn rainy(daily: &Value) -> bool {
    weather_rain_code(numeric(&daily["weather_code"])) == 1
        || numeric(&daily["precipitation_probability_max"]) >= 50.
}
fn summaries(
    daily: &Value,
    intervals: &[Value],
    detail: bool,
    target: &str,
    range: &Value,
) -> Result<(String, String)> {
    let mut ja = vec![format!(
        "{}の天気は{}。",
        if target == "today" {
            "今日"
        } else {
            "明日"
        },
        weather(&daily["weather_code"], "ja")
    )];
    let mut en = vec![format!(
        "{}: {}.",
        if target == "today" {
            "Today"
        } else {
            "Tomorrow"
        },
        weather(&daily["weather_code"], "en")
    )];
    for (key, jlabel, elabel) in [
        ("temperature_2m_max", "最高気温", "High"),
        ("temperature_2m_min", "最低気温", "Low"),
    ] {
        if let Some(n) = daily[key].as_f64() {
            ja.push(format!("{jlabel}{n:.0}度。"));
            en.push(format!("{elabel}: {n:.0}°C."));
        }
    }
    if let Some(n) = daily["precipitation_probability_max"].as_f64() {
        ja.push(format!("一日の最大降水確率は{n:.0}%。"));
        en.push(format!("Maximum daily precipitation probability: {n:.0}%."));
    }
    if !intervals.is_empty() {
        let mut jtimes = Vec::new();
        let mut etimes = Vec::new();
        for interval in intervals {
            let start = parse_local(
                interval["start"]
                    .as_str()
                    .context("Invalid interval start.")?,
            )?;
            let end = parse_local(interval["end"].as_str().context("Invalid interval end.")?)?;
            let jend = if start.date() != end.date() {
                "翌日0時".into()
            } else {
                format!("{}時", end.hour())
            };
            let eend = if start.date() != end.date() {
                "00:00 next day".into()
            } else {
                end.format("%H:%M").to_string()
            };
            jtimes.push(format!("{}時〜{jend}ごろ", start.hour()));
            etimes.push(format!("{}–{eend}", start.format("%H:%M")));
        }
        ja.push(format!(
            "雨が降りそうな時間帯は{}。傘を持って行ってね。",
            jtimes.join("、")
        ));
        en.push(format!(
            "Rain is possible around {}. Bring an umbrella.",
            etimes.join(", ")
        ));
    } else if !detail && rainy(daily) {
        ja.push("雨の可能性があります。時間帯は不明ですが、傘を持って行ってね。".into());
        en.push("Rain is possible, but timing is unknown. Bring an umbrella.".into());
    }
    if let Some(high) = daily["temperature_2m_max"].as_f64() {
        let category = weather_heat_category(high) as usize;
        ja.push(
            [
                "かなり寒いので暖かくしてね。",
                "寒そうだよ。",
                "過ごしやすい気温だね。",
                "暑そうだよ。",
                "かなり暑いので出かけるときは気をつけてね。",
            ][category]
                .into(),
        );
        en.push(
            [
                "Very cold; dress warmly.",
                "It looks cold.",
                "Mild temperatures expected.",
                "It looks hot.",
                "Very hot; take care when going out.",
            ][category]
                .into(),
        );
    }
    if range["is_large"] == true {
        let n = range["value_c"]
            .as_f64()
            .context("Missing temperature range.")?;
        ja.push(format!("寒暖差は{n:.0}度あります。"));
        en.push(format!("The daily temperature range is {n:.0}°C."));
    }
    Ok((ja.join(""), en.join(" ")))
}
fn translated_warning(w: &str) -> &str {
    match w {
        crate::api::HOURLY_WARNING => "時間別の詳細は取得できませんでした。日別予報を返します。",
        MISSING_HOURLY => "対象時間帯の時間別データがありません。雨の時間帯は不明です。",
        PARTIAL_HOURLY => {
            "一部の時間帯で雨のデータが欠損しています。雨の時間帯は取得できた範囲のみです。"
        }
        _ => w,
    }
}
pub fn build_result(
    location: Value,
    data: Value,
    mut warnings: Vec<String>,
    target: &str,
    include_hourly: bool,
    language: &str,
    now: Option<DateTime<Utc>>,
) -> Result<Value> {
    ensure!(
        ["today", "tomorrow", "current"].contains(&target),
        "Invalid forecast target."
    );
    ensure!(["ja", "en"].contains(&language), "Invalid language.");
    let zone: Tz = location["timezone"]
        .as_str()
        .context("Missing timezone.")?
        .parse()?;
    let aware_now = now.unwrap_or_else(Utc::now).with_timezone(&zone);
    let now = aware_now.naive_local();
    let now = now
        .with_nanosecond(now.nanosecond() / 1000 * 1000)
        .context("Invalid current time.")?;
    let date = now.date() + Duration::days(if target == "tomorrow" { 1 } else { 0 });
    let mut current = data.get("current").cloned().unwrap_or(json!({}));
    ensure!(current.is_object(), "Invalid current weather object.");
    current["weather"] = json!(weather(&current["weather_code"], language));
    let mut result = json!({"location":location,"fetched_at":iso_fixed(now,aware_now.offset().fix()),"timezone":zone.to_string(),"target":target,"source":"Open-Meteo","source_url":"https://open-meteo.com/","current":current,"current_units":data.get("current_units").cloned().unwrap_or(json!({})),"language":language});
    if target == "current" {
        ensure!(
            current["time"].as_str().is_some_and(|t| !t.is_empty())
                && (!current["temperature_2m"].is_null() || !current["weather_code"].is_null()),
            "Current weather data is unavailable."
        );
    } else {
        let days = &data["daily"];
        let index = days["time"]
            .as_array()
            .and_then(|a| a.iter().position(|v| v.as_str() == Some(&date.to_string())))
            .context("No forecast for the requested date.")?;
        let mut daily = json!({});
        for key in [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
        ] {
            daily[key] = value(days, key, index);
        }
        ensure!(
            daily.as_object().unwrap().values().any(|v| !v.is_null()),
            "Weather values are missing for the requested date."
        );
        daily["date"] = json!(date.to_string());
        daily["weather"] = json!(weather(&daily["weather_code"], language));
        let mut points = Vec::new();
        let mut intervals: Vec<Value> = Vec::new();
        if let Some(times) = data["hourly"]["time"].as_array() {
            for (index, stamp) in times.iter().enumerate() {
                let dt = parse_local(stamp.as_str().context("Invalid hourly timestamp.")?)?;
                if dt.date() != date || (target == "today" && dt + Duration::hours(1) <= now) {
                    continue;
                }
                let mut point = json!({});
                for key in [
                    "weather_code",
                    "temperature_2m",
                    "precipitation_probability",
                    "rain",
                    "showers",
                ] {
                    point[key] = value(&data["hourly"], key, index);
                }
                point["time"] = json!(iso(dt, zone)?);
                point["weather"] = json!(weather(&point["weather_code"], language));
                point["rain_likely"] = rain(&point);
                if point["rain_likely"] == true {
                    // Existing intervals add one hour to the serialized fixed-offset stamp.
                    let start = DateTime::parse_from_rfc3339(point["time"].as_str().unwrap())?;
                    let end = json!(iso_fixed(
                        (start + Duration::hours(1)).naive_local(),
                        *start.offset()
                    ));
                    if let Some(last) = intervals
                        .last_mut()
                        .filter(|last| last["end"] == point["time"])
                    {
                        last["end"] = end;
                    } else {
                        intervals.push(json!({"start":point["time"],"end":end}));
                    }
                }
                points.push(point);
            }
        }
        let known = points
            .iter()
            .filter(|p| !p["rain_likely"].is_null())
            .count();
        let range = temperature(&daily["temperature_2m_max"], &daily["temperature_2m_min"]);
        let (ja, en) = summaries(&daily, &intervals, known > 0, target, &range)?;
        result["summary"] = json!(if language == "ja" { &ja } else { &en });
        result["summary_ja"] = json!(ja);
        result["summary_en"] = json!(en);
        result["daily"] = daily;
        result["daily_units"] = data.get("daily_units").cloned().unwrap_or(json!({}));
        result["temperature_range"] = range;
        result["rain_intervals"] = json!(intervals);
        result["hourly_detail_available"] = json!(known > 0);
        result["rain_scope"] = json!(match (language, target) {
            ("ja", "today") => "このあと",
            ("ja", _) => "一日全体",
            (_, "today") => "remaining hours",
            _ => "whole day",
        });
        if known == 0 && warnings.is_empty() {
            warnings.push(MISSING_HOURLY.into());
        } else if known != points.len() {
            warnings.push(PARTIAL_HOURLY.into());
        }
        if include_hourly {
            result["hourly"] = json!(points);
            result["hourly_units"] = data.get("hourly_units").cloned().unwrap_or(json!({}));
        }
    }
    result["warnings"] = json!(warnings
        .iter()
        .map(|w| if language == "ja" {
            translated_warning(w)
        } else {
            w
        })
        .collect::<Vec<_>>());
    Ok(result)
}
