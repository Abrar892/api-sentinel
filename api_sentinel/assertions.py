"""Assertion engine evaluating HTTP probe responses against configured rules."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import AssertionRule
from .models import AssertionResult


def extract_json_path(data: Any, path: str) -> Tuple[bool, Any]:
    """
    Extract a nested value from JSON data using dot-notation.
    Supports dictionary keys and integer array indices (e.g., 'data.users.0.email').
    """
    if not path:
        return False, None

    tokens = path.split(".")
    current = data

    for token in tokens:
        if isinstance(current, dict):
            if token in current:
                current = current[token]
            else:
                return False, None
        elif isinstance(current, (list, tuple)):
            if token.isdigit():
                idx = int(token)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return False, None
            else:
                return False, None
        else:
            return False, None

    return True, current


def evaluate_operator(actual: Any, expected: Any, operator: str) -> Tuple[bool, str]:
    """Compare actual and expected values according to the specified operator."""
    try:
        if operator == "eq":
            passed = actual == expected
            msg = f"Expected {expected!r}, got {actual!r}"
            return passed, msg

        if operator == "ne":
            passed = actual != expected
            msg = f"Expected value not equal to {expected!r}, got {actual!r}"
            return passed, msg

        if operator in ("lt", "lte", "gt", "gte"):
            if actual is None:
                return False, f"Cannot perform numeric comparison on None value"
            act_num = float(actual)
            exp_num = float(expected)
            if operator == "lt":
                passed = act_num < exp_num
            elif operator == "lte":
                passed = act_num <= exp_num
            elif operator == "gt":
                passed = act_num > exp_num
            else:
                passed = act_num >= exp_num
            return passed, f"{act_num} {operator} {exp_num}"

        if operator == "contains":
            if actual is None:
                return False, "Actual value is None"
            if isinstance(actual, (str, list, dict, set, tuple)):
                passed = expected in actual if not isinstance(actual, str) else str(expected) in actual
            else:
                passed = str(expected) in str(actual)
            return passed, f"Expected '{actual}' to contain '{expected}'"

        if operator == "regex":
            if actual is None:
                return False, "Cannot evaluate regex on None"
            pattern = re.compile(str(expected))
            passed = pattern.search(str(actual)) is not None
            return passed, f"Regex pattern r'{expected}' against '{actual}'"

        return False, f"Unknown operator: {operator}"

    except (ValueError, TypeError, re.error) as err:
        return False, f"Evaluation error: {err}"


class AssertionEngine:
    """Evaluates probe responses against an ordered list of assertion rules."""

    @staticmethod
    def evaluate_rule(
        rule: AssertionRule,
        status_code: Optional[int],
        latency_ms: float,
        headers: Dict[str, str],
        body_text: str,
        parsed_json: Optional[Any] = None,
    ) -> AssertionResult:
        field_label = rule.field_name or rule.rule_type

        # 1. Status Code
        if rule.rule_type == "status_code":
            passed, detail = evaluate_operator(status_code, rule.expected, rule.operator)
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name="status_code",
                expected=rule.expected,
                actual=status_code,
                passed=passed,
                message=detail if not passed else f"Status code matches {rule.expected}",
            )

        # 2. Maximum Latency (ms)
        if rule.rule_type == "max_latency_ms":
            passed, detail = evaluate_operator(latency_ms, rule.expected, rule.operator or "lte")
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name="latency_ms",
                expected=rule.expected,
                actual=round(latency_ms, 2),
                passed=passed,
                message=detail if not passed else f"Latency {latency_ms:.1f}ms within threshold {rule.expected}ms",
            )

        # 3. HTTP Header Match
        if rule.rule_type == "header_match":
            header_key = (rule.field_name or "").lower()
            # Normalize headers dictionary for case-insensitive lookup
            norm_headers = {k.lower(): v for k, v in headers.items()}
            actual_val = norm_headers.get(header_key)
            passed, detail = evaluate_operator(actual_val, rule.expected, rule.operator)
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name=f"header:{header_key}",
                expected=rule.expected,
                actual=actual_val,
                passed=passed,
                message=detail if not passed else f"Header '{header_key}' satisfied expectation",
            )

        # 4. JSON Path Extraction & Validation
        if rule.rule_type == "json_path":
            if parsed_json is None:
                try:
                    parsed_json = json.loads(body_text)
                except Exception:
                    return AssertionResult(
                        rule_type=rule.rule_type,
                        field_name=rule.field_name or "body",
                        expected=rule.expected,
                        actual=None,
                        passed=False,
                        message="Response body is not valid JSON",
                    )
            found, extracted_val = extract_json_path(parsed_json, rule.field_name or "")
            if not found:
                return AssertionResult(
                    rule_type=rule.rule_type,
                    field_name=rule.field_name or "path",
                    expected=rule.expected,
                    actual=None,
                    passed=False,
                    message=f"JSON path '{rule.field_name}' not found in response payload",
                )
            passed, detail = evaluate_operator(extracted_val, rule.expected, rule.operator)
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name=rule.field_name or "path",
                expected=rule.expected,
                actual=extracted_val,
                passed=passed,
                message=detail if not passed else f"JSON path '{rule.field_name}' verified",
            )

        # 5. Body Regex Match
        if rule.rule_type == "body_regex":
            passed, detail = evaluate_operator(body_text, rule.expected, "regex")
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name="body",
                expected=rule.expected,
                actual=f"{body_text[:80]}..." if len(body_text) > 80 else body_text,
                passed=passed,
                message=detail if not passed else "Body regex pattern matched",
            )

        # 6. Body Substring Contains
        if rule.rule_type == "body_contains":
            passed, detail = evaluate_operator(body_text, rule.expected, "contains")
            return AssertionResult(
                rule_type=rule.rule_type,
                field_name="body",
                expected=rule.expected,
                actual=f"{body_text[:80]}..." if len(body_text) > 80 else body_text,
                passed=passed,
                message=detail if not passed else f"Body contains '{rule.expected}'",
            )

        return AssertionResult(
            rule_type=rule.rule_type,
            field_name=field_label,
            expected=rule.expected,
            actual=None,
            passed=False,
            message=f"Unsupported rule type: {rule.rule_type}",
        )

    @classmethod
    def evaluate_all(
        cls,
        rules: List[AssertionRule],
        status_code: Optional[int],
        latency_ms: float,
        headers: Dict[str, str],
        body_text: str,
    ) -> List[AssertionResult]:
        """Run all configured assertion rules against the response."""
        results: List[AssertionResult] = []
        parsed_json = None
        # Attempt to parse json once if needed
        for rule in rules:
            if rule.rule_type == "json_path" and parsed_json is None:
                try:
                    parsed_json = json.loads(body_text)
                except Exception:
                    pass

            result = cls.evaluate_rule(
                rule=rule,
                status_code=status_code,
                latency_ms=latency_ms,
                headers=headers,
                body_text=body_text,
                parsed_json=parsed_json,
            )
            results.append(result)

        return results
