"""Tests for webhook incident alerting."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import unittest

from api_sentinel.alerts import AlertDispatcher
from api_sentinel.models import HealthStatus


class MockAlertReceiver(BaseHTTPRequestHandler):
    received_payloads = []

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")
        try:
            parsed = json.loads(body)
            MockAlertReceiver.received_payloads.append(parsed)
        except Exception:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')


class TestAlerts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        MockAlertReceiver.received_payloads = []
        cls.server = HTTPServer(("127.0.0.1", 0), MockAlertReceiver)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_alert_dispatch(self):
        webhook_url = f"http://127.0.0.1:{self.port}/webhook"
        dispatcher = AlertDispatcher(webhook_urls=[webhook_url])

        results = dispatcher.dispatch_incident_event(
            event_type="incident.detected",
            target_id="checkout-api",
            target_name="Checkout API",
            url="https://api.example.com/checkout",
            status=HealthStatus.UNHEALTHY,
            details="HTTP 500 Server Error",
            timestamp="2026-11-03T10:00:00Z",
        )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        self.assertEqual(results[0]["status_code"], 200)

        self.assertEqual(len(MockAlertReceiver.received_payloads), 1)
        item = MockAlertReceiver.received_payloads[0]
        self.assertEqual(item["event"], "incident.detected")
        self.assertEqual(item["target_id"], "checkout-api")
        self.assertEqual(item["status"], "unhealthy")


if __name__ == "__main__":
    unittest.main()
