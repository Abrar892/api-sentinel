"""Data models and domain entities for API Sentinel."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class HealthStatus(str, Enum):
    """Health classification for probed endpoints."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

    @property
    def badge_color(self) -> str:
        if self == HealthStatus.HEALTHY:
            return "#10b981"  # Emerald green
        if self == HealthStatus.DEGRADED:
            return "#f59e0b"  # Amber
        if self == HealthStatus.UNHEALTHY:
            return "#ef4444"  # Crimson red
        return "#6b7280"      # Slate gray


@dataclass
class AssertionResult:
    """Outcome of an individual assertion rule execution."""
    rule_type: str
    field_name: str
    expected: Any
    actual: Any
    passed: bool
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProbeResult:
    """Detailed observation recorded from an HTTP endpoint probe."""
    target_id: str
    target_name: str
    url: str
    method: str
    status_code: Optional[int]
    latency_ms: float
    timestamp: str
    status: HealthStatus
    assertions: List[AssertionResult] = field(default_factory=list)
    error: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    response_size_bytes: int = 0
    attempt: int = 1

    @classmethod
    def failure(
        cls,
        target_id: str,
        target_name: str,
        url: str,
        method: str,
        error: str,
        latency_ms: float = 0.0,
        attempt: int = 1,
    ) -> ProbeResult:
        """Helper to create a failed probe observation."""
        return cls(
            target_id=target_id,
            target_name=target_name,
            url=url,
            method=method,
            status_code=None,
            latency_ms=round(latency_ms, 2),
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=HealthStatus.UNHEALTHY,
            error=error,
            attempt=attempt,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class TargetMetrics:
    """Aggregated historical performance and SLA metrics for a target."""
    target_id: str
    target_name: str
    total_probes: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    unhealthy_count: int = 0
    uptime_pct: float = 100.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    last_status: HealthStatus = HealthStatus.UNKNOWN
    last_checked_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["last_status"] = self.last_status.value
        return data


@dataclass
class IncidentRecord:
    """Incident tracker for tracking target downtime and recovery."""
    incident_id: str
    target_id: str
    target_name: str
    started_at: str
    resolved_at: Optional[str] = None
    error_summary: str = ""
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
