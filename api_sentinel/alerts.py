"""Webhook notification dispatcher for incident alerts."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import HealthStatus, IncidentRecord, ProbeResult


class AlertDispatcher:
    """Dispatches webhook alerts on target downtime or recovery events."""

    def __init__(self, webhook_urls: Optional[List[str]] = None, timeout_seconds: float = 5.0):
        self.webhook_urls = webhook_urls or []
        self.timeout_seconds = timeout_seconds

    def dispatch_incident_event(
        self,
        event_type: str,
        target_id: str,
        target_name: str,
        url: str,
        status: HealthStatus,
        details: str,
        timestamp: str,
    ) -> List[Dict[str, Any]]:
        """Send notification payload to all configured webhook endpoints."""
        if not self.webhook_urls:
            return []

        payload = {
            "source": "api-sentinel",
            "event": event_type,
            "target_id": target_id,
            "target_name": target_name,
            "target_url": url,
            "status": status.value,
            "message": details,
            "timestamp": timestamp,
        }
        data_bytes = json.dumps(payload).encode("utf-8")

        dispatch_results = []
        for hook_url in self.webhook_urls:
            req = urllib.request.Request(
                hook_url,
                data=data_bytes,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "API-Sentinel-Notifier/0.2.0",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    dispatch_results.append({
                        "webhook": hook_url,
                        "status_code": resp.status,
                        "success": 200 <= resp.status < 300,
                    })
            except Exception as err:
                dispatch_results.append({
                    "webhook": hook_url,
                    "status_code": getattr(err, "code", None),
                    "success": False,
                    "error": str(err),
                })

        return dispatch_results
