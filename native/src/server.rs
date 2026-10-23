//! The six existing tools over the official MCP Rust stdio SDK.
use crate::{
    api::WeatherSource,
    forecast::build_result,
    locations::{clean_name, LocationStore},
};
use anyhow::{bail, ensure, Context, Result};
use chrono::{DateTime, Utc};
use rmcp::{
    model::*, service::RequestContext, transport::stdio, ErrorData, RoleServer, ServerHandler,
    ServiceExt,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{path::PathBuf, sync::Arc};

#[derive(Clone)]
pub struct WeatherServer {
    store: LocationStore,
    api: Arc<dyn WeatherSource>,
    language: String,
    tools: Vec<Tool>,
    clock: Arc<dyn Fn() -> DateTime<Utc> + Send + Sync>,
}
fn jp() -> String {
    "JP".to_owned()
}
fn today() -> String {
    "today".to_owned()
}
#[derive(Deserialize)]
struct Search {
    place_name: String,
    #[serde(default = "jp")]
    country_code: String,
}
#[derive(Deserialize)]
struct SetLocation {
    alias: String,
    place_name: String,
    additional_aliases: Option<Vec<String>>,
    candidate_id: Option<String>,
    #[serde(default)]
    make_default: bool,
    #[serde(default = "jp")]
    country_code: String,
}
#[derive(Deserialize)]
struct UpdateLocation {
    alias: String,
    place_name: Option<String>,
    new_alias: Option<String>,
    additional_aliases: Option<Vec<String>>,
    candidate_id: Option<String>,
    #[serde(default)]
    make_default: bool,
    #[serde(default = "jp")]
    country_code: String,
}
#[derive(Deserialize)]
struct Alias {
    alias: String,
}
#[derive(Deserialize)]
struct GetWeather {
    alias: Option<String>,
    language: Option<String>,
    #[serde(default = "today")]
    target: String,
    #[serde(default)]
    include_hourly: bool,
}
impl WeatherServer {
    pub fn new(config: PathBuf, api: Arc<dyn WeatherSource>, language: String) -> Result<Self> {
        ensure!(
            ["en", "ja"].contains(&language.as_str()),
            "language must be en or ja."
        );
        Ok(Self {
            store: LocationStore::new(config),
            api,
            language,
            tools: serde_json::from_str(include_str!("../resources/tools.json"))?,
            clock: Arc::new(Utc::now),
        })
    }
    /// An explicit injected clock keeps date-boundary tests deterministic.
    pub fn with_clock(mut self, clock: impl Fn() -> DateTime<Utc> + Send + Sync + 'static) -> Self {
        self.clock = Arc::new(clock);
        self
    }
    fn resolve(
        &self,
        place: &str,
        country: &str,
        candidate: Option<&str>,
    ) -> Result<(Option<Value>, Vec<Value>)> {
        let candidates = self.api.search(place, country)?;
        let chosen = if let Some(id) = candidate {
            Some(
                candidates
                    .iter()
                    .find(|row| match &row["id"] {
                        Value::String(s) => s == id,
                        Value::Number(n) => n.to_string() == id,
                        _ => false,
                    })
                    .context("Candidate ID is not in these search results. Search again.")?,
            )
        } else if candidates.len() == 1 {
            Some(&candidates[0])
        } else {
            None
        };
        let item = if let Some(chosen) = chosen {
            Some(
                json!({"place_name":clean_name(place)?,"latitude":chosen["latitude"],"longitude":chosen["longitude"],"timezone":chosen["timezone"],"resolved":chosen}),
            )
        } else {
            None
        };
        Ok((item, candidates))
    }
    pub fn dispatch(&self, name: &str, args: Value) -> Result<Value> {
        ensure!(args.is_object(), "Tool arguments must be an object.");
        match name {
            "weather_list_locations" => Ok(json!({"locations":self.store.list()?,"limit":3})),
            "weather_search_places" => {
                let args: Search = serde_json::from_value(args)?;
                Ok(
                    json!({"candidates":self.api.search(&args.place_name,&args.country_code)?,"source":"Open-Meteo / GeoNames; Japanese address fallback: GSI"}),
                )
            }
            "weather_set_location" => {
                let args: SetLocation = serde_json::from_value(args)?;
                let alias = clean_name(&args.alias)?;
                let place = clean_name(&args.place_name)?;
                let (item, candidates) =
                    self.resolve(&place, &args.country_code, args.candidate_id.as_deref())?;
                let Some(mut item) = item else {
                    return Ok(
                        json!({"registered":false,"candidates":candidates,"message":"Refine the place name or select a candidate_id from the results."}),
                    );
                };
                item["alias"] = json!(alias);
                item["additional_aliases"] = json!(args.additional_aliases.unwrap_or_default());
                item["is_default"] = json!(args.make_default);
                Ok(json!({"registered":true,"location":self.store.set(item)?}))
            }
            "weather_update_location" => {
                let args: UpdateLocation = serde_json::from_value(args)?;
                self.store.get(Some(&args.alias))?;
                let mut updates = json!({});
                if let Some(place) = args.place_name {
                    let (item, candidates) =
                        self.resolve(&place, &args.country_code, args.candidate_id.as_deref())?;
                    let Some(item) = item else {
                        return Ok(
                            json!({"updated":false,"candidates":candidates,"message":"Refine the place name or select a candidate_id from the results."}),
                        );
                    };
                    updates = item;
                }
                if let Some(alias) = args.new_alias {
                    updates["alias"] = json!(alias);
                }
                if let Some(aliases) = args.additional_aliases {
                    updates["additional_aliases"] = json!(aliases);
                }
                if args.make_default {
                    updates["is_default"] = json!(true);
                }
                Ok(json!({"updated":true,"location":self.store.update(&args.alias,updates)?}))
            }
            "weather_remove_location" => {
                let args: Alias = serde_json::from_value(args)?;
                Ok(json!({"removed":self.store.remove(&args.alias)?}))
            }
            "weather_get" => {
                let args: GetWeather = serde_json::from_value(args)?;
                ensure!(
                    ["current", "today", "tomorrow"].contains(&args.target.as_str()),
                    "target must be current, today or tomorrow."
                );
                let language = args.language.as_deref().unwrap_or(&self.language);
                ensure!(
                    ["en", "ja"].contains(&language),
                    "language must be en or ja."
                );
                let location = self.store.get(args.alias.as_deref())?;
                let (data, warnings) = self.api.forecast(&location, &args.target)?;
                build_result(
                    location,
                    data,
                    warnings,
                    &args.target,
                    args.include_hourly,
                    language,
                    Some((self.clock)()),
                )
            }
            _ => bail!("Unknown tool: {name}"),
        }
    }
}
impl ServerHandler for WeatherServer {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
            .with_server_info(Implementation::new(
                "home-weather",
                env!("CARGO_PKG_VERSION"),
            ))
            .with_instructions(
                include_str!("../resources/instructions.txt")
                    .trim()
                    .to_owned(),
            )
    }
    async fn list_tools(
        &self,
        _: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        Ok(ListToolsResult::with_all_items(self.tools.clone()))
    }
    fn get_tool(&self, name: &str) -> Option<Tool> {
        self.tools.iter().find(|tool| tool.name == name).cloned()
    }
    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let server = self.clone();
        // Blocking network and flock work must not block the MCP protocol runtime.
        let outcome = tokio::task::spawn_blocking(move || {
            server.dispatch(
                &request.name,
                Value::Object(request.arguments.unwrap_or_default()),
            )
        })
        .await;
        let result = match outcome {
            Ok(Ok(value)) => CallToolResult::structured(value),
            Ok(Err(error)) => CallToolResult::error(vec![ContentBlock::text(error.to_string())]),
            Err(error) => CallToolResult::error(vec![ContentBlock::text(format!(
                "Weather operation failed: {error}"
            ))]),
        };
        Ok(result.into())
    }
}
pub async fn serve(server: WeatherServer) -> Result<()> {
    let running = server.serve(stdio()).await?;
    running.waiting().await?;
    Ok(())
}
