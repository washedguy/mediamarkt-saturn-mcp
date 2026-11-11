"""Stable error codes for storefront failures."""
import re


def classify(message):
    text = message.lower()
    if '429' in text:
        return 'rate_limited'
    if '403' in text or 'cloudflare challenge' in text:
        return 'blocked'
    if '407' in text or 'proxy authentication' in text:
        return 'proxy_error'
    if '404' in text or 'not a known outlet_id' in text:
        return 'not_found'
    if 'invalid mms_proxy' in text or 'unsupported language' in text or 'unsupported country' in text or 'must not' in text:
        return 'invalid_input'
    if 'not verified' in text or 'does not support' in text:
        return 'unsupported'
    if ('changed' in text or 'persistedquerynotfound' in text or 'could not parse' in text
            or 'did not contain' in text or 'non-json' in text or 'unexpected response' in text):
        return 'retailer_changed'
    if 'network and proxy settings' in text or 'timeout' in text:
        return 'network_error'
    if re.search(r'\bhttp 5\d\d\b', text):
        return 'upstream_error'
    return 'retailer_error'


class RetailerError(Exception):
    """A storefront failure with a stable, non-sensitive machine-readable code."""
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code or classify(message)
