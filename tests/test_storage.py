"""Tests for SQLite persistence, percentiles, and incident tracking."""

import os
import tempfile
import unittest

from api_sentinel.models import AssertionResult, HealthStatus, ProbeResult
from api_sentinel.storage import SentinelStorage, calculate_percentile


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_sentinel.db")
        self.storage = SentinelStorage(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_percentile_calculation(self):
        data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        p50 = calculate_percentile(data, 50.0)
        p95 = calculate_percentile(data, 95.0)
        self.assertAlmostEqual(p50, 55.0, places=1)
        self.assertGreater(p95, 90.0)

    def test_save_and_retrieve_probe(self):
        result = ProbeResult(
            target_id="api-1",
            target_name="API One",
            url="https://example.com/api",
            method="GET",
            status_code=200,
            latency_ms=120.5,
            timestamp="2026-11-02T12:00:00Z",
            status=HealthStatus.HEALTHY,
            assertions=[
                AssertionResult(
                    rule_type="status_code",
                    field_name="status_code",
                    expected=200,
                    actual=200,
                    passed=True,
                    message="OK",
                )
            ],
            response_size_bytes=512,
        )
        probe_id = self.storage.save_probe_result(result)
        self.assertGreater(probe_id, 0)

        probes = self.storage.get_recent_probes(target_id="api-1", limit=10)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0].target_id, "api-1")
        self.assertEqual(probes[0].status_code, 200)
        self.assertEqual(len(probes[0].assertions), 1)
        self.assertTrue(probes[0].assertions[0].passed)

    def test_incident_lifecycle(self):
        # 1. Unhealthy probe triggers open incident
        bad_result = ProbeResult(
            target_id="failing-svc",
            target_name="Failing Service",
            url="https://example.com/fail",
            method="GET",
            status_code=503,
            latency_ms=900.0,
            timestamp="2026-11-02T12:00:00Z",
            status=HealthStatus.UNHEALTHY,
            error="Service Unavailable",
        )
        self.storage.save_probe_result(bad_result)
        open_incidents = self.storage.get_open_incidents()
        self.assertEqual(len(open_incidents), 1)
        self.assertEqual(open_incidents[0].target_id, "failing-svc")

        # 2. Healthy probe resolves the incident
        good_result = ProbeResult(
            target_id="failing-svc",
            target_name="Failing Service",
            url="https://example.com/fail",
            method="GET",
            status_code=200,
            latency_ms=100.0,
            timestamp="2026-11-02T12:05:00Z",
            status=HealthStatus.HEALTHY,
        )
        self.storage.save_probe_result(good_result)
        open_incidents_after = self.storage.get_open_incidents()
        self.assertEqual(len(open_incidents_after), 0)

    def test_target_metrics_aggregation(self):
        for lat in [100.0, 150.0, 200.0]:
            self.storage.save_probe_result(
                ProbeResult(
                    target_id="metrics-target",
                    target_name="Metrics Target",
                    url="https://example.com",
                    method="GET",
                    status_code=200,
                    latency_ms=lat,
                    timestamp="2026-11-02T12:00:00Z",
                    status=HealthStatus.HEALTHY,
                )
            )

        metrics = self.storage.get_target_metrics("metrics-target", "Metrics Target")
        self.assertEqual(metrics.total_probes, 3)
        self.assertEqual(metrics.healthy_count, 3)
        self.assertEqual(metrics.uptime_pct, 100.0)
        self.assertEqual(metrics.avg_latency_ms, 150.0)
        self.assertEqual(metrics.min_latency_ms, 100.0)
        self.assertEqual(metrics.max_latency_ms, 200.0)


if __name__ == "__main__":
    unittest.main()
