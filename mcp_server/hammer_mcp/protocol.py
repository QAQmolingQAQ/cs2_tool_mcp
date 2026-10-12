"""Framing contract shared with injected_dll/protocol.h; no OS dependencies."""
from __future__ import annotations
import json
import struct
from typing import Any

MSG_MAGIC = 0x43533254
MSG_VERSION = 1
HEADER_SIZE = 16
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024

class ProtocolError(OSError):
    """The peer returned an invalid bridge frame."""

def encode_request(request_id: int, method: str, params: dict[str, Any] | None) -> bytes:
    request = {"id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    payload = json.dumps(request, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError("Request exceeds bridge frame limit")
    return struct.pack("<IIII", MSG_MAGIC, MSG_VERSION, len(payload), 0) + payload

def response_length(header: bytes) -> int:
    if len(header) != HEADER_SIZE:
        raise ProtocolError("Incomplete bridge header")
    magic, version, length, reserved = struct.unpack("<IIII", header)
    if magic != MSG_MAGIC or version != MSG_VERSION or reserved != 0:
        raise ProtocolError("Invalid bridge magic, version or reserved field")
    if not 0 < length <= MAX_PAYLOAD_SIZE:
        raise ProtocolError("Invalid bridge payload length")
    return length

def decode_response(body: bytes, request_id: int) -> dict[str, Any]:
    try:
        response = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError("Invalid bridge JSON") from exc
    if not isinstance(response, dict) or response.get("id") != request_id:
        raise ProtocolError("Bridge response ID mismatch")
    if "result" not in response and "error" not in response:
        raise ProtocolError("Bridge response has no result or error")
    return response
