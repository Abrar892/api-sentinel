"""Tests for assertion engine and operators."""

import unittest

from api_sentinel.assertions import AssertionEngine, extract_json_path
from api_sentinel.config import AssertionRule


class TestAssertions(unittest.TestCase):
    def test_extract_json_path_nested(self):
        data = {
            "meta": {"code": 200},
            "data": {
                "users": [
                    {"id": 101, "name": "Admin"},
                    {"id": 102, "name": "Developer"},
                ]
            },
        }
        found, val = extract_json_path(data, "meta.code")
        self.assertTrue(found)
        self.assertEqual(val, 200)

        found, val = extract_json_path(data, "data.users.1.name")
        self.assertTrue(found)
        self.assertEqual(val, "Developer")

        found, val = extract_json_path(data, "nonexistent.key")
        self.assertFalse(found)

    def test_status_code_assertion(self):
        rule = AssertionRule(rule_type="status_code", expected=200, operator="eq")
        res = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=200,
            latency_ms=45.0,
            headers={},
            body_text="",
        )
        self.assertTrue(res.passed)

        res_fail = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=500,
            latency_ms=45.0,
            headers={},
            body_text="",
        )
        self.assertFalse(res_fail.passed)

    def test_latency_assertion(self):
        rule = AssertionRule(rule_type="max_latency_ms", expected=300.0, operator="lte")
        res_pass = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=200,
            latency_ms=250.0,
            headers={},
            body_text="",
        )
        self.assertTrue(res_pass.passed)

        res_fail = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=200,
            latency_ms=350.0,
            headers={},
            body_text="",
        )
        self.assertFalse(res_fail.passed)

    def test_header_match(self):
        rule = AssertionRule(
            rule_type="header_match",
            field_name="Content-Type",
            expected="application/json",
            operator="contains",
        )
        headers = {"content-type": "application/json; charset=utf-8"}
        res = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=200,
            latency_ms=50.0,
            headers=headers,
            body_text="{}",
        )
        self.assertTrue(res.passed)

    def test_json_path_assertion(self):
        rule = AssertionRule(
            rule_type="json_path",
            field_name="service.status",
            expected="UP",
            operator="eq",
        )
        body = '{"service": {"status": "UP", "version": "1.0"}}'
        res = AssertionEngine.evaluate_rule(
            rule=rule,
            status_code=200,
            latency_ms=10.0,
            headers={},
            body_text=body,
        )
        self.assertTrue(res.passed)

    def test_body_regex_and_contains(self):
        rule_regex = AssertionRule(rule_type="body_regex", expected=r"v[0-9]+\.[0-9]+")
        rule_contains = AssertionRule(rule_type="body_contains", expected="Welcome")

        body = "Welcome to the Sentinel API v2.4"
        res1 = AssertionEngine.evaluate_rule(
            rule=rule_regex,
            status_code=200,
            latency_ms=10.0,
            headers={},
            body_text=body,
        )
        self.assertTrue(res1.passed)

        res2 = AssertionEngine.evaluate_rule(
            rule=rule_contains,
            status_code=200,
            latency_ms=10.0,
            headers={},
            body_text=body,
        )
        self.assertTrue(res2.passed)


if __name__ == "__main__":
    unittest.main()
