import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mediamarkt_mcp.client import Client
from mediamarkt_mcp.shop.parsing import _marketplace_offers

FIXTURES = Path(__file__).parent / 'fixtures'


class FixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_sanitized_live_search_snapshots(self):
        for fixture, country, language, currency in [('search_de.json', 'de', 'de', 'EUR'), ('search_ch_fr.json', 'ch', 'fr', 'CHF')]:
            with self.subTest(fixture=fixture):
                text = (FIXTURES / fixture).read_text()
                client = Client('mediamarkt', country, language)
                session = AsyncMock()
                session.get.return_value = SimpleNamespace(status_code=200, url=f'{client.base}/{language}/search.html', text='window.__PRELOADED_STATE__ = ' + text)
                manager = AsyncMock(); manager.__aenter__.return_value = session
                with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
                    result = await client.search('Nintendo Switch')
                self.assertEqual(result['count'], 2)
                self.assertEqual(result['products'][0]['currency'], currency)
                self.assertIsNotNone(result['products'][0]['price'])
                self.assertEqual(result['country'], country)

    def test_sanitized_live_marketplace_offer_snapshot(self):
        state = json.loads((FIXTURES / 'product_de_offers.json').read_text())
        offers = _marketplace_offers(state, 'Media', '3058718')
        self.assertTrue(offers)
        self.assertEqual(offers[0]['product_id'], '184658993')
        self.assertIsNotNone(offers[0]['offer_id'])
        self.assertIsNotNone(offers[0]['seller_name'])

    async def test_sanitized_live_redirect_and_404_snapshots(self):
        fixture = json.loads((FIXTURES / 'redirect_saturn.json').read_text())
        text = fixture['html'] + '<script>window.__PRELOADED_STATE__ = ' + json.dumps({'apolloState': fixture['apolloState']}) + '</script>'
        session = AsyncMock()
        session.get.return_value = SimpleNamespace(status_code=200, url=fixture['url'], text=text)
        manager = AsyncMock(); manager.__aenter__.return_value = session
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await Client('saturn').search('GTA 6', max_price=80)
        self.assertEqual(result['coverage'], 'partial_landing_page')
        self.assertEqual(result['count'], 2)
        self.assertTrue(all(p['price'] <= 80 for p in result['products']))
        missing = json.loads((FIXTURES / 'missing_product.json').read_text())
        session.get.return_value = SimpleNamespace(status_code=missing['status_code'])
        with patch('mediamarkt_mcp.shop.http.AsyncSession', return_value=manager), patch('mediamarkt_mcp.shop.http.asyncio.sleep', new_callable=AsyncMock):
            result = await Client().product(missing['url'])
        self.assertFalse(result['found'])
        self.assertEqual(result['reason'], 'product_url_not_found')
