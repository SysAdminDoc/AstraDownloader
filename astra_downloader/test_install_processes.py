"""Installation shutdown never targets a process by image name alone."""

import ctypes
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import install_processes as install

TARGET = r"C:\Users\Owner\AppData\Local\AstraDownloader\AstraDownloader.exe"
OLD_COPY = r"C:\Users\Owner\Downloads\AstraDownloader-Old.exe"
SETUP = r"C:\Users\Owner\Downloads\AstraDownloader-Setup.exe"
YTDLP = r"C:\Users\Owner\AppData\Local\AstraDownloader\yt-dlp.exe"
FFMPEG = r"C:\Users\Owner\AppData\Local\AstraDownloader\ffmpeg.exe"


def process(pid, path=TARGET, created=100, user=b"owner", session=1):
    return install._Process(pid, created, install._canonical_path(path), user, session)


class FakeProcesses:
    def __init__(self, processes=(), parents=None, listener_pids=()):
        self.current = {item.pid: item for item in processes}
        self.current[900] = process(900, SETUP, 500)
        self.rows = {
            pid: install._SnapshotEntry(pid, (parents or {}).get(pid, 0), install.ntpath.basename(item.path))
            for pid, item in self.current.items()
        }
        self.listener_pids = set(listener_pids)
        self.terminated = []
        self.keep_running = False

    def snapshot(self):
        return self.rows

    def add(self, item, parent_pid):
        self.current[item.pid] = item
        self.rows[item.pid] = install._SnapshotEntry(item.pid, parent_pid, install.ntpath.basename(item.path))

    def identity(self, pid):
        return self.current.get(pid)

    def listeners(self, port):
        assert port == 9752
        return self.listener_pids

    def terminate(self, expected):
        if self.current.get(expected.pid) == expected:
            self.terminated.append(expected.pid)
            if not self.keep_running:
                self.current.pop(expected.pid)


