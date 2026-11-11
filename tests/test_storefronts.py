import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp import Client as MCPClient
from mediamarkt_mcp.client import Client, RetailerError
from mediamarkt_mcp.server import mcp


class StorefrontTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests deliberately trigger tool errors; keep test output readable.
        import logging
        log_patch = patch.object(logging.getLogger("mcp.server.mcpserver.server"), "disabled", True)
        log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_country_and_language_validation(self):
        self.assertEqual(Client('mediamarkt', 'it').base, 'https://www.mediaworld.it')
        self.assertEqual(Client('mediamarkt', 'ch', 'fr').currency, 'CHF')
        self.assertEqual(Client('mediamarkt', 'be').language, 'nl')
        with self.assertRaises(ValueError): Client('saturn', 'at')
        with self.assertRaises(ValueError): Client('mediamarkt', 'ch', 'es')

    async def test_localized_delivery_filter(self):
        for country, language, expected in [('at', 'de', 'auf Lager'), ('ch', 'fr', 'En stock'), ('nl', 'nl', 'Op voorraad')]:
            with self.subTest(country=country, language=language):
                client = Client('mediamarkt', country, language)
                client.search_page = AsyncMock(return_value={'products': []})
                await client.search('test', delivery_only=True)
                self.assertEqual(client.search_page.await_args.args[2], [f'availabilityText:{expected}'])
        with self.assertRaises(RetailerError):
            await Client('mediamarkt', 'es').search('test', delivery_only=True)

    async def test_localized_graphql_headers(self):
        client = Client('mediamarkt', 'ch', 'fr')
        session = AsyncMock()
        session.get.side_effect = [SimpleNamespace(status_code=200, text='<meta name="version" content="1.0">'),
                                   SimpleNamespace(status_code=200, headers={}, json=lambda: {'data': {'storeSuggestions': []}})]
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await client.stores('Zurich')
        headers = session.get.await_args.kwargs['headers']
        self.assertEqual((headers['x-mms-country'], headers['x-mms-language']), ('CH', 'fr'))
        self.assertEqual((result['country'], result['language']), ('ch', 'fr'))

    async def test_mcp_storefront_discovery_and_invalid_combination(self):
        async with MCPClient(mcp) as client:
            result = await client.call_tool('list_storefronts', {})
            shops = result.structured_content['storefronts']
            swiss = next(s for s in shops if s['country'] == 'ch')
            self.assertEqual(swiss['languages'], ['de', 'fr', 'it'])
            self.assertEqual(swiss['currency'], 'CHF')
            result = await client.call_tool('search_products', {'query': 'test', 'country': 'at', 'retailer': 'saturn'})
            self.assertTrue(result.is_error)
            self.assertIn('Germany', result.content[0].text)

    async def test_redirected_search_never_silently_discards_filters(self):
        import json
        state = {'ROOT_QUERY': {'searchV4:{"query":"*"}': {'totalProducts': 1, 'paging': {}}}}
        response = SimpleNamespace(status_code=200, url='https://mediamarkt.pl/pl/brand/nintendo',
                                   text='window.__PRELOADED_STATE__ = ' + json.dumps({'apolloState': state}))
        session = AsyncMock(); session.get.return_value = response
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await Client('mediamarkt', 'pl').search('Nintendo Switch', max_price=1000)
        self.assertEqual(result['coverage'], 'partial_landing_page')
        self.assertEqual(result['local_filters'], ['currentprice:0-1000'])
        self.assertIsNone(result['total_products'])
