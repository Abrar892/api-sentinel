"""SQLite persistence layer for probe time-series, assertions, and incidents."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

from .models import AssertionResult, HealthStatus, IncidentRecord, ProbeResult, TargetMetrics


def calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate percentile rank using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_data[int(k)], 2)
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return round(d0 + d1, 2)


class SentinelStorage:
    """Manages SQLite storage for probe observations, assertion audits, and SLA tracking."""

    def __init__(self, db_path: str = ".sentinel/sentinel.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS probes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status_code INTEGER,
                    latency_ms REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    response_size_bytes INTEGER DEFAULT 0,
                    attempt INTEGER DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_probes_target_time
                ON probes(target_id, timestamp);

                CREATE TABLE IF NOT EXISTS assertions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    probe_id INTEGER NOT NULL REFERENCES probes(id) ON DELETE CASCADE,
                    rule_type TEXT NOT NULL,
                    field_name TEXT,
                    expected TEXT,
                    actual TEXT,
                    passed INTEGER NOT NULL,
                    message TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_assertions_probe
                ON assertions(probe_id);

                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT UNIQUE NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    resolved_at TEXT,
                    error_summary TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_target
                ON incidents(target_id, resolved);
                """
            )

    def save_probe_result(self, result: ProbeResult) -> int:
        """Persist a single probe observation and its assertion outcomes."""
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO probes (
                    target_id, target_name, url, method, status_code,
                    latency_ms, timestamp, status, error, response_size_bytes, attempt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.target_id,
                    result.target_name,
                    result.url,
                    result.method,
                    result.status_code,
                    result.latency_ms,
                    result.timestamp,
                    result.status.value,
                    result.error,
                    result.response_size_bytes,
                    result.attempt,
                ),
            )
            probe_id = cur.lastrowid

            if result.assertions:
                cur.executemany(
                    """
                    INSERT INTO assertions (
                        probe_id, rule_type, field_name, expected, actual, passed, message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            probe_id,
                            a.rule_type,
                            a.field_name,
                            json.dumps(a.expected) if not isinstance(a.expected, (str, int, float, bool)) and a.expected is not None else str(a.expected),
                            json.dumps(a.actual) if not isinstance(a.actual, (str, int, float, bool)) and a.actual is not None else str(a.actual),
                            1 if a.passed else 0,
                            a.message,
                        )
                        for a in result.assertions
                    ],
                )

            # Auto-handle incident lifecycle
            self._update_incident_state(conn, result)

            conn.commit()
            return probe_id

    def _update_incident_state(self, conn: sqlite3.Connection, result: ProbeResult) -> None:
        """Track ongoing incidents or mark them resolved when health restores."""
        cur = conn.cursor()
        cur.execute(
            """
            SELECT incident_id, started_at FROM incidents
            WHERE target_id = ? AND resolved = 0
            ORDER BY id DESC LIMIT 1
            """,
            (result.target_id,),
        )
        row = cur.fetchone()

        if result.status == HealthStatus.UNHEALTHY:
            if not row:
                # Open a new incident
                inc_id = f"inc_{uuid.uuid4().hex[:8]}"
                err = result.error or "Assertion validation failed"
                cur.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, target_id, target_name, started_at, error_summary, resolved
                    ) VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (inc_id, result.target_id, result.target_name, result.timestamp, err),
                )
        elif result.status == HealthStatus.HEALTHY and row:
            # Resolve existing open incident
            cur.execute(
                """
                UPDATE incidents
                SET resolved = 1, resolved_at = ?
                WHERE incident_id = ?
                """,
                (result.timestamp, row["incident_id"]),
            )

    def get_recent_probes(
        self, target_id: Optional[str] = None, limit: int = 50
    ) -> List[ProbeResult]:
        """Fetch recent probe results, optionally filtered by target."""
        with self._connection() as conn:
            cur = conn.cursor()
            if target_id:
                cur.execute(
                    """
                    SELECT id, target_id, target_name, url, method, status_code,
                           latency_ms, timestamp, status, error, response_size_bytes, attempt
                    FROM probes
                    WHERE target_id = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (target_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, target_id, target_name, url, method, status_code,
                           latency_ms, timestamp, status, error, response_size_bytes, attempt
                    FROM probes
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                )
            rows = cur.fetchall()

            results: List[ProbeResult] = []
            for r in rows:
                probe_id = r["id"]
                # Fetch assertions for this probe
                cur.execute(
                    """
                    SELECT rule_type, field_name, expected, actual, passed, message
                    FROM assertions WHERE probe_id = ?
                    """,
                    (probe_id,),
                )
                a_rows = cur.fetchall()
                assertions = [
                    AssertionResult(
                        rule_type=ar["rule_type"],
                        field_name=ar["field_name"],
                        expected=ar["expected"],
                        actual=ar["actual"],
                        passed=bool(ar["passed"]),
                        message=ar["message"],
                    )
                    for ar in a_rows
                ]

                results.append(
                    ProbeResult(
                        target_id=r["target_id"],
                        target_name=r["target_name"],
                        url=r["url"],
                        method=r["method"],
                        status_code=r["status_code"],
                        latency_ms=r["latency_ms"],
                        timestamp=r["timestamp"],
                        status=HealthStatus(r["status"]),
                        assertions=assertions,
                        error=r["error"],
                        response_size_bytes=r["response_size_bytes"],
                        attempt=r["attempt"],
                    )
                )

            return results

    def get_target_metrics(
        self, target_id: str, target_name: str, since_timestamp: Optional[str] = None
    ) -> TargetMetrics:
        """Calculate aggregate latency percentiles and uptime statistics."""
        with self._connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT status, latency_ms, timestamp
                FROM probes
                WHERE target_id = ?
            """
            params: List[Any] = [target_id]
            if since_timestamp:
                query += " AND timestamp >= ?"
                params.append(since_timestamp)
            query += " ORDER BY id ASC"

            cur.execute(query, params)
            rows = cur.fetchall()

            if not rows:
                return TargetMetrics(
                    target_id=target_id,
                    target_name=target_name,
                    last_status=HealthStatus.UNKNOWN,
                )

            total = len(rows)
            healthy = sum(1 for r in rows if r["status"] == HealthStatus.HEALTHY.value)
            degraded = sum(1 for r in rows if r["status"] == HealthStatus.DEGRADED.value)
            unhealthy = sum(1 for r in rows if r["status"] == HealthStatus.UNHEALTHY.value)

            latencies = [float(r["latency_ms"]) for r in rows if r["latency_ms"] is not None]
            uptime = round(((healthy + degraded) / total) * 100.0, 2) if total > 0 else 100.0

            last_row = rows[-1]

            return TargetMetrics(
                target_id=target_id,
                target_name=target_name,
                total_probes=total,
                healthy_count=healthy,
                degraded_count=degraded,
                unhealthy_count=unhealthy,
                uptime_pct=uptime,
                min_latency_ms=round(min(latencies), 2) if latencies else 0.0,
                max_latency_ms=round(max(latencies), 2) if latencies else 0.0,
                avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
                p50_latency_ms=calculate_percentile(latencies, 50.0),
                p95_latency_ms=calculate_percentile(latencies, 95.0),
                p99_latency_ms=calculate_percentile(latencies, 99.0),
                last_status=HealthStatus(last_row["status"]),
                last_checked_at=last_row["timestamp"],
            )

    def get_open_incidents(self) -> List[IncidentRecord]:
        """Retrieve unresolved system incidents."""
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT incident_id, target_id, target_name, started_at, resolved_at, error_summary, resolved
                FROM incidents
                WHERE resolved = 0
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
            return [
                IncidentRecord(
                    incident_id=r["incident_id"],
                    target_id=r["target_id"],
                    target_name=r["target_name"],
                    started_at=r["started_at"],
                    resolved_at=r["resolved_at"],
                    error_summary=r["error_summary"],
                    resolved=bool(r["resolved"]),
                )
                for r in rows
            ]