class InstallationShutdownTests(unittest.TestCase):
    def run_stop(self, backend, callback=None, timeout=1):
        self.elapsed = 0.0

        def advance(seconds):
            self.elapsed += seconds

        with mock.patch.object(install.os, "name", "nt"), \
                mock.patch.object(install.os, "getpid", return_value=900), \
                mock.patch.object(install, "_WindowsProcesses", return_value=backend), \
                mock.patch.object(install.time, "monotonic", side_effect=lambda: self.elapsed), \
                mock.patch.object(install.time, "sleep", side_effect=advance):
            return install.stop_existing_installation(
                TARGET, control_port=9752, request_shutdown=callback or mock.Mock(), timeout=timeout,
            )

    def test_no_existing_process_does_not_send_shutdown(self):
        callback = mock.Mock()
        self.assertFalse(self.run_stop(FakeProcesses(), callback))
        callback.assert_not_called()

    def test_graceful_exit_never_forces_termination(self):
        backend = FakeProcesses([process(10)])
        callback = mock.Mock(side_effect=lambda: backend.current.pop(10))
        self.assertTrue(self.run_stop(backend, callback))
        callback.assert_called_once_with()
        self.assertEqual(backend.terminated, [])

    def test_force_closes_verified_target_children_before_parent(self):
        backend = FakeProcesses([process(10), process(11, created=200)], {11: 10})
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [11, 10])
        self.assertLessEqual(self.elapsed, 1)

    def test_media_tree_is_closed_child_first_even_with_equal_creation_times(self):
        backend = FakeProcesses([
            process(10), process(11, YTDLP), process(12, FFMPEG),
            process(13, r"C:\Runtime\custom-decoder.exe"),
        ], {11: 10, 12: 11, 13: 12})
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [13, 12, 11, 10])

    def test_captured_helpers_are_closed_after_the_app_exits_gracefully(self):
        backend = FakeProcesses([
            process(10), process(11, YTDLP, 200), process(12, FFMPEG, 300),
        ], {11: 10, 12: 11})
        self.assertTrue(self.run_stop(backend, lambda: backend.current.pop(10)))
        self.assertEqual(backend.terminated, [12, 11])

    def test_gracefully_closed_helpers_are_not_forced(self):
        backend = FakeProcesses([process(10), process(11, YTDLP, 200)], {11: 10})
        self.assertTrue(self.run_stop(backend, backend.current.clear))
        self.assertEqual(backend.terminated, [])

    def test_helpers_spawned_during_grace_are_captured_before_force(self):
        backend = FakeProcesses([process(10)])

        def spawn():
            backend.add(process(11, YTDLP, 200), 10)
            backend.add(process(12, FFMPEG, 300), 11)

        self.assertTrue(self.run_stop(backend, spawn))
        self.assertEqual(backend.terminated, [12, 11, 10])

    def test_retained_orphan_helper_can_anchor_new_children(self):
        backend = FakeProcesses([process(10), process(11, YTDLP, 200)], {11: 10})

        def spawn_after_app_exits():
            backend.current.pop(10)
            backend.add(process(12, FFMPEG, 300), 11)

        self.assertTrue(self.run_stop(backend, spawn_after_app_exits))
        self.assertEqual(backend.terminated, [12, 11])

    def test_reused_parent_pid_does_not_adopt_its_new_helpers(self):
        backend = FakeProcesses([process(10)])

        def reuse():
            backend.current[10] = process(10, created=500)
            backend.add(process(11, YTDLP, 600), 10)

        self.assertTrue(self.run_stop(backend, reuse))
        self.assertEqual(backend.terminated, [])
        self.assertIn(11, backend.current)

    def test_reused_helper_pid_is_preserved_but_its_captured_child_is_closed(self):
        backend = FakeProcesses([
            process(10), process(11, YTDLP, 200), process(12, FFMPEG, 300),
        ], {11: 10, 12: 11})

        def reuse():
            backend.add(process(11, YTDLP, 900), 0)

        self.assertTrue(self.run_stop(backend, reuse))
        self.assertEqual(backend.terminated, [12, 10])
        self.assertIn(11, backend.current)

    def test_children_with_older_start_other_user_or_other_session_are_preserved(self):
        for child in (
            process(11, YTDLP, 50),
            process(11, YTDLP, 200, user=b"other-owner"),
            process(11, YTDLP, 200, session=2),
        ):
            with self.subTest(child=child):
                backend = FakeProcesses([process(10), child], {11: 10})
                self.assertTrue(self.run_stop(backend))
                self.assertEqual(backend.terminated, [10])

    def test_browser_explorer_and_unrelated_runtime_children_are_preserved(self):
        backend = FakeProcesses([
            process(10), process(11, r"C:\Browser\chrome.exe", 200),
            process(12, r"C:\Windows\explorer.exe", 200),
            process(13, FFMPEG, 300), process(14, YTDLP, 200),
            process(15, r"D:\Portable\AstraDownloader.exe", 200),
        ], {11: 10, 12: 10, 13: 11, 14: 0, 15: 10})
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [10])
        self.assertTrue({11, 12, 13, 14, 15}.issubset(backend.current))

    def test_a_reused_child_in_a_stale_snapshot_is_not_adopted(self):
        backend = FakeProcesses([process(10), process(11, YTDLP, 200)], {11: 10})
        stale_rows = dict(backend.rows)
        calls = 0

        def snapshot():
            nonlocal calls
            calls += 1
            if calls <= 2:  # Root discovery, then initial descendants.
                return stale_rows
            backend.add(process(11, YTDLP, 300), 0)
            return backend.rows

        backend.snapshot = snapshot
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [10])

    def test_parent_identity_is_rechecked_before_accepting_an_edge(self):
        backend = FakeProcesses([process(10), process(11, YTDLP, 200)], {11: 10})
        calls = 0

        def snapshot():
            nonlocal calls
            calls += 1
            if calls == 3:
                backend.current[10] = process(10, created=300)
            return backend.rows

        backend.snapshot = snapshot
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [])

    def test_stubborn_orphan_helper_prevents_a_successful_return(self):
        backend = FakeProcesses([process(10), process(11, YTDLP, 200)], {11: 10})
        backend.keep_running = True
        with self.assertRaisesRegex(install.InstallationProcessError, "PID 11"):
            self.run_stop(backend, lambda: backend.current.pop(10))
        self.assertEqual(backend.terminated, [11])

    def test_portable_copies_other_users_and_other_sessions_are_preserved(self):
        backend = FakeProcesses([
            process(10, r"D:\Portable\AstraDownloader.exe"),
            process(11, user=b"other-owner"),
            process(12, session=2),
        ])
        self.assertFalse(self.run_stop(backend))
        self.assertEqual(backend.terminated, [])

    def test_control_listener_adds_only_its_pyinstaller_family(self):
        backend = FakeProcesses([
            process(10, OLD_COPY), process(11, OLD_COPY, 200), process(12, OLD_COPY, 300),
            process(13, OLD_COPY, 210), process(14, r"C:\Other\AstraDownloader-Old.exe", 300),
        ], {11: 10, 12: 11, 14: 10}, {11})
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(set(backend.terminated), {10, 11, 12})
        self.assertIn(13, backend.current)
        self.assertIn(14, backend.current)

    def test_port_owner_requires_verified_app_name_and_same_owner(self):
        for candidate in (
            process(10, r"C:\Other\unrelated.exe"),
            process(10, OLD_COPY, user=b"other-owner"),
            process(10, OLD_COPY, session=2),
        ):
            with self.subTest(candidate=candidate):
                backend = FakeProcesses([candidate], listener_pids={10})
                self.assertFalse(self.run_stop(backend))
                self.assertEqual(backend.terminated, [])

    def test_installer_and_its_same_path_bootloader_ancestors_are_excluded(self):
        backend = FakeProcesses([
            process(898, SETUP, 300), process(899, SETUP, 400),
        ], {900: 899, 899: 898}, {900})
        self.assertFalse(self.run_stop(backend))
        self.assertEqual(backend.terminated, [])

    def test_installer_is_excluded_even_when_running_from_managed_target(self):
        backend = FakeProcesses([process(899, TARGET, 400)], {900: 899}, {900})
        backend.current[900] = process(900, TARGET, 500)
        backend.rows[900] = install._SnapshotEntry(900, 899, "AstraDownloader.exe")
        self.assertFalse(self.run_stop(backend))
        self.assertEqual(backend.terminated, [])

    def test_reused_parent_pid_is_not_mistaken_for_a_bootloader(self):
        backend = FakeProcesses([
            process(10, OLD_COPY, 300), process(11, OLD_COPY, 200),
        ], {11: 10}, {11})
        self.assertTrue(self.run_stop(backend))
        self.assertEqual(backend.terminated, [11])

    def test_pid_reuse_during_graceful_wait_does_not_kill_replacement(self):
        for change in (
            {"created": 999}, {"path": install._canonical_path(OLD_COPY)},
            {"user": b"other-owner"}, {"session": 2},
        ):
            with self.subTest(change=change):
                original = process(10)
                backend = FakeProcesses([original])
                callback = lambda b=backend, p=original, c=change: b.current.update({10: replace(p, **c)})
                self.assertTrue(self.run_stop(backend, callback))
                self.assertEqual(backend.terminated, [])

    def test_access_denied_is_actionable_and_stops_without_termination(self):
        backend = FakeProcesses([process(10)])
        original = backend.identity
        backend.identity = lambda pid: (_ for _ in ()).throw(OSError(5, "denied")) if pid == 10 else original(pid)
        with self.assertRaisesRegex(install.InstallationProcessError, "Access was denied"):
            self.run_stop(backend)
        self.assertEqual(backend.terminated, [])

    def test_stubborn_process_raises_after_bounded_wait(self):
        backend = FakeProcesses([process(10)])
        backend.keep_running = True
        with self.assertRaisesRegex(install.InstallationProcessError, "PID 10.*Task Manager"):
            self.run_stop(backend)
        self.assertLessEqual(self.elapsed, 1.001)

    def test_failed_shutdown_request_is_logged_then_verified_process_is_closed(self):
        backend = FakeProcesses([process(10)])
        with self.assertLogs("install_processes", level="WARNING"):
            self.assertTrue(self.run_stop(backend, mock.Mock(side_effect=OSError("offline"))))
        self.assertEqual(backend.terminated, [10])


