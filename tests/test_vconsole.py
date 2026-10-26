from pathlib import Path
import sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'mcp_server'))
from hammer_mcp.vconsole import HEADER,MAX_FRAME,Reader,encode_command,print_text
from hammer_mcp.windows_tcp import match_server
from hammer_mcp.vconsole import probe
from unittest.mock import patch
import struct,socket


class Fragmented:
    def __init__(self,data):self.data=data
    def settimeout(self,timeout):pass
    def recv(self,count):
        chunk=self.data[:min(count,17)];self.data=self.data[len(chunk):];return chunk


class VconsoleTests(unittest.TestCase):
    def test_long_cvar_frame_does_not_desynchronize(self):
        body=b'x'*754646
        text=bytes(28)+b'marker\0'
        data=HEADER.pack(b'CVRB',2,12+len(body),0)+body+HEADER.pack(b'PRNT',212,12+len(text),0)+text
        reader=Reader(Fragmented(data),time.monotonic()+5)
        self.assertEqual(reader.frame()['length'],754658)
        self.assertEqual(print_text(reader.frame()),'marker')
        self.assertEqual(reader.received,len(data))
    def test_bad_header_truncation_budget_and_deadline_fail_closed(self):
        for data in (HEADER.pack(b'AINF',212,11,0),HEADER.pack(b'AINF',212,MAX_FRAME+1,0)):
            with self.assertRaises(ValueError):Reader(Fragmented(data),time.monotonic()+1).frame()
        with self.assertRaises(EOFError):Reader(Fragmented(b'AIN'),time.monotonic()+1).frame()
        with self.assertRaises(ValueError):Reader(Fragmented(HEADER.pack(b'AINF',212,12,0)),time.monotonic()+1,4).frame()
        with self.assertRaises(TimeoutError):Reader(Fragmented(b''),time.monotonic()-1).frame()
    def test_command_and_print_bounds(self):
        frame=encode_command('echo marker',212)
        self.assertEqual(HEADER.unpack(frame[:12]),(b'CMND',212,len(frame),0))
        for command in ('','x\ny','x\0y','x'*5000):
            with self.assertRaises(ValueError):encode_command(command,212)
        with self.assertRaises(ValueError):print_text({'type':'PRNT','body':b'x'})
    def test_server_flow_pid_and_ambiguity(self):
        ip=struct.unpack('<I',socket.inet_aton('127.0.0.1'))[0]
        row=struct.pack('<6I',5,ip,socket.htons(29000),ip,socket.htons(32000),123)
        self.assertEqual(match_server(struct.pack('<I',1)+row,('127.0.0.1',29000),('127.0.0.1',32000)),123)
        with self.assertRaises(ValueError):match_server(struct.pack('<I',2)+row+row,('127.0.0.1',29000),('127.0.0.1',32000))
        with self.assertRaises(ValueError):match_server(struct.pack('<I',1)+row,('127.0.0.1',29000),('127.0.0.1',32001))
    def test_unsupported_handshake_and_wrong_owner_never_send_commands(self):
        class Stream(Fragmented):
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def sendall(self,data):raise AssertionError('must not send')
        with patch('hammer_mcp.vconsole.socket.create_connection',return_value=Stream(HEADER.pack(b'AINF',210,12,0))):
            report=probe()
            self.assertFalse(report['command_sent']);self.assertFalse(report['echo_verified'])
        with patch('hammer_mcp.vconsole.socket.create_connection',return_value=Stream(b'')),patch('hammer_mcp.windows_tcp.server_pid',return_value=999):
            report=probe(expected_pid=1,expected_created='identity')
            self.assertFalse(report['command_sent']);self.assertIn('identity mismatch',report['error'])
