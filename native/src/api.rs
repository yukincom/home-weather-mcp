//! On-demand HTTP; native TLS uses the host trust store, without bundled roots.
use crate::locations::clean_name;
use anyhow::{bail, ensure, Context, Result};
use regex::Regex;
use reqwest::{blocking::Client, redirect::Policy};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::time::Duration;

pub const FORECAST_URL: &str = "https://api.open-meteo.com/v1/forecast";
pub const GEOCODING_URL: &str = "https://geocoding-api.open-meteo.com/v1/search";
pub const GSI_URL: &str = "https://msearch.gsi.go.jp/address-search/AddressSearch";
pub const HOURLY_WARNING: &str = "Hourly details are unavailable; returning the daily forecast.";

pub trait WeatherSource: Send + Sync {
    fn search(&self, place: &str, country: &str) -> Result<Vec<Value>>;
    fn forecast(&self, location: &Value, target: &str) -> Result<(Value, Vec<String>)>;
}
#[derive(Clone)]
pub struct WeatherApi {
    client: Client,
    forecast_url: String,
    geocoding_url: String,
    gsi_url: String,
}
impl WeatherApi {
    pub fn new() -> Result<Self> {
        Self::with_endpoints(
            FORECAST_URL,
            GEOCODING_URL,
            GSI_URL,
            Duration::from_secs(10),
        )
    }
    /// Dependency injection for local HTTP contract tests; the CLI uses fixed HTTPS URLs.
    pub fn with_endpoints(
        forecast: &str,
        geocoding: &str,
        gsi: &str,
        timeout: Duration,
    ) -> Result<Self> {
        Ok(Self {
            client: Client::builder()
                .timeout(timeout)
                .redirect(Policy::none())
                .user_agent("home-weather-mcp/0.4 (personal use)")
                .build()?,
            forecast_url: forecast.into(),
            geocoding_url: geocoding.into(),
            gsi_url: gsi.into(),
        })
    }
    fn get(&self, url: &str, params: &[(&str, String)], allow_list: bool) -> Result<Value> {
        for attempt in 0..2 {
            let response = match self.client.get(url).query(params).send() {
                Ok(response) => response,
                Err(error) if retryable(&error) && attempt == 0 => continue,
                Err(error) => {
                    return Err(error).context("Weather API connection failed or timed out.")
                }
            };
            ensure!(
                response.status().is_success(),
                "Weather API returned HTTP {}.",
                response.status().as_u16()
            );
            let bytes = match response.bytes() {
                Ok(bytes) => bytes,
                Err(_) if attempt == 0 => continue,
                Err(error) => {
                    return Err(error).context("Weather API connection failed or timed out.")
                }
            };
            let data: Value =
                serde_json::from_slice(&bytes).context("Invalid response from the weather API.")?;
            if allow_list && data.is_array() {
                return Ok(data);
            }
            ensure!(
                data.is_object() && !truthy(&data["error"]),
                "Invalid response from the weather API."
            );
            return Ok(data);
        }
        bail!("Weather API connection failed or timed out.")
    }
}
fn retryable(error: &reqwest::Error) -> bool {
    if error.is_connect() || error.is_timeout() || error.is_body() {
        return true;
    }
    let mut source: Option<&(dyn std::error::Error + 'static)> = Some(error);
    while let Some(cause) = source {
        if let Some(io) = cause.downcast_ref::<std::io::Error>() {
            use std::io::ErrorKind::*;
            if matches!(
                io.kind(),
                ConnectionReset
                    | ConnectionAborted
                    | BrokenPipe
                    | NotConnected
                    | UnexpectedEof
                    | TimedOut
            ) {
                return true;
            }
        }
        source = cause.source();
    }
    false
}

fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.),
    }
}
impl WeatherSource for WeatherApi {
    fn search(&self, place: &str, country: &str) -> Result<Vec<Value>> {
        let place = clean_name(place)?;
        let country = country.to_uppercase();
        ensure!(
            country.len() == 2 && country.bytes().all(|b| b.is_ascii_uppercase()),
            "country_code must contain two letters, e.g. JP."
        );
        let pattern = Regex::new(r"^(北海道|東京都|京都府|大阪府|.{2,3}県)(.+)$")?;
        let query = pattern
            .captures(&place)
            .map(|c| format!("{}, {}", &c[2], &c[1]))
            .unwrap_or_else(|| place.clone());
        let data = self.get(
            &self.geocoding_url,
            &[
                ("name", query),
                ("language", "ja".into()),
                ("count", "10".into()),
                ("countryCode", country.clone()),
            ],
            false,
        )?;
        let mut rows = Vec::new();
        if let Some(results) = data["results"].as_array() {
            for row in results {
                if !row["feature_code"]
                    .as_str()
                    .unwrap_or("")
                    .starts_with("PPL")
                {
                    continue;
                }
                let mut output = json!({});
                for key in [
                    "id",
                    "name",
                    "country",
                    "country_code",
                    "admin1",
                    "admin2",
                    "admin3",
                    "latitude",
                    "longitude",
                    "timezone",
                ] {
                    output[key] = row[key].clone();
                }
                rows.push(output);
            }
        }
        if !rows.is_empty() {
            return Ok(rows);
        }
        if country == "JP" {
            let features = self.get(&self.gsi_url, &[("q", place.clone())], true)?;
            let features = features.as_array().context("Invalid geocoding response.")?;
            for feature in features.iter().take(10) {
                let title = feature["properties"]["title"].as_str().unwrap_or("");
                let geometry = &feature["geometry"];
                if title.is_empty() || geometry["type"] != "Point" {
                    continue;
                }
                let coordinates = geometry["coordinates"]
                    .as_array()
                    .context("Invalid geocoding coordinates.")?;
                ensure!(
                    coordinates.len() >= 2
                        && coordinates[0].is_number()
                        && coordinates[1].is_number(),
                    "Invalid geocoding coordinates."
                );
                let (lon, lat) = (&coordinates[0], &coordinates[1]);
                let identity = format!("{title}:{lat}:{lon}");
                let hash = format!("{:x}", Sha256::digest(identity.as_bytes()));
                rows.push(json!({"id":format!("gsi-{}", &hash[..16]),"name":title,"latitude":lat,"longitude":lon,"timezone":"Asia/Tokyo","country_code":"JP","source":"Geospatial Information Authority of Japan"}));
            }
            let exact: Vec<_> = rows
                .iter()
                .filter(|r| r["name"] == place)
                .cloned()
                .collect();
            if !exact.is_empty() {
                return Ok(exact);
            }
        }
        Ok(rows)
    }
    fn forecast(&self, location: &Value, target: &str) -> Result<(Value, Vec<String>)> {
        let common = vec![
            ("latitude", location["latitude"].to_string()),
            ("longitude", location["longitude"].to_string()),
            (
                "timezone",
                location["timezone"]
                    .as_str()
                    .context("Missing timezone.")?
                    .to_owned(),
            ),
            ("forecast_days", "2".into()),
            ("temperature_unit", "celsius".into()),
            ("wind_speed_unit", "ms".into()),
            ("precipitation_unit", "mm".into()),
        ];
        let mut params = common.clone();
        params.push(("current", "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m".into()));
        params.push((
            "daily",
            "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                .into(),
        ));
        let mut daily = self.get(&self.forecast_url, &params, false)?;
        if target == "current" {
            return Ok((daily, vec![]));
        }
        let mut hourly_params = common;
        hourly_params.push((
            "hourly",
            "weather_code,temperature_2m,precipitation_probability,rain,showers".into(),
        ));
        let warnings = match self.get(&self.forecast_url, &hourly_params, false) {
            Ok(hourly) => {
                daily["hourly"] = hourly.get("hourly").cloned().unwrap_or(json!({}));
                daily["hourly_units"] = hourly.get("hourly_units").cloned().unwrap_or(json!({}));
                vec![]
            }
            Err(_) => vec![HOURLY_WARNING.to_owned()],
        };
        Ok((daily, warnings))
    }
}
