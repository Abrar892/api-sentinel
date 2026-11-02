"""Configuration loading, validation, and schema definitions for API Sentinel."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


VALID_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
VALID_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "contains", "regex"}
VALID_RULE_TYPES = {
    "status_code",
    "max_latency_ms",
    "json_path",
    "header_match",
    "body_regex",
    "body_contains",
}


class ConfigValidationError(Exception):
    """Raised when monitor configuration fails semantic validation."""
    pass


@dataclass
class AssertionRule:
    """Assertion condition applied against probe responses."""
    rule_type: str
    expected: Any
    field_name: Optional[str] = None
    operator: str = "eq"

    def __post_init__(self):
        if self.rule_type not in VALID_RULE_TYPES:
            raise ConfigValidationError(
                f"Unsupported assertion rule_type: '{self.rule_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_RULE_TYPES))}"
            )
        if self.operator not in VALID_OPERATORS:
            raise ConfigValidationError(
                f"Unsupported assertion operator: '{self.operator}'. "
                f"Must be one of: {', '.join(sorted(VALID_OPERATORS))}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssertionRule:
        return cls(
            rule_type=data.get("rule_type", "status_code"),
            expected=data.get("expected"),
            field_name=data.get("field_name"),
            operator=data.get("operator", "eq"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "expected": self.expected,
            "field_name": self.field_name,
            "operator": self.operator,
        }


@dataclass
class TargetConfig:
    """Specification of an HTTP target to probe and validate."""
    id: str
    name: str
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    timeout_seconds: float = 10.0
    max_retries: int = 1
    retry_backoff_ms: int = 200
    sla_latency_threshold_ms: float = 500.0
    assertions: List[AssertionRule] = field(default_factory=list)

    def __post_init__(self):
        self.method = self.method.upper()
        if self.method not in VALID_HTTP_METHODS:
            raise ConfigValidationError(
                f"Invalid HTTP method '{self.method}' for target '{self.id}'. "
                f"Must be one of {sorted(VALID_HTTP_METHODS)}"
            )

        parsed = urlparse(self.url)
        if not parsed.scheme or not parsed.netloc:
            raise ConfigValidationError(
                f"Target '{self.id}' has invalid URL: '{self.url}'. "
                "Must include valid protocol (http/https) and host."
            )
        if parsed.scheme not in ("http", "https"):
            raise ConfigValidationError(
                f"Target '{self.id}' protocol must be http or https, got: '{parsed.scheme}'"
            )

        if self.timeout_seconds <= 0:
            raise ConfigValidationError(
                f"Target '{self.id}' timeout_seconds must be positive, got: {self.timeout_seconds}"
            )

        if self.max_retries < 0:
            raise ConfigValidationError(
                f"Target '{self.id}' max_retries must be non-negative, got: {self.max_retries}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TargetConfig:
        assertions_raw = data.get("assertions", [])
        assertions = [
            AssertionRule.from_dict(a) if isinstance(a, dict) else a
            for a in assertions_raw
        ]
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            url=data["url"],
            method=data.get("method", "GET"),
            headers=data.get("headers", {}),
            body=data.get("body"),
            timeout_seconds=float(data.get("timeout_seconds", 10.0)),
            max_retries=int(data.get("max_retries", 1)),
            retry_backoff_ms=int(data.get("retry_backoff_ms", 200)),
            sla_latency_threshold_ms=float(data.get("sla_latency_threshold_ms", 500.0)),
            assertions=assertions,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "method": self.method,
            "headers": self.headers,
            "body": self.body,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_backoff_ms": self.retry_backoff_ms,
            "sla_latency_threshold_ms": self.sla_latency_threshold_ms,
            "assertions": [a.to_dict() for a in self.assertions],
        }


@dataclass
class MonitorConfig:
    """Master configuration containing monitor settings and target list."""
    name: str = "API Sentinel Monitor"
    environment: str = "production"
    db_path: str = ".sentinel/sentinel.db"
    concurrency: int = 4
    targets: List[TargetConfig] = field(default_factory=list)

    def __post_init__(self):
        if self.concurrency < 1:
            raise ConfigValidationError("concurrency must be at least 1")

        # Validate unique target IDs
        ids = set()
        for target in self.targets:
            if target.id in ids:
                raise ConfigValidationError(f"Duplicate target ID found: '{target.id}'")
            ids.add(target.id)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MonitorConfig:
        targets_raw = data.get("targets", [])
        targets = [
            TargetConfig.from_dict(t) if isinstance(t, dict) else t
            for t in targets_raw
        ]
        return cls(
            name=data.get("name", "API Sentinel Monitor"),
            environment=data.get("environment", "production"),
            db_path=data.get("db_path", ".sentinel/sentinel.db"),
            concurrency=int(data.get("concurrency", 4)),
            targets=targets,
        )

    @classmethod
    def load_from_file(cls, path: str) -> MonitorConfig:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def save_to_file(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "environment": self.environment,
            "db_path": self.db_path,
            "concurrency": self.concurrency,
            "targets": [t.to_dict() for t in self.targets],
        }
