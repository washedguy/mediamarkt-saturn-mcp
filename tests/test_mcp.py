import unittest
from unittest.mock import AsyncMock, patch

from mcp import Client as MCPClient
from mediamarkt_mcp.server import mcp


class MCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests deliberately trigger tool errors; keep test output readable.
        import logging
        log_patch = patch.object(logging.getLogger("mcp.server.mcpserver.server"), "disabled", True)
        log_patch.start()
        self.addCleanup(log_patch.stop)

    async def test_discovery_and_structured_results(self):
        result = {"retailer": "saturn", "query": "test", "products": [], "count": 0,
                  "total_products": 0, "page": 1, "next_page": None,
                  "paging": {"current_page": 1, "page_count": 0, "max_page": 1}, "source": "search_page", "coverage": "search_page"}
        with patch("mediamarkt_mcp.server.Client") as factory:
            factory.return_value.search = AsyncMock(return_value=result)
            async with MCPClient(mcp) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, {"list_storefronts", "search_products", "browse_page", "get_product", "find_stores", "check_pickup_availability"})
                self.assertTrue(all(tool.output_schema for tool in tools.tools))
                response = await client.call_tool("search_products", {"query": "test", "retailer": "saturn"})
                self.assertFalse(response.is_error)
                self.assertEqual(response.structured_content["count"], 0)
                self.assertIsNone(response.structured_content["next_page"])

    async def test_browse_page_returns_related_pages_over_mcp(self):
        url = 'https://www.mediamarkt.de/de/brand/apple'
        result = {'retailer': 'mediamarkt', 'query': url, 'products': [], 'count': 0,
                  'total_products': None, 'page': 1, 'next_page': None,
                  'paging': {'current_page': 1, 'page_count': None, 'max_page': None},
                  'source': 'redirected_page', 'coverage': 'partial_landing_page',
                  'related_pages': [url + '/iphone']}
        with patch('mediamarkt_mcp.server.Client') as factory:
            factory.return_value.browse_page = AsyncMock(return_value=result)
            async with MCPClient(mcp) as client:
                response = await client.call_tool('browse_page', {'url': url, 'fresh': True})
        self.assertFalse(response.is_error)
        self.assertEqual(response.structured_content['related_pages'], [url + '/iphone'])

    async def test_bad_price_range_is_an_error(self):
        async with MCPClient(mcp) as client:
            result = await client.call_tool("search_products", {"query": "test", "min_price": 100, "max_price": 10})
            self.assertTrue(result.is_error)
            self.assertIn("min_price must not exceed max_price", result.content[0].text)

    async def test_search_offer_enrichment_keeps_partial_failures_visible(self):
        result = {'retailer': 'mediamarkt', 'query': 'camera', 'products': [
            {'id': '1', 'title': 'First', 'brand': None, 'price': 10, 'currency': 'EUR', 'url': None, 'delivery': {'status': 'unknown', 'retailer_status': None, 'retailer_code': None, 'earliest': None}},
            {'id': '2', 'title': 'Second', 'brand': None, 'price': None, 'currency': 'EUR', 'url': None, 'delivery': {'status': 'unknown', 'retailer_status': None, 'retailer_code': None, 'earliest': None}}],
            'count': 2, 'total_products': 2, 'page': 1, 'next_page': None,
            'paging': {'current_page': 1, 'page_count': 1, 'max_page': 1}, 'source': 'search_page', 'coverage': 'search_page'}
        from mediamarkt_mcp.client import RetailerError
        with patch('mediamarkt_mcp.server.Client') as factory:
            factory.return_value.search = AsyncMock(return_value=result)
            factory.return_value.product = AsyncMock(side_effect=[{'found': True, 'product': {'variants': [], 'marketplace_offers': [], 'offers_coverage': 'embedded_page_only'}}, RetailerError('HTTP 403')])
            async with MCPClient(mcp) as client:
                response = await client.call_tool('search_products', {'query': 'camera', 'include_offers': True})
        self.assertFalse(response.is_error)
        products = response.structured_content['products']
        self.assertEqual(products[0]['offers_coverage'], 'embedded_page_only')
        self.assertIn('403', products[1]['enrichment_error'])
        self.assertIsNone(products[1]['marketplace_offers'])

    async def test_errors_are_structured_and_cache_is_bypassable(self):
        from mediamarkt_mcp.shop.cache import _entries
        from mediamarkt_mcp.shop.errors import RetailerError
        _entries.clear()
        result = {'retailer': 'mediamarkt', 'query': 'cached', 'products': [], 'count': 0,
                  'total_products': 0, 'page': 1, 'next_page': None,
                  'paging': {'current_page': 1, 'page_count': 0, 'max_page': 1}, 'source': 'search_page', 'coverage': 'search_page'}
        with patch('mediamarkt_mcp.server.Client') as factory:
            factory.return_value.search = AsyncMock(return_value=result)
            async with MCPClient(mcp) as client:
                first = await client.call_tool('search_products', {'query': 'cached'})
                second = await client.call_tool('search_products', {'query': 'cached'})
                third = await client.call_tool('search_products', {'query': 'cached', 'fresh': True})
                self.assertFalse(first.structured_content['cache']['hit'])
                self.assertTrue(second.structured_content['cache']['hit'])
                self.assertFalse(third.structured_content['cache']['hit'])
                self.assertIsNotNone(first.structured_content['observed_at'])
                self.assertEqual(factory.return_value.search.await_count, 2)
                factory.return_value.search = AsyncMock(side_effect=RetailerError('Search page returned HTTP 429.'))
                error = await client.call_tool('search_products', {'query': 'blocked', 'fresh': True})
                self.assertTrue(error.is_error)
                self.assertEqual(error.structured_content['error']['code'], 'rate_limited')

    async def test_all_live_tools_expose_fresh_and_error_codes(self):
        from mediamarkt_mcp.shop.errors import RetailerError
        async with MCPClient(mcp) as client:
            tools = await client.list_tools()
            for tool in tools.tools:
                if tool.name != 'list_storefronts':
                    self.assertIn('fresh', tool.input_schema['properties'])
            cases = [('HTTP 403', 'blocked'), ('HTTP 429', 'rate_limited'),
                     ('HTTP 503', 'upstream_error'), ('PersistedQueryNotFound', 'retailer_changed'),
                     ('request failed; check network and proxy settings', 'network_error')]
            with patch('mediamarkt_mcp.server.Client') as factory:
                for message, code in cases:
                    factory.return_value.search = AsyncMock(side_effect=RetailerError(message))
                    result = await client.call_tool('search_products', {'query': code, 'fresh': True})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content['error']['code'], code)

    async def test_malformed_product_url_returns_invalid_input(self):
        async with MCPClient(mcp) as client:
            for reference in ('https://www.mediamarkt.de:invalid/de/product/_item-123.html',
                              'https://example.com/de/product/_item-123.html', 'not-a-product'):
                with self.subTest(reference=reference):
                    result = await client.call_tool('get_product', {'reference': reference, 'fresh': True})
                    self.assertTrue(result.is_error)
                    self.assertEqual(result.structured_content['error']['code'], 'invalid_input')

    async def test_missing_enriched_product_has_error_code(self):
        result = {'retailer': 'mediamarkt', 'query': 'missing', 'products': [
            {'id': '1', 'title': 'First', 'brand': None, 'price': None, 'currency': 'EUR', 'url': None,
             'delivery': {'status': 'unknown', 'retailer_status': None, 'retailer_code': None, 'earliest': None}}],
            'count': 1, 'total_products': 1, 'page': 1, 'next_page': None,
            'paging': {'current_page': 1, 'page_count': 1, 'max_page': 1}, 'source': 'search_page', 'coverage': 'search_page'}
        with patch('mediamarkt_mcp.server.Client') as factory:
            factory.return_value.search = AsyncMock(return_value=result)
            factory.return_value.product = AsyncMock(return_value={'found': False, 'reason': 'product_url_not_found'})
            async with MCPClient(mcp) as client:
                response = await client.call_tool('search_products', {'query': 'missing', 'include_offers': True, 'fresh': True})
        self.assertFalse(response.is_error)
        self.assertEqual(response.structured_content['products'][0]['enrichment_error_code'], 'not_found')
