"""RFC 6455 compliant WebSocket client probe with zero external dependencies."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from .http_client import RawResponse


WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


def pack_client_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Pack an RFC 6455 client-to-server frame (client frames must be masked)."""
    header = bytearray()
    # FIN bit set (0x80) + opcode
    header.append(0x80 | (opcode & 0x0F))

    length = len(payload)
    mask_bit = 0x80  # Client must mask

    if length <= 125:
        header.append(mask_bit | length)
    elif length <= 65535:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", length))

    # 4-byte random masking key
    masking_key = os.urandom(4)
    header.extend(masking_key)

    # Mask payload
    masked_payload = bytearray(length)
    for i in range(length):
        masked_payload[i] = payload[i] ^ masking_key[i % 4]

    return bytes(header) + bytes(masked_payload)


def unpack_server_frame(buffer: bytes) -> Optional[Tuple[int, bytes, int]]:
    """
    Unpack a server-to-client frame (server frames are unmasked).
    Returns (opcode, payload_bytes, total_frame_length) or None if incomplete.
    """
    if len(buffer) < 2:
        return None

    byte1 = buffer[0]
    byte2 = buffer[1]
    opcode = byte1 & 0x0F
    is_masked = bool(byte2 & 0x80)
    payload_len = byte2 & 0x7F

    offset = 2
    if payload_len == 126:
        if len(buffer) < 4:
            return None
        payload_len = struct.unpack("!H", buffer[2:4])[0]
        offset = 4
    elif payload_len == 127:
        if len(buffer) < 10:
            return None
        payload_len = struct.unpack("!Q", buffer[2:10])[0]
        offset = 10

    if is_masked:
        if len(buffer) < offset + 4:
            return None
        masking_key = buffer[offset : offset + 4]
        offset += 4

    total_len = offset + payload_len
    if len(buffer) < total_len:
        return None

    raw_payload = buffer[offset:total_len]
    if is_masked:
        unmasked = bytearray(payload_len)
        for i in range(payload_len):
            unmasked[i] = raw_payload[i] ^ masking_key[i % 4]
        payload = bytes(unmasked)
    else:
        payload = raw_payload

    return opcode, payload, total_len


class WebSocketClient:
    """Performs RFC 6455 handshake and synthetic probe against ws:// and wss:// targets."""

    @classmethod
    def probe(
        cls,
        url: str,
        timeout_seconds: float = 10.0,
        headers: Optional[Dict[str, str]] = None,
        send_payload: Optional[str] = None,
    ) -> RawResponse:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("ws", "wss"):
            return RawResponse(
                status_code=None,
                latency_ms=0.0,
                error_message=f"Unsupported WebSocket scheme: '{scheme}'. Use ws:// or wss://",
            )

        is_secure = scheme == "wss"
        default_port = 443 if is_secure else 80
        host = parsed.hostname or "localhost"
        port = parsed.port or default_port
        resource_path = parsed.path or "/"
        if parsed.query:
            resource_path += f"?{parsed.query}"

        start_time = time.perf_counter()
        sock = None
        try:
            # 1. TCP Connection
            raw_sock = socket.create_connection((host, port), timeout=timeout_seconds)
            raw_sock.settimeout(timeout_seconds)

            if is_secure:
                context = ssl.create_default_context()
                sock = context.wrap_socket(raw_sock, server_hostname=host)
            else:
                sock = raw_sock

            # 2. Handshake request
            sec_key = base64.b64encode(os.urandom(16)).decode("ascii")
            req_lines = [
                f"GET {resource_path} HTTP/1.1",
                f"Host: {host}:{port}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {sec_key}",
                "Sec-WebSocket-Version: 13",
                "User-Agent: API-Sentinel-WS/0.2.0",
            ]
            if headers:
                for k, v in headers.items():
                    req_lines.append(f"{k}: {v}")
            req_lines.extend(["", ""])
            req_data = "\r\n".join(req_lines).encode("utf-8")
            sock.sendall(req_data)

            # 3. Read Handshake Response
            resp_buffer = bytearray()
            while b"\r\n\r\n" not in resp_buffer:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp_buffer.extend(chunk)

            if b"\r\n\r\n" not in resp_buffer:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return RawResponse(
                    status_code=None,
                    latency_ms=round(latency_ms, 2),
                    error_message="Incomplete handshake response from server",
                )

            header_part, _, frame_part = bytes(resp_buffer).partition(b"\r\n\r\n")
            header_lines = header_part.decode("utf-8", errors="replace").split("\r\n")
            status_line = header_lines[0] if header_lines else ""

            # Parse status code
            status_code = None
            parts = status_line.split(" ", 2)
            if len(parts) >= 2 and parts[1].isdigit():
                status_code = int(parts[1])

            resp_headers: Dict[str, str] = {}
            for line in header_lines[1:]:
                if ":" in line:
                    hk, hv = line.split(":", 1)
                    resp_headers[hk.strip().lower()] = hv.strip()

            if status_code != 101:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return RawResponse(
                    status_code=status_code,
                    latency_ms=round(latency_ms, 2),
                    headers=resp_headers,
                    body_text=header_part.decode("utf-8", errors="replace"),
                    error_message=f"Handshake failed with HTTP {status_code}: {status_line}",
                )

            # Validate Sec-WebSocket-Accept
            expected_accept = base64.b64encode(
                hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
            ).decode("ascii")
            server_accept = resp_headers.get("sec-websocket-accept", "")

            if server_accept != expected_accept:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return RawResponse(
                    status_code=101,
                    latency_ms=round(latency_ms, 2),
                    headers=resp_headers,
                    error_message=f"Invalid Sec-WebSocket-Accept token. Expected '{expected_accept}', got '{server_accept}'",
                )

            # 4. Exchange Ping/Pong or Text Frame
            body_text = "Handshake verified"
            if send_payload:
                sock.sendall(pack_client_frame(OPCODE_TEXT, send_payload.encode("utf-8")))
            else:
                sock.sendall(pack_client_frame(OPCODE_PING, b"sentinel-ping"))

            # Attempt to read frame reply
            incoming_buffer = bytearray(frame_part)
            read_deadline = time.perf_counter() + min(2.0, timeout_seconds)
            while time.perf_counter() < read_deadline:
                frame_info = unpack_server_frame(bytes(incoming_buffer))
                if frame_info:
                    op, payload, consumed = frame_info
                    if op == OPCODE_PONG:
                        body_text = f"PONG received: {payload.decode('utf-8', errors='replace')}"
                    elif op == OPCODE_TEXT:
                        body_text = payload.decode("utf-8", errors="replace")
                    break
                try:
                    sock.settimeout(0.5)
                    chunk = sock.recv(2048)
                    if not chunk:
                        break
                    incoming_buffer.extend(chunk)
                except (socket.timeout, TimeoutError):
                    break

            # 5. Clean Close
            try:
                sock.sendall(pack_client_frame(OPCODE_CLOSE, struct.pack("!H", 1000)))
            except Exception:
                pass

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return RawResponse(
                status_code=101,
                latency_ms=round(latency_ms, 2),
                headers=resp_headers,
                body_text=body_text,
                size_bytes=len(resp_buffer) + len(incoming_buffer),
                error_message=None,
            )

        except (socket.timeout, TimeoutError):
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return RawResponse(
                status_code=None,
                latency_ms=round(latency_ms, 2),
                error_message=f"WebSocket connection timed out after {timeout_seconds}s",
            )
        except Exception as err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return RawResponse(
                status_code=None,
                latency_ms=round(latency_ms, 2),
                error_message=f"WebSocket error: {err}",
            )
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
