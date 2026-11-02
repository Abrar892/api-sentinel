"""Zero-dependency HTTP client with high-resolution latency timing."""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class RawResponse:
    """Raw response details captured from the HTTP network request."""
    status_code: Optional[int]
    latency_ms: float
    headers: Dict[str, str] = field(default_factory=dict)
    body_text: str = ""
    size_bytes: int = 0
    error_message: Optional[str] = None


class HttpClient:
    """Robust HTTP probe execution client using Python standard library."""

    DEFAULT_USER_AGENT = "API-Sentinel/0.1.0 (+https://github.com/Abrar892/api-sentinel)"

    @classmethod
    def execute_request(
        cls,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ) -> RawResponse:
        """
        Execute an HTTP request and measure latency with high precision.
        Captures status codes and bodies even on HTTP 4xx/5xx responses.
        """
        req_headers = {"User-Agent": cls.DEFAULT_USER_AGENT}
        if headers:
            req_headers.update(headers)

        encoded_body = body.encode("utf-8") if body is not None else None

        req = urllib.request.Request(
            url=url,
            data=encoded_body,
            headers=req_headers,
            method=method.upper(),
        )

        start_time = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                raw_bytes = response.read()
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                resp_headers = {k.lower(): v for k, v in response.headers.items()}
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    body_text = raw_bytes.decode(charset, errors="replace")
                except Exception:
                    body_text = raw_bytes.decode("utf-8", errors="replace")

                return RawResponse(
                    status_code=response.status,
                    latency_ms=round(latency_ms, 2),
                    headers=resp_headers,
                    body_text=body_text,
                    size_bytes=len(raw_bytes),
                    error_message=None,
                )

        except urllib.error.HTTPError as http_err:
            # HTTP errors (4xx, 5xx) are valid responses to probe and evaluate
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            resp_headers = {k.lower(): v for k, v in http_err.headers.items()} if http_err.headers else {}
            try:
                raw_bytes = http_err.read()
                body_text = raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                raw_bytes = b""
                body_text = ""

            return RawResponse(
                status_code=http_err.code,
                latency_ms=round(latency_ms, 2),
                headers=resp_headers,
                body_text=body_text,
                size_bytes=len(raw_bytes),
                error_message=f"HTTP {http_err.code}: {http_err.reason}",
            )

        except urllib.error.URLError as url_err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            reason = str(url_err.reason) if hasattr(url_err, "reason") else str(url_err)
            return RawResponse(
                status_code=None,
                latency_ms=round(latency_ms, 2),
                headers={},
                body_text="",
                size_bytes=0,
                error_message=f"Network URLError: {reason}",
            )

        except TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return RawResponse(
                status_code=None,
                latency_ms=round(latency_ms, 2),
                headers={},
                body_text="",
                size_bytes=0,
                error_message=f"Request timed out after {timeout_seconds}s",
            )

        except Exception as err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return RawResponse(
                status_code=None,
                latency_ms=round(latency_ms, 2),
                headers={},
                body_text="",
                size_bytes=0,
                error_message=f"Unexpected client exception: {err}",
            )
