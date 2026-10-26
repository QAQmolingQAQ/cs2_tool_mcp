"""Windows compiler process tree ownership, with PID creation-time identities."""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import os
import subprocess


if os.name == 'nt':
    kernel = c.WinDLL('kernel32', use_last_error=True)
    for name, args, result in (
        ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        ('CloseHandle', [w.HANDLE], w.BOOL),
        ('GetProcessTimes', [w.HANDLE, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p], w.BOOL),
        ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
        ('GetExitCodeProcess', [w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        ('CreateJobObjectW', [c.c_void_p, w.LPCWSTR], w.HANDLE),
        ('SetInformationJobObject', [w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        ('QueryInformationJobObject', [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
        ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
        ('TerminateProcess', [w.HANDLE, w.UINT], w.BOOL),
        ('ResumeThread', [w.HANDLE], w.DWORD),
        ('InitializeProcThreadAttributeList', [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
        ('UpdateProcThreadAttribute', [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p], w.BOOL),
        ('DeleteProcThreadAttributeList', [c.c_void_p], None),
        ('CreateProcessW', [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL,
                            w.DWORD, c.c_void_p, w.LPCWSTR, c.c_void_p, c.c_void_p], w.BOOL),
    ):
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result


def _check(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


def process_identity(pid: int) -> str | None:
    """None only when PID is absent/terminated; access errors remain errors."""
    if os.name != 'nt':
        raise OSError('build process management currently requires Windows')
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        error = c.get_last_error()
        if error == 87:
            return None
        raise c.WinError(error)
    try:
        status = kernel.WaitForSingleObject(handle, 0)
        if status == 0:
            return None
        if status != 258:
            raise c.WinError(c.get_last_error())
        times = [c.c_uint64() for _ in range(4)]
        _check(kernel.GetProcessTimes(handle, *(c.byref(item) for item in times)))
        return str(times[0].value)
    finally:
        kernel.CloseHandle(handle)


class _BasicLimit(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                ('min_working_set', c.c_size_t), ('max_working_set', c.c_size_t),
                ('active_limit', w.DWORD), ('affinity', c.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]


class _IO(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class _ExtendedLimit(c.Structure):
    _fields_ = [('basic', _BasicLimit), ('io', _IO), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class _Accounting(c.Structure):
    _fields_ = [(name, c.c_int64) for name in ('user', 'kernel', 'period_user', 'period_kernel')] + [
        (name, w.DWORD) for name in ('faults', 'total', 'active', 'terminated')]


class _Startup(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                ('chars_x', w.DWORD), ('chars_y', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', c.c_void_p),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class _StartupEx(c.Structure):
    _fields_ = [('startup', _Startup), ('attributes', c.c_void_p)]


class _ProcessInfo(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


def spawn_worker(command: list[str], cwd: str) -> dict:
    """Launch a desktop worker outside the MCP client's kill-on-close job.

    The desktop shell supplies process parent/job inheritance. Token and explicit
    command remain the caller's; no scheduled task, service or autostart is created.
    No caller stdio handles are inherited from the shell.
    """
    if os.name != 'nt':
        raise OSError('build workers currently require Windows')
    user = c.WinDLL('user32', use_last_error=True)
    user.GetShellWindow.argtypes, user.GetShellWindow.restype = [], w.HWND
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.GetWindowThreadProcessId.restype = w.DWORD
    window = user.GetShellWindow()
    if not window:
        raise OSError('desktop shell unavailable; cannot launch an independent build worker')
    shell_pid = w.DWORD()
    _check(user.GetWindowThreadProcessId(window, c.byref(shell_pid)))
    parent = _check(kernel.OpenProcess(0x80, False, shell_pid.value))
    attributes = None
    info = _ProcessInfo()
    try:
        size = c.c_size_t()
        kernel.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
        buffer = c.create_string_buffer(size.value)
        _check(kernel.InitializeProcThreadAttributeList(buffer, 1, 0, c.byref(size)))
        attributes = buffer
        handle = w.HANDLE(parent)
        _check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020000, c.byref(handle), c.sizeof(handle), None, None))
        startup = _StartupEx()
        startup.startup.cb = c.sizeof(startup)
        startup.attributes = c.cast(attributes, c.c_void_p)
        _check(kernel.CreateProcessW(command[0], c.create_unicode_buffer(subprocess.list2cmdline(command)),
                                    None, None, False, 0x08000000 | 0x80000, None, cwd,
                                    c.byref(startup), c.byref(info)))
        return {'pid': info.pid, 'created': process_identity(info.pid), 'parent': 'desktop_shell'}
    finally:
        if info.thread:
            kernel.CloseHandle(info.thread)
        if info.process:
            kernel.CloseHandle(info.process)
        if attributes is not None:
            kernel.DeleteProcThreadAttributeList(attributes)
        kernel.CloseHandle(parent)


class CompilerProcess:
    """Assign the kill-on-close Job Object atomically at process creation, then run.

    Descendants cannot escape before assignment, and worker death closes the job.
    """
    def __init__(self, command: list[str], cwd: str, env: dict, log):
        if os.name != 'nt':
            raise OSError('compiler jobs currently require Windows')
        import msvcrt
        self.job = _check(kernel.CreateJobObjectW(None, None))
        self.handle = None
        process = _ProcessInfo()
        attributes = None
        try:
            limits = _ExtendedLimit()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _check(kernel.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)))
            startup_ex = _StartupEx()
            startup = startup_ex.startup
            startup.cb, startup.flags = c.sizeof(startup_ex), 0x100
            size = c.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
            buffer = c.create_string_buffer(size.value)
            _check(kernel.InitializeProcThreadAttributeList(buffer, 1, 0, c.byref(size)))
            attributes = buffer
            job_list = (w.HANDLE * 1)(self.job)
            _check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x0002000D, job_list, c.sizeof(job_list), None, None))
            startup_ex.attributes = c.cast(attributes, c.c_void_p)
            log_handle = msvcrt.get_osfhandle(log.fileno())
            with open(os.devnull, 'rb') as null:
                null_handle = msvcrt.get_osfhandle(null.fileno())
                os.set_handle_inheritable(log_handle, True)
                os.set_handle_inheritable(null_handle, True)
                try:
                    startup.stdin = null_handle
                    startup.stdout = startup.stderr = log_handle
                    environment = c.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items(), key=lambda pair: pair[0].upper())) + '\0\0')
                    _check(kernel.CreateProcessW(command[0], c.create_unicode_buffer(subprocess.list2cmdline(command)),
                        None, None, True, 0x08000000 | 0x400 | 0x4 | 0x80000, environment, cwd,
                        c.byref(startup_ex), c.byref(process)))
                finally:
                    os.set_handle_inheritable(log_handle, False)
                    os.set_handle_inheritable(null_handle, False)
            self.handle, self.pid = process.process, process.pid
            if kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
                raise c.WinError(c.get_last_error())
            self.identity = process_identity(self.pid)
        except BaseException:
            if process.process:
                kernel.TerminateProcess(process.process, 1)
                kernel.WaitForSingleObject(process.process, 5000)
            self.close()
            raise
        finally:
            if attributes is not None:
                kernel.DeleteProcThreadAttributeList(attributes)
            if process.thread:
                kernel.CloseHandle(process.thread)

    def poll(self) -> int | None:
        status = kernel.WaitForSingleObject(self.handle, 0)
        if status == 258:
            return None
        if status != 0:
            raise c.WinError(c.get_last_error())
        code = w.DWORD()
        _check(kernel.GetExitCodeProcess(self.handle, c.byref(code)))
        return code.value

    def active_count(self) -> int:
        info = _Accounting()
        _check(kernel.QueryInformationJobObject(self.job, 1, c.byref(info), c.sizeof(info), None))
        return info.active

    def terminate(self):
        _check(kernel.TerminateJobObject(self.job, 1223))

    def close(self):
        if self.job:
            kernel.CloseHandle(self.job)
            self.job = None
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None
