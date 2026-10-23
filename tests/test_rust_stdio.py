"""External MCP client tests against the compiled Rust server and local HTTP fixtures."""
import asyncio
from contextlib import asynccontextmanager
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('WEATHER_BINARY', ROOT / 'native/target/debug/home-weather-mcp')).resolve()
CONTRACT = Path(os.environ.get('WEATHER_CONTRACT_BINARY', ROOT / 'native/target/debug/examples/contract_server')).resolve()
REFERENCE = json.loads((ROOT / 'native/tests/fixtures/forecast_cases.json').read_text())[0]


class API:
    def __init__(self):
        self.requests = []
        self.fail_hourly = False
        self.timeout_first = False
        self.reset_first = False
        self.invalid_json = False
        self.status = 200
        self.payload = copy.deepcopy(REFERENCE['data'])
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                state.requests.append((parsed.path, query))
                if state.reset_first and len(state.requests) == 1:
                    import struct
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    self.connection.close()
                    return
                status = state.status
                if state.timeout_first and len(state.requests) == 1:
                    time.sleep(.4)
                if parsed.path == '/search':
                    name = query['name'][0]
                    row = {'id': 1, 'name': name, 'feature_code': 'PPL', 'latitude': 34.7,
                           'longitude': 135.5, 'timezone': 'Asia/Tokyo', 'country_code': 'JP'}
                    result = {'results': [row]}
                    if name == 'Ambiguous':
                        result['results'].append({**row, 'id': 2})
                    if name == '新宿区, 東京都':
                        result['results'] = [{**row, 'feature_code': 'PRK'}]
                elif parsed.path == '/gsi':
                    result = [{'geometry': {'type': 'Point', 'coordinates': [139.7034, 35.6938]},
                               'properties': {'title': '東京都新宿区'}}]
                else:
                    if 'hourly' in query and state.fail_hourly:
                        status = 503
                    result = {key: value for key, value in state.payload.items()
                              if (key.startswith("hourly")) == ("hourly" in query)}
                body = b'{bad json' if state.invalid_json else json.dumps(result).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@pytest.fixture
def api():
    server = API()
    server.start()
    yield server
    server.close()


@asynccontextmanager
async def client(path, api=None, timeout=1000, language='en', environment=None):
    if api:
        params = StdioServerParameters(command=str(CONTRACT), args=[str(path), api.base, str(timeout)])
    else:
        params = StdioServerParameters(command=str(BINARY), args=['--config', str(path), '--language', language], env=environment)
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    assert not result.isError, result
    data = json.loads(result.content[0].text)
    assert result.structuredContent == data
    return data


def test_production_stdio_schema_defaults_and_no_write(tmp_path):
    async def run():
        path = tmp_path / 'locations.json'
        async with client(path) as session:
            tools = (await session.list_tools()).tools
            original = json.loads((ROOT/'native/resources/tools.json').read_text())
            assert {t.name for t in tools} == {t['name'] for t in original}
            for tool in tools:
                old = next(t for t in original if t['name'] == tool.name)
                assert tool.inputSchema == old['inputSchema']
                assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == old['annotations']
            rows = await call(session, 'weather_list_locations', {})
            assert rows['locations'][0]['alias'] == 'Tokyo'
            for args in [{'target': 'yesterday'}, {'alias': '未知'}, {'include_hourly': 'wrong'}, {'language': 'fr'}]:
                assert (await session.call_tool('weather_get', args)).isError
            assert not path.exists()
    asyncio.run(run())


def test_full_location_lifecycle_and_ambiguity(tmp_path, api):
    async def run():
        path = tmp_path/'locations.json'
        async with client(path, api) as session:
            await call(session,'weather_list_locations',{})
            assert api.requests == []
            result=await call(session,'weather_set_location',{'alias':'Office','place_name':'Ambiguous'})
            assert not result['registered'] and not path.exists()
            result=await call(session,'weather_set_location',{'alias':'Ｏｆｆｉｃｅ','place_name':'Ambiguous','candidate_id':'2','additional_aliases':['職場'],'make_default':True})
            assert result['location']['alias']=='Office'
            before=path.read_bytes()
            result=await call(session,'weather_update_location',{'alias':'職場','place_name':'Ambiguous'})
            assert not result['updated'] and path.read_bytes()==before
            assert (await session.call_tool('weather_update_location',{'alias':'職場','place_name':'Ambiguous','candidate_id':'99'})).isError
            assert path.read_bytes()==before
            result=await call(session,'weather_update_location',{'alias':'職場','new_alias':'Work','additional_aliases':[]})
            assert result['location']['is_default'] and result['location']['additional_aliases']==[]
            assert (await session.call_tool('weather_remove_location',{'alias':'職場'})).isError
            result=await call(session,'weather_set_location',{'alias':'Travel','place_name':'Osaka'})
            assert result['registered']
            before=path.read_bytes()
            assert (await session.call_tool('weather_set_location',{'alias':'Fourth','place_name':'Kyoto'})).isError
            assert path.read_bytes()==before
            assert (await session.call_tool('weather_update_location',{'alias':'Work','additional_aliases':['東京']})).isError
            assert path.read_bytes()==before
            await call(session,'weather_remove_location',{'alias':'Work'})
            rows=await call(session,'weather_list_locations',{})
            assert rows['locations'][0]['is_default'] and rows['locations'][0]['alias']=='Tokyo'
            await call(session,'weather_remove_location',{'alias':'東京'})
            await call(session,'weather_remove_location',{'alias':'Travel'})
            assert (await call(session,'weather_list_locations',{}))['locations']==[]
        async with client(path, api) as session:
            assert (await call(session,'weather_list_locations',{}))['locations']==[]
            assert (await session.call_tool('weather_get',{})).isError
    asyncio.run(run())


