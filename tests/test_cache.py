import os
import unittest
from unittest.mock import AsyncMock, patch

from mediamarkt_mcp.shop.cache import _entries, cached_call


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _entries.clear()

    async def test_hit_fresh_copy_and_expiration(self):
        fetch = AsyncMock(side_effect=[{'products': [{'id': '1'}]}, {'products': [{'id': '2'}]}, {'products': [{'id': '3'}]}])
        with patch('mediamarkt_mcp.shop.cache.time.monotonic', return_value=100):
            first = await cached_call('search', ('de', 'q'), False, fetch)
            first['products'][0]['id'] = 'changed'
            second = await cached_call('search', ('de', 'q'), False, fetch)
            self.assertEqual(second['products'][0]['id'], '1')
            self.assertTrue(second['cache']['hit'])
            self.assertEqual(first['observed_at'], second['observed_at'])
            refreshed = await cached_call('search', ('de', 'q'), True, fetch)
            self.assertFalse(refreshed['cache']['hit'])
            self.assertEqual(refreshed['products'][0]['id'], '2')
        with patch('mediamarkt_mcp.shop.cache.time.monotonic', return_value=131):
            expired = await cached_call('search', ('de', 'q'), False, fetch)
        self.assertEqual(expired['products'][0]['id'], '3')
        self.assertEqual(fetch.await_count, 3)

    async def test_missing_errors_and_proxy_settings_do_not_share_cache(self):
        fetch = AsyncMock(return_value={'found': False})
        await cached_call('product', ('id',), False, fetch)
        await cached_call('product', ('id',), False, fetch)
        self.assertEqual(fetch.await_count, 2)
        fetch = AsyncMock(side_effect=RuntimeError('network error'))
        for _ in range(2):
            with self.assertRaises(RuntimeError): await cached_call('stores', ('Berlin',), False, fetch)
        self.assertEqual(fetch.await_count, 2)
        fetch = AsyncMock(return_value={'products': []})
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:secret@one:80'}):
            await cached_call('pickup', ('216',), False, fetch)
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://user:secret@two:80'}):
            result = await cached_call('pickup', ('216',), False, fetch)
        self.assertFalse(result['cache']['hit'])
        self.assertEqual(fetch.await_count, 2)
        self.assertNotIn('secret', repr(list(_entries)))

    async def test_pickup_ttl_is_ten_seconds_and_keys_are_isolated(self):
        fetch = AsyncMock(return_value={'products': []})
        with patch('mediamarkt_mcp.shop.cache.time.monotonic', return_value=100):
            await cached_call('pickup', ('de', '216', ('1',)), False, fetch)
            await cached_call('pickup', ('de', '217', ('1',)), False, fetch)
        with patch('mediamarkt_mcp.shop.cache.time.monotonic', return_value=109):
            same = await cached_call('pickup', ('de', '216', ('1',)), False, fetch)
        self.assertTrue(same['cache']['hit'])
        self.assertEqual(same['cache']['age_seconds'], 9)
        with patch('mediamarkt_mcp.shop.cache.time.monotonic', return_value=110):
            expired = await cached_call('pickup', ('de', '216', ('1',)), False, fetch)
        self.assertFalse(expired['cache']['hit'])
        self.assertEqual(fetch.await_count, 3)
