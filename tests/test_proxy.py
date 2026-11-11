import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mediamarkt_mcp.client import Client, RetailerError
from mediamarkt_mcp.shop.http import _session


def proxy_environment(url):
    return {'HTTPS_PROXY': url, 'https_proxy': '', 'ALL_PROXY': '', 'all_proxy': '', 'NO_PROXY': '', 'no_proxy': ''}


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)

    async def test_standard_environment_is_available_for_all_request_types(self):
        state = {'ROOT_QUERY': {'searchV4:{}': {'totalProducts': 0, 'paging': {}, 'products': []}}}
        search = SimpleNamespace(status_code=200, url='https://www.mediamarkt.de/de/search.html', text='window.__PRELOADED_STATE__ = ' + json.dumps({'apolloState': state}))
        missing = SimpleNamespace(status_code=404)
        homepage = SimpleNamespace(status_code=200, text='<meta name="version" content="1.2.3">')
        graphql = SimpleNamespace(status_code=200, headers={}, json=lambda: {'data': {'storeSuggestions': []}})
        with patch.dict(os.environ, proxy_environment('socks5h://user:password@proxy.example:1080')), patch('mediamarkt_mcp.shop.http.AsyncSession') as factory, patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            manager = AsyncMock(); session = manager.__aenter__.return_value
            session.get.side_effect = [search, missing, homepage, graphql]
            factory.return_value = manager
            client = Client()
            await client.search('test')
            await client.product('https://www.mediamarkt.de/de/product/_unknown-123.html')
            await client.stores('Berlin')
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(session.get.await_count, 4)
        for call in factory.call_args_list:
            self.assertNotIn('proxy', call.kwargs)
            self.assertNotEqual(call.kwargs.get('trust_env'), False)

    async def test_authenticated_http_proxy_and_redacted_errors(self):
        received = []
        async def handle(reader, writer):
            try:
                received.append(await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3))
                writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="test"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
            finally:
                writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with patch.dict(os.environ, proxy_environment(f'http://testuser:testsecret@127.0.0.1:{port}')), patch('mediamarkt_mcp.shop.http._last_request', 0.0):
                with self.assertRaises(RetailerError) as error:
                    await asyncio.wait_for(Client().search('test'), 8)
            self.assertNotIn('testsecret', str(error.exception))
            self.assertNotIn('testuser', str(error.exception))
            self.assertEqual(error.exception.code, 'proxy_error')
        finally:
            server.close(); await server.wait_closed()
        expected = b'proxy-authorization: basic ' + base64.b64encode(b'testuser:testsecret').lower()
        self.assertTrue(any(expected in request.lower() for request in received))
        self.assertIn(b'CONNECT www.mediamarkt.de:443', received[0])

    async def test_legacy_proxy_settings_fail_closed(self):
        from mediamarkt_mcp.shop.cache import cached_call
        for name in ('MMS_PROXY', 'MMS_PROXY_FILE'):
            with self.subTest(name=name), patch.dict(os.environ, {name: 'private-value'}), patch('mediamarkt_mcp.shop.http.AsyncSession') as factory:
                with self.assertRaises(RetailerError) as error:
                    _session(timeout=1)
                self.assertEqual(error.exception.code, 'invalid_input')
                self.assertNotIn('private-value', str(error.exception))
                factory.assert_not_called()
                fetch = AsyncMock(return_value={'products': []})
                with self.assertRaises(RetailerError):
                    await cached_call('search', ('legacy',), False, fetch)
                fetch.assert_not_awaited()

    async def test_no_proxy_bypasses_standard_proxy(self):
        async def serve(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK')
            await writer.drain(); writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(serve, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            env = {'http_proxy': 'http://127.0.0.1:1', 'ALL_PROXY': '', 'all_proxy': '', 'NO_PROXY': '127.0.0.1', 'no_proxy': '127.0.0.1'}
            with patch.dict(os.environ, env):
                async with _session(timeout=3) as session:
                    response = await session.get(f'http://127.0.0.1:{port}/')
            self.assertEqual(response.status_code, 200)
        finally:
            server.close(); await server.wait_closed()

    async def test_config_references_dotenv_without_exposing_its_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('HTTPS_PROXY=http://testuser:testsecret@proxy.example:8080\n')
            with patch('mediamarkt_mcp.cli.shutil.which', return_value='/usr/local/bin/uv'), patch('sys.argv', ['mediamarkt-saturn-mcp', '--config', '--env-file', str(path)]), patch('sys.stdout', new_callable=__import__('io').StringIO) as stdout:
                from mediamarkt_mcp.cli import main
                main()
            output = stdout.getvalue()
            config = json.loads(output)['mcpServers']['mediamarkt-saturn']
            self.assertEqual(config['command'], '/usr/local/bin/uv')
            self.assertIn(str(path.resolve()), config['args'])
            self.assertNotIn('testsecret', output)
            self.assertNotIn('testuser', output)

    @unittest.skipUnless(shutil.which('uv'), 'uv is needed to test dotenv launcher')
    async def test_uv_dotenv_launcher_supplies_standard_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('HTTPS_PROXY=http://testuser:testsecret@proxy.example:8080\n')
            env = {key: value for key, value in os.environ.items() if key.lower() not in {'https_proxy', 'all_proxy', 'no_proxy'}}
            result = await asyncio.create_subprocess_exec(shutil.which('uv'), 'run', '--no-project', '--env-file', str(path), '--', sys.executable, '-c', 'import os; print(os.getenv("HTTPS_PROXY", "").endswith("@proxy.example:8080"))', env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await result.communicate()
            self.assertEqual(result.returncode, 0, stderr.decode())
            self.assertEqual(stdout.decode().strip(), 'True')
            self.assertNotIn(b'testsecret', stdout + stderr)

    @unittest.skipUnless(shutil.which('uv'), 'uv is needed to test the MCP dotenv setup')
    async def test_generated_mcp_config_loads_dotenv_and_uses_authenticated_proxy(self):
        from mcp import Client as MCPClient
        from mcp.client.stdio import StdioServerParameters, stdio_client
        received = []
        async def handle(reader, writer):
            try:
                received.append(await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5))
                writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="test"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
            finally:
                writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(handle, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / '.env'
                path.write_text(f'HTTPS_PROXY=http://testuser:testsecret@127.0.0.1:{port}\n')
                with patch('sys.argv', ['mediamarkt-saturn-mcp', '--config', '--env-file', str(path)]), patch('sys.stdout', new_callable=__import__('io').StringIO) as stdout:
                    from mediamarkt_mcp.cli import main
                    main()
                output = stdout.getvalue()
                config = json.loads(output)['mcpServers']['mediamarkt-saturn']
                self.assertNotIn('testsecret', output)
                env = {key: value for key, value in os.environ.items() if key.lower() not in {'https_proxy', 'all_proxy', 'no_proxy', 'mms_proxy', 'mms_proxy_file'}}
                params = StdioServerParameters(command=config['command'], args=config['args'], env=env)
                with open(os.devnull, 'w') as error_log:
                    async with MCPClient(stdio_client(params, errlog=error_log)) as client:
                        result = await asyncio.wait_for(client.call_tool('search_products', {'query': 'test', 'fresh': True}), 15)
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content['error']['code'], 'proxy_error')
                self.assertNotIn('testsecret', str(result.content))
        finally:
            server.close(); await server.wait_closed()
        expected = b'proxy-authorization: basic ' + base64.b64encode(b'testuser:testsecret').lower()
        self.assertTrue(any(expected in request.lower() for request in received))
