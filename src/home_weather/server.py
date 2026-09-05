"""Standard stdio MCP entry point, independent of Hermes internals."""

import argparse
import os
from pathlib import Path
from typing import Literal
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .api import WeatherAPI
from .forecast import build_result
from .locations import LocationStore, clean_name


def create_server(config_path: Path, api=None, language="en"):
    store = LocationStore(config_path)
    api = api or WeatherAPI()
    mcp = FastMCP("home-weather", log_level="WARNING", instructions=(
        "Fetch weather on demand with weather_get. Do not schedule background requests. "
        "Use weather_list_locations to look up names. Omit alias to use the default location (initially Tokyo). "
        "Register, update, or remove settings only when requested by the user. Up to three locations; "
        "each has a primary alias, additional aliases, and a real place name resolved to coordinates. "
        "Use weather_update_location to change a place, its names, or the default. "
        "If geocoding is ambiguous, ask the user to choose a candidate. Never register examples automatically. "
        "Weather data is not saved. Save to Obsidian with other tools only if the user requests it. "
        "Preserve units, target dates and timestamps. Missing data never means clear skies or zero rain. "
        "temperature_range contains the daily high-minus-low in Celsius and an inclusive 7-degree flag. "
        "This is not a comparison with yesterday. A null flag means unknown. "
        "Use this signal to tailor a conversational reminder to the user; do not infer their health status. "
        "Weather summaries are available in English and Japanese; language selects the displayed weather labels."
    ))
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
    local_read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=local_read)
    def weather_list_locations() -> dict:
        """List up to three locations, their primary/alternate names, coordinates, and default status."""
        return {"locations": store.list(), "limit": 3}

    @mcp.tool(annotations=read)
    def weather_search_places(place_name: str, country_code: str = "JP") -> dict:
        """Search a real place name for geographic candidates without changing settings.

        Use country_code (JP by default) for the country. Check administrative regions
        when names are ambiguous. Japanese ward names use GSI as a fallback.

        """
        return {"candidates": api.search(place_name, country_code), "source": "Open-Meteo / GeoNames; Japanese address fallback: GSI"}

    def resolve(place_name, country_code, candidate_id):
        candidates = api.search(place_name, country_code)
        if candidate_id is not None:
            chosen = next((row for row in candidates if str(row["id"]) == candidate_id), None)
            if chosen is None:
                raise ValueError("Candidate ID is not in these search results. Search again.")
        elif len(candidates) == 1:
            chosen = candidates[0]
        else:
            return None, candidates
        return {"place_name": clean_name(place_name), "latitude": chosen["latitude"],
                "longitude": chosen["longitude"], "timezone": chosen["timezone"], "resolved": chosen}, candidates

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    def weather_set_location(
        alias: str, place_name: str, additional_aliases: list[str] | None = None,
        make_default: bool = False, candidate_id: str | None = None, country_code: str = "JP",
    ) -> dict:
        """Add a location requested by the user. Only location settings are persisted.

        Example: alias=Office, place_name=Osaka, Japan, country_code=JP.
        At most three locations. additional_aliases supplies alternate names.
        make_default=true selects this location when alias is omitted in weather_get.
        Multiple geocoding matches are returned without saving; pass a selected candidate_id
        as a string. Use weather_update_location to modify an existing location.

        """
        alias, place_name = clean_name(alias), clean_name(place_name)
        item, candidates = resolve(place_name, country_code, candidate_id)
        if item is None:
            return {"registered": False, "candidates": candidates,
                    "message": "Refine the place name or select a candidate_id from the results."}
        item.update({"alias": alias, "additional_aliases": additional_aliases or [], "is_default": make_default})
        return {"registered": True, "location": store.set(item)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))
    def weather_update_location(
        alias: str, place_name: str | None = None, new_alias: str | None = None,
        additional_aliases: list[str] | None = None, make_default: bool = False,
        candidate_id: str | None = None, country_code: str = "JP",
    ) -> dict:
        """Update an existing location without adding a slot.

        alias identifies the location using any current name. Changing place_name resolves
        new coordinates. new_alias renames the primary alias. additional_aliases replaces
        the alternate names; [] removes them. Omitted fields remain unchanged.
        make_default=true selects this place as the default. Ambiguous geocoding returns
        candidates without saving. Retry with the selected candidate_id as a string.

        """
        store.get(alias)
        updates = {}
        if place_name is not None:
            resolved, candidates = resolve(place_name, country_code, candidate_id)
            if resolved is None:
                return {"updated": False, "candidates": candidates,
                        "message": "Refine the place name or select a candidate_id from the results."}
            updates.update(resolved)
        if new_alias is not None:
            updates["alias"] = new_alias
        if additional_aliases is not None:
            updates["additional_aliases"] = additional_aliases
        if make_default:
            updates["is_default"] = True
        return {"updated": True, "location": store.update(alias, updates)}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
    def weather_remove_location(alias: str) -> dict:
        """Remove a location as requested. Removing the default selects the first remaining location."""
        return {"removed": store.remove(alias)}

    default_language = language

    @mcp.tool(annotations=read)
    def weather_get(alias: str | None = None, target: Literal["current", "today", "tomorrow"] = "today", include_hourly: bool = False, language: Literal["en", "ja"] | None = None) -> dict:
        """Fetch fresh weather for a registered primary or alternate name.

        Omit alias to use the default (initially Tokyo). target: current, today, or tomorrow.
        Forecasts include temperature_range: value_c, threshold_c, is_large (>= threshold),
        and basis=daily_max_minus_min. Missing/invalid temperatures yield null value and flag.
        Includes rain intervals and temperature/umbrella advice. Today's rain covers the
        remaining hours. include_hourly=true adds hourly values. Units: Celsius, m/s, mm;
        timestamps use the location timezone. No weather storage, cache or scheduling.
        language=en|ja overrides the server default. Both summary_en and summary_ja are
        included for forecasts; summary and weather labels use the selected language.

        """
        location = store.get(alias)
        data, warnings = api.forecast(location, target)
        return build_result(location, data, warnings, target, include_hourly, language=language or default_language)

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(os.environ.get(
        "HOME_WEATHER_CONFIG", str(Path.home() / ".config/home-weather-mcp/locations.json"))))
    parser.add_argument("--language", choices=["en", "ja"], default="en")
    args = parser.parse_args()
    create_server(args.config.expanduser().resolve(), language=args.language).run(transport="stdio")


if __name__ == "__main__":
    main()
