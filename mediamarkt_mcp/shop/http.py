"""Proxy configuration, request pacing, and persisted GraphQL calls."""
import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4
from curl_cffi.requests import AsyncSession
from .errors import RetailerError

HASHES = {
    "GetStoreSuggestions": "08958aeb8da650ae5fb0d96c98931d3dedbf306f590b83976b620abf03f61b50",
    "GetCofrPickupFeaturePickups": "81938af9c97c7bf5419b70d29819aba4cdee672fba4b020a5178dadd3b0cd979",
}

_lock = asyncio.Lock()
_last_request = 0.0

@asynccontextmanager
async def paced():
    global _last_request
    async with _lock:
        await asyncio.sleep(max(0, 2.5 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        yield

def request_error(context, exc):
    """Report proxy failures without exposing proxy URLs or credentials."""
    detail = str(exc).lower()
    if "connect tunnel failed" in detail or "proxy authentication" in detail or re.search(r"curl: \(\s*(5|97)\)", detail):
        return RetailerError(f"{context}: proxy connection or authentication failed; check proxy settings.", code="proxy_error")
    return RetailerError(f"{context} ({type(exc).__name__}); check network and proxy settings.", code="network_error")


def validate_proxy_environment():
    """Fail closed when an obsolete proxy setting would otherwise be ignored."""
    if os.environ.get("MMS_PROXY") or os.environ.get("MMS_PROXY_FILE"):
        raise RetailerError(
            "MMS_PROXY and MMS_PROXY_FILE are no longer supported; remove them and configure HTTPS_PROXY.",
            code="invalid_input",
        )


def _session(*, timeout):
    """Use libcurl's standard proxy environment variables and NO_PROXY rules."""
    validate_proxy_environment()
    return AsyncSession(impersonate="chrome", timeout=timeout)



async def gql(self, operation: str, variables: dict, cacheable: bool = True) -> dict:
    pwa = {"captureChannel": "DESKTOP", "salesLine": self.sales_line, "country": self.country.upper(), "language": self.language, "globalLoyaltyProgram": True, "isOneAccountProgramActive": True, "shouldInactiveContractsBeHidden": True, "isUsingXccCustomerComponent": True, "isCheckoutPhoneCompareActive": True}
    params = {"operationName": operation, "variables": json.dumps(variables, separators=(",", ":")), "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASHES[operation]}, "pwa": pwa}, separators=(",", ":"))}
    headers = {"accept": "*/*", "content-type": "application/json", "origin": self.base, "referer": self.base + "/", "x-operation": operation, "x-mms-salesline": self.sales_line, "x-mms-country": self.country.upper(), "x-mms-language": self.language, "x-cacheable": str(cacheable).lower(), "apollographql-client-name": "pwa-client-pqm"}
    async with _session(timeout=15) as session:
        async with paced():
            try:
                homepage = await session.get(self.base + "/")
            except Exception as exc:
                raise request_error(f"{self.sales_line} session initialization failed", exc) from exc
            if homepage.status_code != 200:
                raise RetailerError(f"{self.sales_line} session initialization returned HTTP {homepage.status_code}.")
            version = re.search(r'<meta\s+name=["\']version["\']\s+content=["\']([^"\']+)', homepage.text)
            if not version:
                raise RetailerError("Could not determine the current storefront version from the homepage.")
            headers["apollographql-client-version"] = version.group(1)
        for attempt in range(3):
            async with paced():
                try:
                    response = await session.get(f"{self.base}/api/v1/graphql", params=params, headers={**headers, "x-flow-id": str(uuid4())})
                except Exception as exc:
                    raise request_error(f"{self.sales_line} request failed", exc) from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                await asyncio.sleep(4 * (attempt + 1))
                continue
            if response.status_code == 403 and response.headers.get("cf-mitigated") == "challenge":
                raise RetailerError(f"{self.sales_line} blocked the request with a Cloudflare challenge (HTTP 403). The API is not accessible from this connection.")
            if response.status_code != 200:
                raise RetailerError(f"{self.sales_line} {operation} returned HTTP {response.status_code}; the retailer may be blocking or limiting requests.")
            try:
                body = response.json()
            except ValueError as exc:
                raise RetailerError("The retailer returned a non-JSON response.") from exc
            if not isinstance(body, dict):
                raise RetailerError("The retailer returned an unexpected response.")
            if body.get("errors"):
                raise RetailerError(f"{operation}: " + "; ".join(str(e.get("message", e)) for e in body["errors"]))
            if not isinstance(body.get("data"), dict):
                raise RetailerError(f"{operation} returned no data.")
            return body["data"]
    raise RetailerError("Request failed after retries.")

