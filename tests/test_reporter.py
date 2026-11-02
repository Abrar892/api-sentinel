"""Tests for terminal, JSON, and HTML dashboard reporters."""

import json
import unittest

from api_sentinel.models import HealthStatus, ProbeResult
from api_sentinel.reporter import HtmlReporter, JsonReporter, TerminalReporter


class TestReporter(unittest.TestCase):
    def setUp(self):
        self.sample_results = [
            ProbeResult(
                target_id="healthy-svc",
                target_name="Healthy Service",
                url="https://api.example.com/ok",
                method="GET",
                status_code=200,
                latency_ms=45.2,
                timestamp="2026-11-02T12:00:00Z",
                status=HealthStatus.HEALTHY,
            ),
            ProbeResult(
                target_id="broken-svc",
                target_name="Broken Service",
                url="https://api.example.com/fail",
                method="POST",
                status_code=500,
                latency_ms=120.4,
                timestamp="2026-11-02T12:00:00Z",
                status=HealthStatus.UNHEALTHY,
                error="Internal Server Error",
            ),
        ]

    def test_terminal_reporter(self):
        output = TerminalReporter.render_probe_summary(self.sample_results)
        self.assertIn("API SENTINEL - SYNTHETIC HEALTH PROBE REPORT", output)
        self.assertIn("Healthy Service", output)
        self.assertIn("Broken Service", output)
        self.assertIn("Healthy: 1", output)
        self.assertIn("Unhealthy: 1", output)

    def test_json_reporter(self):
        json_str = JsonReporter.render(self.sample_results)
        parsed = json.loads(json_str)
        self.assertIn("summary", parsed)
        self.assertEqual(parsed["summary"]["total_targets"], 2)
        self.assertEqual(parsed["summary"]["healthy"], 1)
        self.assertEqual(parsed["summary"]["unhealthy"], 1)
        self.assertEqual(len(parsed["probes"]), 2)

    def test_html_reporter(self):
        html = HtmlReporter.render("Test Suite Dashboard", self.sample_results)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Test Suite Dashboard", html)
        self.assertIn("Healthy Service", html)
        self.assertIn("Broken Service", html)
        self.assertIn("Endpoint Latency Distribution", html)


if __name__ == "__main__":
    unittest.main()
