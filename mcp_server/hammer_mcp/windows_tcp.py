"""Bind a loopback connection's server flow to an observed Windows PID."""
import ctypes
from ctypes import wintypes
import socket
import struct


def server_pid(stream) -> int:
    api=ctypes.WinDLL('iphlpapi',use_last_error=True).GetExtendedTcpTable
    api.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),wintypes.BOOL,
                  wintypes.ULONG,ctypes.c_int,wintypes.ULONG]
    api.restype=wintypes.DWORD
    size=wintypes.DWORD()
    code=api(None,ctypes.byref(size),False,2,5,0)
    if code not in (0,122):raise OSError(code,'GetExtendedTcpTable sizing failed')
    for _ in range(3):
        if not 4<=size.value<=16*1024*1024:raise ValueError('TCP table exceeds bound')
        data=ctypes.create_string_buffer(size.value)
        code=api(data,ctypes.byref(size),False,2,5,0)
        if code==122:continue
        if code:raise OSError(code,'GetExtendedTcpTable failed')
        return match_server(data.raw[:size.value],stream.getpeername(),stream.getsockname())
    raise OSError('TCP table repeatedly changed')


def match_server(data: bytes, server: tuple, client: tuple) -> int:
    if len(data)<4:raise ValueError('truncated TCP table')
    count=struct.unpack_from('<I',data)[0]
    if count>100000 or 4+24*count>len(data):raise ValueError('invalid TCP table bounds')
    matches=[]
    for i in range(count):
        state,local_addr,local_port,remote_addr,remote_port,pid=struct.unpack_from('<6I',data,4+i*24)
        local=(socket.inet_ntoa(struct.pack('<I',local_addr)),socket.ntohs(local_port&65535))
        remote=(socket.inet_ntoa(struct.pack('<I',remote_addr)),socket.ntohs(remote_port&65535))
        if state==5 and local==server and remote==client:matches.append(pid)
    if len(matches)!=1:raise ValueError('server flow must identify exactly one PID')
    return matches[0]
