"""Identify and close only an existing Windows installation owned by this user.

The Windows boundary is loaded on demand. PID reuse is guarded by creation
time, executable path, token user and session checks before any termination.
"""

import ctypes
import logging
import ntpath
import os
import socket
import struct
import time
from ctypes import wintypes
from dataclasses import dataclass


class InstallationProcessError(RuntimeError):
    """An existing application could not safely be inspected or closed."""


@dataclass(frozen=True)
class _Process:
    pid: int
    created: int
    path: str
    user: bytes
    session: int


@dataclass(frozen=True)
class _SnapshotEntry:
    pid: int
    parent_pid: int
    name: str


def _canonical_path(path):
    value = ntpath.abspath(os.fspath(path))
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


class _TcpRow(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        "state", "local_address", "local_port", "remote_address",
        "remote_port", "pid",
    )]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class _WindowsProcesses:
    """Small, mockable Win32 boundary. Every opened handle is closed here."""

    _QUERY = 0x1000
    _SYNCHRONIZE = 0x100000

    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.ip = ctypes.WinDLL("iphlpapi", use_last_error=True)
        declarations = (
            (self.kernel, "CreateToolhelp32Snapshot", [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel, "Process32FirstW", [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)], wintypes.BOOL),
            (self.kernel, "Process32NextW", [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)], wintypes.BOOL),
            (self.kernel, "OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, "QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.kernel, "GetProcessTimes", [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
            (self.kernel, "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.kernel, "TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            (self.security, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
            (self.security, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.security, "GetLengthSid", [ctypes.c_void_p], wintypes.DWORD),
            (self.ip, "GetExtendedTcpTable", [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG], wintypes.DWORD),
        )
        for library, name, args, result in declarations:
            function = getattr(library, name)
            function.argtypes = args
            function.restype = result

    @staticmethod
    def _error(operation, pid=None):
        code = ctypes.get_last_error()
        label = f"{operation} for PID {pid}" if pid is not None else operation
        return OSError(code, f"{label}: {ctypes.FormatError(code).strip()}")

    def snapshot(self):
        handle = self.kernel.CreateToolhelp32Snapshot(0x2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise self._error("Read the process list")
        try:
            entry = _ProcessEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            rows = {}
            while found:
                rows[entry.th32ProcessID] = _SnapshotEntry(
                    entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile,
                )
                found = self.kernel.Process32NextW(handle, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise self._error("Read the process list")
            return rows
        finally:
            self.kernel.CloseHandle(handle)

    def _token_information(self, token, kind):
        needed = wintypes.DWORD()
        self.security.GetTokenInformation(token, kind, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise self._error("Read the application owner")
        buffer = ctypes.create_string_buffer(needed.value)
        if not self.security.GetTokenInformation(token, kind, buffer, len(buffer), ctypes.byref(needed)):
            raise self._error("Read the application owner")
        return buffer

    def _identity_from_handle(self, handle, pid):
        state = self.kernel.WaitForSingleObject(handle, 0)
        if state == 0:  # The process has exited, even if its PID is not reaped yet.
            return None
        if state != 258:  # WAIT_TIMEOUT means still running.
            raise self._error("Check the application state", pid)
        capacity = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(capacity.value)
        if not self.kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(capacity)):
            raise self._error("Read the application path", pid)
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel_time), ctypes.byref(user_time),
        ):
            raise self._error("Read the application start time", pid)
        token = wintypes.HANDLE()
        if not self.security.OpenProcessToken(handle, 0x8, ctypes.byref(token)):
            raise self._error("Read the application owner", pid)
        try:
            owner = self._token_information(token, 1)  # TokenUser
            sid = _SidAndAttributes.from_buffer(owner).sid
            size = self.security.GetLengthSid(sid)
            if not size:
                raise self._error("Read the application owner", pid)
            user = ctypes.string_at(sid, size)
            session_data = self._token_information(token, 12)  # TokenSessionId
            session = wintypes.DWORD.from_buffer(session_data).value
        finally:
            self.kernel.CloseHandle(token)
        return _Process(
            pid, (created.dwHighDateTime << 32) | created.dwLowDateTime,
            _canonical_path(image.value), user, session,
        )

    def identity(self, pid):
        handle = self.kernel.OpenProcess(self._QUERY | self._SYNCHRONIZE, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID ended.
                return None
            raise self._error("Inspect Astra Downloader", pid)
        try:
            try:
                return self._identity_from_handle(handle, pid)
            except OSError:
                if self.kernel.WaitForSingleObject(handle, 0) == 0:
                    return None
                raise
        finally:
            self.kernel.CloseHandle(handle)

    def listeners(self, port):
        needed = wintypes.DWORD()
        code = self.ip.GetExtendedTcpTable(None, ctypes.byref(needed), False, 2, 3, 0)
        for _attempt in range(3):
            if code not in (0, 122):
                raise OSError(code, "Read the local application control listener")
            buffer = ctypes.create_string_buffer(max(4, needed.value))
            code = self.ip.GetExtendedTcpTable(buffer, ctypes.byref(needed), False, 2, 3, 0)
            if code == 122:  # The table grew between calls.
                continue
            if code:
                raise OSError(code, "Read the local application control listener")
            count = wintypes.DWORD.from_buffer(buffer).value
            offset = ctypes.sizeof(wintypes.DWORD)
            if count > (len(buffer) - offset) // ctypes.sizeof(_TcpRow):
                raise OSError("The local TCP ownership table was incomplete")
            owners = set()
            for index in range(count):
                row = _TcpRow.from_buffer(buffer, offset + index * ctypes.sizeof(_TcpRow))
                address = socket.inet_ntoa(struct.pack("<I", row.local_address))
                if address == "127.0.0.1" and socket.ntohs(row.local_port & 0xffff) == port:
                    owners.add(row.pid)
            return owners
        raise OSError("The local TCP ownership table kept changing; retry the installation")

    def terminate(self, expected):
        handle = self.kernel.OpenProcess(self._QUERY | self._SYNCHRONIZE | 0x1, False, expected.pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise self._error("Close Astra Downloader", expected.pid)
        try:
            try:
                if self._identity_from_handle(handle, expected.pid) != expected:
                    return
            except OSError:
                if self.kernel.WaitForSingleObject(handle, 0) == 0:
                    return
                raise
            # It may have exited naturally after the identity check.
            if (not self.kernel.TerminateProcess(handle, 1)
                    and self.kernel.WaitForSingleObject(handle, 0) != 0):
                raise self._error("Close Astra Downloader", expected.pid)
        finally:
            self.kernel.CloseHandle(handle)


def _same_owner(process, installer):
    return process is not None and (process.user, process.session) == (installer.user, installer.session)


_HELPER_NAMES = frozenset({
    "yt-dlp.exe", "ffmpeg.exe", "ffprobe.exe", "deno.exe", "node.exe",
    "quickjs.exe", "qjs.exe", "whisper-cli.exe", "python.exe", "pythonw.exe",
})


def _capture_descendants(backend, captured):
    """Retain exact helper identities even if their application exits first.

    Each value records its verified parent and whether it is in a helper
    subtree. Direct app children must be known runtimes or the same executable;
    opening a browser or Explorer must not give setup ownership of that app.
    """
    rows = backend.snapshot()
    pending = list(captured)
    visited = set()
    while pending:
        parent = pending.pop()
        if parent in visited or backend.identity(parent.pid) != parent:
            continue
        visited.add(parent)
        helper_tree = captured[parent][1]
        for entry in rows.values():
            if entry.parent_pid != parent.pid or entry.pid == os.getpid():
                continue
            name = ntpath.basename(entry.name).casefold()
            if not helper_tree and name not in _HELPER_NAMES and name != ntpath.basename(parent.path):
                continue
            child = backend.identity(entry.pid)
            if not _same_owner(child, parent) or child.created < parent.created:
                continue
            helper = helper_tree or ntpath.basename(child.path) in _HELPER_NAMES
            if not helper and child.path != parent.path:
                continue
            # A stale Toolhelp row can refer to a PID that was reused before
            # its image was read. Confirm both the edge and its identities.
            current_row = backend.snapshot().get(child.pid)
            if (current_row is None or current_row.parent_pid != parent.pid
                    or backend.identity(child.pid) != child
                    or backend.identity(parent.pid) != parent):
                continue
            captured[child] = (parent, helper)
            pending.append(child)


def _child_first(captured, live):
    def depth(process):
        seen = set()
        while process in captured and process not in seen:
            seen.add(process)
            process = captured[process][0]
        return len(seen)

    return sorted(live, key=lambda item: (depth(item), item.created), reverse=True)


def _find_existing(backend, target, control_port, installer_pid):
    rows = backend.snapshot()
    installer = backend.identity(installer_pid)
    if installer is None:
        raise InstallationProcessError("Could not verify the installer process. Close Astra Downloader and retry.")
    cache = {installer_pid: installer}

    def identity(pid):
        if pid not in cache:
            cache[pid] = backend.identity(pid)
        return cache[pid]

    excluded = {installer_pid}
    child = installer
    while child.pid in rows:
        parent_pid = rows[child.pid].parent_pid
        if not parent_pid or parent_pid in excluded or parent_pid not in rows:
            break
        if ntpath.basename(rows[parent_pid].name).casefold() != ntpath.basename(installer.path).casefold():
            break
        parent = identity(parent_pid)
        if not _same_owner(parent, installer) or parent.path != installer.path or parent.created > child.created:
            break
        excluded.add(parent.pid)
        child = parent

    found = {}
    for pid, entry in rows.items():
        if pid in excluded or ntpath.basename(entry.name).casefold() != ntpath.basename(target).casefold():
            continue
        process = identity(pid)
        if _same_owner(process, installer) and process.path == target:
            found[pid] = process

    anchors = []
    for pid in backend.listeners(control_port):
        if pid in excluded:
            continue
        entry = rows.get(pid)
        if entry is None or not entry.name.casefold().startswith("astradownloader") or not entry.name.casefold().endswith(".exe"):
            continue
        process = identity(pid)
        if _same_owner(process, installer):
            basename = ntpath.basename(process.path)
            if basename.startswith("astradownloader") and basename.endswith(".exe"):
                found[pid] = process
                anchors.append(process)

    # PyInstaller's one-file bootloader shares the child's path. Follow only
    # that identified family; another portable copy is not an installation.
    for anchor in anchors:
        family = {anchor.pid: anchor}
        changed = True
        while changed:
            changed = False
            for pid, entry in rows.items():
                if pid in excluded or pid in family:
                    continue
                children = [item for child_pid, item in family.items() if rows.get(child_pid) and rows[child_pid].parent_pid == pid]
                parent = family.get(entry.parent_pid)
                if not parent and not children:
                    continue
                if ntpath.basename(entry.name).casefold() != ntpath.basename(anchor.path):
                    continue
                process = identity(pid)
                if not _same_owner(process, installer) or process.path != anchor.path:
                    continue
                if (parent and process.created >= parent.created) or any(process.created <= item.created for item in children):
                    family[pid] = process
                    changed = True
        found.update(family)
    return tuple(found.values())


def stop_existing_installation(target_path, *, control_port, request_shutdown, timeout=8, progress=None):
    """Close verified old app processes, excluding this installer's bootloader.

    ``request_shutdown`` sends the authenticated command and must itself use
    bounded I/O. The timeout includes that request and all waits. No process
    is force-closed unless its captured identity still matches. Returns False
    if no matching same-user/session process exists; otherwise returns True
    only after every captured application and helper has exited or its PID
    has been reused. Browser and Explorer windows opened by the app are kept.
    """
    if os.name != "nt":
        return False
    timeout = float(timeout)
    if not 0 < timeout <= 120:
        raise ValueError("timeout must be between 0 and 120 seconds")
    if not callable(request_shutdown):
        raise TypeError("request_shutdown must be callable")
    port = int(control_port)
    if not 0 < port < 65536:
        raise ValueError("control_port must be a valid TCP port")
    try:
        backend = _WindowsProcesses()
        existing = _find_existing(backend, _canonical_path(target_path), port, os.getpid())
        if not existing:
            return False
        started = time.monotonic()
        deadline = started + timeout
        graceful_deadline = started + timeout * 0.75
        captured = {process: (None, False) for process in existing}
        _capture_descendants(backend, captured)
        if progress:
            progress("Closing Astra Downloader...")
        try:
            request_shutdown()
        except OSError as error:
            logging.getLogger(__name__).warning("Graceful application shutdown failed: %s", error)

        def remaining():
            return [process for process in captured if backend.identity(process.pid) == process]

        live = remaining()
        while live and time.monotonic() < graceful_deadline:
            time.sleep(min(0.1, max(0, graceful_deadline - time.monotonic())))
            live = remaining()
        if live:
            # Only still-matching parents can grant ownership of new children
            # spawned while shutdown was pending. Previously captured orphans
            # remain tracked even when their parent is already gone.
            _capture_descendants(backend, captured)
            live = remaining()
            if progress:
                progress("Astra Downloader is not responding. Closing it now...")
            for process in _child_first(captured, live):
                backend.terminate(process)
            live = remaining()
            while live and time.monotonic() < deadline:
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
                live = remaining()
        if live:
            pids = ", ".join(str(item.pid) for item in live)
            raise InstallationProcessError(
                f"Astra Downloader is still running (PID {pids}). Close it in Task Manager, then retry the installation."
            )
        return True
    except OSError as error:
        if error.errno == 5 or getattr(error, "winerror", None) == 5:
            advice = "Access was denied. Close Astra Downloader in Task Manager or run this installer with the same permissions as the running app."
        else:
            advice = "Close Astra Downloader, then retry the installation."
        raise InstallationProcessError(f"Could not safely close the existing application. {advice} Details: {error}") from error
