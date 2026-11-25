"""End-to-end checks against an isolated PostgreSQL database when a test DSN is set."""
import base64
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from secrets import token_urlsafe
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/app"), str(ROOT)]
import main
import merchant_auth
import merchant_couriers
import merchant_connectors
import merchant_events
import merchant_shopify
import merchant_shopify_privacy
import merchant_verification
import merchant_woo
import integration_jobs
import platform_jobs
import service
from platform_data import tenant_connection
from scripts import platform_database
from scripts.platform_database import assign_owner, import_pilot, migrate


ORIGIN = "https://merchant.test"
CSV = "order_id,customer_name,product,phone,city\nshared,Private Buyer,Shirt,03001234567,Lahore\n"


@unittest.skipUnless(os.environ.get("COD_GUARD_TEST_ADMIN_DSN"), "Disposable PostgreSQL test server required")
class MerchantPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin = os.environ["COD_GUARD_TEST_ADMIN_DSN"]
        cls.database = "cg_test_" + uuid4().hex
        cls.runtime = cls.database + "_api"
        password = token_urlsafe(32)
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(cls.runtime), sql.Literal(password)))
            cls.addClassCleanup(cls.drop_role, admin)
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database)))
            cls.addClassCleanup(cls.drop_database, admin)
        cls.admin_dsn = make_conninfo(admin, dbname=cls.database)
        cls.runtime_dsn = make_conninfo(cls.admin_dsn, user=cls.runtime, password=password)
        with (psycopg.connect(cls.admin_dsn) as db,
              patch.multiple(platform_database, _VERSION=1, _INTEGRATION_SCHEMA=(), _INTEGRATION_TABLES=())):
            migrate(db, cls.runtime)
            db.execute("INSERT INTO cod_guard.merchant_accounts (id,name) VALUES ('upgrade-fixture','Existing merchant')")
        with psycopg.connect(cls.admin_dsn) as db:
            migrate(db, cls.runtime)
            migrate(db, cls.runtime)
            assert db.execute("SELECT version FROM cod_guard.schema_version").fetchone() == (3,)
            assert db.execute("SELECT name FROM cod_guard.merchant_accounts WHERE id='upgrade-fixture'").fetchone() == (
                "Existing merchant",)

    @classmethod
    def drop_database(cls, admin):
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(cls.database)))

    @classmethod
    def drop_role(cls, admin):
        with psycopg.connect(admin, autocommit=True) as db:
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.runtime)))

    def setUp(self):
        self.outbox = {}
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(service, "STATE_PATH", self.folder / "state.json"))
        self.enterContext(patch.object(merchant_auth, "_mail", side_effect=self.capture_email))
        keys = json.dumps({"active": "test", "keys": {"test": base64.b64encode(b"A" * 32).decode()}})
        self.enterContext(patch.dict(os.environ, COD_GUARD_DATABASE_URL=self.runtime_dsn, COD_GUARD_DATA_KEYS=keys,
                                     COD_GUARD_AUTH_KEY="a" * 43, COD_GUARD_PORTAL_ORIGINS=ORIGIN, COD_GUARD_REDIS_URL="",
                                     COD_GUARD_PUBLIC_API_BASE=ORIGIN, COD_GUARD_LIVE_BUYER_CONTACT="0",
                                     COD_GUARD_OPERATORS=json.dumps({
                                         "legacy": {"tenant_id": "demo", "key": "legacy-operator-does-not-work"}})))

    def capture_email(self, to, _subject, message):
        self.outbox[to] = message.strip().splitlines()[-1]

    def client(self):
        return self.enterContext(TestClient(main.app, base_url=ORIGIN, headers={"Origin": ORIGIN}))

    def signin(self, client, email, *, name=None, invitation=None):
        start = client.post("/auth/email/start", json={"email": email})
        self.assertEqual(start.status_code, 202, start.text)
        response = client.post("/auth/email/complete", json={"store_name": name,
                               "code": self.outbox[email], "invitation": invitation})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers.get("set-cookie", ""))
        self.assertIn("Secure", response.headers.get("set-cookie", ""))
        return response.json()["merchant"]["tenant_id"]

    def upload(self, client, contents=CSV):
        return client.post("/orders/import", files={"file": ("orders.csv", contents, "text/csv")},
                           headers={"Idempotency-Key": "same-request"})

    def machine_headers(self, client, scope):
        response = client.post("/merchant/api-keys", json={"name": "Synthetic device", "scope": scope})
        self.assertEqual(response.status_code, 201, response.text)
        return {"Authorization": "Bearer " + response.json()["key"]}, response.json()["id"]

    def integration_rows(self, tenant, kind):
        with tenant_connection(tenant) as db:
            return db.execute("""SELECT id,status FROM integration_jobs WHERE tenant_id=? AND kind=?
                ORDER BY created_at""", (tenant, kind)).fetchall()

    def run_job(self, tenant, id, kind, handler):
        integration_jobs.run(service.STATE_PATH, tenant, id, {kind: handler})

    def test_erp_replay_revocation_and_signed_delivery(self):
        owner, outsider = self.client(), self.client()
        tenant = self.signin(owner, "erp-shop@example.test", name="ERP Shop")
        self.signin(outsider, "unrelated-erp-shop@example.test", name="Unrelated")
        headers, key_id = self.machine_headers(owner, "orders:write")
        headers["Idempotency-Key"] = "purchase-17"
        with patch("public_https.verify_url"):
            setup = owner.post("/merchant/webhooks", json={"name": "ERP events", "url": "https://erp.example.test/api"})
        self.assertEqual(setup.status_code, 201, setup.text)
        secret = setup.json()["signing_secret"]
        self.assertNotIn(secret, owner.get("/merchant/connections").text)
        order = {"order_id": "WEB-17", "customer_name": "Private name", "product": "Kurta",
                 "phone": "03001234567", "city": "Lahore", "amount_pkr": 2500, "items_count": 2}
        created = owner.post("/v1/orders", headers=headers, json=order)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["external_order_id"], "WEB-17")
        order_id = created.json()["order_id"]
        self.assertEqual(owner.post("/v1/orders", headers=headers, json=order).json(), created.json())
        self.assertEqual(owner.post("/v1/orders", headers=headers, json=order | {"items_count": 3}).status_code, 409)
        self.assertEqual(outsider.get(f"/orders/{order_id}").status_code, 404)
        self.assertEqual(owner.post(f"/orders/{order_id}/verify", json={"text": "yes"}).status_code, 200)
        queued = self.integration_rows(tenant, "erp_webhook")
        self.assertEqual(len(queued), 2)
        with patch("public_https.request", return_value=(200, {}, b"")) as send:
            for job in queued:
                self.run_job(tenant, job["id"], "erp_webhook",
                             lambda tenant, data: merchant_events.deliver(service.STATE_PATH, tenant, data))
            self.assertEqual(send.call_count, 2)
            body = send.call_args.kwargs["body"]
            envelope = send.call_args.kwargs["headers"]
            msg = json.loads(body)
            self.assertEqual((msg["type"], msg["decision"], msg["revision"]), ("order.decision", "SHIP", 1))
            self.assertNotIn(b"Private name", body)
            self.assertNotIn(b"03001234567", body)
            self.assertEqual(envelope["X-COD-Guard-Signature"], "sha256=" + hmac.digest(
                secret.encode(), envelope["X-COD-Guard-Timestamp"].encode() + b"." + body, "sha256").hex())
        self.assertEqual({row["status"] for row in self.integration_rows(tenant, "erp_webhook")}, {"done"})
        self.assertEqual(outsider.delete(f"/merchant/api-keys/{key_id}").status_code, 404)
        self.assertEqual(owner.delete(f"/merchant/api-keys/{key_id}").status_code, 204)
        self.assertEqual(owner.post("/v1/orders", headers=headers, json=order).status_code, 401)

    def test_storefront_authorization_and_shopify_owned_holds(self):
        seller = self.client()
        tenant = self.signin(seller, "storefronts@example.test", name="Storefronts")
        with patch("public_https.verify_url"), patch("woocommerce.WooCommerceClient.request", return_value=([], None)):
            start = seller.post("/merchant/woocommerce/authorize", json={"url": "https://woo.example.test"})
            self.assertEqual(start.status_code, 200, start.text)
            query = parse_qs(urlsplit(start.json()["authorize_url"]).query)
            payload = {"user_id": query["user_id"][0], "consumer_key": "ck_" + "a" * 40,
                       "consumer_secret": "cs_" + "b" * 40, "key_permissions": "read_write"}
            callback = urlsplit(query["callback_url"][0]).path
            self.assertEqual(seller.post(callback, json=payload).status_code, 200)
            self.assertEqual(seller.post(callback, json=payload).status_code, 404)
        self.assertEqual(len(self.integration_rows(tenant, "woo_setup")), 1)
        self.assertNotIn(payload["consumer_secret"], seller.get("/merchant/connections").text)
        with patch("woocommerce.WooCommerceClient.request", return_value=([], None)) as registrar, \
                patch("woocommerce.poll_once") as poll:
            merchant_woo.sync(tenant, {"connector": payload["user_id"]}, setup=True)
            self.assertEqual(registrar.call_count, 3)
            poll.assert_called_once()

        shop = "merchant-dev.myshopify.com"
        app_secret = "dev-fixture-shopify-client-secret"
        with patch.dict(os.environ, COD_GUARD_SHOPIFY_CLIENT_ID="synthetic", COD_GUARD_SHOPIFY_CLIENT_SECRET=app_secret), \
                patch.object(merchant_shopify, "_token", return_value={"access_token": "synthetic",
                             "refresh_token": "synthetic", "expires_at": int(time.time()) + 3600}):
            prepare = seller.post("/merchant/shopify/authorize", json={"shop": shop, "protected_fields": True})
            self.assertEqual(prepare.status_code, 200, prepare.text)
            params = {"shop": shop, "code": "synthetic", "state": prepare.json()["installation_code"],
                      "timestamp": int(time.time())}
            params["hmac"] = hmac.digest(app_secret.encode(), urlencode(sorted(params.items())).encode(), "sha256").hex()
            self.assertEqual(seller.get("/providers/shopify/oauth", params=params, follow_redirects=False).status_code, 303)
            self.assertEqual(seller.get("/providers/shopify/oauth", params=params, follow_redirects=False).status_code, 401)
            order = {"id": 4102, "test": False, "currency": "PKR", "financial_status": "pending",
                     "payment_gateway_names": ["Cash on Delivery (COD)"], "total_price": "2500",
                     "shipping_address": {"name": "Synthetic buyer", "phone": "03001234567"},
                     "line_items": [{"title": "Shirt", "quantity": 1}]}
            body = json.dumps(order).encode()
            signed = {"X-Shopify-Shop-Domain": shop, "X-Shopify-Topic": "orders/create",
                      "X-Shopify-Hmac-Sha256": base64.b64encode(hmac.digest(app_secret.encode(), body, "sha256")).decode()}
            with tenant_connection(tenant) as db:
                callback = merchant_connectors.read(db, tenant, shop, "shopify")["credentials"]["callback_token"]
            self.assertEqual(seller.post(f"/providers/shopify/webhooks/{shop}/wrong", headers=signed,
                                        content=body).status_code, 401)
            imported = seller.post(f"/providers/shopify/webhooks/{shop}/{callback}", headers=signed, content=body)
            self.assertEqual(imported.json(), {"imported": 1})
        self.assertEqual(seller.put(f"/merchant/shopify/{shop}/holds", json={"enforce": True}).status_code, 200)
        order_id = seller.get("/orders?search=4102").json()[0]["order_id"]
        self.assertEqual(seller.post(f"/orders/{order_id}/verify", json={"text": "yes"}).status_code, 200)
        payload = {"connector": shop, "order_id": order_id, "external_id": "4102", "kind": "decision"}
        fulfillment = {"id": "FO1", "status": "ON_HOLD", "supportedActions": [{"action": "RELEASE_HOLD"}],
                       "fulfillmentHolds": [{"id": "other", "handle": "other", "heldByRequestingApp": False},
                                            {"id": "owned", "handle": "cod-guard", "heldByRequestingApp": True}]}
        lookup = {"order": {"cancelledAt": None, "closedAt": None, "displayFinancialStatus": "PENDING",
                           "fulfillmentOrders": {"pageInfo": {"hasNextPage": False}, "nodes": [fulfillment]}}}
        with patch.object(merchant_shopify, "_graphql", side_effect=[
                    lookup, {"fulfillmentOrderReleaseHold": {"userErrors": []}}]) as graph:
            merchant_shopify.writeback(tenant, payload)
            self.assertEqual(graph.call_args.args[-1]["holds"], ["owned"])
        with patch.dict(os.environ, COD_GUARD_SHOPIFY_CLIENT_ID="synthetic", COD_GUARD_SHOPIFY_CLIENT_SECRET=app_secret):
            fake_shop = {"shop_id": 99, "shop_domain": shop, "customer": {"id": 12}}
            def privacy_webhook(topic, body):
                raw = json.dumps(body).encode()
                signature = base64.b64encode(hmac.digest(app_secret.encode(), raw, "sha256")).decode()
                return seller.post("/providers/shopify/privacy", content=raw, headers={
                    "X-Shopify-Topic": topic, "X-Shopify-Shop-Domain": shop, "X-Shopify-Hmac-Sha256": signature,
                })
            request = fake_shop | {"orders_requested": [4102], "data_request": {"id": 7}}
            self.assertEqual(privacy_webhook("customers/data_request", request).status_code, 200)
            entry, = seller.get("/merchant/shopify/privacy").json()
            export = seller.get(f"/merchant/shopify/privacy/{entry['id']}/export")
            self.assertEqual(export.json()["orders"][0]["phone"], "03001234567")
            self.assertEqual(seller.post(f"/merchant/shopify/privacy/{entry['id']}/complete").status_code, 200)
            redaction = fake_shop | {"orders_to_redact": [4102]}
            for _ in range(2):
                self.assertEqual(privacy_webhook("customers/redact", redaction).status_code, 200)
            job, = self.integration_rows(tenant, "shopify_privacy")
            self.run_job(tenant, job["id"], "shopify_privacy", merchant_shopify_privacy.process)
            self.assertEqual(seller.get(f"/orders/{order_id}").json()["customer_name"], "Redacted")
            self.assertEqual(seller.post(f"/providers/shopify/webhooks/{shop}/{callback}", headers=signed,
                                         content=body).json(), {"imported": 0})
            with tenant_connection(tenant, writable=True) as db:
                db.execute("UPDATE merchant_connectors SET active=false WHERE tenant_id=? AND id=?", (tenant, shop))
            self.assertEqual(privacy_webhook("shop/redact", {"shop_id": 99, "shop_domain": shop}).status_code, 200)
            job = self.integration_rows(tenant, "shopify_privacy")[-1]
            self.run_job(tenant, job["id"], "shopify_privacy", merchant_shopify_privacy.process)
            self.assertEqual(seller.get(f"/orders/{order_id}").status_code, 404)

    def test_verification_and_courier_events_gate_model_input(self):
        owner = self.client()
        tenant = self.signin(owner, "verification-shop@example.test", name="Verify")
        contents = CSV.replace("phone,city", "phone,city,amount_pkr,items_count").replace("Lahore\n", "Lahore,2500,2\n")
        self.assertEqual(self.upload(owner, contents).status_code, 201)
        route = "/merchant/orders/shared"
        sender = {"waba_id": "60", "phone_number_id": "61", "template_id": "62",
                  "token": "synthetic-token-for-whatsapp", "app_secret": "synthetic-app-secret", "business_verified": True}
        result = owner.post("/merchant/channels/whatsapp", json=sender)
        self.assertEqual(result.status_code, 200, result.text)
        with patch.dict(os.environ, COD_GUARD_LIVE_BUYER_CONTACT="1"), \
                patch("whatsapp_cloud.CloudTransport.verify_template", return_value="synthetic_template"), \
                patch("whatsapp_cloud.CloudTransport.send", return_value="wamid.fixture") as transport:
            target = route + "/verification/whatsapp"
            self.assertEqual(owner.post(target).status_code, 409)
            self.assertEqual(owner.put(route + "/contact-consent/whatsapp", json={
                "opted_in": True, "evidence_reference": "buyer-opt-in-1"}).status_code, 200)
            attempt = owner.post(target)
            self.assertEqual(attempt.status_code, 202, attempt.text)
            self.assertEqual(owner.post(target).json(), attempt.json())
            job = self.integration_rows(tenant, "buyer_contact")[0]
            self.run_job(tenant, job["id"], "buyer_contact", merchant_verification.send)
            self.run_job(tenant, job["id"], "buyer_contact", merchant_verification.send)
            transport.assert_called_once()
        msg = {"from": "923001234567", "id": "reply-1", "type": "text",
               "context": {"id": "wamid.fixture"}, "text": {"body": "yes"}}
        notification = {"object": "whatsapp_business_account", "entry": [{"id": "60", "changes": [
            {"field": "messages", "value": {"metadata": {"phone_number_id": "61"}, "messages": [msg]}}]}]}
        body = json.dumps(notification).encode()
        headers = {"X-Hub-Signature-256": "sha256=" + hmac.digest(sender["app_secret"].encode(), body, "sha256").hex()}
        for _ in range(2):
            self.assertEqual(owner.post(f"/providers/whatsapp/{tenant}", headers=headers, content=body).status_code, 200)
        order = owner.get("/orders/shared").json()
        self.assertEqual((order["decision"], len(order["messages"])), ("SHIP", 1))
        linked = owner.put(route + "/shipment", json={"courier": "postex", "tracking": "CG12345", "order_day": "2025-11-01"})
        self.assertEqual(linked.status_code, 200, linked.text)
        courier_headers, _ = self.machine_headers(owner, "courier:write")
        event = {"courier": "postex", "tracking": "CG12345", "event_id": "settled-123", "outcome": "refused"}
        accepted = owner.post("/v1/courier-events", headers=courier_headers, json=event)
        self.assertEqual(accepted.status_code, 202, accepted.text)
        self.assertEqual(owner.post("/v1/courier-events", headers=courier_headers, json=event).json(), accepted.json())
        self.assertEqual(owner.post("/v1/courier-events", headers=courier_headers,
                                    json=event | {"outcome": "returned"}).status_code, 409)
        self.run_job(tenant, accepted.json()["job_id"], "courier_terminal", merchant_couriers.apply_terminal)
        self.assertEqual(owner.get("/orders/shared").json()["outcome"], "refused")
        dataset = "/merchant/learning/dataset"
        self.assertEqual(len(owner.get(dataset).text.splitlines()), 1)
        confirmed = owner.put(route + "/refusal-evidence", json={"confirmed": True, "reference": "case-17"})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        rows = owner.get(dataset).text.splitlines()
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[-1].endswith(",1"))
        self.assertNotIn("03001234567", rows[-1])
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts import train_seller_risk

        def read_training_input(selected_tenant, dataset, output, **options):
            self.assertEqual(selected_tenant, tenant)
            self.assertEqual(dataset.read_text().splitlines(), rows)
            return {"mode": "shadow", "rows": 1}

        with (patch.object(sys, "argv", ["train_seller_risk.py", "--tenant", tenant, "--from-merchant-database",
                                         "--output", str(self.folder / "fixture.pkl")]),
              patch.object(train_seller_risk, "train_seller", side_effect=read_training_input) as train,
              redirect_stdout(StringIO())):
            train_seller_risk.main()
        train.assert_called_once()

    def test_urdu_call_callback_uses_signature_and_current_consent(self):
        owner = self.client()
        tenant = self.signin(owner, "calls-shop@example.test", name="Calls")
        self.assertEqual(self.upload(owner).status_code, 201)
        sid, token, call_sid = "AC" + "a" * 32, "synthetic-twilio-token", "CA" + "b" * 32
        with patch("public_https.verify_url"):
            setup = owner.post("/merchant/channels/calls", json={"account_sid": sid, "auth_token": token,
                               "from_number": "+12025550123", "prompt_url": "https://audio.example.test/urdu.ogg"})
        self.assertEqual(setup.status_code, 200, setup.text)
        route = "/merchant/orders/shared"
        self.assertEqual(owner.put(route + "/contact-consent/calls", json={
            "opted_in": True, "evidence_reference": "call-consent-1"}).status_code, 200)
        with patch.dict(os.environ, COD_GUARD_LIVE_BUYER_CONTACT="1"), \
                patch.object(merchant_verification, "_call", return_value=call_sid) as dial:
            attempt = owner.post(route + "/verification/calls")
            self.assertEqual(attempt.status_code, 202, attempt.text)
            job = self.integration_rows(tenant, "buyer_contact")[0]
            self.run_job(tenant, job["id"], "buyer_contact", merchant_verification.send)
            dial.assert_called_once()
        path = f"/providers/calls/{tenant}/{attempt.json()['id']}/answer"
        fields = {"AccountSid": sid, "CallSid": call_sid, "To": "+923001234567", "Digits": "2"}
        self.assertEqual(owner.post(path, data=fields).status_code, 401)
        signed = ORIGIN + path + "".join(key + fields[key] for key in sorted(fields))
        signature = base64.b64encode(hmac.digest(token.encode(), signed.encode(), "sha1")).decode()
        headers = {"X-Twilio-Signature": signature}
        for _ in range(2):
            self.assertEqual(owner.post(path, data=fields, headers=headers).status_code, 200)
        order = owner.get("/orders/shared").json()
        self.assertEqual((order["decision"], len(order["messages"])), ("HOLD_CANCEL", 1))

    def test_shopify_embedded_pairing_binds_the_shop_and_user(self):
        owner = self.client()
        self.signin(owner, "app-home@example.test", name="App Home")
        shop, app_secret, client_id = "embed-dev.myshopify.com", "embedded-fixture-shopify-secret", "fixture_app"
        with patch.dict(os.environ, COD_GUARD_SHOPIFY_CLIENT_ID=client_id,
                        COD_GUARD_SHOPIFY_CLIENT_SECRET=app_secret), \
                patch.object(merchant_shopify, "_token", return_value={"access_token": "synthetic",
                             "refresh_token": "synthetic", "expires_at": int(time.time()) + 3600}) as exchange:
            prepare = owner.post("/merchant/shopify/authorize", json={"shop": shop})
            self.assertEqual(prepare.status_code, 200, prepare.text)
            code = prepare.json()["installation_code"]
            def token(subject):
                def encode(value):
                    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
                signed = encode({"alg": "HS256"}) + "." + encode({
                    "iss": f"https://{shop}/admin", "dest": f"https://{shop}", "aud": client_id, "sub": subject,
                    "nbf": int(time.time()) - 1, "exp": int(time.time()) + 60,
                })
                signature = base64.urlsafe_b64encode(hmac.digest(app_secret.encode(), signed.encode(), "sha256"))
                return {"Authorization": "Bearer " + signed + "." + signature.decode().rstrip("=")}
            self.assertEqual(owner.get("/providers/shopify/embedded/orders", headers=token("123")).status_code, 403)
            paired = owner.post("/providers/shopify/embedded/link", headers=token("123"), json={"code": code})
            self.assertEqual(paired.status_code, 200, paired.text)
            self.assertEqual(exchange.call_args.args[1]["requested_token_type"],
                             "urn:shopify:params:oauth:token-type:offline-access-token")
            self.assertEqual(owner.get("/providers/shopify/embedded/orders", headers=token("123")).json(), [])
            self.assertEqual(owner.get("/providers/shopify/embedded/orders", headers=token("42")).status_code, 403)

    def test_database_sessions_order_isolation_roles_and_encryption(self):
        alpha, beta, packer, anonymous = (self.client() for _ in range(4))
        self.assertEqual(anonymous.get("/orders", headers={
            "Authorization": "Bearer legacy-operator-does-not-work"}).status_code, 401)
        aid = self.signin(alpha, "alpha@example.test", name="Alpha")
        bid = self.signin(beta, "beta@example.test", name="Beta")
        self.assertNotEqual(aid, bid)
        self.assertEqual(alpha.post("/auth/session/tenant", json={"tenant_id": bid}).status_code, 404)
        self.assertEqual(self.upload(alpha).json()["imported"], 1)
        self.assertEqual(beta.get("/orders/shared").status_code, 404)
        self.assertEqual(self.upload(beta, CSV.replace("Shirt", "Shoes")).json()["imported"], 1)
        self.assertEqual(beta.get("/orders/shared").json()["product"], "Shoes")
        self.assertEqual(alpha.post("/orders/shared/verify", json={"text": "yes"},
                                    headers={"Origin": "https://elsewhere.test"}).status_code, 403)
        verified = alpha.post("/orders/shared/verify", json={"text": "yes"})
        self.assertEqual(verified.json()["decision"], "SHIP")
        self.assertEqual(alpha.get("/orders/shared").json()["messages"][0]["text"], "yes")
        self.assertEqual(beta.get("/orders/shared").json()["messages"], [])
        with tenant_connection(aid) as db:
            rows = db.execute("SELECT tenant_id, customer_name, phone, city FROM orders").fetchall()
            self.assertEqual([row["tenant_id"] for row in rows], [aid])
            self.assertNotIn("Private Buyer", rows[0]["customer_name"])
            self.assertNotIn("03001234567", rows[0]["phone"])
            self.assertNotIn("Lahore", rows[0]["city"])
            self.assertNotEqual(db.execute("SELECT text FROM messages").fetchone()[0], "yes")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), tenant_connection(aid, writable=True) as db:
            db.execute("INSERT INTO audit_events (tenant_id, actor, action, at) VALUES (?, ?, ?, ?)",
                       (bid, "x", "y", "z"))

        from connector_orders import CANCELLED, OPEN, StorefrontSnapshot, ingest

        store = (aid, "SHOPIFY", "sample-shop")
        details = {"customer_name": "Store Buyer", "phone": "03001234567", "product": "Shirt", "city": "Lahore"}
        ingest(service.STATE_PATH, store, [StorefrontSnapshot("4102", OPEN, "2026-11-25T09:00:00", details)], "test")
        imported = alpha.get("/orders?search=4102").json()[0]
        storefront_path = f"/orders/{imported['order_id']}"
        self.assertEqual(imported["source_order_id"], "4102")
        self.assertEqual(alpha.post(f"{storefront_path}/verify", json={"text": "yes"}).status_code, 200)
        ingest(service.STATE_PATH, store, [StorefrontSnapshot("4102", CANCELLED, "2026-11-25T10:00:00")], "test")
        for view in ("queue", "conflicts", "closed"):
            filtered = alpha.get(f"/orders?view={view}").json()
            self.assertTrue(filtered[0]["storefront_conflict"], filtered)
            self.assertEqual(filtered[0]["source_order_id"], "4102")

        invitation = alpha.post("/auth/invitations", json={"email": "packer@example.test", "role": "packer"})
        self.assertEqual(invitation.status_code, 202, invitation.text)
        code = self.outbox["packer@example.test"]
        self.assertEqual(self.signin(packer, "packer@example.test", invitation=code), aid)
        packed = packer.get("/orders")
        self.assertEqual(packed.status_code, 200, packed.text)
        self.assertEqual(packed.headers["X-Total-Count"], "1")
        self.assertEqual(packed.json(), [packer.get("/orders/shared").json()])
        self.assertNotIn("customer_name", packed.json()[0])
        self.assertEqual(packer.get("/orders/shared?reveal_phone=true").status_code, 403)
        self.assertEqual(packer.post("/orders/shared/verify", json={"text": "no"}).status_code, 403)
        self.assertEqual(packer.post("/auth/invitations",
                         json={"email": "other@example.test", "role": "ops"}).status_code, 403)
        self.assertEqual(alpha.post("/orders/shared/outcome", json={"outcome": "delivered"}).status_code, 200)
        self.assertEqual(packer.get("/orders").json(), [])
        self.assertEqual(packer.get("/orders/shared").status_code, 404)
        old = alpha.cookies.get(merchant_auth.SESSION)
        self.assertEqual(alpha.delete("/auth/session").status_code, 204)
        anonymous.cookies.set(merchant_auth.SESSION, old)
        self.assertEqual(anonymous.get("/orders").status_code, 401)

    def test_pilot_backup_import_and_verified_owner(self):
        from order_intake import import_orders

        legacy = self.folder / "pilot.json"
        with patch.dict(os.environ, COD_GUARD_DATABASE_URL=""):
            import_orders(legacy, "migrated-shop", "old-operator", "historical-key", CSV.encode())
            with patch.object(service, "STATE_PATH", legacy):
                order = service.get_order("shared", "migrated-shop")
                service.verify_reply(order, "yes", tenant_id="migrated-shop", actor="old-operator")
                service.mark_outcome("shared", "delivered", tenant_id="migrated-shop", actor="old-operator")
        with psycopg.connect(self.admin_dsn) as db:
            # Each test owns its records. Restore-independent cleanup happens in a fresh schema for this case.
            db.execute("DROP SCHEMA cod_guard CASCADE")
            migrate(db, self.runtime)
            counts = import_pilot(db, legacy.with_suffix(".sqlite3"))
            assign_owner(db, "migrated-shop", "migrated@example.test")
        self.assertEqual((counts["orders"], counts["decisions"], counts["outcomes"], counts["messages"]),
                         (1, 1, 1, 1))
        merchant = self.client()
        self.assertEqual(self.signin(merchant, "migrated@example.test"), "migrated-shop")
        detail = merchant.get("/orders/shared")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual((detail.json()["decision"], detail.json()["outcome"]), ("SHIP", "delivered"))
        self.assertEqual(detail.json()["messages"][0]["text"], "yes")
        with psycopg.connect(self.admin_dsn) as db, self.assertRaises(ValueError):
            import_pilot(db, legacy.with_suffix(".sqlite3"))

    def test_voice_job_recovers_after_lost_delivery_and_worker_crash(self):
        owner, outsider = self.client(), self.client()
        tenant = self.signin(owner, "voice-shop@example.test", name="Voice")
        self.signin(outsider, "other-shop@example.test", name="Other")
        self.assertEqual(self.upload(owner).status_code, 201)
        with patch.dict(os.environ, COD_GUARD_REDIS_URL="redis://127.0.0.1:1"), \
                patch.object(merchant_auth, "_redis") as redis_client:
            redis_client.return_value.eval.return_value = (1, 59)
            queued = owner.post("/orders/shared/voice", files={"file": ("reply.ogg", b"example", "audio/ogg")})
            self.assertGreater(redis_client.return_value.eval.call_count, 0)
        self.assertEqual(queued.status_code, 202, queued.text)
        job = queued.json()["job_id"]
        path = f"/orders/shared/voice/{job}"
        self.assertEqual(outsider.get(path).status_code, 404)
        self.assertEqual(owner.get(path).json()["status"], "queued")
        self.assertEqual(self.relayed_jobs(), [(tenant, job)])
        self.assertEqual(self.relayed_jobs(), [])
        with tenant_connection(tenant, writable=True) as db:
            self.assertNotIn("example", db.execute("SELECT audio FROM merchant_voice_jobs WHERE id=?", (job,)).fetchone()[0])
            db.execute("UPDATE merchant_voice_jobs SET relay_at=now() WHERE id=?", (job,))
        self.assertEqual(self.relayed_jobs(), [(tenant, job)])
        with patch.object(platform_jobs, "transcribe_voice_note", side_effect=RuntimeError("worker terminated")):
            with self.assertRaisesRegex(RuntimeError, "worker terminated"):
                platform_jobs.run_voice(service.STATE_PATH, tenant, job)
        self.assertEqual(owner.get(path).json()["status"], "running")
        with tenant_connection(tenant, writable=True) as db:
            db.execute("UPDATE merchant_voice_jobs SET lease_until=now(), relay_at=now() WHERE id=?", (job,))
        self.assertEqual(self.relayed_jobs(), [(tenant, job)])
        transcript = {"ok": True, "text": "yes"}
        with patch.object(platform_jobs, "transcribe_voice_note", return_value=transcript) as transcribe:
            platform_jobs.run_voice(service.STATE_PATH, tenant, job)
            platform_jobs.run_voice(service.STATE_PATH, tenant, job)
            transcribe.assert_called_once_with(b"example", suffix=".ogg")
        result = owner.get(path)
        self.assertEqual(result.json()["result"]["text"], "yes")
        self.assertTrue(result.json()["result"]["needs_review"])
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        self.assertEqual(owner.get("/orders/shared").json()["messages"], [])
        with tenant_connection(tenant) as db:
            row = db.execute("SELECT audio, result, attempts FROM merchant_voice_jobs WHERE id=?", (job,)).fetchone()
            self.assertIsNone(row["audio"])
            self.assertNotIn('"text": "yes"', row["result"])
            self.assertEqual(row["attempts"], 2)

    def relayed_jobs(self):
        deliveries = []
        platform_jobs.relay(service.STATE_PATH, lambda tenant, job: deliveries.append((tenant, job)))
        return deliveries

    @unittest.skipUnless(os.environ.get("COD_GUARD_TEST_REDIS_URL"), "Redis broker required")
    def test_voice_job_crosses_redis_and_runs_in_celery_worker(self):
        from celery.contrib.testing.worker import start_worker

        owner = self.client()
        self.signin(owner, "broker-shop@example.test", name="Broker")
        self.assertEqual(self.upload(owner).status_code, 201)
        with patch.dict(os.environ, COD_GUARD_REDIS_URL=os.environ["COD_GUARD_TEST_REDIS_URL"]), \
                patch.object(platform_jobs, "transcribe_voice_note", return_value={"ok": True, "text": "yes"}):
            from backend.app import worker

            with start_worker(worker.app, perform_ping_check=False, queues=["voice"]):
                started = owner.post("/orders/shared/voice", files={"file": ("reply.ogg", b"audio", "audio/ogg")})
                self.assertEqual(started.status_code, 202, started.text)
                job = started.json()["job_id"]
                worker.relay.run()
                status_url = f"/orders/shared/voice/{job}"
                for _ in range(40):
                    status = owner.get(status_url).json()
                    if status["status"] == "done":
                        break
                    time.sleep(0.1)
        self.assertEqual(status["status"], "done", status)
        self.assertEqual(status["result"]["intent"], "CONFIRM")
