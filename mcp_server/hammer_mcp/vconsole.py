"""Bounded VConsole2 framing, distinct from newline-based text netconsole.

Wire header verified against local AINF/CHAN/CVRB/PRNT captures, including a
754658-byte CVRB frame: fourcc, uint16 version, uint32 total length, uint16 handle.
All integers are network byte order. No scanning/resynchronization or retries.
"""
import socket
import struct
import time
from uuid import uuid4

HEADER = struct.Struct('>4sHIH')
MAX_FRAME = 4*1024*1024
MAX_OBSERVATION_FRAMES = 100000  # initial console replay can exceed 10k; byte/deadline limits still apply


def encode_command(command: str, version: int) -> bytes:
    if not isinstance(command, str) or not command or any(c in command for c in '\0\r\n'):
        raise ValueError('expected one nonempty console command')
    body = command.encode('utf-8')+b'\0'
    if len(body)>4096 or not 0<=version<=65535:
        raise ValueError('command/version exceeds bound')
    return HEADER.pack(b'CMND',version,HEADER.size+len(body),0)+body


class Reader:
    def __init__(self, stream, deadline: float, byte_limit: int = 16*1024*1024):
        self.stream,self.deadline,self.byte_limit = stream,deadline,byte_limit
        self.received=0

    def exact(self, count: int) -> bytes:
        chunks=[]
        while count:
            remaining=self.deadline-time.monotonic()
            if remaining<=0:
                raise TimeoutError('VConsole observation deadline exceeded; no replay')
            self.stream.settimeout(remaining)
            data=self.stream.recv(count)
            if not data:raise EOFError('VConsole stream closed')
            self.received+=len(data)
            if self.received>self.byte_limit:raise ValueError('VConsole byte budget exceeded')
            chunks.append(data);count-=len(data)
        return b''.join(chunks)

    def frame(self) -> dict:
        tag,version,length,handle=HEADER.unpack(self.exact(HEADER.size))
        if not all(65<=c<=90 or 48<=c<=57 for c in tag) or not HEADER.size<=length<=MAX_FRAME:
            raise ValueError('invalid VConsole header; no resynchronization')
        return {'type':tag.decode('ascii'),'version':version,'handle':handle,
                'body':self.exact(length-HEADER.size),'length':length}


def print_text(frame: dict) -> str | None:
    if frame['type']!='PRNT':return None
    body=frame['body']
    if len(body)<28:raise ValueError('truncated PRNT body')
    text=body[28:]
    if b'\0' not in text:raise ValueError('PRNT lacks string terminator')
    return text.split(b'\0',1)[0].decode('utf-8',errors='replace')


def probe(port: int = 29000, timeout: float = 5, expected_pid: int | None = None,
          expected_created: str | None = None) -> dict:
    """Loopback AINF + unique echo. No map/gameplay completion inference."""
    if isinstance(port,bool) or not isinstance(port,int) or not 1<=port<=65535:
        raise ValueError('invalid port')
    if not 0<timeout<=10:raise ValueError('timeout must be in (0,10]')
    marker='CS2_MCP_ECHO_'+uuid4().hex
    report={'protocol':'unverified','port':port,'echo_verified':False,
            'command_sent':False,'marker':marker,'runtime_map_verified':False}
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=timeout) as stream:
            if expected_pid is not None:
                from .windows_tcp import server_pid
                from .build_process import process_identity
                if server_pid(stream)!=expected_pid or process_identity(expected_pid)!=expected_created:
                    raise ValueError('VConsole server flow/process identity mismatch')
                report.update(server_pid=expected_pid,server_created=expected_created)
            reader=Reader(stream,time.monotonic()+timeout)
            first=reader.frame()
            if first['type']!='AINF' or first['version']!=212:
                raise ValueError('unsupported VConsole handshake/version')
            report.update(protocol='vconsole2',version=first['version'],handshake_verified=True)
            report['dispatch_started']=True
            stream.sendall(encode_command('echo '+marker,first['version']))
            report['command_sent']=True
            counts={first['type']:1};largest=first['length']
            for _ in range(MAX_OBSERVATION_FRAMES):
                frame=reader.frame()
                counts[frame['type']]=counts.get(frame['type'],0)+1
                largest=max(largest,frame['length'])
                text=print_text(frame)
                if text is not None and text.strip()==marker:
                    report['echo_verified']=True
                    break
            report.update(frame_types=counts,largest_frame=largest,received_bytes=reader.received)
    except (OSError,EOFError,ValueError) as exc:
        report['error']=str(exc)
        report['outcome']='unknown_do_not_replay' if report.get('dispatch_started') else 'no_command_sent'
    return report


def cs2_console_probe(port: int = 29000) -> dict:
    """Verify local VConsole2 AINF and unique echo against the active bridge PID.

    Sends only a generated echo. Does not send text commands to unknown protocols,
    retry commands, load maps, or treat TCP/echo success as runtime-map validation.
    """
    try:
        from .session import get_session
        from .versioning import inspect_live
        from .build_process import process_identity
        live=inspect_live(get_session().pipe)
        pid,created=live['live']['pid'],live['live']['created']
        result=probe(port,expected_pid=pid,expected_created=created)
        if process_identity(pid)!=created:
            result.update(echo_verified=False,error='process identity changed during probe')
        return {'ok':result['echo_verified'],**result,'scope':'bridge_bound_loopback_diagnostic'}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'ok':False,'echo_verified':False,'runtime_map_verified':False,'error':str(exc)}
