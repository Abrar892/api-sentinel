"""Tests for RFC 6455 WebSocket client probing and framing."""

import base64
import hashlib
import socket
import threading
import time
import unittest

from api_sentinel.ws_client import (
    OPCODE_CLOSE,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    WS_GUID,
    WebSocketClient,
    pack_client_frame,
    unpack_server_frame,
)


def mock_ws_server_handler(conn: socket.socket):
    """Simple mock server responding to RFC 6455 WebSocket handshake and ping/text."""
    try:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = conn.recv(1024)
            if not chunk:
                return
            buffer.extend(chunk)

        # Parse Sec-WebSocket-Key
        headers_str = buffer.decode("utf-8", errors="replace")
        sec_key = None
        for line in headers_str.split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                sec_key = line.split(":", 1)[1].strip()
                break

        if not sec_key:
            conn.close()
            return

        accept_val = base64.b64encode(
            hashlib.sha1((sec_key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
        )
        conn.sendall(response.encode("utf-8"))

        # Read client frame (ping or text)
        frame_buf = bytearray()
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break
            frame_buf.extend(chunk)
            frame_info = unpack_server_frame(bytes(frame_buf))
            if frame_info:
                opcode, payload, consumed = frame_info
                if opcode == OPCODE_PING:
                    # Echo pong (unmasked)
                    pong_frame = bytearray([0x80 | OPCODE_PONG, len(payload)]) + payload
                    conn.sendall(bytes(pong_frame))
                elif opcode == OPCODE_TEXT:
                    reply = b"ECHO:" + payload
                    text_frame = bytearray([0x80 | OPCODE_TEXT, len(reply)]) + reply
                    conn.sendall(bytes(text_frame))
                elif opcode == OPCODE_CLOSE:
                    break
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


class TestWebSocket(unittest.TestCase):
    def test_frame_pack_and_unpack(self):
        # Pack client frame (masked)
        payload = b"Hello, Sentinel!"
        client_frame = pack_client_frame(OPCODE_TEXT, payload)
        self.assertGreater(len(client_frame), len(payload))
        # Client frame must have MASK bit set
        self.assertTrue(bool(client_frame[1] & 0x80))

        # Unpack as masked frame
        res = unpack_server_frame(client_frame)
        self.assertIsNotNone(res)
        op, unpacked_payload, consumed = res
        self.assertEqual(op, OPCODE_TEXT)
        self.assertEqual(unpacked_payload, payload)

    def test_rfc6455_accept_token_derivation(self):
        # Known test vector from RFC 6455 Section 1.3
        test_key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected_accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        computed_accept = base64.b64encode(
            hashlib.sha1((test_key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        self.assertEqual(computed_accept, expected_accept)

    def test_websocket_client_probe_live(self):
        # Start ephemeral loopback TCP server
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.bind(("127.0.0.1", 0))
        srv_sock.listen(1)
        port = srv_sock.getsockname()[1]

        def serve():
            conn, _ = srv_sock.accept()
            mock_ws_server_handler(conn)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        try:
            # Probe with ping
            ws_url = f"ws://127.0.0.1:{port}/feed"
            resp = WebSocketClient.probe(ws_url, timeout_seconds=3.0)
            self.assertEqual(resp.status_code, 101)
            self.assertIn("PONG", resp.body_text)
            self.assertGreater(resp.latency_ms, 0.0)
            self.assertIsNone(resp.error_message)
        finally:
            srv_sock.close()


if __name__ == "__main__":
    unittest.main()
