"""Embedded multi-behavior HTTP mock server for testing and simulation."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse


class MockApiHandler(BaseHTTPRequestHandler):
    """Handles simulated endpoints with customizable latencies, status codes, and payloads."""

    def log_message(self, format: str, *args):
        # Silence default stderr logging during probes
        pass

    def _send_json_response(self, status: int, data: dict, headers: Optional[dict] = None):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/health" or path == "/":
            self._send_json_response(200, {
                "status": "healthy",
                "service": "api-sentinel-mock",
                "timestamp": time.time(),
            })
        elif path == "/delay":
            ms = float(query.get("ms", [100])[0])
            time.sleep(ms / 1000.0)
            self._send_json_response(200, {
                "status": "delayed",
                "slept_ms": ms,
            })
        elif path == "/fault":
            code = int(query.get("code", [500])[0])
            self._send_json_response(code, {
                "error": "Simulated upstream service error",
                "code": f"FAULT_{code}",
            })
        elif path == "/users":
            self._send_json_response(200, {
                "count": 2,
                "users": [
                    {"id": 1, "name": "Alice", "role": "admin"},
                    {"id": 2, "name": "Bob", "role": "engineer"},
                ],
            })
        else:
            self._send_json_response(404, {"error": "Not Found", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else ""

        try:
            parsed_json = json.loads(body) if body else {}
        except Exception:
            parsed_json = {"raw": body}

        self._send_json_response(201, {
            "received": True,
            "path": parsed.path,
            "data": parsed_json,
        })


class MockServerDaemon:
    """Convenience controller to launch and terminate the mock server in a background thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.server = HTTPServer((host, port), MockApiHandler)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"