def test_http_geocoding_ward_query_and_stable_id(tmp_path, api):
    async def run():
        async with client(tmp_path/'locations.json',api) as session:
            result=await call(session,'weather_search_places',{'place_name':'東京都新宿区'})
            row=result['candidates'][0]
            import hashlib
            assert row['id']=='gsi-'+hashlib.sha256('東京都新宿区:35.6938:139.7034'.encode()).hexdigest()[:16]
            assert row['latitude']==35.6938
            assert api.requests[0][1]['name']==['新宿区, 東京都']
            assert api.requests[1][1]['q']==['東京都新宿区']
            result=await call(session,'weather_search_places',{'place_name':'London','country_code':'gb'})
            assert result['candidates']
            assert api.requests[-1][1]['countryCode']==['GB']
            assert (await session.call_tool('weather_search_places',{'place_name':'London','country_code':'GBR'})).isError
    asyncio.run(run())


def test_forecasts_both_languages_freshness_and_hourly_failure(tmp_path, api):
    async def run():
        path=tmp_path/'locations.json'
        async with client(path,api) as session:
            results={}
            for target in ['current','today','tomorrow']:
                for language in ['en','ja']:
                    result=await call(session,'weather_get',{'target':target,'language':language,'include_hourly':True})
                    assert result['target']==target and result['language']==language
                    if target=='current': assert 'temperature_range' not in result
                    else:
                        assert result['summary']==result['summary_'+language]
                        assert result['daily']['date']==('2026-09-05' if target=='today' else '2026-09-06')
                    results[target,language]=result
            assert results['today','en']['summary_ja']==results['today','ja']['summary_ja']
            assert results['today','en']['temperature_range']==results['today','ja']['temperature_range']
            assert len(api.requests)==10  # two current calls; four daily + hourly calls
            for _,query in api.requests:
                assert query['temperature_unit']==['celsius'] and query['wind_speed_unit']==['ms']
                assert query['timezone']==['Asia/Tokyo']
            assert not path.exists()
            api.fail_hourly=True
            result=await call(session,'weather_get',{'language':'ja'})
            assert result['daily'] and result['warnings'] and not result['hourly_detail_available']
            assert '詳細は取得できませんでした' in result['warnings'][0]
    asyncio.run(run())


def test_timeout_retries_once(tmp_path, api):
    api.timeout_first=True
    async def run():
        async with client(tmp_path/'locations.json',api,timeout=100) as session:
            result=await call(session,'weather_get',{'target':'current'})
            assert result['current']['temperature_2m']==28
            assert len(api.requests)==2
    asyncio.run(run())


@pytest.mark.parametrize('failure',['status','json','missing'])
def test_invalid_http_responses_are_tool_errors(tmp_path,api,failure):
    if failure=='status':api.status=503
    elif failure=='json':api.invalid_json=True
    else:api.payload={}
    async def run():
        async with client(tmp_path/'locations.json',api) as session:
            assert (await session.call_tool('weather_get',{'target':'current'})).isError
            assert len(api.requests)==1
    asyncio.run(run())


def test_corrupt_settings_remain_untouched(tmp_path,api):
    path=tmp_path/'locations.json';path.write_text('{broken')
    async def run():
        async with client(path,api) as session:
            assert (await session.call_tool('weather_set_location',{'alias':'Home','place_name':'Osaka'})).isError
            assert path.read_text()=='{broken'
    asyncio.run(run())


def test_untrusted_tls_is_rejected(tmp_path):
    key=tmp_path/'key.pem';certificate=tmp_path/'cert.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(certificate),'-days','1','-subj','/CN=localhost'],check=True,capture_output=True)
    api=API()
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certificate,key)
    api.server.socket=context.wrap_socket(api.server.socket,server_side=True)
    api.base=api.base.replace('http:','https:');api.start()
    async def run():
        async with client(tmp_path/'locations.json',api) as session:
            assert (await session.call_tool('weather_get',{'target':'current'})).isError
            assert not api.requests
    try:asyncio.run(run())
    finally:api.close()


def test_cli_help_and_environment_config(tmp_path):
    result=subprocess.run([str(BINARY),'--help'],capture_output=True,text=True,check=True)
    assert '--config' in result.stdout and '--language' in result.stdout
    path=tmp_path/'empty.json';path.write_text('{"version":1,"locations":[]}')
    async def run():
        params=StdioServerParameters(command=str(BINARY),args=[],env={**os.environ,'HOME_WEATHER_CONFIG':str(path)})
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                assert (await call(session,'weather_list_locations',{}))['locations']==[]
    asyncio.run(run())


def test_connection_reset_retries_once(tmp_path, api):
    api.reset_first=True
    async def run():
        async with client(tmp_path/'locations.json',api) as session:
            result=await call(session,'weather_get',{'target':'current'})
            assert result['current']['temperature_2m']==28
            assert len(api.requests)==2
    asyncio.run(run())


def test_configuration_symlink_updates_target(tmp_path):
    target=tmp_path/'real.json'
    link=tmp_path/'link.json'
    target.write_text(json.dumps({'version':1,'locations':[REFERENCE['location']]}))
    link.symlink_to(target)
    async def run():
        async with client(link) as session:
            await call(session,'weather_remove_location',{'alias':'Tokyo'})
    asyncio.run(run())
    assert link.is_symlink()
    assert json.loads(target.read_text())['locations']==[]
    assert Path(str(target)+'.lock').exists()
    assert not Path(str(link)+'.lock').exists()