@unittest.skipUnless(os.name == "nt", "Requires native Windows process identity checks")
class NativeProcessTreeTests(unittest.TestCase):
    def test_private_native_tree_exits_and_unrelated_private_copy_survives(self):
        backend = install._WindowsProcesses()
        with tempfile.TemporaryDirectory(prefix="astra-process-tree-") as tmp:
            root = Path(tmp)
            system = Path(os.environ["SystemRoot"]) / "System32"
            target, helper, leaf = (root / name for name in (
                "AstraDownloader.exe", "yt-dlp.exe", "ffmpeg.exe",
            ))
            shutil.copy2(system / "cmd.exe", target)
            shutil.copy2(system / "cmd.exe", helper)
            shutil.copy2(system / "ping.exe", leaf)
            child_script, app_script = root / "helper.cmd", root / "app.cmd"
            child_script.write_text(f'@"{leaf}" -t 127.0.0.1\n', encoding="utf-8")
            app_script.write_text(f'@"{helper}" /d /c "{child_script}"\n', encoding="utf-8")
            paths = {install._canonical_path(path) for path in (target, helper, leaf)}
            owned = []

            def private_processes():
                found = []
                for entry in backend.snapshot().values():
                    if entry.name.casefold() not in {path.name.casefold() for path in (target, helper, leaf)}:
                        continue
                    identity = backend.identity(entry.pid)
                    if identity is not None and identity.path in paths:
                        found.append(identity)
                return found

            options = {
                "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
            }
            try:
                unrelated = subprocess.Popen([str(leaf), "-t", "127.0.0.1"], **options)
                owned.append(unrelated)
                app = subprocess.Popen([str(target), "/d", "/c", str(app_script)], **options)
                owned.append(app)
                deadline = time.monotonic() + 5
                tree = []
                while time.monotonic() < deadline:
                    tree = [item for item in private_processes() if item.pid != unrelated.pid]
                    if len(tree) == 3:
                        break
                    if app.poll() is not None:
                        self.fail("The private native test parent exited before creating its helpers")
                    time.sleep(0.05)
                self.assertEqual(len(tree), 3, "The private native helper tree did not start")
                callback = mock.Mock()
                # Reserve an otherwise unused control port so no actual app
                # listener can be selected by this native test.
                with socket.socket() as control:
                    control.bind(("127.0.0.1", 0))
                    control.listen()
                    result = install.stop_existing_installation(
                        target, control_port=control.getsockname()[1],
                        request_shutdown=callback, timeout=2,
                    )
                self.assertTrue(result)
                callback.assert_called_once_with()
                for identity in tree:
                    self.assertNotEqual(backend.identity(identity.pid), identity)
                self.assertIsNone(unrelated.poll())
            finally:
                # Only exact private paths are eligible, including if an
                # assertion failed before helper PIDs could be captured.
                for identity in sorted(private_processes(), key=lambda item: item.created, reverse=True):
                    backend.terminate(identity)
                for child in owned:
                    try:
                        child.wait(timeout=3)
                    finally:
                        if child.poll() is None:
                            child.kill()
                            child.wait(timeout=3)
                deadline = time.monotonic() + 3
                while private_processes() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(private_processes(), [])


