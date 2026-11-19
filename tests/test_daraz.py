import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from backend.app.daraz import DarazClient, DarazError, INTAKE_MODE, POLL_INTERVAL_SECONDS, sign_request


class DarazTests(unittest.TestCase):
    def test_signature_sorts_and_excludes_signature(self):
        params = {"foo": "1", "sign": "ignored", "foo_bar": "3", "bar": "2", "foobar": "4"}
        self.assertEqual(sign_request("/test/api", params, "test-secret"),
                         "FE01B44E2D0F8A799FDC350C3EDDA02F3BFCE762E60DA58768964FF1CD949437")

    @patch("backend.app.daraz.build_opener")
    def test_all_routes_send_signed_https_get(self, build_opener):
        opener = build_opener.return_value
        client = DarazClient("demo-key", "demo-secret", "demo+token", clock=lambda: 1234.567)
        opener.open.side_effect = [io.BytesIO(json.dumps({"code": "0", "data": data}).encode())
                                   for data in ({"orders": []}, {"order_id": 42}, [])]
        self.assertEqual(client.get_orders(updated_after="2026-11-19T01:00:00Z",
                                           updated_before="2026-11-19T01:15:00Z", offset=50),
                         {"orders": []})
        self.assertEqual(client.get_order(42), {"order_id": 42})
        self.assertEqual(client.get_order_items(42), [])
        paths = ("/orders/get", "/order/get", "/order/items/get")
        for call, path in zip(opener.open.call_args_list, paths, strict=True):
            request = call.args[0]
            url = urlsplit(request.full_url)
            params = {key: values[0] for key, values in parse_qs(url.query).items()}
            self.assertEqual((url.scheme, url.netloc, url.path), ("https", "api.daraz.pk", "/rest" + path))
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(params["access_token"], "demo+token")
            self.assertEqual(params["timestamp"], "1234567")
            self.assertEqual(params["sign_method"], "sha256")
            self.assertNotIn("demo-secret", request.full_url)
            self.assertEqual(params["sign"], sign_request(path, params, "demo-secret"))
            if path == "/orders/get":
                self.assertEqual(params["offset"], "50")
                self.assertEqual(params["update_after"], "2026-11-19T01:00:00Z")
                self.assertEqual(params["update_before"], "2026-11-19T01:15:00Z")
            else:
                self.assertEqual(params["order_id"], "42")

    @patch("backend.app.daraz.build_opener")
    def test_errors_do_not_expose_upstream_payloads_or_tokens(self, build_opener):
        client = DarazClient("demo-key", "demo-secret", "demo-token")
        build_opener.return_value.open.side_effect = [
            HTTPError("https://api.daraz.pk/rest/order/get?access_token=demo-token", 302, "redirect", {}, None),
            io.BytesIO(b'{"code":"denied","message":"private buyer data"}'),
            io.BytesIO(b'invalid json'),
        ]
        for _ in range(3):
            with self.assertRaises(DarazError) as raised:
                client.get_order(42)
            self.assertNotIn("demo-token", str(raised.exception))
            self.assertNotIn("private buyer data", str(raised.exception))
            self.assertIsNone(raised.exception.__context__)

    def test_spike_does_not_enable_verification(self):
        self.assertEqual(INTAKE_MODE, "score-and-queue-only")
        self.assertTrue(600 <= POLL_INTERVAL_SECONDS <= 900)
