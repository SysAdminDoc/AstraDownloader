"""Tests for readiness probes, managed binaries and the updater."""

import ast
import hashlib
import inspect
import io
import re
import json
import os
import queue
import shutil
import socketserver
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
import urllib.request
from datetime import date, datetime, timedelta
from unittest import mock
from pathlib import Path
import xml.etree.ElementTree as ET
import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


class DiagnosticsBundleTests(unittest.TestCase):
    def test_redact_diagnostic_text_removes_private_paths_urls_and_secrets(self):
        secret = "secret-token-1234567890"
        raw = (
            f"GET https://example.com/watch?v=private123 "
            f"Authorization: Bearer {secret} "
            f"at C:\\Users\\private\\Videos\\clip.mp4"
        )

        redacted = ad.redact_diagnostic_text(
            raw,
            secrets=(secret,),
        )

        self.assertNotIn("https://example.com", redacted)
        self.assertNotIn("private123", redacted)
        self.assertNotIn(secret, redacted)
        self.assertNotIn("C:\\Users\\private", redacted)
        self.assertIn("[redacted URL]", redacted)
        self.assertIn("[redacted path]", redacted)

    def test_seed_log_ring_rehydrates_the_persisted_tail(self):
        from collections import deque

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, "_log_ring", deque(maxlen=ad._LOG_RING_MAX)):
            path = Path(tmp) / "server.log"
            path.write_text(
                "2026-08-08 10:00:00 first\n"
                "2026-08-08 10:00:01 second\n",
                encoding="utf-8",
            )
            self.assertEqual(ad.seed_log_ring(path), 2)
            self.assertEqual(
                [entry["msg"] for entry in ad.get_recent_log_entries()],
                ["first", "second"],
            )

    def test_save_diagnostics_writes_the_redacted_payload_to_a_chosen_file(self):
        class Window:
            pass

        window = Window()
        events = []
        window._append_log = events.append
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "diagnostics.json"
            with mock.patch.object(ad.QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.assertTrue(ad.MainWindow._save_diagnostics_text(window, '{"ok": true}'))
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True})
        self.assertIn("Diagnostics saved", events[-1])

    def test_reveal_log_file_uses_the_isolated_spawn_dependency(self):
        class Window:
            pass

        window = Window()
        events = []
        spawned = []
        window._append_log = events.append
        window._dependencies = {
            "LOG_PATH": lambda: log_path,
            "build_reveal_command": lambda value: f"reveal {value}",
            "spawn_detached": spawned.append,
        }
        window._value = lambda name: (
            window._dependencies[name]()
            if callable(window._dependencies[name])
            else window._dependencies[name]
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            log_path.write_text("entry\n", encoding="utf-8")
            self.assertTrue(ad.MainWindow._reveal_log_file(window))
        self.assertEqual(spawned, [f"reveal {log_path}"])
        self.assertIn("Revealed", events[-1])

    def test_bundle_is_allowlisted_bounded_and_redacts_seeded_secrets(self):
        secret = "seeded-secret-value-1234567890abcdef"
        logs = [
            {
                "ts": "2026-07-14 12:00:00",
                "msg": (
                    f"Request https://youtube.com/watch?v=private123 failed; "
                    f"token={secret}; cookie=SAPISID; path=C:\\Users\\private\\Videos\\clip.mp4; "
                    f"id={'a' * 32}"
                ),
            }
        ] * (ad.DIAGNOSTIC_LOG_ENTRY_LIMIT + 5)

        commands = [
            {
                "status": "failed",
                "command": f"yt-dlp --password {secret} https://youtube.com/watch?v=private123",
            }
        ] * (ad.DIAGNOSTIC_COMMAND_ENTRY_LIMIT + 3)

        bundle = ad.build_diagnostics_bundle(
            server_running=True,
            endpoint="http://127.0.0.1:9751",
            active_downloads=2,
            completed_downloads=7,
            recent_logs=logs,
            secrets=(secret,),
            recent_commands=commands,
        )
        serialized = json.dumps(bundle)

        self.assertEqual(set(bundle), {
            "schemaVersion", "application", "service", "dependencies",
            "recentLog", "recentCommands",
        })
        self.assertEqual(len(bundle["recentLog"]), ad.DIAGNOSTIC_LOG_ENTRY_LIMIT)
        self.assertEqual(
            len(bundle["recentCommands"]), ad.DIAGNOSTIC_COMMAND_ENTRY_LIMIT)
        self.assertEqual(bundle["recentCommands"][0]["status"], "failed")
        self.assertEqual(bundle["service"]["activeDownloads"], 2)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("private123", serialized)
        self.assertNotIn("C:\\\\Users", serialized)
        self.assertNotIn("SAPISID", serialized)
        self.assertNotIn("a" * 32, serialized)
        self.assertIn("[redacted", serialized)

    def test_the_real_log_ring_holds_what_the_bundle_advertises(self):
        # Injecting a synthetic list let the bundle claim 30 entries while the
        # ring behind get_recent_log_entries only ever held 20, so the two
        # constants could diverge with every test still green.
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "server.log"
            for index in range(ad.DIAGNOSTIC_LOG_ENTRY_LIMIT + 10):
                ad.write_persistent_log(f"entry {index}", log_path)

            entries = ad.get_recent_log_entries()
            # write_persistent_log hands the file write to a writer thread, so
            # leaving this block can race the flush and fail the directory
            # cleanup with WinError 145 instead of failing an assertion.
            ad.flush_persistent_log()

        self.assertEqual(len(entries), ad.DIAGNOSTIC_LOG_ENTRY_LIMIT)
        bundle = ad.build_diagnostics_bundle(recent_logs=entries)
        self.assertEqual(
            len(bundle["recentLog"]), ad.DIAGNOSTIC_LOG_ENTRY_LIMIT,
            "the bundle must be able to carry a full ring",
        )
        self.assertEqual(
            bundle["recentLog"][-1]["message"],
            f"entry {ad.DIAGNOSTIC_LOG_ENTRY_LIMIT + 9}",
        )


class AutoUpdateThrottleTests(unittest.TestCase):
    """yt-dlp updates use a long success interval and short failure backoff."""

    def test_should_check_returns_true_with_no_prior_stamp(self):
        class _C:
            def get(self, key, default=None):
                return "" if key == "LastYtDlpUpdateCheck" else default
        self.assertTrue(ad.should_check_ytdlp_update(_C()))

    def test_should_check_returns_false_with_recent_stamp(self):
        recent = (ad.datetime.now() - ad.datetime.now().__class__.min.__class__.min.__class__.resolution).strftime("%Y-%m-%d %H:%M:%S")
        # Simpler form: use "now" as the stamp.
        import datetime as _dt
        recent = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        class _C:
            def get(self, key, default=None):
                return recent if key == "LastYtDlpUpdateCheck" else default
        self.assertFalse(ad.should_check_ytdlp_update(_C()))

    def test_should_check_returns_false_with_recent_failed_attempt(self):
        import datetime as _dt
        recent = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        class _C:
            def get(self, key, default=None):
                return recent if key == "LastYtDlpUpdateFailure" else default

        self.assertFalse(ad.should_check_ytdlp_update(_C()))

    def test_should_check_allows_failed_attempt_after_short_backoff(self):
        import datetime as _dt
        old = (_dt.datetime.now() - _dt.timedelta(hours=2)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        class _C:
            def get(self, key, default=None):
                return old if key == "LastYtDlpUpdateFailure" else default

        self.assertTrue(ad.should_check_ytdlp_update(_C()))

    def test_should_check_handles_corrupt_stamp(self):
        class _C:
            def get(self, key, default=None):
                return "not-a-date" if key == "LastYtDlpUpdateCheck" else default
        # Malformed stamps should not wedge the update path — default to True
        # so the next launch can re-establish a valid stamp.
        self.assertTrue(ad.should_check_ytdlp_update(_C()))


class AutoUpdateActiveDownloadGuardTests(unittest.TestCase):
    """v4.47.0 NF26 — yt-dlp's ``-U`` flag atomically replaces the binary.
    On Windows an in-flight ``subprocess.Popen([YTDLP_PATH, ...])`` of an
    active download can race the replace with file-in-use errors. The
    guard takes a caller-supplied ``active_count_fn`` and defers the
    update when the function reports any in-flight downloads.
    """

    def _fake_config(self, last_check_stamp=""):
        # Empty stamp triggers should_check_ytdlp_update -> True.
        class _C:
            def __init__(self, stamp):
                self._d = {
                    "AutoUpdateYtDlp": True,
                    "LastYtDlpUpdateCheck": stamp,
                }
            def get(self, key, default=None):
                return self._d.get(key, default)
            def set(self, key, value):
                self._d[key] = value
            def save(self):
                pass
        return _C(last_check_stamp)

    def test_update_fires_when_no_active_downloads(self):
        # active_count_fn returning 0 must NOT defer the update; the
        # threading.Thread must be spawned (we mock it to track the spawn
        # without actually running yt-dlp).
        spawned = {"count": 0}
        orig_thread = ad.threading.Thread
        try:
            class _FakeThread:
                def __init__(self, target=None, daemon=None):
                    self._target = target
                def start(self):
                    spawned["count"] += 1
                    # Don't actually run -U; this tests the guard, not the
                    # subprocess invocation.
            ad.threading.Thread = _FakeThread
            # YTDLP_PATH must exist for the guard to fall through to the
            # active-count check; patch its existence check.
            ad.YTDLP_PATH = type(ad.YTDLP_PATH)(ad.YTDLP_PATH)
            with mock.patch.object(ad.YTDLP_PATH.__class__, 'exists', return_value=True):
                ad.maybe_auto_update_ytdlp(self._fake_config(), active_count_fn=lambda: 0)
        finally:
            ad.threading.Thread = orig_thread
        self.assertEqual(spawned["count"], 1,
                         "Update thread must spawn when active_count == 0")

    def test_update_defers_when_active_downloads_in_flight(self):
        # active_count_fn returning > 0 must defer the update; no thread
        # should spawn.
        spawned = {"count": 0}
        log_lines = []
        orig_thread = ad.threading.Thread
        orig_log = ad.write_persistent_log
        try:
            class _FakeThread:
                def __init__(self, target=None, daemon=None):
                    pass
                def start(self):
                    spawned["count"] += 1
            ad.threading.Thread = _FakeThread
            ad.write_persistent_log = lambda msg: log_lines.append(msg)
            with mock.patch.object(ad.YTDLP_PATH.__class__, 'exists', return_value=True):
                ad.maybe_auto_update_ytdlp(self._fake_config(), active_count_fn=lambda: 3)
        finally:
            ad.threading.Thread = orig_thread
            ad.write_persistent_log = orig_log
        self.assertEqual(spawned["count"], 0,
                         "Update thread must NOT spawn when active_count > 0")
        self.assertTrue(any("auto-update deferred" in line for line in log_lines),
                        f"Defer log line must surface in persistent log; got {log_lines!r}")
        self.assertTrue(any("3 active download" in line for line in log_lines),
                        f"Defer log must include the count; got {log_lines!r}")

    def test_update_defers_when_active_count_fn_raises(self):
        # Replacing the binary while activity is unknown is unsafe. A broken
        # caller-supplied probe must fail closed and defer the update.
        spawned = {"count": 0}
        log_lines = []
        orig_thread = ad.threading.Thread
        orig_log = ad.write_persistent_log
        try:
            class _FakeThread:
                def __init__(self, target=None, daemon=None):
                    pass
                def start(self):
                    spawned["count"] += 1
            ad.threading.Thread = _FakeThread
            ad.write_persistent_log = lambda msg: log_lines.append(msg)

            def broken_probe():
                raise RuntimeError("probe boom")
            with mock.patch.object(ad.YTDLP_PATH.__class__, 'exists', return_value=True):
                ad.maybe_auto_update_ytdlp(self._fake_config(), active_count_fn=broken_probe)
        finally:
            ad.threading.Thread = orig_thread
            ad.write_persistent_log = orig_log
        self.assertEqual(spawned["count"], 0,
                         "Update thread must not spawn when activity is unknown")
        self.assertTrue(any("deferred" in line and "probe failed" in line for line in log_lines),
                        f"Probe-failure log line must surface; got {log_lines!r}")

    def test_update_without_active_count_fn_proceeds(self):
        # Back-compat: existing callers without the new arg must still work.
        spawned = {"count": 0}
        orig_thread = ad.threading.Thread
        try:
            class _FakeThread:
                def __init__(self, target=None, daemon=None):
                    pass
                def start(self):
                    spawned["count"] += 1
            ad.threading.Thread = _FakeThread
            with mock.patch.object(ad.YTDLP_PATH.__class__, 'exists', return_value=True):
                ad.maybe_auto_update_ytdlp(self._fake_config())
        finally:
            ad.threading.Thread = orig_thread
        self.assertEqual(spawned["count"], 1,
                         "Update must still fire when no active_count_fn provided")


class DenoRuntimeHardGateTests(unittest.TestCase):
    """Runtime-required downloads fail closed on the capability contract."""

    def _create_api(self, deno_probe_result):
        # Build a fresh create_api(config, dl_manager, history) instance with
        # the deno probe patched to the given dict. Returns the Flask test
        # client. Mirrors the existing ApiSecurityTests setup.
        cfg = FakeConfig({'ServerToken': 'test-token-1234567890abcdef1234567890ab'})
        dl_manager = ad.DownloadManager(cfg, FakeHistory())

        with mock.patch.object(ad, 'probe_javascript_runtime', return_value=deno_probe_result):
            api = ad.create_api(cfg, dl_manager, FakeHistory())
        api.config['TESTING'] = True
        return api.test_client(), cfg

    def _auth_header(self, cfg):
        return {'X-Auth-Token': cfg.get('ServerToken', '')}

    def test_download_rejected_when_yt_dlp_needs_runtime_and_deno_absent(self):
        client, cfg = self._create_api({
            'installed': False,
            'version': None,
            'path': None,
            'ytdlpNeedsRuntime': True,
            'advice': 'winget install DenoLand.Deno',
        })
        # Note: even though we patched probe_deno_runtime at create_api time,
        # the handler calls it on every request, so re-patch for the request.
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value={
            'installed': False,
            'supported': False,
            'ejsReady': False,
            'reason': 'runtime-not-installed',
            'ytdlpNeedsRuntime': True,
            'advice': 'winget install DenoLand.Deno',
        }):
            resp = client.post(
                '/download',
                headers={**self._auth_header(cfg), 'Host': '127.0.0.1'},
                json={'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
            )
        self.assertEqual(resp.status_code, 422,
                         f"Expected 422, got {resp.status_code} body={resp.data!r}")
        body = resp.get_json() or {}
        self.assertEqual(body.get('code'), 'js-runtime-missing')
        self.assertEqual(body.get('error_code'), 'js-runtime-missing')
        self.assertEqual(body.get('next_action'), 'configure-javascript-runtime',
                         'Payload must include the recovery action for the extension UI')
        self.assertIn('Deno', body.get('error', ''),
                      'Error message must mention Deno so the extension can surface it')
        self.assertIn('winget install', body.get('advice', ''),
                      'Advice field must carry the install command verbatim')

    def test_download_allowed_when_deno_installed(self):
        # ytdlpNeedsRuntime=True but installed=True → guard passes through.
        client, cfg = self._create_api({
            'installed': True,
            'runtime': 'deno',
            'version': '2.3.0',
            'path': '/usr/bin/deno',
            'supported': True,
            'ejsReady': True,
            'reason': 'ready',
            'ytdlpNeedsRuntime': True,
            'advice': '',
        })
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value={
            'installed': True,
            'runtime': 'deno',
            'supported': True,
            'ejsReady': True,
            'reason': 'ready',
            'ytdlpNeedsRuntime': True,
        }):
            resp = client.post(
                '/download',
                headers={**self._auth_header(cfg), 'Host': '127.0.0.1'},
                json={'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
            )
        # We expect the download to proceed past the Deno gate; the request
        # may fail later (yt-dlp.exe likely missing in the test env) but
        # NOT with our 422. Specifically check that the response is not
        # 422 with code='deno-runtime-missing'.
        if resp.status_code == 422:
            body = resp.get_json() or {}
            self.assertNotEqual(body.get('code'), 'deno-runtime-missing',
                                'Deno-installed path must pass through the NF27 gate')

    def test_download_allowed_when_runtime_not_needed(self):
        # Pre-cutoff yt-dlp (ytdlpNeedsRuntime=False) — guard MUST allow
        # regardless of Deno installed state, so older pins keep working.
        client, cfg = self._create_api({
            'installed': False,
            'ytdlpNeedsRuntime': False,
        })
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value={
            'installed': False,
            'supported': False,
            'ejsReady': False,
            'ytdlpNeedsRuntime': False,
        }):
            resp = client.post(
                '/download',
                headers={**self._auth_header(cfg), 'Host': '127.0.0.1'},
                json={'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
            )
        # As above: not 422 with code='deno-runtime-missing'.
        if resp.status_code == 422:
            body = resp.get_json() or {}
            self.assertNotEqual(body.get('code'), 'deno-runtime-missing',
                                'Pre-cutoff yt-dlp path must skip the NF27 gate')

    def test_download_rejected_when_deno_is_below_runtime_floor(self):
        client, cfg = self._create_api({
            'installed': True,
            'version': '2.2.9',
            'supported': False,
            'ejsReady': False,
            'reason': 'runtime-version-unsupported',
            'stale': True,
            'minVersion': '2.3.0',
            'ytdlpNeedsRuntime': True,
            'advice': 'upgrade Deno',
        })
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value={
            'installed': True,
            'version': '2.2.9',
            'supported': False,
            'ejsReady': False,
            'reason': 'runtime-version-unsupported',
            'stale': True,
            'minVersion': '2.3.0',
            'ytdlpNeedsRuntime': True,
            'advice': 'upgrade Deno',
        }):
            resp = client.post(
                '/download',
                headers={**self._auth_header(cfg), 'Host': '127.0.0.1'},
                json={'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
            )
        self.assertEqual(resp.status_code, 422)
        body = resp.get_json() or {}
        self.assertEqual(body.get('code'), 'js-runtime-unsupported')
        self.assertEqual(body.get('next_action'), 'upgrade-javascript-runtime')

    def test_unknown_and_exception_runtime_states_have_stable_codes(self):
        cases = (
            ('runtime-version-unparseable', 'js-runtime-unverified'),
            ('runtime-probe-failed', 'js-runtime-unverified'),
            ('runtime-execution-failed', 'ejs-runtime-not-ready'),
        )
        for reason, expected_code in cases:
            runtime = {
                'installed': True,
                'runtime': 'deno',
                'supported': reason == 'runtime-execution-failed',
                'ejsReady': False,
                'reason': reason,
                'ytdlpNeedsRuntime': True,
                'advice': 'repair runtime',
            }
            client, cfg = self._create_api(runtime)
            with self.subTest(reason=reason), \
                 mock.patch.object(ad, 'probe_javascript_runtime', return_value=runtime):
                resp = client.post(
                    '/download',
                    headers={**self._auth_header(cfg), 'Host': '127.0.0.1'},
                    json={'url': 'https://www.youtube.com/watch?v=abcdefghijk'},
                )
            self.assertEqual(resp.status_code, 422)
            self.assertEqual((resp.get_json() or {}).get('code'), expected_code)


class FfmpegCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        ad.reset_ffmpeg_capabilities_cache()

    def tearDown(self):
        ad.reset_ffmpeg_capabilities_cache()

    def test_parse_ffmpeg_major_extracts_integer_from_canonical_release(self):
        self.assertEqual(ad.parse_ffmpeg_major('8.1.1'), 8)
        self.assertEqual(ad.parse_ffmpeg_major('7.0-static'), 7)
        self.assertEqual(ad.parse_ffmpeg_major('6.1.1-essentials_build'), 6)
        # BtbN release builds carry a lowercase n tag prefix; they are tagged
        # releases and must be comparable against the security floor.
        self.assertEqual(ad.parse_ffmpeg_major('n8.0.1-9-g1234567'), 8)

    def test_parse_ffmpeg_major_returns_none_on_unparseable(self):
        # ffmpeg-master nightly / git builds report N-NNNNN-gXXXXXXX; not a
        # version we can interpret. None lets the caller degrade gracefully.
        for value in ('', None, 'N-118574-gabc1234', 'not-a-version'):
            with self.subTest(value=value):
                self.assertIsNone(ad.parse_ffmpeg_major(value))

    def test_check_ffmpeg_capabilities_treats_unparseable_as_unknown(self):
        # Monkeypatch get_ffmpeg_version to a snapshot-style string. The
        # audit must not return current=false in that case — an undated
        # snapshot is intentionally non-numeric and we shouldn't guess.
        original = ad.get_ffmpeg_version
        ad.get_ffmpeg_version = lambda *a, **k: 'N-118574-gabc1234'
        try:
            result = ad.check_ffmpeg_capabilities(force=True)
        finally:
            ad.get_ffmpeg_version = original
        self.assertIsNone(result['majorVersion'])
        self.assertIsNone(result['current'])
        self.assertIn('not detected', result['message'].lower())

    def test_check_ffmpeg_capabilities_compares_snapshot_build_date(self):
        original = ad.get_ffmpeg_version
        ad.get_ffmpeg_version = lambda *a, **k: 'N-123918-gabc-20260411'
        try:
            result = ad.check_ffmpeg_capabilities(force=True)
        finally:
            ad.get_ffmpeg_version = original
        self.assertIsNone(result['majorVersion'])
        self.assertEqual(result['buildDate'], '2026-04-11')
        self.assertEqual(result['comparison'], 'snapshot-date')
        self.assertFalse(result['current'])
        self.assertIn('re-download', result['message'])

    def test_check_ffmpeg_capabilities_marks_current_when_at_or_above_floor(self):
        original = ad.get_ffmpeg_version
        # 8.1.2 is the exact security floor (CVE-2026-8461); at-floor passes.
        ad.get_ffmpeg_version = lambda *a, **k: '8.1.2'
        try:
            result = ad.check_ffmpeg_capabilities(force=True)
        finally:
            ad.get_ffmpeg_version = original
        self.assertEqual(result['majorVersion'], 8)
        self.assertTrue(result['current'])
        self.assertIn('meets', result['message'])

    def test_check_ffmpeg_capabilities_flags_vulnerable_8_0_below_exact_floor(self):
        # 8.0.1 clears the major-8 bar but is inside the RV60 OOB-read range and
        # below the 8.1.2 MagicYUV-RCE fix, so the exact floor must flag it.
        original = ad.get_ffmpeg_version
        ad.get_ffmpeg_version = lambda *a, **k: '8.0.1'
        try:
            result = ad.check_ffmpeg_capabilities(force=True)
        finally:
            ad.get_ffmpeg_version = original
        self.assertEqual(result['majorVersion'], 8)
        self.assertFalse(result['current'])
        self.assertIn('8.1.2', result['message'])

    def test_check_ffmpeg_capabilities_marks_stale_below_floor(self):
        original = ad.get_ffmpeg_version
        ad.get_ffmpeg_version = lambda *a, **k: '5.1.2'
        try:
            result = ad.check_ffmpeg_capabilities(force=True)
        finally:
            ad.get_ffmpeg_version = original
        self.assertEqual(result['majorVersion'], 5)
        self.assertFalse(result['current'])
        self.assertIn('below', result['message'])

    def test_health_endpoint_exposes_ffmpeg_capabilities(self):
        # Pin the wire contract — the extension popup will key off
        # /health.ffmpegCapabilities.current to render the stale-ffmpeg
        # pill.
        config = FakeConfig({"ServerToken": "z" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get(
            "/health", headers={"X-MDL-Client": "MediaDL"},
        )
        body = resp.get_json()
        self.assertIn('ffmpegCapabilities', body)
        caps = body['ffmpegCapabilities']
        self.assertIsInstance(caps, dict)
        for key in ('majorVersion', 'current', 'message'):
            self.assertIn(key, caps)


class DenoRuntimeProbeTests(unittest.TestCase):
    """probe_deno_runtime, version-date cutoff parsing, and
    /health.denoRuntime field shape. The extension's downloadHealthPanel
    keys the 'Deno: missing' warn pill off exactly this wire contract."""

    def setUp(self):
        ad.reset_deno_runtime_cache()

    def tearDown(self):
        ad.reset_deno_runtime_cache()

    def test_parse_ytdlp_release_date_extracts_yyyy_mm_dd(self):
        self.assertEqual(ad._parse_ytdlp_release_date("2026.04.10"), (2026, 4, 10))
        self.assertEqual(ad._parse_ytdlp_release_date("2025.10.22"), (2025, 10, 22))
        # Builds may carry a nightly suffix like 2026.05.03.233852 — should
        # still parse the leading YYYY.MM.DD prefix.
        self.assertEqual(ad._parse_ytdlp_release_date("2026.05.03.233852"), (2026, 5, 3))

    def test_parse_ytdlp_release_date_returns_none_on_garbage(self):
        for bad in ["", "git-sha-abc123", None, "v1.2.3", "not-a-version", "0.0.0"]:
            self.assertIsNone(ad._parse_ytdlp_release_date(bad))

    def test_parse_ytdlp_release_date_rejects_out_of_range_components(self):
        # Defensive — out-of-range month / day mean we got something other
        # than a real release date and the runtime probe should NOT flag it.
        self.assertIsNone(ad._parse_ytdlp_release_date("2026.13.10"))
        self.assertIsNone(ad._parse_ytdlp_release_date("2026.04.99"))
        self.assertIsNone(ad._parse_ytdlp_release_date("2026.00.10"))

    def test_ytdlp_needs_external_runtime_at_or_past_cutoff(self):
        # Cutoff is 2026.04.01.
        self.assertTrue(ad.ytdlp_needs_external_runtime("2026.04.01"))
        self.assertTrue(ad.ytdlp_needs_external_runtime("2026.04.10"))
        self.assertTrue(ad.ytdlp_needs_external_runtime("2026.05.03.233852"))
        self.assertTrue(ad.ytdlp_needs_external_runtime("2027.01.01"))

    def test_ytdlp_needs_external_runtime_before_cutoff_returns_false(self):
        self.assertFalse(ad.ytdlp_needs_external_runtime("2026.03.31"))
        self.assertFalse(ad.ytdlp_needs_external_runtime("2025.10.22"))
        self.assertFalse(ad.ytdlp_needs_external_runtime("2024.12.31"))

    def test_ytdlp_needs_external_runtime_unparseable_is_false(self):
        # Important: we MUST NOT false-positive on first-run when
        # get_ytdlp_version() returns an empty string before bootstrap.
        for bad in ["", None, "git-sha", "unknown"]:
            self.assertFalse(ad.ytdlp_needs_external_runtime(bad))

    def test_probe_deno_runtime_returns_wire_contract_shape(self):
        # Fake the underlying primitives so the test has no PATH dep.
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        original_run_captured = ad._run_captured
        ad.shutil.which = lambda binary: '/usr/local/bin/deno' if binary == 'deno' else None
        ad.get_ytdlp_version = lambda force=False: '2026.05.03.233852'
        ad._run_captured = lambda args, timeout=5: (
            ad.JS_RUNTIME_CAPABILITY_MARKER if 'eval' in args
            else f'deno {ad.DENO_SECURITY_MIN_VERSION} (release, x86_64-pc-windows-msvc)\n'
        )
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad._run_captured = original_run_captured
        # Wire-contract shape pin — extension/ytkit.js consumes EXACTLY
        # these fields. Adding fields is safe (additive); renaming or
        # dropping any of these would break the downloadHealthPanel.
        self.assertEqual(set(result.keys()), {
            'installed', 'version', 'path', 'source', 'supported', 'stale',
            'minVersion', 'ytdlpNeedsRuntime', 'advice', 'runtime', 'ejsReady',
            'reason', 'configuredRuntime', 'canProvisionDeno', 'securityMinVersion'
        })
        self.assertTrue(result['installed'])
        self.assertEqual(result['version'], ad.DENO_SECURITY_MIN_VERSION)
        self.assertIn(result['source'], ('bundled', 'system'))
        self.assertTrue(result['supported'])
        self.assertTrue(result['ejsReady'])
        self.assertEqual(result['reason'], 'ready')
        self.assertFalse(result['stale'])
        self.assertEqual(result['minVersion'], ad.DENO_MIN_VERSION)
        self.assertTrue(result['ytdlpNeedsRuntime'])
        self.assertEqual(result['advice'], '')

    def test_probe_deno_runtime_marks_stale_version_unsupported(self):
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        original_run_captured = ad._run_captured
        ad.shutil.which = lambda binary: '/usr/local/bin/deno' if binary == 'deno' else None
        ad.get_ytdlp_version = lambda force=False: '2026.06.09'
        ad._run_captured = lambda args, timeout=5: 'deno 2.2.9\n'
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad._run_captured = original_run_captured
        self.assertTrue(result['installed'])
        self.assertFalse(result['supported'])
        self.assertTrue(result['stale'])
        self.assertEqual(result['minVersion'], ad.DENO_MIN_VERSION)
        self.assertIn(ad.DENO_MIN_VERSION, result['advice'])

    def test_probe_deno_runtime_distinguishes_the_security_floor(self):
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        original_run_captured = ad._run_captured
        ad.shutil.which = lambda binary: '/usr/local/bin/deno' if binary == 'deno' else None
        ad.get_ytdlp_version = lambda force=False: '2026.06.09'
        ad._run_captured = lambda args, timeout=5: 'deno 2.7.0\n'
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad._run_captured = original_run_captured
        self.assertFalse(result['supported'])
        self.assertEqual(result['reason'], 'runtime-version-below-security-floor')
        self.assertEqual(result['minVersion'], ad.DENO_MIN_VERSION)
        self.assertEqual(result['securityMinVersion'], ad.DENO_SECURITY_MIN_VERSION)
        self.assertIn('security floor', result['advice'])

    def test_probe_deno_runtime_fails_closed_when_version_cannot_be_verified(self):
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        original_run_captured = ad._run_captured
        ad.shutil.which = lambda binary: '/usr/local/bin/deno' if binary == 'deno' else None
        ad.get_ytdlp_version = lambda force=False: '2026.06.09'
        ad._run_captured = lambda args, timeout=5: ''
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad._run_captured = original_run_captured
        self.assertTrue(result['installed'])
        self.assertIsNone(result['version'])
        self.assertFalse(result['supported'])
        self.assertTrue(result['stale'])
        self.assertIn('could not verify', result['advice'])
        self.assertEqual(result['reason'], 'runtime-version-unparseable')

    def test_deno_version_support_rejects_missing_and_unparseable_values(self):
        for version in (None, '', 'unknown', 'deno canary', '2.3'):
            with self.subTest(version=version):
                self.assertFalse(ad._is_deno_version_supported(version))
        self.assertFalse(ad._is_deno_version_supported('2.2.9'))
        self.assertFalse(ad._is_deno_version_supported('2.3.0'))
        self.assertFalse(ad._is_deno_version_supported('2.7.0'))
        self.assertTrue(ad._is_deno_version_supported(ad.DENO_SECURITY_MIN_VERSION))
        self.assertTrue(ad._is_deno_version_supported('3.0.0'))

    def test_probe_deno_runtime_surfaces_advice_when_needed_and_missing(self):
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        ad.shutil.which = lambda binary: None  # deno absent
        ad.get_ytdlp_version = lambda force=False: '2026.05.03.233852'
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
        self.assertFalse(result['installed'])
        self.assertIsNone(result['version'])
        self.assertIsNone(result['path'])
        self.assertTrue(result['ytdlpNeedsRuntime'])
        self.assertIn('Deno', result['advice'])
        self.assertIn('JavaScript runtime', result['advice'])

    def test_probe_deno_runtime_quiet_on_pre_cutoff_ytdlp(self):
        # Field installs running the pre-Deno-line yt-dlp don't need the
        # runtime — the pill should stay quiet (ytdlpNeedsRuntime=False)
        # AND advice should be empty regardless of Deno presence.
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        ad.shutil.which = lambda binary: None
        ad.get_ytdlp_version = lambda force=False: '2025.10.22'
        try:
            result = ad.probe_deno_runtime(force=True)
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
        self.assertFalse(result['ytdlpNeedsRuntime'])
        self.assertEqual(result['advice'], '')

    def test_probe_deno_runtime_cached_within_ttl(self):
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        call_count = {'n': 0}
        def counting_which(binary):
            call_count['n'] += 1
            return None
        ad.shutil.which = counting_which
        ad.get_ytdlp_version = lambda force=False: '2026.05.03'
        try:
            ad.probe_deno_runtime(force=True)
            ad.probe_deno_runtime()  # cached
            ad.probe_deno_runtime()  # cached
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
        # Auto checks Deno and Node once; subsequent reads use the cache.
        self.assertEqual(call_count['n'], 2)

    def test_probe_deno_runtime_does_not_hold_cache_lock_during_probes(self):
        first_started = threading.Event()
        release_first = threading.Event()
        second_finished = threading.Event()
        call_lock = threading.Lock()
        call_count = 0

        def slow_probe(args, timeout=5):
            nonlocal call_count
            with call_lock:
                call_count += 1
                call_number = call_count
            if call_number == 1:
                first_started.set()
                release_first.wait(timeout=2)
            if '--version' in args:
                return f'deno {ad.DENO_SECURITY_MIN_VERSION}\n'
            return ad.JS_RUNTIME_CAPABILITY_MARKER

        with mock.patch.object(
            ad, 'DENO_PATH', Path(tempfile.gettempdir()) / 'astra-missing-deno-probe.exe'
        ), mock.patch.object(
            ad.shutil, 'which', side_effect=lambda binary: (
                '/usr/local/bin/deno' if binary == 'deno' else None
            )
        ), mock.patch.object(
            ad, 'get_ytdlp_version', return_value='2026.07.04'
        ), mock.patch.object(ad, '_run_captured', side_effect=slow_probe):
            first = threading.Thread(
                target=lambda: ad.probe_deno_runtime(force=True), daemon=True
            )
            second = threading.Thread(
                target=lambda: (
                    ad.probe_deno_runtime(force=True), second_finished.set()
                ),
                daemon=True,
            )
            first.start()
            self.assertTrue(first_started.wait(timeout=1))
            second.start()
            self.assertTrue(
                second_finished.wait(timeout=1),
                "a second runtime probe must not wait on the first subprocess",
            )
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertGreaterEqual(call_count, 2)

    def test_configured_node_22_is_recognized_and_emitted_to_ytdlp(self):
        with mock.patch.object(ad, 'DENO_PATH', Path(tempfile.gettempdir()) / 'astra-missing-deno-probe.exe'), \
             mock.patch.object(ad.shutil, 'which', side_effect=lambda binary: (
                 'C:/Program Files/nodejs/node.exe' if binary == 'node' else None
             )), \
             mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.07.04'), \
             mock.patch.object(ad, '_run_captured', side_effect=lambda args, timeout=5: (
                 'v24.16.0' if '--version' in args else ad.JS_RUNTIME_CAPABILITY_MARKER
             )):
            result = ad.probe_javascript_runtime(force=True, configured_runtime='node')
        self.assertEqual(result['runtime'], 'node')
        self.assertEqual(result['version'], '24.16.0')
        self.assertTrue(result['supported'])
        self.assertTrue(result['ejsReady'])
        self.assertEqual(result['reason'], 'ready')
        self.assertEqual(ad.build_javascript_runtime_args(result), [
            '--no-js-runtimes', '--js-runtimes',
            'node:C:/Program Files/nodejs/node.exe',
        ])

    def test_supported_version_with_failed_execution_is_not_ejs_ready(self):
        def probe_output(args, timeout=5):
            if '--version' in args:
                return f'deno {ad.DENO_SECURITY_MIN_VERSION}'
            raise RuntimeError('execution blocked')

        with mock.patch.object(ad, 'DENO_PATH', Path(tempfile.gettempdir()) / 'astra-missing-deno-probe.exe'), \
             mock.patch.object(ad.shutil, 'which', side_effect=lambda binary: (
                 '/usr/local/bin/deno' if binary == 'deno' else None
             )), \
             mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.07.04'), \
             mock.patch.object(ad, '_run_captured', side_effect=probe_output):
            result = ad.probe_javascript_runtime(force=True, configured_runtime='deno')
        self.assertTrue(result['supported'])
        self.assertFalse(result['ejsReady'])
        self.assertEqual(result['reason'], 'runtime-execution-failed')
        self.assertEqual(ad.build_javascript_runtime_args(result), [])


class DenoProvisionTests(unittest.TestCase):
    """provision_deno auto-download and /provision-deno endpoint."""

    class _FakeResponse:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code
            self.text = payload.decode('utf-8', errors='replace') if isinstance(payload, bytes) else str(payload)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def iter_content(self, _chunk_size):
            yield self.payload

    def test_provision_deno_returns_none_on_network_failure(self):
        original_get = ad.first_party_http_get
        ad.first_party_http_get = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
        original_path = ad.DENO_PATH
        ad.DENO_PATH = Path('/nonexistent/deno.exe')
        try:
            result = ad.provision_deno()
            self.assertIsNone(result)
        finally:
            ad.first_party_http_get = original_get
            ad.DENO_PATH = original_path

    def test_provision_deno_endpoint_requires_token(self):
        config = FakeConfig({"ServerToken": "f" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().post("/provision-deno")
        self.assertEqual(resp.status_code, 403)

    def test_provision_deno_endpoint_omits_local_install_path(self):
        token = "f" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        runtime = {
            "runtime": "deno",
            "installed": True,
            "supported": True,
            "ejsReady": True,
            "path": "C:/Users/tester/AppData/Local/Astra Downloader/deno.exe",
        }
        api = ad.create_api(config, manager, FakeHistory())
        with mock.patch.object(ad, "provision_deno", return_value=runtime["path"]), \
                mock.patch.object(ad, "probe_javascript_runtime", return_value=runtime):
            body = api.test_client().post(
                "/provision-deno",
                headers={"X-Auth-Token": token},
            ).get_json()

        self.assertTrue(body["ok"])
        self.assertNotIn("path", body)
        self.assertNotIn("path", body["denoRuntime"])

    def test_provision_deno_requires_sha256_sidecar_before_extracting(self):
        original_path = ad.DENO_PATH
        original_dir = ad.DENO_DIR
        with tempfile.TemporaryDirectory() as tmp:
            ad.DENO_DIR = Path(tmp)
            ad.DENO_PATH = ad.DENO_DIR / 'deno.exe'
            with mock.patch.object(ad, 'fetch_expected_sha256', return_value=None), \
                    mock.patch.object(ad, 'first_party_http_get') as get_mock:
                result = ad.provision_deno()
            self.assertIsNone(result)
            get_mock.assert_not_called()
            error = ad.get_last_deno_provision_error()
            self.assertEqual(error['code'], 'deno-sha256-sidecar-missing')
            self.assertFalse(ad.DENO_PATH.exists())
        ad.DENO_PATH = original_path
        ad.DENO_DIR = original_dir

    def test_provision_deno_rejects_sha256_mismatch_and_deletes_archive(self):
        original_path = ad.DENO_PATH
        original_dir = ad.DENO_DIR
        with tempfile.TemporaryDirectory() as tmp:
            ad.DENO_DIR = Path(tmp)
            ad.DENO_PATH = ad.DENO_DIR / 'deno.exe'
            zip_path = Path(tmp) / 'deno.zip'
            with zipfile.ZipFile(zip_path, 'w') as zf:
                zf.writestr('deno.exe', b'MZ fake deno')
            payload = zip_path.read_bytes()
            with mock.patch.object(ad, 'fetch_expected_sha256', return_value='0' * 64), \
                    mock.patch.object(ad, 'first_party_http_get', return_value=self._FakeResponse(payload)):
                result = ad.provision_deno()
            self.assertIsNone(result)
            error = ad.get_last_deno_provision_error()
            self.assertEqual(error['code'], 'deno-sha256-verification-failed')
            self.assertFalse(ad.DENO_PATH.exists())
            self.assertEqual(list(ad.DENO_DIR.glob('.deno.*.zip')), [])
        ad.DENO_PATH = original_path
        ad.DENO_DIR = original_dir

    def test_provision_deno_endpoint_returns_structured_failure_code(self):
        config = FakeConfig({"ServerToken": "f" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        with mock.patch.object(ad, 'provision_deno', return_value=None), \
                mock.patch.object(ad, 'get_last_deno_provision_error', return_value={
                    'code': 'deno-sha256-verification-failed',
                    'message': 'checksum mismatch',
                }):
            resp = api.test_client().post(
                "/provision-deno",
                headers={'X-MDL-Token': 'f' * 32},
            )
        self.assertEqual(resp.status_code, 500)
        body = resp.get_json() or {}
        self.assertFalse(body['ok'])
        self.assertEqual(body['code'], 'deno-sha256-verification-failed')
        self.assertIn('checksum', body['error'])

    def test_probe_includes_source_field(self):
        ad.reset_deno_runtime_cache()
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        ad.shutil.which = lambda binary: '/usr/local/bin/deno' if binary == 'deno' else None
        ad.get_ytdlp_version = lambda force=False: '2026.05.03'
        ad._run_captured_orig = ad._run_captured
        ad._run_captured = lambda args, timeout=5: f'deno {ad.DENO_SECURITY_MIN_VERSION}\n'
        original_deno_path = ad.DENO_PATH
        ad.DENO_PATH = Path('/nonexistent/deno.exe')
        try:
            result = ad.probe_deno_runtime(force=True)
            self.assertIn('source', result)
            self.assertEqual(result['source'], 'system')
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad._run_captured = ad._run_captured_orig
            ad.DENO_PATH = original_deno_path
            ad.reset_deno_runtime_cache()


class SabrReadinessTests(unittest.TestCase):
    """SABR support pill: derived by the async readiness probe, refreshed on
    every probe run — never a synchronous yt-dlp probe on the GUI thread."""

    def _window(self):
        calls = []
        win = types.SimpleNamespace(
            _set_readiness=lambda key, text, tone="neutral", tooltip="": calls.append((key, text, tone)),
            # The readiness method also refreshes the browser-impersonation
            # choices; this fixture only exercises the status rows.
            _apply_impersonate_targets=lambda _targets: None,
            # ... and the managed-tool version pins, which have their own
            # tests; this fixture only exercises the status rows.
            _apply_managed_binaries=lambda _inventory: None,
            _dependencies={
                'evaluate_sabr_support': lambda v: self._sabr_result,
                'managed_binary_state': lambda _path: 'ok',
                'MANAGED_BINARY_ANTIVIRUS_ADVICE': ad.MANAGED_BINARY_ANTIVIRUS_ADVICE,
                'INSTALL_DIR': ad.INSTALL_DIR,
                'YTDLP_PATH': ad.YTDLP_PATH,
                'FFMPEG_PATH': ad.FFMPEG_PATH,
            },
        )
        win._value = types.MethodType(
            gui_module_for_tests().MainWindowCore._value, win
        )
        win._set_tool_readiness = types.MethodType(
            gui_module_for_tests().MainWindowCore._set_tool_readiness, win
        )
        return win, calls

    def test_apply_readiness_updates_sabr_from_ytdlp_version(self):
        win, calls = self._window()
        self._sabr_result = "supported"
        ad.MainWindow._apply_readiness(win, {"ytDlp": "2026.07.04", "ffmpeg": "8.1.2"})
        self.assertIn(("sabr", "Supported", "success"), calls)
        calls.clear()
        self._sabr_result = "limited"
        ad.MainWindow._apply_readiness(win, {"ytDlp": "2026.07.04", "ffmpeg": "8.1.2"})
        self.assertIn(("sabr", "Limited", "warning"), calls)

    def test_apply_readiness_survives_a_broken_sabr_evaluator(self):
        win, calls = self._window()
        def boom(_v):
            raise RuntimeError("no")
        win._dependencies['evaluate_sabr_support'] = boom
        ad.MainWindow._apply_readiness(win, {"ytDlp": "2026.07.04", "ffmpeg": "8.1.2"})
        self.assertIn(("sabr", "Limited", "warning"), calls)


class NonYoutubeRuntimeGateTests(unittest.TestCase):
    """The Deno/JS-runtime hard gate is a YouTube requirement, not a global one."""

    def _client(self, token):
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        return api.test_client(), manager

    def test_missing_js_runtime_blocks_youtube_but_not_other_sites(self):
        token = "r" * 32
        client, manager = self._client(token)
        unusable = {
            'runtime': None,
            'installed': False,
            'supported': False,
            'ejsReady': False,
            'ytdlpNeedsRuntime': True,
            'reason': 'runtime-not-installed',
            'advice': 'Install Deno.',
        }
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value=unusable), \
             mock.patch.object(manager, 'start_download', return_value=('dl_ok', None)):
            youtube = client.post(
                "/download",
                json={"url": "https://www.youtube.com/watch?v=abc"},
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(youtube.status_code, 422)
            self.assertEqual(youtube.get_json()["code"], "js-runtime-missing")

            other = client.post(
                "/download",
                json={"url": "https://www.reddit.com/r/videos/comments/abc/clip/"},
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(
                other.status_code, 200,
                "Reddit extraction never needs the YouTube n/sig runtime",
            )


class QuarantinedBinaryTests(unittest.TestCase):
    """A quarantine stub is present, unusable, and must not read as installed."""

    def _binary(self, tmpdir, name, size):
        path = Path(tmpdir) / name
        path.write_bytes(b"\0" * size)
        return path

    # ── The classification ───────────────────────────────────────────────

    def test_a_zero_byte_stub_is_damaged_not_missing(self):
        # The distinction is the whole point: `.exists()` is true for a stub,
        # so every gate written against it lets an unusable tool through.
        with tempfile.TemporaryDirectory() as tmpdir:
            stub = self._binary(tmpdir, "yt-dlp.exe", 0)
            self.assertTrue(stub.exists())
            self.assertEqual(ad.managed_binary_state(stub), "damaged")
            self.assertFalse(ad.managed_binary_usable(stub))

    def test_a_truncated_binary_is_damaged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stub = self._binary(tmpdir, "ffmpeg.exe", 4096)
            self.assertEqual(ad.managed_binary_state(stub), "damaged")

    def test_a_whole_binary_is_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            real = self._binary(tmpdir, "yt-dlp.exe", ad.MANAGED_BINARY_MIN_BYTES)
            self.assertEqual(ad.managed_binary_state(real), "ok")
            self.assertTrue(ad.managed_binary_usable(real))

    def test_an_absent_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                ad.managed_binary_state(Path(tmpdir) / "nothing.exe"), "missing"
            )

    def test_a_directory_is_not_a_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(ad.managed_binary_state(tmpdir), "missing")

    def test_the_installed_binaries_clear_the_floor(self):
        # The floor must not be so high that a real install reads as damaged.
        for path in (ad.YTDLP_PATH, ad.FFMPEG_PATH):
            if not Path(path).exists():
                continue
            with self.subTest(binary=Path(path).name):
                self.assertEqual(ad.managed_binary_state(path), "ok")

    # ── What setup does about it ─────────────────────────────────────────

    def test_setup_refetches_a_stub_and_names_antivirus(self):
        logged = []
        persisted = []
        worker = types.SimpleNamespace(
            log=types.SimpleNamespace(emit=logged.append),
            _dependencies={
                'managed_binary_state': ad.managed_binary_state,
                'write_persistent_log': persisted.append,
            },
        )
        core = gui_module_for_tests().SetupWorkerCore
        worker._value = types.MethodType(core._value, worker)
        worker._report_managed_binary = types.MethodType(
            core._report_managed_binary, worker
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            worker._dependencies['MANAGED_BINARY_ANTIVIRUS_ADVICE'] = (
                ad.MANAGED_BINARY_ANTIVIRUS_ADVICE
            )
            worker._dependencies['INSTALL_DIR'] = tmpdir
            stub = self._binary(tmpdir, "yt-dlp.exe", 0)
            state = worker._report_managed_binary(stub, "yt-dlp")
        self.assertEqual(state, "damaged")
        message = " ".join(logged)
        self.assertIn("present but unusable", message)
        self.assertIn("Antivirus", message)
        self.assertIn(tmpdir, message)
        # The explanation has to outlive the session's log panel.
        self.assertEqual(len(persisted), 1)

    def test_setup_says_nothing_about_antivirus_for_a_clean_install(self):
        logged = []
        worker = types.SimpleNamespace(
            log=types.SimpleNamespace(emit=logged.append),
            _dependencies={
                'managed_binary_state': ad.managed_binary_state,
                'write_persistent_log': lambda *_args: None,
                'MANAGED_BINARY_ANTIVIRUS_ADVICE': ad.MANAGED_BINARY_ANTIVIRUS_ADVICE,
                'INSTALL_DIR': '',
            },
        )
        core = gui_module_for_tests().SetupWorkerCore
        worker._value = types.MethodType(core._value, worker)
        worker._report_managed_binary = types.MethodType(
            core._report_managed_binary, worker
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "yt-dlp.exe"
            self.assertEqual(worker._report_managed_binary(missing, "yt-dlp"),
                             "missing")
        self.assertEqual(logged, [])

    def test_setup_refetches_a_stale_ffmpeg_snapshot(self):
        logged = []
        persisted = []
        worker = types.SimpleNamespace(
            force_ffmpeg=False,
            config={},
            log=types.SimpleNamespace(emit=logged.append),
            _dependencies={
                'check_ffmpeg_capabilities': lambda **_kwargs: {
                    'current': False,
                    'comparison': 'snapshot-date',
                    'message': 'old snapshot',
                },
                'managed_binary_pin_for': lambda _config, _name: '',
                'get_ffmpeg_version': lambda: 'N-1-g0-20260101',
                'write_persistent_log': persisted.append,
            },
        )
        core = gui_module_for_tests().SetupWorkerCore
        worker._ffmpeg_needs_refresh = types.MethodType(
            core._ffmpeg_needs_refresh, worker
        )
        self.assertTrue(worker._ffmpeg_needs_refresh('ok'))
        self.assertTrue(any('security floor' in message for message in logged))
        self.assertEqual(len(persisted), 1)

        # A pinned ffmpeg that is the installed one stays, and says why.
        worker._dependencies['managed_binary_pin_for'] = (
            lambda _config, _name: 'N-1-g0-20260101'
        )
        logged.clear()
        persisted.clear()
        self.assertFalse(worker._ffmpeg_needs_refresh('ok'))
        self.assertTrue(any('pinned to' in message for message in logged))

        # A pin never keeps a binary that cannot run.
        self.assertTrue(worker._ffmpeg_needs_refresh('damaged'))

    # ── What the readiness row says ──────────────────────────────────────

    def _readiness_window(self, state):
        calls = []
        win = types.SimpleNamespace(
            _set_readiness=lambda key, text, tone="neutral", tooltip="":
                calls.append((key, text, tone, tooltip)),
            _dependencies={
                'managed_binary_state': lambda _path: state,
                'MANAGED_BINARY_ANTIVIRUS_ADVICE': ad.MANAGED_BINARY_ANTIVIRUS_ADVICE,
                'INSTALL_DIR': r"C:\Install\Dir",
            },
        )
        core = gui_module_for_tests().MainWindowCore
        win._value = types.MethodType(core._value, win)
        win._set_tool_readiness = types.MethodType(core._set_tool_readiness, win)
        return win, calls

    def test_a_stub_reads_as_removed_and_names_the_exclusion_path(self):
        win, calls = self._readiness_window("damaged")
        win._set_tool_readiness("ytDlp", "", "ignored")
        key, text, tone, tooltip = calls[0]
        self.assertEqual((key, text, tone), ("ytDlp", "Removed?", "danger"))
        self.assertIn("Antivirus", tooltip)
        self.assertIn(r"C:\Install\Dir", tooltip)

    def test_a_tool_that_was_never_installed_still_reads_as_missing(self):
        win, calls = self._readiness_window("missing")
        win._set_tool_readiness("ffmpeg", "", "ignored")
        self.assertEqual(calls[0][:3], ("ffmpeg", "Missing", "danger"))

    def test_a_working_tool_reports_its_version(self):
        win, calls = self._readiness_window("ok")
        win._set_tool_readiness("ytDlp", "2026.08.04", "ignored")
        self.assertEqual(calls[0][:3], ("ytDlp", "2026.08.04", "success"))


class WhisperModelProvisioningTests(unittest.TestCase):
    """The model path is atomic and never trusted without its pinned digest."""

    def test_a_checksum_failure_removes_the_downloaded_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "ggml-tiny-q5_1.bin"

            def fake_download(_url, path, **_kwargs):
                Path(path).write_bytes(b"bad model")

            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "INSTALL_DIR", root), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=None), \
                    mock.patch.object(ad, "verify_file_sha256", side_effect=RuntimeError("bad digest")), \
                    mock.patch.object(ad, "write_persistent_log"):
                self.assertIsNone(ad.provision_whisper_model())
            self.assertFalse(model.exists())

    def test_a_failed_refresh_keeps_the_previous_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "ggml-tiny-q5_1.bin"
            previous = b"previous model"
            model.write_bytes(previous)

            def fake_download(_url, path, **_kwargs):
                Path(path).write_bytes(b"bad model")

            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "INSTALL_DIR", root), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "managed_binary_state",
                                      return_value="damaged"), \
                    mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=None), \
                    mock.patch.object(ad, "verify_file_sha256",
                                      side_effect=RuntimeError("bad digest")), \
                    mock.patch.object(ad, "write_persistent_log"):
                self.assertIsNone(ad.provision_whisper_model())

            self.assertEqual(model.read_bytes(), previous)
            self.assertEqual(list(root.glob(".ggml-tiny-q5_1.bin.*.verified")), [])

    def test_a_download_is_verified_before_it_is_reported_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "ggml-tiny-q5_1.bin"
            calls = []

            def fake_download(url, path, **kwargs):
                calls.append((url, Path(path), kwargs))
                Path(path).write_bytes(b"verified model")

            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "INSTALL_DIR", root), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=None), \
                    mock.patch.object(ad, "verify_file_sha256", return_value=True), \
                    mock.patch.object(ad, "write_persistent_log"):
                result = ad.provision_whisper_model()
            self.assertEqual(result, str(model))
            self.assertEqual(calls[0][0], ad.WHISPER_MODEL_URL)
            self.assertIn(
                f"resolve/{ad.WHISPER_MODEL_REVISION}/",
                calls[0][0],
            )
            self.assertNotIn("resolve/main/", calls[0][0])
            self.assertNotEqual(calls[0][1], model)
            self.assertEqual(calls[0][2]["max_bytes"], ad.HELPER_DOWNLOAD_MAX_BYTES)


class WhisperRuntimeProbeTests(unittest.TestCase):
    """A size-valid CLI is not trusted until its SRT capability is observable."""

    def _binary(self, root, size=1):
        path = Path(root) / "whisper-cli.exe"
        path.write_bytes(b"x" * size)
        return path

    def test_missing_runtime_is_reported_before_process_probe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ad.probe_whisper_runtime(Path(tmpdir) / "missing.exe", 1)
        self.assertEqual(result["state"], "missing")
        self.assertFalse(result["usable"])
        self.assertEqual(result["reason"], "missing")

    def test_present_runtime_without_srt_switch_is_not_usable(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return types.SimpleNamespace(stdout="Usage: whisper-cli", stderr="", returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._binary(tmpdir)
            result = ad.probe_whisper_runtime(path, 1, runner=runner)
        self.assertEqual(result["state"], "ok")
        self.assertFalse(result["usable"])
        self.assertEqual(result["reason"], "capability-missing")
        self.assertEqual(calls[0][0], [str(path), "--help"])

    def test_help_output_proves_the_srt_capability(self):
        def runner(_args, **_kwargs):
            return types.SimpleNamespace(
                stdout="--output-srt, -osrt  output SRT subtitles",
                stderr="",
                returncode=0,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ad.probe_whisper_runtime(self._binary(tmpdir), 1, runner=runner)
        self.assertTrue(result["usable"])
        self.assertEqual(result["reason"], "ready")


class WhisperRuntimeProvisioningTests(unittest.TestCase):
    """The multi-file whisper.cpp runtime is verified and swapped atomically."""

    def _archive(self, path):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("build/bin/Release/whisper-cli.exe", b"cli")
            archive.writestr("build/bin/Release/whisper.dll", b"dll")

    def test_archive_provisions_the_cli_and_sibling_dll(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "whisper"
            runtime_path = runtime_dir / "whisper-cli.exe"

            def fake_download(_url, path, **_kwargs):
                self._archive(path)

            def fake_probe(path, *_args, **_kwargs):
                return {"usable": Path(path).is_file(), "path": str(path)}

            with mock.patch.object(ad, "INSTALL_DIR", root), \
                    mock.patch.object(ad, "WHISPER_BIN_DIR", runtime_dir), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", runtime_path), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=None), \
                    mock.patch.object(ad, "verify_file_sha256", return_value=True), \
                    mock.patch.object(ad, "probe_whisper_runtime", side_effect=fake_probe), \
                    mock.patch.object(ad, "write_persistent_log"):
                result = ad.provision_whisper_runtime()

            self.assertEqual(result, str(runtime_path))
            self.assertTrue(runtime_path.is_file())
            self.assertTrue((runtime_dir / "whisper.dll").is_file())

    def test_checksum_failure_keeps_an_existing_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime_dir = root / "whisper"
            runtime_path = runtime_dir / "whisper-cli.exe"
            runtime_dir.mkdir()
            runtime_path.write_bytes(b"verified old runtime")

            def fake_probe(_path, *_args, **_kwargs):
                return {"usable": False}

            with mock.patch.object(ad, "INSTALL_DIR", root), \
                    mock.patch.object(ad, "WHISPER_BIN_DIR", runtime_dir), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", runtime_path), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "download_file_atomic", lambda _u, path, **_k: Path(path).write_bytes(b"bad")), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=None), \
                    mock.patch.object(ad, "verify_file_sha256", side_effect=RuntimeError("bad digest")), \
                    mock.patch.object(ad, "probe_whisper_runtime", side_effect=fake_probe), \
                    mock.patch.object(ad, "write_persistent_log"):
                self.assertIsNone(ad.provision_whisper_runtime())
            self.assertEqual(runtime_path.read_bytes(), b"verified old runtime")


class SubtitleAgainstTheRealBinaryTests(unittest.TestCase):
    """The flags this app compiles do what it claims, on the installed yt-dlp.

    Offline and deterministic: a --load-info-json fixture holding a manual EN
    track, an auto EN track and an auto ES track, served over loopback.
    """

    MANUAL = b"WEBVTT\n\n00:00.000 --> 00:01.000\nMANUAL-TRACK\n"
    AUTO_EN = b"WEBVTT\n\n00:00.000 --> 00:01.000\nAUTO-EN\n"
    AUTO_ES = b"WEBVTT\n\n00:00.000 --> 00:01.000\nAUTO-ES\n"

    @classmethod
    def setUpClass(cls):
        import http.server
        cls.bodies = {
            "/manual-en.vtt": cls.MANUAL,
            "/auto-en.vtt": cls.AUTO_EN,
            "/auto-es.vtt": cls.AUTO_ES,
        }
        bodies = cls.bodies

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = bodies.get(self.path)
                self.send_response(200 if body else 404)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def log_message(self, *_args):
                pass

        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def _run(self, config, subtitles_only=False):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        info = {
            "id": "p1", "title": "fixture", "ext": "mp4",
            "extractor": "generic", "extractor_key": "Generic",
            "webpage_url": "https://example.com/p", "_type": "video",
            "formats": [{"format_id": "0", "url": f"{self.base}/none.mp4",
                         "ext": "mp4", "protocol": "http"}],
            "subtitles": {"en": [{"ext": "vtt",
                                  "url": f"{self.base}/manual-en.vtt"}]},
            "automatic_captions": {
                "en": [{"ext": "vtt", "url": f"{self.base}/auto-en.vtt"}],
                "es": [{"ext": "vtt", "url": f"{self.base}/auto-es.vtt"}],
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            info_path = tmp / "p.info.json"
            info_path.write_text(json.dumps(info), encoding="utf-8")
            args = [str(ytdlp), "--ignore-config", "--load-info-json",
                    str(info_path), "--skip-download", "--color", "no_color",
                    "-o", str(tmp / "%(title)s.%(ext)s")]
            args += [
                arg for arg in ad.build_subtitle_args(
                    config, subtitles_only=subtitles_only)
                if arg != "--embed-subs"
            ]
            proc = subprocess.run(args, capture_output=True, text=True,
                                  timeout=180)
            written = {}
            for path in tmp.iterdir():
                if path.suffix in {".vtt", ".srt"}:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    marker = next(
                        (m for m in ("MANUAL-TRACK", "AUTO-EN", "AUTO-ES")
                         if m in text), "?")
                    written[path.name] = marker
            return proc, written

    def _config(self, **overrides):
        config = ad.sanitize_config({"EmbedSubs": True, "SubLangs": "en,es"})
        config["SubtitleSleepSeconds"] = 0
        config.update(overrides)
        return config

    def test_prefer_manual_takes_the_creator_track_and_fills_the_gap(self):
        proc, written = self._run(self._config(SubtitleMode="prefer-manual"))
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertEqual(written,
                         {"fixture.en.vtt": "MANUAL-TRACK",
                          "fixture.es.vtt": "AUTO-ES"})

    def test_creator_only_leaves_out_the_language_that_has_no_creator_track(self):
        proc, written = self._run(self._config(SubtitleMode="manual"))
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertEqual(written, {"fixture.en.vtt": "MANUAL-TRACK"})

    def test_auto_only_takes_the_machine_transcript_even_where_a_creator_track_exists(self):
        proc, written = self._run(self._config(SubtitleMode="auto"))
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertEqual(written,
                         {"fixture.en.vtt": "AUTO-EN",
                          "fixture.es.vtt": "AUTO-ES"})

    def test_conversion_rewrites_every_track_to_the_chosen_format(self):
        proc, written = self._run(
            self._config(SubtitleMode="prefer-manual", SubtitleFormat="srt"))
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertEqual(sorted(written), ["fixture.en.srt", "fixture.es.srt"])
        self.assertEqual(written["fixture.en.srt"], "MANUAL-TRACK")

    def test_all_language_selection_is_accepted_by_the_offline_fixture(self):
        proc, written = self._run(
            self._config(SubLangs="all,live_chat"), subtitles_only=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertEqual(
            written,
            {"fixture.en.vtt": "MANUAL-TRACK",
             "fixture.es.vtt": "AUTO-ES"},
        )

    def test_a_subtitles_only_run_writes_no_media(self):
        proc, written = self._run(
            ad.sanitize_config({"EmbedSubs": False}), subtitles_only=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        self.assertTrue(written)
        self.assertNotIn("fixture.mp4", written)


class StartMenuIntegrationTests(unittest.TestCase):
    """The companion publishes itself in the Start Menu and takes it back on
    uninstall. Without it the only ways back in are the tray, a desktop icon,
    and the logon task — none of them discoverable by searching the name."""

    def test_start_menu_dir_is_per_user(self):
        with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\tester\AppData\Roaming"}):
            programs = ad.start_menu_programs_dir()
        self.assertEqual(programs.name, "Programs")
        self.assertIn("Start Menu", programs.parts)
        self.assertIn("Roaming", programs.parts,
                      "an unelevated install must not write an all-users entry")

    def test_start_menu_dir_falls_back_without_appdata(self):
        # Only APPDATA goes missing in practice; clearing the whole environment
        # would also take USERPROFILE and test a state Windows never presents.
        environment = {k: v for k, v in os.environ.items() if k != "APPDATA"}
        with mock.patch.dict(os.environ, environment, clear=True):
            programs = ad.start_menu_programs_dir()
        self.assertEqual(programs.name, "Programs")
        self.assertIn("Roaming", programs.parts)

    def test_shortcut_command_carries_target_icon_and_arguments(self):
        command = ad.build_shortcut_command(
            Path(r"C:\Menu\Astra Downloader.lnk"),
            r"C:\Install\AstraDownloader.exe",
            ["-Background"],
        )
        self.assertIn("WScript.Shell", command)
        self.assertIn("AstraDownloader.exe", command)
        self.assertIn("-Background", command)
        self.assertIn("Astra Downloader.lnk", command)
        self.assertIn("$sc.Save()", command)

    def test_shortcut_command_quotes_paths_containing_apostrophes(self):
        # PowerShell single-quoted strings escape an apostrophe by doubling it;
        # a naive interpolation would end the string early and change the
        # command that runs.
        command = ad.build_shortcut_command(
            Path(r"C:\Users\O'Brien\Astra Downloader.lnk"),
            r"C:\Users\O'Brien\AstraDownloader.exe",
            [],
        )
        self.assertIn("O''Brien", command)
        self.assertNotIn("'C:\\Users\\O'Brien", command)

    def test_integrations_register_the_start_menu_entry(self):
        calls = []
        with mock.patch.object(ad, 'register_desktop_shortcut',
                               lambda *a: calls.append('desktop')), \
             mock.patch.object(ad, 'register_start_menu_shortcut',
                               lambda *a: calls.append('start-menu')), \
             mock.patch.object(ad, 'register_startup_task', lambda *a: calls.append('task')), \
             mock.patch.object(ad, 'register_protocol_handlers', lambda *a: None), \
             mock.patch.object(ad, 'register_uninstall_entry', lambda *a: None), \
             mock.patch.object(ad, 'register_native_messaging_hosts', lambda *a: None), \
             mock.patch.object(ad, '_get_integrations_stamp', lambda: ''), \
             mock.patch.object(ad, '_set_integrations_stamp', lambda: None), \
             mock.patch.object(ad, 'launch_command_parts',
                               lambda prefer_installed=True: ("C:\\x.exe", [])):
            ad.ensure_system_integrations()
        self.assertIn('start-menu', calls,
                      "the Start Menu entry must ride the same integration pass")

    def test_start_menu_shortcut_is_written_and_removed(self):
        if os.name != 'nt':
            self.skipTest("Windows shortcut integration")
        with tempfile.TemporaryDirectory() as tmpdir:
            programs = Path(tmpdir) / "Programs"
            target = Path(tmpdir) / "AstraDownloader.exe"
            target.write_bytes(b"MZ stub")

            with mock.patch.object(ad, 'start_menu_programs_dir', lambda: programs):
                ad.register_start_menu_shortcut(str(target), [])
                lnk = programs / ad.SHORTCUT_NAME
                self.assertTrue(lnk.exists(), "the .lnk should exist after registration")
                self.assertGreater(lnk.stat().st_size, 0)

                lnk.unlink()
                self.assertFalse(lnk.exists())


class ManagedBinaryPinTests(unittest.TestCase):
    """A pin freezes a managed binary; a rollback puts the previous one back."""

    def test_a_pin_below_a_declared_security_floor_is_refused_by_name(self):
        for name, version, floor in (
            ("deno", "2.7.0", "2.8.1"),
            ("quickjs", "0.15.0", "0.16.1"),
            ("ffmpeg", "8.0.1", "8.1.2"),
        ):
            with self.subTest(binary=name):
                decision = ad.evaluate_binary_pin(name, version)
                self.assertFalse(decision["ok"])
                self.assertEqual(decision["reason"], "pin-below-security-floor")
                self.assertEqual(decision["floor"], floor)
                self.assertIn(floor, decision["message"])

    def test_a_pin_at_or_above_the_floor_is_accepted(self):
        for name, version in (
            ("deno", "2.8.1"), ("quickjs", "0.17.0"), ("ffmpeg", "8.2.0"),
            # No version floor is declared for these, so any well-shaped
            # release is pinnable — including an old one, which is the point.
            ("yt-dlp", "2026.07.04"), ("whisper", "1.7.4"),
        ):
            with self.subTest(binary=name):
                self.assertTrue(ad.evaluate_binary_pin(name, version)["ok"])

    def test_an_ffmpeg_snapshot_is_measured_against_the_dated_floor(self):
        # FFmpeg-Builds master snapshots carry no semver at all, so a semver
        # comparison reads every one of them as "below 8.1.2".
        fresh = ad.evaluate_binary_pin("ffmpeg", "N-126229-gf101fce22d-20260820")
        self.assertTrue(fresh["ok"], fresh)
        stale = ad.evaluate_binary_pin("ffmpeg", "N-120000-gabcdef123-20260101")
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["reason"], "pin-below-security-floor")
        self.assertEqual(stale["floor"], ad._FFMPEG_MIN_SNAPSHOT_DATE)

    def test_a_shape_that_is_not_a_version_is_refused_before_any_comparison(self):
        for value in ("../../evil.exe", "--update-to", "; rm -rf", "abc"):
            with self.subTest(value=value):
                decision = ad.evaluate_binary_pin("ffmpeg", value)
                self.assertFalse(decision["ok"])
                self.assertEqual(decision["reason"], "pin-version-unreadable")
        self.assertEqual(
            ad.evaluate_binary_pin("notatool", "1.0")["reason"],
            "unknown-managed-binary",
        )

    def test_clearing_a_pin_is_always_allowed(self):
        decision = ad.evaluate_binary_pin("deno", "")
        self.assertTrue(decision["ok"])
        self.assertEqual(decision["version"], "")

    def test_a_stored_pin_that_the_floor_has_overtaken_is_dropped_on_read(self):
        # The floor rises between releases. A pin that would be refused today
        # must not keep holding a binary below it.
        config = FakeConfig({"ManagedBinaryPins": {
            "deno": "2.7.0", "yt-dlp": "2026.07.04",
        }})
        self.assertEqual(
            ad.active_managed_binary_pins(config), {"yt-dlp": "2026.07.04"},
        )

    def test_config_sanitisation_keeps_only_well_shaped_pins(self):
        # config.py checks the shape and nothing else. A version no publisher
        # ships survives here and is simply never matched; a version below a
        # floor is dropped one layer up, by active_managed_binary_pins.
        self.assertEqual(
            ad.sanitize_config({"ManagedBinaryPins": {
                "yt-dlp": "2026.07.04",
                "ffmpeg": "../../evil",
                "unknown-tool": "1.0",
                "deno": 5,
            }})["ManagedBinaryPins"],
            {"yt-dlp": "2026.07.04", "deno": "5"},
        )
        self.assertEqual(ad.sanitize_config({})["ManagedBinaryPins"], {})

    def test_config_and_health_agree_on_which_binaries_exist(self):
        # config.py owns the schema and health.py owns the floors; neither may
        # gain a binary the other does not know.
        self.assertEqual(
            set(ad.MANAGED_BINARY_PIN_NAMES), set(ad.MANAGED_BINARY_NAMES),
        )
        self.assertTrue(
            set(ad.MANAGED_BINARY_FLOORS).issubset(set(ad.MANAGED_BINARY_NAMES))
        )

    def test_setting_a_pin_writes_it_and_a_refusal_writes_nothing(self):
        stored = {}

        class PinConfig(FakeConfig):
            def update(self, mapping):
                stored.update(mapping)
                self.data.update(mapping)
                return True

        config = PinConfig({"ManagedBinaryPins": {}})
        with mock.patch.object(ad, "write_persistent_log", return_value=None):
            accepted = ad.set_managed_binary_pin(config, "yt-dlp", "2026.07.04")
            self.assertTrue(accepted["ok"])
            self.assertEqual(
                stored["ManagedBinaryPins"], {"yt-dlp": "2026.07.04"})

            refused = ad.set_managed_binary_pin(config, "deno", "2.0.0")
            self.assertFalse(refused["ok"])
            self.assertEqual(
                stored["ManagedBinaryPins"], {"yt-dlp": "2026.07.04"})

            cleared = ad.set_managed_binary_pin(config, "yt-dlp", "")
            self.assertTrue(cleared["ok"])
            self.assertEqual(stored["ManagedBinaryPins"], {})

    def test_an_unprobeable_binary_is_never_mistaken_for_a_pinned_one(self):
        # An antivirus quarantine leaves a stub that reports no version. With
        # no pin stored, `managed_binary_pin_for` also returns '', and the
        # equality that decides "leave it alone" used to be '' == ''.
        config = FakeConfig({"ManagedBinaryPins": {}})
        self.assertEqual(ad.managed_binary_pin_for(config, "deno"), "")
        source = inspect.getsource(ad.provision_deno)
        self.assertIn(
            "if version and managed_binary_pin_for(config, 'deno') == version:",
            source,
            "an empty version must not satisfy an empty pin",
        )

    def test_the_digest_is_withheld_until_the_pinned_version_is_installed(self):
        # A pin is stored the moment it is chosen; the binary moves on the
        # next update, or never if that update fails. Publishing the digest
        # of whatever is on disk names a release the row does not.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "yt-dlp.exe"
            path.write_bytes(b"installed" + b"\0" * (2 * 1024 * 1024))
            config = FakeConfig({"ManagedBinaryPins": {"yt-dlp": "2026.07.04"}})

            def rows(installed):
                with mock.patch.object(ad, "managed_binary_paths",
                                       return_value={"yt-dlp": path}), \
                        mock.patch.object(ad, "probe_managed_binary_version",
                                          return_value=installed), \
                        mock.patch.object(ad, "managed_binary_rollback_path",
                                          return_value=None):
                    return {row["name"]: row
                            for row in ad.managed_binary_inventory(config)}

            not_yet = rows("2026.08.19")
            self.assertEqual(not_yet["yt-dlp"]["pinned"], "2026.07.04")
            self.assertEqual(not_yet["yt-dlp"]["sha256"], "")
            arrived = rows("2026.07.04")
            self.assertEqual(arrived["yt-dlp"]["sha256"], ad._compute_sha256(path))

    def test_every_rollbackable_binary_has_a_path_that_retains_a_copy(self):
        # The panel offers Roll back for all five. A binary whose replacement
        # path never retains a copy leaves that button disabled forever.
        sources = (inspect.getsource(ad)
                   + inspect.getsource(gui_module_for_tests())).splitlines()
        retaining = {
            name for name in ad.MANAGED_BINARY_NAMES
            if any("retain_managed_binary_rollback" in line and f"'{name}'" in line
                   for line in sources)
        }
        # yt-dlp keeps its own last-known-good inside the updater rather than
        # through the shared helper.
        retaining.add("yt-dlp")
        self.assertEqual(
            retaining, set(ad.MANAGED_BINARY_NAMES),
            "a tool the pin UI can roll back must retain the copy it replaces",
        )

    def test_the_ytdlp_updater_targets_the_pin_instead_of_the_alias(self):
        source = inspect.getsource(ad._run_ytdlp_self_update)
        self.assertIn("managed_binary_pin_for(config, 'yt-dlp')", source)
        self.assertIn("f'{channel}@{target}'", source)

    def test_the_auto_update_stops_asking_once_the_pin_is_satisfied(self):
        ran = []
        config = FakeConfig({
            "AutoUpdateYtDlp": True,
            "ManagedBinaryPins": {"yt-dlp": "2026.07.04"},
        })
        with mock.patch.object(ad, "get_ytdlp_version", return_value="2026.07.04"), \
                mock.patch.object(ad, "should_check_ytdlp_update",
                                  side_effect=lambda *_a, **_k: ran.append(1) or True):
            ad.maybe_auto_update_ytdlp(config)
        self.assertEqual(ran, [], "a satisfied pin must not reach the throttle")

        with mock.patch.object(ad, "get_ytdlp_version", return_value="2026.08.19"), \
                mock.patch.object(ad, "should_check_ytdlp_update",
                                  side_effect=lambda *_a, **_k: ran.append(1) or False):
            ad.maybe_auto_update_ytdlp(config)
        self.assertEqual(ran, [1], "a pin that is not satisfied still updates")

    def test_a_rollback_restores_the_retained_copy_and_pins_to_it(self):
        stored = {}

        class PinConfig(FakeConfig):
            def update(self, mapping):
                stored.update(mapping)
                self.data.update(mapping)
                return True

        config = PinConfig({"ManagedBinaryPins": {}})
        with tempfile.TemporaryDirectory() as tmpdir:
            active = Path(tmpdir) / "yt-dlp.exe"
            backup = Path(tmpdir) / "yt-dlp.rollback.exe"
            active.write_bytes(b"new" + b"\0" * (2 * 1024 * 1024))
            versions = {str(active): "2026.08.19", str(backup): "2026.07.04"}

            def probe(name, path=None):
                return versions.get(str(path or active), "")

            with mock.patch.object(ad, "managed_binary_paths",
                                   return_value={"yt-dlp": active}), \
                    mock.patch.object(ad, "managed_binary_rollback_path",
                                      return_value=backup), \
                    mock.patch.object(ad, "write_persistent_log", return_value=None):
                # Nothing retained yet: the reason is named, not guessed.
                empty = ad.rollback_managed_binary(config, "yt-dlp")
                self.assertFalse(empty["ok"])
                self.assertEqual(empty["reason"], "no-retained-copy")

                backup.write_bytes(b"old" + b"\0" * (2 * 1024 * 1024))
                with mock.patch.object(ad, "probe_managed_binary_version",
                                       side_effect=probe):
                    versions[str(active)] = "2026.07.04"
                    result = ad.rollback_managed_binary(config, "yt-dlp")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["version"], "2026.07.04")
            self.assertEqual(active.read_bytes(), backup.read_bytes())
            self.assertEqual(
                stored["ManagedBinaryPins"], {"yt-dlp": "2026.07.04"})

    def test_retaining_a_rollback_copy_survives_a_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "gone.exe"
            with mock.patch.object(ad, "managed_binary_paths",
                                   return_value={"ffmpeg": missing}):
                self.assertEqual(ad.retain_managed_binary_rollback("ffmpeg"), "")

    def test_the_inventory_carries_the_digest_of_a_pinned_binary_only(self):
        # A pin is a claim about which release is running, and a version
        # string names a release rather than the file. Unpinned binaries move
        # on their own, so a digest for one expires the moment it is read.
        with tempfile.TemporaryDirectory() as tmpdir:
            pinned = Path(tmpdir) / "yt-dlp.exe"
            loose = Path(tmpdir) / "ffmpeg.exe"
            pinned.write_bytes(b"pinned" + b"\0" * (2 * 1024 * 1024))
            loose.write_bytes(b"loose" + b"\0" * (2 * 1024 * 1024))
            config = FakeConfig({"ManagedBinaryPins": {"yt-dlp": "2026.07.04"}})
            with mock.patch.object(ad, "managed_binary_paths",
                                   return_value={"yt-dlp": pinned, "ffmpeg": loose}), \
                    mock.patch.object(ad, "probe_managed_binary_version",
                                      side_effect=lambda name, path=None: (
                                          "2026.07.04" if name == "yt-dlp" else "8.1.2")), \
                    mock.patch.object(ad, "managed_binary_rollback_path",
                                      return_value=None):
                rows = {row["name"]: row
                        for row in ad.managed_binary_inventory(config)}
            self.assertEqual(
                rows["yt-dlp"]["sha256"], ad._compute_sha256(pinned))
            self.assertEqual(rows["yt-dlp"]["pinned"], "2026.07.04")
            self.assertEqual(rows["ffmpeg"]["sha256"], "")
            self.assertEqual(set(rows), set(ad.MANAGED_BINARY_NAMES))

    def test_the_settings_rows_render_the_inventory_and_pin_from_the_form(self):
        _get_qapp_or_skip(self)
        config = FakeConfig({"ManagedBinaryPins": {}})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            self.assertEqual(
                set(window.managed_pin_rows), set(ad.MANAGED_BINARY_NAMES))
            window._apply_managed_binaries([
                {"name": "yt-dlp", "installed": "2026.08.19",
                 "pinned": "", "rollback": "2026.07.04"},
                {"name": "deno", "installed": "", "pinned": "", "rollback": ""},
            ])
            ytdlp = window.managed_pin_rows["yt-dlp"]
            self.assertIn("2026.08.19", ytdlp["installed"].text())
            self.assertTrue(ytdlp["rollback"].isEnabled())
            self.assertFalse(window.managed_pin_rows["deno"]["rollback"].isEnabled())

            applied = []
            window._dependencies['set_managed_binary_pin'] = (
                lambda _config, name, version: applied.append((name, version))
                or {"ok": True, "name": name, "version": version,
                    "message": "pinned"}
            )
            ytdlp["field"].setText("2026.07.04")
            ytdlp["pin"].click()
            self.assertEqual(applied, [("yt-dlp", "2026.07.04")])
            self.assertEqual(ytdlp["pin"].text(), "Unpin")

            # The button now reads Unpin, so pressing it clears the pin
            # whatever text is left in the field.
            ytdlp["pin"].click()
            self.assertEqual(applied[-1], ("yt-dlp", ""))
        finally:
            _retire_test_window(window)


class ProbeInFlightAcrossASwapTests(unittest.TestCase):
    """A probe reads a binary that a rollback then replaces underneath it.

    All three probes run their subprocess with the lock released, which is
    deliberate. What was missing is that the answer coming back was published
    unconditionally, so a rollback's prime() or reset() could be undone by a
    probe that had already started, for a full hour of TTL.
    """

    def _blocking_probe(self, released, resumed, answer):
        def runner(_args):
            released.set()
            self.assertTrue(resumed.wait(15))
            return answer
        return runner

    def test_prime_survives_a_probe_that_started_before_it(self):
        released = threading.Event()
        resumed = threading.Event()
        probe = ad.ExecutableVersionProbe(
            path=lambda: Path(__file__),
            args=("--version",),
            runner=self._blocking_probe(released, resumed, "2026.01.01"),
            parser=lambda text: text.strip(),
        )
        result = {}
        worker = threading.Thread(target=lambda: result.update(got=probe.get()))
        worker.start()
        try:
            self.assertTrue(released.wait(15))
            # The rollback lands while the old binary is still being read.
            probe.prime("2026.08.19")
        finally:
            resumed.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(
            probe.get(), "2026.08.19",
            "the probe republished the version of a binary that is gone",
        )
        self.assertEqual(
            result["got"], "2026.08.19",
            "the in-flight caller answers with what is installed now",
        )

    def test_reset_is_not_undone_by_an_older_probe(self):
        released = threading.Event()
        resumed = threading.Event()
        answers = iter(["2026.01.01", "2026.08.19"])
        started = []

        def runner(_args):
            started.append(1)
            if len(started) == 1:
                released.set()
                self.assertTrue(resumed.wait(15))
            return next(answers)

        probe = ad.ExecutableVersionProbe(
            path=lambda: Path(__file__),
            args=("--version",),
            runner=runner,
            parser=lambda text: text.strip(),
        )
        worker = threading.Thread(target=probe.get)
        worker.start()
        try:
            self.assertTrue(released.wait(15))
            probe.reset()
        finally:
            resumed.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        # The discarded answer left no cached value, so the next caller runs
        # its own probe rather than reading a stale one for the whole TTL.
        self.assertEqual(probe.get(), "2026.08.19")
        self.assertEqual(len(started), 2)


class ProbeRestartsRatherThanAnsweringAboutAGoneBinaryTests(unittest.TestCase):
    """A reset mid-flight has to produce an answer, not a shrug."""

    def test_the_version_probe_rereads_after_a_reset(self):
        released = threading.Event()
        resumed = threading.Event()
        answers = iter(["2026.01.01", "2026.08.19"])
        calls = []

        def runner(_args):
            calls.append(1)
            if len(calls) == 1:
                released.set()
                self.assertTrue(resumed.wait(15))
            return next(answers)

        probe = ad.ExecutableVersionProbe(
            path=lambda: Path(__file__), args=("--version",),
            runner=runner, parser=lambda text: text.strip(),
        )
        result = {}
        worker = threading.Thread(target=lambda: result.update(got=probe.get()))
        worker.start()
        try:
            self.assertTrue(released.wait(15))
            probe.reset()
        finally:
            resumed.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(
            result["got"], "2026.08.19",
            "answering None would report the executable as unreadable",
        )
        self.assertEqual(len(calls), 2)

    def test_the_ffmpeg_probe_rereads_after_a_reset(self):
        # The first guard here read `generation changed AND _value is not
        # None`, and reset() is the only thing that changes the generation --
        # and it nulls _value. So it could never fire in the case it was for.
        released = threading.Event()
        resumed = threading.Event()
        answers = iter(["7.0", "9.0.1"])
        calls = []

        def version_getter():
            calls.append(1)
            if len(calls) == 1:
                released.set()
                self.assertTrue(resumed.wait(15))
            return next(answers)

        probe = ad.FfmpegCapabilitiesProbe(
            version_getter=version_getter, minimum_major=8,
        )
        result = {}
        worker = threading.Thread(
            target=lambda: result.update(got=probe.check()))
        worker.start()
        try:
            self.assertTrue(released.wait(15))
            probe.reset()
        finally:
            resumed.set()
            worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["got"]["majorVersion"], 9)
        self.assertTrue(
            result["got"]["current"],
            "the replaced ffmpeg was reported for a whole TTL",
        )


class YtDlpPinFloorTests(unittest.TestCase):
    """A pin is a user-writable setting, so it needs the floor the fetch has.

    yt-dlp and ffmpeg do every byte of network and media parsing this program
    performs. ffmpeg was already floored through MANAGED_BINARY_FLOORS;
    yt-dlp was pinnable to any release the version shape accepted, including
    ones before CVE-2026-55404 was fixed.
    """

    def test_a_pin_below_the_cve_fix_is_refused_by_name(self):
        for version in ('2026.06.09', '2025.12.31', '2024.01.01'):
            with self.subTest(version=version):
                decision = ad.evaluate_binary_pin('yt-dlp', version)
                self.assertFalse(decision['ok'])
                self.assertEqual(decision['reason'], 'pin-below-security-floor')
                self.assertEqual(decision['floor'], ad.YTDLP_SECURITY_MIN_VERSION)
                self.assertIn(ad.YTDLP_SECURITY_MIN_VERSION, decision['message'])

    def test_the_floor_itself_and_later_releases_are_accepted(self):
        for version in (ad.YTDLP_SECURITY_MIN_VERSION, '2026.7.4', '2026.08.19',
                        '2027.01.01'):
            with self.subTest(version=version):
                decision = ad.evaluate_binary_pin('yt-dlp', version)
                self.assertTrue(decision['ok'], decision['message'])

    def test_the_floor_is_the_release_requirements_names_for_the_cve(self):
        # The number is not invented here. requirements.txt has recorded which
        # yt-dlp release carries the CVE-2026-55404 fix since it shipped; this
        # keeps the pin path from disagreeing with it.
        requirements = (
            Path(ad.__file__).resolve().parent / 'requirements.txt'
        ).read_text(encoding='utf-8')
        self.assertIn('CVE-2026-55404', requirements)
        self.assertRegex(
            requirements,
            r'2026\.7\.4 fixed CVE-2026-55404',
            'requirements.txt must keep naming the release the floor is set to',
        )
        self.assertEqual(
            ad._compare_semver(ad.YTDLP_SECURITY_MIN_VERSION, '2026.7.4'), 0
        )

    def test_a_stored_pin_below_the_floor_is_dropped_on_load(self):
        # Dropping rather than raising to the floor: an unpinned binary follows
        # the published release, which is at or above the floor by definition,
        # while raising would freeze it at a version nobody chose.
        config = FakeConfig({'ManagedBinaryPins': {
            'yt-dlp': '2026.06.09', 'ffmpeg': '8.1.2',
        }})
        active = ad.active_managed_binary_pins(config)
        self.assertNotIn('yt-dlp', active)
        self.assertEqual(active.get('ffmpeg'), '8.1.2')
        self.assertEqual(ad.managed_binary_pin_for(config, 'yt-dlp'), '')

    def test_every_pinnable_binary_that_touches_the_network_has_a_floor(self):
        for name in ('yt-dlp', 'ffmpeg', 'deno', 'quickjs'):
            with self.subTest(name=name):
                self.assertTrue(
                    ad.MANAGED_BINARY_FLOORS.get(name),
                    f"{name} parses untrusted input and must not be pinnable "
                    "to an arbitrarily old build",
                )


class FirstPartyNetworkPolicyTests(unittest.TestCase):
    """What this program fetches for itself takes the route the user configured.

    Downloads always honoured the proxy because it reaches yt-dlp as argv. The
    managed binary fetches, their checksum sidecars, the Deno archive, the
    release API, the version source and the Kick resolver went out on the
    default route, so on a proxy-only network the downloads worked and the
    bootstrap, the updater and Kick silently did not.
    """

    def setUp(self):
        self._saved = ad.first_party_network_policy()

    def tearDown(self):
        ad.set_first_party_network_policy(
            lambda key, default=None: {
                'Proxy': self._saved.get('proxy', ''), 'UseSystemProxy': False,
            }.get(key, default),
            detected='',
        )

    @staticmethod
    def _config(**values):
        return lambda key, default=None: values.get(key, default)

    def test_a_typed_proxy_beats_the_detected_one(self):
        resolved = ad.set_first_party_network_policy(
            self._config(Proxy='http://typed.example:3128', UseSystemProxy=True),
            detected='http://detected.example:8080',
        )
        self.assertEqual(resolved['proxy'], 'http://typed.example:3128')

    def test_the_system_proxy_is_used_only_when_the_option_is_on(self):
        off = ad.set_first_party_network_policy(
            self._config(UseSystemProxy=False), detected='http://detected.example:8080',
        )
        self.assertEqual(off['proxy'], '')
        on = ad.set_first_party_network_policy(
            self._config(UseSystemProxy=True), detected='http://detected.example:8080',
        )
        self.assertEqual(on['proxy'], 'http://detected.example:8080')

    def test_the_bind_address_carries_the_forced_address_family(self):
        # Binding the wildcard of one family is how a socket is told to use it:
        # create_connection skips every getaddrinfo candidate whose family the
        # bind rejects. No resolver monkeypatching, which would be process-wide.
        self.assertEqual(ad.resolve_first_party_bind_address('ipv4', ''), ('0.0.0.0', 0))
        self.assertEqual(ad.resolve_first_party_bind_address('ipv6', ''), ('::', 0))
        self.assertIsNone(ad.resolve_first_party_bind_address('', ''))
        # An explicit source address already names its family and wins.
        self.assertEqual(
            ad.resolve_first_party_bind_address('ipv6', '192.0.2.7'), ('192.0.2.7', 0)
        )

    def test_the_session_carries_the_proxy_and_ignores_the_environment(self):
        ad.set_first_party_network_policy(
            self._config(Proxy='http://proxy.example:3128'), detected='',
        )
        session = ad.build_first_party_session()
        try:
            self.assertEqual(session.proxies.get('https'), 'http://proxy.example:3128')
            self.assertEqual(session.proxies.get('http'), 'http://proxy.example:3128')
            # A configured proxy is the route, not a suggestion: an env NO_PROXY
            # must not put a host back on the direct path.
            self.assertFalse(session.trust_env)
        finally:
            session.close()

    def test_the_session_binds_when_a_source_address_is_configured(self):
        ad.set_first_party_network_policy(
            self._config(ForceIPVersion='ipv4'), detected='',
        )
        session = ad.build_first_party_session()
        try:
            adapter = session.get_adapter('https://example.invalid/')
            self.assertEqual(
                adapter.poolmanager.connection_pool_kw.get('source_address'),
                ('0.0.0.0', 0),
            )
        finally:
            session.close()
        ad.set_first_party_network_policy(self._config(), detected='')
        plain = ad.build_first_party_session()
        try:
            adapter = plain.get_adapter('https://example.invalid/')
            self.assertIsNone(
                adapter.poolmanager.connection_pool_kw.get('source_address')
            )
        finally:
            plain.close()

    def test_every_first_party_fetch_goes_through_the_policy(self):
        source = inspect.getsource(ad)
        stray = re.findall(r"\bhttp_requests\.get\(", source)
        self.assertEqual(
            stray, [],
            "a first-party fetch calls requests.get directly and so ignores the "
            "configured proxy; route it through first_party_http_get",
        )

    def test_the_native_resolver_is_handed_the_policy_aware_opener(self):
        source = inspect.getsource(ad)
        self.assertIn(
            "fetch=first_party_native_fetch", source,
            "resolve_native_source must be injected with the policy-aware fetch, "
            "or the Kick resolver keeps using a bare urlopen on the default route",
        )

    def test_a_fetch_really_traverses_the_proxy_and_fails_when_it_refuses(self):
        # Attribute checks prove the session was configured. This proves the
        # bytes went that way: the target host does not resolve, so a request
        # that reaches a 200 can only have been forwarded by the proxy, and one
        # that reports a proxy error can only have tried to.
        served = []

        class _Proxy(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        class _Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request_line = self.rfile.readline(65536).decode('latin-1')
                served.append(request_line.split(' ')[1] if ' ' in request_line else '')
                while True:
                    line = self.rfile.readline(65536)
                    if line in (b'\r\n', b'\n', b''):
                        break
                self.wfile.write(
                    b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n'
                    b'Connection: close\r\n\r\nok'
                )

        server = _Proxy(('127.0.0.1', 0), _Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            ad.set_first_party_network_policy(
                self._config(Proxy=f'http://127.0.0.1:{port}'), detected='',
            )
            with ad.first_party_http_get(
                'http://unresolvable.invalid/binary', timeout=15,
            ) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'ok')
            self.assertEqual(
                served, ['http://unresolvable.invalid/binary'],
                'the proxy must have been handed the absolute URI',
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(10)

        # Same fixture, now refusing: the port is closed and the failure must
        # name the proxy rather than looking like a broken internet.
        ad.set_first_party_network_policy(
            self._config(Proxy=f'http://127.0.0.1:{port}'), detected='',
        )
        with self.assertRaises(ad.http_requests.exceptions.ProxyError) as caught:
            ad.first_party_http_get('http://unresolvable.invalid/binary', timeout=15)
        self.assertIn(str(port), str(caught.exception))

    def test_the_native_fetch_sends_through_the_configured_proxy(self):
        ad.set_first_party_network_policy(
            self._config(Proxy='http://proxy.example:3128'), detected='',
        )
        seen = {}

        class _Opener:
            def open(self, request, timeout=None):
                raise AssertionError('the fixture opener must not be reached')

        def _fake_build_opener(*handlers):
            for handler in handlers:
                if isinstance(handler, urllib.request.ProxyHandler):
                    seen['proxies'] = dict(handler.proxies)
            return _Opener()

        with mock.patch.object(
            ad.urllib.request, 'build_opener', side_effect=_fake_build_opener
        ):
            with self.assertRaises(AssertionError):
                ad.first_party_native_fetch('https://web.kick.example/playback')
        self.assertEqual(
            seen.get('proxies'),
            {'http': 'http://proxy.example:3128', 'https': 'http://proxy.example:3128'},
        )


class DatedFixtureShelfLifeTests(unittest.TestCase):
    """A fixture measured against a relative window must not carry a literal date.

    `ytdlp-freshness` compares a dated yt-dlp release against `date.today()`
    through `YTDLP_STALE_AFTER_DAYS`. A test that pins an absolute version and
    then asserts a *fresh* outcome passes on the day it is written and fails,
    silently and later, a run that changed nothing. That is what happened to
    `test_health_exposes_preflight_without_network_or_site_metadata`, which
    pinned `2026.08.01` and went red on 2026-08-31.
    """

    _VERSION_PATCH_RE = re.compile(
        r"""get_ytdlp_version['"]\s*,\s*return_value\s*=\s*['"](\d{4}\.\d{1,2}\.\d{1,2})['"]"""
    )
    # A literal version is only a fuse where the outcome under assertion is
    # measured against the clock. The same literal feeding a pin comparison
    # (`ManagedBinaryPins`) is a plain string equality and never expires, so
    # the scan looks for the freshness surface by name rather than flagging
    # every dated literal in the tree.
    _FRESHNESS_MARKERS = ("preflight", "ytdlp-freshness", "evaluate_preflight_checks")
    # And on that surface, direction decides. Asserting a *stale* or *warning*
    # outcome from an absolute date is correct and permanent, because an
    # absolute date can only get staler. Asserting a *fresh* one from an
    # absolute date is the fuse: it holds until the window closes under it.
    _FRESH_OUTCOME_RE = re.compile(r"""['"](?:ready|ok)['"]""")

    @staticmethod
    def _test_module_sources():
        root = Path(ad.__file__).resolve().parent
        return sorted(root.glob("test_*.py"))

    @classmethod
    def _dated_literals_in_freshness_tests(cls, text):
        """Yield (test name, version literal) for clock-sensitive fixtures."""
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            body = ast.get_source_segment(text, node) or ""
            if not any(marker in body for marker in cls._FRESHNESS_MARKERS):
                continue
            if not cls._FRESH_OUTCOME_RE.search(body):
                continue
            for literal in cls._VERSION_PATCH_RE.findall(body):
                yield node.name, literal

    def test_helper_reads_fresh_at_any_point_on_the_clock(self):
        # One year out and one day past the nominal release both have to hold,
        # because the helper's whole job is to have no shelf life.
        for offset in (0, 1, 30, 365, 3650):
            with self.subTest(days_ahead=offset):
                simulated = date(2026, 9, 4) + timedelta(days=offset)
                check = next(
                    item
                    for item in ad.evaluate_preflight_checks(
                        ytdlp_version=fresh_ytdlp_version(simulated),
                        ffmpeg_capabilities={
                            "current": True, "filterCheck": True, "missingFilters": [],
                        },
                        javascript_runtime={"ytdlpNeedsRuntime": False},
                        sign_in_entries=[],
                        github_api_budget={"remaining": 20, "limit": 60},
                        po_token_provider=None,
                        now=simulated,
                    )["checks"]
                    if item["id"] == "ytdlp-freshness"
                )
                self.assertEqual(check["status"], "ok")
                self.assertEqual(check["details"]["ageDays"], 0)

    def test_the_scan_flags_a_planted_fuse(self):
        # Positive control: with the tree clean the scan below has nothing to
        # report, and a check that can only pass is not a check. Feed it the
        # exact shape of the bug and confirm it is seen.
        planted = (
            "def test_planted(self):\n"
            "    with mock.patch.object(ad, 'get_ytdlp_version',"
            " return_value='2026.08.01'):\n"
            "        body = client.get('/health').get_json()\n"
            "    self.assertEqual(body['preflight']['status'], 'ready')\n"
        )
        self.assertEqual(
            list(self._dated_literals_in_freshness_tests(planted)),
            [("test_planted", "2026.08.01")],
        )
        # And the two shapes that are correct stay unflagged: the same literal
        # outside the freshness surface, and one on that surface asserting the
        # stale direction, which an absolute date can only keep satisfying.
        pinned = (
            "def test_pin(self):\n"
            "    with mock.patch.object(ad, 'get_ytdlp_version',"
            " return_value='2026.08.01'):\n"
            "        ad.maybe_auto_update_ytdlp(config)\n"
        )
        self.assertEqual(list(self._dated_literals_in_freshness_tests(pinned)), [])
        stale_direction = (
            "def test_stale(self):\n"
            "    with mock.patch.object(ad, 'get_ytdlp_version',"
            " return_value='2026.01.01'):\n"
            "        body = client.get('/health').get_json()\n"
            "    self.assertEqual(body['preflight']['status'], 'attention')\n"
        )
        self.assertEqual(
            list(self._dated_literals_in_freshness_tests(stale_direction)), []
        )

    def test_no_freshness_fixture_pins_a_version_that_can_expire(self):
        offenders = [
            f"{source.name}::{name} pins {literal}"
            for source in self._test_module_sources()
            for name, literal in self._dated_literals_in_freshness_tests(
                source.read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(
            offenders, [],
            "These tests patch get_ytdlp_version to an absolute version and then "
            "assert a fresh outcome on a check measured against date.today(). "
            "That passes on the day it is written and fails later on a run that "
            "changed nothing. Use fresh_ytdlp_version() from testing_support, or "
            "freeze the clock with the check's own `now` argument.",
        )


if __name__ == "__main__":
    unittest.main()
