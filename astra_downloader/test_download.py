"""Tests for the queue, yt-dlp argv, cookies and everything a download does."""

import ast
import hashlib
import inspect
import io
import re
import json
import os
import queue
import shutil
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
from datetime import datetime, timedelta
from unittest import mock
from pathlib import Path
import xml.etree.ElementTree as ET
import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


class YTDLPActivityBoundaryTests(unittest.TestCase):
    def test_spawn_registers_and_prunes_a_live_process(self):
        registry = ad.YTDLPActivityRegistry()

        class Process:
            returncode = None

            def poll(self):
                return self.returncode

        process = Process()
        with mock.patch.object(ad, '_YTDLP_ACTIVITY', registry), \
             mock.patch.object(ad.subprocess, 'Popen', return_value=process):
            self.assertIs(
                ad.spawn_ytdlp(['yt-dlp.exe', 'https://example.test']),
                process,
            )
            self.assertEqual(registry.active_count(), 1)
            process.returncode = 0
            self.assertEqual(registry.active_count(), 0)

    def test_completed_process_can_release_a_polling_reservation(self):
        registry = ad.YTDLPActivityRegistry()
        process = object()
        token = registry.reserve()
        registry.attach(token, process)

        registry.release_process(process)

        self.assertEqual(registry.active_count(), 0)


class InstalledExecutableTests(unittest.TestCase):
    """A portable/forked launch must not corrupt or downgrade the install."""

    def _paths(self, tmp):
        root = Path(tmp)
        current = root / "Downloads" / "AstraDownloader.exe"
        target = root / "AstraDownloader" / "AstraDownloader.exe"
        current.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        return current, target

    def _frozen_patches(self, current, target, *, installed_version):
        return mock.patch.object(ad, "is_frozen_app", return_value=True), \
            mock.patch.object(ad, "current_executable_path", return_value=current), \
            mock.patch.object(ad, "install_target_exe", return_value=target), \
            mock.patch.object(ad, "_probe_companion_version", return_value=installed_version), \
            mock.patch.object(ad, "write_persistent_log")

    def test_adjacent_release_sidecar_accepts_absence_and_matching_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "AstraDownloader.exe"
            payload = b"MZ" + (b"verified-release" * 128)
            executable.write_bytes(payload)

            self.assertFalse(ad.verify_adjacent_release_sidecar(executable))

            digest = hashlib.sha256(payload).hexdigest()
            executable.with_name(executable.name + ".sha256").write_text(
                f"{digest}  {executable.name}\n",
                encoding="ascii",
            )
            self.assertTrue(ad.verify_adjacent_release_sidecar(executable))

    def test_malformed_adjacent_release_sidecar_has_a_named_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "AstraDownloader.exe"
            executable.write_bytes(b"MZrelease")
            executable.with_name(executable.name + ".sha256").write_text(
                "not-a-checksum\n",
                encoding="ascii",
            )

            with self.assertRaises(
                ad.DownloadedExecutableIntegrityError
            ) as raised:
                ad.verify_adjacent_release_sidecar(executable)

            self.assertEqual(
                raised.exception.code,
                "download-integrity-check-failed",
            )

    def test_wrong_download_sidecar_stops_before_the_installer_entry_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "Downloads" / "AstraDownloader.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"MZdownloaded-release")
            executable.with_name(executable.name + ".sha256").write_text(
                f"{'0' * 64}  {executable.name}\n",
                encoding="ascii",
            )
            managed = root / "AppData" / "AstraDownloader" / "AstraDownloader.exe"

            with mock.patch.object(ad.sys, "argv", [str(executable), "--install"]), \
                    mock.patch.object(ad, "is_frozen_app", return_value=True), \
                    mock.patch.object(
                        ad, "current_executable_path", return_value=executable
                    ), \
                    mock.patch.object(ad, "companion_install_exit_code") as install:
                with self.assertRaises(
                    ad.DownloadedExecutableIntegrityError
                ) as raised:
                    ad.main()

            self.assertEqual(
                raised.exception.code,
                "download-integrity-check-failed",
            )
            self.assertIn("SHA-256", str(raised.exception))
            install.assert_not_called()
            self.assertFalse(managed.exists())

    def test_newer_managed_exe_is_kept_when_an_older_copy_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, target = self._paths(tmp)
            current.write_bytes(b"running-older")
            target.write_bytes(b"managed-newer")
            # Unreachably newer, so this stays "newer than the running
            # build" across every future version bump.
            patches = self._frozen_patches(current, target, installed_version="999.0.0")
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = ad.ensure_installed_executable()

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"managed-newer")

    def test_older_managed_exe_is_replaced_by_a_verified_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, target = self._paths(tmp)
            current.write_bytes(b"running-newer")
            target.write_bytes(b"managed-older")
            patches = self._frozen_patches(current, target, installed_version="2.4.0")
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                result = ad.ensure_installed_executable()

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"running-newer")

    def test_failed_verified_copy_keeps_the_previous_managed_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            current, target = self._paths(tmp)
            current.write_bytes(b"running-newer")
            target.write_bytes(b"managed-still-good")
            patches = self._frozen_patches(current, target, installed_version="2.4.0")
            with patches[0], patches[1], patches[2], patches[3], patches[4], \
                    mock.patch.object(ad, "atomic_copy_verified",
                                       side_effect=OSError("disk full")):
                result = ad.ensure_installed_executable()

            self.assertEqual(result, current)
            self.assertEqual(target.read_bytes(), b"managed-still-good")


