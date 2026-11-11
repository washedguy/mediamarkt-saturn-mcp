import unittest
from unittest.mock import AsyncMock, patch
from mediamarkt_mcp.client import Client, RetailerError

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_passes_filters_to_page(self):
        client = Client("saturn")
        client.search_page = AsyncMock(return_value={"products": []})
        await client.search("headphones", brand="Sony", min_price=10, max_price=100, delivery_only=True)
        self.assertEqual(client.search_page.call_args.args, ("headphones", 1, ["brand:Sony", "currentprice:10-100", "availabilityText:sofort lieferbar"]))

    async def test_pickup_missing_is_unknown_and_batches(self):
        client = Client()
        client.gql = AsyncMock(return_value={"cofrProductAggregates": [{"cofrPickupFeature": {"id": "Media:de:1:7", "displayStatus": "AVAILABLE"}}]})
        result = await client.pickup("7", [str(i) for i in range(1, 15)])
        self.assertEqual(client.gql.await_count, 2)
        self.assertEqual(result["products"][0]["status"], "available")
        self.assertEqual(result["products"][1]["status"], "unknown")


    async def test_graphql_uses_fresh_version_and_same_session(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        client = Client()
        homepage = SimpleNamespace(status_code=200, text='<meta name="version" content="8.999.1">')
        response = SimpleNamespace(status_code=200, headers={}, json=lambda: {"data": {"storeSuggestions": []}})
        session = AsyncMock()
        session.get.side_effect = [homepage, response]
        manager = AsyncMock()
        manager.__aenter__.return_value = session
        with patch("mediamarkt_mcp.shop.http.AsyncSession", return_value=manager), patch("mediamarkt_mcp.shop.http.asyncio.sleep", new_callable=AsyncMock):
            result = await client.stores("Berlin")
        self.assertEqual(result["stores"], [])
        self.assertEqual(session.get.await_count, 2)
        self.assertEqual(session.get.await_args.kwargs["headers"]["apollographql-client-version"], "8.999.1")

    async def test_product_url_404_and_host_validation(self):
        from types import SimpleNamespace
        client = Client()
        session = AsyncMock()
        session.get.return_value = SimpleNamespace(status_code=404)
        manager = AsyncMock()
        manager.__aenter__.return_value = session
        with patch("mediamarkt_mcp.shop.http.AsyncSession", return_value=manager), patch("mediamarkt_mcp.shop.http.asyncio.sleep", new_callable=AsyncMock):
            result = await client.product("https://www.mediamarkt.de/de/product/_unknown-123.html?utm_source=test")
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "product_url_not_found")
        self.assertEqual(session.get.await_args.args[0], "https://www.mediamarkt.de/de/product/_unknown-123.html")
        with self.assertRaises(RetailerError):
            await client.product("https://example.com/de/product/_unknown-123.html")

    async def test_product_page_extracts_requested_product(self):
        import json
        from types import SimpleNamespace
        client = Client()
        feature_id = 'Media:de:123'
        state = {
            'GraphqlProduct:Media:de-DE:123': {'id': '123', 'title': 'Camera', 'manufacturer': 'Example', 'ean': '0123', 'description': '<p>Good &amp; small</p>', 'url': '/de/product/_camera-123.html', 'featureGroupsWithProductId': {'__ref': 'groups'}, 'breadcrumbs': [{'name': 'Cameras'}]},
            'CofrPriceFeature:price': {'id': feature_id, 'currency': 'EUR', 'price': {'amount': 20}},
            'CofrDeliveryFeature:' + feature_id: {'delivery': {'displayStatus': 'AVAILABLE'}},
            'CofrCoreFeature:' + feature_id: {'reviewStatistics': {'averageOverallRating': 4.5, 'totalReviewCount': 8}},
            'CofrMediaAssetsFeature:' + feature_id: {'productImages': [{'link': 'https://example.com/image', 'altText': 'Camera'}]},
            'groups': {'featureGroups': [{'featureGroupName': 'Technical', 'features': [{'__ref': 'feature'}]}]},
            'feature': {'name': 'Color', 'value': 'Black', 'unit': None},
        }
        session = AsyncMock()
        session.get.return_value = SimpleNamespace(status_code=200, text='window.__PRELOADED_STATE__ = ' + json.dumps({'apolloState': state}))
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await client.product('https://www.mediamarkt.de/de/product/_camera-123.html')
        product = result['product']
        self.assertEqual(product['ean'], '0123')
        self.assertEqual(product['description'], 'Good & small')
        self.assertEqual(product['features'][0]['items'][0]['value'], 'Black')
        self.assertEqual(product['rating']['count'], 8)
        self.assertEqual(product['price'], 20)

    async def test_product_redirect_to_other_host_is_rejected(self):
        from types import SimpleNamespace
        session = AsyncMock()
        session.get.return_value = SimpleNamespace(status_code=302, headers={'location': 'https://example.com/de/product/_camera-123.html'})
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            with self.assertRaises(RetailerError):
                await Client().product('https://www.mediamarkt.de/de/product/_camera-123.html')
        self.assertEqual(session.get.await_count, 1)

    def test_redirected_page_extracts_only_visible_linked_products(self):
        from types import SimpleNamespace
        client = Client('saturn')
        state = {
            'CofrCoreFeature:Saturn:de:123': {'productName': 'Test console', 'manufacturerName': 'TEST'},
            'CofrPriceFeature:123': {'id': 'Saturn:de:123', 'currency': 'EUR', 'price': {'amount': 79.99}},
            'CofrDeliveryFeature:Saturn:de:123': {'delivery': {'displayStatus': 'AVAILABLE'}},
            'CofrCoreFeature:Saturn:de:999': {'productName': 'Hidden recommendation'},
        }
        response = SimpleNamespace(url='https://www.saturn.de/de/campaign/example?query=abc', text='<a href="/de/product/_test-123.html">Test</a><a href="/de/product/_test-123.html">Duplicate</a>')
        result = client._redirected_search(state, response, 'abc', 1, [])
        self.assertEqual(result['source'], 'redirected_page')
        self.assertEqual(result['redirected_url'], 'https://www.saturn.de/de/campaign/example')
        self.assertIsNone(result['total_products'])
        self.assertEqual([(p['id'], p['price']) for p in result['products']], [('123', 79.99)])
        self.assertIsNone(result['next_page'])
        filtered = client._redirected_search(state, response, 'abc', 1, ['brand:TEST', 'currentprice:10-100'])
        self.assertEqual(filtered['products'][0]['id'], '123')
        self.assertEqual(client._redirected_search(state, response, 'abc', 1, ['currentprice:1-10'])['count'], 0)
        with self.assertRaises(RetailerError):
            client._redirected_search(state, response, 'abc', 1, ['availabilityText:in stock'])
        with self.assertRaises(RetailerError):
            client._redirected_search(state, response, 'abc', 2, [])
        with self.assertRaises(RetailerError):
            client._redirected_search(state, SimpleNamespace(url='https://example.com/de/campaign/example', text=response.text), 'abc', 1, [])

    def test_linked_offers_and_variants_are_distinct_and_incomplete(self):
        import json
        from pathlib import Path
        from mediamarkt_mcp.shop.parsing import _marketplace_offers, _related_products
        state = json.loads((Path(__file__).parent / 'fixtures/product_relationships.json').read_text())
        offers = _marketplace_offers(state, 'Media', '100')
        self.assertEqual(len(offers), 1)
        self.assertEqual((offers[0]['product_id'], offers[0]['offer_id'], offers[0]['seller_name']), ('200', '900', 'Example seller'))
        self.assertEqual(offers[0]['shipping_cost'], 0)
        self.assertEqual(offers[0]['delivery']['status'], 'available')
        self.assertEqual(_marketplace_offers(state, 'Media', '200')[0]['offer_id'], '900')
        product = {'variants': [{'variantName': 'Color', 'variantProducts': [
            {'productId': '100'}, {'productId': '101', 'variantValue': 'Black', 'product': {'__ref': 'GraphqlProduct:Media:de-DE:101'}}]}]}
        variants = _related_products(state, product, '100')
        self.assertEqual([item['product_id'] for item in variants], ['101'])

    def test_unknown_availability_is_not_unavailable(self):
        from mediamarkt_mcp.shop.parsing import _delivery
        self.assertEqual(_delivery({'displayStatus': 'SOMETHING_NEW'})['status'], 'unknown')
        self.assertEqual(_delivery({'displayStatus': 'SOMETHING_NEW'})['retailer_status'], 'SOMETHING_NEW')

    async def test_redirect_to_another_product_keeps_original_id(self):
        import json
        from types import SimpleNamespace
        state = {'GraphqlProduct:Media:de-DE:123': {'id': '123', 'title': 'Marketplace item', 'url': '/de/product/_item-123.html'}}
        session = AsyncMock()
        session.get.side_effect = [SimpleNamespace(status_code=302, headers={'location': '/de/product/_canonical-456.html'}),
                                   SimpleNamespace(status_code=200, text='window.__PRELOADED_STATE__ = ' + json.dumps({'apolloState': state}))]
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await Client().product('123')
        self.assertTrue(result['found'])
        self.assertEqual(result['product']['id'], '123')
        self.assertTrue(result['product']['resolved_url'].endswith('-456.html'))

    def test_local_price_filter_accepts_scientific_notation(self):
        from types import SimpleNamespace
        client = Client()
        state = {'CofrCoreFeature:Media:de:123': {'productName': 'Test', 'manufacturerName': 'TEST'},
                 'CofrPriceFeature:123': {'id': 'Media:de:123', 'currency': 'EUR', 'price': {'amount': 79.99}}}
        response = SimpleNamespace(url='https://www.mediamarkt.de/de/campaign/example', text='<a href="/de/product/_test-123.html">Test</a>')
        result = client._redirected_search(state, response, 'test', 1, ['currentprice:1e-08-100'])
        self.assertEqual(result['count'], 1)
