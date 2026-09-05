# Home Weather MCP

[日本語](README.ja.md) · [MIT License](LICENSE)

On-demand weather for up to three named locations, powered by Open-Meteo. Runs as a standalone **stdio MCP server** with Hermes or another compatible MCP client. It does not import or modify Hermes internals.

**Tokyo is the initial default.** English is the default presentation language; Japanese is also available. No API key is needed for Open-Meteo's non-commercial service.

## Features

- Current conditions, today's forecast, and tomorrow's forecast.
- Primary and alternate location names, plus a configurable default when no place is specified.
- Register, change, rename, and remove locations through MCP tools. Changing a place name resolves new coordinates.
- Temperature, apparent temperature, humidity, wind, daily rain probability, and hourly rain windows with umbrella and temperature advice.
- English and Japanese summaries based on the same weather values.
- Fetches only when a tool is called. No scheduler, weather cache, weather files, or Obsidian integration. Only location settings are persisted.
- Open-Meteo/GeoNames geocoding, with a GSI fallback for Japanese addresses and wards.

## Requirements

- macOS or Linux (location-setting writes use POSIX file locks).
- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
- Internet access when looking up places or fetching weather.

## Quick start

From the repository root:

```sh
uv sync --frozen
.venv/bin/python -m home_weather.server
```

The process speaks MCP on standard input/output, so it waits for an MCP client rather than showing an interactive prompt. To see command-line options:

```sh
.venv/bin/python -m home_weather.server --help
```

The first run uses **Tokyo, Japan** (35.6895, 139.69171; Asia/Tokyo), with aliases `Tokyo` and `東京`. It does not create a settings file just to answer weather questions. The first settings change saves the location list to:

```text
~/.config/home-weather-mcp/locations.json
```

Override this with `--config /absolute/path/locations.json` or `HOME_WEATHER_CONFIG`. An explicitly saved empty list stays empty; Tokyo is only the fallback when the file does not exist. See [the example settings](examples/locations.example.json).

## Connect to Hermes

Add the following entry under the existing `mcp_servers` mapping in Hermes's `config.yaml`. Replace the placeholder with the absolute path to this checkout. Do not replace your other MCP entries.

```yaml
mcp_servers:
  home_weather:
    command: /absolute/path/home-weather-mcp/.venv/bin/python
    args: ["-m", "home_weather.server", "--language", "en"]
    enabled: true
    timeout: 60
    connect_timeout: 20
    supports_parallel_tool_calls: false
    tools:
      resources: false
      prompts: false
```

Reload MCP or restart the client after adding the server. Later location-setting changes do not require a restart. For Japanese presentation, change `en` to `ja`. A `language` argument on `weather_get` can override the server default for one call.

Other stdio MCP clients use the same `command` and `args`; their configuration wrapper may differ. A copyable Hermes example is in [examples/hermes-mcp.yaml](examples/hermes-mcp.yaml).

## Example requests

- “What's the weather today?” — uses the default, initially Tokyo.
- “Add Osaka, Japan as Office, with Work as another name.”
- “Will it rain at Work tomorrow?”
- “Change Office to Kyoto, Japan.” — resolves new coordinates without consuming another slot.
- “Make Office my default weather location.”
- “Rename Tokyo to Home and keep Tokyo as an alternate name.”
- “Show today's forecast in Japanese.”

The assistant translates these requests into tool calls. Use `country_code` for international searches (for example, `GB` for London). Its default is `JP`. If a search returns several candidates, no settings are changed until a candidate is selected. Candidate IDs are passed as strings.

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
uv sync --frozen
uv run --frozen pytest -q
uv build
```

[GitHub Actions](.github/workflows/ci.yml) runs on pushes and pull requests, using Linux/macOS and Python 3.11/3.14. It checks the locked environment, runs unit and real-stdio protocol tests, builds the wheel/source distribution, and checks the MIT metadata and release contents. Tests use simulated weather APIs and do not require API credentials or live weather access.

Local checks can be run before upload. GitHub will show the actual CI result after the repository is pushed with Actions enabled; there is no preclaimed CI badge.

## License and data sources

The software is licensed under the [MIT License](LICENSE). Weather data and upstream services retain their own terms:

- [Open-Meteo weather API](https://open-meteo.com/en/docs), [service limits and attribution](https://open-meteo.com/en/pricing).
- [Open-Meteo geocoding / GeoNames](https://open-meteo.com/en/docs/geocoding-api).
- [Geospatial Information Authority of Japan address search](https://github.com/gsi-cyberjapan/gsimaps/issues/29).
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

The daily/hourly retrieval and rain/temperature advice originated from the StackChan_EX_Amigo weather service design. This independent version excludes its scheduler, conversation routing, journal, and weather cache. No personal location settings or client configuration backups are distributed.
