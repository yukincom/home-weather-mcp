# Agent reference

This document is for agents using or maintaining Home Weather MCP. Human-facing setup and examples belong in [README.md](README.md) and [README.ja.md](README.ja.md).

## Runtime and configuration

Source builds require Rust/cargo. The complete runtime is Rust; Python/uv are used only for external protocol tests.
Run the installed standalone stdio MCP executable. It does not import or modify Hermes internals. macOS/Linux are supported; location-setting writes use POSIX file locks.

```sh
.install/bin/home-weather-mcp --help
.install/bin/home-weather-mcp --language en
```

Default settings path: `~/.config/home-weather-mcp/locations.json`. Override with `--config /absolute/path/locations.json` or `HOME_WEATHER_CONFIG`.

When that file does not exist, use Tokyo, Japan (35.6895, 139.69171; Asia/Tokyo), with aliases `Tokyo` and `東京`. Reading this default does not create a file. The first settings change persists the list. An explicitly saved empty list stays empty. See [example settings](examples/locations.example.json).

Set the server language with `--language en|ja`; default `en`. For other stdio clients, reuse the command and arguments from [the Hermes example](examples/hermes-mcp.yaml) in the client's own configuration format.

## Calling policy

- Fetch weather when requested. There is no scheduler, weather cache, or weather-file output. Only location settings are persisted.
- Register, update, or remove locations only when the user requests it. Do not register places mentioned merely as examples.
- Omit the location argument when the user has not specified a place, so the configured default is used.
- Geocoding uses Open-Meteo/GeoNames and falls back to GSI for Japanese addresses and wards. Use `country_code` for international searches, such as `GB` for London; the default is `JP`.
- If there are multiple candidates, ask the user to choose one before saving. Pass candidate IDs as strings.
- There is no Obsidian integration. If the user requests saving, use the client's other tools. The client may retain conversation/tool history according to its own settings.

## Tools

| Tool | Purpose |
| --- | --- |
| `weather_list_locations` | List places, aliases, coordinates, and default status |
| `weather_search_places` | Search a real place name without saving |
| `weather_set_location` | Add a place, optionally with alternate names and default status |
| `weather_update_location` | Change place, primary name, alternate names, or default |
| `weather_remove_location` | Remove a place |
| `weather_get` | Fetch current, today, or tomorrow weather |

`weather_get` arguments:

| Argument | Default | Meaning |
| --- | --- | --- |
| `alias` | omitted | Primary/alternate name; omission selects the default |
| `target` | `today` | `current`, `today`, or `tomorrow` |
| `include_hourly` | `false` | Include hourly values as well as the summary |
| `language` | server setting | `en` or `ja` |

Forecast responses include `summary_en`, `summary_ja`, and `summary` in the selected language. Weather labels and warnings use the selected language; tool descriptions and errors are English. Current-only responses contain weather values and labels rather than a daily summary. Units, source, target date, retrieval time, and timezone are included.

Location updates preserve omitted fields. `additional_aliases` replaces the alternate-name list; `[]` clears it. A primary-name change does not automatically keep the previous primary name as an alias. Names must be unique across all three places, with up to ten names per place. Deleting the default selects the first remaining place.

## Weather behavior

- Celsius, m/s, millimeters; dates and hours are local to the registered place.
- Today's rain windows cover the remaining hours; tomorrow covers the full day. Daily highs/lows and maximum rain probability always refer to the whole day.
- Rain windows use hourly rain/showers, weather codes, or precipitation probability of at least 50%. They are approximate forecast intervals, not radar nowcasts.
- Connection failures/timeouts are retried once. If only hourly retrieval fails, the daily forecast is returned with a warning. Missing values are not converted into clear skies or zero precipitation.
- Weather results are never written by this server. Your MCP client may retain conversation/tool history according to its own settings.

## Development and CI

```sh
cargo fetch --manifest-path native/Cargo.toml --locked
cargo test --manifest-path native/Cargo.toml --locked --offline
cargo build --manifest-path native/Cargo.toml --example contract_server --locked --offline
uv sync --frozen
uv run --frozen python scripts/check_security.py
uv run --frozen pytest -q
cargo install --path native --locked --root .install
.install/bin/home-weather-mcp --version
```

[GitHub Actions](.github/workflows/ci.yml) runs only on pushes (no schedule, pull-request, or manual trigger), using Linux/macOS and Python 3.11/3.14. It checks locked dependencies, unit and real-stdio protocol tests, Rust formatting/lints, source installation, and the installed executable. Tests simulate weather APIs and require neither API credentials nor live weather access. Check the actual workflow result for the commit being reviewed.

## Structured temperature range

Today/tomorrow responses include this language-independent signal:

```json
{"basis": "daily_max_minus_min", "value_c": 10.0, "threshold_c": 7.0, "is_large": true}
```

The value is the daily maximum minus minimum temperature in Celsius, not a change from yesterday. `is_large` is true at **7°C or above**, false below it. Missing, non-finite, or inverted temperatures produce null for both `value_c` and `is_large`. Current-only responses omit the field. Both language summaries use this same rule. The assistant can use the signal to phrase a contextual reminder; the flag does not assess the user's health.

## Implementation provenance

The daily/hourly retrieval and rain/temperature advice originated from the StackChan_EX_Amigo weather service design. This independent version excludes its scheduler, conversation routing, journal, and weather cache. Do not distribute personal settings or client configuration backups.

Protocol implementation: [official MCP Rust SDK](https://github.com/modelcontextprotocol/rust-sdk).
