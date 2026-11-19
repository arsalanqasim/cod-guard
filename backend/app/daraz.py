"""Read-only Daraz Pakistan client for the feasibility spike."""

import hmac
import json
from time import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_ROOT = "https://api.daraz.pk/rest"
POLL_INTERVAL_SECONDS = 15 * 60
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
INTAKE_MODE = "score-and-queue-only"


class DarazError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def sign_request(path, params, secret):
    canonical = path + "".join(
        key + params[key] for key in sorted(params) if key != "sign" and params[key]
    )
    return hmac.digest(secret.encode(), canonical.encode(), "sha256").hex().upper()


class DarazClient:
    def __init__(self, app_key, app_secret, access_token, *, clock=time):
        if not all((app_key, app_secret, access_token)):
            raise ValueError("Daraz app key, app secret and seller access token are required")
        self._app_key = app_key
        self._app_secret = app_secret
        self._access_token = access_token
        self._clock = clock
        self._opener = build_opener(_NoRedirect())

    def get_orders(self, *, updated_after, updated_before, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0 or not updated_after or not updated_before:
            raise ValueError("Invalid Daraz polling window or page bounds")
        return self._get("/orders/get", update_after=updated_after,
                         update_before=updated_before, limit=str(limit), offset=str(offset))

    def get_order(self, order_id):
        return self._get("/order/get", order_id=str(order_id))

    def get_order_items(self, order_id):
        return self._get("/order/items/get", order_id=str(order_id))

    def _get(self, path, **business):
        params = dict(business, app_key=self._app_key, access_token=self._access_token,
                      timestamp=str(int(self._clock() * 1000)), sign_method="sha256")
        params["sign"] = sign_request(path, params, self._app_secret)
        request = Request(f"{API_ROOT}{path}?{urlencode(params)}",
                          headers={"Accept": "application/json"})
        error = None
        try:
            with self._opener.open(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            error = f"Daraz rejected {path} (HTTP {exc.code})"
        except (URLError, OSError):
            error = f"Daraz request failed for {path}"
        if error:
            raise DarazError(error)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DarazError(f"Daraz response exceeded the size limit for {path}")
        try:
            envelope = json.loads(raw)
        except (ValueError, RecursionError):
            envelope = None
        if not isinstance(envelope, dict) or envelope.get("code") not in ("0", 0):
            raise DarazError(f"Daraz did not return a success envelope for {path}")
        if not isinstance(envelope.get("data"), (dict, list)):
            raise DarazError(f"Daraz did not return order data for {path}")
        return envelope["data"]
