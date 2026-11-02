"""End-to-end integration tests using local mock server."""

import os
import tempfile
import unittest

from api_sentinel.config import AssertionRule, MonitorConfig, TargetConfig
from api_sentinel.engine import ProbeExecutor
from api_sentinel.mock_server import MockServerDaemon
from api_sentinel.models import HealthStatus
from api_sentinel.storage import SentinelStorage


class TestE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start mock server on loopback with ephemeral port
        cls.mock_daemon = MockServerDaemon(host="127.0.0.1", port=0)
        cls.mock_daemon.start()
        cls.base_url = cls.mock_daemon.base_url

    @classmethod
    def tearDownClass(cls):
        cls.mock_daemon.stop()

    def test_full_pipeline_healthy_degraded_unhealthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "e2e_sentinel.db")
            storage = SentinelStorage(db_path)
            executor = ProbeExecutor(storage=storage)

            targets = [
                TargetConfig(
                    id="health-endpoint",
                    name="Health Check",
                    url=f"{self.base_url}/health",
                    method="GET",
                    sla_latency_threshold_ms=1000.0,
                    assertions=[
                        AssertionRule(rule_type="status_code", expected=200),
                        AssertionRule(rule_type="json_path", field_name="status", expected="healthy"),
                    ],
                ),
                TargetConfig(
                    id="degraded-endpoint",
                    name="Delayed Service",
                    url=f"{self.base_url}/delay?ms=120",
                    method="GET",
                    sla_latency_threshold_ms=50.0,  # lower than 120ms -> degraded
                    assertions=[
                        AssertionRule(rule_type="status_code", expected=200),
                    ],
                ),
                TargetConfig(
                    id="faulty-endpoint",
                    name="Crashing Service",
                    url=f"{self.base_url}/fault?code=500",
                    method="GET",
                    sla_latency_threshold_ms=500.0,
                    assertions=[
                        AssertionRule(rule_type="status_code", expected=200),
                    ],
                ),
                TargetConfig(
                    id="users-endpoint",
                    name="Users API",
                    url=f"{self.base_url}/users",
                    method="GET",
                    assertions=[
                        AssertionRule(rule_type="status_code", expected=200),
                        AssertionRule(rule_type="json_path", field_name="users.0.name", expected="Alice"),
                    ],
                ),
            ]

            results = executor.probe_all(targets, concurrency=4)
            self.assertEqual(len(results), 4)

            status_by_id = {r.target_id: r.status for r in results}
            self.assertEqual(status_by_id["health-endpoint"], HealthStatus.HEALTHY)
            self.assertEqual(status_by_id["degraded-endpoint"], HealthStatus.DEGRADED)
            self.assertEqual(status_by_id["faulty-endpoint"], HealthStatus.UNHEALTHY)
            self.assertEqual(status_by_id["users-endpoint"], HealthStatus.HEALTHY)

            # Check SQLite persisted data
            persisted_probes = storage.get_recent_probes(limit=10)
            self.assertEqual(len(persisted_probes), 4)

            # Check open incidents: faulty-endpoint should be an open incident
            open_incidents = storage.get_open_incidents()
            self.assertEqual(len(open_incidents), 1)
            self.assertEqual(open_incidents[0].target_id, "faulty-endpoint")


if __name__ == "__main__":
    unittest.main()
