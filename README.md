# Home Weather MCP

[日本語](README.ja.md) · [MIT License](LICENSE)

Ask Hermes for the weather at up to three places you choose. Powered by Open-Meteo, Home Weather MCP works with Hermes and other compatible MCP clients.

**Tokyo is the initial default.** English and Japanese are supported. No API key is needed for Open-Meteo's non-commercial service.

## What you can do

- Check current conditions, today's forecast, or tomorrow's forecast.
- Ask about temperature, humidity, wind, rain probability, and when rain is expected.
- Get umbrella suggestions and a reminder about large daytime temperature changes.
- Give places familiar names such as Home or Office, add alternate names, and change them through conversation.
- Choose which place to use when you ask for weather without specifying a location.

## Setup

You need macOS or Linux, Python 3.11 or newer, [uv](https://docs.astral.sh/uv/) >= 0.13.4, and an internet connection.

```sh
git clone https://github.com/yukincom/home-weather-mcp.git
cd home-weather-mcp
uv sync --frozen
uv run --frozen python scripts/check_security.py
```

Add the following entry under `mcp_servers` in Hermes's `config.yaml`. Replace `/absolute/path/home-weather-mcp` with the absolute path to your checkout, and keep your existing server entries.

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

Reload MCP or restart Hermes after adding the server. Location changes made later take effect without a restart. Change `en` to `ja` for Japanese responses.

## Try asking

- “What's the weather today?” — uses your default place, initially Tokyo.
- “Add Osaka, Japan as Office, with Work as another name.”
- “Will it rain at Work tomorrow?”
- “Change Office to Kyoto, Japan.”
- “Make Office my default weather location.”
- “Rename Tokyo to Home and keep Tokyo as an alternate name.”
- “Show today's forecast in Japanese.”

You can register up to three places. Include the country when adding an overseas location. If several places match, choose the one you mean from the results.

## License and credits

The software uses the [MIT License](LICENSE). Weather data is provided by [Open-Meteo](https://open-meteo.com/), with [its own service limits and attribution terms](https://open-meteo.com/en/pricing). Place lookup uses [GeoNames via Open-Meteo](https://open-meteo.com/en/docs/geocoding-api) and, where needed, [GSI](https://github.com/gsi-cyberjapan/gsimaps/issues/29).

Agent and development reference: [Agent.md](Agent.md).

Security update / セキュリティ更新: [2026-10-23 migration](docs/2026-10-23-security.md).
