"""Concurrent probe execution engine with retries and health classification."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .alerts import AlertDispatcher
from .assertions import AssertionEngine
from .config import AssertionRule, TargetConfig
from .http_client import HttpClient, RawResponse
from .models import AssertionResult, HealthStatus, ProbeResult
from .storage import SentinelStorage
from .ws_client import WebSocketClient


class ProbeExecutor:
    """Coordinates concurrent endpoint probes, retry loops, and health evaluations."""

    def __init__(
        self,
        storage: Optional[SentinelStorage] = None,
        on_probe_complete: Optional[Callable[[ProbeResult], None]] = None,
        alert_dispatcher: Optional[AlertDispatcher] = None,
    ):
        self.storage = storage
        self.on_probe_complete = on_probe_complete
        self.alert_dispatcher = alert_dispatcher

    def probe_target(self, target: TargetConfig) -> ProbeResult:
        """Execute probe for a single target, with retry and backoff on transient failures."""
        attempts = 0
        max_attempts = target.max_retries + 1
        last_response: Optional[RawResponse] = None
        last_error: Optional[str] = None
        is_ws = target.url.lower().startswith(("ws://", "wss://"))

        while attempts < max_attempts:
            attempts += 1
            if is_ws:
                response = WebSocketClient.probe(
                    url=target.url,
                    timeout_seconds=target.timeout_seconds,
                    headers=target.headers,
                    send_payload=target.ws_payload,
                )
            else:
                response = HttpClient.execute_request(
                    url=target.url,
                    method=target.method,
                    headers=target.headers,
                    body=target.body,
                    timeout_seconds=target.timeout_seconds,
                )
            last_response = response

            # If request succeeded with an HTTP/WS response, stop retry loop
            if response.status_code is not None:
                break

            # Network connection or timeout error
            last_error = response.error_message
            if attempts < max_attempts and target.retry_backoff_ms > 0:
                time.sleep((target.retry_backoff_ms * attempts) / 1000.0)

        # Build ProbeResult
        timestamp = datetime.now(timezone.utc).isoformat()

        if last_response is None or last_response.status_code is None:
            result = ProbeResult(
                target_id=target.id,
                target_name=target.name,
                url=target.url,
                method="WS" if is_ws else target.method,
                status_code=None,
                latency_ms=last_response.latency_ms if last_response else 0.0,
                timestamp=timestamp,
                status=HealthStatus.UNHEALTHY,
                assertions=[],
                error=last_error or "Network unreachable",
                response_size_bytes=0,
                attempt=attempts,
            )
        else:
            # Evaluate all configured assertion rules
            rules = list(target.assertions)

            # If no assertions configured, inject default status rule (101 for WS, 200 for HTTP)
            if not rules:
                expected_status = 101 if is_ws else 200
                rules.append(AssertionRule(rule_type="status_code", expected=expected_status, operator="eq"))

            assertion_results = AssertionEngine.evaluate_all(
                rules=rules,
                status_code=last_response.status_code,
                latency_ms=last_response.latency_ms,
                headers=last_response.headers,
                body_text=last_response.body_text,
            )

            # Determine health classification
            all_passed = all(a.passed for a in assertion_results)

            if all_passed:
                # Check SLA degradation threshold
                if last_response.latency_ms > target.sla_latency_threshold_ms:
                    health = HealthStatus.DEGRADED
                else:
                    health = HealthStatus.HEALTHY
                error_msg = None
            else:
                # Check if failure is only latency-based
                non_latency_failures = [
                    a for a in assertion_results if not a.passed and a.rule_type != "max_latency_ms"
                ]
                latency_failures = [
                    a for a in assertion_results if not a.passed and a.rule_type == "max_latency_ms"
                ]

                # If status code is valid (2xx) and only latency failed, mark degraded
                if not non_latency_failures and latency_failures and (
                    last_response.status_code and 200 <= last_response.status_code < 300
                ):
                    health = HealthStatus.DEGRADED
                    error_msg = "SLA latency threshold exceeded"
                else:
                    health = HealthStatus.UNHEALTHY
                    failed_msgs = [f"[{a.field_name}] {a.message}" for a in assertion_results if not a.passed]
                    error_msg = "; ".join(failed_msgs)

            result = ProbeResult(
                target_id=target.id,
                target_name=target.name,
                url=target.url,
                method="WS" if is_ws else target.method,
                status_code=last_response.status_code,
                latency_ms=last_response.latency_ms,
                timestamp=timestamp,
                status=health,
                assertions=assertion_results,
                error=error_msg,
                headers=last_response.headers,
                response_size_bytes=last_response.size_bytes,
                attempt=attempts,
            )

        # Persist result if storage configured
        if self.storage:
            try:
                self.storage.save_probe_result(result)
            except Exception:
                pass

        # Dispatch webhook alert on failure
        if self.alert_dispatcher and result.status == HealthStatus.UNHEALTHY:
            try:
                self.alert_dispatcher.dispatch_incident_event(
                    event_type="incident.detected",
                    target_id=result.target_id,
                    target_name=result.target_name,
                    url=result.url,
                    status=result.status,
                    details=result.error or "Probe assertion failure",
                    timestamp=result.timestamp,
                )
            except Exception:
                pass

        if self.on_probe_complete:
            self.on_probe_complete(result)

        return result

    def probe_all(
        self, targets: List[TargetConfig], concurrency: int = 4
    ) -> List[ProbeResult]:
        """Concurrently probe all configured targets and return sorted results."""
        if not targets:
            return []

        results: List[ProbeResult] = []
        max_workers = min(len(targets), max(concurrency, 1))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_target = {
                executor.submit(self.probe_target, target): target for target in targets
            }
            for future in as_completed(future_to_target):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as exc:
                    target = future_to_target[future]
                    results.append(
                        ProbeResult.failure(
                            target_id=target.id,
                            target_name=target.name,
                            url=target.url,
                            method=target.method,
                            error=f"Executor exception: {exc}",
                        )
                    )

        # Sort results to match original target ordering
        order_map = {t.id: i for i, t in enumerate(targets)}
        results.sort(key=lambda r: order_map.get(r.target_id, 999))
        return results
