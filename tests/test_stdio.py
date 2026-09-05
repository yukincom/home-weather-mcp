import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_actual_stdio_handshake_unknown_place_and_schema_validation(tmp_path):
    async def run():
        config = tmp_path / "locations.json"
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "home_weather.server", "--config", str(config)])
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 6
                result = await session.call_tool("weather_list_locations", {})
                assert not result.isError
                assert json.loads(result.content[0].text)["locations"][0]["alias"] == "Tokyo"
                result = await session.call_tool("weather_get", {"alias": "未知"})
                assert result.isError
                result = await session.call_tool("weather_get", {"target": "yesterday"})
                assert result.isError
                assert not config.exists()
    asyncio.run(run())