class QuarantinedStateFileTests(unittest.TestCase):
    """A corrupt state file is set aside silently. Something has to say so."""

    def setUp(self):
        import config as _config

        self.config_module = _config
        _config._quarantined_state_files[:] = []
        self.addCleanup(lambda: _config._quarantined_state_files.__setitem__(
            slice(None), []))

    def test_loading_a_corrupt_file_records_the_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text("{ not json", encoding="utf-8")

            self.assertEqual(ad.load_json_file(target, {}), {})

            records = self.config_module.quarantined_state_files()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["path"], str(target))
            backup = Path(records[0]["backup"])
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "{ not json")

    def test_restore_puts_the_original_back_and_clears_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text('{"ServerToken": "original", ', encoding="utf-8")
            ad.load_json_file(target, {})
            target.write_text('{"ServerToken": "regenerated"}', encoding="utf-8")

            backup = self.config_module.quarantined_state_files()[0]["backup"]
            restored = self.config_module.restore_quarantined_file(backup)

            self.assertEqual(restored, target)
            self.assertEqual(
                target.read_text(encoding="utf-8"), '{"ServerToken": "original", ')
            self.assertFalse(Path(backup).exists())
            self.assertEqual(self.config_module.quarantined_state_files(), [])

    def test_a_corrupt_queue_is_distinguished_from_an_empty_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "download-queue.json"

            empty = ad.DownloadManager(
                FakeConfig(), FakeHistory(), queue_path=queue_path)
            self.assertEqual(empty.queue_payload()["persistenceError"], None)

            queue_path.write_text("{ truncated", encoding="utf-8")
            corrupt = ad.DownloadManager(
                FakeConfig(), FakeHistory(), queue_path=queue_path)
            notice = corrupt.queue_payload()["persistenceError"]
            self.assertIsNotNone(notice)
            self.assertIn("set aside", notice)

    def test_the_download_page_offers_to_restore_a_quarantined_file(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config.json"
            target.write_text("{ not json", encoding="utf-8")
            ad.load_json_file(target, {})
            target.write_text('{"ServerToken": "regenerated"}', encoding="utf-8")

            manager = ad.DownloadManager(FakeConfig(), FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
                try:
                    self.assertFalse(window.quarantine_panel.isHidden())
                    text = window.quarantine_notice.text()
                    self.assertIn("config.json", text)
                    self.assertIn("pairing again", text,
                                  "a regenerated token is the consequence to name")

                    window.btn_quarantine_restore.click()
                    QApplication.processEvents()

                    self.assertEqual(
                        target.read_text(encoding="utf-8"), "{ not json")
                    self.assertTrue(window.quarantine_panel.isHidden())
                finally:
                    _retire_test_window(window)

    def test_dismiss_hides_the_notice_without_restoring(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "download-queue.json"
            target.write_text("{ not json", encoding="utf-8")
            ad.load_json_file(target, {})

            manager = ad.DownloadManager(FakeConfig(), FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
                try:
                    self.assertFalse(window.quarantine_panel.isHidden())
                    window.btn_quarantine_dismiss.click()
                    QApplication.processEvents()
                    self.assertTrue(window.quarantine_panel.isHidden())
                    self.assertEqual(
                        len(self.config_module.quarantined_state_files()), 1,
                        "dismissing must not delete the backup",
                    )
                finally:
                    _retire_test_window(window)


class TransferReliabilityArgvTests(unittest.TestCase):
    """Throttle recovery, timeouts and format verification reach the argv."""

    def setUp(self):
        self.addCleanup(ad.reset_deno_runtime_cache)
        self.addCleanup(ad.reset_ffmpeg_capabilities_cache)
        self.addCleanup(ad.reset_po_token_provider_cache)

    def _argv(self, overrides, section=None):
        captured = []

        class Proc:
            returncode = 0

            def __init__(self, args, **_kwargs):
                captured.append(list(args))
                self.stdout = iter(["[download] Destination: clip.mp4\n"])

            def wait(self):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                # reason: satisfy the API the cancel path expects
                pass

            def kill(self):
                # reason: same as terminate
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            settings.update(overrides)
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            download = ad.Download("dl_reliability", "https://example.com/video",
                                   output_dir=tmpdir, section=section)
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", Proc), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
        runs = [args for args in captured if download.url in args]
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_a_format_preference_reaches_the_download_argv(self):
        argv = self._argv({
            "VideoCodecPreference": "h264",
            "PreferredFrameRate": 60,
        })
        self.assertEqual(
            argv[argv.index("--format-sort") + 1],
            "res,channels,lang,vcodec:h264,fps~60",
        )

    def test_defaults_include_soft_audio_sort_and_quiet_colors(self):
        argv = self._argv({})
        self.assertEqual(
            argv[argv.index("--format-sort") + 1], "res,channels,lang"
        )
        self.assertEqual(argv[argv.index("--color") + 1], "no_color")
        for flag in ("--throttled-rate", "--socket-timeout",
                     "--extractor-retries", "--check-formats"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv, "defaults must not change the argv")

    def test_native_clip_selectors_reach_yt_dlp_argv(self):
        for section, expected in (
            (
                {"start": "*from-url", "end": "inf"},
                "*from-url",
            ),
            (
                {"start": "*-30", "end": "inf"},
                "*-30-inf",
            ),
        ):
            with self.subTest(section=section):
                argv = self._argv({}, section=section)
                self.assertEqual(
                    argv[argv.index("--download-sections") + 1], expected
                )

    def test_configured_values_compile_into_the_argv(self):
        argv = self._argv({
            "ThrottledRate": "100K",
            "SocketTimeoutSeconds": 30,
            "ExtractorRetries": 5,
            "VerifyFormats": True,
        })
        self.assertEqual(argv[argv.index("--throttled-rate") + 1], "100K")
        self.assertEqual(argv[argv.index("--socket-timeout") + 1], "30")
        self.assertEqual(argv[argv.index("--extractor-retries") + 1], "5")
        self.assertIn("--check-formats", argv)

    def test_a_junk_throttle_floor_is_dropped_rather_than_passed(self):
        # These land in a subprocess argument.
        argv = self._argv({"ThrottledRate": "fast; rm -rf /"})
        self.assertNotIn("--throttled-rate", argv)

    def test_pacing_compiles_and_a_stray_maximum_is_normalised(self):
        argv = self._argv({
            "SleepIntervalSeconds": 5,
            "MaxSleepIntervalSeconds": 12,
            "SleepRequestsSeconds": 2,
        })
        self.assertEqual(argv[argv.index("--sleep-interval") + 1], "5")
        self.assertEqual(argv[argv.index("--max-sleep-interval") + 1], "12")
        self.assertEqual(argv[argv.index("--sleep-requests") + 1], "2")

        # yt-dlp refuses a maximum below the minimum, which would fail the
        # whole download rather than the setting.
        argv = self._argv({"SleepIntervalSeconds": 9, "MaxSleepIntervalSeconds": 3})
        self.assertEqual(argv[argv.index("--sleep-interval") + 1], "9")
        self.assertNotIn("--max-sleep-interval", argv)

        argv = self._argv({
            "SleepIntervalSeconds": 5,
            "PacingJitterPercent": 20,
        })
        self.assertEqual(argv[argv.index("--sleep-interval") + 1], "5")
        self.assertEqual(argv[argv.index("--max-sleep-interval") + 1], "6")

    def test_retry_after_text_is_bounded_and_understands_minutes(self):
        self.assertEqual(
            ad.parse_retry_after_seconds(["ERROR: HTTP 429", "Retry-After: 2 minutes"]),
            120,
        )
        self.assertEqual(
            ad.parse_retry_after_seconds("retry in 4 seconds"),
            4,
        )
        self.assertIsNone(ad.parse_retry_after_seconds(["HTTP 429 without a header"]))

    def test_a_429_is_classified_as_rate_limited_not_as_a_dead_network(self):
        self.assertEqual(
            ad.classify_download_failure('ERROR: HTTP Error 429: Too Many Requests'),
            'rate-limited',
        )
        self.assertEqual(
            ad.classify_download_failure('ERROR: Connection reset by peer'),
            'network-unreachable',
        )
        advice = ad.DOWNLOAD_FAILURE_RECOVERY['rate-limited']
        self.assertIn('pacing', advice['advice'])
        self.assertIn('rate-limited', ad.DOWNLOAD_RETRYABLE_ERROR_CODES)

    def test_a_paced_download_reads_as_waiting_rather_than_hung(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        download = ad.Download("dl_paced", "https://example.com/video")
        download.status = "downloading"
        download.speed = "8.2MiB/s"
        class Proc:
            stdout = iter(["[download] Sleeping 7.00 seconds as required by the site...\n"])

        manager._consume_ytdlp_output(download, Proc(), {'at': 0.0})
        self.assertEqual(download.speed, "waiting 7s")
        self.assertEqual(download.eta, "")

    def test_the_real_binary_accepts_the_reliability_flags(self):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        result = subprocess.run(
            [str(ytdlp), "--throttled-rate", "100K", "--socket-timeout", "30",
             "--extractor-retries", "5", "--check-formats", "--help"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-400:])


class SponsorBlockCategoryTests(unittest.TestCase):
    def test_unknown_categories_are_dropped_and_all_means_all(self):
        # These names reach a subprocess argument.
        self.assertEqual(
            ad.normalize_sponsorblock_categories("sponsor, outro, nonsense"),
            "sponsor,outro",
        )
        self.assertEqual(ad.normalize_sponsorblock_categories("all"), "")
        self.assertEqual(ad.normalize_sponsorblock_categories(""), "")
        self.assertEqual(
            ad.normalize_sponsorblock_categories(["intro", "intro", "sponsor"]),
            "intro,sponsor",
        )
        # A token carrying anything but a category name is dropped whole
        # rather than salvaged down to the part that happens to match.
        self.assertEqual(
            ad.normalize_sponsorblock_categories("sponsor; rm -rf /"), "")

    def _argv_for(self, categories):
        captured = []
        manager = ad.DownloadManager(
            FakeConfig({
                "SponsorBlock": True,
                "SponsorBlockAction": "remove",
                "SponsorBlockCategories": categories,
            }),
            FakeHistory(),
        )
        download = ad.Download("dl_sb", "https://www.youtube.com/watch?v=abc")

        class Proc:
            returncode = 0

            def __init__(self, args, **_kwargs):
                captured.append(list(args))
                self.stdout = iter(["[download] Destination: clip.mp4\n"])

            def wait(self):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                # reason: satisfy the API the cancel path expects
                pass

            def kill(self):
                # reason: same as terminate
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            download.output_dir = tmpdir
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", Proc), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
        runs = [args for args in captured if download.url in args]
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_selected_categories_reach_ytdlp(self):
        args = self._argv_for("sponsor,selfpromo")
        self.assertEqual(args[args.index("--sponsorblock-remove") + 1],
                         "sponsor,selfpromo")

    def test_no_selection_still_means_every_category(self):
        args = self._argv_for("")
        self.assertEqual(args[args.index("--sponsorblock-remove") + 1], "all")


class PerDownloadDestinationTests(unittest.TestCase):
    def _window(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            return ad.MainWindow(FakeConfig(), manager, FakeHistory()), manager

    def test_a_chosen_folder_applies_to_one_download_then_clears(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window, manager = self._window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(
                    ad.QFileDialog, "getExistingDirectory", return_value=tmp
                ):
                    window.btn_quick_download_dest.click()
                QApplication.processEvents()
                self.assertEqual(window._quick_download_dir, tmp)
                self.assertIn(tmp, window.btn_quick_download_dest.accessibleName())

                window.quick_download_url.setText("https://example.com/video")
                with mock.patch.object(
                    manager, "start_download", return_value=("dl_dest", None)
                ) as start:
                    window._start_quick_download()

                self.assertEqual(start.call_args.kwargs["output_dir"], tmp)
                self.assertIn(tmp, window.quick_download_status.text())
                self.assertEqual(
                    window._quick_download_dir, "",
                    "the override is for one download, not a new default",
                )

                window.quick_download_url.setText("https://example.com/second")
                with mock.patch.object(
                    manager, "start_download", return_value=("dl_default", None)
                ) as start:
                    window._start_quick_download()
                self.assertIsNone(start.call_args.kwargs["output_dir"])
        finally:
            _retire_test_window(window)

    def test_clicking_the_destination_again_clears_it(self):
        _get_qapp_or_skip(self)
        window, _manager = self._window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(
                    ad.QFileDialog, "getExistingDirectory", return_value=tmp
                ):
                    window.btn_quick_download_dest.click()
                self.assertEqual(window._quick_download_dir, tmp)

                # No dialog this time: a second click means "never mind".
                with mock.patch.object(
                    ad.QFileDialog, "getExistingDirectory",
                    side_effect=AssertionError("must not reopen the picker"),
                ):
                    window.btn_quick_download_dest.click()
                self.assertEqual(window._quick_download_dir, "")
        finally:
            _retire_test_window(window)


class IntermediateFileSweepTests(unittest.TestCase):
    """"3/4 files and a folder when downloading, I want just 1 file." """

    def setUp(self):
        # A run here replaces subprocess.Popen wholesale, which the JS runtime
        # and ffmpeg probes also go through. Their results are cached module
        # wide, so without this a failed fake process teaches every later test
        # that the runtime is broken.
        self.addCleanup(ad.reset_deno_runtime_cache)
        self.addCleanup(ad.reset_ffmpeg_capabilities_cache)
        self.addCleanup(ad.reset_po_token_provider_cache)

    def _finished(self, tmpdir, config=None):
        manager = ad.DownloadManager(
            config or FakeConfig({"DownloadPath": tmpdir}), FakeHistory())
        download = ad.Download("dl_sweep", "https://example.com/video")
        download.status = "complete"
        download.filename = str(Path(tmpdir) / "Holiday Clip.mp4")
        return manager, download

    def _litter(self, tmpdir):
        folder = Path(tmpdir)
        (folder / "Holiday Clip.mp4").write_text("final", encoding="utf-8")
        leftovers = [
            folder / "Holiday Clip.mp4.part",
            folder / "Holiday Clip.mp4.ytdl",
            folder / "Holiday Clip.f137.mp4",
            folder / "Holiday Clip.f140.m4a",
        ]
        for path in leftovers:
            path.write_text("junk", encoding="utf-8")
        bystander = folder / "Someone Else's Video.mp4"
        bystander.write_text("keep", encoding="utf-8")
        return leftovers, bystander

    def test_a_successful_download_leaves_one_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            leftovers, bystander = self._litter(tmpdir)
            manager, download = self._finished(tmpdir)

            with mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._sweep_download_intermediates(download)

            for path in leftovers:
                self.assertFalse(path.exists(), f"{path.name} should have been swept")
            self.assertTrue(Path(download.filename).exists())
            self.assertTrue(bystander.exists(),
                            "only this download's own intermediates may be removed")

    def test_a_successful_download_removes_its_private_staging_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
                tempfile.TemporaryDirectory() as install_dir, \
                mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
            manager, download = self._finished(tmpdir)
            Path(download.filename).write_text("final", encoding="utf-8")
            staging = manager._download_intermediate_dir(download)
            staging.mkdir(parents=True)
            partial = staging / "Holiday Clip.mp4.part"
            partial.write_text("partial", encoding="utf-8")

            with mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._sweep_download_intermediates(download)

            self.assertFalse(partial.exists())
            self.assertFalse(staging.exists())
            self.assertTrue(Path(download.filename).exists())

    def test_keeping_intermediates_is_a_setting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            leftovers, _bystander = self._litter(tmpdir)
            manager, download = self._finished(tmpdir, FakeConfig({
                "DownloadPath": tmpdir, "KeepIntermediateFiles": True,
            }))

            manager._sweep_download_intermediates(download)

            for path in leftovers:
                self.assertTrue(path.exists(), f"{path.name} must be kept")

    def test_a_failed_download_sweeps_its_private_staging_directory(self):
        class FailingProc:
            returncode = 1

            def __init__(self, args, **_kwargs):
                self.stdout = iter(["ERROR: unable to download video data\n"])
                temp_arg = next(
                    value for index, value in enumerate(args[:-1])
                    if args[index] == '--paths'
                    and value.startswith('temp:')
                )
                staging = Path(temp_arg[len('temp:'):])
                staging.mkdir(parents=True)
                (staging / "failed.mp4.part").write_text(
                    "partial", encoding="utf-8"
                )

            def wait(self):
                return 1

            def poll(self):
                return 1

            def terminate(self):
                # reason: the cancel path may call this; satisfy the API
                pass

            def kill(self):
                # reason: same as terminate
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as install_dir, \
                    mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
                manager = ad.DownloadManager(
                    FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                    FakeHistory(),
                )
                download = ad.Download(
                    "dl_failed_sweep", "https://example.com/video", output_dir=tmpdir)
                download.status = "queued"

                with mock.patch.object(ad.subprocess, "Popen", FailingProc), \
                     mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                     mock.patch.object(ad, "write_persistent_log", return_value=None):
                    manager._run_download(download)

                self.assertEqual(download.status, "failed")
                self.assertFalse(manager._download_intermediate_dir(download).exists())

    def test_cancelled_download_sweeps_staging_without_touching_other_jobs(self):
        with tempfile.TemporaryDirectory() as install_dir:
            with mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
                manager = ad.DownloadManager(FakeConfig(), FakeHistory())
                cancelled = ad.Download("cancelled", "https://example.com/video")
                other = ad.Download("other", "https://example.com/other")
                manager.downloads[cancelled.id] = cancelled
                manager.downloads[other.id] = other
                cancelled_dir = manager._download_intermediate_dir(cancelled)
                other_dir = manager._download_intermediate_dir(other)
                cancelled_dir.mkdir(parents=True)
                other_dir.mkdir(parents=True)
                (cancelled_dir / "clip.part").write_text("partial", encoding="utf-8")
                (other_dir / "keep.part").write_text("partial", encoding="utf-8")

                with mock.patch.object(manager, "_launch_workers") as launch:
                    self.assertTrue(manager.cancel(cancelled.id))
                launch.assert_called_once_with([other])

                self.assertFalse(cancelled_dir.exists())
                self.assertTrue(other_dir.exists())

    def test_startup_sweeps_orphaned_staging_but_keeps_restored_queue_ids(self):
        with tempfile.TemporaryDirectory() as install_dir, \
                tempfile.TemporaryDirectory() as output_dir, \
                mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
            config = FakeConfig({
                "DownloadPath": output_dir,
                "AudioDownloadPath": output_dir,
            })
            queue_path = Path(install_dir) / "download-queue.json"
            first = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(first.pause_intake())
            download_id, error = first.start_download("https://example.com/video")
            self.assertIsNone(error)
            restored_dir = first._download_intermediate_dir(
                first.downloads[download_id]
            )
            restored_dir.mkdir(parents=True)
            (restored_dir / "resume.part").write_text("partial", encoding="utf-8")
            orphan_dir = restored_dir.parent / "orphan"
            orphan_dir.mkdir(parents=True)
            (orphan_dir / "stale.part").write_text("stale", encoding="utf-8")

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)

            self.assertIn(download_id, restored.downloads)
            self.assertTrue(restored_dir.exists())
            self.assertFalse(orphan_dir.exists())


class UiRefreshCoalescingTests(unittest.TestCase):
    def _window(self, history=None):
        history = history or FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            return ad.MainWindow(FakeConfig(), manager, history), manager

    def test_a_burst_of_progress_signals_causes_one_refresh(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window, manager = self._window()
        try:
            refreshes = []
            real_update = window._update_ui
            window._update_ui = lambda: (refreshes.append(1), real_update())[1]
            window._ui_refresh_timer.timeout.disconnect()
            window._ui_refresh_timer.timeout.connect(lambda: window._update_ui())

            # yt-dlp emits a line per progress tick, per running download.
            for _ in range(200):
                window._request_ui_refresh()
            QApplication.processEvents()
            self.assertEqual(refreshes, [], "the burst must not refresh synchronously")

            deadline = time.monotonic() + 2
            while not refreshes and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)

            self.assertEqual(
                len(refreshes), 1,
                f"200 progress signals collapsed to {len(refreshes)} refreshes",
            )
        finally:
            _retire_test_window(window)

    def test_typing_in_the_history_search_reloads_once(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)

        class CountingHistory(FakeHistory):
            def __init__(self):
                super().__init__()
                self.loads = 0

            def load(self):
                self.loads += 1
                return list(self.entries)

        history = CountingHistory()
        window, _manager = self._window(history)
        try:
            history.loads = 0
            for length in range(1, 9):
                window.history_search.setText("holiday"[:length] or "h")
                QApplication.processEvents()
            self.assertEqual(history.loads, 0, "typing must not hit the store per key")

            deadline = time.monotonic() + 2
            while history.loads == 0 and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
            self.assertEqual(history.loads, 1)
        finally:
            _retire_test_window(window)


class FatalErrorReportingTests(unittest.TestCase):
    """A windowed exe that dies silently just doesn't open when you click it."""

    def test_report_fatal_error_writes_the_crash_log_and_shows_a_dialog(self):
        shown = []

        class FakeUser32:
            def MessageBoxW(self, _hwnd, text, caption, _flags):
                shown.append((caption, text))
                return 1

        class FakeWindll:
            user32 = FakeUser32()

        import ctypes as _ctypes

        with tempfile.TemporaryDirectory() as tmp:
            crash_log = Path(tmp) / "crash.log"
            with mock.patch.object(ad, "CRASH_LOG_PATH", crash_log), \
                    mock.patch.object(ad.sys, "platform", "win32"), \
                    mock.patch.object(_ctypes, "windll", FakeWindll(), create=True):
                try:
                    raise RuntimeError("PySide6 plugin missing")
                except RuntimeError as error:
                    ad.report_fatal_error(f"Fatal startup error: {error}")

            self.assertTrue(crash_log.exists(), "the crash log must be written")
            body = crash_log.read_text(encoding="utf-8")
            self.assertIn("PySide6 plugin missing", body)

        self.assertEqual(len(shown), 1)
        caption, text = shown[0]
        self.assertEqual(caption, ad.APP_NAME)
        self.assertIn("PySide6 plugin missing", text)
        self.assertIn(str(crash_log), text,
                      "the dialog must name the file the user should send")

    def test_unhandled_exception_hook_logs_and_notifies(self):
        notices = []
        original = sys.excepthook
        # The hook chains to whatever was installed before it; under pytest-qt
        # that is a recorder that would fail the test on the exception we are
        # deliberately raising.
        sys.excepthook = lambda *_args: None
        with tempfile.TemporaryDirectory() as tmp:
            crash_log = Path(tmp) / "crash.log"
            with mock.patch.object(ad, "CRASH_LOG_PATH", crash_log):
                hook = ad.install_unhandled_exception_hooks(notify=notices.append)
                try:
                    try:
                        raise ValueError("slot exploded")
                    except ValueError:
                        hook(*sys.exc_info())
                finally:
                    sys.excepthook = original

            self.assertTrue(crash_log.exists())
            body = crash_log.read_text(encoding="utf-8")
            self.assertIn("slot exploded", body)
            self.assertIn("Unhandled exception", body)

        self.assertEqual(notices, ["ValueError: slot exploded"])

    def test_unhandled_exception_hook_leaves_keyboard_interrupt_alone(self):
        notices = []
        original = sys.excepthook
        # The hook chains to whatever was installed before it; under pytest-qt
        # that is a recorder that would fail the test on the exception we are
        # deliberately raising.
        sys.excepthook = lambda *_args: None
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ad, "CRASH_LOG_PATH", Path(tmp) / "crash.log"):
                hook = ad.install_unhandled_exception_hooks(notify=notices.append)
                try:
                    hook(KeyboardInterrupt, KeyboardInterrupt(), None)
                finally:
                    sys.excepthook = original
        self.assertEqual(notices, [])


class DownloadManagerTests(unittest.TestCase):
    def test_start_download_applies_profile_format_quality_and_persists_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig({
                "DownloadPath": tmp,
                "SiteProfiles": [{
                    "Name": "Archive",
                    "Domain": "youtube.com",
                    "VideoFormat": "mkv",
                    "Quality": "1080",
                }],
            })
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            dl_id, error = manager.start_download(
                "https://www.youtube.com/watch?v=profile",
                profile_name="Archive",
            )
            self.assertIsNone(error)
            download = manager.downloads[dl_id]
            self.assertEqual(download.format, "mkv")
            self.assertEqual(download.quality, "1080")
            self.assertEqual(download.profile_name, "Archive")
            payload = manager.queue_payload()
            self.assertEqual(payload["downloads"][0]["profileName"], "Archive")

    def test_fourth_download_is_retained_pending_while_three_run(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        release = threading.Event()

        def hold_queued(download):
            download.status = 'downloading'
            release.wait(15)
            download.status = 'complete'
            download.mark_terminal()

        manager._run_download = hold_queued

        ids = []
        for i in range(ad.MAX_CONCURRENT + 1):
            dl_id, err = manager.start_download(f"https://example.com/{i}")
            self.assertIsNone(err)
            ids.append(dl_id)

        self.assertEqual(manager.active_count(), ad.MAX_CONCURRENT)
        self.assertEqual(manager.pending_count(), 1)
        self.assertEqual(manager.downloads[ids[-1]].status, 'pending')
        release.set()

    def test_cancel_does_not_relabel_completed_downloads(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        dl = ad.Download("done", "https://example.com/done")
        dl.status = "complete"
        manager.downloads[dl.id] = dl

        self.assertFalse(manager.cancel(dl.id))
        self.assertEqual(dl.status, "complete")

    def test_cancel_stamps_terminal_time(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        dl = ad.Download("active", "https://example.com/active")
        manager.downloads[dl.id] = dl

        self.assertTrue(manager.cancel(dl.id))
        self.assertEqual(dl.status, "cancelled")
        self.assertIsNotNone(dl.finished_time)

    def test_cleanup_old_uses_finished_time_not_start_time(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        now = time.time()

        recent_long_download = ad.Download("recent-long", "https://example.com/recent-long")
        recent_long_download.status = "complete"
        recent_long_download.start_time = now - 3600
        recent_long_download.finished_time = now

        old_terminal = ad.Download("old-terminal", "https://example.com/old-terminal")
        old_terminal.status = "failed"
        old_terminal.start_time = now - 3600
        old_terminal.finished_time = now - 360

        manager.downloads[recent_long_download.id] = recent_long_download
        manager.downloads[old_terminal.id] = old_terminal

        manager.cleanup_old()

        self.assertIn(recent_long_download.id, manager.downloads)
        self.assertNotIn(old_terminal.id, manager.downloads)

    def test_terminal_records_are_reclaimed_before_queue_cap(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())

        def finish_immediately(download):
            download.status = "complete" if manager._next_id % 2 else "cancelled"
            download.mark_terminal()

        class ImmediateThread:
            def __init__(self, target=None, args=(), daemon=None):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        manager._run_download = finish_immediately
        with mock.patch.object(ad.threading, "Thread", ImmediateThread):
            for index in range(ad.MAX_QUEUED_TOTAL + 5):
                dl_id, err = manager.start_download(f"https://example.com/{index}")
                self.assertIsNone(err)
                self.assertIsNotNone(dl_id)

            active = ad.Download("active-preserved", "https://example.com/active")
            active.status = "downloading"
            manager.downloads[active.id] = active
            dl_id, err = manager.start_download("https://example.com/after-cap")

        self.assertIsNone(err)
        self.assertIsNotNone(dl_id)
        self.assertIn(active.id, manager.downloads)
        self.assertLessEqual(len(manager.downloads), ad.MAX_QUEUED_TOTAL)

    def test_pause_reorder_cancel_and_resume_control_pending_intake(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        self.assertTrue(manager.pause_intake())
        ids = []
        for index in range(3):
            dl_id, err = manager.start_download(f"https://example.com/{index}")
            self.assertIsNone(err)
            ids.append(dl_id)

        self.assertEqual(manager.active_count(), 0)
        self.assertEqual(manager.pending_count(), 3)
        ok, err = manager.move_pending(ids[2], 0)
        self.assertTrue(ok, err)
        self.assertEqual(manager.queue_payload()['downloads'][0]['id'], ids[2])

        running = ad.Download('running', 'https://example.com/running')
        running.status = 'downloading'
        manager.downloads[running.id] = running
        ok, err = manager.move_pending(running.id, 0)
        self.assertFalse(ok)
        self.assertIn('pending', err.lower())

        ok, err = manager.move_pending(ids[0], 0.5)
        self.assertFalse(ok)
        self.assertIn('integer', err.lower())

        self.assertTrue(manager.cancel(ids[1]))
        self.assertEqual(manager.downloads[ids[1]].status, 'cancelled')

    def test_persisted_intake_pause_survives_restart_with_empty_queue(self):
        # Regression: intakePaused was serialized but never read back, so
        # pausing intake with an empty pending list silently un-paused after
        # an application restart.
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            config = FakeConfig({'DownloadPath': tmp, 'AudioDownloadPath': tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            self.assertEqual(manager.pending_count(), 0)

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(restored.intake_paused)

    def test_persisted_queue_restores_paused_and_never_serializes_cookies(self):
        cookies = [{
            'domain': '.youtube.com', 'name': 'SID', 'value': 'top-secret-cookie',
            'path': '/', 'secure': True,
        }]
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            config = FakeConfig({
                'DownloadPath': tmp,
                'AudioDownloadPath': tmp,
            })
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            plain_id, plain_err = manager.start_download(
                'https://www.youtube.com/watch?v=plainQueue',
                section={"start": "1:02.5", "end": "1:05"},
            )
            playlist_id, playlist_err = manager.start_download(
                'https://www.youtube.com/playlist?list=PLplaylistQueue',
                playlist_items=[5, 1, 3, 3],
            )
            auth_id, auth_err = manager.start_download(
                'https://www.youtube.com/watch?v=authQueue1',
                cookies=cookies,
            )
            self.assertIsNone(plain_err)
            self.assertIsNone(playlist_err)
            self.assertIsNone(auth_err)

            persisted = queue_path.read_text(encoding='utf-8')
            self.assertNotIn('top-secret-cookie', persisted)
            self.assertNotIn('cookies_file', persisted)
            self.assertNotIn('cookiesFile', persisted)
            self.assertNotIn('.cookies.', persisted)

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(restored.active_count(), 0)
            self.assertTrue(restored.intake_paused)
            self.assertEqual(restored.downloads[plain_id].status, 'paused')
            self.assertEqual(
                restored.downloads[plain_id].section,
                {"start": 62.5, "end": 65.0},
            )
            self.assertEqual(
                restored.downloads[playlist_id].playlist_items,
                [1, 3, 5],
            )
            self.assertEqual(restored.downloads[auth_id].status, 'needs-auth')

            started = []

            def complete(download):
                started.append(download.id)
                download.status = 'complete'
                download.mark_terminal()

            restored._run_download = complete
            self.assertTrue(restored.resume_intake())
            deadline = time.time() + 15
            while time.time() < deadline and plain_id not in started:
                time.sleep(0.01)
            self.assertIn(plain_id, started)
            self.assertNotIn(auth_id, started)
            self.assertEqual(restored.downloads[auth_id].status, 'needs-auth')

            ok, err = restored.resume_download(auth_id)
            self.assertFalse(ok)
            self.assertIn('Fresh YouTube cookies', err)

            before_count = len(restored.downloads)
            with mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)):
                recovered_id, recovery_err = restored.start_download(
                    'https://www.youtube.com/watch?v=authQueue1',
                    cookies=[{
                        'domain': '.youtube.com', 'name': 'SID', 'value': 'fresh-cookie',
                        'path': '/', 'secure': True,
                    }],
                )
            self.assertIsNone(recovery_err)
            self.assertEqual(recovered_id, auth_id)
            self.assertEqual(len(restored.downloads), before_count)
            self.assertNotIn('fresh-cookie', queue_path.read_text(encoding='utf-8'))
            # A worker teardown queues a deferred write. Leaving this block
            # while one is in flight races the directory removal against the
            # writer's own atomic temp file.
            self.assertTrue(restored.flush_persistence())
            self.assertTrue(manager.flush_persistence())

    def test_restore_queue_defaults_non_string_format_and_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            queue_path.write_text(json.dumps({
                'schemaVersion': ad.DOWNLOAD_QUEUE_SCHEMA_VERSION,
                'intakePaused': True,
                'downloads': [
                    {
                        'id': 'bad-format',
                        'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                        'outputDir': tmp,
                        'audioOnly': False,
                        'format': ['mp4'],
                        'quality': '1080',
                    },
                    {
                        'id': 'bad-quality',
                        'url': 'https://www.youtube.com/watch?v=9bZkp7q19f0',
                        'outputDir': tmp,
                        'audioOnly': True,
                        'format': 'm4a',
                        'quality': {},
                    },
                ],
            }), encoding='utf-8')

            restored = ad.DownloadManager(
                FakeConfig({'DownloadPath': tmp, 'AudioDownloadPath': tmp}),
                FakeHistory(),
                queue_path=queue_path,
            )

        self.assertTrue(restored.intake_paused)
        self.assertEqual(restored.downloads['bad-format'].format, 'mp4')
        self.assertEqual(restored.downloads['bad-format'].quality, '1080')
        self.assertEqual(restored.downloads['bad-quality'].format, 'm4a')
        self.assertEqual(restored.downloads['bad-quality'].quality, 'best')

    def test_empty_paused_queue_restores_paused_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            config = FakeConfig({'DownloadPath': tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)

        self.assertTrue(restored.intake_paused)
        self.assertEqual(restored.pending_count(), 0)

    def test_restore_rejects_non_youtube_and_outside_root_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            outside = str(Path(tmp).parent / 'outside-downloads')
            queue_path.write_text(json.dumps({
                'schemaVersion': ad.DOWNLOAD_QUEUE_SCHEMA_VERSION,
                'intakePaused': True,
                'downloads': [
                    {
                        'id': 'non-youtube',
                        'url': 'https://127.0.0.1/internal',
                        'outputDir': tmp,
                    },
                    {
                        'id': 'outside-root',
                        'url': 'https://www.youtube.com/watch?v=outsideRoot',
                        'outputDir': outside,
                    },
                ],
            }), encoding='utf-8')

            restored = ad.DownloadManager(
                FakeConfig({'DownloadPath': tmp}),
                FakeHistory(),
                queue_path=queue_path,
            )

        self.assertEqual(restored.downloads, {})
        self.assertTrue(restored.intake_paused)

    def test_future_queue_schema_is_preserved_and_blocks_destructive_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            future = {
                'schemaVersion': ad.DOWNLOAD_QUEUE_SCHEMA_VERSION + 1,
                'futureOnly': {'preserve': True},
                'downloads': [],
            }
            queue_path.write_text(json.dumps(future), encoding='utf-8')
            manager = ad.DownloadManager(
                FakeConfig({'DownloadPath': tmp}),
                FakeHistory(),
                queue_path=queue_path,
            )

            dl_id, err = manager.start_download('https://example.com/future-schema')
            self.assertIsNone(dl_id)
            # The surfaced error must name the real cause (schema mismatch),
            # not the generic disk-space/permissions advice.
            self.assertIn('incompatible Astra Downloader version', err)
            self.assertEqual(json.loads(queue_path.read_text(encoding='utf-8')), future)
            self.assertIn('incompatible', manager.queue_payload()['persistenceError'])

    def test_missing_and_older_queue_schemas_are_accepted_and_normalized_on_save(self):
        for stored_version in (None, ad.DOWNLOAD_QUEUE_SCHEMA_VERSION - 1):
            with self.subTest(stored_version=stored_version):
                payload = {"downloads": [], "intakePaused": False}
                if stored_version is not None:
                    payload["schemaVersion"] = stored_version
                writes = []
                logs = []
                store = ad.DownloadQueueStore(
                    path=Path("unused.json"),
                    reader=lambda *_args, payload=payload: payload,
                    writer=lambda _path, data: writes.append(data),
                    logger=logs.append,
                    clean_text=ad.clean_text,
                    clean_path_text=ad.clean_path_text,
                )

                loaded, compatible = store.load()

                self.assertEqual(loaded, payload)
                self.assertTrue(compatible)
                self.assertTrue(store.save([], False))
                self.assertEqual(
                    writes[-1]["schemaVersion"],
                    ad.DOWNLOAD_QUEUE_SCHEMA_VERSION,
                )
                self.assertTrue(any("Migrating download queue schema" in message for message in logs))

    def test_only_classified_transient_failures_can_retry(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()
        transient = ad.Download('transient', 'https://example.com/transient')
        transient.status = 'failed'
        transient.error_code = 'network-unreachable'
        transient.mark_terminal()
        # A failure whose recovery action has NOT been performed. No stored
        # sign-in covers this site, so the precondition is genuinely unmet.
        blocked = ad.Download('blocked', 'https://example.com/members-only')
        blocked.status = 'failed'
        blocked.error_code = 'sign-in-required'
        blocked.mark_terminal()
        manager.downloads[transient.id] = transient
        manager.downloads[blocked.id] = blocked

        ok, err = manager.retry(transient.id)
        self.assertTrue(ok, err)
        self.assertEqual(transient.status, 'pending')

        ok, err = manager.retry(blocked.id)
        self.assertFalse(ok)
        # The refusal has to name what is still missing, not just refuse.
        self.assertIn('stored sign-in', err)
        self.assertFalse(manager.is_retryable(blocked))

    def test_a_failure_becomes_retryable_once_its_precondition_is_met(self):
        # The refusal message promises "needs its recovery action before it can
        # be retried". Nothing used to re-check, so performing the action left
        # the download stuck and the only way forward was to re-paste the URL.
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()
        stalled = ad.Download('stalled', 'https://www.youtube.com/watch?v=abc')
        stalled.status = 'failed'
        stalled.error_code = 'js-runtime-missing'
        stalled.mark_terminal()
        manager.downloads[stalled.id] = stalled

        unusable = {'supported': False, 'ejsReady': False, 'reason': 'runtime-not-installed'}
        manager.update_readiness_snapshot({
            'configuredRuntime': 'auto',
            'runtime': unusable,
            'impersonateTargets': [],
        })
        with mock.patch.object(ad, 'probe_javascript_runtime',
                               side_effect=AssertionError('GUI path spawned a probe')):
            manager._precondition_cache.clear()
            self.assertFalse(manager.is_retryable(stalled))
            ok, err = manager.retry(stalled.id)
            self.assertFalse(ok)
            self.assertIn('JavaScript runtime', err)

        # The user installs the runtime; the readiness probe now reports it.
        usable = {'supported': True, 'ejsReady': True, 'runtime': 'deno'}
        manager.update_readiness_snapshot({
            'configuredRuntime': 'auto',
            'runtime': usable,
            'impersonateTargets': [],
        })
        with mock.patch.object(ad, 'probe_javascript_runtime',
                               side_effect=AssertionError('retry path spawned a probe')):
            manager._precondition_cache.clear()
            self.assertTrue(manager.is_retryable(stalled))
            ok, err = manager.retry(stalled.id)
            self.assertTrue(ok, err)
            self.assertEqual(stalled.status, 'pending')

    def test_recovery_preconditions_use_cached_impersonate_targets(self):
        config = FakeConfig({'ImpersonateTarget': 'Chrome-131'})
        manager = ad.DownloadManager(config, FakeHistory())
        manager.pause_intake()
        blocked = ad.Download('blocked-browser', 'https://example.com/video')
        blocked.status = 'failed'
        blocked.error_code = 'blocked-by-site'
        blocked.mark_terminal()
        manager.downloads[blocked.id] = blocked
        manager.update_readiness_snapshot({
            'configuredRuntime': 'auto',
            'runtime': {},
            'impersonateTargets': ['Chrome-131'],
        })

        with mock.patch.object(ad, 'probe_impersonate_targets',
                               side_effect=AssertionError('GUI path spawned a probe')):
            self.assertTrue(manager.is_retryable(blocked))
            payload = manager.queue_payload()
            self.assertTrue(payload['downloads'][0]['retryable'])

    def test_an_unknown_failure_code_stays_unretryable(self):
        # New codes must default to refusing rather than to allowing.
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()
        unknown = ad.Download('unknown', 'https://example.com/x')
        unknown.status = 'failed'
        unknown.error_code = 'something-invented-later'
        unknown.mark_terminal()
        manager.downloads[unknown.id] = unknown

        self.assertFalse(manager.is_retryable(unknown))
        ok, err = manager.retry(unknown.id)
        self.assertFalse(ok)
        self.assertIn('recovery action', err)

    def test_total_running_and_pending_capacity_remains_bounded(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()
        for index in range(ad.MAX_QUEUED_TOTAL):
            dl_id, err = manager.start_download(f"https://example.com/{index}")
            self.assertIsNone(err)
            self.assertIsNotNone(dl_id)

        dl_id, err = manager.start_download('https://example.com/overflow')
        self.assertIsNone(dl_id)
        self.assertIn(f'{ad.MAX_QUEUED_TOTAL}/{ad.MAX_QUEUED_TOTAL}', err)
        capacity = manager.capacity()
        self.assertEqual(capacity['total'], ad.MAX_QUEUED_TOTAL)
        self.assertEqual(capacity['available'], 0)
        failed = ad.Download('failed-retry', 'https://example.com/failed-retry')
        failed.status = 'failed'
        failed.error_code = 'network-unreachable'
        failed.mark_terminal()
        manager.downloads[failed.id] = failed
        ok, retry_err = manager.retry(failed.id)
        self.assertFalse(ok)
        self.assertIn('queue is full', retry_err.lower())
        self.assertEqual(manager.capacity()['total'], ad.MAX_QUEUED_TOTAL)


class HostBackoffTests(unittest.TestCase):
    def test_a_blocked_domain_does_not_hide_another_host_from_the_scheduler(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        blocked = ad.Download(
            "blocked", "https://media.example.com/blocked", title="Blocked"
        )
        blocked.status = "pending"
        blocked.queue_order = 1
        other = ad.Download(
            "other", "https://other.test/video", title="Other"
        )
        other.status = "pending"
        other.queue_order = 2
        manager.downloads.update({blocked.id: blocked, other.id: other})
        manager._host_backoffs["example.com"] = {
            "until": time.monotonic() + 60,
            "retry_after": 60,
            "failures": 1,
        }

        with mock.patch.object(manager, "_arm_host_backoff_wakeup") as arm_wakeup, \
                mock.patch.object(manager, "_launch_workers") as launch:
            manager._schedule()

        self.assertEqual(blocked.status, "pending")
        self.assertEqual(other.status, "queued")
        self.assertIn(other.id, manager._running_ids)
        launch.assert_called_once_with([other])
        arm_wakeup.assert_called_once()

    def test_retry_after_is_recorded_by_registrable_domain_and_blocks_manual_retry(self):
        manager = ad.DownloadManager(
            FakeConfig({"PacingJitterPercent": 0}), FakeHistory()
        )
        with mock.patch.object(manager, "_arm_host_backoff_wakeup"):
            remaining = manager._record_host_backoff(
                "https://cdn.example.co.uk/watch", retry_after_seconds=4
            )

        self.assertIn("example.co.uk", manager._host_backoffs)
        self.assertGreaterEqual(remaining, 3.0)
        self.assertLessEqual(remaining, 4.0)
        self.assertGreater(
            manager.host_backoff_remaining("https://www.example.co.uk/other"),
            0,
        )
        self.assertEqual(manager.host_backoff_remaining("https://other.test/video"), 0)

        failed = ad.Download("limited", "https://www.example.co.uk/retry")
        failed.status = "failed"
        failed.error_code = "rate-limited"
        failed.mark_terminal()
        manager.downloads[failed.id] = failed
        ok, error = manager.retry(failed.id)
        self.assertFalse(ok)
        self.assertIn("retry in", error)

    def test_three_same_refusals_open_a_domain_circuit_and_hold_the_next_item(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()
        ids = [
            manager.start_download(
                f"https://www.example.com/video-{index}"
            )[0]
            for index in range(4)
        ]
        manager.intake_paused = False

        with mock.patch.object(manager, "_arm_host_backoff_wakeup"):
            for dl_id in ids[:3]:
                download = manager.downloads[dl_id]
                download.status = "failed"
                download.error = "Sign in to confirm you are not a bot"
                download.error_code = "sign-in-required"
                manager._record_terminal_download(download)

        circuit = manager._host_circuits["example.com"]
        self.assertEqual(circuit["failures"], 3)
        self.assertEqual(circuit["error_code"], "sign-in-required")
        self.assertGreater(
            manager.host_backoff_remaining("https://example.com/next"), 0
        )

        held = manager.downloads[ids[3]]
        with mock.patch.object(manager, "_arm_host_backoff_wakeup"), \
                mock.patch.object(manager, "_launch_workers") as launch:
            manager._schedule()

        self.assertEqual(held.status, "pending")
        launch.assert_not_called()

        gui = gui_module_for_tests()
        queue_window = types.SimpleNamespace(
            dl_manager=manager,
            _value=lambda name: getattr(ad, name),
            _download_host_backoff_seconds=lambda dl: int(
                manager.host_backoff_remaining(dl.url)
            ),
        )
        queue_text = gui.MainWindowCore._download_meta_text(queue_window, held)
        self.assertIn("Host paused", queue_text)
        self.assertIn("retry in", queue_text)


class DownloadFailureClassifierTests(unittest.TestCase):
    def test_classifies_recoverable_youtube_failures(self):
        cases = [
            ('ERROR: Missing PO Token for web client', 'po-token-required'),
            ('bgutil PO token provider failed to issue token: stale provider', 'po-provider-stale'),
            ('ERROR: requested format is not available; SABR only', 'sabr-limited'),
            ('ERROR: Playability status UNPLAYABLE; tv_downgraded', 'cookie-incompatible'),
            ('Deno JavaScript runtime not found for n/sig signature solving', 'deno-runtime-missing'),
            ('ERROR: Sign in to confirm you are not a bot', 'sign-in-required'),
            ('ERROR: ffmpeg not found; install ffmpeg', 'ffmpeg-missing-or-stale'),
            ('ERROR: Unable to download webpage: HTTP Error 503', 'network-unreachable'),
        ]
        for message, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(ad.classify_download_failure(message), expected)

    def test_message_borne_cause_outranks_benign_warning_lines(self):
        # yt-dlp routinely emits a benign "PO Token which was not provided"
        # WARNING during extraction; it must never shadow the real failure
        # cause carried by the final error message.
        warn_tail = [
            '[youtube] Extracting URL',
            'WARNING: [youtube] xyz: some web formats require a PO Token '
            'which was not provided',
        ]
        cases = [
            ('ERROR: Connection reset by peer', 'network-unreachable'),
            ('ERROR: ffmpeg exited with code 1', 'ffmpeg-missing-or-stale'),
            ('ERROR: Sign in to confirm you are not a bot', 'sign-in-required'),
        ]
        for message, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    ad.classify_download_failure(message, lines=warn_tail),
                    expected,
                )
        # An unrecognized message still falls back to the output tail.
        self.assertEqual(
            ad.classify_download_failure('exit code 1', lines=warn_tail),
            'po-token-required',
        )

    def test_benign_failure_noise_never_becomes_the_surfaced_error(self):
        import download
        noise = [
            'WARNING: Your yt-dlp version (2026.03.17) is older than 90 days!',
            '[youtube] dQw4w9WgXcQ: Downloading webpage',
            'WARNING: [youtube] some web formats require a PO Token',
            '[download] Destination: video.mp4',
            'MDLP_JSON {"downloaded_bytes": 1}',
        ]
        for line in noise:
            with self.subTest(line=line):
                self.assertTrue(download._is_benign_failure_noise(line))
        for line in (
            'ERROR: Video unavailable',
            'ERROR: Sign in to confirm you are not a bot',
            'ffmpeg exited with code 1',
        ):
            with self.subTest(line=line):
                self.assertFalse(download._is_benign_failure_noise(line))
        # The whole point: the version-age nag must never be the failure reason.
        meaningful = [ln for ln in noise if not download._is_benign_failure_noise(ln)]
        self.assertEqual(meaningful, [])

    def test_download_error_payload_keeps_legacy_code_and_action_fields(self):
        payload = ad.download_error_payload('po-token-required')

        self.assertEqual(payload['code'], 'po-token-required')
        self.assertEqual(payload['error_code'], 'po-token-required')
        self.assertEqual(payload['next_action'], 'sign-in-and-retry')
        self.assertIn('proof-of-origin token', payload['error'])
        self.assertNotIn('bgutil', payload['advice'].lower())

    def test_download_to_dict_includes_failure_recovery_metadata(self):
        dl = ad.Download('dl_test', 'https://www.youtube.com/watch?v=abcdefghijk')

        ad.apply_download_failure_classification(dl, 'ffmpeg-missing-or-stale')
        payload = dl.to_dict()

        self.assertEqual(payload['error_code'], 'ffmpeg-missing-or-stale')
        self.assertEqual(payload['next_action'], 'refresh-ffmpeg')
        self.assertIn('ffmpeg', payload['advice'])


class CookieJarTests(unittest.TestCase):
    """Audit-pass coverage for write_cookies_netscape.

    The extension pushes Chrome cookie objects into the server's /download
    request and yt-dlp needs them in Netscape cookies.txt format. Regressing
    the converter would silently break logged-in/age-gated downloads, so each
    behaviour below is locked down by a dedicated test.
    """

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_returns_none_for_empty_or_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            self.assertIsNone(ad.write_cookies_netscape(None, target))
            self.assertIsNone(ad.write_cookies_netscape([], target))
            self.assertIsNone(ad.write_cookies_netscape("not a list", target))
            # All entries invalid (missing name/domain) → no jar written.
            self.assertIsNone(ad.write_cookies_netscape(
                [{"name": ""}, {"domain": ".youtube.com"}],
                target,
            ))
            self.assertFalse(target.exists())

    def test_writes_netscape_format_with_httponly_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            cookies = [
                {
                    "domain": ".youtube.com", "name": "SID", "value": "abc",
                    "path": "/", "secure": True, "httpOnly": True,
                    "expirationDate": 1700000000,
                },
                {
                    "domain": "youtube.com", "name": "PREF", "value": "tz=UTC",
                    "path": "/", "secure": False, "httpOnly": False,
                    # Session cookie (no expirationDate) — must serialize as 0
                    "expirationDate": None,
                },
            ]
            result = ad.write_cookies_netscape(cookies, target)
            self.assertEqual(result, str(target))
            body = self._read(target)
            self.assertIn("# Netscape HTTP Cookie File", body)
            # httpOnly cookie gets the #HttpOnly_ prefix yt-dlp expects.
            self.assertIn("#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1700000000\tSID\tabc", body)
            self.assertIn("youtube.com\tFALSE\t/\tFALSE\t0\tPREF\ttz=UTC", body)

    def test_system_binaries_resolve_through_system32(self):
        # CreateProcess searches the CWD before %PATH% for a bare argv[0], so
        # `icacls`/`powershell`/`schtasks` by name can be shadowed by a file
        # dropped where the app runs — and the icacls call is the one applying
        # the cookie-jar ACL. Pin the absolute resolutions.
        root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
        self.assertEqual(
            ad.system32_command('powershell').lower(),
            str(root / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe').lower(),
        )
        self.assertEqual(
            ad.system32_command('schtasks').lower(),
            str(root / 'System32' / 'schtasks.exe').lower(),
        )
        import download as _download_module
        self.assertEqual(
            _download_module._system32_icacls().lower(),
            str(root / 'System32' / 'icacls.exe').lower(),
        )
        # No bare-name spawn may come back: every subprocess.run in the
        # package must also carry a timeout.
        module_dir = Path(ad.__file__).resolve().parent
        for name in ("astra_downloader.py", "download.py", "health.py",
                     "gui.py", "config.py", "subscriptions.py", "routes.py"):
            tree = ast.parse((module_dir / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Attribute) and func.attr == "run"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "subprocess"):
                    self.assertIn(
                        "timeout", {k.arg for k in node.keywords},
                        f"{name}:{node.lineno} subprocess.run has no timeout",
                    )
                first = node.args[0] if node.args else None
                if isinstance(first, ast.List) and first.elts:
                    head = first.elts[0]
                    if isinstance(head, ast.Constant) and isinstance(head.value, str):
                        self.assertNotIn(
                            head.value.lower(), ("icacls", "powershell", "schtasks"),
                            f"{name}:{node.lineno} spawns {head.value} by bare name",
                        )

    @unittest.skipUnless(os.name == 'nt', 'Windows ACLs are only available on Windows')
    def test_cookie_jar_has_no_inherited_broad_acl(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            result = ad.write_cookies_netscape([{
                "domain": ".youtube.com", "name": "SID", "value": "secret",
            }], target)
            self.assertEqual(result, str(target))

            acl = subprocess.run(
                ["icacls", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(acl.returncode, 0, acl.stderr)
            acl_text = f"{acl.stdout}\n{acl.stderr}"
            self.assertNotIn("(I)", acl_text,
                             "cookie jar must not retain inherited ACEs")
            self.assertNotRegex(
                acl_text,
                r"(?i)(everyone|authenticated users|builtin\\users)",
                "cookie jar must not grant broad local-user access",
            )

    def test_acl_failure_writes_no_cookie_bytes(self):
        import importlib

        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            download_module = importlib.import_module("download")
            with mock.patch.object(download_module, "_apply_cookie_jar_acl",
                                   side_effect=PermissionError("ACL denied")):
                result = download_module.write_cookies_netscape(
                    [{"domain": ".youtube.com", "name": "SID", "value": "secret"}],
                    target,
                    logger=logs.append,
                )
            self.assertIsNone(result)
            self.assertFalse(target.exists())
            self.assertTrue(any("ACL denied" in line for line in logs))

    def test_non_finite_expiry_degrades_to_session_cookie(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            result = ad.write_cookies_netscape([{
                "domain": ".youtube.com",
                "name": "SID",
                "value": "secret",
                "expirationDate": float("inf"),
            }], target)

            self.assertEqual(result, str(target))
            self.assertIn("\t0\tSID\tsecret", self._read(target))

    def test_strips_control_chars_that_would_corrupt_tsv(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            cookies = [
                # Tabs/newlines in a value would shift columns in the TSV and
                # make yt-dlp fail to parse the jar. Control-char stripping
                # produces a well-formed single-line value.
                {"domain": ".youtube.com", "name": "X", "value": "a\tb\nc"},
                {"domain": ".youtube.com", "name": "Y", "value": "ok"},
            ]
            self.assertEqual(ad.write_cookies_netscape(cookies, target), str(target))
            body = self._read(target)
            # The line for X must end with a clean value containing no raw
            # tabs or newlines beyond the column separator.
            x_line = [line for line in body.splitlines() if "\tX\t" in line][0]
            self.assertTrue(x_line.endswith("abc"))
            self.assertEqual(x_line.count("\t"), 6)  # 7 columns → 6 separators
            self.assertIn("Y\tok", body)

    def test_rejects_malformed_expiration_without_failing_whole_jar(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cookies.txt"
            cookies = [
                {"domain": ".youtube.com", "name": "A", "value": "a", "expirationDate": "bogus"},
                {"domain": ".youtube.com", "name": "B", "value": "b", "expirationDate": -42},
                {"domain": ".youtube.com", "name": "C", "value": "c", "expirationDate": 100},
            ]
            self.assertEqual(ad.write_cookies_netscape(cookies, target), str(target))
            body = self._read(target)
            self.assertIn("\tA\ta", body)  # bogus → 0
            self.assertIn("\t0\tA\ta", body)
            self.assertIn("\t0\tB\tb", body)  # negative → 0
            self.assertIn("\t100\tC\tc", body)


class ProcessTerminationTests(unittest.TestCase):
    def test_process_kill_fallbacks_emit_warning_level_diagnostics(self):
        import importlib

        download_module = importlib.import_module("download")
        logs = []

        class FailingProcess:
            pid = 123

            def poll(self):
                return None

            def terminate(self):
                raise OSError("terminate denied")

            def kill(self):
                raise OSError("kill denied")

        def fail_taskkill(*_args, **_kwargs):
            raise OSError("taskkill denied")

        download_module.terminate_process_tree(
            FailingProcess(),
            platform="win32",
            runner=fail_taskkill,
            logger=logs.append,
        )

        self.assertGreaterEqual(len(logs), 3)
        self.assertTrue(all(message.startswith("WARNING:") for message in logs))


class Sha256VerifyTests(unittest.TestCase):
    """v1.2.0 S3 — binary integrity verification for yt-dlp/ffmpeg."""

    def test_verify_accepts_matching_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bin.exe"
            path.write_bytes(b"hello world")
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertTrue(ad.verify_file_sha256(path, expected))

    def test_verify_raises_on_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bin.exe"
            path.write_bytes(b"tampered bytes")
            wrong = "0" * 64
            with self.assertRaises(RuntimeError) as ctx:
                ad.verify_file_sha256(path, wrong)
            self.assertIn("SHA-256 mismatch", str(ctx.exception))

    def test_verify_returns_false_on_missing_or_malformed_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bin.exe"
            path.write_bytes(b"hi")
            self.assertFalse(ad.verify_file_sha256(path, None))
            self.assertFalse(ad.verify_file_sha256(path, ""))
            self.assertFalse(ad.verify_file_sha256(path, "not-a-hash"))

    def test_parse_sha256_sums_with_multiple_assets(self):
        doc = (
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa  yt-dlp.exe\n"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb  yt-dlp\n"
            "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc  yt-dlp_macos\n"
        )
        self.assertEqual(
            ad._parse_sha256_sums(doc, target_asset="yt-dlp.exe"),
            "a" * 64,
        )

    def test_parse_sha256_sums_accepts_single_line_sidecar(self):
        digest = "d" * 64
        self.assertEqual(ad._parse_sha256_sums(f"{digest}\n"), digest)
        self.assertIsNone(
            ad._parse_sha256_sums(f"{digest}\n", target_asset="other.exe")
        )


    def test_deno_get_filehash_sidecar_yields_a_digest(self):
        # Deno publishes the console rendering of PowerShell's Get-FileHash,
        # not a sha256sum line. Before this was handled the digest could not be
        # read at all and the Deno download fell through unverified.
        sidecar = "\r\n".join([
            "",
            "Algorithm : SHA256",
            "Hash      : 171EFAB55AC6B9881FD53EE4C20F8BF3BB1340FFC618483746909014DB12216A",
            "Path      : C:\\a\\deno\\deno\\target\\release\\deno-x86_64-pc-windows-msvc.zip",
            "",
        ])
        self.assertEqual(
            ad._parse_sha256_sums(sidecar, target_asset="deno-x86_64-pc-windows-msvc.zip"),
            "171efab55ac6b9881fd53ee4c20f8bf3bb1340ffc618483746909014db12216a",
        )
        self.assertIsNone(
            ad._parse_sha256_sums(sidecar, target_asset="deno-aarch64-pc-windows-msvc.zip"),
            "a digest must not be handed to an asset the sidecar does not name",
        )
        self.assertIsNone(
            ad._parse_sha256_sums(
                "Algorithm : SHA256\r\nPath      : C:\\out\\deno.zip",
                target_asset="deno.zip",
            ),
            "a block with no Hash line resolves to nothing",
        )

    def test_get_filehash_blocks_are_paired_not_scanned(self):
        # denoland publishes arm64 Windows builds too. A last-wins scan over
        # Hash and Path lines separately would hand one asset's digest to the
        # other, and the JS resolver that records the digest in the licence
        # policy pairs them, so both parsers have to agree.
        two_blocks = "\r\n".join([
            "Algorithm : SHA256",
            "Hash      : " + ("a" * 64).upper(),
            "Path      : C:\\out\\deno-x86_64-pc-windows-msvc.zip",
            "",
            "Algorithm : SHA256",
            "Hash      : " + ("b" * 64).upper(),
            "Path      : C:\\out\\deno-aarch64-pc-windows-msvc.zip",
        ])
        self.assertEqual(
            ad._parse_sha256_sums(two_blocks, target_asset="deno-x86_64-pc-windows-msvc.zip"),
            "a" * 64,
        )
        self.assertEqual(
            ad._parse_sha256_sums(two_blocks, target_asset="deno-aarch64-pc-windows-msvc.zip"),
            "b" * 64,
        )

        stray_path = "\r\n".join([
            "Algorithm : SHA256",
            "Hash      : " + ("a" * 64).upper(),
            "Path      : C:\\out\\SOMETHING-ELSE.zip",
            "Path      : C:\\out\\deno-x86_64-pc-windows-msvc.zip",
        ])
        self.assertIsNone(
            ad._parse_sha256_sums(stray_path, target_asset="deno-x86_64-pc-windows-msvc.zip"),
            "a trailing Path line must not re-point the digest above it",
        )

    def test_ffmpeg_checksum_manifest_selects_the_named_archive(self):
        digest = "f" * 64
        manifest = (
            f"{'e' * 64}  ffmpeg-master-latest-win64-gpl-shared.zip\n"
            f"{digest}  ffmpeg-master-latest-win64-gpl.zip\n"
        )
        self.assertEqual(
            ad._parse_sha256_sums(manifest, target_asset=ad.FFMPEG_SHA256_ASSET),
            digest,
        )
        self.assertEqual(ad.FFMPEG_SHA256_ASSET, "ffmpeg-master-latest-win64-gpl.zip")
        self.assertTrue(ad.FFMPEG_SHA256_URL.endswith("/checksums.sha256"))

    class _SidecarResponse:
        def __init__(self, chunks, *, status_code=200, headers=None):
            self._chunks = list(chunks)
            self.status_code = status_code
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def iter_content(self, _chunk_size):
            return iter(self._chunks)

    def test_checksum_sidecar_fetch_is_streamed_and_bounded(self):
        digest = b"e" * 64
        valid = self._SidecarResponse([digest[:20], digest[20:] + b"  yt-dlp.exe\n"])
        with mock.patch.object(ad, 'first_party_http_get', return_value=valid) as get:
            result = ad.fetch_expected_sha256(
                "https://example.invalid/SHA2-256SUMS", target_asset="yt-dlp.exe",
            )
        self.assertEqual(result, "e" * 64)
        self.assertTrue(get.call_args.kwargs['stream'])

        oversized = self._SidecarResponse(
            [b"x" * (ad.CHECKSUM_SIDECAR_MAX_BYTES + 1)],
        )
        with mock.patch.object(ad, 'first_party_http_get', return_value=oversized):
            self.assertIsNone(ad.fetch_expected_sha256("https://example.invalid/sums"))

    def test_checksum_sidecar_rejects_oversized_content_length_before_reading(self):
        response = self._SidecarResponse(
            [b"f" * 64],
            headers={'content-length': str(ad.CHECKSUM_SIDECAR_MAX_BYTES + 1)},
        )
        with mock.patch.object(ad, 'first_party_http_get', return_value=response):
            self.assertIsNone(ad.fetch_expected_sha256("https://example.invalid/sums"))

    def test_bare_sidecar_must_name_the_requested_asset(self):
        response = self._SidecarResponse([b"f" * 64])
        with mock.patch.object(ad, 'first_party_http_get', return_value=response):
            self.assertIsNone(ad.fetch_expected_sha256(
                "https://example.invalid/other.exe.sha256",
                target_asset="yt-dlp.exe",
            ))

        response = self._SidecarResponse([b"f" * 64])
        with mock.patch.object(ad, 'first_party_http_get', return_value=response):
            self.assertEqual(ad.fetch_expected_sha256(
                "https://example.invalid/yt-dlp.exe.sha256",
                target_asset="yt-dlp.exe",
            ), "f" * 64)


class SetupChecksumTests(unittest.TestCase):
    def test_setup_worker_preserves_auto_update_preference(self):
        self.assertFalse(ad.SetupWorker(auto_update_ytdlp=False).auto_update_ytdlp)
        self.assertTrue(ad.SetupWorker(auto_update_ytdlp=True).auto_update_ytdlp)

    def test_forced_ffmpeg_refresh_preserves_existing_binary_on_download_failure(self):
        original_install_dir = ad.INSTALL_DIR
        original_ytdlp_path = ad.YTDLP_PATH
        original_ffmpeg_path = ad.FFMPEG_PATH
        original_download_path = ad.DEFAULT_CONFIG["DownloadPath"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ad.INSTALL_DIR = root
            ad.YTDLP_PATH = root / "yt-dlp.exe"
            ad.FFMPEG_PATH = root / "ffmpeg.exe"
            ad.DEFAULT_CONFIG["DownloadPath"] = str(root / "downloads")
            ad.YTDLP_PATH.write_bytes(b"existing yt-dlp")
            ad.FFMPEG_PATH.write_bytes(b"known working ffmpeg")
            worker = ad.SetupWorker(force_ffmpeg=True)
            try:
                with mock.patch.object(ad, 'first_party_http_get', side_effect=RuntimeError('offline')), \
                        mock.patch.object(ad, 'log_crash'):
                    worker.run()
                self.assertEqual(ad.FFMPEG_PATH.read_bytes(), b"known working ffmpeg")
            finally:
                ad.INSTALL_DIR = original_install_dir
                ad.YTDLP_PATH = original_ytdlp_path
                ad.FFMPEG_PATH = original_ffmpeg_path
                ad.DEFAULT_CONFIG["DownloadPath"] = original_download_path

    def test_setup_worker_rejects_missing_helper_checksum_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yt-dlp.exe"
            path.write_bytes(b"helper")
            worker = ad.SetupWorker()
            with mock.patch.object(ad, 'fetch_expected_sha256', return_value=None), \
                    mock.patch.object(ad, 'write_persistent_log') as log:
                with self.assertRaises(RuntimeError) as ctx:
                    worker._verify_required_checksum(
                        path, "https://example.invalid/SHA2-256SUMS",
                        asset_name="yt-dlp.exe", label="yt-dlp",
                    )
            self.assertIn("sidecar", str(ctx.exception))
            self.assertFalse(path.exists())
            log.assert_called()

    def test_setup_worker_accepts_matching_helper_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yt-dlp.exe"
            payload = b"helper"
            path.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            worker = ad.SetupWorker()
            with mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected):
                self.assertTrue(worker._verify_required_checksum(
                    path, "https://example.invalid/SHA2-256SUMS",
                    asset_name="yt-dlp.exe", label="yt-dlp",
                ))
            self.assertTrue(path.exists())

    def test_setup_worker_deletes_helper_on_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ffmpeg.zip"
            path.write_bytes(b"wrong")
            worker = ad.SetupWorker()
            with mock.patch.object(ad, 'fetch_expected_sha256', return_value="0" * 64):
                with self.assertRaises(RuntimeError):
                    worker._verify_required_checksum(
                        path, "https://example.invalid/ffmpeg.zip.sha256",
                        label="ffmpeg",
                    )
            self.assertFalse(path.exists())

    def test_setup_worker_keeps_existing_binary_until_staged_checksum_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yt-dlp.exe"
            previous = b"previous verified helper"
            replacement = b"replacement helper"
            path.write_bytes(previous)
            worker = ad.SetupWorker()

            def fake_download(_url, staged, **_kwargs):
                Path(staged).write_bytes(replacement)

            def verify_staged(staged, _expected):
                self.assertNotEqual(Path(staged), path)
                self.assertEqual(path.read_bytes(), previous)
                return True

            with mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "fetch_expected_sha256",
                                      return_value="a" * 64), \
                    mock.patch.object(ad, "verify_file_sha256",
                                      side_effect=verify_staged):
                installed = worker._download_verified_binary(
                    "https://example.invalid/yt-dlp.exe", path,
                    "https://example.invalid/yt-dlp.exe.sha256",
                    asset_name="yt-dlp.exe", label="yt-dlp",
                )

            self.assertEqual(installed, path)
            self.assertEqual(path.read_bytes(), replacement)
            self.assertEqual(list(path.parent.glob(".yt-dlp.exe.*.verified")), [])

    def test_setup_worker_keeps_existing_binary_when_staged_checksum_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yt-dlp.exe"
            previous = b"previous verified helper"
            path.write_bytes(previous)
            worker = ad.SetupWorker()

            def fake_download(_url, staged, **_kwargs):
                Path(staged).write_bytes(b"bad replacement")

            with mock.patch.object(ad, "download_file_atomic", fake_download), \
                    mock.patch.object(ad, "fetch_expected_sha256",
                                      return_value="0" * 64):
                with self.assertRaises(RuntimeError):
                    worker._download_verified_binary(
                        "https://example.invalid/yt-dlp.exe", path,
                        "https://example.invalid/yt-dlp.exe.sha256",
                        asset_name="yt-dlp.exe", label="yt-dlp",
                    )

            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(path.parent.glob(".yt-dlp.exe.*.verified")), [])

    def test_setup_worker_passes_ffmpeg_asset_name_to_checksum_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / ad.FFMPEG_SHA256_ASSET
            archive.write_bytes(b"ffmpeg archive")
            worker = ad.SetupWorker()
            with mock.patch.object(
                ad, "fetch_expected_sha256", return_value="f" * 64
            ) as fetch, mock.patch.object(ad, "verify_file_sha256") as verify:
                worker._verify_required_checksum(
                    archive,
                    ad.FFMPEG_SHA256_URL,
                    asset_name=worker._value("FFMPEG_SHA256_ASSET"),
                    label="ffmpeg",
                )
        fetch.assert_called_once_with(
            ad.FFMPEG_SHA256_URL,
            target_asset=ad.FFMPEG_SHA256_ASSET,
        )
        verify.assert_called_once_with(archive, "f" * 64)

    def test_setup_worker_routes_updates_through_staged_rollback_updater(self):
        config = FakeConfig({'AutoUpdateYtDlp': True})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ytdlp = root / 'yt-dlp.exe'
            ffmpeg = root / 'ffmpeg.exe'
            icon = root / 'icon.ico'
            for path in (ytdlp, ffmpeg, icon):
                path.write_bytes(b'existing')
            download_path = root / 'downloads'
            with mock.patch.object(ad, 'INSTALL_DIR', root), \
                    mock.patch.object(ad, 'YTDLP_PATH', ytdlp), \
                    mock.patch.object(ad, 'FFMPEG_PATH', ffmpeg), \
                    mock.patch.object(ad, 'ICON_PATH', icon), \
                    mock.patch.dict(ad.DEFAULT_CONFIG, {'DownloadPath': str(download_path)}), \
                    mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.07.04'), \
                    mock.patch.object(ad, 'ytdlp_needs_external_runtime', return_value=False), \
                    mock.patch.object(ad, '_run_ytdlp_self_update', return_value={
                        'ok': True, 'version_after': '2026.07.05',
                    }) as update, \
                    mock.patch.object(ad, '_set_integrations_stamp'), \
                    mock.patch.object(ad, 'register_desktop_shortcut'), \
                    mock.patch.object(ad, 'register_startup_task'), \
                    mock.patch.object(ad, 'register_protocol_handlers'), \
                    mock.patch.object(ad, 'register_uninstall_entry'):
                worker = ad.SetupWorker(config=config)
                worker.run()

        update.assert_called_once_with(config, source_tag='setup')


class CookieJarSweepTests(unittest.TestCase):
    """v1.2.0 S4 — orphaned .cookies.*.txt cleanup on server start.

    When the downloader is killed mid-run (power loss, taskkill /F), session
    cookies leak into INSTALL_DIR. A stale sweep on DownloadManager init
    keeps session cookies from outliving the process that needed them.
    """

    def test_cleanup_removes_old_cookie_jars_and_spares_fresh_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            original = ad.INSTALL_DIR
            try:
                ad.INSTALL_DIR = install_dir
                stale = install_dir / ".cookies.abc123.txt"
                fresh = install_dir / ".cookies.def456.txt"
                fresh_probe = install_dir / ".cookies.probe.crashed.txt"
                unrelated = install_dir / "config.json"
                stale.write_text("stale", encoding="utf-8")
                fresh.write_text("fresh", encoding="utf-8")
                fresh_probe.write_text("probe", encoding="utf-8")
                unrelated.write_text("{}", encoding="utf-8")
                # Backdate the stale entry to beyond the cleanup horizon.
                old_mtime = time.time() - 3600
                import os as _os
                _os.utime(stale, (old_mtime, old_mtime))
                ad.cleanup_stale_cookie_jars(older_than_seconds=300)
                self.assertFalse(stale.exists(), "stale cookie jar should be removed")
                self.assertTrue(fresh.exists(), "fresh cookie jar should be preserved")
                self.assertFalse(fresh_probe.exists(), "probe jars must be removed regardless of age")
                self.assertTrue(unrelated.exists(), "non-cookie files must not be touched")
            finally:
                ad.INSTALL_DIR = original


class CookieThreatModelDocTests(unittest.TestCase):
    """Keep the cookie-risk documentation tied to live mitigations."""

    def test_doc_records_advisory_and_companion_cookie_controls(self):
        root = Path(__file__).resolve().parent.parent
        doc_path = root / "docs" / "yt-dlp-cookie-threat-model.md"
        body = doc_path.read_text(encoding="utf-8")
        requirements = (root / "astra_downloader" / "requirements.txt").read_text(
            encoding="utf-8")
        ytdlp_pin = next(
            line.strip() for line in requirements.splitlines()
            if line.strip().startswith("yt-dlp==")
        )
        for needle in [
            "CVE-2023-35934",
            "GHSA-v8mc-9377-rwjj",
            "2023.07.06",
            f"Astra Downloader {ad.APP_VERSION}",
            "Astra Deck browser extension",
            # Read back off requirements.txt rather than frozen here: the doc
            # claimed 2026.6.9 while the repo pinned 2026.8.19, and this test
            # was what kept the stale claim in place.
            ytdlp_pin,
            "ALLOWED_COOKIE_DOMAINS",
            ".youtube.com",
            "write_cookies_netscape()",
            "--cookies",
            "200 entries",
            "cleanup_stale_cookie_jars()",
            "300 seconds",
            "127.0.0.1",
        ]:
            self.assertIn(needle, body)
        self.assertNotIn("Companion v1.8.0", body)
        self.assertNotIn("Companion v1.9.0", body)


class LogWriterThreadTests(unittest.TestCase):
    """The Qt main thread must not sit on the disk to write a log line.

    write_persistent_log did mkdir + stat + open + write while holding a lock
    every worker thread also wants, and the GUI called it from _append_log on
    every status change.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log_path = Path(self._tmp.name) / "server.log"
        patcher = mock.patch.object(ad, "LOG_PATH", self.log_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(ad.flush_persistent_log)

    def test_the_calling_thread_does_no_file_io(self):
        opened_by = []
        real_open = ad.open if hasattr(ad, "open") else open

        def watching_open(target, *args, **kwargs):
            if str(target) == str(self.log_path):
                opened_by.append(threading.current_thread().name)
            return real_open(target, *args, **kwargs)

        caller = threading.current_thread().name
        with mock.patch("builtins.open", watching_open):
            ad.write_persistent_log("queued from the caller")
            self.assertEqual(
                opened_by, [],
                "the calling thread must not touch the log file",
            )
            self.assertTrue(ad.flush_persistent_log(timeout=10))

        self.assertTrue(opened_by, "the writer thread must have written it")
        self.assertNotIn(caller, opened_by)
        self.assertTrue(all(name.startswith("astra-log-writer") for name in opened_by))

    def test_the_line_still_reaches_the_file_in_order(self):
        for index in range(20):
            ad.write_persistent_log(f"line {index:02d}")
        self.assertTrue(ad.flush_persistent_log(timeout=10))

        body = self.log_path.read_text(encoding="utf-8")
        positions = [body.index(f"line {index:02d}") for index in range(20)]
        self.assertEqual(positions, sorted(positions),
                         "a single writer thread must preserve the order")

    def test_the_in_memory_ring_is_updated_without_waiting(self):
        # The GUI reads the ring immediately, so it stays on the caller.
        marker = "ring visible right away"
        ad.write_persistent_log(marker)
        self.assertIn(
            marker,
            [entry["msg"] for entry in ad.get_recent_log_entries()],
        )

    def test_a_synchronous_write_lands_before_it_returns(self):
        # The crash path cannot rely on a daemon thread that is about to die.
        ad.write_persistent_log("crash detail", self.log_path, synchronous=True)
        self.assertIn("crash detail", self.log_path.read_text(encoding="utf-8"))

    def test_the_crash_paths_are_synchronous(self):
        source = Path(ad.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "write_persistent_log":
                continue
            targets = [ast.unparse(arg) for arg in node.args[1:]]
            if not any("CRASH_LOG_PATH" in target for target in targets):
                continue
            if not any(kw.arg == "synchronous" for kw in node.keywords):
                offenders.append(node.lineno)
        self.assertEqual(
            offenders, [],
            f"crash-log writes must not be queued: lines {offenders}",
        )


class TimedOutProcessReapTests(unittest.TestCase):
    """A tree-kill closes the pipes, which is not the same as waiting.

    Every timeout handler used to terminate and return. The reader threads
    exited because the pipes closed, so it looked finished, but the Popen was
    never waited on and the OS kept the process entry until the object was
    collected.
    """

    class FakeProc:
        def __init__(self, raises=None):
            self.communicate_calls = []
            self.terminated = 0
            self._raises = raises

        def communicate(self, timeout=None):
            self.communicate_calls.append(timeout)
            if self._raises is not None:
                raise self._raises
            return "", ""

    def test_the_child_is_waited_on_after_the_kill(self):
        import download as download_module

        proc = self.FakeProc()
        logged = []
        download_module.reap_terminated_process(
            proc,
            lambda target: setattr(target, "terminated", target.terminated + 1),
            logged.append,
            "format-probe",
        )
        self.assertEqual(proc.terminated, 1)
        self.assertEqual(
            proc.communicate_calls,
            [download_module.REAP_AFTER_TERMINATE_SECONDS],
            "the reap must be bounded, not an unbounded wait",
        )
        self.assertEqual(logged, [])

    def test_a_kill_that_fails_still_reaps(self):
        import download as download_module

        proc = self.FakeProc()
        logged = []

        def failing_terminate(_target):
            raise OSError("access denied")

        download_module.reap_terminated_process(
            proc, failing_terminate, logged.append, "cookie import",
        )
        self.assertEqual(len(proc.communicate_calls), 1,
                         "a failed kill must not skip the wait")
        self.assertTrue(any("cookie import termination failed" in line for line in logged))

    def test_a_child_that_will_not_die_is_reported_not_awaited_forever(self):
        import download as download_module

        proc = self.FakeProc(raises=subprocess.TimeoutExpired("yt-dlp", 5))
        logged = []
        download_module.reap_terminated_process(
            proc, lambda _target: None, logged.append, "playlist-probe",
        )
        self.assertTrue(
            any("playlist-probe did not exit after termination" in line for line in logged)
        )

    def test_every_timeout_handler_routes_through_the_reaper(self):
        # The point of the helper is that no handler keeps the old shape.
        source = Path(ad.__file__).with_name("download.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = ast.unparse(node.type) if node.type else ""
            if "TimeoutExpired" not in caught:
                continue
            body = ast.unparse(ast.Module(body=node.body, type_ignores=[]))
            if "terminate_process_tree" in body and "reap_terminated_process" not in body:
                offenders.append(node.lineno)
        self.assertEqual(
            offenders, [],
            f"timeout handlers terminating without reaping: {offenders}",
        )


class NoArchiveLockTests(unittest.TestCase):
    """v1.3.0 removed the download-archive lock so re-downloads always
    run. These tests pin the invariants so the lock can't be silently
    re-introduced via a stray flag, config key, or yt-dlp argv branch.
    """

    def test_source_python_floor_matches_the_pinned_ytdlp(self):
        # A floor below the pin means pip fails at resolve time and the guard
        # written to explain the problem never gets to run.
        self.assertEqual(ad._MIN_PYTHON, (3, 11))
        requirements = (
            Path(ad.__file__).with_name("requirements.txt")
            .read_text(encoding="utf-8")
        )
        self.assertIn("Floor: Python 3.11", requirements)

    def test_default_config_has_no_download_archive_key(self):
        self.assertNotIn('DownloadArchive', ad.DEFAULT_CONFIG,
                         'DownloadArchive must not be a default config key.')

    def test_source_does_not_pass_download_archive_to_ytdlp(self):
        harness = AnySiteDownloadArgvTests()
        for url in (
            "https://example.com/video",
            "https://example.com/playlist/season-one",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ):
            with self.subTest(url=url):
                argv = harness._argv_for(url, with_cookies=False)
                self.assertNotIn(
                    "--download-archive", argv,
                    "yt-dlp argv must not reintroduce the archive lock",
                )


class VideoFormatSelectorTests(unittest.TestCase):
    """Codec-aware format selection — the previous selector picked the
    highest-bitrate stream regardless of codec, then ``--merge-output-format
    mp4`` only swapped containers, leaving VP9/AV1 inside .mp4. Adobe Premiere
    rejects that combination as "unsupported compression". These tests pin
    the codec preferences per container so the regression can't return
    silently.
    """

    def _selector(self, args):
        # args is the full list returned by build_video_format_args.
        # Layout is ['-f', '<selector>', '--merge-output-format', '<container>']
        self.assertEqual(args[0], '-f')
        self.assertEqual(args[2], '--merge-output-format')
        return args[1], args[3]

    def test_mp4_prefers_avc1_video_and_m4a_audio(self):
        sel, container = self._selector(ad.build_video_format_args('mp4', 'best'))
        self.assertEqual(container, 'mp4')
        # Premiere requires H.264 (avc1) inside MP4. The first cascade tier
        # MUST be avc1+m4a — anything else means the regression is back.
        self.assertTrue(
            sel.startswith('bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/'),
            f'mp4 selector must lead with avc1+m4a, got: {sel}',
        )
        # Must terminate at plain `best` so download never fails purely on codec.
        self.assertTrue(sel.endswith('/best'))

    def test_mp4_with_quality_cap_applies_to_every_tier(self):
        sel, _ = self._selector(ad.build_video_format_args('mp4', '1080'))
        # Every cascade tier should respect the height cap, not just the first.
        # If a tier omits the filter, a 4K stream could leak through when the
        # user explicitly asked for 1080p.
        for tier in sel.split('/'):
            if tier == 'best':
                continue
            self.assertIn('[height<=1080]', tier,
                          f'tier missing height cap: {tier!r}')

    def test_webm_prefers_vp9_and_opus(self):
        sel, container = self._selector(ad.build_video_format_args('webm', 'best'))
        self.assertEqual(container, 'webm')
        self.assertTrue(
            sel.startswith('bestvideo[vcodec^=vp9]+bestaudio[ext=webm]/'),
            f'webm selector must lead with vp9+webm-audio, got: {sel}',
        )

    def test_mkv_has_no_codec_preference(self):
        sel, container = self._selector(ad.build_video_format_args('mkv', 'best'))
        self.assertEqual(container, 'mkv')
        # MKV is a universal container — codec filters here would needlessly
        # constrain quality with no compatibility benefit.
        self.assertNotIn('vcodec', sel)
        self.assertNotIn('acodec', sel)
        self.assertNotIn('[ext=', sel)

    def test_no_unfiltered_height_when_quality_is_best(self):
        # Sanity: when quality is 'best', no height filter should appear,
        # otherwise the cascade silently caps at the previous default.
        sel, _ = ad.build_video_format_args('mp4', 'best')[1], 'mp4'
        self.assertNotIn('[height<=', sel)


class TerminalCounterConcurrencyTests(unittest.TestCase):
    def test_concurrent_completions_count_exactly(self):
        # total_completed was a bare `+= 1` executed on up to MAX_CONCURRENT
        # worker threads — a read-modify-write that loses counts under
        # contention. Hammer _record_terminal_download from many threads and
        # require an exact tally.
        with tempfile.TemporaryDirectory() as tmp:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmp}), FakeHistory())
            count = 48
            downloads = []
            for index in range(count):
                dl = ad.Download(f"dl_ctr_{index}", f"https://example.com/v{index}",
                                 output_dir=tmp)
                dl.status = "complete"
                dl.filename = f"v{index}.mp4"
                downloads.append(dl)
            start = threading.Barrier(8)

            def record(chunk):
                start.wait(timeout=10)
                for dl in chunk:
                    manager._record_terminal_download(dl)

            threads = [
                threading.Thread(target=record, args=(downloads[i::8],))
                for i in range(8)
            ]
            with mock.patch.object(ad, "write_persistent_log", return_value=None):
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)
            self.assertEqual(manager.total_completed, count)


class EndToEndDownloadTests(unittest.TestCase):
    """v1.5.1 / RESEARCH_FEATURE_PLAN EI14: end-to-end download flow with
    a faked yt-dlp subprocess.

    The 80 prior tests cover normalisation, security, rate-limiting, etc.
    but the full /download → spawn yt-dlp → parse progress → mark complete
    → write history flow was never exercised. A regression in the parsing
    loop (filename detection, progress regex, status transitions) would
    ship silently. This test exercises the whole flow with a fake
    subprocess.Popen — no real yt-dlp invocation — so it stays
    deterministic, sub-second, and hermetic.
    """

    def _make_fake_popen(self, lines, returncode=0):
        """Build a subprocess.Popen replacement that yields the given
        progress lines as if from yt-dlp stdout, then "exits" with
        returncode.
        """
        class FakeProc:
            def __init__(self, lines, rc):
                self._lines = list(lines)
                self.stdout = iter([line + "\n" for line in self._lines])
                self.returncode = rc
                self._waited = False

            def wait(self):
                self._waited = True
                return self.returncode

            def poll(self):
                return self.returncode if self._waited else None

            def terminate(self):
                # reason: cancel() path may call this; satisfy the API
                pass

            def kill(self):
                # reason: same as terminate
                pass

        def factory(args, **kwargs):
            return FakeProc(lines, returncode)
        return factory

    # 15 s, not 2: these wait on a worker thread, and the number has to be
    # large enough for a machine running the suite across every core. A tight
    # deadline turns "the box was busy" into a behaviour failure, and it
    # costs nothing when the thread finishes in milliseconds.
    WORKER_WAIT_SECONDS = 15.0

    def _wait_for_terminal(self, dl, timeout=WORKER_WAIT_SECONDS):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if dl.status in ad.DOWNLOAD_TERMINAL_STATES:
                return True
            time.sleep(0.01)
        return False

    def _wait_for_history(self, history, count=1, timeout=WORKER_WAIT_SECONDS):
        """Wait for the history write that follows a terminal status.

        `_run_download` sets the terminal status inside its `finally` and
        writes history after it, deliberately: joining the watchdog first
        would add latency between the two. So a status observer can arrive
        while history is still empty, and waiting on the status alone made
        this a one-in-five flake rather than an assertion about behaviour.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(history.entries) >= count:
                return True
            time.sleep(0.01)
        return False

    def test_cookieless_live_retry_reruns_the_download_without_cookies(self):
        # The cookie-less retry for "live event has ended" had zero coverage:
        # cookie stripping, the second yt-dlp invocation, and its progress
        # parsing were all unasserted, and its cloned parse loop had already
        # drifted from the original.
        attempts = []

        class FakeProc:
            def __init__(self, lines, rc):
                self.stdout = iter([line + "\n" for line in lines])
                self.returncode = rc
                self._waited = False

            def wait(self):
                self._waited = True
                return self.returncode

            def poll(self):
                return self.returncode if self._waited else None

            def terminate(self):
                pass

            def kill(self):
                pass

            def communicate(self, *_args, **_kwargs):
                self._waited = True
                return ('', '')

        def popen(args, **_kwargs):
            # yt-dlp/deno/node --version probes run through the same Popen;
            # only the real download invocations count as attempts.
            if '--ignore-config' not in args:
                return FakeProc([], 0)
            attempts.append(list(args))
            if len(attempts) == 1:
                return FakeProc([
                    'ERROR: HTTP Error 429: too many requests; this live event has ended.'
                ], 1)
            return FakeProc([
                'MDLP_JSON {"downloaded_bytes": 10, "total_bytes": 10}',
                '[Merger] Merging formats into "archived-stream.mp4"',
            ], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            cookie_jar = Path(tmpdir) / "cookies.txt"
            cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            download = ad.Download(
                "dl_live_retry",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"
            download.cookies_file = str(cookie_jar)
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(len(attempts), 2, "the ended-live failure must trigger exactly one retry")
        self.assertIn('--cookies', attempts[0], "the first attempt carries the cookie jar")
        self.assertNotIn('--cookies', attempts[1], "the retry must strip --cookies")
        self.assertNotIn(str(cookie_jar), attempts[1], "the retry must strip the jar path too")
        self.assertEqual(download.status, "complete")
        self.assertEqual(download.progress, 100)
        self.assertEqual(download.filename, "archived-stream.mp4",
                         "the retry must parse progress with the same parser as the first attempt")
        self.assertEqual(download.error, "")
        self.assertEqual(download.error_code, "")
        self.assertEqual(download.error_advice, "")
        self.assertEqual(download.error_action, "")
        self.assertEqual(manager._host_backoffs, {},
                         "a successful retry must not pause the host for the first attempt")

    def test_cookieless_retry_strips_cookies_for_tv_downgraded_unplayable(self):
        attempts = []

        class FakeProc:
            def __init__(self, lines, rc):
                self.stdout = iter([line + "\n" for line in lines])
                self.returncode = rc
                self._waited = False

            def wait(self):
                self._waited = True
                return self.returncode

            def poll(self):
                return self.returncode if self._waited else None

            def terminate(self):
                pass

            def kill(self):
                pass

            def communicate(self, *_args, **_kwargs):
                self._waited = True
                return ('', '')

        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return FakeProc([], 0)
            attempts.append(list(args))
            if len(attempts) == 1:
                return FakeProc([
                    'ERROR: [youtube] abc: Playability status UNPLAYABLE; tv_downgraded'
                ], 1)
            return FakeProc([
                'MDLP_JSON {"downloaded_bytes": 10, "total_bytes": 10}',
                '[download] Destination: public.mp4',
            ], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            cookie_jar = Path(tmpdir) / "cookies.txt"
            cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            download = ad.Download(
                "dl_cookie_retry",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"
            download.cookies_file = str(cookie_jar)
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(len(attempts), 2)
        self.assertIn('--cookies', attempts[0])
        self.assertNotIn('--cookies', attempts[1])
        self.assertEqual(download.status, "complete")
        self.assertEqual(download.error_code, "")

    def test_cookieless_retry_with_no_output_is_skipped(self):
        attempts = []

        class FakeProc:
            def __init__(self, lines, rc):
                self.stdout = iter([line + "\n" for line in lines])
                self.returncode = rc
                self._waited = False

            def wait(self):
                self._waited = True
                return self.returncode

            def poll(self):
                return self.returncode if self._waited else None

            def terminate(self):
                return None

            def kill(self):
                return None

            def communicate(self, *_args, **_kwargs):
                self._waited = True
                return ('', '')

        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return FakeProc([], 0)
            attempts.append(list(args))
            if len(attempts) == 1:
                return FakeProc(['ERROR: This live event has ended.'], 1)
            return FakeProc([], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            cookie_jar = Path(tmpdir) / "cookies.txt"
            cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            download = ad.Download(
                "dl_live_retry_empty",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"
            download.cookies_file = str(cookie_jar)
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(len(attempts), 2)
        self.assertEqual(download.status, "skipped")
        self.assertEqual(download.progress, 0)
        self.assertIn("Nothing was downloaded", download.error)
        self.assertEqual(download.error_code, "")

    def test_cancel_during_cookieless_retry_spawn_terminates_retry_process(self):
        attempts = []
        retry_processes = []

        class FakeProc:
            def __init__(self, lines, rc):
                self.stdout = iter([line + "\n" for line in lines])
                self.returncode = rc
                self._waited = False

            def wait(self):
                self._waited = True
                return self.returncode

            def poll(self):
                return self.returncode if self._waited else None

            def communicate(self, *_args, **_kwargs):
                self._waited = True
                return ('', '')

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            cookie_jar = Path(tmpdir) / "cookies.txt"
            cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            download = ad.Download(
                "dl_cancel_retry",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"
            download.cookies_file = str(cookie_jar)

            def popen(args, **_kwargs):
                if '--ignore-config' not in args:
                    return FakeProc([], 0)
                attempts.append(list(args))
                if len(attempts) == 1:
                    return FakeProc(['ERROR: This live event has ended.'], 1)
                download.status = 'cancelled'
                retry_process = FakeProc([], 1)
                retry_processes.append(retry_process)
                return retry_process

            terminated = []
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None), \
                 mock.patch.object(ad, 'terminate_process_tree', side_effect=terminated.append):
                manager._run_download(download)

        self.assertEqual(len(attempts), 2)
        self.assertEqual(terminated, retry_processes,
                         "a retry spawned after cancellation must be terminated immediately")
        self.assertEqual(download.status, 'cancelled')

    def test_stall_watchdog_terminates_a_hung_download_and_classifies_it(self):
        import importlib

        download_module = importlib.import_module("download")
        terminated = []
        stopped = threading.Event()

        class FakeProc:
            def __init__(self):
                self.returncode = None
                self.stdout = self.BlockingStdout(self, stopped)

            class BlockingStdout:
                def __init__(self, proc, stop_event):
                    self.proc = proc
                    self.stop_event = stop_event

                def __iter__(self):
                    return self

                def __next__(self):
                    if not self.stop_event.wait(15):
                        # A missing watchdog must not make this test hang
                        # forever; it will still fail the outcome assertions.
                        self.proc.returncode = 1
                    raise StopIteration

                def close(self):
                    return None

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode or 1

        process = FakeProc()

        def terminate(proc):
            terminated.append(proc)
            stopped.set()
            proc.returncode = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            manager._dependencies["spawn_ytdlp"] = lambda *_args, **_kwargs: process
            manager._dependencies["terminate_process_tree"] = terminate
            manager._dependencies["probe_po_token_provider"] = lambda: None
            manager._dependencies["probe_javascript_runtime"] = lambda **_kwargs: {}
            manager._dependencies["build_javascript_runtime_args"] = lambda *_args, **_kwargs: []
            manager._dependencies["build_youtube_extractor_args"] = lambda *_args, **_kwargs: []
            download = ad.Download(
                "dl_stall_watchdog",
                "https://example.com/video",
                output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(download_module, "DOWNLOAD_STALL_TIMEOUT_SECONDS", 0), \
                 mock.patch.object(download_module, "DOWNLOAD_WATCHDOG_POLL_SECONDS", 0.01):
                manager._run_download(download)

        self.assertEqual(terminated, [process])
        self.assertEqual(download.status, "failed")
        self.assertIn("Download stalled", download.error)
        self.assertEqual(download.error_code, "network-unreachable")

    def test_live_wait_watchdog_bounds_a_never_started_event(self):
        import importlib

        download_module = importlib.import_module("download")
        terminated = []
        stopped = threading.Event()
        spawned_args = []

        class FakeProc:
            def __init__(self):
                self.returncode = None
                self.stdout = self.BlockingStdout(self, stopped)

            class BlockingStdout:
                def __init__(self, proc, stop_event):
                    self.proc = proc
                    self.stop_event = stop_event
                    self.wait_line_emitted = False

                def __iter__(self):
                    return self

                def __next__(self):
                    if not self.wait_line_emitted:
                        self.wait_line_emitted = True
                        return "[wait] Waiting for the live event to begin...\n"
                    if not self.stop_event.wait(15):
                        # A missing overall live-wait deadline must not make
                        # this regression test hang indefinitely.
                        self.proc.returncode = 1
                    raise StopIteration

                def close(self):
                    return None

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode or 1

        process = FakeProc()

        def spawn(args, **_kwargs):
            spawned_args.append(list(args))
            return process

        def terminate(proc):
            terminated.append(proc)
            stopped.set()
            proc.returncode = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({
                    "DownloadPath": tmpdir,
                    "AudioDownloadPath": tmpdir,
                    "WaitForVideoSeconds": 45,
                }),
                FakeHistory(),
            )
            manager._dependencies["spawn_ytdlp"] = spawn
            manager._dependencies["terminate_process_tree"] = terminate
            manager._dependencies["probe_po_token_provider"] = lambda: None
            manager._dependencies["probe_javascript_runtime"] = lambda **_kwargs: {}
            manager._dependencies["build_javascript_runtime_args"] = lambda *_args, **_kwargs: []
            manager._dependencies["build_youtube_extractor_args"] = lambda *_args, **_kwargs: []
            download = ad.Download(
                "dl_live_wait_watchdog",
                "https://example.com/scheduled-live",
                output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(download_module, "DOWNLOAD_LIVE_WAIT_MAX_SECONDS", 0), \
                 mock.patch.object(download_module, "DOWNLOAD_WATCHDOG_POLL_SECONDS", 0.01):
                manager._run_download(download)

        self.assertEqual(terminated, [process])
        self.assertIn("--wait-for-video", spawned_args[0])
        self.assertEqual(spawned_args[0][spawned_args[0].index("--wait-for-video") + 1], "45")
        self.assertEqual(download.status, "failed")
        self.assertIn("Live video did not start", download.error)
        self.assertEqual(download.error_code, "live-wait-timeout")

    def test_retry_watchdog_terminates_the_retried_hung_download(self):
        import importlib

        download_module = importlib.import_module("download")
        terminated = []

        class CompletedProc:
            def __init__(self):
                self.returncode = 1
                self.stdout = iter(["ERROR: This live event has ended.\n"])

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

            def terminate(self):
                return None

            def kill(self):
                return None

            def close_stdout(self):
                return None

        class HangingProc:
            def __init__(self):
                self.returncode = None
                self.stop_event = threading.Event()
                self.stdout = self.BlockingStdout(self, self.stop_event)

            class BlockingStdout:
                def __init__(self, proc, stop_event):
                    self.proc = proc
                    self.stop_event = stop_event

                def __iter__(self):
                    return self

                def __next__(self):
                    # Generous, because this waits for the watchdog THREAD to
                    # be scheduled. A one-second deadline made a busy machine
                    # look like a watchdog that never fired.
                    if not self.stop_event.wait(15):
                        self.proc.returncode = 1
                    raise StopIteration

                def close(self):
                    return None

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode or 1

        first = CompletedProc()
        retry = HangingProc()
        processes = iter((first, retry))

        def spawn(*_args, **_kwargs):
            return next(processes)

        def terminate(proc):
            terminated.append(proc)
            if hasattr(proc, "stop_event"):
                proc.stop_event.set()
            proc.returncode = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "WaitForVideoSeconds": 45,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            manager._dependencies["spawn_ytdlp"] = spawn
            manager._dependencies["terminate_process_tree"] = terminate
            manager._dependencies["probe_po_token_provider"] = lambda: None
            manager._dependencies["probe_javascript_runtime"] = lambda **_kwargs: {}
            manager._dependencies["build_javascript_runtime_args"] = lambda *_args, **_kwargs: []
            manager._dependencies["build_youtube_extractor_args"] = lambda *_args, **_kwargs: []
            cookie_jar = Path(tmpdir) / "cookies.txt"
            cookie_jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            download = ad.Download(
                "dl_retry_watchdog",
                "https://www.youtube.com/watch?v=retry-watchdog",
                output_dir=tmpdir,
            )
            download.status = "queued"
            download.cookies_file = str(cookie_jar)
            with mock.patch.object(download_module, "DOWNLOAD_LIVE_WAIT_MAX_SECONDS", 0), \
                 mock.patch.object(download_module, "DOWNLOAD_STALL_TIMEOUT_SECONDS", 60), \
                 mock.patch.object(download_module, "DOWNLOAD_WATCHDOG_POLL_SECONDS", 0.01):
                manager._run_download(download)

        # The retry has to be terminated, and nothing outside these two
        # processes may be. Not `== [retry]`: the live-wait maximum is patched
        # to zero, so the first attempt's own watchdog can legitimately fire
        # before that attempt finishes, and on a loaded machine it does. That
        # is the patched constant working, not a wrong process being killed.
        self.assertIn(retry, terminated)
        self.assertEqual(terminated[-1], retry)
        self.assertTrue(set(terminated) <= {first, retry}, terminated)
        self.assertEqual(download.status, "failed")
        self.assertIn("Live video did not start", download.error)
        self.assertEqual(download.error_code, "live-wait-timeout")

    def test_shared_output_parser_never_resurrects_a_cancelled_download(self):
        # The retry's cloned loop lacked the original's cancelled guard, so a
        # late "[Merger]" line flipped a cancelled item back to "merging" while
        # the process was still draining. One shared parser keeps the guard.
        class FakeProc:
            def __init__(self, lines):
                self.stdout = iter([line + "\n" for line in lines])

        config = FakeConfig({})
        manager = ad.DownloadManager(config, FakeHistory())
        download = ad.Download(
            "dl_cancel_guard",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        download.status = "cancelled"
        activity = {'at': time.monotonic()}
        last_lines, last_error = manager._consume_ytdlp_output(
            download,
            FakeProc([
                '[Merger] Merging formats into "late.mp4"',
                '[ExtractAudio] Destination: late.m4a',
            ]),
            activity,
        )

        self.assertEqual(download.status, "cancelled",
                         "output lines must never revive a cancelled download")
        self.assertEqual(download.filename, "late.mp4",
                         "filename detection still runs so the file can be cleaned up")
        self.assertEqual(len(last_lines), 2)
        self.assertIsNone(last_error)

    def test_full_download_flow_marks_complete_and_writes_history(self):
        # Fake yt-dlp output: structured progress lines that the parsing
        # loop knows how to decode + a Merger line (sets filename) + a
        # final "100%" line. The real flow then waits on the process
        # and stamps "complete".
        token = "i" * 32
        fake_lines = [
            'MDLP_JSON {"downloaded_bytes": 5000, "total_bytes": 10000, "_speed_str": "1.2MiB/s", "_eta_str": "00:01"}',
            'MDLP_JSON {"downloaded_bytes": 10000, "total_bytes": 10000, "_speed_str": "1.2MiB/s", "_eta_str": "00:00"}',
            '[Merger] Merging formats into "fake-video.mp4"',
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "ServerToken": token,
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            history = FakeHistory()
            manager = ad.DownloadManager(config, history)

            popen_factory = self._make_fake_popen(fake_lines, returncode=0)
            with mock.patch.object(ad.subprocess, 'Popen', popen_factory), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                dl_id, err = manager.start_download(
                    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    audio_only=False,
                    fmt="mp4",
                    quality="best",
                )
                self.assertIsNone(err, f"start_download must succeed: {err}")
                self.assertIsNotNone(dl_id)
                dl = manager.downloads[dl_id]
                self.assertTrue(self._wait_for_terminal(dl),
                    f"download must reach a terminal state within timeout; status={dl.status}")
                self.assertTrue(self._wait_for_history(history),
                    "history write must follow the terminal status")

            self.assertEqual(dl.status, "complete",
                f"download must terminate as complete; got {dl.status} (error={dl.error})")
            self.assertEqual(dl.progress, 100, "complete download must have progress=100")
            self.assertEqual(dl.filename, "fake-video.mp4",
                "Merger line must be parsed into dl.filename")
            self.assertEqual(len(history.entries), 1,
                "completed download must write exactly one history entry")
            entry = history.entries[0]
            self.assertEqual(entry["id"], dl_id)
            self.assertEqual(entry["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertEqual(entry["filename"], "fake-video.mp4")
            self.assertEqual(entry["format"], "mp4")
            self.assertFalse(entry["audioOnly"])
            self.assertEqual(entry["status"], "complete")
            self.assertEqual(entry["errorCode"], "")
            self.assertEqual(entry["error"], "")

    def test_accurate_section_recut_reencodes_then_atomically_replaces_source(self):
        captured = []

        class FakeFfmpeg:
            returncode = 0
            stdout = None

            def __init__(self, args):
                self.args = list(args)

            def communicate(self):
                Path(self.args[-1]).write_bytes(b"trimmed-media")
                return "", None

            def poll(self):
                return self.returncode

        def spawn(args, **_kwargs):
            captured.append(list(args))
            return FakeFfmpeg(args)

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.mp4"
            source.write_bytes(b"full-media")
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            download = ad.Download(
                "dl_section",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
                fmt="mp4",
                section={"start": 62.5, "end": 65.0},
            )
            download.filename = str(source)

            with mock.patch.object(ad, "FFMPEG_PATH", Path(tmpdir) / "ffmpeg.exe"), \
                 mock.patch.object(ad, "spawn_media_process", side_effect=spawn):
                self.assertTrue(manager._recut_section(download, {}))

            self.assertEqual(source.read_bytes(), b"trimmed-media")
            args = captured[0]
            self.assertLess(args.index("-i"), args.index("-ss"))
            self.assertEqual(args[args.index("-ss") + 1], "62.500")
            self.assertEqual(args[args.index("-t") + 1], "2.500")
            self.assertIn("libx264", args)
            self.assertNotIn("--download-sections", args)

    def test_saved_config_cannot_inject_link_file_flags_into_spawn(self):
        captured_args = []
        # A real successful yt-dlp run always announces its destination; an
        # empty stdout now classifies as 'skipped' (nothing was written).
        base_factory = self._make_fake_popen(
            ['[download] Destination: clip.mp4'], returncode=0
        )

        def capture(args, **kwargs):
            captured_args.append(list(args))
            return base_factory(args, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "ytDlpArgs": list(ad.YTDLP_FORBIDDEN_LINK_FLAGS),
                "extraArgs": ["--write-link"],
                "writeLink": True,
                "--write-desktop-link": True,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_link_policy",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"  # the state _schedule() hands to the worker
            with mock.patch.object(ad.subprocess, 'Popen', capture), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'probe_javascript_runtime', return_value={
                     'runtime': 'deno', 'path': 'C:/Tools/deno.exe',
                     'supported': True, 'ejsReady': True,
                 }), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "complete")
        downloads = ytdlp_invocations(captured_args)
        self.assertEqual(len(downloads), 1)
        argv = downloads[0]
        options = {
            arg.split('=', 1)[0].casefold()
            for arg in argv[1:]
            if isinstance(arg, str) and arg.startswith('--')
        }
        self.assertTrue(options.isdisjoint(ad.YTDLP_FORBIDDEN_LINK_FLAGS))
        self.assertFalse(any(
            "aria2" in str(argument).casefold() for argument in argv
        ))
        self.assertIn('--no-js-runtimes', argv)
        self.assertIn('deno:C:/Tools/deno.exe', argv)

    def test_playlist_subset_is_the_only_playlist_selection_passed_to_ytdlp(self):
        captured_args = []
        # A real successful yt-dlp run always announces its destination; an
        # empty stdout now classifies as 'skipped' (nothing was written).
        base_factory = self._make_fake_popen(
            ['[download] Destination: clip.mp4'], returncode=0
        )

        def capture(args, **kwargs):
            captured_args.append(list(args))
            return base_factory(args, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            download = ad.Download(
                "dl_playlist_subset",
                "https://www.youtube.com/playlist?list=PLfixture",
                output_dir=tmpdir,
                playlist_items=[1, 3, 5],
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", capture), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "complete")
        args = ytdlp_invocations(captured_args)[0]
        self.assertIn("--yes-playlist", args)
        self.assertEqual(args[args.index("--playlist-items") + 1], "1,3,5")
        self.assertNotIn("--playlist-start", args)
        self.assertNotIn("--playlist-end", args)

    def _capture_download_argv(self, download):
        captured_args = []
        base_factory = self._make_fake_popen(
            ['[download] Destination: clip.mp4'], returncode=0
        )

        def capture(args, **kwargs):
            captured_args.append(list(args))
            return base_factory(args, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            download.output_dir = tmpdir
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", capture), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
        # Version and capability probes share this Popen and are cached
        # module-wide, so how many of them run depends on test order. The
        # download itself is the only invocation carrying the URL.
        runs = [args for args in captured_args if download.url in args]
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_fresh_download_still_overwrites_an_existing_output_file(self):
        # The v1.3.0 behaviour: re-downloading the same URL must not stop at
        # "has already been downloaded".
        download = ad.Download("dl_fresh", "https://example.com/video")
        self.assertIn("--force-overwrites", self._capture_download_argv(download))

    def test_resumed_download_keeps_its_partial_file(self):
        # --force-overwrites includes --no-continue, so sending it on a resume
        # throws away the `.part` file and re-fetches from byte zero.
        download = ad.Download("dl_resume", "https://example.com/video")
        download.resume_partial = True
        self.assertNotIn("--force-overwrites", self._capture_download_argv(download))

    def test_retry_and_resume_mark_the_download_as_continuing(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())

        retried = ad.Download("dl_retry", "https://example.com/video")
        retried.status = 'failed'
        retried.error_code = sorted(ad.DOWNLOAD_RETRYABLE_ERROR_CODES)[0]
        manager.downloads[retried.id] = retried
        self.assertFalse(retried.resume_partial)
        ok, err = manager.retry(retried.id)
        self.assertTrue(ok, err)
        self.assertTrue(retried.resume_partial)

        paused = ad.Download("dl_paused", "https://example.com/video")
        paused.status = 'paused'
        manager.downloads[paused.id] = paused
        self.assertFalse(paused.resume_partial)
        ok, err = manager.resume_download(paused.id)
        self.assertTrue(ok, err)
        self.assertTrue(paused.resume_partial)

    def test_completed_download_reports_a_failed_history_write(self):
        # The download really did finish and the file really is on disk, so
        # there is no failure to raise — which is why this used to vanish.
        class RefusingHistory(FakeHistory):
            def add(self, entry):
                return False

        download = ad.Download("dl_history_fail", "https://example.com/video")
        captured_args = []
        base_factory = self._make_fake_popen(
            ['[download] Destination: clip.mp4'], returncode=0
        )

        def capture(args, **kwargs):
            captured_args.append(list(args))
            return base_factory(args, **kwargs)

        logged = []
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                RefusingHistory(),
            )
            download.output_dir = tmpdir
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", capture), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", side_effect=logged.append):
                manager._run_download(download)

            self.assertEqual(download.status, "complete",
                             "a history write failure must not fail the download")
            notice = manager.persistence_notice()
            self.assertIn("History", notice)
            self.assertEqual(manager.queue_payload()["historyError"], notice)
            self.assertTrue(
                any("history entry could not be saved" in line for line in logged),
                logged,
            )

    def test_successful_history_write_leaves_no_notice(self):
        download = ad.Download("dl_history_ok", "https://example.com/video")
        base_factory = self._make_fake_popen(
            ['[download] Destination: clip.mp4'], returncode=0
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            download.output_dir = tmpdir
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", base_factory), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
            self.assertEqual(download.status, "complete")
            self.assertEqual(manager.persistence_notice(), "")
            self.assertIsNone(manager.queue_payload()["historyError"])

    def test_playlist_subset_rejects_video_urls_and_clip_combinations(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        download_id, err = manager.start_download(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            playlist_items=[1],
        )
        self.assertIsNone(download_id)
        self.assertIn("playlist URL", err)

        download_id, err = manager.start_download(
            "https://www.youtube.com/playlist?list=PLfixture",
            playlist_items=[1],
            section={"start": 1, "end": 2},
        )
        self.assertIsNone(download_id)
        self.assertIn("single-video", err)

    def test_completed_download_closes_subprocess_stdout(self):
        token = "z" * 32
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "ServerToken": token,
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            dl = ad.Download(
                "dl_stdout_cleanup",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            dl.status = "queued"  # the state _schedule() hands to the worker

            class FakeProc:
                def __init__(self):
                    self.stdout = io.StringIO(
                        'MDLP_JSON {"downloaded_bytes": 1, "total_bytes": 1}\n'
                        '[download] Destination: clip.mp4\n'
                    )
                    self.returncode = 0

                def wait(self):
                    return self.returncode

                def poll(self):
                    return self.returncode

            fake_proc = FakeProc()
            with mock.patch.object(ad.subprocess, 'Popen', return_value=fake_proc), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(dl)

            self.assertEqual(dl.status, "complete")
            self.assertTrue(fake_proc.stdout.closed,
                "download teardown must close the PIPE-backed stdout stream")
            self.assertIsNone(dl.process)

    def test_yt_dlp_nonzero_exit_with_error_marks_failed(self):
        # When the subprocess exits non-zero and progress never reached
        # 99 %, the download must transition to "failed" with the error
        # text taken from the last ERROR line (truncated to 240 chars
        # per the audit-pass fix).
        token = "j" * 32
        fake_lines = [
            'MDLP_JSON {"downloaded_bytes": 100, "total_bytes": 10000, "_speed_str": "10KiB/s", "_eta_str": "01:00"}',
            'ERROR: Sign in to confirm your age',
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "ServerToken": token,
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            history = FakeHistory()
            manager = ad.DownloadManager(config, history)
            popen_factory = self._make_fake_popen(fake_lines, returncode=1)
            with mock.patch.object(ad.subprocess, 'Popen', popen_factory), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                dl_id, err = manager.start_download(
                    url="https://www.youtube.com/watch?v=ageGated",
                )
                self.assertIsNone(err)
                dl = manager.downloads[dl_id]
                self.assertTrue(self._wait_for_terminal(dl))

            self.assertEqual(dl.status, "failed",
                f"non-zero exit with low progress must fail; got {dl.status}")
            self.assertIn("Sign in to confirm", dl.error or "",
                "error must surface the yt-dlp ERROR text")
            self.assertEqual(dl.error_code, "sign-in-required",
                "sign-in failures must expose a stable recovery code")
            self.assertEqual(dl.to_dict().get("next_action"), "sign-in-and-retry",
                "status payload must expose the matching recovery action")
            self.assertTrue(self._wait_for_history(history),
                "failed downloads must remain visible in History")
            self.assertEqual(len(history.entries), 1)
            self.assertEqual(history.entries[0]["status"], "failed")
            self.assertEqual(history.entries[0]["errorCode"], "sign-in-required")
            self.assertIn("Sign in to confirm", history.entries[0]["error"])

    def test_yt_dlp_nonzero_exit_after_full_progress_still_marks_failed(self):
        token = "p" * 32
        fake_lines = [
            'MDLP_JSON {"downloaded_bytes": 10000, "total_bytes": 10000, "_speed_str": "1.2MiB/s", "_eta_str": "00:00"}',
            'ERROR: Postprocessing: ffmpeg exited with code 1',
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "ServerToken": token,
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            history = FakeHistory()
            manager = ad.DownloadManager(config, history)
            popen_factory = self._make_fake_popen(fake_lines, returncode=1)
            with mock.patch.object(ad.subprocess, 'Popen', popen_factory), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                dl_id, err = manager.start_download(
                    url="https://www.youtube.com/watch?v=postProcessFail",
                )
                self.assertIsNone(err)
                dl = manager.downloads[dl_id]
                self.assertTrue(self._wait_for_terminal(dl))
                self.assertTrue(self._wait_for_history(history))

        self.assertEqual(dl.status, "failed",
            f"non-zero exit after full progress must fail; got {dl.status}")
        self.assertEqual(dl.progress, 100,
            "the parsed progress can remain complete, but status must not")
        self.assertEqual(dl.error_code, "ffmpeg-missing-or-stale",
            "late ffmpeg failures must expose the recovery code")
        self.assertEqual(dl.to_dict().get("next_action"), "refresh-ffmpeg",
            "status payload must expose the matching recovery action")
        self.assertEqual(len(history.entries), 1,
            "failed postprocessor exits must remain visible in History")
        self.assertEqual(history.entries[0]["status"], "failed")
        self.assertEqual(history.entries[0]["errorCode"], "ffmpeg-missing-or-stale")
        self.assertIn("ffmpeg", history.entries[0]["error"].lower())

    def test_parse_loop_crash_terminates_orphan_and_purges_cookie_jar(self):
        """Audit fix: an unexpected exception inside the output-parsing loop
        must not orphan the still-running yt-dlp tree. The finally has to
        kill the process tree BEFORE unlinking the cookie jar, so the orphan
        never outlives (or holds open) the credential file."""
        token = "k" * 32

        class ExplodingStdout:
            def __iter__(self):
                return self

            def __next__(self):
                raise OSError("boom: stdout read failed mid-stream")

        class FakeProc:
            def __init__(self):
                self.stdout = ExplodingStdout()
                self.returncode = None

            def poll(self):
                # Still running — this is the orphan scenario.
                return None

            def wait(self, timeout=None):
                return None

            def terminate(self):
                pass

            def kill(self):
                pass

        fake_proc = FakeProc()
        cookies = [{
            "domain": ".youtube.com", "name": "SID", "value": "abc",
            "path": "/", "secure": True, "httpOnly": True,
            "expirationDate": 1700000000,
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "ServerToken": token,
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            history = FakeHistory()
            with mock.patch.object(ad, 'INSTALL_DIR', Path(tmpdir)):
                manager = ad.DownloadManager(config, history)
                with mock.patch.object(ad, 'spawn_ytdlp', return_value=fake_proc), \
                     mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                     mock.patch.object(ad, 'probe_javascript_runtime', return_value={}), \
                     mock.patch.object(ad, 'write_persistent_log', return_value=None), \
                     mock.patch.object(ad, 'terminate_process_tree') as terminate:
                    dl_id, err = manager.start_download(
                        url="https://www.youtube.com/watch?v=crashCase",
                        cookies=cookies,
                    )
                    self.assertIsNone(err)
                    dl = manager.downloads[dl_id]
                    # Wait for the finally to finish (status flips to failed in
                    # the except, BEFORE the finally runs — so poll on the
                    # jar/process fields, not just the terminal status).
                    deadline = time.time() + self.WORKER_WAIT_SECONDS
                    while time.time() < deadline:
                        if dl.cookies_file is None and dl.process is None:
                            break
                        time.sleep(0.01)
                    # History is written after the finally clears those two,
                    # so waiting on them alone still reads an empty history.
                    self.assertTrue(self._wait_for_history(history))

                    self.assertEqual(dl.status, "failed")
                    terminate.assert_called_once_with(fake_proc)
                    self.assertIsNone(dl.process,
                        "finally must null dl.process after the kill")
                    self.assertIsNone(dl.cookies_file,
                        "cookie jar reference must be cleared")
                    leftovers = list(Path(tmpdir).glob(".cookies.*.txt"))
                    self.assertEqual(leftovers, [],
                        "cookie jar file must be unlinked after the orphan is killed")
                    self.assertEqual(len(history.entries), 1)
                    self.assertEqual(history.entries[0]["status"], "failed")
                    self.assertIn("Unexpected download error", history.entries[0]["error"])


class Aria2cExternalDownloaderBanTests(unittest.TestCase):
    """CVE-2026-50574: yt-dlp removed aria2c HLS/DASH support because
    aria2c manifest downloads allowed arbitrary code execution.  Verify
    the companion never passes --external-downloader aria2c."""

    def test_external_downloader_is_refused_at_the_process_boundary(self):
        for option in ('--external-downloader', '--downloader', '--downloader-args'):
            with self.subTest(option=option), \
                 mock.patch.object(ad.subprocess, 'Popen') as popen:
                with self.assertRaises(ValueError):
                    ad.spawn_ytdlp([
                        'yt-dlp.exe', option, 'aria2c', 'https://example.test',
                    ])
                popen.assert_not_called()


class DownloadSizeCeilingTests(unittest.TestCase):
    """Audit fix: download_file_atomic must enforce a byte ceiling while
    streaming so a misbehaving CDN can't fill the disk before the SHA-256
    check ever runs."""

    class _FakeResponse:
        def __init__(self, chunks, headers=None):
            self._chunks = list(chunks)
            self.headers = headers or {}

        def raise_for_status(self):
            pass

        def iter_content(self, _chunk_size):
            return iter(self._chunks)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_default_ceiling_constant_is_500_mb(self):
        self.assertEqual(ad.HELPER_DOWNLOAD_MAX_BYTES, 500 * 1024 * 1024)

    def test_rejects_oversized_content_length_before_streaming(self):
        resp = self._FakeResponse([b"x" * 4], headers={"content-length": "1000"})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.bin"
            with mock.patch.object(ad, 'first_party_http_get', return_value=resp):
                with self.assertRaises(RuntimeError):
                    ad.download_file_atomic(
                        "https://example.invalid/asset", target, max_bytes=10,
                    )
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [],
                "no partial temp file may remain after the abort")

    def test_aborts_and_cleans_partial_when_stream_exceeds_limit(self):
        # No content-length header — the server lies by omission, so the
        # streamed byte count itself must trip the ceiling mid-download.
        resp = self._FakeResponse([b"x" * 8, b"y" * 8])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.bin"
            with mock.patch.object(ad, 'first_party_http_get', return_value=resp):
                with self.assertRaises(RuntimeError):
                    ad.download_file_atomic(
                        "https://example.invalid/asset", target, max_bytes=10,
                    )
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [],
                "partial download must be cleaned up on ceiling breach")

    def test_download_within_limit_still_succeeds(self):
        resp = self._FakeResponse([b"hello", b"world"],
                                  headers={"content-length": "10"})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "asset.bin"
            with mock.patch.object(ad, 'first_party_http_get', return_value=resp):
                ad.download_file_atomic(
                    "https://example.invalid/asset", target, max_bytes=10,
                )
            self.assertEqual(target.read_bytes(), b"helloworld")

    def test_stream_copy_stops_at_limit_without_buffering_remainder(self):
        source = io.BytesIO(b"0123456789")
        destination = io.BytesIO()
        with self.assertRaises(RuntimeError):
            ad.copy_stream_limited(source, destination, max_bytes=5, chunk_size=1024)
        self.assertLessEqual(len(destination.getvalue()), 5)


class ResponseSizeCapTests(unittest.TestCase):
    """v1.5.1 / RESEARCH_FEATURE_PLAN EI12: bounded HTTP surface.

    Both sides of the wire must be capped so the Flask process can't be
    OOM'd by an oversized payload:

      • incoming: MAX_REQUEST_BYTES = 1 MB, enforced by Flask itself via
        app.config['MAX_CONTENT_LENGTH']
      • outgoing: MAX_RESPONSE_BYTES = 10 MB, enforced by cors_response
        replacing oversized payloads with a 413 error body before the
        wire layer transmits anything
    """

    def test_constants_declared_with_expected_values(self):
        # The values themselves are policy — assert the documented
        # numbers so a silent drift to 1 GB doesn't sneak through.
        self.assertEqual(ad.MAX_REQUEST_BYTES, 1 * 1024 * 1024)
        self.assertEqual(ad.MAX_RESPONSE_BYTES, 10 * 1024 * 1024)

    def test_request_size_cap_wired_into_flask(self):
        # Flask's MAX_CONTENT_LENGTH gates the body BEFORE the route
        # handler sees it, so an oversized POST gets a generic 413
        # without exercising our auth / validation logic. Assert
        # create_api wires the cap into app.config.
        token = "f" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        self.assertEqual(api.config['MAX_CONTENT_LENGTH'], ad.MAX_REQUEST_BYTES,
            "create_api must seed MAX_CONTENT_LENGTH so Flask itself caps incoming bodies")

    def test_request_body_exceeding_cap_returns_413(self):
        # End-to-end: send a body > MAX_REQUEST_BYTES against /download
        # and verify Flask emits 413 before our handler runs. The body
        # is just oversized JSON; the auth + validation logic in the
        # /download handler is never reached.
        token = "g" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        oversized = "x" * (ad.MAX_REQUEST_BYTES + 1024)
        with mock.patch.object(ad, "write_persistent_log") as log:
            resp = api.test_client().post(
                "/download",
                data=oversized,
                headers={
                    "X-Auth-Token": token,
                    "Content-Type": "application/json",
                    "Host": "127.0.0.1:9751",
                },
            )
        self.assertEqual(resp.status_code, 413,
            "POST body > MAX_REQUEST_BYTES must return 413 (RequestEntityTooLarge)")
        self.assertEqual(resp.get_json()["code"], "request-too-large")
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(log.called)

    def test_unhandled_route_exception_is_json_logged_and_security_headered(self):
        token = "h" * 32
        config = FakeConfig({"ServerToken": token})
        api = ad.create_api(config, ad.DownloadManager(config, FakeHistory()), FakeHistory())

        def fail_for_test():
            raise RuntimeError("fixture route exploded")

        api.add_url_rule("/test-unhandled", view_func=fail_for_test)
        with mock.patch.object(ad, "write_persistent_log") as log:
            response = api.test_client().get(
                "/test-unhandled", headers={"Host": "127.0.0.1"}
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["code"], "internal-server-error")
        self.assertIn("could not complete", response.get_json()["error"].lower())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("fixture route exploded", log.call_args.args[0])

    def test_cors_response_has_outgoing_size_guard(self):
        # Force a small policy limit and return a deliberately oversized
        # history payload. The public route must replace it with the bounded
        # 413 response before it reaches the client.
        token = "i" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad, "MAX_RESPONSE_BYTES", 64), \
                mock.patch.object(
                    ad,
                    "query_history_entries",
                    return_value={"history": ["x" * 256]},
                ):
            api = ad.create_api(config, manager, FakeHistory())
        response = api.test_client().get(
            "/history?limit=1",
            headers={
                "X-Auth-Token": token,
                "Host": "127.0.0.1:9751",
            },
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn("byte limit", response.get_json()["error"])


class DownloadWorkerRaceGuardTests(unittest.TestCase):
    """Race guards between cancel()/worker teardown and (re)scheduling.

    cancel() can land between _schedule() releasing the manager lock and the
    worker thread's first statement, and retry()/resume_download() can land in
    the millisecond gap where a worker has stamped a terminal status but its
    finally block has not yet discarded the id from _running_ids. Both windows
    previously revived or double-scheduled downloads.
    """

    def _manager(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        manager.pause_intake()  # keep _schedule() from starting real workers
        return manager

    def _reserved_download(self, manager, url="https://www.youtube.com/watch?v=raceguard1"):
        """A download in the post-_schedule() state: queued + slot reserved."""
        dl_id, err = manager.start_download(url)
        self.assertIsNone(err)
        dl = manager.downloads[dl_id]
        with manager._lock:
            dl.status = 'queued'
            manager._running_ids.add(dl_id)
        return dl

    def test_start_download_does_not_race_the_ytdlp_updater(self):
        # Regression: the v1.5.4 'download-initiated' trigger fired BEFORE the
        # download was enqueued, so the updater passed its active_count()==0
        # idle gate and its binary swap raced the yt-dlp.exe this download
        # spawned milliseconds later (file-in-use failure + a wasted full
        # re-download of the release). Initiation must not trigger the
        # updater; the queue-idle hook in _worker_entry covers staleness.
        manager = self._manager()
        calls = []
        manager._dependencies['maybe_auto_update_ytdlp'] = (
            lambda config, active_count_fn: calls.append((config, active_count_fn))
        )
        dl_id, err = manager.start_download("https://www.youtube.com/watch?v=autoupd001")
        self.assertIsNone(err)
        self.assertEqual(calls, [], "initiation must not open the update window while the download is about to spawn")

    def test_worker_entry_triggers_ytdlp_update_at_queue_idle(self):
        manager = self._manager()
        download = ad.Download(
            "dl_queue_idle_hook",
            "https://example.com/video",
        )
        download.status = "complete"
        with manager._lock:
            manager._running_ids.add(download.id)
        manager._run_download = lambda _download: None
        manager._schedule = lambda: None
        refresh = mock.Mock()
        manager.maybe_refresh_ytdlp = refresh

        manager._worker_entry(download)

        refresh.assert_called_once_with("queue-idle")

    def test_maybe_refresh_ytdlp_is_a_safe_noop_without_the_hook(self):
        manager = self._manager()
        manager._dependencies.pop('maybe_auto_update_ytdlp', None)
        manager.maybe_refresh_ytdlp('test')  # must not raise

    def test_maybe_refresh_ytdlp_swallows_hook_failures(self):
        manager = self._manager()
        def boom(*_a, **_k):
            raise RuntimeError('updater exploded')
        manager._dependencies['maybe_auto_update_ytdlp'] = boom
        manager.maybe_refresh_ytdlp('test')  # a broken updater must never crash a download

    def test_run_download_bails_when_cancel_lands_before_worker_entry(self):
        manager = self._manager()
        dl = self._reserved_download(manager)
        self.assertTrue(manager.cancel(dl.id))
        self.assertEqual(dl.status, 'cancelled')

        manager._run_download(dl)  # the worker thread arrives after cancel()

        self.assertEqual(dl.status, 'cancelled',
                         "a cancelled download must not be revived to 'downloading'")
        self.assertIsNone(dl.process, "no yt-dlp subprocess may be spawned after cancel()")

    def test_launch_workers_releases_slot_for_already_cancelled_download(self):
        manager = self._manager()
        dl = self._reserved_download(manager)
        self.assertTrue(manager.cancel(dl.id))

        started = threading.Event()
        manager._worker_entry = lambda _dl: started.set()
        manager._launch_workers([dl])

        self.assertFalse(started.wait(0.2),
                         "no worker thread may start for a cancelled download")
        self.assertNotIn(dl.id, manager._running_ids,
                         "the reserved slot must be released — no finally block will do it")
        self.assertEqual(dl.status, 'cancelled')

    def test_launch_workers_unlinks_cookie_jar_when_cancel_lands_mid_write(self):
        import importlib
        download_module = importlib.import_module("download")
        manager = self._manager()
        dl_id, err = manager.start_download(
            "https://www.youtube.com/watch?v=raceguard2",
            cookies=[{"name": "SID", "value": "secret", "domain": ".youtube.com"}],
        )
        self.assertIsNone(err)
        dl = manager.downloads[dl_id]
        with manager._lock:
            dl.status = 'queued'
            manager._running_ids.add(dl_id)

        started = threading.Event()
        manager._worker_entry = lambda _dl: started.set()

        with tempfile.TemporaryDirectory() as tmp:
            def fake_write(cookies, jar_path, logger=None, domain_filter=None):
                Path(jar_path).write_text("jar", encoding="utf-8")
                # cancel() lands while the jar is being written; it cannot
                # unlink a jar it doesn't know about yet.
                self.assertTrue(manager.cancel(dl.id))
                return str(jar_path)

            with mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
                 mock.patch.object(download_module, 'write_cookies_netscape',
                                   side_effect=fake_write):
                manager._launch_workers([dl])

            jar = Path(tmp) / f".cookies.{dl.id}.txt"
            self.assertFalse(jar.exists(),
                             "a jar written after cancel() must be unlinked by the launcher")

        self.assertFalse(started.wait(0.2))
        self.assertIsNone(dl.cookies_file)
        self.assertNotIn(dl.id, manager._running_ids)
        self.assertEqual(dl.status, 'cancelled')

    def test_launch_workers_aborts_with_classified_cookie_jar_failure(self):
        import importlib
        download_module = importlib.import_module("download")
        manager = self._manager()
        dl_id, err = manager.start_download(
            "https://www.youtube.com/watch?v=cookieacl1",
            cookies=[{"name": "SID", "value": "secret", "domain": ".youtube.com"}],
        )
        self.assertIsNone(err)
        dl = manager.downloads[dl_id]
        with manager._lock:
            dl.status = 'queued'
            manager._running_ids.add(dl_id)

        started = threading.Event()
        manager._worker_entry = lambda _dl: started.set()
        with mock.patch.object(download_module, 'write_cookies_netscape', return_value=None):
            manager._launch_workers([dl])

        self.assertFalse(started.wait(0.2),
                         "yt-dlp must not start without a protected cookie jar")
        self.assertEqual(dl.status, 'failed')
        self.assertEqual(dl.error_code, 'cookie-jar-failed')
        self.assertEqual(dl.error_action, 'sign-in-and-retry')
        self.assertIn('protected YouTube cookie jar', dl.error)
        self.assertTrue(dl.to_dict()['retryable'])
        self.assertNotIn(dl.id, manager._running_ids)

    def test_retry_is_rejected_while_worker_is_finalizing(self):
        manager = self._manager()
        dl = self._reserved_download(manager)
        # Worker stamped a retryable failure but its finally block has not
        # discarded the id from _running_ids yet.
        with manager._lock:
            dl.status = 'failed'
            dl.error_code = 'network-unreachable'

        ok, err = manager.retry(dl.id)
        self.assertFalse(ok)
        self.assertIn('still finalizing', err)
        self.assertEqual(dl.status, 'failed', "the finalizing item must not flip to pending")

        # Once the worker's finally block releases the slot, retry succeeds.
        with manager._lock:
            manager._running_ids.discard(dl.id)
        ok, err = manager.retry(dl.id)
        self.assertTrue(ok, err)
        self.assertEqual(dl.status, 'pending')

    def test_resume_is_rejected_while_worker_is_finalizing(self):
        manager = self._manager()
        dl = self._reserved_download(manager)
        with manager._lock:
            dl.status = 'pending'

        ok, err = manager.resume_download(dl.id)
        self.assertFalse(ok)
        self.assertIn('still finalizing', err)

        with manager._lock:
            manager._running_ids.discard(dl.id)
        ok, err = manager.resume_download(dl.id)
        self.assertTrue(ok, err)

    def test_retry_and_resume_routes_surface_409_download_finalizing(self):
        token = "z" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        manager.pause_intake()
        dl_id, err = manager.start_download("https://www.youtube.com/watch?v=raceguard3")
        self.assertIsNone(err)
        dl = manager.downloads[dl_id]
        with manager._lock:
            dl.status = 'failed'
            dl.error_code = 'network-unreachable'
            manager._running_ids.add(dl_id)
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        headers = {"X-Auth-Token": token}

        resp = client.post(f"/queue/{dl_id}/retry", json={}, headers=headers)
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertEqual(body["code"], "download-finalizing")
        self.assertIn("still finalizing", body["error"])

        with manager._lock:
            dl.status = 'pending'
        resp = client.post(f"/queue/{dl_id}/resume", json={}, headers=headers)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "download-finalizing")

    def test_persist_intake_flag_writes_flag_without_changing_live_pause(self):
        # Companion self-update support: persist the pre-update flag for the
        # relaunched process while the dying process stays paused.
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / 'download-queue.json'
            config = FakeConfig({'DownloadPath': tmp, 'AudioDownloadPath': tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())

            self.assertTrue(manager.persist_intake_flag(False))
            self.assertTrue(manager.intake_paused, "the live pause must be untouched")

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertFalse(restored.intake_paused,
                             "the relaunched manager must see the persisted flag")


class MediaSourcePolicyTests(unittest.TestCase):
    """v1.8.0: any public media URL is accepted; private networks never are."""

    PUBLIC_URLS = (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.reddit.com/r/videos/comments/abc123/title/",
        "https://v.redd.it/abc123",
        "https://old.reddit.com/r/aww/comments/abc/clip/",
        "https://x.com/someone/status/1234567890",
        "https://twitter.com/someone/status/1234567890",
        "https://www.tiktok.com/@someone/video/7000000000000000000",
        "https://vimeo.com/123456789",
        "https://www.twitch.tv/someone/clip/AbcDef",
        "https://www.dailymotion.com/video/x8abcde",
        "https://www.instagram.com/reel/Abc123/",
        "https://www.facebook.com/watch/?v=1234567890",
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://soundcloud.com/artist/track",
        "https://streamable.com/abc123",
        "https://cdn.example.com/media/clip.mp4",
        "https://example.co.uk/watch?v=1",
        "https://xn--p1ai.xn--p1ai/video/1",
    )

    BLOCKED_URLS = (
        ("http://127.0.0.1:9751/download", "private-host"),
        ("http://localhost/video", "private-host"),
        ("http://[::1]/video", "private-host"),
        ("http://[::ffff:127.0.0.1]/video", "private-host"),
        ("http://10.1.2.3/video.mp4", "private-host"),
        ("http://192.168.0.10/admin", "private-host"),
        ("http://172.16.4.4/stream", "private-host"),
        ("http://169.254.169.254/latest/meta-data/", "private-host"),
        ("http://metadata.google.internal/computeMetadata/v1/", "private-host"),
        ("http://nas/movie.mp4", "private-host"),
        ("http://printer.local/stream", "private-host"),
        ("http://host.lan/video", "private-host"),
        ("http://0.0.0.0/video", "private-host"),
        ("http://2130706433/", "private-host"),
        ("http://127.1/", "non-public-host"),
        ("http://0x7f.0.0.1/", "non-public-host"),
        ("https://user:pw@example.com/video", "credentials-in-url"),
        ("ftp://example.com/video.mp4", "invalid-url"),
        ("file:///C:/secret.mp4", "invalid-url"),
        ("", "invalid-url"),
    )

    def test_public_media_urls_are_supported(self):
        for url in self.PUBLIC_URLS:
            self.assertIsNone(ad.media_url_block_reason(url), url)
            self.assertTrue(ad.is_supported_media_url(url), url)

    def test_private_and_malformed_urls_are_blocked_with_a_reason(self):
        for url, expected in self.BLOCKED_URLS:
            self.assertEqual(ad.media_url_block_reason(url), expected, url)
            self.assertFalse(ad.is_supported_media_url(url), url)

    def test_every_block_reason_has_user_facing_copy(self):
        for _url, reason in self.BLOCKED_URLS:
            message = ad.describe_media_url_block(reason)
            self.assertIn(reason, ad.MEDIA_URL_BLOCK_MESSAGES)
            self.assertTrue(message and not message.endswith(" "), reason)

    def test_clipboard_heuristic_stages_media_shaped_links_only(self):
        for staged in (
            "https://www.youtube.com/watch?v=abc",
            "https://www.reddit.com/r/videos/comments/abc/x/",
            "https://x.com/a/status/1",
            "https://vimeo.com/1",
            "https://cdn.example.com/a/clip.mp4",
            "https://site.example/embed/abc",
        ):
            self.assertTrue(ad.looks_like_media_link(staged), staged)
        for ignored in (
            "https://example.com/pricing",
            "https://docs.example.com/getting-started",
            "http://127.0.0.1/watch",          # loopback beats the path hint
            "http://nas.local/videos/clip.mp4",  # private host beats the extension hint
            "nonsense",
        ):
            self.assertFalse(ad.looks_like_media_link(ignored), ignored)

    def test_start_download_rejects_private_targets_from_every_entry_point(self):
        # The GUI quick-download box and the clipboard grabber call
        # start_download directly, bypassing the HTTP routes, so the policy has
        # to hold at the queue boundary too.
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            dl_id, error = manager.start_download(url="http://127.0.0.1:9751/x")
            self.assertIsNone(dl_id)
            self.assertIn("private", error.lower())
            self.assertEqual(manager.downloads, {})

    def test_start_download_accepts_non_youtube_public_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()  # queue it without spawning a worker
            dl_id, error = manager.start_download(
                url="https://www.reddit.com/r/videos/comments/abc/clip/"
            )
            self.assertIsNone(error)
            self.assertIn(dl_id, manager.downloads)

    def test_start_download_rejects_a_probed_size_before_queueing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            manager._dependencies["check_download_disk_space"] = (
                lambda *_args, **_kwargs: ad.download_error_payload(
                    "insufficient-disk-space",
                    error="The selected format is 400 MiB short of free space.",
                )
            )

            dl_id, error = manager.start_download(
                url="https://example.com/video",
                format_summary={
                    "formats": [{
                        "has_video": True,
                        "has_audio": True,
                        "height": 1080,
                        "filesize": 500 * 1024 * 1024,
                    }],
                },
            )

        self.assertIsNone(dl_id)
        self.assertEqual(error.error_code, "insufficient-disk-space")
        self.assertIn("400 MiB short", str(error))
        self.assertEqual(manager.downloads, {})

    def test_auth_recovery_clears_the_previous_run_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            url = "https://www.youtube.com/watch?v=authRetry1"
            download = ad.Download("dl_auth_retry", url, output_dir=tmpdir)
            download.status = "needs-auth"
            download.filename = str(Path(tmpdir) / "previous.mp4")
            manager.downloads[download.id] = download

            recovered_id, error = manager.start_download(
                url,
                cookies=[{
                    "domain": ".youtube.com",
                    "name": "SID",
                    "value": "fresh-cookie",
                    "path": "/",
                    "secure": True,
                }],
            )

            self.assertIsNone(error)
            self.assertEqual(recovered_id, download.id)
            self.assertEqual(download.filename, "")
            download.sabr_capped_warning = True
            manager._apply_zero_exit_outcome(download)

        self.assertEqual(download.status, "failed")
        self.assertEqual(download.error_code, "sabr-limited")

    def test_playlist_detection_covers_other_sites_without_changing_youtube(self):
        for playlist in (
            "https://www.youtube.com/playlist?list=PL123",
            "https://soundcloud.com/artist/sets/my-set",
            "https://example.com/album/12345",
            "https://tube.example/videos/playlist/abc",
            "https://podcast.example/series/season-one",
        ):
            self.assertTrue(ad.is_playlist_url(playlist), playlist)
        for single in (
            "https://www.youtube.com/watch?v=abc&list=PL123",  # historical contract
            "https://www.youtube.com/watch?v=abc",
            "https://www.reddit.com/r/videos/comments/abc/clip/",
            "https://x.com/someone/status/1",
            "https://cdn.example.com/clip.mp4",
            # Whole segments only. A slug that merely contains the word is one
            # video, and classifying it as a playlist filed it under a folder
            # named after a field yt-dlp could not resolve.
            "https://example.com/video/playlist-of-hits",
            "https://cdn.example.com/albums-of-the-year.mp4",
            "https://site.example/watch/series-finale",
        ):
            self.assertFalse(ad.is_playlist_url(single), single)

    def test_playlist_folder_never_falls_back_to_a_literal_na(self):
        # yt-dlp substitutes "NA" for an unresolved field, so a collection with
        # no title used to create a folder called NA that every such download
        # shared. Verified against the real binary: this template yields
        # "Playlist/…" when the fields are missing and the real title when they
        # are present.
        argv = AnySiteDownloadArgvTests()._argv_for(
            "https://example.com/playlist/season-one", with_cookies=False
        )
        template = argv[argv.index("-o") + 1]
        self.assertIn("%(playlist_title,playlist_id|Playlist).200B", template)
        self.assertNotEqual(template, "%(playlist_title).200B/%(title).200B.%(ext)s")

    def test_recovered_queue_keeps_non_youtube_entries(self):
        # Before v1.8.0 the restore path dropped every non-YouTube row, so a
        # Reddit download that survived a restart vanished without a trace.
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "download-queue.json"
            config = FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            manager.pause_intake()
            manager.start_download(url="https://v.redd.it/abc123")
            self.assertEqual(len(manager.downloads), 1)

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(len(restored.downloads), 1)
            self.assertEqual(
                next(iter(restored.downloads.values())).url,
                "https://v.redd.it/abc123",
            )


class AnySiteDownloadArgvTests(unittest.TestCase):
    """yt-dlp argv stays YouTube-scoped where it must and generic elsewhere."""

    class _FakeProc:
        def __init__(self, lines, returncode=0):
            self.stdout = iter(lines)
            self.returncode = returncode
            self._waited = False

        def wait(self):
            self._waited = True
            return self.returncode

        def poll(self):
            return self.returncode if self._waited else None

        def terminate(self):
            pass

        def kill(self):
            pass

        def communicate(self, *_args, **_kwargs):
            self._waited = True
            return ('', '')

    def _argv_for(self, url, *, config_overrides=None, with_cookies=True,
                  profile_name=None, output_name="", playlist_items=None,
                  output_template=""):
        attempts = []

        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            attempts.append(list(args))
            return self._FakeProc([
                'MDLP_JSON {"downloaded_bytes": 10, "total_bytes": 10}',
                'MDLP_FILEPATH "clip.mp4"',
            ], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            settings.update(config_overrides or {})
            config = FakeConfig(settings)
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_argv", url, output_dir=tmpdir, profile_name=profile_name,
                output_name=output_name, playlist_items=playlist_items,
                output_template=output_template,
            )
            download.status = "queued"
            if with_cookies:
                jar = Path(tmpdir) / "cookies.txt"
                jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
                download.cookies_file = str(jar)
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)
        self.assertTrue(attempts, "no yt-dlp invocation was captured")
        return attempts[0]


    def test_a_subscription_template_outranks_the_global_one(self):
        # One feed can land in its own folder shape while every other
        # download keeps the user's default.
        default = self._argv_for(
            "https://example.com/video", with_cookies=False,
            config_overrides={"OutputTemplate": "global/%(title)s.%(ext)s"},
        )
        self.assertEqual(
            default[default.index("-o") + 1], "global/%(title)s.%(ext)s")

        overridden = self._argv_for(
            "https://example.com/video", with_cookies=False,
            config_overrides={"OutputTemplate": "global/%(title)s.%(ext)s"},
            output_template="%(uploader)s/%(title)s.%(ext)s",
        )
        # Bounded on the way through, the same as any accepted template:
        # normalize_output_template caps each field so a long uploader name
        # cannot push the path past MAX_PATH.
        self.assertEqual(
            overridden[overridden.index("-o") + 1],
            ad.normalize_output_template("%(uploader)s/%(title)s.%(ext)s"),
        )
        self.assertIn("%(uploader)", overridden[overridden.index("-o") + 1])

    def test_a_template_that_escapes_the_download_folder_is_refused(self):
        # It arrives from a subscription record on disk, so the queue
        # boundary normalises it exactly as it does an API caller's.
        argv = self._argv_for(
            "https://example.com/video", with_cookies=False,
            config_overrides={"OutputTemplate": "global/%(title)s.%(ext)s"},
            output_template="../../%(title)s.%(ext)s",
        )
        self.assertEqual(
            argv[argv.index("-o") + 1], "global/%(title)s.%(ext)s",
            "a refused template falls back rather than being sent",
        )

    def test_non_youtube_download_is_single_item_and_cookie_free(self):
        argv = self._argv_for("https://www.reddit.com/r/videos/comments/abc/clip/")
        self.assertIn('--no-playlist', argv,
                      "a non-YouTube single link must not walk a whole profile")
        self.assertNotIn('--cookies', argv,
                         "the YouTube cookie jar must not follow the request off-site")
        self.assertNotIn('--extractor-args', argv,
                         "YouTube PO-token/client args are YouTube-only")

    def test_youtube_download_keeps_cookies_and_extractor_args(self):
        argv = self._argv_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIn('--cookies', argv)
        self.assertIn('--extractor-args', argv)
        self.assertNotIn('--no-playlist', argv,
                         "YouTube keeps its historical playlist semantics")

    def test_network_workarounds_reach_the_download_invocation(self):
        argv = self._argv_for(
            "https://example.com/video",
            config_overrides={
                "ForceIPVersion": "ipv6",
                "SourceAddress": "2001:db8::10",
                "Xff": "US",
                "GeoVerificationProxy": "https://proxy.example:8443",
            },
            with_cookies=False,
        )
        self.assertIn('--force-ipv6', argv)
        self.assertEqual(argv[argv.index('--source-address') + 1], '2001:db8::10')
        self.assertEqual(argv[argv.index('--xff') + 1], 'US')
        self.assertEqual(
            argv[argv.index('--geo-verification-proxy') + 1],
            'https://proxy.example:8443',
        )

    def test_matching_profile_overlays_download_network_and_pacing_args(self):
        argv = self._argv_for(
            "https://www.youtube.com/watch?v=profile",
            config_overrides={
                "RateLimit": "1M",
                "SiteProfiles": [{
                    "Name": "Archive",
                    "Domain": "youtube.com",
                    "Proxy": "https://profile-proxy.example:8443",
                    "RateLimit": "500K",
                    "ForceIPVersion": "ipv4",
                    "SleepIntervalSeconds": 3,
                    "MaxSleepIntervalSeconds": 5,
                }],
            },
            profile_name="Archive",
            with_cookies=False,
        )
        self.assertEqual(argv[argv.index('--proxy') + 1], 'https://profile-proxy.example:8443')
        self.assertEqual(argv[argv.index('--limit-rate') + 1], '500K')
        self.assertIn('--force-ipv4', argv)
        self.assertEqual(argv[argv.index('--sleep-interval') + 1], '3')
        self.assertEqual(argv[argv.index('--max-sleep-interval') + 1], '5')

    def test_archive_options_compile_without_changing_embed_flags(self):
        argv = self._argv_for(
            "https://example.com/live",
            config_overrides={
                "EmbedMetadata": True,
                "EmbedThumbnail": True,
                "EmbedChapters": True,
                "WriteInfoJson": True,
                "WriteDescription": True,
                "WriteThumbnail": True,
                "SplitChapters": True,
                "LiveFromStart": True,
                "WaitForVideoSeconds": 45,
            },
            with_cookies=False,
        )
        for flag in (
            "--embed-metadata", "--embed-thumbnail", "--embed-chapters",
            "--write-info-json", "--write-description", "--write-thumbnail",
            "--split-chapters", "--live-from-start",
        ):
            self.assertIn(flag, argv)
        self.assertIn("--windows-filenames", argv)
        self.assertEqual(argv[argv.index("--wait-for-video") + 1], "45")

    def test_nfo_archiving_fetches_metadata_json_without_duplicate_flags(self):
        argv = self._argv_for(
            "https://example.com/video",
            config_overrides={"WriteNfo": True},
            with_cookies=False,
        )
        self.assertEqual(argv.count("--write-info-json"), 1)

    def test_completed_download_converts_yt_dlp_metadata_into_an_nfo(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as install_dir, \
                mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
            final = Path(output_dir) / "Clip.mp4"
            metadata = {
                "id": "clip-123",
                "title": "Clip",
                "extractor_key": "Youtube",
                "webpage_url": "https://youtube.com/watch?v=clip-123",
            }

            def popen(args, **_kwargs):
                if '--ignore-config' not in args:
                    return self._FakeProc([], 0)
                final.write_bytes(b"finished")
                Path(f"{final}.info.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                return self._FakeProc(
                    [f'MDLP_FILEPATH {json.dumps(str(final))}'], 0
                )

            config = FakeConfig({
                "DownloadPath": output_dir,
                "AudioDownloadPath": output_dir,
                "WriteNfo": True,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_nfo", "https://youtube.com/watch?v=clip-123",
                output_dir=output_dir,
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                    mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                    mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

            self.assertEqual(download.status, "complete")
            nfo = final.with_suffix(".nfo")
            self.assertTrue(nfo.exists())
            self.assertEqual(ET.parse(nfo).getroot().findtext("youtubeid"), "clip-123")

    def test_non_youtube_playlist_url_still_downloads_the_collection(self):
        argv = self._argv_for("https://soundcloud.com/artist/sets/my-set",
                              with_cookies=False)
        self.assertIn('--yes-playlist', argv)
        self.assertNotIn('--no-playlist', argv)

    def test_download_stages_intermediates_outside_destination_and_sweeps_them(self):
        attempts = []
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as install_dir, \
                mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
            final = Path(output_dir) / "Clip.mp4"

            def popen(args, **_kwargs):
                if '--ignore-config' not in args:
                    return self._FakeProc([], 0)
                attempts.append(list(args))
                path_args = [
                    args[index + 1]
                    for index, value in enumerate(args[:-1])
                    if value == '--paths'
                ]
                temp_arg = next(value for value in path_args if value.startswith('temp:'))
                staging = Path(temp_arg[len('temp:'):])
                staging.mkdir(parents=True)
                (staging / "Clip.mp4.part").write_text("partial", encoding="utf-8")
                final.write_text("finished", encoding="utf-8")
                return self._FakeProc(
                    [f'MDLP_FILEPATH {json.dumps(str(final))}'], 0
                )

            config = FakeConfig({
                "DownloadPath": output_dir,
                "AudioDownloadPath": output_dir,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download("dl_private_stage", "https://example.com/video",
                                   output_dir=output_dir)
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                    mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                    mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

            self.assertEqual(download.status, "complete")
            self.assertEqual(len(attempts), 1)
            argv = attempts[0]
            output_template = argv[argv.index('-o') + 1]
            self.assertEqual(output_template, "%(title).200B.%(ext)s")
            path_args = [
                argv[index + 1]
                for index, value in enumerate(argv[:-1])
                if value == '--paths'
            ]
            self.assertIn(f"home:{output_dir}", path_args)
            temp_arg = next(value for value in path_args if value.startswith('temp:'))
            staging = Path(temp_arg[len('temp:'):])
            self.assertTrue(staging.is_relative_to(Path(install_dir)))
            self.assertFalse(staging.is_relative_to(Path(output_dir)))
            self.assertTrue(final.exists())
            self.assertEqual(list(Path(output_dir).iterdir()), [final])
            self.assertFalse(staging.exists())

    def test_keep_intermediates_stages_them_beside_the_output_for_diagnosis(self):
        argv = self._argv_for(
            "https://example.com/video",
            config_overrides={"KeepIntermediateFiles": True},
            with_cookies=False,
        )
        path_args = [
            argv[index + 1]
            for index, value in enumerate(argv[:-1])
            if value == '--paths'
        ]
        self.assertIn(
            next(value for value in path_args if value.startswith('home:'))
            .replace('home:', 'temp:', 1),
            path_args,
        )
        self.assertFalse(Path(argv[argv.index('-o') + 1]).is_absolute())

    def test_recovered_download_reuses_staging_path_after_restart(self):
        attempts = []
        partial_seen = []
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as install_dir, \
                mock.patch.object(ad, "INSTALL_DIR", Path(install_dir)):
            queue_path = Path(install_dir) / "download-queue.json"
            config = FakeConfig({
                "DownloadPath": output_dir,
                "AudioDownloadPath": output_dir,
            })
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            download_id, error = manager.start_download(
                "https://example.com/video", title="Recover me"
            )
            self.assertIsNone(error)
            original = manager.downloads[download_id]
            staging = manager._download_intermediate_dir(original)
            staging.mkdir(parents=True)
            partial = staging / "Recover me.mp4.part"
            partial.write_text("partial", encoding="utf-8")

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            recovered = restored.downloads[download_id]
            self.assertTrue(recovered.resume_partial)
            self.assertEqual(restored._download_intermediate_dir(recovered), staging)
            recovered.status = "queued"
            final = Path(output_dir) / "Recover me.mp4"

            def popen(args, **_kwargs):
                if '--ignore-config' not in args:
                    return self._FakeProc([], 0)
                attempts.append(list(args))
                temp_arg = next(
                    args[index + 1]
                    for index, value in enumerate(args[:-1])
                    if value == '--paths' and args[index + 1].startswith('temp:')
                )
                resumed_staging = Path(temp_arg[len('temp:'):])
                partial_seen.append((resumed_staging, partial.exists()))
                final.write_text("finished", encoding="utf-8")
                return self._FakeProc(
                    [f'MDLP_FILEPATH {json.dumps(str(final))}'], 0
                )

            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                    mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                    mock.patch.object(ad, 'write_persistent_log', return_value=None):
                restored._run_download(recovered)

            self.assertEqual(len(attempts), 1)
            self.assertEqual(partial_seen, [(staging, True)])
            self.assertNotIn('--force-overwrites', attempts[0])
            self.assertFalse(staging.exists())

    def test_zero_exit_without_a_file_reports_skipped_not_complete(self):
        # yt-dlp exits 0 when --max-filesize rejects every format. Reporting
        # "complete" with nothing on disk reads as a broken downloader.
        attempts = []

        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            attempts.append(list(args))
            return self._FakeProc([], 0)  # no Destination / filepath line

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "MaxFileSizeMB": 25,
            })
            history = FakeHistory()
            manager = ad.DownloadManager(config, history)
            download = ad.Download(
                "dl_skip", "https://archive.org/details/BigBuckBunny_124",
                output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "skipped")
        self.assertIn("25 MB size limit", download.error)
        self.assertEqual(download.progress, 0)
        self.assertEqual(manager.total_completed, 0,
                         "a skip is not a completed download")
        self.assertEqual(len(history.entries), 1,
                         "every terminal outcome is retained in history")
        self.assertEqual(history.entries[0]["status"], "skipped")
        self.assertIn("skipped", ad.DOWNLOAD_TERMINAL_STATES,
                      "a skip must be terminal or the queue slot never frees")

    def test_zero_exit_with_a_file_still_completes(self):
        # Guards the skip rule against over-reach: a run that announces a
        # destination is a real success on any site.
        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            return self._FakeProc(['[download] Destination: clip.mp4'], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "MaxFileSizeMB": 25,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_ok", "https://v.redd.it/abc123", output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "complete")
        self.assertEqual(download.progress, 100)
        self.assertEqual(download.filename, "clip.mp4")

    def test_zero_exit_with_a_sabr_warning_and_file_completes(self):
        # A warning describes formats yt-dlp skipped, not the file it did
        # deliver. The finished file must be the source of truth at exit 0.
        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            delivered = Path(tmpdir) / 'clip.mp4'
            delivered.write_bytes(b'media')
            progress = [f'[download] {index}.0%' for index in range(1, 32)]
            return self._FakeProc(
                [
                    'WARNING: [youtube] abc: Some web client https formats have '
                    'been skipped as they are missing a url. YouTube is forcing '
                    'SABR streaming',
                    *progress,
                    f'MDLP_FILEPATH {json.dumps(str(delivered))}',
                ],
                0,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_sabr", "https://www.youtube.com/watch?v=abc", output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "complete")
        self.assertEqual(download.progress, 100)
        self.assertEqual(download.filename, str(Path(tmpdir) / 'clip.mp4'))
        self.assertEqual(download.error_code, "")
        self.assertTrue(getattr(download, "sabr_capped_warning", False))

    def test_zero_exit_with_only_a_sabr_warning_still_fails(self):
        def popen(args, **_kwargs):
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            return self._FakeProc(
                [
                    'WARNING: [youtube] abc: Some web client https formats have '
                    'been skipped as they are missing a url. YouTube is forcing '
                    'SABR streaming',
                ],
                0,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download(
                "dl_sabr_empty", "https://www.youtube.com/watch?v=abc",
                output_dir=tmpdir,
            )
            download.status = "queued"
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                manager._run_download(download)

        self.assertEqual(download.status, "failed")
        self.assertEqual(download.error_code, "sabr-limited")
        self.assertTrue(getattr(download, "sabr_capped_warning", False))

    def test_sponsorblock_is_not_requested_off_youtube(self):
        overrides = {"SponsorBlock": True, "SponsorBlockAction": "remove"}
        youtube = self._argv_for("https://www.youtube.com/watch?v=abc",
                                 config_overrides=overrides, with_cookies=False)
        self.assertIn('--sponsorblock-remove', youtube)
        other = self._argv_for("https://vimeo.com/123", config_overrides=overrides,
                               with_cookies=False)
        self.assertNotIn('--sponsorblock-remove', other)


class PlaylistBoundTests(unittest.TestCase):
    """A pasted playlist can be bounded without reintroducing an archive."""

    def test_defaults_bound_nothing(self):
        self.assertEqual(
            ad.build_playlist_bound_args(ad.sanitize_config({})), []
        )

    def test_a_count_cap_compiles(self):
        self.assertEqual(
            ad.build_playlist_bound_args({"PlaylistMaxItems": 5}),
            ["--max-downloads", "5"],
        )

    def test_a_date_bound_compiles(self):
        self.assertEqual(
            ad.build_playlist_bound_args({"PlaylistDateAfter": "today-30days"}),
            ["--dateafter", "today-30days"],
        )

    def test_duration_bounds_become_one_match_filter(self):
        # One expression, so neither bound can be dropped independently.
        self.assertEqual(
            ad.build_playlist_bound_args({
                "PlaylistMinDurationSeconds": 60,
                "PlaylistMaxDurationSeconds": 3600,
            }),
            ["--match-filters", "duration>=60 & duration<=3600"],
        )

    def test_a_lone_minimum_leaves_the_maximum_out(self):
        self.assertEqual(
            ad.build_playlist_bound_args({"PlaylistMinDurationSeconds": 60}),
            ["--match-filters", "duration>=60"],
        )

    # ── The date grammar is an allow-list, not a sanitiser ───────────────

    def test_an_absolute_and_a_relative_date_are_accepted(self):
        # An integer is included deliberately: a config file can carry
        # 20260101 unquoted, and that is a date, not junk.
        for value in ("20260101", "today-30days", "now-1year", "TODAY-2 weeks",
                      20260101):
            with self.subTest(value=value):
                self.assertTrue(ad.normalize_playlist_date(value), value)

    def test_anything_else_is_dropped_rather_than_passed(self):
        # This lands in a subprocess argument, and an unparseable value would
        # make yt-dlp reject the whole download rather than the one setting.
        for value in ("2026-01-01", "yesterday", "; rm -rf /", "--exec=calc",
                      "today-30fortnights", "202601", "", None):
            with self.subTest(value=value):
                self.assertEqual(ad.normalize_playlist_date(value), "")

    def test_a_maximum_below_the_minimum_is_normalised(self):
        # The pair would otherwise match nothing at all, which reads as a
        # broken download rather than a filter the user got wrong.
        data = ad.sanitize_config({
            "PlaylistMinDurationSeconds": 600,
            "PlaylistMaxDurationSeconds": 60,
        })
        self.assertEqual(data["PlaylistMaxDurationSeconds"], 600)

    # ── Where they apply ─────────────────────────────────────────────────

    def test_the_archive_flag_stays_out(self):
        # subscriptions.py's archive keys are this project's answer to
        # "already seen"; a second mechanism makes a deliberate re-download
        # report "already downloaded" and do nothing.
        args = ad.build_playlist_bound_args({
            "PlaylistMaxItems": 5, "PlaylistDateAfter": "20260101",
            "PlaylistMinDurationSeconds": 60,
        })
        self.assertNotIn("--download-archive", args)

    def test_the_real_binary_accepts_the_compiled_bounds(self):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        args = ad.build_playlist_bound_args({
            "PlaylistMaxItems": 3,
            "PlaylistDateAfter": "today-30days",
            "PlaylistMinDurationSeconds": 60,
            "PlaylistMaxDurationSeconds": 3600,
        })
        proc = subprocess.run(
            [str(ytdlp), "--ignore-config", "--no-plugin-dirs"] + args
            + ["--help"],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0,
                         (proc.stdout[-400:], proc.stderr[-400:]))


class PlaylistBoundArgvTests(unittest.TestCase):
    """The bounds reach a playlist run, and only a playlist run."""

    def setUp(self):
        self.addCleanup(ad.reset_deno_runtime_cache)
        self.addCleanup(ad.reset_ffmpeg_capabilities_cache)
        self.addCleanup(ad.reset_po_token_provider_cache)

    def _argv(self, url, overrides):
        captured = []

        class Proc:
            returncode = 0

            def __init__(self, args, **_kwargs):
                captured.append(list(args))
                self.stdout = iter(["[download] Destination: clip.mp4\n"])

            def wait(self):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                # reason: satisfy the API the cancel path expects
                pass

            def kill(self):
                # reason: same as terminate
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            settings.update(overrides)
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            download = ad.Download("dl_playlist", url, output_dir=tmpdir)
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", Proc), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
        runs = [args for args in captured if download.url in args]
        self.assertEqual(len(runs), 1)
        return runs[0]

    _BOUNDS = {
        "PlaylistMaxItems": 4,
        "PlaylistDateAfter": "today-7days",
        "PlaylistMinDurationSeconds": 90,
    }

    def test_a_playlist_run_carries_the_bounds(self):
        argv = self._argv(
            "https://www.youtube.com/playlist?list=PL123", self._BOUNDS
        )
        self.assertIn("--yes-playlist", argv)
        self.assertEqual(argv[argv.index("--max-downloads") + 1], "4")
        self.assertEqual(argv[argv.index("--dateafter") + 1], "today-7days")
        self.assertEqual(argv[argv.index("--match-filters") + 1], "duration>=90")

    def test_a_single_video_is_never_filtered_by_them(self):
        # A bound meant for a playlist must not silently skip the one video
        # the user actually asked for.
        argv = self._argv(
            "https://www.youtube.com/watch?v=abc12345678", self._BOUNDS
        )
        for flag in ("--max-downloads", "--dateafter", "--match-filters"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv)


class FormatSortTests(unittest.TestCase):
    """Audio richness and codec/frame-rate preferences compile to one --format-sort."""

    def test_defaults_prefer_audio_richness_and_original_language(self):
        self.assertEqual(
            ad.build_format_sort_args(ad.sanitize_config({})),
            ["--format-sort", "res,channels,lang"],
        )

    def test_resolution_always_leads_the_sort(self):
        # yt-dlp puts the given fields ahead of its own defaults, so naming
        # vcodec alone ranks a 360p H.264 stream above a 1080p VP9 one.
        # Verified against the real binary: `--format-sort vcodec:h264` on a
        # 4K source selects 1080p, `res,vcodec:h264` keeps 2160p.
        args = ad.build_format_sort_args({"VideoCodecPreference": "h264"})
        self.assertEqual(
            args, ["--format-sort", "res,channels,lang,vcodec:h264"]
        )

    def test_every_preference_compiles_into_one_flag(self):
        args = ad.build_format_sort_args({
            "VideoCodecPreference": "av1",
            "AudioCodecPreference": "opus",
            "PreferredFrameRate": 60,
        })
        self.assertEqual(
            args,
            ["--format-sort",
             "res,channels,lang,vcodec:av01,acodec:opus,fps~60"],
        )

    def test_frame_rate_is_a_target_not_a_requirement(self):
        # `~` is "closest to": an unavailable 60fps falls back rather than
        # failing the whole format selection.
        args = ad.build_format_sort_args({"PreferredFrameRate": 60})
        self.assertIn("fps~60", args[1])

    def test_an_unknown_preference_is_ignored(self):
        for config in (
            {"VideoCodecPreference": "h265"},
            {"AudioCodecPreference": "flac"},
            {"PreferredFrameRate": "nonsense"},
            {"PreferredFrameRate": 0},
        ):
            self.assertEqual(
                ad.build_format_sort_args(config),
                ["--format-sort", "res,channels,lang"],
                config,
            )

    def test_the_two_modules_share_one_vocabulary(self):
        # config.py owns the schema, download.py owns the argv mapping, and
        # the modules never cross-import. Neither may gain a value the other
        # does not know.
        self.assertEqual(
            set(ad.FORMAT_SORT_VIDEO_FIELDS) | {"auto"},
            set(ad.FORMAT_SORT_VIDEO_CODECS),
        )
        self.assertEqual(
            set(ad.FORMAT_SORT_AUDIO_FIELDS) | {"auto"},
            set(ad.FORMAT_SORT_AUDIO_CODECS),
        )

    def test_sanitize_rejects_a_value_outside_the_vocabulary(self):
        data = ad.sanitize_config({
            "VideoCodecPreference": "h265",
            "AudioCodecPreference": "flac",
            "PreferredFrameRate": 45,
        })
        self.assertEqual(data["VideoCodecPreference"], "auto")
        self.assertEqual(data["AudioCodecPreference"], "auto")
        self.assertEqual(data["PreferredFrameRate"], 0)

    def test_the_editor_safe_container_path_is_untouched(self):
        # MP4 remains a hard H.264 + AAC constraint; the preference only
        # orders what that leaves open.
        args = ad.build_video_format_args("mp4", "1080")
        self.assertIn("bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]",
                      args[1])
        self.assertEqual(args[2:], ["--merge-output-format", "mp4"])

    # A synthetic format table with H.264 only at 720p and AV1 at 1080p. It
    # is the smallest shape that distinguishes "prefer H.264" from "prefer
    # H.264 without losing resolution", and `--load-info-json` means the real
    # binary decides, offline and deterministically.
    _SORT_FIXTURE = {
        "id": "t", "title": "t", "_type": "video",
        "extractor": "generic", "extractor_key": "Generic",
        "webpage_url": "https://example.test/t",
        "formats": [
            {"format_id": "h264-720", "url": "https://example.test/a",
             "ext": "mp4", "height": 720, "width": 1280, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "none", "protocol": "https"},
            {"format_id": "av1-1080", "url": "https://example.test/b",
             "ext": "mp4", "height": 1080, "width": 1920, "fps": 60,
             "vcodec": "av01.0.09M.08", "acodec": "none", "protocol": "https"},
            {"format_id": "audio", "url": "https://example.test/d",
             "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2",
             "protocol": "https"},
        ],
    }

    def _selected_format(self, sort_args):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        with tempfile.TemporaryDirectory() as tmpdir:
            info = Path(tmpdir) / "info.json"
            info.write_text(json.dumps(self._SORT_FIXTURE), encoding="utf-8")
            proc = subprocess.run(
                [str(ytdlp), "--ignore-config", "--no-plugin-dirs",
                 "--no-warnings", "-f", "bestvideo"] + list(sort_args)
                + ["--simulate", "--print", "%(format_id)s",
                   "--load-info-json", str(info)],
                capture_output=True, text=True, timeout=120,
            )
        lines = [line.strip() for line in (proc.stdout or "").splitlines()
                 if line.strip()]
        self.assertTrue(lines, (proc.stdout, proc.stderr))
        return lines[-1]

    def test_the_real_binary_honours_the_codec_preference(self):
        # Not just "the flag parses": the preference has to change the choice.
        self.assertEqual(self._selected_format([]), "av1-1080")
        self.assertEqual(
            self._selected_format(
                ad.build_format_sort_args({"VideoCodecPreference": "h264"})
            ),
            "av1-1080",
        )

    # A native 1080p upload alongside YouTube's AI upscale of it at 2160p.
    # Resolution alone puts the upscale first, which is the behaviour the
    # setting exists to reverse. `format_note` carries yt-dlp's marker
    # (2026.08.19 onwards); the audio track carries none at all, which is
    # what the none-inclusive negation has to keep.
    _UPSCALE_FIXTURE = {
        "id": "u", "title": "u", "_type": "video",
        "extractor": "generic", "extractor_key": "Generic",
        "webpage_url": "https://example.test/u",
        "formats": [
            {"format_id": "native-1080", "url": "https://example.test/a",
             "ext": "mp4", "height": 1080, "width": 1920, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "none", "protocol": "https",
             "format_note": "1080p"},
            {"format_id": "sr-2160", "url": "https://example.test/b",
             "ext": "mp4", "height": 2160, "width": 3840, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "none", "protocol": "https",
             "format_note": "2160p, AI-upscaled"},
            {"format_id": "audio", "url": "https://example.test/d",
             "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2",
             "protocol": "https"},
        ],
    }

    def _selected_from(self, fixture, format_args):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        with tempfile.TemporaryDirectory() as tmpdir:
            info = Path(tmpdir) / "info.json"
            info.write_text(json.dumps(fixture), encoding="utf-8")
            proc = subprocess.run(
                [str(ytdlp), "--ignore-config", "--no-plugin-dirs",
                 "--no-warnings"] + list(format_args)
                + ["--simulate", "--print", "%(format_id)s",
                   "--load-info-json", str(info)],
                capture_output=True, text=True, timeout=120,
            )
        lines = [line.strip() for line in (proc.stdout or "").splitlines()
                 if line.strip()]
        self.assertTrue(lines, (proc.stdout, proc.stderr))
        return lines[-1]

    def test_the_upscale_preference_is_off_by_default_in_the_selector(self):
        # The chain has to be byte-identical to the historical one when the
        # setting is off, or every download changes shape for a YouTube-only
        # problem.
        self.assertEqual(
            ad.build_video_format_args("mp4", "1080"),
            ad.build_video_format_args("mp4", "1080", avoid_upscaled=False),
        )
        self.assertNotIn("AI-upscaled",
                         ad.build_video_format_args("mp4", "1080")[1])

    def test_the_upscale_preference_falls_back_rather_than_excluding(self):
        # Deprioritise, not exclude: an unfiltered tier always trails the
        # filtered one, so a site that only offers an upscale still downloads.
        tiers = ad.build_video_format_args(
            "mp4", "best", avoid_upscaled=True)[1].split("/")
        self.assertTrue(any("AI-upscaled" in tier for tier in tiers))
        self.assertNotIn("AI-upscaled", tiers[-1])

    def test_the_height_cap_outranks_the_upscale_preference(self):
        # Every capped tier has to come before every uncapped one, or asking
        # for 1080p on a video whose only 1080p rendition is upscaled fetches
        # the native 2160p instead and exceeds the cap the user set.
        tiers = ad.build_video_format_args(
            "mp4", "1080", avoid_upscaled=True)[1].split("/")
        capped = [index for index, tier in enumerate(tiers)
                  if "height<=1080" in tier]
        uncapped = [index for index, tier in enumerate(tiers)
                    if "height<=1080" not in tier]
        self.assertTrue(capped and uncapped)
        self.assertLess(max(capped), min(uncapped))
        # Within the capped block, native still comes first.
        native = [index for index in capped if "AI-upscaled" in tiers[index]]
        plain = [index for index in capped if "AI-upscaled" not in tiers[index]]
        self.assertLess(max(native), min(plain))

    # A progressive (muxed) table: the native upload is above the cap and the
    # only rendition inside it is the AI upscale. This is the shape that
    # turns a preference into a cap violation.
    _CAPPED_UPSCALE_FIXTURE = {
        "id": "c", "title": "c", "_type": "video",
        "extractor": "generic", "extractor_key": "Generic",
        "webpage_url": "https://example.test/c",
        "formats": [
            {"format_id": "native-2160", "url": "https://example.test/a",
             "ext": "mp4", "height": 2160, "width": 3840, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "mp4a.40.2",
             "protocol": "https", "format_note": "2160p"},
            {"format_id": "sr-1080", "url": "https://example.test/b",
             "ext": "mp4", "height": 1080, "width": 1920, "fps": 30,
             "vcodec": "avc1.640028", "acodec": "mp4a.40.2",
             "protocol": "https", "format_note": "1080p, AI-upscaled"},
        ],
    }

    def test_the_real_binary_keeps_the_cap_when_only_an_upscale_fits(self):
        self.assertEqual(
            self._selected_from(
                self._CAPPED_UPSCALE_FIXTURE,
                ad.build_video_format_args("any", "1080")[:2],
            ),
            "sr-1080",
        )
        self.assertEqual(
            self._selected_from(
                self._CAPPED_UPSCALE_FIXTURE,
                ad.build_video_format_args(
                    "any", "1080", avoid_upscaled=True)[:2],
            ),
            "sr-1080",
        )

    def test_the_real_binary_takes_the_native_upload_over_the_upscale(self):
        # yt-dlp's own ordering puts the 2160p upscale first...
        self.assertEqual(
            self._selected_from(
                self._UPSCALE_FIXTURE,
                ad.build_video_format_args("any", "best")[:2],
            ),
            "sr-2160+audio",
        )
        # ...and the setting reverses that without losing the audio track,
        # which carries no format_note to match against.
        self.assertEqual(
            self._selected_from(
                self._UPSCALE_FIXTURE,
                ad.build_video_format_args(
                    "any", "best", avoid_upscaled=True)[:2],
            ),
            "native-1080+audio",
        )

    def test_the_real_binary_still_takes_an_upscale_when_it_is_all_there_is(self):
        only_upscaled = dict(self._UPSCALE_FIXTURE)
        only_upscaled["formats"] = [
            fmt for fmt in self._UPSCALE_FIXTURE["formats"]
            if fmt["format_id"] != "native-1080"
        ]
        self.assertEqual(
            self._selected_from(
                only_upscaled,
                ad.build_video_format_args(
                    "any", "best", avoid_upscaled=True)[:2],
            ),
            "sr-2160+audio",
        )

    def test_the_real_binary_shows_why_res_has_to_lead(self):
        # The trap this compiler exists to avoid, demonstrated rather than
        # asserted: a bare vcodec preference drops 1080p to 720p because that
        # is as high as H.264 goes here.
        self.assertEqual(
            self._selected_format(["--format-sort", "vcodec:h264"]), "h264-720"
        )


class SiteLoginStoreTests(unittest.TestCase):
    """The store keeps one site's session and discards everything else."""

    MIXED_EXPORT = "\n".join([
        "# Netscape HTTP Cookie File",
        ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tX-SECRET",
        "#HttpOnly_.x.com\tTRUE\t/\tTRUE\t2000000000\tct0\tX-CT0",
        ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tYT-SECRET",
        ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tIG-SECRET",
        "video.twimg.com\tFALSE\t/\tTRUE\t2000000000\tcdn\tCDN",
    ])

    def _store(self, root, clock=None):
        return ad.SiteLoginStore(root, clock=clock or (lambda: 1_700_000_000))

    def test_import_keeps_only_the_target_sites_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            result, error = store.import_netscape_text("https://x.com/", self.MIXED_EXPORT)
            self.assertIsNone(error)
            self.assertEqual(result["site"], "x.com")
            self.assertEqual(result["cookies"], 2)
            self.assertEqual(result["skipped"], 3)
            jar = Path(tmp) / ad.SITE_LOGIN_DIRNAME / "x.com.txt"
            body = jar.read_text(encoding="utf-8")
            self.assertIn("X-SECRET", body)
            for foreign in ("YT-SECRET", "IG-SECRET", "CDN"):
                self.assertNotIn(foreign, body, "a foreign site's cookie was stored")

    def test_entries_never_expose_cookie_names_or_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            entries = store.entries()
            self.assertEqual(len(entries), 1)
            rendered = json.dumps(entries)
            for secret in ("X-SECRET", "X-CT0", "auth_token", "ct0"):
                self.assertNotIn(secret, rendered)
            self.assertEqual(entries[0]["cookies"], 2)
            self.assertTrue(entries[0]["stored"])
            self.assertFalse(entries[0]["expired"])

    def test_credentials_are_stored_as_protected_metadata_free_secrets(self):
        username = "member@example.com"
        password = "PASSWORD-ONLY-FOR-TEST"
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            result, error = store.save_credentials("vimeo.com", username, password)
            self.assertIsNone(error)
            self.assertEqual(result, {"site": "vimeo.com", "credentialed": True})
            entries = store.entries()
            serialized = json.dumps(entries)
            self.assertNotIn(username, serialized)
            self.assertNotIn(password, serialized)
            self.assertTrue(entries[0]["credentialed"])
            self.assertTrue(entries[0]["stored"])
            self.assertEqual(
                store.credentials_for_url("https://vimeo.com/video"),
                {"username": username, "password": password},
            )
            auth_path = Path(tmp) / ad.SITE_LOGIN_DIRNAME / "vimeo.com.auth"
            self.assertTrue(auth_path.exists())

            reopened = self._store(tmp)
            self.assertEqual(
                reopened.credentials_for_url("https://www.vimeo.com/video"),
                {"username": username, "password": password},
            )

    def test_credential_undo_restores_the_protected_file_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.save_credentials("vimeo.com", "member", "secret-password")
            undo, error = store.remove_with_undo("vimeo.com")
            self.assertIsNone(error)
            self.assertTrue(undo["hasCredentials"])
            self.assertNotIn("secret-password", json.dumps(undo))
            self.assertFalse(
                (Path(tmp) / ad.SITE_LOGIN_DIRNAME / "vimeo.com.auth").exists()
            )
            restored, error = store.restore_removed(undo)
            self.assertTrue(restored)
            self.assertIsNone(error)
            self.assertEqual(
                store.credentials_for_url("https://vimeo.com/video")["password"],
                "secret-password",
            )

    def test_reddit_and_linkedin_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            for site in ("reddit.com", "linkedin.com"):
                result, error = store.save_credentials(site, "user", "password")
                self.assertIsNone(result)
                self.assertIn("cookies.txt", error)

    def test_import_rejects_cookies_that_do_not_belong_to_the_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            result, error = store.import_netscape_text("vimeo.com", self.MIXED_EXPORT)
            self.assertIsNone(result)
            self.assertIn("belong to vimeo.com", error)
            self.assertFalse((Path(tmp) / ad.SITE_LOGIN_DIRNAME / "vimeo.com.txt").exists())

    def test_store_is_bounded_and_removable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            for index in range(ad.MAX_SITE_LOGINS):
                site = f"site{index}.com"
                _result, error = store.import_netscape_text(
                    site, f".{site}\tTRUE\t/\tTRUE\t2000000000\ta\tb"
                )
                self.assertIsNone(error, site)
            _result, error = store.import_netscape_text(
                "overflow.com", ".overflow.com\tTRUE\t/\tTRUE\t2000000000\ta\tb"
            )
            self.assertIn("limit reached", error)

            self.assertTrue(store.remove("site0.com"))
            self.assertFalse((Path(tmp) / ad.SITE_LOGIN_DIRNAME / "site0.com.txt").exists())
            self.assertFalse(store.remove("site0.com"), "removal is idempotent")
            _result, error = store.import_netscape_text(
                "overflow.com", ".overflow.com\tTRUE\t/\tTRUE\t2000000000\ta\tb"
            )
            self.assertIsNone(error, "a freed slot can be reused")

    def test_remove_with_undo_restores_the_protected_jar_without_exposing_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            undo, error = store.remove_with_undo("x.com")
            self.assertIsNone(error)
            self.assertEqual(undo["site"], "x.com")
            self.assertNotIn("X-SECRET", json.dumps(undo))
            self.assertEqual(store.entries(), [])
            self.assertFalse(
                (Path(tmp) / ad.SITE_LOGIN_DIRNAME / "x.com.txt").exists()
            )

            restored, error = store.restore_removed(undo)
            self.assertTrue(restored)
            self.assertIsNone(error)
            self.assertIn("X-SECRET", (
                Path(tmp) / ad.SITE_LOGIN_DIRNAME / "x.com.txt"
            ).read_text(encoding="utf-8"))
            self.assertEqual(store.entries()[0]["site"], "x.com")

    def test_new_store_preserves_a_referenced_site_login_undo_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            undo, error = store.remove_with_undo("x.com")
            self.assertIsNone(error)
            backup = Path(tmp) / ad.SITE_LOGIN_DIRNAME / f".undo-{undo['token']}.txt"
            self.assertTrue(backup.exists())
            reopened = self._store(tmp)
            self.assertTrue(backup.exists())
            self.assertEqual(reopened.load_removed_undo()["token"], undo["token"])
            restored, error = reopened.restore_removed(reopened.load_removed_undo())
            self.assertTrue(restored)
            self.assertIsNone(error)
            self.assertIn(
                "X-SECRET",
                (Path(tmp) / ad.SITE_LOGIN_DIRNAME / "x.com.txt").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(reopened.entries()[0]["site"], "x.com")

    def test_new_store_removes_an_unreferenced_site_login_undo_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            undo, error = store.remove_with_undo("x.com")
            self.assertIsNone(error)
            orphan = Path(tmp) / ad.SITE_LOGIN_DIRNAME / (
                ".undo-" + "a" * 32 + ".txt"
            )
            orphan.write_text("orphan", encoding="utf-8")
            self.assertTrue(orphan.exists())
            reopened = self._store(tmp)
            self.assertTrue(
                (Path(tmp) / ad.SITE_LOGIN_DIRNAME / f".undo-{undo['token']}.txt").exists()
            )
            self.assertFalse(orphan.exists())
            self.assertEqual(reopened.load_removed_undo()["site"], "x.com")

    def test_export_skips_expired_cookies_and_unknown_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Clock is past the cookie's expiry.
            store = self._store(tmp, clock=lambda: 2_100_000_000)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            target = Path(tmp) / "per-download.txt"
            self.assertIsNone(
                store.export_jar_for("https://x.com/a/status/1", target),
                "an expired session must not be presented as a live sign-in",
            )
            self.assertFalse(target.exists())
            self.assertIsNone(store.export_jar_for("https://vimeo.com/1", target))

    def test_export_writes_a_scoped_per_download_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            target = Path(tmp) / "per-download.txt"
            written = store.export_jar_for("https://x.com/someone/status/1", target)
            self.assertTrue(written)
            body = Path(written).read_text(encoding="utf-8")
            self.assertIn("X-SECRET", body)
            self.assertNotIn("YT-SECRET", body)
            # The stored jar is never handed to yt-dlp directly: --cookies is a
            # write path, so concurrent downloads would race on it.
            self.assertNotEqual(
                Path(written).resolve(),
                (Path(tmp) / ad.SITE_LOGIN_DIRNAME / "x.com.txt").resolve(),
            )

    def test_site_key_lookup_requires_a_stored_jar(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            self.assertEqual(store.site_key_for_url("https://x.com/a"), "")
            store.import_netscape_text("x.com", self.MIXED_EXPORT)
            self.assertEqual(store.site_key_for_url("https://x.com/a"), "x.com")
            self.assertEqual(store.site_key_for_url("https://api.x.com/a"), "x.com")
            self.assertEqual(store.site_key_for_url("https://vimeo.com/1"), "")


class SiteLoginDownloadTests(unittest.TestCase):
    """A stored sign-in reaches yt-dlp for its own site and no other."""

    class _FakeProc:
        def __init__(self, lines, returncode=0):
            self.stdout = iter(lines)
            self.returncode = returncode
            self._waited = False

        def wait(self):
            self._waited = True
            return self.returncode

        def poll(self):
            return self.returncode if self._waited else None

        def terminate(self):
            pass

        def kill(self):
            pass

        def communicate(self, *_args, **_kwargs):
            self._waited = True
            return ('', '')

    def _run(self, url, *, seed_site=None, seed_credentials=None,
             request_cookies=None, video_password=None,
             impersonate_targets=None, native_source=None):
        captured = []
        live_jar = []
        # The cookie jar's owner-only ACL is applied by shelling out to
        # icacls through this very Popen, so a fake that swallows every
        # command silently breaks jar creation and the test then "proves"
        # cookies were not attached for the wrong reason.
        real_popen = ad.subprocess.Popen

        def popen(args, **kwargs):
            if args and str(args[0]).lower().endswith(('icacls', 'icacls.exe')):
                return real_popen(args, **kwargs)
            if '--ignore-config' not in args:
                return self._FakeProc([], 0)
            captured.append(list(args))
            # Read the jar here, while yt-dlp is notionally running. The
            # download's finally block unlinks it on exit, so a reader that
            # waits for the run to finish can only ever see "(cleaned)" and
            # cannot tell an empty jar from a correct one.
            if '--cookies' in args:
                jar = Path(args[list(args).index('--cookies') + 1])
                if jar.exists():
                    live_jar.append(jar.read_text(encoding='utf-8'))
            return self._FakeProc(['[download] Destination: clip.mp4'], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            if impersonate_targets is not None:
                # The real probe shells out to yt-dlp; the registry default is
                # gated on what it reports, so the test has to own the answer.
                manager._dependencies['probe_impersonate_targets'] = (
                    lambda *_a, **_k: list(impersonate_targets)
                )
            if native_source is not None:
                # A callable raises or returns; a dict is returned as-is. The
                # real resolver talks to the site, which the suite never does.
                manager._dependencies['resolve_native_source'] = (
                    native_source if callable(native_source)
                    else (lambda *_a, **_k: native_source)
                )
            if seed_site:
                manager.site_logins.import_netscape_text(
                    seed_site,
                    f".{seed_site}\tTRUE\t/\tTRUE\t2000000000\tauth\tSITE-SECRET",
                )
            if seed_credentials:
                manager.site_logins.save_credentials(
                    seed_credentials[0], seed_credentials[1], seed_credentials[2]
                )
            # Drive the production path: start_download schedules the worker,
            # which is where the jar is chosen and written. Faking the process
            # first keeps a real yt-dlp out of the unit suite.
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'probe_po_token_provider', return_value=None), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                dl_id, error = manager.start_download(
                    url=url,
                    cookies=request_cookies,
                    video_password=video_password,
                )
                self.assertIsNone(error, error)
                download = manager.downloads[dl_id]
                deadline = time.time() + 10
                while download.status not in ad.DOWNLOAD_TERMINAL_STATES and time.time() < deadline:
                    time.sleep(0.05)
            argv = captured[-1] if captured else []
            jar_body = live_jar[-1] if live_jar else ''
            if not jar_body and '--cookies' in argv:
                jar_path = Path(argv[argv.index('--cookies') + 1])
                jar_body = jar_path.read_text(encoding='utf-8') if jar_path.exists() else '(cleaned)'
            return argv, download, jar_body

    def test_stored_sign_in_is_attached_for_its_own_site(self):
        argv, download, _body = self._run(
            "https://x.com/someone/status/1", seed_site="x.com"
        )
        self.assertIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, 'x.com')

    def test_stored_sign_in_is_not_attached_to_another_site(self):
        argv, download, _body = self._run(
            "https://www.reddit.com/r/videos/comments/a/b/", seed_site="x.com"
        )
        self.assertNotIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, '')

    def test_stored_credentials_are_attached_without_being_kept_in_the_download(self):
        argv, download, _body = self._run(
            "https://vimeo.com/123",
            seed_credentials=("vimeo.com", "member@example.com", "PASSWORD-SECRET"),
        )
        self.assertEqual(
            argv[argv.index("--username") + 1], "member@example.com"
        )
        self.assertEqual(argv[argv.index("--password") + 1], "PASSWORD-SECRET")
        self.assertIsNone(download._credentials)
        self.assertNotIn("PASSWORD-SECRET", json.dumps(download.to_dict()))

    def test_video_password_reaches_one_link_and_is_not_serialized(self):
        argv, download, _body = self._run(
            "https://vimeo.com/123", video_password="VIDEO-SECRET"
        )
        self.assertEqual(argv[argv.index("--video-password") + 1], "VIDEO-SECRET")
        self.assertEqual(download._video_password, "")
        self.assertNotIn("VIDEO-SECRET", json.dumps(download.to_dict()))

    def test_video_password_is_rejected_for_a_playlist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir}), FakeHistory()
            )
            dl_id, error = manager.start_download(
                "https://www.youtube.com/playlist?list=fixture",
                video_password="VIDEO-SECRET",
            )
        self.assertIsNone(dl_id)
        self.assertIn("single-link", error)

    def test_no_stored_sign_in_downloads_signed_out_instead_of_failing(self):
        argv, download, _body = self._run("https://vimeo.com/123")
        self.assertNotIn('--cookies', argv)
        self.assertEqual(download.status, 'complete',
                         "a missing sign-in is not a cookie-jar failure")

    def test_youtube_request_cookies_never_follow_a_url_off_site(self):
        # A token holder posting a non-YouTube URL with YouTube cookies must
        # not cause those cookies to be sent anywhere. The bridge is scoped to
        # the download's own site now, so the mismatch is caught one step
        # earlier than it used to be: the cookies are dropped before a jar is
        # written, rather than written into a jar that argv then refuses.
        argv, download, _body = self._run(
            "https://vimeo.com/123",
            request_cookies=[{
                "name": "SID", "value": "YT-SECRET", "domain": ".youtube.com",
                "path": "/", "secure": True, "expirationDate": 2_000_000_000,
            }],
        )
        self.assertNotIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, '')
        self.assertIsNone(
            download.cookies_file,
            "an off-site cookie must not reach disk at all",
        )

    def test_request_cookies_are_attached_for_a_site_that_is_not_youtube(self):
        # The whole point of the widened bridge. Before it, cookies posted for
        # any site other than YouTube were filtered out on the way in, so the
        # jar came back empty and the download ran signed out with nothing
        # said about it.
        argv, download, body = self._run(
            "https://www.twitch.tv/videos/123",
            request_cookies=[{
                "name": "auth-token", "value": "TWITCH-SECRET",
                "domain": ".twitch.tv", "path": "/", "secure": True,
                "expirationDate": 2_000_000_000,
            }],
        )
        self.assertIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, 'twitch.tv')
        self.assertIn('TWITCH-SECRET', body)

    def test_request_cookies_are_filtered_to_the_download_site(self):
        # A jar for one site must not become a general cookie dump because the
        # caller sent more than it needed.
        argv, download, body = self._run(
            "https://www.twitch.tv/videos/123",
            request_cookies=[
                {"name": "auth-token", "value": "TWITCH-SECRET",
                 "domain": ".twitch.tv", "path": "/", "secure": True,
                 "expirationDate": 2_000_000_000},
                {"name": "SID", "value": "YT-SECRET", "domain": ".youtube.com",
                 "path": "/", "secure": True, "expirationDate": 2_000_000_000},
            ],
        )
        self.assertIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, 'twitch.tv')
        self.assertIn('TWITCH-SECRET', body)
        self.assertNotIn(
            'YT-SECRET', body,
            "a Twitch jar must not carry a YouTube session",
        )

    def test_youtube_request_cookies_keep_the_google_account_session(self):
        # YouTube's session lives on Google's account domains as well as its
        # own. Scoping the jar to the registrable domain alone would silently
        # sign the user out, which is the regression this pins.
        argv, download, body = self._run(
            "https://www.youtube.com/watch?v=scoped",
            request_cookies=[
                {"name": "SID", "value": "YT-SECRET", "domain": ".youtube.com",
                 "path": "/", "secure": True, "expirationDate": 2_000_000_000},
                {"name": "SAPISID", "value": "GOOGLE-SECRET",
                 "domain": ".google.com", "path": "/", "secure": True,
                 "expirationDate": 2_000_000_000},
            ],
        )
        self.assertIn('--cookies', argv)
        self.assertEqual(download.cookies_scope, 'youtube.com')
        self.assertIn('YT-SECRET', body)
        self.assertIn('GOOGLE-SECRET', body)

    def test_a_fingerprint_checked_site_gets_impersonation_in_the_real_argv(self):
        # The unit builder is covered in test_sites; this proves the argv the
        # subprocess actually receives carries it, which is where the wiring
        # between the registry and the manager could silently be missing.
        # Real target names, copied from the installed binary's own
        # --list-impersonate-targets output. The first version of this test
        # invented a bare "chrome" entry, which no yt-dlp build reports, and
        # so it passed against a default that never fired in production.
        argv, _download, _body = self._run(
            "https://kick.com/somechannel/videos/abc",
            impersonate_targets=["Chrome-99", "Chrome-133", "Chrome-136", "Safari-18.0"],
        )
        self.assertIn("--impersonate", argv)
        self.assertEqual(
            argv[argv.index("--impersonate") + 1], "Chrome-136",
            "the newest target in the family wins, not the first or the oldest",
        )

    def test_impersonation_is_dropped_when_the_family_is_absent(self):
        # Safari-only build: asking for the chrome family must emit nothing
        # rather than a target the binary would raise on.
        argv, _download, _body = self._run(
            "https://kick.com/somechannel/videos/abc",
            impersonate_targets=["Safari-18.0"],
        )
        self.assertNotIn("--impersonate", argv)

    def test_impersonation_is_dropped_when_the_binary_cannot_do_it(self):
        # An unknown --impersonate target raises inside yt-dlp and kills the
        # download, so a site asking for one the binary lacks must go without.
        argv, _download, _body = self._run(
            "https://kick.com/somechannel/videos/abc",
            impersonate_targets=[],
        )
        self.assertNotIn("--impersonate", argv)

    def test_a_site_that_needs_a_referer_gets_its_own_origin(self):
        argv, _download, _body = self._run("https://vimeo.com/123")
        self.assertIn("--referer", argv)
        self.assertEqual(argv[argv.index("--referer") + 1], "https://vimeo.com/")

    def test_a_site_with_no_registry_row_gets_no_extra_argv(self):
        argv, _download, _body = self._run("https://example.com/watch/1")
        for flag in ("--impersonate", "--referer", "--extractor-args"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv)

    _KICK_VOD = "https://kick.com/loulz/videos/01a04eaf-79f0-71f9-ad3e-342286927538"
    _KICK_MANIFEST = "https://web.kick.com/api/v1/stream/manifest.m3u8?init=SECRET.JWT.SIG"

    def test_a_native_source_replaces_the_url_ytdlp_is_given(self):
        # The whole point of the resolver: yt-dlp is pointed at the manifest,
        # with the header the delivery host insists on and the real title, and
        # never sees the page URL its own extractor 404s on.
        argv, download, _body = self._run(
            self._KICK_VOD,
            native_source={
                "site": "kick", "url": self._KICK_MANIFEST, "title": "Fight night",
                "duration": 30116, "headers": {"User-Agent": "UA/kick"},
            },
        )
        self.assertEqual(argv[-1], self._KICK_MANIFEST)
        self.assertNotIn(self._KICK_VOD, argv)
        self.assertEqual(argv[argv.index("--user-agent") + 1], "UA/kick")
        self.assertEqual(argv[argv.index("--parse-metadata") + 1], "Fight night:(?P<title>.+)")
        self.assertEqual(download.status, "complete")
        # The record keeps the page: that is what history, retry and the log show.
        self.assertEqual(download.url, self._KICK_VOD)
        self.assertEqual(download.title, "Fight night")

    def test_the_visible_command_never_carries_the_session_token(self):
        _argv, download, _body = self._run(
            self._KICK_VOD,
            native_source={"site": "kick", "url": self._KICK_MANIFEST, "title": "t",
                           "duration": 1, "headers": {}},
        )
        shown = " ".join(download.command_args)
        self.assertNotIn("SECRET.JWT.SIG", shown)
        self.assertIn("init=[redacted]", shown)

    def test_a_site_with_no_resolver_is_untouched(self):
        argv, download, _body = self._run(
            "https://vimeo.com/123", native_source=None,
        )
        self.assertEqual(argv[-1], "https://vimeo.com/123")
        self.assertNotIn("--parse-metadata", argv)
        self.assertEqual(download.status, "complete")

    def test_a_refused_native_source_fails_with_its_own_reason(self):
        from native_sources import NativeSourceError

        def refuse(*_a, **_k):
            raise NativeSourceError("Kick will not play this video (Forbidden).")

        argv, download, _body = self._run(self._KICK_VOD, native_source=refuse)
        self.assertEqual(argv, [], "yt-dlp must not be spawned for a refusal")
        self.assertEqual(download.status, "failed")
        self.assertEqual(download.error_code, "source-unavailable")
        self.assertIn("Forbidden", download.error)
        self.assertTrue(download.error_advice)

    def test_an_unreachable_native_source_is_retryable(self):
        from native_sources import NativeSourceError

        def unreachable(*_a, **_k):
            raise NativeSourceError("Kick could not be reached", code="network-unreachable")

        _argv, download, _body = self._run(self._KICK_VOD, native_source=unreachable)
        self.assertEqual(download.status, "failed")
        self.assertEqual(download.error_code, "network-unreachable")
        self.assertIn(download.error_code, ad.DOWNLOAD_RETRYABLE_ERROR_CODES)

    def test_a_refusal_still_tears_down_the_cookie_jar(self):
        from native_sources import NativeSourceError

        def refuse(*_a, **_k):
            raise NativeSourceError("no")

        _argv, download, _body = self._run(
            self._KICK_VOD, seed_site="kick.com", native_source=refuse,
        )
        self.assertEqual(download.status, "failed")
        self.assertFalse(
            download.cookies_file and Path(download.cookies_file).exists(),
            "a jar exported for the run must not outlive a pre-spawn refusal",
        )

    def test_stored_sign_in_probe_is_scoped_bounded_and_cleaned(self):
        captured = {}

        class StoredLogin:
            def export_jar_for_site(self, url, target_path):
                captured['site_url'] = url
                captured['jar_path'] = Path(target_path)
                captured['jar_path'].write_text(
                    '# Netscape HTTP Cookie File\n'
                    '.x.com\tTRUE\t/\tTRUE\t2000000000\tauth\tSECRET\n',
                    encoding='utf-8',
                )
                return str(captured['jar_path']), 'x.com'

        class ProbeProc:
            returncode = 0

            def communicate(self, timeout=None):
                captured['timeout'] = timeout
                return '{}', ''

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(FakeConfig({'DownloadPath': tmpdir}), FakeHistory())
            manager.site_logins = StoredLogin()
            manager._dependencies['YTDLP_PATH'] = lambda: 'yt-dlp.exe'

            def spawn_probe(args, **_kwargs):
                captured['args'] = list(args)
                return ProbeProc()

            manager._dependencies['spawn_ytdlp'] = spawn_probe

            result, error = manager.test_site_login('https://x.com/video', timeout=99)

        self.assertIsNone(error, error)
        self.assertTrue(result['ok'])
        self.assertEqual(captured['site_url'], 'https://x.com/')
        self.assertEqual(captured['timeout'], ad.SITE_LOGIN_TEST_TIMEOUT_SECONDS)
        args = captured['args']
        self.assertIn('--skip-download', args)
        self.assertIn('--dump-single-json', args)
        self.assertEqual(args[-1], 'https://x.com/')
        self.assertFalse(captured['jar_path'].exists())


class ProbeIdentityTests(unittest.TestCase):
    """Metadata probes use the same site, proxy and browser identity as runs."""

    class _StoredLogin:
        def export_jar_for_site(self, url, target_path):
            key = "youtube.com" if "youtube" in str(url) else "x.com"
            target_path = Path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                "# Netscape HTTP Cookie File\n"
                f".{key}\tTRUE\t/\tTRUE\t2000000000\tauth\tPROBE\n",
                encoding="utf-8",
            )
            return str(target_path), key

    class _FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            self.timeout = timeout
            return json.dumps({
                "id": "fixture",
                "title": "Fixture",
                "formats": [],
                "entries": [{"id": "video-1", "title": "One"}],
                "playlist_count": 1,
            }), ""

    def _manager(self, root):
        manager = ad.DownloadManager(
            FakeConfig({
                "Proxy": "https://proxy.example:8443",
                "ImpersonateTarget": "Chrome-136",
            }),
            FakeHistory(),
        )
        manager._dependencies["INSTALL_DIR"] = lambda: Path(root)
        manager._dependencies["probe_impersonate_targets"] = lambda: ["Chrome-136"]
        manager.site_logins = self._StoredLogin()
        return manager

    def test_format_probe_carries_scoped_login_proxy_and_impersonation(self):
        captured = []
        with tempfile.TemporaryDirectory() as root:
            manager = self._manager(root)
            with mock.patch.object(ad, "spawn_ytdlp", side_effect=lambda args, **_kwargs: captured.append(list(args)) or self._FakeProc()), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "probe_javascript_runtime", return_value={}):
                result, error = manager.list_formats("https://x.com/video", timeout=7)

            self.assertIsNone(error)
            self.assertEqual(result["id"], "fixture")
            args = captured[0]
            self.assertEqual(args[args.index("--proxy") + 1], "https://proxy.example:8443")
            self.assertEqual(args[args.index("--impersonate") + 1], "Chrome-136")
            cookie_path = Path(args[args.index("--cookies") + 1])
            self.assertFalse(cookie_path.exists(), "probe jars must be transient")

    def test_playlist_and_subscription_probes_share_identity_builder(self):
        captured = []
        with tempfile.TemporaryDirectory() as root:
            manager = self._manager(root)
            with mock.patch.object(ad, "spawn_ytdlp", side_effect=lambda args, **_kwargs: captured.append(list(args)) or self._FakeProc()), \
                 mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
                 mock.patch.object(ad, "probe_javascript_runtime", return_value={}):
                result, error = manager.preview_playlist(
                    "https://www.youtube.com/playlist?list=fixture",
                    timeout=7,
                )
                self.assertIsNone(error)
                self.assertEqual(result["id"], "fixture")

                result, error = ad.probe_subscription_uploads(
                    "https://www.youtube.com/channel/fixture",
                    timeout=7,
                    identity_builder=manager._build_probe_identity_args,
                )
                self.assertIsNone(error)
                self.assertEqual(result[0]["id"], "video-1")

            self.assertEqual(len(captured), 2)
            for args in captured:
                self.assertIn("--proxy", args)
                self.assertIn("--cookies", args)
                self.assertIn("--impersonate", args)


class SkippedDownloadSurfaceTests(unittest.TestCase):
    """A terminal status that renders nowhere is the failure `skipped` exists
    to prevent, so the GUI bucket is pinned against the shared constant."""

    def test_skipped_download_renders_with_its_reason_and_a_retry(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-skip-surface-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

app_instance = QApplication(["skip-surface"])
app.MainWindow._start_instance_command_listener = lambda self: None
app.MainWindow._stop_instance_command_listener = lambda self: None
app.MainWindow._start_readiness_probe = lambda self: None
app.MainWindow._refresh_tools_status = lambda self: None

config = app.Config()
config.update({
    "CloseToTray": False,
    "StartMinimized": False,
    "DownloadPath": temp_dir,
    "AudioDownloadPath": temp_dir,
})
manager = app.DownloadManager(config, app.History())
window = app.MainWindow(config, manager, app.History())
window._animate_page = lambda: None
window.update_timer.stop()
window.cleanup_timer.stop()
window.tools_status_timer.stop()
window.show()

skipped = app.Download("dl_skip", "https://archive.org/details/x", output_dir=temp_dir)
skipped.status = "skipped"
skipped.title = "Oversized archive item"
skipped.error = "Nothing was downloaded: every available format is larger than the 25 MB size limit."
skipped.mark_terminal()
manager.downloads["dl_skip"] = skipped

window._nav_click("Download")
window._downloads_signature = None
window._update_ui()
app_instance.processEvents()

visible = " | ".join(
    label.text() for label in window.findChildren(QLabel)
    if label.isVisible() and label.text()
)
assert "Oversized archive item" in visible, "skipped download must be listed"
assert "25 MB size limit" in visible, "the reason must be shown"

buttons = [
    button.text() for button in window.findChildren(QPushButton)
    if button.isVisible() and button.text()
]
assert "Retry" in buttons, "a skipped download must offer a retry"

assert "skipped" in app.DOWNLOAD_TERMINAL_STATES
window.close()
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_gui_buckets_cover_every_terminal_state(self):
        script = r'''
import os
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-terminal-buckets-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtWidgets import QApplication, QLabel

app_instance = QApplication(["terminal-buckets"])
app.MainWindow._start_instance_command_listener = lambda self: None
app.MainWindow._stop_instance_command_listener = lambda self: None
app.MainWindow._start_readiness_probe = lambda self: None
app.MainWindow._refresh_tools_status = lambda self: None

config = app.Config()
config.update({
    "CloseToTray": False,
    "StartMinimized": False,
    "NotifyOnComplete": False,
    "DownloadPath": temp_dir,
    "AudioDownloadPath": temp_dir,
})
manager = app.DownloadManager(config, app.History())
window = app.MainWindow(config, manager, app.History())
window._animate_page = lambda: None
window.update_timer.stop()
window.cleanup_timer.stop()
window.tools_status_timer.stop()
window.show()

for index, status in enumerate(sorted(app.DOWNLOAD_TERMINAL_STATES)):
    download = app.Download(
        f"dl_{status}",
        f"https://example.com/{status}",
        output_dir=temp_dir,
    )
    download.status = status
    download.title = f"Terminal bucket {status}"
    download.error = f"Fixture detail for {status}"
    download.start_time += index
    download.mark_terminal()
    manager.downloads[download.id] = download

window._nav_click("Download")
window._downloads_signature = None
window._update_ui()
app_instance.processEvents()

for status in app.DOWNLOAD_TERMINAL_STATES:
    key = ("download", f"dl_{status}")
    assert key in window._download_widgets, f"{status} did not enter Recent activity"
    card = window._download_widgets[key]
    card_copy = " | ".join(
        label.text() for label in card.findChildren(QLabel) if label.text()
    )
    assert f"Terminal bucket {status}" in card_copy, f"{status} card is not visible"
    assert card.isVisible(), f"{status} card is hidden"

recent_heading = window._download_widgets.get(("section", "recent"))
assert recent_heading is not None, "Recent activity heading was not rendered"
assert recent_heading.text() == "Recent activity"
layout = window.downloads_list_layout
recent_index = layout.indexOf(recent_heading)
spacer_index = layout.indexOf(window._download_widgets[("spacer",)])
assert recent_index >= 0 and spacer_index > recent_index
for status in app.DOWNLOAD_TERMINAL_STATES:
    card = window._download_widgets[("download", f"dl_{status}")]
    card_index = layout.indexOf(card)
    assert recent_index < card_index < spacer_index, (
        f"{status} card is not placed under Recent activity"
    )

window.close()
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_skipped_download_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            download = ad.Download("dl_skip", "https://archive.org/details/x",
                                   output_dir=tmpdir)
            download.status = "skipped"
            download.error = "Nothing was downloaded: …size limit."
            download.mark_terminal()
            manager.downloads["dl_skip"] = download

            ok, error = manager.retry("dl_skip")
            self.assertTrue(ok, error)
        self.assertEqual(manager.downloads["dl_skip"].status, "pending")
        self.assertEqual(manager.downloads["dl_skip"].error, "")

    def test_non_terminal_downloads_still_cannot_be_retried(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            download = ad.Download("dl_pending", "https://vimeo.com/1", output_dir=tmpdir)
            download.status = "pending"
            manager.downloads["dl_pending"] = download

            ok, error = manager.retry("dl_pending")
            self.assertFalse(ok)
            self.assertIn("retried", error)


class StoreErrorSurfaceTests(unittest.TestCase):
    """Unreadable stores must never masquerade as empty stores."""

    def test_subscription_and_sign_in_store_errors_offer_log_recovery(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-store-error-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

class RaisingSubscriptions:
    def snapshot(self):
        raise RuntimeError("subscription archive unreadable")

    def stop(self):
        pass

class RaisingSiteLogins:
    def entries(self):
        raise RuntimeError("sign-in index unreadable")

qt_app = QApplication(["store-error-pin"])
app.MainWindow._start_instance_command_listener = lambda self: None
app.MainWindow._stop_instance_command_listener = lambda self: None
app.MainWindow._start_readiness_probe = lambda self: None
app.MainWindow._refresh_tools_status = lambda self: None

config = app.Config()
config.update({
    "CloseToTray": False,
    "StartMinimized": False,
    "DownloadPath": temp_dir,
    "AudioDownloadPath": temp_dir,
})
manager = app.DownloadManager(config, app.History())
manager.site_logins = RaisingSiteLogins()
window = app.MainWindow(
    config, manager, app.History(), subscriptions=RaisingSubscriptions()
)
window._animate_page = lambda: None
window.update_timer.stop()
window.cleanup_timer.stop()
window.tools_status_timer.stop()
window.show()
qt_app.processEvents()

def recovery_buttons(container):
    return [
        button for button in container.findChildren(QPushButton)
        if button.isVisible() and button.text() == "Reveal log file"
    ]

window._nav_click("Subscriptions")
qt_app.processEvents()
assert "subscription archive unreadable" in window.subscription_status.text(), window.subscription_status.text()
assert recovery_buttons(window.subscription_scroll), [
    button.text() for button in window.subscription_scroll.findChildren(QPushButton)
]
subscription_text = " | ".join(
    label.text() for label in window.subscription_scroll.findChildren(QLabel)
    if label.isVisible() and label.text()
)
assert "No scheduled subscriptions" not in subscription_text, subscription_text

window._nav_click("Sign-ins")
qt_app.processEvents()
assert "sign-in index unreadable" in window.site_login_status.text(), window.site_login_status.text()
assert recovery_buttons(window.site_login_scroll), [
    button.text() for button in window.site_login_scroll.findChildren(QPushButton)
]
visible_text = " | ".join(
    label.text() for label in window.site_login_scroll.findChildren(QLabel)
    if label.isVisible() and label.text()
)
assert "No stored sign-ins" not in visible_text, visible_text
window.tray.hide()
window._force_exit = True
window.close()
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class RevealInExplorerTests(unittest.TestCase):
    """Showing a finished file selects it, and the quoting is exact."""

    def test_the_path_is_quoted_but_the_switch_is_not(self):
        # Measured against the real shell: `explorer.exe "/select,C:\dir\My
        # File.mp4"` — one fully-quoted argument, which is what building this
        # as a list and letting Python quote it produces — opened the user's
        # Documents folder. The quotes have to wrap the path alone.
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "Astra reveal probe.mp4"
            target.write_bytes(b"\0" * 16)
            command = ad.build_reveal_command(str(target))
        self.assertIsInstance(command, str)
        self.assertTrue(command.startswith("explorer.exe /select,\""), command)
        self.assertTrue(command.endswith("\""), command)
        self.assertNotIn("\"/select", command)

    def test_a_path_with_spaces_survives_intact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "two words.mp4"
            target.write_bytes(b"\0" * 16)
            command = ad.build_reveal_command(str(target))
            self.assertIn(f'/select,"{target.resolve()}"', command)

    def test_nothing_is_revealed_for_a_file_that_is_gone(self):
        # A history row outlives the file it names; asking Explorer to select
        # a path that no longer exists opens an unrelated folder.
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(
                ad.build_reveal_command(str(Path(tmpdir) / "deleted.mp4")))
        self.assertIsNone(ad.build_reveal_command(""))
        self.assertIsNone(ad.build_reveal_command(None))

    def test_a_directory_is_not_revealed_as_a_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(ad.build_reveal_command(tmpdir))

    def test_a_quote_in_the_name_is_refused_rather_than_escaped(self):
        with mock.patch.object(ad.Path, "is_file", lambda _self: True), \
             mock.patch.object(ad.Path, "resolve",
                               lambda _self: Path('C:/x/we"ird.mp4')):
            self.assertIsNone(ad.build_reveal_command("anything"))

    def test_the_window_reveals_rather_than_opening_the_folder(self):
        gui = gui_module_for_tests()
        spawned = []
        window = types.SimpleNamespace(
            logs=[],
            _dependencies={
                "build_reveal_command": lambda path: f'explorer.exe /select,"{path}"',
                "spawn_detached": lambda command: spawned.append(command),
            },
        )
        window._append_log = window.logs.append
        window._open_folder = lambda: spawned.append("FOLDER")
        gui.MainWindowCore._show_download_location(window, r"C:\Videos\clip.mp4")
        self.assertEqual(spawned, [r'explorer.exe /select,"C:\Videos\clip.mp4"'])

    def test_a_shell_that_refuses_select_still_opens_the_folder(self):
        gui = gui_module_for_tests()
        opened = []
        window = types.SimpleNamespace(
            logs=[],
            _dependencies={
                "build_reveal_command": lambda _path: "explorer.exe /select,x",
                "spawn_detached": lambda _command: (_ for _ in ()).throw(
                    OSError("no shell")),
            },
        )
        window._append_log = window.logs.append
        window._open_folder = lambda: opened.append("FOLDER")
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "clip.mp4"
            target.write_bytes(b"\0")
            with mock.patch.object(gui.os, "startfile",
                                   lambda path: opened.append(path)):
                gui.MainWindowCore._show_download_location(window, str(target))
        self.assertEqual(opened, [tmpdir])
        self.assertTrue(any("Explorer" in line for line in window.logs))


class TaskbarIdentityTests(unittest.TestCase):
    """The process claims a stable taskbar identity."""

    def test_the_identity_carries_no_version(self):
        # Windows keys a pinned shortcut on this string. A version in it
        # would orphan the user's pin at every release.
        self.assertNotIn(ad.APP_VERSION, ad.APP_USER_MODEL_ID)
        self.assertRegex(ad.APP_USER_MODEL_ID, r"^[A-Za-z0-9]+\.[A-Za-z0-9]+$")

    def test_a_shell_that_refuses_the_id_does_not_stop_the_app(self):
        import ctypes

        logged = []
        # E_INVALIDARG. The call succeeds at the C level and reports failure
        # through the HRESULT, which is the case a bare try/except misses.
        with mock.patch.object(ad, "write_persistent_log", logged.append), \
             mock.patch.object(ctypes.windll.shell32,
                               "SetCurrentProcessExplicitAppUserModelID",
                               lambda _app_id: -2147024809):
            self.assertFalse(ad.set_app_user_model_id())
        self.assertTrue(logged)
        self.assertIn("refused", logged[0])

    def test_a_host_without_the_shell_export_does_not_stop_the_app(self):
        import ctypes

        def explode(_app_id):
            raise AttributeError("no such export")

        logged = []
        with mock.patch.object(ad, "write_persistent_log", logged.append), \
             mock.patch.object(ctypes.windll.shell32,
                               "SetCurrentProcessExplicitAppUserModelID",
                               explode):
            self.assertFalse(ad.set_app_user_model_id())
        self.assertTrue(logged)

    def test_the_real_shell_accepts_it(self):
        self.assertTrue(ad.set_app_user_model_id())


class TaskbarProgressSummaryTests(unittest.TestCase):
    """Many downloads reduce to the one bar Windows gives a button."""

    RUNNING = ("downloading", "processing")
    TERMINAL = ("complete", "failed", "cancelled", "skipped")

    def _summarize(self, *downloads):
        return ad.summarize_taskbar_progress(
            [types.SimpleNamespace(**d) for d in downloads],
            self.RUNNING, self.TERMINAL,
        )

    def test_an_idle_queue_shows_no_bar(self):
        # An empty bar over an idle app is worse than no bar.
        self.assertEqual(
            self._summarize({"status": "complete", "progress": 100}),
            (ad.TASKBAR_PROGRESS_NONE, 0, 0),
        )
        self.assertEqual(self._summarize(), (ad.TASKBAR_PROGRESS_NONE, 0, 0))

    def test_one_download_reports_its_own_percentage(self):
        state, done, total = self._summarize({"status": "downloading", "progress": 42})
        self.assertEqual((state, done, total), (ad.TASKBAR_PROGRESS_NORMAL, 42, 100))

    def test_several_downloads_average_rather_than_counting_finished_ones(self):
        # Five jobs at 20% is 20% of the work, not "none of five done".
        state, done, total = self._summarize(
            *[{"status": "downloading", "progress": 20}] * 5
        )
        self.assertEqual(state, ad.TASKBAR_PROGRESS_NORMAL)
        self.assertEqual((done, total), (100, 500))

    def test_work_with_no_progress_yet_is_indeterminate(self):
        # Before the first progress line there is nothing to show but the
        # fact that something is happening.
        self.assertEqual(
            self._summarize({"status": "downloading", "progress": 0}),
            (ad.TASKBAR_PROGRESS_INDETERMINATE, 0, 100),
        )

    def test_a_past_failure_does_not_colour_a_running_queue(self):
        state, _done, _total = self._summarize(
            {"status": "failed", "progress": 0},
            {"status": "downloading", "progress": 50},
        )
        self.assertEqual(state, ad.TASKBAR_PROGRESS_NORMAL)

    def test_pending_work_is_not_counted_as_running(self):
        state, done, total = self._summarize(
            {"status": "downloading", "progress": 50},
            {"status": "pending", "progress": 0},
        )
        self.assertEqual((state, done, total), (ad.TASKBAR_PROGRESS_NORMAL, 50, 100))

    def test_a_nonsense_progress_value_cannot_break_the_bar(self):
        for value in (None, "", "abc", -20, 500, float("nan")):
            with self.subTest(value=value):
                _state, done, total = self._summarize(
                    {"status": "downloading", "progress": value})
                self.assertGreaterEqual(done, 0)
                self.assertLessEqual(done, total)

    def test_an_unchanged_value_is_not_pushed_to_the_shell_twice(self):
        # The UI tick runs twice a second and the shell does not need to
        # hear the same number again.
        applied = []
        taskbar = ad.TaskbarProgress(logger=lambda _m: None)
        taskbar._taskbar = object()
        taskbar._call = lambda *args, **kwargs: applied.append(args)
        taskbar.apply(1234, ad.TASKBAR_PROGRESS_NORMAL, 40, 100)
        first = len(applied)
        taskbar.apply(1234, ad.TASKBAR_PROGRESS_NORMAL, 40, 100)
        self.assertEqual(len(applied), first)
        taskbar.apply(1234, ad.TASKBAR_PROGRESS_NORMAL, 41, 100)
        self.assertGreater(len(applied), first)

    def test_an_unavailable_shell_interface_is_not_retried_forever(self):
        logged = []
        taskbar = ad.TaskbarProgress(logger=logged.append)
        with mock.patch.object(ad, "_guid_from_string",
                               side_effect=OSError("no ole32")):
            self.assertFalse(taskbar.apply(99, ad.TASKBAR_PROGRESS_NORMAL, 1, 2))
            self.assertFalse(taskbar.apply(99, ad.TASKBAR_PROGRESS_NORMAL, 3, 4))
        self.assertEqual(len(logged), 1, "the failure should be reported once")

    def test_no_window_means_no_call(self):
        taskbar = ad.TaskbarProgress(logger=lambda _m: None)
        self.assertFalse(taskbar.apply(0, ad.TASKBAR_PROGRESS_NORMAL, 1, 2))


class SubtitleRequestTests(unittest.TestCase):
    """Which subtitle tracks are asked for, and what happens to them."""

    def _config(self, **overrides):
        config = ad.sanitize_config({"EmbedSubs": True})
        config["SubtitleSleepSeconds"] = 0
        config.update(overrides)
        return config

    # -- The vocabulary the two modules share -----------------------------

    def test_config_and_argv_agree_on_the_modes(self):
        # config.py declares what a user may store; download.py declares what
        # each stored value compiles to. A value in one and not the other is
        # either an unreachable setting or a KeyError at argv time.
        self.assertEqual(
            set(ad.SUBTITLE_MODES),
            set(ad.SUBTITLE_WRITE_FLAGS),
        )

    def test_config_and_argv_agree_on_the_formats(self):
        self.assertEqual(
            {value for value in ad.SUBTITLE_FORMATS if value},
            set(ad.SUBTITLE_CONVERT_FORMATS),
        )

    # -- Track selection --------------------------------------------------

    def test_prefer_manual_sends_both_flags(self):
        # Measured against the installed binary: both flags do NOT produce two
        # files for one language. yt-dlp merges the catalogues per language
        # and the creator's track wins, so this IS prefer-manual-else-auto.
        args = ad.build_subtitle_args(
            self._config(SubtitleMode="prefer-manual"))
        self.assertIn("--write-subs", args)
        self.assertIn("--write-auto-subs", args)

    def test_creator_only_never_asks_for_the_machine_transcript(self):
        args = ad.build_subtitle_args(
            self._config(SubtitleMode="manual"))
        self.assertIn("--write-subs", args)
        self.assertNotIn("--write-auto-subs", args)

    def test_auto_only_never_asks_for_the_creator_track(self):
        args = ad.build_subtitle_args(
            self._config(SubtitleMode="auto"))
        self.assertIn("--write-auto-subs", args)
        self.assertNotIn("--write-subs", args)

    def test_an_unknown_mode_falls_back_to_the_shipped_behaviour(self):
        # A config hand-edited to a mode a later version removed must not
        # silently stop fetching subtitles.
        args = ad.build_subtitle_args(
            self._config(SubtitleMode="whatever-this-is"))
        self.assertIn("--write-subs", args)
        self.assertIn("--write-auto-subs", args)

    # -- The gate ---------------------------------------------------------

    def test_subtitles_off_sends_nothing(self):
        self.assertEqual(
            ad.build_subtitle_args(
                ad.sanitize_config({"EmbedSubs": False})),
            [],
        )

    def test_a_subtitles_only_job_ignores_the_embed_switch(self):
        # Embedding is the one thing it cannot do, so gating it on the embed
        # checkbox would make the download type silently do nothing.
        args = ad.build_subtitle_args(
            ad.sanitize_config({"EmbedSubs": False}), subtitles_only=True)
        self.assertIn("--write-subs", args)
        self.assertNotIn("--embed-subs", args)

    def test_a_normal_job_still_embeds(self):
        args = ad.build_subtitle_args(self._config())
        self.assertIn("--embed-subs", args)

    # -- Languages and format ---------------------------------------------

    def test_languages_reach_the_argv(self):
        args = ad.build_subtitle_args(
            self._config(SubLangs="en,es,zh-Hans"))
        self.assertIn("--sub-langs", args)
        self.assertEqual(args[args.index("--sub-langs") + 1], "en,es,zh-Hans")

    def test_all_languages_use_the_live_chat_exclusion_idiom(self):
        args = ad.build_subtitle_args(
            self._config(SubLangs="all,live_chat"))
        self.assertEqual(
            args[args.index("--sub-langs") + 1], "all,-live_chat"
        )

    def test_subtitle_request_delay_is_bounded_and_optional(self):
        delayed = ad.build_subtitle_args(
            self._config(SubtitleSleepSeconds=1.25))
        self.assertEqual(
            delayed[delayed.index("--sleep-subtitles") + 1], "1.25"
        )
        self.assertNotIn(
            "--sleep-subtitles",
            ad.build_subtitle_args(self._config(SubtitleSleepSeconds=0)),
        )

    def test_a_language_string_cannot_smuggle_an_argument(self):
        args = ad.build_subtitle_args(
            self._config(SubLangs="en --exec=calc"))
        self.assertEqual(args[args.index("--sub-langs") + 1], "en--execcalc")

    def test_a_chosen_format_is_converted(self):
        args = ad.build_subtitle_args(
            self._config(SubtitleFormat="srt"))
        self.assertIn("--convert-subs", args)
        self.assertEqual(args[args.index("--convert-subs") + 1], "srt")

    def test_no_format_leaves_the_site_format_alone(self):
        self.assertNotIn(
            "--convert-subs",
            ad.build_subtitle_args(self._config(SubtitleFormat="")),
        )

    def test_an_unknown_format_is_dropped_rather_than_passed(self):
        for value in ("exe", "; rm -rf /", "--exec"):
            with self.subTest(value=value):
                self.assertNotIn(
                    "--convert-subs",
                    ad.build_subtitle_args(
                        self._config(SubtitleFormat=value)),
                )

    def test_the_stored_values_are_shape_checked(self):
        self.assertEqual(ad.normalize_subtitle_mode("manual"), "manual")
        self.assertEqual(ad.normalize_subtitle_mode("nonsense"), "prefer-manual")
        self.assertEqual(ad.normalize_subtitle_format("SRT"), "srt")
        self.assertEqual(ad.normalize_subtitle_format("../../etc"), "")


class SubtitlesOnlyJobTests(unittest.TestCase):
    """A subtitles-only job skips the media and still names its output."""

    class _Download:
        def __init__(self, subtitles_only=True):
            self.subtitles_only = subtitles_only
            self.filename = ""

    def setUp(self):
        self.addCleanup(ad.reset_deno_runtime_cache)
        self.addCleanup(ad.reset_ffmpeg_capabilities_cache)
        self.addCleanup(ad.reset_po_token_provider_cache)

    def _argv(self, overrides, subtitles_only=True):
        """The real argv, captured by running the real download path."""
        captured = []

        class Proc:
            returncode = 0
            stdout = io.StringIO("")

            def __init__(self, args, **_kwargs):
                captured.append(list(args))

            def wait(self, timeout=None):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                # reason: satisfy the API the cancel path expects
                pass

            def kill(self):
                # reason: same as terminate
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            settings.update(overrides)
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            download = ad.Download("dl_subs", "https://example.com/video",
                                   output_dir=tmpdir,
                                   subtitles_only=subtitles_only)
            download.status = "queued"
            with mock.patch.object(ad.subprocess, "Popen", Proc),                  mock.patch.object(ad, "probe_po_token_provider", return_value=None),                  mock.patch.object(ad, "write_persistent_log", return_value=None):
                manager._run_download(download)
        runs = [args for args in captured if download.url in args]
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_the_media_is_skipped(self):
        self.assertIn("--skip-download", self._argv({"EmbedSubs": True}))

    def test_a_normal_download_never_skips_the_media(self):
        self.assertNotIn(
            "--skip-download",
            self._argv({"EmbedSubs": True}, subtitles_only=False),
        )

    def test_nothing_is_embedded_into_a_file_that_was_not_downloaded(self):
        # Every embed postprocesses the media container, and this run
        # deliberately produces none.
        argv = self._argv({
            "EmbedSubs": True, "EmbedMetadata": True,
            "EmbedThumbnail": True, "EmbedChapters": True,
        })
        for flag in ("--embed-subs", "--embed-metadata", "--embed-thumbnail",
                     "--embed-chapters"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, argv)

    def test_a_normal_download_still_embeds_all_four(self):
        argv = self._argv({
            "EmbedSubs": True, "EmbedMetadata": True,
            "EmbedThumbnail": True, "EmbedChapters": True,
        }, subtitles_only=False)
        for flag in ("--embed-subs", "--embed-metadata", "--embed-thumbnail",
                     "--embed-chapters"):
            with self.subTest(flag=flag):
                self.assertIn(flag, argv)

    def test_the_subtitles_still_get_fetched(self):
        argv = self._argv({"EmbedSubs": False, "SubtitleMode": "manual"})
        self.assertIn("--write-subs", argv)
        self.assertNotIn("--write-auto-subs", argv)

    def test_the_written_subtitle_line_is_recognised(self):
        match = ad.SUBTITLE_WRITTEN_RE.match(
            r"[info] Writing video subtitles to: C:\\Videos\\Clip.en.vtt")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), r"C:\\Videos\\Clip.en.vtt")

    def test_an_unrelated_info_line_is_not_a_subtitle(self):
        for line in (
            "[info] Writing video description to: C:\\Videos\\Clip.description",
            "[download] Destination: C:\\Videos\\Clip.en.vtt",
            "Writing video subtitles to: relative-without-the-info-prefix",
        ):
            with self.subTest(line=line):
                self.assertIsNone(
                    ad.SUBTITLE_WRITTEN_RE.match(line))

    def test_a_converted_subtitle_is_named_by_its_new_extension(self):
        # yt-dlp announces the .vtt it downloaded and only then converts it;
        # the [SubtitlesConvertor] line names no destination, so the path has
        # to be derived. Verified against the installed binary.
        with tempfile.TemporaryDirectory() as tmpdir:
            written = Path(tmpdir) / "Clip.en.vtt"
            written.write_text("WEBVTT\n", encoding="utf-8")
            converted = Path(tmpdir) / "Clip.en.srt"
            converted.write_text("1\n", encoding="utf-8")
            manager = types.SimpleNamespace(
                config={"SubtitleFormat": "srt"},
                _converted_subtitle_path=None,
            )
            manager._converted_subtitle_path = types.MethodType(
                ad.DownloadManager._converted_subtitle_path,
                manager,
            )
            self.assertEqual(
                manager._converted_subtitle_path(str(written)), str(converted))

    def test_an_unconverted_subtitle_keeps_the_announced_path(self):
        # If the conversion did not happen, naming a file that is not there
        # would make "Show in folder" open nothing.
        with tempfile.TemporaryDirectory() as tmpdir:
            written = Path(tmpdir) / "Clip.en.vtt"
            written.write_text("WEBVTT\n", encoding="utf-8")
            manager = types.SimpleNamespace(config={"SubtitleFormat": "srt"})
            manager._converted_subtitle_path = types.MethodType(
                ad.DownloadManager._converted_subtitle_path,
                manager,
            )
            self.assertEqual(
                manager._converted_subtitle_path(str(written)), str(written))

    def test_the_flag_survives_a_restart(self):
        # The queue index is what a recovered download is rebuilt from; a
        # subtitles-only job that came back as a full video download would
        # fetch the media the user deliberately skipped.
        download = ad.Download(
            "dl_1", "https://example.com/v", subtitles_only=True)
        store = ad.DownloadQueueStore(
            path=Path("unused.json"), reader=lambda *_a: None,
            writer=lambda *_a: None, logger=lambda *_a: None,
            clean_text=ad.clean_text, clean_path_text=ad.clean_path_text,
        )
        download.status = "pending"
        record = store.serialize([download])["downloads"][0]
        self.assertIs(record["subtitlesOnly"], True)

    def test_a_normal_download_does_not_carry_the_flag(self):
        download = ad.Download("dl_1", "https://example.com/v")
        self.assertNotIn("subtitlesOnly", download.to_dict())


class LocalSubtitleGenerationTests(unittest.TestCase):
    """Opt-in local Whisper transcription is safe, visible, and cancellable."""

    def _download(self, media, **overrides):
        data = {"GenerateSubtitles": True, "SubLangs": "en,es"}
        data.update(overrides)
        config = ad.sanitize_config(data)
        download = ad.Download(
            "dl_local_subtitles", "https://example.com/video",
            output_dir=str(Path(media).parent),
        )
        download.filename = str(media)
        return config, download

    def test_local_generation_is_off_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "clip.mp4"
            media.write_bytes(b"media")
            config, download = self._download(media, GenerateSubtitles=False)
            self.assertFalse(ad.should_generate_local_subtitles(config, download))

    def test_existing_sidecar_and_embedded_track_suppress_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "clip.mp4"
            media.write_bytes(b"media")
            config, download = self._download(media)
            self.assertTrue(ad.should_generate_local_subtitles(config, download))

            (Path(tmpdir) / "clip.en.vtt").write_text("WEBVTT\n", encoding="utf-8")
            self.assertFalse(ad.should_generate_local_subtitles(config, download))

            (Path(tmpdir) / "clip.en.vtt").unlink()
            download.subtitle_written = True
            self.assertFalse(ad.should_generate_local_subtitles(config, download))

    def test_audio_and_subtitle_only_jobs_never_start_whisper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "clip.mp4"
            media.write_bytes(b"media")
            config, download = self._download(media)
            download.audio_only = True
            self.assertFalse(ad.should_generate_local_subtitles(config, download))
            download.audio_only = False
            download.subtitles_only = True
            self.assertFalse(ad.should_generate_local_subtitles(config, download))

    def test_filter_paths_escape_drive_letters_and_filter_punctuation(self):
        args = ad.build_local_subtitle_args(
            r"C:\Tools\ffmpeg.exe",
            r"C:\Videos\A:B,clip.mp4",
            r"C:\Users\A:B\whisper model.bin",
            r"C:\Videos\A:B,clip.srt",
            language="en",
        )
        graph = args[args.index("-af") + 1]
        self.assertIn(r"model=C\\:/Users/A\\:B/whisper model.bin", graph)
        self.assertIn(r"destination=C\\:/Videos/A\\:B\\,clip.srt", graph)
        self.assertIn("format=srt", graph)
        self.assertEqual(
            args[-6:],
            ["-progress", "pipe:1", "-nostats", "-f", "null", "-"],
        )

    def test_first_selected_language_is_used_for_transcription(self):
        self.assertEqual(
            ad.subtitle_language_for_transcription({"SubLangs": "zh-Hans, en"}),
            "zh",
        )
        self.assertEqual(
            ad.subtitle_language_for_transcription({"SubLangs": ""}),
            "auto",
        )

    def test_transcription_wav_estimate_uses_clip_duration_and_safe_fallback(self):
        clipped = types.SimpleNamespace(section={"start": 2.5, "end": 5.0})
        self.assertEqual(
            ad.estimate_transcription_wav_bytes(clipped),
            2.5 * ad.TRANSCRIPTION_WAV_BYTES_PER_SECOND,
        )
        self.assertEqual(
            ad.estimate_transcription_wav_bytes(types.SimpleNamespace()),
            ad.TRANSCRIPTION_FALLBACK_DURATION_SECONDS
            * ad.TRANSCRIPTION_WAV_BYTES_PER_SECOND,
        )

    def test_whisper_progress_is_parsed_and_clamped(self):
        self.assertEqual(ad.parse_whisper_progress("progress = 37%"), 37.0)
        self.assertEqual(ad.parse_whisper_progress("progress: 120%"), 100.0)
        self.assertIsNone(ad.parse_whisper_progress("progress=end"))

    def test_whisper_invocation_requests_real_progress_output(self):
        import download as download_module

        with mock.patch.object(download_module.os, "cpu_count", return_value=12):
            args = ad.build_whisper_transcription_args(
                "whisper-cli.exe", "model.bin", "audio.wav", "captions"
            )
        self.assertEqual(args[args.index("-t") + 1], "12")
        self.assertIn("-sow", args)
        args = ad.build_whisper_transcription_args(
            "whisper-cli.exe", "model.bin", "audio.wav", "captions",
            threads=7,
        )
        self.assertIn("-pp", args)
        self.assertEqual(args[args.index("-pp") - 2], "-of")

    def test_whisper_sidecar_pin_has_a_verified_release_digest(self):
        self.assertEqual(ad.WHISPER_BIN_VERSION, "1.9.2")
        self.assertEqual(
            ad.WHISPER_BIN_SHA256,
            "49dcc16de826f20bd53d44f947a1ae49dfa81f86cad67a64d80820cb192d674a",
        )
        self.assertIn("/v1.9.2/whisper-bin-x64.zip", ad.WHISPER_BIN_URL)

    def test_transcription_gate_is_independent_of_download_limit(self):
        manager = ad.DownloadManager(
            FakeConfig({"MaxConcurrentDownloads": 10}), FakeHistory()
        )
        self.assertEqual(manager._max_concurrent(), 10)
        self.assertTrue(manager._transcription_gate.acquire(blocking=False))
        try:
            self.assertFalse(manager._transcription_gate.acquire(blocking=False))
        finally:
            manager._transcription_gate.release()

    class _TranscriptProcess:
        def __init__(self, args, **_kwargs):
            self.args = list(args)
            self.returncode = 0
            if "-af" in self.args:
                graph = self.args[self.args.index("-af") + 1]
                destination = graph.split(":destination=", 1)[1].split(
                    ":format=", 1
                )[0]
                for character in (":", ",", "[", "]", ";", "'"):
                    destination = destination.replace("\\\\" + character, character)
                    destination = destination.replace("\\" + character, character)
                destination_path = Path(destination)
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                destination_path.write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
            elif "-c:a" in self.args:
                audio_path = Path(self.args[self.args.index("-c:a") + 2])
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_path.write_bytes(b"pcm audio")
            elif "-osrt" in self.args:
                base = Path(self.args[self.args.index("-of") + 1])
                output = Path(f"{base}.srt")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
            self.stdout = io.StringIO("out_time_ms=100\nprogress=end\n")

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    def test_success_commits_an_srt_only_after_ffmpeg_finishes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            model = root / "ggml-tiny-q5_1.bin"
            model.write_bytes(b"model")
            whisper = root / "whisper-cli.exe"
            whisper.write_bytes(b"runtime")
            config, download = self._download(media)
            manager = ad.DownloadManager(config=FakeConfig(config), history=FakeHistory())
            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", whisper), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "probe_whisper_runtime", return_value={"usable": True}), \
                    mock.patch.object(ad, "FFMPEG_PATH", root / "ffmpeg.exe"), \
                    mock.patch.object(ad, "spawn_media_process", self._TranscriptProcess):
                self.assertTrue(manager._run_local_subtitles(download, config))
            output = root / "clip.srt"
            self.assertTrue(output.is_file())
            self.assertIn("hello", output.read_text(encoding="utf-8"))
            self.assertEqual(download.status, "complete")
            self.assertEqual(download.progress, 100.0)
            self.assertEqual(list(root.glob(".clip*")), [])

    def test_transcription_preflights_wav_space_and_stages_beside_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            model = root / "ggml-tiny-q5_1.bin"
            model.write_bytes(b"model")
            whisper = root / "whisper-cli.exe"
            whisper.write_bytes(b"runtime")
            config, download = self._download(media)
            manager = ad.DownloadManager(config=FakeConfig(config), history=FakeHistory())
            checks = []
            process_args = []

            class InspectProcess(self._TranscriptProcess):
                def __init__(inner_self, args, **kwargs):
                    process_args.append(list(args))
                    super().__init__(args, **kwargs)

            def check(path, required, **kwargs):
                checks.append((Path(path), required, Path(kwargs["staging_path"])))
                return None

            with mock.patch.object(ad, "INSTALL_DIR", root / "install"), \
                    mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", whisper), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "probe_whisper_runtime", return_value={"usable": True}), \
                    mock.patch.object(ad, "FFMPEG_PATH", root / "ffmpeg.exe"), \
                    mock.patch.object(ad, "check_download_disk_space", side_effect=check), \
                    mock.patch.object(ad, "spawn_media_process", InspectProcess):
                self.assertTrue(manager._run_local_subtitles(download, config))
                staging = manager._download_intermediate_dir(download)

            self.assertEqual(checks, [(root, checks[0][1], staging)])
            self.assertEqual(
                checks[0][1],
                ad.TRANSCRIPTION_FALLBACK_DURATION_SECONDS
                * ad.TRANSCRIPTION_WAV_BYTES_PER_SECOND,
            )
            self.assertTrue(process_args)
            self.assertTrue(all(str(staging) in " ".join(args) for args in process_args))
            self.assertEqual(list(root.glob(".clip*")), [])

    def test_transcription_disk_failure_is_reported_before_spawning_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            model = root / "ggml-tiny-q5_1.bin"
            model.write_bytes(b"model")
            whisper = root / "whisper-cli.exe"
            whisper.write_bytes(b"runtime")
            config, download = self._download(media)
            manager = ad.DownloadManager(config=FakeConfig(config), history=FakeHistory())
            failure = ad.download_error_payload(
                "insufficient-disk-space", error="fixture has no staging space"
            )
            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", whisper), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "probe_whisper_runtime", return_value={"usable": True}), \
                    mock.patch.object(ad, "check_download_disk_space", return_value=failure), \
                    mock.patch.object(ad, "spawn_media_process") as spawn:
                self.assertFalse(manager._run_local_subtitles(download, config))

            self.assertFalse(spawn.called)
            self.assertEqual(download.status, "complete")
            self.assertEqual(download.error_code, "insufficient-disk-space")
            self.assertIn("fixture has no staging space", download.error)

    def test_whisper_watchdog_bounds_the_real_child_and_reports_progress(self):
        import importlib

        download_module = importlib.import_module("download")
        terminated = []
        stopped = threading.Event()
        calls = []
        progress_seen = []

        class CompletedProcess:
            def __init__(self, args):
                self.args = list(args)
                self.returncode = 0
                self.stdout = io.StringIO("progress=end\n")

            def wait(self, timeout=None):
                return self.returncode

            def poll(self):
                return self.returncode

        class HangingProcess:
            def __init__(self, args):
                self.args = list(args)
                self.returncode = None
                self.stdout = self.BlockingStdout(self, stopped)

            class BlockingStdout:
                def __init__(self, proc, stop_event):
                    self.proc = proc
                    self.stop_event = stop_event
                    self.progress_emitted = False

                def __iter__(self):
                    return self

                def __next__(self):
                    if not self.progress_emitted:
                        self.progress_emitted = True
                        return "progress = 37%\n"
                    if not self.stop_event.wait(15):
                        self.proc.returncode = 1
                    raise StopIteration

                def close(self):
                    return None

            def wait(self, timeout=None):
                return self.returncode or 1

            def poll(self):
                return self.returncode

        hanging = HangingProcess(["whisper-cli.exe"])

        def spawn(args, **kwargs):
            calls.append((list(args), dict(kwargs)))
            return hanging if "-osrt" in args else CompletedProcess(args)

        def terminate(proc):
            terminated.append(proc)
            stopped.set()
            proc.returncode = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            model = root / "ggml-tiny-q5_1.bin"
            model.write_bytes(b"model")
            whisper = root / "whisper-cli.exe"
            whisper.write_bytes(b"runtime")
            config, download = self._download(media)
            manager = ad.DownloadManager(config=FakeConfig(config), history=FakeHistory())
            manager.progress_updated.connect(
                lambda: progress_seen.append(download.progress)
            )
            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", whisper), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "probe_whisper_runtime", return_value={"usable": True}), \
                    mock.patch.object(ad, "FFMPEG_PATH", root / "ffmpeg.exe"), \
                    mock.patch.object(ad, "spawn_media_process", side_effect=spawn), \
                    mock.patch.object(ad, "terminate_process_tree", side_effect=terminate), \
                    mock.patch.object(download_module, "LOCAL_TRANSCRIPTION_TIMEOUT_SECONDS", 0), \
                    mock.patch.object(download_module, "LOCAL_TRANSCRIPTION_WATCHDOG_POLL_SECONDS", 0.01):
                result = manager._run_local_subtitles(download, config)

        self.assertFalse(result)
        self.assertEqual(terminated, [hanging])
        self.assertEqual(download.status, "complete")
        self.assertEqual(download.error_code, "transcription-timeout")
        self.assertIn("time limit", download.error)
        self.assertIsNone(download.process)
        self.assertTrue(
            any(abs(value - 49.6) < 0.01 for value in progress_seen),
            progress_seen,
        )
        self.assertIn("-pp", calls[1][0])
        self.assertEqual(
            calls[1][1]["creationflags"]
            & download_module.TRANSCRIPTION_BELOW_NORMAL_PRIORITY_CLASS,
            download_module.TRANSCRIPTION_BELOW_NORMAL_PRIORITY_CLASS,
        )

    def test_cancelling_the_stage_does_not_leave_a_partial_srt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            model = root / "ggml-tiny-q5_1.bin"
            model.write_bytes(b"model")
            whisper = root / "whisper-cli.exe"
            whisper.write_bytes(b"runtime")
            config, download = self._download(media)

            class CancelProcess(self._TranscriptProcess):
                def __init__(inner_self, args, **_kwargs):
                    super().__init__(args)
                    download.status = "cancelled"
                    inner_self.returncode = -15

            manager = ad.DownloadManager(config=FakeConfig(config), history=FakeHistory())
            with mock.patch.object(ad, "WHISPER_MODEL_PATH", model), \
                    mock.patch.object(ad, "WHISPER_MODEL_MIN_BYTES", 1), \
                    mock.patch.object(ad, "WHISPER_BIN_PATH", whisper), \
                    mock.patch.object(ad, "WHISPER_BIN_MIN_BYTES", 1), \
                    mock.patch.object(ad, "probe_whisper_runtime", return_value={"usable": True}), \
                    mock.patch.object(ad, "FFMPEG_PATH", root / "ffmpeg.exe"), \
                    mock.patch.object(ad, "spawn_media_process", CancelProcess):
                self.assertFalse(manager._run_local_subtitles(download, config))
            self.assertEqual(download.status, "cancelled")
            self.assertFalse((root / "clip.srt").exists())
            self.assertEqual(list(root.glob(".clip*")), [])


class SubtitleRetryTests(unittest.TestCase):
    """A sidecar failure is retried in place, never as a second media fetch."""

    def test_completed_media_keeps_its_path_when_subtitles_are_retried(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            download = ad.Download(
                "dl_subtitle_retry", "https://example.com/video",
                output_dir=str(root),
            )
            download.status = "complete"
            download.filename = str(media)
            download.error_code = "transcription-failed"
            manager = ad.DownloadManager(config=FakeConfig(), history=FakeHistory())
            manager.downloads[download.id] = download
            manager._schedule = lambda: None

            ok, error = manager.retry(download.id)

            self.assertTrue(ok, error)
            self.assertIsNone(error)
            self.assertEqual(download.status, "pending")
            self.assertTrue(download.subtitle_retry)
            self.assertEqual(download.filename, str(media))
            self.assertTrue(download.to_dict()["retryable"] is False)

    def test_complete_transcription_failure_is_visible_as_retryable(self):
        download = ad.Download("dl_complete", "https://example.com/video")
        download.status = "complete"
        download.error_code = "transcription-runtime-missing"
        self.assertTrue(download.to_dict()["retryable"])


class ImpersonateTests(unittest.TestCase):
    """Imitating a browser is the standard 403 remedy, gated on what exists."""

    # Trimmed from the installed binary's real output, including the repeated
    # client rows that make the raw table longer than the target list.
    SAMPLE = """[info] Available impersonate targets
Client          OS           Source
--------------------------------------
Chrome-133      Macos-15     curl_cffi
Chrome-136      Macos-15     curl_cffi
Safari-17.2     Ios-17.2     curl_cffi
Chrome-99       Android-12   curl_cffi
Chrome-99       Windows-10   curl_cffi
Edge-101        Windows-10   curl_cffi
"""

    def test_the_table_parses_to_client_names_only(self):
        targets = ad.parse_impersonate_targets(self.SAMPLE)
        self.assertEqual(
            targets,
            ["Chrome-133", "Chrome-136", "Safari-17.2", "Chrome-99", "Edge-101"],
        )

    def test_the_header_rule_and_info_line_are_not_targets(self):
        targets = ad.parse_impersonate_targets(self.SAMPLE)
        for noise in ("Client", "[info]", "--------------------------------------"):
            self.assertNotIn(noise, targets)

    def test_a_client_listed_for_several_systems_appears_once(self):
        # The OS column is provenance; --impersonate takes the client.
        self.assertEqual(
            ad.parse_impersonate_targets(self.SAMPLE).count("Chrome-99"), 1
        )

    def test_junk_output_yields_no_targets(self):
        for value in ("", None, "yt-dlp: error: no such option", "   "):
            self.assertEqual(ad.parse_impersonate_targets(value), [])

    # ── The argv gate ────────────────────────────────────────────────────

    def test_nothing_configured_sends_no_flag(self):
        self.assertEqual(
            ad.build_impersonate_args(ad.sanitize_config({}), ["Chrome-136"]), []
        )

    def test_a_target_the_binary_has_is_sent(self):
        self.assertEqual(
            ad.build_impersonate_args(
                {"ImpersonateTarget": "Chrome-136"}, ["Chrome-133", "Chrome-136"]
            ),
            ["--impersonate", "Chrome-136"],
        )

    def test_a_target_the_binary_lacks_is_dropped(self):
        # Verified against the installed yt-dlp: an unknown target does not
        # warn, it raises YoutubeDLError and the download dies. A setting that
        # went stale across an update must not break every download.
        self.assertEqual(
            ad.build_impersonate_args(
                {"ImpersonateTarget": "Chrome-999"}, ["Chrome-136"]
            ),
            [],
        )

    def test_no_probe_means_no_flag(self):
        self.assertEqual(
            ad.build_impersonate_args({"ImpersonateTarget": "Chrome-136"}, []), []
        )

    def test_network_workaround_args_are_ordered_and_shape_checked(self):
        self.assertEqual(
            ad.build_network_workaround_args({
                "ForceIPVersion": "ipv4",
                "SourceAddress": "192.0.2.10",
                "Xff": "us",
                "GeoVerificationProxy": "https://proxy.example:8443",
            }),
            [
                "--force-ipv4",
                "--source-address", "192.0.2.10",
                "--xff", "US",
                "--geo-verification-proxy", "https://proxy.example:8443",
            ],
        )
        self.assertEqual(
            ad.build_network_workaround_args({
                "ForceIPVersion": "both",
                "SourceAddress": "; calc.exe",
                "Xff": "US; --exec",
                "GeoVerificationProxy": "file:///tmp/nope",
            }),
            [],
        )

    def test_the_stored_value_is_shape_checked(self):
        for value in ("; rm -rf /", "--exec=calc", "Chrome", "notareal", "  "):
            with self.subTest(value=value):
                self.assertEqual(ad.normalize_impersonate_target(value), "")
        self.assertEqual(ad.normalize_impersonate_target("Safari-17.2"), "Safari-17.2")

    # ── The failure it answers ───────────────────────────────────────────

    def test_a_403_is_classified_as_a_refusal_not_a_dead_network(self):
        for text in (
            "ERROR: unable to download webpage: HTTP Error 403: Forbidden",
            "ERROR: Cloudflare challenge detected",
        ):
            with self.subTest(text=text):
                self.assertEqual(ad.classify_download_failure(text), "blocked-by-site")

    def test_the_403_advice_names_the_remedy(self):
        advice = ad.download_error_payload("blocked-by-site")["advice"]
        self.assertIn("imitate", advice.lower())
        self.assertIn("--force-ipv4", advice)

    def test_geo_restriction_is_classified_and_names_xff(self):
        self.assertEqual(
            ad.classify_download_failure(
                "ERROR: This video is not available in your country"
            ),
            "geo-restricted",
        )
        advice = ad.download_error_payload("geo-restricted")["advice"]
        self.assertIn("--xff", advice)

    def test_a_403_becomes_retryable_once_a_browser_is_chosen(self):
        # Not transient, so not in DOWNLOAD_RETRYABLE_ERROR_CODES — it is
        # retryable once the user has done the thing that fixes it, which is
        # what the precondition gate expresses.
        self.assertNotIn("blocked-by-site", ad.DOWNLOAD_RETRYABLE_ERROR_CODES)
        with tempfile.TemporaryDirectory() as tmpdir:
            targets = ["Chrome-136"]
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            manager.update_readiness_snapshot({
                "configuredRuntime": "auto",
                "runtime": {},
                "impersonateTargets": targets,
            })
            dl = ad.Download("dl_403", "https://example.com/v")
            dl.status = "failed"
            dl.error_code = "blocked-by-site"

            satisfied, missing = manager.recovery_precondition(dl)
            self.assertFalse(satisfied)
            self.assertIn("Settings", missing)

            manager.config = FakeConfig({**settings, "ImpersonateTarget": "Chrome-136"})
            manager._precondition_cache.clear()
            satisfied, _missing = manager.recovery_precondition(dl)
            self.assertTrue(satisfied)

    def test_a_target_the_binary_lost_is_named_in_the_refusal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir,
                        "ImpersonateTarget": "Chrome-999"}
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            manager.update_readiness_snapshot({
                "configuredRuntime": "auto",
                "runtime": {},
                "impersonateTargets": ["Chrome-136"],
            })
            dl = ad.Download("dl_403", "https://example.com/v")
            dl.status = "failed"
            dl.error_code = "blocked-by-site"
            satisfied, missing = manager.recovery_precondition(dl)
        self.assertFalse(satisfied)
        self.assertIn("Chrome-999", missing)

    def test_geo_restriction_becomes_retryable_after_a_geo_workaround_is_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            dl = ad.Download("dl_geo", "https://example.com/v")
            dl.status = "failed"
            dl.error_code = "geo-restricted"

            satisfied, missing = manager.recovery_precondition(dl)
            self.assertFalse(satisfied)
            self.assertIn("--xff", missing)

            manager.config = FakeConfig({**settings, "Xff": "US"})
            manager._precondition_cache.clear()
            satisfied, _missing = manager.recovery_precondition(dl)
            self.assertTrue(satisfied)

    def test_geo_profile_workaround_satisfies_retry_precondition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = {
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "SiteProfiles": [{
                    "Name": "Example geo",
                    "Domain": "example.com",
                    "Xff": "US",
                }],
            }
            manager = ad.DownloadManager(FakeConfig(settings), FakeHistory())
            dl = ad.Download("dl_profile_geo", "https://example.com/video")
            dl.status = "failed"
            dl.error_code = "geo-restricted"

            satisfied, missing = manager.recovery_precondition(dl)

        self.assertTrue(satisfied, missing)

    # ── Against the real binary ──────────────────────────────────────────

    def test_the_installed_binary_reports_targets_this_parser_understands(self):
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest("yt-dlp is not installed in this environment")
        proc = subprocess.run(
            [str(ytdlp), "--list-impersonate-targets"],
            capture_output=True, text=True, timeout=120,
        )
        targets = ad.parse_impersonate_targets(proc.stdout)
        self.assertTrue(targets, f"no targets parsed from: {proc.stdout[:300]}")
        for target in targets:
            with self.subTest(target=target):
                # Every parsed target must survive the stored-value shape
                # check, or the picker would offer something that cannot
                # round-trip through the config.
                self.assertEqual(ad.normalize_impersonate_target(target), target)


class SmallerGapTests(unittest.TestCase):
    """The second batch of measured, individually-minor defects."""

    def _store(self, path, clock=lambda: 1000.0):
        return ad.SubscriptionStore(
            path=path,
            reader=ad.load_json_file,
            writer=ad.atomic_write_json,
            logger=self.fail,
            normalize_url=ad.normalize_url,
            is_youtube_url=ad.is_youtube_url,
            clean_text=ad.clean_text,
            clamp_int=ad.clamp_int,
            coerce_bool=ad.coerce_bool,
            clock=clock,
        )

    def test_the_download_cookie_cap_matches_the_store_that_accepts_them(self):
        # A hardcoded 200 here halved a jar the sign-in store keeps whole, and
        # the only symptom was yt-dlp failing to authenticate.
        token = "c" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        cookies = [
            {"name": f"cookie-{index}", "value": "v", "domain": ".example.com"}
            for index in range(ad.MAX_SITE_LOGIN_COOKIES + 23)
        ]
        with mock.patch.object(
            manager, "start_download", return_value=("dl-cookie-cap", None)
        ) as start:
            response = api.test_client().post(
                "/download",
                json={"url": "https://example.com/video", "cookies": cookies},
                headers={"X-Auth-Token": token},
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(
            len(start.call_args.kwargs["cookies"]), ad.MAX_SITE_LOGIN_COOKIES
        )
        self.assertEqual(
            response.get_json()["cookiesTruncated"], ad.MAX_SITE_LOGIN_COOKIES
        )

    def test_the_precondition_cache_drops_expired_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp}),
                FakeHistory(),
            )
            ttl = manager._PRECONDITION_TTL_SECONDS
            stale = time.time() - (ttl * 10)
            with manager._precondition_cache_lock:
                for index in range(50):
                    manager._precondition_cache[("sign-in", f"u{index}", False)] = (
                        stale, (True, None)
                    )
            self.assertEqual(len(manager._precondition_cache), 50)

            dl = ad.Download("dl_cache", "https://www.youtube.com/watch?v=abc12345678")
            dl.error_code = "sign-in-required"
            manager.recovery_precondition(dl)

            # Every stale entry is gone; only the fresh answer remains.
            self.assertLessEqual(
                len(manager._precondition_cache), 1,
                "expired precondition entries must not accumulate for the "
                "life of a tray app that runs for days",
            )

    def test_the_next_scan_is_anchored_to_the_scan_start_not_its_end(self):
        # Measuring from the finish adds the scan duration to every cycle, so
        # an hourly subscription whose scan takes two minutes slips about 48
        # minutes a day.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            clock = {"now": 1_000_000.0}
            store = self._store(path, clock=lambda: clock["now"])
            created, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", interval_minutes=60
            )
            self.assertIsNone(error)
            sub_id = created["id"]

            started = clock["now"]
            self.assertIsNotNone(store.begin_scan(sub_id))
            clock["now"] = started + 120.0  # a two-minute scan
            self.assertTrue(store.finish_scan(sub_id, queued=1))

            record = store.list_subscriptions()[0]
            self.assertEqual(
                record["nextScanAt"], started + 3600.0,
                "the next scan must fall an interval after this one began",
            )

    def test_a_scan_longer_than_its_interval_does_not_schedule_in_the_past(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            clock = {"now": 1_000_000.0}
            store = self._store(path, clock=lambda: clock["now"])
            created, _error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", interval_minutes=1
            )
            sub_id = created["id"]
            self.assertIsNotNone(store.begin_scan(sub_id))
            clock["now"] += 600.0  # the scan outran its own interval
            self.assertTrue(store.finish_scan(sub_id, queued=0))

            record = store.list_subscriptions()[0]
            self.assertGreater(
                record["nextScanAt"], clock["now"],
                "an overrunning scan must not queue a backlog of due scans",
            )

    def test_one_archive_entry_is_read_without_copying_the_whole_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            store = self._store(path)
            created, _error = store.add_subscription(
                "https://www.youtube.com/@astra-channel"
            )
            key = "id:onlyone"
            store.reserve_archive(key, {"title": "Only one"}, created["id"])

            entry = store.archive_entry(key)
            self.assertTrue(entry, "the entry must be returned")
            self.assertEqual(store.archive_entry("id:absent"), {})

            # A copy, not the live record: mutating the result must not reach
            # the store.
            entry["title"] = "mutated"
            self.assertNotEqual(store.archive_entry(key).get("title"), "mutated")

    def test_the_retry_exhausted_branch_reads_a_single_entry(self):
        subs = subscriptions_module()
        store = mock.Mock()
        store.reserve_archive.return_value = subs.RESERVE_RETRY_EXHAUSTED
        store.archive_entry.return_value = {
            "attempts": subs.SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS,
            "lastError": "provider refused the request",
        }
        store._clean.side_effect = lambda value, default, maximum: (
            str(value)[:maximum] if value else default
        )
        store.archive_entries.side_effect = AssertionError(
            "the retry path copied the whole archive"
        )
        manager = ad.SubscriptionManager(
            store=store,
            probe=lambda _url: ([], None),
            enqueue=lambda *_args: ("dl", None),
        )
        candidate = {"id": "onlyone", "title": "Only one"}
        claimed, skipped, errors = manager._reserve_candidates(
            "sub-one", [candidate], 1000
        )
        self.assertEqual(claimed, [])
        self.assertEqual(skipped, 1)
        self.assertTrue(errors)
        store.archive_entry.assert_called_once_with("id:onlyone")
        store.archive_entries.assert_not_called()


class SystemProxyTests(unittest.TestCase):
    """Windows already knows the proxy; the user should not retype it.

    Detection is deliberately split: the registry read lives in the composition
    root, parsing and precedence live in config.py, so a malformed registry
    value is refused by exactly the rules a typed proxy faces.
    """

    def test_a_bare_host_port_applies_to_every_protocol(self):
        self.assertEqual(
            ad.parse_wininet_proxy_server("proxy.corp:8080"),
            "http://proxy.corp:8080",
        )

    def test_a_per_protocol_list_is_resolved_by_preference_not_by_order(self):
        # WinINET stores an unordered list. Taking whichever entry came first
        # would route through the ftp proxy on a machine that lists it first.
        self.assertEqual(
            ad.parse_wininet_proxy_server("ftp=f.corp:21;http=p.corp:8080;https=s.corp:8443"),
            "http://s.corp:8443",
        )
        self.assertEqual(
            ad.parse_wininet_proxy_server("ftp=f.corp:21;http=p.corp:8080"),
            "http://p.corp:8080",
        )

    def test_a_socks_entry_keeps_its_scheme(self):
        self.assertEqual(
            ad.parse_wininet_proxy_server("socks=s.corp:1080"),
            "socks5://s.corp:1080",
        )

    def test_a_malformed_registry_value_is_refused(self):
        for value in ("", "   ", "ftp=f.corp:21", "=;;=", None, 12345):
            with self.subTest(value=value):
                self.assertEqual(ad.parse_wininet_proxy_server(value), "")

    def test_a_typed_proxy_always_wins_over_the_detected_one(self):
        config = FakeConfig({"Proxy": "http://typed:3128", "UseSystemProxy": True})
        self.assertEqual(
            ad.resolve_effective_proxy(config.get, "http://detected:8080"),
            "http://typed:3128",
        )

    def test_the_detected_proxy_is_ignored_while_the_option_is_off(self):
        config = FakeConfig({"Proxy": "", "UseSystemProxy": False})
        self.assertEqual(
            ad.resolve_effective_proxy(config.get, "http://detected:8080"), ""
        )

    def test_the_detected_proxy_is_used_when_opted_in_with_no_typed_value(self):
        config = FakeConfig({"Proxy": "", "UseSystemProxy": True})
        self.assertEqual(
            ad.resolve_effective_proxy(config.get, "http://detected:8080"),
            "http://detected:8080",
        )

    def test_a_disabled_system_proxy_is_not_read_from_a_stale_registry_value(self):
        # ProxyEnable = 0 with a leftover ProxyServer string is the normal
        # state of a machine whose proxy was turned off, not configuration.
        calls = {}

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_query(_key, name):
            calls[name] = calls.get(name, 0) + 1
            if name == "ProxyEnable":
                return (0, 4)
            return ("stale.corp:8080", 1)

        winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=lambda *_a, **_k: FakeKey(),
            QueryValueEx=fake_query,
            CloseKey=lambda _key: None,
        )
        with mock.patch.dict(sys.modules, {"winreg": winreg}), \
                mock.patch.object(ad.sys, "platform", "win32"):
            self.assertEqual(ad.detect_system_proxy(), "")
        self.assertNotIn("ProxyServer", calls)

    def test_an_enabled_system_proxy_is_parsed(self):
        class FakeKey:
            pass

        def fake_query(_key, name):
            return (1, 4) if name == "ProxyEnable" else ("proxy.corp:8080", 1)

        winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=lambda *_a, **_k: FakeKey(),
            QueryValueEx=fake_query,
            CloseKey=lambda _key: None,
        )
        with mock.patch.dict(sys.modules, {"winreg": winreg}), \
                mock.patch.object(ad.sys, "platform", "win32"):
            self.assertEqual(ad.detect_system_proxy(), "http://proxy.corp:8080")

    def test_an_unreadable_key_reports_no_proxy_instead_of_raising(self):
        def boom(*_args, **_kwargs):
            raise OSError("access denied")

        winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            OpenKey=boom,
            QueryValueEx=lambda *_a: None,
            CloseKey=lambda _key: None,
        )
        with mock.patch.dict(sys.modules, {"winreg": winreg}), \
                mock.patch.object(ad.sys, "platform", "win32"):
            self.assertEqual(ad.detect_system_proxy(), "")

    def test_the_setting_never_travels_in_a_settings_bundle(self):
        # It describes one machine's network, exactly like Proxy itself: an
        # import must not silently route another machine's traffic.
        self.assertIn("UseSystemProxy", ad.BUNDLE_EXCLUDED_SETTINGS)


class OutputNameTests(unittest.TestCase):
    """A per-download name is a file stem, never a path and never a template.

    Open Video Downloader shipped a path-traversal fix in v3.1.2 for this exact
    feature, so the normalizer refuses rather than sanitizes: rewriting
    ``../../evil`` into ``evil`` would teach the caller that traversal was
    accepted and leave the next laxer build to actually honour it.
    """

    ACCEPTED = ("My Video", "Episode 1 - The Beginning", "good-name_01", "a.b.c")
    REFUSED = (
        "a/b", "a" + chr(92) + "b", "C:evil", "..", "../../evil",
        "%(title)s", "50%", "CON", "con.mp4", "NUL", "LPT1",
        "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b", "a:b",
        "a" + chr(0) + "b", "a" + chr(10) + "b",
        "", "   ", ".", " . ",
    )

    def test_accepted_names_survive_normalization(self):
        for value in self.ACCEPTED:
            with self.subTest(value=value):
                self.assertEqual(ad.normalize_output_name(value), value)

    def test_refused_names_normalize_to_empty(self):
        for value in self.REFUSED:
            with self.subTest(value=value):
                self.assertEqual(
                    ad.normalize_output_name(value), "",
                    f"{value!r} must be refused, not sanitized into a usable name",
                )

    def test_surrounding_whitespace_and_trailing_dots_are_trimmed(self):
        # Windows silently drops a trailing dot or space, so the stem the user
        # sees in the hint has to be the stem that reaches the filesystem.
        self.assertEqual(ad.normalize_output_name("  spaced  "), "spaced")
        self.assertEqual(ad.normalize_output_name("trailing. "), "trailing")

    def test_the_name_is_capped_rather_than_rejected(self):
        capped = ad.normalize_output_name("x" * 500)
        self.assertEqual(len(capped), ad.MAX_OUTPUT_NAME_LENGTH)

    def test_a_refused_name_never_reaches_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp}),
                FakeHistory(),
            )
            dl_id, error = manager.start_download(
                url="https://www.youtube.com/watch?v=abc12345678",
                output_name="../../evil",
            )
            self.assertIsNone(error)
            self.assertEqual(manager.downloads[dl_id].output_name, "")

    def test_an_accepted_name_reaches_the_queue_and_the_status_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp}),
                FakeHistory(),
            )
            dl_id, error = manager.start_download(
                url="https://www.youtube.com/watch?v=abc12345678",
                output_name="  Holiday clip  ",
            )
            self.assertIsNone(error)
            self.assertEqual(manager.downloads[dl_id].output_name, "Holiday clip")
            self.assertEqual(
                manager.downloads[dl_id].to_dict().get("outputName"), "Holiday clip"
            )

    def test_the_name_round_trips_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "download-queue.json"
            config = FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            dl_id, error = manager.start_download(
                url="https://www.youtube.com/watch?v=abc12345678",
                output_name="Holiday clip",
            )
            self.assertIsNone(error)
            persisted = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["downloads"][0]["outputName"], "Holiday clip")

            reopened = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(reopened.downloads[dl_id].output_name, "Holiday clip")

    def test_a_traversal_name_written_into_the_queue_file_is_refused_on_restore(self):
        # The queue document is a file on disk. A name written by an older,
        # laxer build - or by hand - must not become an output path just
        # because it survived to a restart.
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "download-queue.json"
            config = FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            dl_id, error = manager.start_download(
                url="https://www.youtube.com/watch?v=abc12345678",
                output_name="Holiday clip",
            )
            self.assertIsNone(error)
            document = json.loads(queue_path.read_text(encoding="utf-8"))
            for record in document["downloads"]:
                record["outputName"] = "../../evil"
            queue_path.write_text(json.dumps(document), encoding="utf-8")

            reopened = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(reopened.downloads[dl_id].output_name, "")

    def test_the_argv_uses_the_name_for_a_single_download_only(self):
        # A playlist shares one output template across every entry, so a single
        # stem would have each item overwrite the last.
        harness = AnySiteDownloadArgvTests()
        single = harness._argv_for(
            "https://example.com/video", with_cookies=False,
            output_name="Holiday clip",
        )
        playlist = harness._argv_for(
            "https://example.com/playlist/season-one", with_cookies=False,
            output_name="Holiday clip",
        )
        self.assertEqual(single[single.index("-o") + 1], "Holiday clip.%(ext)s")
        self.assertNotEqual(playlist[playlist.index("-o") + 1], "Holiday clip.%(ext)s")

    def test_a_playlist_run_that_names_one_item_keeps_the_name(self):
        # The staging dialog queues a renamed row as its own download with a
        # single --playlist-items entry. That is one file, so one stem cannot
        # overwrite anything, and dropping the name discarded the whole
        # per-item naming feature.
        harness = AnySiteDownloadArgvTests()
        one = harness._argv_for(
            "https://example.com/playlist/season-one", with_cookies=False,
            output_name="Holiday clip", playlist_items=[3],
        )
        self.assertEqual(one[one.index("-o") + 1], "Holiday clip.%(ext)s")
        self.assertEqual(one[one.index("--playlist-items") + 1], "3")
        several = harness._argv_for(
            "https://example.com/playlist/season-one", with_cookies=False,
            output_name="Holiday clip", playlist_items=[3, 4],
        )
        self.assertNotEqual(
            several[several.index("-o") + 1], "Holiday clip.%(ext)s")

    def test_the_api_accepts_the_field(self):
        self.assertIn("outputName", ad.DOWNLOAD_REQUEST_ALLOWED_FIELDS)


class QueueRollbackTests(unittest.TestCase):
    """A rejected queue mutation puts the download back exactly as it was."""

    def _manager(self, tmpdir):
        return ad.DownloadManager(
            FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
            FakeHistory(),
        )

    def _failed(self, manager, *, code="network-unreachable", requires_auth=False):
        dl = ad.Download("dl_rollback", "https://www.youtube.com/watch?v=abc12345678")
        dl.status = "failed"
        dl.error = "boom"
        dl.error_code = code
        dl.error_advice = "advice"
        dl.error_action = "retry"
        dl.requires_auth = requires_auth
        dl.progress = 42.0
        dl.filename = "half.mp4"
        manager.downloads[dl.id] = dl
        return dl

    def test_a_failed_write_on_the_needs_auth_path_rolls_back(self):
        # The rollback here used to unpack 14 of 15 packed fields and raise
        # ValueError *instead of* restoring, stranding the download in
        # needs-auth with its queue order already bumped. A retryable code is
        # required to reach the branch at all — a non-retryable one is
        # rejected earlier by the precondition gate.
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            dl = self._failed(manager, requires_auth=True)
            before = {
                name: getattr(dl, name) for name in ad.RETRY_ROLLBACK_FIELDS
            }
            manager._persist_locked = lambda: False

            ok, err = manager.retry(dl.id)

            self.assertFalse(ok)
            self.assertIsNotNone(err)
            for name, value in before.items():
                with self.subTest(field=name):
                    self.assertEqual(getattr(dl, name), value)

    def test_a_failed_write_on_the_ordinary_retry_path_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            dl = self._failed(manager)
            before = {
                name: getattr(dl, name) for name in ad.RETRY_ROLLBACK_FIELDS
            }
            manager._persist_locked = lambda: False

            ok, _err = manager.retry(dl.id)

            self.assertFalse(ok)
            for name, value in before.items():
                with self.subTest(field=name):
                    self.assertEqual(getattr(dl, name), value)

    def test_a_failed_write_on_resume_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir)
            dl = self._failed(manager)
            dl.status = "paused"
            before = {
                name: getattr(dl, name) for name in ad.RESUME_ROLLBACK_FIELDS
            }
            manager._persist_locked = lambda: False

            ok, _err = manager.resume_download(dl.id)

            self.assertFalse(ok)
            for name, value in before.items():
                with self.subTest(field=name):
                    self.assertEqual(getattr(dl, name), value)

    def test_the_snapshot_covers_every_field_each_path_mutates(self):
        # Track the real retry mutation and force persistence to fail. Every
        # field touched by the rollback path must be represented in the
        # snapshot, otherwise a future retry would leave a half-applied item.
        class TrackingDownload(ad.Download):
            def __setattr__(self, name, value):
                if getattr(self, "track_writes", False):
                    self.writes.add(name)
                super().__setattr__(name, value)

        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        download = TrackingDownload(
            "dl_snapshot_tracking",
            "https://example.com/video",
        )
        download.status = "failed"
        download.error_code = "network-unreachable"
        download.writes = set()
        download.track_writes = True
        manager.downloads[download.id] = download
        manager._persist_locked = lambda: False

        ok, _error = manager.retry(download.id)

        self.assertFalse(ok)
        missing = sorted(
            download.writes - set(ad.RETRY_ROLLBACK_FIELDS) - {"track_writes"}
        )
        self.assertEqual(missing, [])

    def test_restore_is_the_inverse_of_snapshot(self):
        dl = ad.Download("dl_x", "https://example.com/v")
        dl.status = "failed"
        dl.progress = 12.5
        snapshot = ad.snapshot_download_fields(dl, ad.RETRY_ROLLBACK_FIELDS)
        dl.status = "pending"
        dl.progress = 0.0
        ad.restore_download_fields(dl, snapshot)
        self.assertEqual(dl.status, "failed")
        self.assertEqual(dl.progress, 12.5)


class BlockedDownloadRecoveryTests(unittest.TestCase):
    """The states that block a download must offer the control that fixes them."""

    def test_max_file_size_round_trips_and_needs_auth_reaches_sign_ins(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-recovery-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

qt = QApplication(["recovery-pin"])
qt.setStyleSheet(app.STYLESHEET)
app.MainWindow._start_instance_command_listener = lambda self: None
app.MainWindow._stop_instance_command_listener = lambda self: None
app.MainWindow._start_readiness_probe = lambda self: None
app.MainWindow._refresh_tools_status = lambda self: None

config = app.Config()
config.update({
    "CloseToTray": False,
    "StartMinimized": False,
    "DownloadPath": temp_dir,
    "AudioDownloadPath": temp_dir,
})
manager = app.DownloadManager(config, app.History())
manager.pause_intake()
window = app.MainWindow(config, manager, app.History())
window._animate_page = lambda: None
window.update_timer.stop()
window.cleanup_timer.stop()
window.tools_status_timer.stop()
window.show()
qt.processEvents()

# The `skipped` reason tells the user to change this, so it needs a control.
window._nav_click("Settings")
qt.processEvents()
window.cfg_maxsize.setValue(250)
window._save_settings()
qt.processEvents()
assert config.get("MaxFileSizeMB") == 250, "max file size must persist"
assert window.cfg_maxsize.specialValueText() == "No limit", "0 needs plain-language copy"

reloaded = app.MainWindow(config, manager, app.History())
reloaded.update_timer.stop()
reloaded.cleanup_timer.stop()
reloaded.tools_status_timer.stop()
assert reloaded.cfg_maxsize.value() == 250, "max file size must reload"
reloaded.close()

def row_actions():
    window._nav_click("Download")
    window._downloads_signature = None
    window._update_ui()
    qt.processEvents()
    # Retired rows are released with deleteLater, so without letting the
    # deferred deletions run findChildren still returns the previous row's
    # buttons and the assertions below pass or fail for the wrong reason.
    QTest.qWait(150)
    return [b.text() for b in window.findChildren(QPushButton)
            if b.isVisible() and b.text()]

blocked = app.Download("dl_auth", "https://vimeo.com/ondemand/private", output_dir=temp_dir)
blocked.status = "needs-auth"
blocked.title = "Private film"
manager.downloads["dl_auth"] = blocked
assert "Add sign-in" in row_actions(), "a blocked non-YouTube download needs a way in"

button = next(b for b in window.findChildren(QPushButton)
              if b.isVisible() and b.text() == "Add sign-in")
button.click()
qt.processEvents()
assert window._page_names[window.tabs.currentIndex()] == "Sign-ins"
assert "vimeo.com" in window.site_login_url.text(), "the site should be prefilled"

# YouTube keeps using the extension's cookie bridge, so no store prompt there.
manager.downloads.clear()
youtube = app.Download("dl_yt", "https://www.youtube.com/watch?v=abc", output_dir=temp_dir)
youtube.status = "needs-auth"
youtube.title = "Members video"
manager.downloads["dl_yt"] = youtube
assert "Add sign-in" not in row_actions(), "YouTube auth is the extension's job"
window.close()
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_skipped_size_message_names_a_control_that_exists(self):
        # The preceding real-window round trip proves the control persists.
        # This check ties the terminal explanation to that stored setting.
        self.assertIn("MaxFileSizeMB", ad.DEFAULT_CONFIG)
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({
                "DownloadPath": tmpdir,
                "AudioDownloadPath": tmpdir,
                "MaxFileSizeMB": 25,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            download = ad.Download("dl", "https://archive.org/details/x", output_dir=tmpdir)
            reason = manager._empty_result_reason(download)
            self.assertIn("Max file size", reason)
            self.assertIn("25 MB", reason)


class SiteLoginDurabilityTests(unittest.TestCase):
    """The sign-in store gets the same durability contract as every other
    companion store, and never leaves a live session in an unlisted jar."""

    EXPORT = ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tSECRET"

    def test_manager_wires_the_atomic_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            store = manager.site_logins
            self.assertIsNotNone(store._writer,
                                 "a torn index write must not be possible")
            self.assertIsNotNone(store._reader)

            calls = []
            original = ad.atomic_write_json

            def spy(path, data):
                calls.append(Path(path).name)
                return original(path, data)

            with mock.patch.object(ad, 'atomic_write_json', spy):
                result, error = store.import_netscape_text("x.com", self.EXPORT)
            self.assertIsNone(error)
            self.assertEqual(result["site"], "x.com")
            self.assertIn(ad.SITE_LOGIN_INDEX_NAME, calls,
                          "the index must be written through atomic_write_json")

    def test_failed_index_write_rolls_back_the_jar(self):
        def full_disk(path, data):
            # atomic_write_json reports failure by raising, so the fake has to
            # fail the same way or it proves nothing about the real writer.
            raise OSError(28, "No space left on device")

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(
                tmpdir,
                reader=lambda path, fallback: fallback,
                writer=full_disk,
            )
            result, error = store.import_netscape_text("x.com", self.EXPORT)

            self.assertIsNone(result)
            self.assertIn("rolled back", error)
            jar = Path(tmpdir) / ad.SITE_LOGIN_DIRNAME / "x.com.txt"
            self.assertFalse(
                jar.exists(),
                "an unlisted jar has no Remove button, so it must not survive",
            )
            self.assertEqual(store.entries(), [])

    def test_remove_keeps_the_index_and_jar_when_index_write_fails(self):
        writes = {"fail": False}

        def writer(path, data):
            if writes["fail"]:
                raise OSError(28, "No space left on device")
            ad.atomic_write_json(path, data)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(
                tmpdir,
                reader=ad.load_json_file,
                writer=writer,
            )
            result, error = store.import_netscape_text("x.com", self.EXPORT)
            self.assertIsNone(error)
            self.assertEqual(result["site"], "x.com")
            writes["fail"] = True

            self.assertFalse(store.remove("x.com"))
            jar = Path(tmpdir) / ad.SITE_LOGIN_DIRNAME / "x.com.txt"
            index = Path(tmpdir) / ad.SITE_LOGIN_DIRNAME / ad.SITE_LOGIN_INDEX_NAME
            self.assertTrue(jar.exists())
            self.assertIn("x.com", json.loads(index.read_text(encoding="utf-8"))["sites"])
            self.assertEqual(store.entries()[0]["site"], "x.com")

    def test_a_jar_that_cannot_be_deleted_keeps_its_index_row(self):
        # The other half of the test above. The row is dropped first so an
        # index failure cannot have already deleted the jar, but an unlink
        # that fails after that left the jar on disk with nothing listing
        # it: entries() cannot see it, so the UI has no Remove to offer.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(
                tmpdir, reader=ad.load_json_file, writer=ad.atomic_write_json,
            )
            result, error = store.import_netscape_text("x.com", self.EXPORT)
            self.assertIsNone(error)
            self.assertEqual(result["site"], "x.com")
            jar = Path(tmpdir) / ad.SITE_LOGIN_DIRNAME / "x.com.txt"
            self.assertTrue(jar.exists())

            real_unlink = Path.unlink

            def unlink(self, *args, **kwargs):
                if self.name == "x.com.txt":
                    raise OSError(13, "Permission denied")
                return real_unlink(self, *args, **kwargs)

            with mock.patch.object(Path, "unlink", unlink):
                self.assertFalse(store.remove("x.com"))

            self.assertTrue(jar.exists())
            self.assertEqual(
                [entry["site"] for entry in store.entries()], ["x.com"],
                "the jar is still on disk, so the row that offers Remove has "
                "to still be there too",
            )

    def test_export_reports_its_site_without_a_second_index_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(tmpdir)
            store.import_netscape_text("x.com", self.EXPORT)

            reads = []
            original = store._load_index

            def counting():
                reads.append(1)
                return original()

            store._load_index = counting
            target = Path(tmpdir) / "per-download.txt"
            path, key = store.export_jar_for_site("https://x.com/a/status/1", target)

            self.assertTrue(path)
            self.assertEqual(key, "x.com")
            self.assertEqual(len(reads), 1,
                             "the scheduler needs the key and the jar from one lookup")

    def test_export_reports_no_site_when_none_is_stored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(tmpdir)
            path, key = store.export_jar_for_site(
                "https://vimeo.com/1", Path(tmpdir) / "out.txt"
            )
            self.assertIsNone(path)
            self.assertEqual(key, "")

    def test_successful_import_survives_a_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            manager.site_logins.import_netscape_text("x.com", self.EXPORT)

            reopened = ad.DownloadManager(config, FakeHistory())
            sites = [entry["site"] for entry in reopened.site_logins.entries()]
            self.assertIn("x.com", sites)
            self.assertEqual(reopened.site_logins.site_key_for_url("https://x.com/a"),
                             "x.com")


class DeferredQueuePersistTests(unittest.TestCase):
    """The queue write no longer happens under the manager lock."""

    def _manager(self, tmpdir, writer):
        """A real manager whose store writes through `writer`.

        The manager builds its own store, so the writer is swapped rather
        than injected: everything else about the persist path stays the
        production one, which is the point of the assertions below.
        """
        manager = ad.DownloadManager(
            FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
            FakeHistory(),
            queue_path=Path(tmpdir) / "download-queue.json",
        )
        manager._queue_store._writer = writer
        return manager

    def test_the_writer_thread_does_not_hold_the_manager_lock(self):
        # The Qt main thread takes this same lock every 500 ms via
        # _update_ui. If the write happened under it, a slow or
        # BitLocker-throttled disk would be a visible stall.
        observed = []
        written = threading.Event()

        def writer(_path, payload):
            observed.append({
                "thread": threading.current_thread().name,
                "records": len(payload.get("downloads", [])),
            })
            written.set()

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir, writer)
            download = ad.Download("dl_defer", "https://example.com/video")
            download.status = "queued"
            with manager._lock:
                manager.downloads[download.id] = download
                manager._persist_async_locked()
                # The strongest statement available: the write COMPLETES
                # while this thread is still holding the lock. It therefore
                # neither runs under the lock nor waits for it, which is the
                # whole of what this change is for.
                self.assertTrue(
                    written.wait(5),
                    "the write did not finish while the lock was held, so it "
                    "is still waiting on it",
                )
            self.assertTrue(manager.flush_persistence())

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["thread"], "AstraDownloaderQueueWriter")
        self.assertNotEqual(
            observed[0]["thread"], threading.current_thread().name,
            "the write has to leave the caller's thread as well as its lock",
        )
        self.assertEqual(observed[0]["records"], 1)

    def test_a_burst_of_snapshots_collapses_to_the_newest(self):
        # The document is a full snapshot, so an older one is not just
        # redundant, it is wrong to write after a newer one.
        release = threading.Event()
        payloads = []

        def writer(_path, payload):
            payloads.append(payload)
            release.wait(5)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir, writer)
            for index in range(5):
                download = ad.Download(
                    f"dl_burst_{index}", "https://example.com/video")
                download.status = "queued"
                with manager._lock:
                    manager.downloads[download.id] = download
                    manager._persist_async_locked()
            release.set()
            self.assertTrue(manager.flush_persistence())

        self.assertLess(len(payloads), 5, payloads)
        self.assertEqual(
            len(payloads[-1]["downloads"]), 5,
            "the last write has to carry every record",
        )

    def test_a_flush_cannot_return_true_with_a_payload_unwritten(self):
        # `_persist_idle` was cleared outside the lock that sets the payload,
        # so a flush landing between the two saw the flag the writer left set
        # on its last drain and returned having written nothing — exactly the
        # snapshot cancel_all flushes for.
        writes = []
        gate = threading.Event()

        def writer(_path, payload):
            gate.wait(5)
            writes.append(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir, writer)
            first = ad.Download("dl_flush_1", "https://example.com/video")
            first.status = "queued"
            with manager._lock:
                manager.downloads[first.id] = first
                manager._persist_async_locked()
            gate.set()
            self.assertTrue(manager.flush_persistence())
            self.assertEqual(len(writes), 1)

            # The writer is now idle. Queue another and flush immediately.
            second = ad.Download("dl_flush_2", "https://example.com/video")
            second.status = "queued"
            with manager._lock:
                manager.downloads[second.id] = second
                manager._persist_async_locked()
            self.assertTrue(manager.flush_persistence())
            self.assertEqual(
                len(writes), 2,
                "the flush returned before the second snapshot was written",
            )
            self.assertEqual(len(writes[-1]["downloads"]), 2)

    def test_a_flush_starts_a_writer_that_has_already_retired(self):
        # A payload queued while the writer was retiring has no live thread
        # until someone starts one; the flusher has to be able to.
        writes = []
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir, lambda _p, payload: writes.append(payload))
            download = ad.Download("dl_retired", "https://example.com/video")
            download.status = "queued"
            with manager._lock:
                manager.downloads[download.id] = download
                manager._persist_async_locked()
            # Simulate the retirement window: a pending payload, no thread.
            manager._persist_thread = None
            self.assertTrue(manager.flush_persistence())
            self.assertTrue(writes, "a retired writer left the payload unwritten")

    def test_the_drain_helper_reaches_the_composition_root(self):
        # conftest guards with `if callable(...)`, so a helper that never got
        # re-exported fails soft and the drain silently does nothing.
        self.assertTrue(callable(getattr(ad, "flush_all_persistence", None)))
        self.assertTrue(ad.flush_all_persistence())

    def test_a_restored_download_keeps_its_own_output_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "download-queue.json"
            config = FakeConfig({
                "DownloadPath": tmpdir, "AudioDownloadPath": tmpdir,
            })
            manager = ad.DownloadManager(
                config, FakeHistory(), queue_path=queue_path)
            dl_id, error = manager.start_download(
                "https://www.youtube.com/watch?v=templateQueue",
                output_template="%(uploader)s/%(title)s.%(ext)s",
            )
            self.assertIsNone(error)
            expected = manager.downloads[dl_id].output_template
            self.assertTrue(expected)
            self.assertTrue(manager.flush_persistence())

            restored = ad.DownloadManager(
                config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(
                restored.downloads[dl_id].output_template, expected,
                "a subscription's template has to survive a restart",
            )
            self.assertTrue(restored.flush_persistence())

    def test_a_failed_deferred_write_is_reported_rather_than_lost(self):
        # There is no return path to check, so the sticky persistence notice
        # is the whole of how the user learns about it.
        def writer(_path, _payload):
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._manager(tmpdir, writer)
            download = ad.Download("dl_fail", "https://example.com/video")
            download.status = "queued"
            with manager._lock:
                manager.downloads[download.id] = download
                manager._persist_async_locked()
            self.assertTrue(manager.flush_persistence())
            self.assertIn("queue", manager.persistence_notice().lower())
            # The mutation stands: a disk that could not be written is not a
            # reason to pretend the user's cancel did not happen.
            self.assertIn("dl_fail", manager.downloads)

    def test_the_rollback_sites_still_write_synchronously(self):
        # Anything that undoes a mutation on a failed write needs the answer
        # before it releases the lock, so those sites keep _persist_locked.
        source = inspect.getsource(ad.DownloadManagerCore)
        self.assertIn("if not self._persist_locked():", source)
        self.assertIn("self._persist_async_locked()", source)


class FailureStateBelongsToOneRunTests(unittest.TestCase):
    """A run's own output must not decide the next run's outcome.

    Two defects with the same shape. The classification chain re-derived the
    error code from the joined last-thirty-lines after the two-pass
    classifier had already chosen one, so a routine warning outranked the
    real ERROR. And three flags written from one yt-dlp process were never
    cleared when a retry started another one.
    """

    SABR_WARNING = (
        "WARNING: [youtube] Some tv client https formats have been skipped as "
        "they are missing a url. YouTube is forcing SABR streaming for this "
        "client."
    )

    def test_a_routine_sabr_warning_does_not_outrank_the_real_error(self):
        lines = [
            self.SABR_WARNING,
            "ERROR: [youtube] abc: Sign in to confirm you are not a bot.",
        ]
        self.assertEqual(
            ad.classify_download_failure(lines[-1], lines), "sign-in-required"
        )
        # The branch that used to override it tested these three substrings.
        # Each is already in the classifier, so it could only ever replace a
        # better answer with sabr-limited, which is not retryable.
        for text in ("no video formats found",
                     "requested format is not available",
                     "SABR streaming"):
            with self.subTest(text=text):
                self.assertEqual(
                    ad.classify_download_failure(f"ERROR: {text}", [text]),
                    "sabr-limited",
                )
        source = inspect.getsource(ad.DownloadManager._run_download)
        self.assertNotIn(
            "'sabr' in combined", source,
            "the failure chain re-decides the code from the joined output",
        )
        self.assertIn("elif not _failure_code:", source)

    def test_sabr_limited_is_still_not_retryable(self):
        # The reason the override mattered: it moved a download into a state
        # with no way out.
        self.assertNotIn("sabr-limited", ad.DOWNLOAD_RETRYABLE_ERROR_CODES)

    def test_a_retry_forgets_what_the_previous_run_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            download = ad.Download(
                "dl_run_flags", "https://example.com/video",
                output_dir=tmpdir,
            )
            # Declared rather than sprung into existence by the output reader.
            self.assertFalse(download.sabr_capped_warning)

            download.status = "failed"
            download.error_code = "po-token-required"
            download.error = "ERROR: PO token required."
            download.finished_time = time.time()
            download.sabr_capped_warning = True
            download.subtitle_written = True
            download.delivered_height = 360

            manager = ad.DownloadManager(config=FakeConfig(), history=FakeHistory())
            manager.downloads[download.id] = download
            manager._schedule = lambda: None

            ok, retry_error = manager.retry(download.id)
            self.assertTrue(ok, retry_error)
            self.assertFalse(
                download.sabr_capped_warning,
                "a stale SABR warning fails the retried run at exit 0, into a "
                "state that is not retryable",
            )
            self.assertFalse(download.subtitle_written)
            self.assertEqual(download.delivered_height, 0)

            # And the retried run's own exit 0 is a completion again.
            download.filename = str(Path(tmpdir) / "clip.mp4")
            Path(download.filename).write_bytes(b"media")
            manager._apply_zero_exit_outcome(download)
            self.assertEqual(download.status, "complete")

    def test_the_run_flags_roll_back_with_everything_else(self):
        for field in ("sabr_capped_warning", "subtitle_written",
                      "delivered_height"):
            with self.subTest(field=field):
                self.assertIn(field, ad.RETRY_ROLLBACK_FIELDS)


class IntermediateSweepStaysInsideItsOwnFilesTests(unittest.TestCase):
    """The sweep runs in the user's download folder after every download."""

    def _sweep(self, folder, final_name):
        download = ad.Download(
            "dl_sweep", "https://example.com/video", output_dir=str(folder),
        )
        download.filename = str(folder / final_name)
        manager = ad.DownloadManager(
            config=FakeConfig({"KeepIntermediateFiles": False}),
            history=FakeHistory(),
        )
        manager._sweep_download_intermediates(download)

    def test_a_file_that_only_starts_the_same_way_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "Movie.mp4").write_bytes(b"final")
            # yt-dlp never writes these. A person does, and the old glob
            # `Movie.f[0-9]*.*` matched every one: [0-9] takes the 1, then *
            # swallows the rest of the name.
            keep = [
                "Movie.f1080p.WEB-DL.mp4",
                "Movie.f4k.remux.mkv",
                "Movie.f2160p.HDR.DV.mkv",
            ]
            for name in keep:
                (folder / name).write_bytes(b"someone else's file")

            self._sweep(folder, "Movie.mp4")

            for name in keep:
                self.assertTrue(
                    (folder / name).is_file(),
                    f"the sweep deleted {name}, which it did not create",
                )
            self.assertTrue((folder / "Movie.mp4").is_file())

    def test_the_intermediates_it_did_write_are_still_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "Movie.mp4").write_bytes(b"final")
            gone = [
                "Movie.f137.mp4",
                "Movie.f140-drc.m4a",
                "Movie.mp4.part",
                "Movie.mp4.ytdl",
            ]
            for name in gone:
                (folder / name).write_bytes(b"intermediate")

            self._sweep(folder, "Movie.mp4")

            for name in gone:
                self.assertFalse(
                    (folder / name).exists(),
                    f"{name} is one of ours and should have been swept",
                )
            self.assertTrue((folder / "Movie.mp4").is_file())


class SettingsBundleExportsWhatIsSavedTests(unittest.TestCase):
    """A session override is a fact about this run, not a setting."""

    def test_a_fallback_port_is_not_exported_as_the_configured_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            store = ad.ConfigStore(
                install_dir=lambda: Path(tmpdir),
                path=lambda: path,
                sanitizer=ad.sanitize_config,
                loader=ad.load_json_file,
                writer=ad.atomic_write_json,
                logger=lambda _message: None,
            )
            store.set("ServerPort", 9751)
            # What the GUI does when the configured port is busy at startup.
            store.set_session("ServerPort", 9760)
            self.assertEqual(store.get("ServerPort"), 9760)
            self.assertEqual(store.get_persisted("ServerPort"), 9751)

            bundle = ad.build_settings_bundle(store)
            self.assertEqual(
                bundle["settings"]["ServerPort"], 9751,
                "the bundle records the transient fallback port, and importing "
                "it makes that permanent",
            )


class SweepStillRemovesEveryShapeItWritesTests(unittest.TestCase):
    """Narrowing the filter must not stop it doing its job."""

    def test_per_format_partials_are_still_swept(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "Movie.mp4").write_bytes(b"final")
            gone = [
                "Movie.f137.mp4",
                "Movie.f140-drc.m4a",
                "Movie.f137.mp4.part",
                "Movie.f251.webm.part",
                "Movie.f137.mp4.ytdl",
                "Movie.f137.mp4.part-Frag0",
            ]
            keep = [
                "Movie.f1080p.mkv",
                "Movie.f1080p.WEB-DL.mp4",
                "Movie.fhls-1080.mp4",
            ]
            for name in gone + keep:
                (folder / name).write_bytes(b"x")

            download = ad.Download(
                "dl_sweep2", "https://example.com/v", output_dir=str(folder),
            )
            download.filename = str(folder / "Movie.mp4")
            ad.DownloadManager(
                config=FakeConfig({"KeepIntermediateFiles": False}),
                history=FakeHistory(),
            )._sweep_download_intermediates(download)

            for name in gone:
                self.assertFalse((folder / name).exists(), f"{name} survived")
            for name in keep:
                self.assertTrue((folder / name).is_file(), f"{name} was deleted")


class EveryPathThatStartsARunClearsItsFlagsTests(unittest.TestCase):
    """retry() was one of three entry points into another run of yt-dlp."""

    def _stale(self, tmpdir, status):
        download = ad.Download(
            "dl_flags", "https://www.youtube.com/watch?v=abc",
            output_dir=tmpdir,
        )
        download.status = status
        download.sabr_capped_warning = True
        download.subtitle_written = True
        download.delivered_height = 360
        return download

    def test_resume_clears_them(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            download = self._stale(tmpdir, "needs-auth")
            download.requires_auth = True
            manager = ad.DownloadManager(config=FakeConfig(), history=FakeHistory())
            manager.downloads[download.id] = download
            manager._schedule = lambda: None
            ok, error = manager.resume_download(
                download.id, cookies=[{"name": "a", "value": "b",
                                       "domain": ".youtube.com"}],
            )
            self.assertTrue(ok, error)
            self.assertFalse(download.sabr_capped_warning)
            self.assertFalse(download.subtitle_written)
            self.assertEqual(download.delivered_height, 0)

    def test_the_needs_auth_reuse_in_start_download_clears_them(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            download = self._stale(tmpdir, "needs-auth")
            download.requires_auth = True
            manager.downloads[download.id] = download
            manager._schedule = lambda: None
            dl_id, error = manager.start_download(
                url=download.url,
                cookies=[{"name": "a", "value": "b", "domain": ".youtube.com"}],
            )
            self.assertIsNone(error)
            self.assertEqual(dl_id, download.id, "the record was not reused")
            self.assertFalse(download.sabr_capped_warning)
            self.assertFalse(download.subtitle_written)
            self.assertEqual(download.delivered_height, 0)


class ARestoredIndexRowMustNotLieTests(unittest.TestCase):
    EXPORT = SiteLoginDurabilityTests.EXPORT

    def test_a_row_is_not_restored_once_the_jar_is_actually_gone(self):
        # Restoring after the jar was deleted lists a sign-in with no session
        # behind it: it reads as stored and fails every download needs-auth.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ad.SiteLoginStore(
                tmpdir, reader=ad.load_json_file, writer=ad.atomic_write_json,
            )
            result, error = store.import_netscape_text("x.com", self.EXPORT)
            self.assertIsNone(error)
            self.assertEqual(result["site"], "x.com")
            root = Path(tmpdir) / ad.SITE_LOGIN_DIRNAME
            credential = store._credential_path(ad.site_login_key("x.com"))
            credential.write_text("{}", encoding="utf-8")

            real_unlink = Path.unlink

            def unlink(self, *args, **kwargs):
                if self.name == credential.name:
                    raise OSError(13, "Permission denied")
                return real_unlink(self, *args, **kwargs)

            with mock.patch.object(Path, "unlink", unlink):
                self.assertFalse(store.remove("x.com"))

            self.assertFalse((root / "x.com.txt").exists())
            self.assertEqual(
                store.entries(), [],
                "the jar is gone, so the row that claims a stored session "
                "must be gone too",
            )


if __name__ == "__main__":
    unittest.main()
