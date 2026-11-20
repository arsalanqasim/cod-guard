import hmac
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
import main
import service
import whatsapp_cloud as cloud
from records import insert_order, write


PREFIX = "/integrations/whatsapp"
ACCOUNT = {"waba_id": "1", "phone_number_id": "2", "template_id": "3", "token": "demo-cloud-access-token",
           "app_secret": "demo-cloud-app-secret", "verify_token": "demo-cloud-verify-token",
           "signing_key": "simulated-key-not-for-production-32"}
TEMPLATE = {"name": "confirm_cod", "status": "APPROVED", "category": "UTILITY", "language": "en_US", "components": [
    {"type": "BODY", "text": cloud.TEMPLATE_BODY}, {"type": "BUTTONS", "buttons": [
        {"type": "QUICK_REPLY", "text": "Confirm"}, {"type": "QUICK_REPLY", "text": "Cancel"}]}]}


class WhatsAppTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(folder) / "state.json"
        self.enterContext(patch.object(service, "STATE_PATH", self.path))
        self.enterContext(patch.dict(os.environ, COD_GUARD_WHATSAPP=json.dumps({"alpha": ACCOUNT}),
                                     COD_GUARD_OPERATORS=json.dumps({name: {"tenant_id": name,
                                         "key": f"whatsapp-demo-operator-key-{name}"} for name in ("alpha", "beta")})))
        self.client = self.enterContext(TestClient(main.app))
        self.alpha = {"Authorization": "Bearer whatsapp-demo-operator-key-alpha"}
        self.beta = {"Authorization": "Bearer whatsapp-demo-operator-key-beta"}
        with write(self.path) as db:
            for order_id, source in (("cod1", "WOOCOMMERCE"), ("cod2", "SHADOW"), ("daraz1", "DARAZ")):
                insert_order(db, "alpha", {"order_id": order_id, "customer_name": "Test", "product": "Parcels",
                                           "city": "Lahore", "phone": "03001234567", "data_source": source})

    def post(self, suffix, **kwargs):
        return self.client.post(f"{PREFIX}/orders/{suffix}", headers=self.alpha, **kwargs)

    def consent(self):
        return self.post("cod1/consent", json={"opted_in": True, "evidence_reference": "checkout-record-42"})

    def callback(self, *, messages=None, statuses=None, good=True, phone_id="2"):
        data = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages",
                 "value": {"metadata": {"phone_number_id": phone_id}, "messages": messages or [],
                           "statuses": statuses or []}}]}]}
        body = json.dumps(data).encode()
        signature = "sha256=" + hmac.digest(ACCOUNT["app_secret"].encode(), body, "sha256").hex()
        return self.client.post(f"{PREFIX}/alpha/webhook", content=body,
                                headers={"X-Hub-Signature-256": signature if good else "invalid"})

    def text_reply(self, message_id, text):
        return {"id": message_id, "from": "923001234567", "context": {"id": "wamid.demo"},
                "type": "text", "text": {"body": text}}

    def start_attempt(self, request):
        self.assertEqual(self.consent().status_code, 200)
        request.side_effect = [TEMPLATE, {"messages": [{"id": "wamid.demo"}]}]
        self.assertTrue(self.post("cod1/send").json()["sent"])

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_unclear_text_leaves_attempt_open_for_one_clear_follow_up(self, request):
        self.start_attempt(request)
        unclear = self.text_reply("wamid.unclear", "Yes, send the order without the blue shirt")
        for _ in range(2):
            self.assertEqual(self.callback(messages=[unclear]).status_code, 200)
        attempt_path = f"{PREFIX}/orders/cod1"
        self.assertIsNone(self.client.get(attempt_path, headers=self.alpha).json()["verification"]["replied_at"])
        self.assertEqual([msg["intent"] for msg in service.conversation("cod1", "alpha")], ["UNCLEAR"])
        self.assertTrue(self.client.get("/orders/cod1", headers=self.alpha).json()["needs_review"])

        follow_up = self.text_reply("wamid.confirm", "Yes")
        self.assertEqual(self.callback(messages=[follow_up, follow_up]).status_code, 200)
        detail = self.client.get("/orders/cod1", headers=self.alpha).json()
        self.assertEqual((detail["decision"], detail["needs_review"]), ("SHIP", False))
        self.assertEqual([msg["intent"] for msg in detail["messages"]], ["UNCLEAR", "CONFIRM"])
        self.assertIsNotNone(self.client.get(attempt_path, headers=self.alpha).json()["verification"]["replied_at"])

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_stop_closes_pending_clarification_even_after_new_consent(self, request):
        self.start_attempt(request)
        self.callback(messages=[self.text_reply("wamid.unclear", "Maybe")])
        self.callback(messages=[self.text_reply("wamid.stop", "STOP")])
        self.assertEqual(self.post("cod2/send").status_code, 409)
        self.assertEqual(self.consent().status_code, 200)
        self.callback(messages=[self.text_reply("wamid.confirm", "Yes")])
        self.assertEqual([msg["intent"] for msg in service.conversation("cod1", "alpha")], ["UNCLEAR"])

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_clarification_does_not_extend_original_reply_window(self, request):
        with patch.object(cloud, "time", return_value=1_000_000_000):
            self.start_attempt(request)
        with patch.object(cloud, "time", return_value=1_000_000_000 + cloud.REPLY_TTL - 1):
            self.callback(messages=[self.text_reply("wamid.unclear", "Maybe")])
        with patch.object(cloud, "time", return_value=1_000_000_000 + cloud.REPLY_TTL):
            self.callback(messages=[self.text_reply("wamid.confirm", "Yes")])
        self.assertEqual([msg["intent"] for msg in service.conversation("cod1", "alpha")], ["UNCLEAR"])

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_send_requires_consent_exact_utility_copy_and_non_daraz_order(self, request):
        self.assertEqual(self.post("cod1/send").status_code, 409)
        self.assertEqual(self.post("daraz1/send").status_code, 409)
        request.assert_not_called()
        self.assertEqual(self.consent().status_code, 200)
        for template in ({**TEMPLATE, "category": "MARKETING"},
                         {**TEMPLATE, "components": [{"type": "BODY", "text": "Buy now!"}, TEMPLATE["components"][1]]}):
            request.return_value = template
            self.assertEqual(self.post("cod1/send").status_code, 502)
        request.side_effect = [TEMPLATE, {"messages": [{"id": "wamid.demo"}]}]
        self.assertTrue(self.post("cod1/send").json()["sent"])
        self.assertTrue(self.post("cod1/send").json()["already_submitted"])
        packet = request.call_args.kwargs["payload"]
        self.assertEqual(packet["to"], "923001234567")
        self.assertEqual(packet["template"]["components"][0]["parameters"][0]["text"], "cod1")
        self.assertEqual(self.client.get(f"{PREFIX}/orders/cod1", headers=self.beta).status_code, 404)
        self.assertEqual(self.client.get(f"{PREFIX}/status", headers=self.beta).json()["mode"], "simulated")

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_signed_reply_and_billing_are_scoped_and_replay_safe(self, request):
        self.consent()
        request.side_effect = [TEMPLATE, {"messages": [{"id": "wamid.demo"}]}]
        self.post("cod1/send")
        packet = request.call_args.kwargs["payload"]
        signed = packet["template"]["components"][1]["parameters"][0]["payload"]
        incoming = {"from": "923001234567", "context": {"id": "wamid.demo"}, "type": "button",
                    "button": {"payload": signed, "text": "Untrusted display label"}}
        self.assertEqual(self.callback(messages=[incoming], good=False).status_code, 401)
        self.callback(messages=[incoming], phone_id="998")
        self.callback(messages=[{**incoming, "from": "923001234568"}])
        self.callback(messages=[{**incoming, "button": {"payload": signed + "invalid"}}])
        self.assertEqual(service.conversation("cod1", "alpha"), [])
        self.assertEqual(self.callback(messages=[incoming]).status_code, 200)
        self.callback(messages=[incoming])
        reply, = service.conversation("cod1", "alpha")
        self.assertEqual(reply["intent"], "CONFIRM")
        delivery = {"id": "wamid.demo", "status": "delivered", "recipient_id": "923001234567",
                    "timestamp": str(int(datetime(2026, 11, 19, tzinfo=timezone.utc).timestamp())),
                    "pricing": {"billable": True, "category": "utility", "type": "regular"}}
        self.callback(statuses=[delivery, delivery, {**delivery, "status": "sent"}])
        stats = self.client.get(f"{PREFIX}/status", headers=self.alpha).json()
        self.assertEqual((stats["delivered"], stats["billable_deliveries"], stats["estimated_usd_micros"]), (1, 1, 15000))
        self.callback(messages=[{"from": "923001234567", "type": "text", "text": {"body": "STOP"}}])
        self.assertEqual(self.post("cod2/send").status_code, 409)

    @patch("whatsapp_cloud.CloudTransport.request")
    def test_ambiguous_send_does_not_retry_and_status_can_reconcile(self, request):
        self.consent()
        request.side_effect = [TEMPLATE, cloud.CloudError("simulated provider timeout")]
        self.assertEqual(self.post("cod1/send").status_code, 502)
        attempt = request.call_args.kwargs["payload"]["biz_opaque_callback_data"]
        self.assertEqual(self.post("cod1/send").json()["status"], "unconfirmed")
        self.assertEqual(request.call_count, 2)
        delivery = {"id": "wamid.reconciled", "status": "delivered", "recipient_id": "923001234567",
                    "biz_opaque_callback_data": attempt, "pricing": {"category": "utility", "billable": False}}
        self.callback(statuses=[delivery])
        result = self.client.get(f"{PREFIX}/orders/cod1", headers=self.alpha).json()["verification"]
        self.assertEqual((result["status"], result["billable"], result["estimated_usd_micros"]), ("delivered", 0, 0))

    def test_unconfigured_sends_are_simulated(self):
        with patch.dict(os.environ, COD_GUARD_WHATSAPP="{}"):
            result = self.post("cod1/send").json()
        self.assertEqual((result["mode"], result["sent"]), ("simulated", False))
        self.assertIn("cod1", result["preview"])
        self.assertIsNone(cloud._pricing({"pricing": {"type": "regular", "category": "utility"}, "timestamp": "0"})[2])
        self.assertIsNone(cloud._pricing({"pricing": {"type": "free_unknown", "category": "utility", "billable": False}})[0])