class WindowsBoundaryTests(unittest.TestCase):
    def backend(self):
        backend = object.__new__(install._WindowsProcesses)
        backend.kernel = mock.Mock()
        backend.kernel.OpenProcess.return_value = 42
        return backend

    def test_terminate_rechecks_identity_on_the_same_handle(self):
        for changed in (None, replace(process(10), created=101)):
            with self.subTest(changed=changed):
                backend = self.backend()
                backend._identity_from_handle = mock.Mock(return_value=changed)
                backend.terminate(process(10))
                backend.kernel.TerminateProcess.assert_not_called()
                backend.kernel.CloseHandle.assert_called_once_with(42)

    def test_query_failure_closes_its_process_handle(self):
        backend = self.backend()
        backend.kernel.WaitForSingleObject.return_value = 258
        backend._identity_from_handle = mock.Mock(side_effect=OSError(5, "denied"))
        with self.assertRaises(OSError):
            backend.identity(10)
        backend.kernel.CloseHandle.assert_called_once_with(42)

    def test_exit_during_identity_query_is_treated_as_already_gone(self):
        backend = self.backend()
        backend._identity_from_handle = mock.Mock(side_effect=OSError(5, "process exited"))
        backend.kernel.WaitForSingleObject.return_value = 0
        self.assertIsNone(backend.identity(10))
        backend.kernel.CloseHandle.assert_called_once_with(42)

    def test_token_query_failure_closes_token_and_process_handles(self):
        backend = self.backend()
        backend.kernel.WaitForSingleObject.return_value = 258

        def image(_handle, _flags, buffer, _capacity):
            buffer.value = TARGET
            return True

        def token(_process, _access, result):
            result._obj.value = 43
            return True

        backend.kernel.QueryFullProcessImageNameW.side_effect = image
        backend.security = mock.Mock()
        backend.security.OpenProcessToken.side_effect = token
        backend._token_information = mock.Mock(side_effect=OSError(5, "denied"))
        with self.assertRaises(OSError):
            backend.identity(10)
        closed = [getattr(item.args[0], "value", item.args[0]) for item in backend.kernel.CloseHandle.call_args_list]
        self.assertEqual(closed, [43, 42])

    def test_termination_failure_still_closes_its_process_handle(self):
        backend = self.backend()
        backend._identity_from_handle = mock.Mock(return_value=process(10))
        backend.kernel.TerminateProcess.return_value = False
        backend.kernel.WaitForSingleObject.return_value = 258
        backend._error = mock.Mock(return_value=OSError(5, "denied"))
        with self.assertRaises(OSError):
            backend.terminate(process(10))
        backend.kernel.CloseHandle.assert_called_once_with(42)

    def test_tcp_lookup_selects_only_exact_loopback_port(self):
        rows = []
        for address, port, pid in (("127.0.0.1", 9752, 10), ("0.0.0.0", 9752, 11), ("127.0.0.1", 9753, 12)):
            row = install._TcpRow()
            row.local_address = int.from_bytes(socket.inet_aton(address), "little")
            row.local_port = socket.htons(port)
            row.pid = pid
            rows.append(bytes(row))
        count = install.wintypes.DWORD(len(rows))
        payload = bytes(count) + b"".join(rows)

        def table(buffer, size, _ordered, family, table_class, _reserved):
            self.assertEqual((family, table_class), (2, 3))
            size._obj.value = len(payload)
            if buffer is None:
                return 122
            ctypes.memmove(buffer, payload, len(payload))
            return 0

        backend = self.backend()
        backend.ip = mock.Mock()
        backend.ip.GetExtendedTcpTable.side_effect = table
        self.assertEqual(backend.listeners(9752), {10})

    def test_path_comparison_normalizes_dos_prefix_and_case(self):
        self.assertEqual(
            install._canonical_path(r"\\?\C:\Apps\ASTRADOWNLOADER.EXE"),
            install._canonical_path(r"c:\apps\astradownloader.exe"),
        )


if __name__ == "__main__":
    unittest.main()
