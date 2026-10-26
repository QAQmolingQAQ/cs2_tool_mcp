import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp_server"))
from hammer_mcp import protocol
from hammer_mcp.transport import Cs2Pipe


class FakePipe(Cs2Pipe):
    def __init__(self, fail=False):
        super().__init__()
        self.writes = []
        self.opens = 0
        self.buffer = b""
        self.fail = fail

    def _open(self):
        self.opens += 1
        self._handle = 1
        self._on_reset()

    def _authorize(self, method, params):
        # Protocol tests simulate an already-attested connection. Real gate
        # dispatch/rejection is exercised separately in test_versioning.
        pass

    def _close(self):
        self._handle = None
        self._on_reset()

    def _write_all(self, data):
        self.writes.append(data)
        request = json.loads(data[16:])
        body = json.dumps({"id": request["id"], "result": {"status": "ok"}}).encode()
        self.buffer = struct.pack("<IIII", protocol.MSG_MAGIC, 1, len(body), 0) + body

    def _read_exact(self, size):
        if self.fail:
            raise OSError("peer closed after mutation")
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result


class ProtocolTests(unittest.TestCase):
    def test_round_trip_reuses_connection_with_distinct_ids(self):
        pipe = FakePipe()
        for _ in range(2):
            self.assertEqual(pipe.call("ping")["result"], {"status": "ok"})
        self.assertEqual(pipe.opens, 1)
        self.assertNotEqual(json.loads(pipe.writes[0][16:])["id"], json.loads(pipe.writes[1][16:])["id"])

    def test_mutation_is_never_replayed_after_lost_response(self):
        pipe = FakePipe(fail=True)
        with self.assertRaisesRegex(OSError, "not replayed"):
            pipe.call("call_function", {"address": "hammer.dll+0x100"})
        self.assertEqual(len(pipe.writes), 1)
        self.assertIsNone(pipe._handle)
        pipe.fail = False
        pipe.call("ping")
        self.assertEqual(pipe.opens, 2)
        self.assertEqual(json.loads(pipe.writes[-1][16:])["method"], "ping")

    def test_invalid_headers_are_rejected_before_body_read(self):
        for fields in ((0, 1, 20, 0), (protocol.MSG_MAGIC, 2, 20, 0),
                       (protocol.MSG_MAGIC, 1, 0, 0),
                       (protocol.MSG_MAGIC, 1, protocol.MAX_PAYLOAD_SIZE + 1, 0),
                       (protocol.MSG_MAGIC, 1, 20, 1)):
            with self.subTest(fields=fields), self.assertRaises(protocol.ProtocolError):
                protocol.response_length(struct.pack("<IIII", *fields))

    def test_response_correlation_and_encoding(self):
        for body in (b'{"id":2,"result":0}', b'[]', b'{"id":1}', b'\xff', b'{'):
            with self.subTest(body=body), self.assertRaises(protocol.ProtocolError):
                protocol.decode_response(body, 1)
        self.assertEqual(protocol.decode_response(b'{"id":1,"error":"failed"}', 1)["error"], "failed")

    def test_invalid_request_never_opens_connection(self):
        pipe = FakePipe()
        with self.assertRaises(ValueError):
            pipe.call("write_value", {"value": float("nan")})
        self.assertEqual(pipe.opens, 0)
        self.assertEqual(pipe.writes, [])


if __name__ == "__main__":
    unittest.main()
