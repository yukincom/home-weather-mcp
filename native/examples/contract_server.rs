//! Test-only host: injects local HTTP endpoints and a fixed clock into the real server.
//! Not installed or included in binary releases.
use anyhow::{Context, Result};
use home_weather_core::{
    api::WeatherApi,
    server::{serve, WeatherServer},
};
use std::{path::PathBuf, sync::Arc, time::Duration};
fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let path = PathBuf::from(args.get(1).context("config required")?);
    let base = args.get(2).context("base required")?;
    let timeout = args
        .get(3)
        .context("timeout milliseconds required")?
        .parse()?;
    let api = WeatherApi::with_endpoints(
        &format!("{base}/forecast"),
        &format!("{base}/search"),
        &format!("{base}/gsi"),
        Duration::from_millis(timeout),
    )?;
    let server = WeatherServer::new(path, Arc::new(api), "en".into())?
        .with_clock(|| "2026-09-05T05:00:00Z".parse().unwrap());
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(serve(server.clone()))
}
