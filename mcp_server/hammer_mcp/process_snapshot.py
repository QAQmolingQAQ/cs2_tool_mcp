"""Read loaded module paths and PE identities using Windows APIs, without RVAs."""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import struct
import time
from .build_process import process_identity
from .project import sha256


WATCHED = frozenset(('cs2.exe', 'cs2_tool.dll', 'hammer.dll', 'pet.dll', 'particles.dll',
    'met.dll', 'modeldoc_editor.dll', 'scenesystem.dll', 'tier0.dll', 'qt5core.dll',
    'qt5gui.dll', 'qt5widgets.dll', 'datamodel.dll', 'toolframework2.dll'))


class _Module(c.Structure):
    _fields_ = [(name, w.DWORD) for name in ('size', 'id', 'pid', 'global_count', 'process_count')] + [
        ('base', c.c_void_p), ('image_size', w.DWORD), ('module', w.HMODULE),
        ('name', w.WCHAR * 256), ('path', w.WCHAR * 260)]


def pe_identity(data: bytes) -> dict:
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('invalid DOS header')
    position = struct.unpack_from('<I', data, 60)[0]
    if position + 84 > len(data) or data[position:position + 4] != b'PE\0\0':
        raise ValueError('invalid PE header')
    return {'timestamp': struct.unpack_from('<I', data, position + 8)[0],
            'image_size': struct.unpack_from('<I', data, position + 80)[0]}


def disk_identity(path: Path) -> dict:
    before = path.stat()
    digest = sha256(path)
    with path.open('rb') as stream:
        pe = pe_identity(stream.read(4096))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f'file changed during fingerprint: {path}')
    return {'path': str(path), 'sha256': digest, 'file_size': after.st_size, **pe}


def pipe_snapshot(pipe) -> dict:
    if os.name != 'nt' or pipe._handle is None:
        raise OSError('a live Windows pipe connection is required')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    signatures = (
        ('GetNamedPipeServerProcessId', [w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        ('CreateToolhelp32Snapshot', [w.DWORD, w.DWORD], w.HANDLE),
        ('Module32FirstW', [w.HANDLE, c.POINTER(_Module)], w.BOOL),
        ('Module32NextW', [w.HANDLE, c.POINTER(_Module)], w.BOOL),
        ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ('ReadProcessMemory', [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)], w.BOOL),
        ('CloseHandle', [w.HANDLE], w.BOOL),
    )
    for name, args, result in signatures:
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    pid = w.DWORD()
    if not kernel.GetNamedPipeServerProcessId(pipe._handle, c.byref(pid)):
        raise c.WinError(c.get_last_error())
    created = process_identity(pid.value)
    if created is None:
        raise OSError('pipe server process has exited')
    process = kernel.OpenProcess(0x400 | 0x10, False, pid.value)
    if not process:
        raise c.WinError(c.get_last_error())
    snapshot = None
    try:
        for _ in range(3):
            snapshot = kernel.CreateToolhelp32Snapshot(0x8 | 0x10, pid.value)
            if snapshot != c.c_void_p(-1).value:
                break
            if c.get_last_error() != 24:
                raise c.WinError(c.get_last_error())
            time.sleep(0.01)
        else:
            raise OSError('module snapshot repeatedly changed')
        item = _Module()
        item.size = c.sizeof(item)
        if not kernel.Module32FirstW(snapshot, c.byref(item)):
            raise c.WinError(c.get_last_error())
        modules = {}
        while True:
            name = item.name.casefold()
            if name in WATCHED:
                if name in modules:
                    raise ValueError(f'duplicate loaded module: {name}')
                buffer = c.create_string_buffer(4096)
                read = c.c_size_t()
                if not kernel.ReadProcessMemory(process, item.base, buffer, len(buffer), c.byref(read)):
                    raise c.WinError(c.get_last_error())
                disk = disk_identity(Path(item.path))
                loaded = pe_identity(buffer.raw[:read.value])
                modules[name] = {**disk, 'base': hex(item.base), 'loaded': loaded,
                                 'loaded_matches_disk_headers': loaded == {key: disk[key] for key in loaded}}
            if not kernel.Module32NextW(snapshot, c.byref(item)):
                if c.get_last_error() != 18:
                    raise c.WinError(c.get_last_error())
                break
        if process_identity(pid.value) != created:
            raise OSError('pipe process identity changed while inspecting modules')
        return {'pid': pid.value, 'created': created, 'modules': modules,
                'hash_evidence': 'disk SHA-256 at loaded module path; loaded PE timestamp/size compared, not a memory-image hash'}
    finally:
        if snapshot and snapshot != c.c_void_p(-1).value:
            kernel.CloseHandle(snapshot)
        kernel.CloseHandle(process)
