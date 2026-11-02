"""Tests for configuration parsing, defaults, and validation."""

import os
import tempfile
import unittest

from api_sentinel.config import (
    AssertionRule,
    ConfigValidationError,
    MonitorConfig,
    TargetConfig,
)


class TestConfig(unittest.TestCase):
    def test_valid_assertion_rule(self):
        rule = AssertionRule(rule_type="status_code", expected=200, operator="eq")
        self.assertEqual(rule.rule_type, "status_code")
        self.assertEqual(rule.expected, 200)
        self.assertEqual(rule.operator, "eq")

    def test_invalid_rule_type(self):
        with self.assertRaises(ConfigValidationError):
            AssertionRule(rule_type="invalid_type", expected=1)

    def test_invalid_operator(self):
        with self.assertRaises(ConfigValidationError):
            AssertionRule(rule_type="status_code", expected=200, operator="super_equal")

    def test_valid_target_config(self):
        target = TargetConfig(
            id="test-1",
            name="Test Target",
            url="https://example.com/api",
            method="post",
        )
        self.assertEqual(target.method, "POST")
        self.assertEqual(target.timeout_seconds, 10.0)

    def test_target_invalid_url(self):
        with self.assertRaises(ConfigValidationError):
            TargetConfig(id="test-bad", name="Bad", url="ftp://not-supported")

    def test_target_invalid_method(self):
        with self.assertRaises(ConfigValidationError):
            TargetConfig(id="test-bad", name="Bad", url="https://example.com", method="UNKNOWN")

    def test_target_negative_timeout(self):
        with self.assertRaises(ConfigValidationError):
            TargetConfig(id="test-bad", name="Bad", url="https://example.com", timeout_seconds=-5)

    def test_monitor_config_duplicate_ids(self):
        t1 = TargetConfig(id="dup", name="One", url="https://example.com/1")
        t2 = TargetConfig(id="dup", name="Two", url="https://example.com/2")
        with self.assertRaises(ConfigValidationError):
            MonitorConfig(targets=[t1, t2])

    def test_config_save_and_load(self):
        t = TargetConfig(
            id="save-load-test",
            name="Save Load",
            url="https://example.com/test",
            assertions=[AssertionRule(rule_type="status_code", expected=200)],
        )
        cfg = MonitorConfig(name="Saved Config", targets=[t])

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test_config.json")
            cfg.save_to_file(file_path)

            loaded = MonitorConfig.load_from_file(file_path)
            self.assertEqual(loaded.name, "Saved Config")
            self.assertEqual(len(loaded.targets), 1)
            self.assertEqual(loaded.targets[0].id, "save-load-test")
            self.assertEqual(loaded.targets[0].assertions[0].expected, 200)


if __name__ == "__main__":
    unittest.main()
