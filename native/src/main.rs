use anyhow::{bail, Context, Result};
use home_weather_core::{
    api::WeatherApi,
    server::{serve, WeatherServer},
};
use std::{env, path::PathBuf, sync::Arc};

fn main() -> Result<()> {
    let mut config = env::var_os("HOME_WEATHER_CONFIG").map(PathBuf::from);
    let mut language = "en".to_owned();
    let mut args = env::args_os().skip(1);
    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("--config") => {
                config = Some(args.next().context("--config requires a path")?.into())
            }
            Some("--language") => {
                language = args
                    .next()
                    .context("--language requires en or ja")?
                    .into_string()
                    .map_err(|_| anyhow::anyhow!("Invalid language"))?
            }
            Some("--help" | "-h") => {
                println!("Home Weather MCP {}\nUsage: home-weather-mcp [--config PATH] [--language en|ja]\n\nDefault configuration: ~/.config/home-weather-mcp/locations.json\nEnvironment override: HOME_WEATHER_CONFIG\nWeather is fetched only when requested. Logs use stderr; stdio carries MCP.",env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            Some("--version" | "-V") => {
                println!("home-weather-mcp {}", env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            _ => bail!("Unknown argument: {}", arg.to_string_lossy()),
        }
    }
    let mut config = match config {
        Some(path) => path,
        None => {
            PathBuf::from(env::var_os("HOME").context("HOME is unavailable; specify --config.")?)
                .join(".config/home-weather-mcp/locations.json")
        }
    };
    config = home_weather_core::config_path::resolve(&config)?;
    // Construct and drop reqwest's blocking client outside an async runtime.
    let server = WeatherServer::new(config, Arc::new(WeatherApi::new()?), language)?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    runtime.block_on(serve(server.clone()))
}
