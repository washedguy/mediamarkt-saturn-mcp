"""Small process-local cache for successful public storefront results."""
import copy
import hashlib
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone

from .http import validate_proxy_environment


TTL = {"search": 30, "product": 60, "stores": 300, "pickup": 10}
MAX_ENTRIES = 256
_entries = OrderedDict()


def _proxy_key():
    # Reject obsolete settings before either using cached data or opening a connection.
    validate_proxy_environment()
    # Separate connections without storing proxy credentials in cache keys or responses.
    names = ('https_proxy', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY')
    value = '\0'.join(os.environ.get(name, '') for name in names)
    return hashlib.sha256(value.encode()).digest()


async def cached_call(kind, key, fresh, fetch):
    cache_key = (kind, _proxy_key(), *key)
    now = time.monotonic()
    entry = _entries.get(cache_key)
    if not fresh and entry is not None and now - entry[0] < TTL[kind]:
        _entries.move_to_end(cache_key)
        result = copy.deepcopy(entry[1])
        result['cache'] = {'hit': True, 'age_seconds': round(now - entry[0], 3), 'ttl_seconds': TTL[kind]}
        return result
    result = await fetch()
    result = copy.deepcopy(result)
    result['observed_at'] = datetime.now(timezone.utc).isoformat()
    result['cache'] = {'hit': False, 'age_seconds': 0.0, 'ttl_seconds': TTL[kind]}
    # A missing product might be transient. Never cache failures or missing products.
    if result.get('found') is not False:
        _entries[cache_key] = (time.monotonic(), copy.deepcopy(result))
        _entries.move_to_end(cache_key)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)
    return result
