"""Tests for the settings schema, persistence and URL policy."""

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


class ExecutionFloorPolicyTests(unittest.TestCase):
    def test_full_suite_floor_fails_and_names_the_skipped_group(self):
        import pytest

        suite_policy = sys.modules["conftest"]

        class Reporter:
            def __init__(self):
                self.output = []

            def write_sep(self, separator, title, **_kwargs):
                self.output.append(f"{separator}{title}")

            def write_line(self, message, **_kwargs):
                self.output.append(message)

        reporter = Reporter()
        config = types.SimpleNamespace(
            option=types.SimpleNamespace(
                collectonly=False, keyword="", markexpr="", lf=False,
                failedfirst=False, newfirst=False, stepwise=False,
            ),
            invocation_params=types.SimpleNamespace(
                args=(), dir=Path.cwd()
            ),
            pluginmanager=types.SimpleNamespace(
                get_plugin=lambda name: reporter if name == "terminalreporter" else None
            ),
        )
        session = types.SimpleNamespace(
            config=config, exitstatus=pytest.ExitCode.OK
        )
        executed_before = set(suite_policy._executed_nodeids)
        skipped_before = dict(suite_policy._skipped_nodeids)
        try:
            suite_policy._executed_nodeids.clear()
            suite_policy._executed_nodeids.add("one-test")
            suite_policy._skipped_nodeids.clear()
            suite_policy._skipped_nodeids["sixth-test"] = (
                "yt-dlp is not installed in this environment"
            )
            suite_policy.pytest_sessionfinish(session, pytest.ExitCode.OK)
        finally:
            suite_policy._executed_nodeids.clear()
            suite_policy._executed_nodeids.update(executed_before)
            suite_policy._skipped_nodeids.clear()
            suite_policy._skipped_nodeids.update(skipped_before)

        self.assertEqual(session.exitstatus, pytest.ExitCode.TESTS_FAILED)
        self.assertIn("yt-dlp integration (1)", "\n".join(reporter.output))

        config.args = ("astra_downloader",)
        config.option.ignore = []
        config.option.ignore_glob = []
        config.option.deselect = []
        self.assertTrue(
            suite_policy._is_full_suite_run(config),
            "an explicit configured test root is still a full-suite run",
        )
        config.option.ignore = ["astra_downloader/test_build.py"]
        self.assertFalse(
            suite_policy._is_full_suite_run(config),
            "an ignored test path must disable the full-suite floor",
        )


class NormalizationTests(unittest.TestCase):
    def test_normalize_url_rejects_invalid_or_ambiguous_values(self):
        for value in ("", "https://", "javascript:alert(1)", "https://exa mple.com"):
            with self.subTest(value=value):
                url, err = ad.normalize_url(value)
                self.assertIsNone(url)
                self.assertIsNotNone(err)

        url, err = ad.normalize_url("https://example.com/watch?v=abc")
        self.assertEqual(url, "https://example.com/watch?v=abc")
        self.assertIsNone(err)

    def test_normalize_url_rejects_overlong_values_without_truncating(self):
        value = "https://example.com/" + ("a" * 5000)
        url, err = ad.normalize_url(value)
        self.assertIsNone(url)
        self.assertEqual(err, "URL is too long to download safely.")

    def test_sanitize_config_clamps_and_normalizes_untrusted_values(self):
        cfg = ad.sanitize_config({
            "ServerPort": "999999",
            "ServerToken": "short",
            "ConcurrentFragments": "999",
            "RateLimit": "2m",
            "Proxy": "file:///tmp/nope",
            "EmbedMetadata": "false",
            "LegacyHealthTokenEcho": "false",
            "SubLangs": "en,es;<bad>",
        })
        self.assertEqual(cfg["ServerPort"], 65535)
        self.assertEqual(cfg["ConcurrentFragments"], 32)
        self.assertEqual(cfg["RateLimit"], "2M")
        self.assertEqual(cfg["Proxy"], "")
        self.assertEqual(cfg["PacingJitterPercent"], 0)
        self.assertEqual(cfg["JavaScriptRuntime"], "auto")
        self.assertFalse(cfg["EmbedMetadata"])
        self.assertFalse(cfg["LegacyHealthTokenEcho"])
        self.assertEqual(cfg["SubLangs"], "en,esbad")
        self.assertEqual(
            ad.sanitize_config({"SubLangs": "all,live_chat"})["SubLangs"],
            "all,-live_chat",
        )
        self.assertEqual(
            ad.sanitize_config({"SubLangs": "en,live_chat,es"})["SubLangs"],
            "en,es",
        )
        self.assertEqual(ad.sanitize_config({})["SubtitleSleepSeconds"], 1.0)
        self.assertEqual(
            ad.sanitize_config({"SubtitleSleepSeconds": 99})[
                "SubtitleSleepSeconds"
            ],
            60.0,
        )
        for value in (True, "invalid", float("inf"), -1):
            with self.subTest(subtitle_sleep=value):
                self.assertEqual(
                    ad.sanitize_config({"SubtitleSleepSeconds": value})[
                        "SubtitleSleepSeconds"
                    ],
                    0.0,
                )
        self.assertGreaterEqual(len(cfg["ServerToken"]), 16)
        self.assertEqual(
            ad.sanitize_config({})["HistoryRetentionLimit"],
            ad.HISTORY_RETENTION_DEFAULT,
        )
        self.assertEqual(
            ad.sanitize_config({"HistoryRetentionLimit": 1})[
                "HistoryRetentionLimit"
            ],
            ad.HISTORY_RETENTION_MIN,
        )
        self.assertEqual(
            ad.sanitize_config({"HistoryRetentionLimit": 999999})[
                "HistoryRetentionLimit"
            ],
            ad.HISTORY_RETENTION_MAX,
        )

        self.assertEqual(cfg["Theme"], "system")
        self.assertEqual(ad.sanitize_config({"Theme": "LIGHT"})["Theme"], "light")
        self.assertEqual(ad.sanitize_config({"Theme": "neon"})["Theme"], "system")

        node_cfg = ad.sanitize_config({"JavaScriptRuntime": "NODE"})
        self.assertEqual(node_cfg["JavaScriptRuntime"], "node")
        jitter_cfg = ad.sanitize_config({"PacingJitterPercent": 999})
        self.assertEqual(jitter_cfg["PacingJitterPercent"], 100)
        archive_cfg = ad.sanitize_config({
            "WriteInfoJson": "yes",
            "WriteNfo": "yes",
            "WriteDescription": "yes",
            "WriteThumbnail": True,
            "SplitChapters": "true",
            "LiveFromStart": "on",
            "WaitForVideoSeconds": 9999,
        })
        for key in (
            "WriteInfoJson", "WriteNfo", "WriteDescription", "WriteThumbnail",
            "SplitChapters", "LiveFromStart",
        ):
            self.assertTrue(archive_cfg[key], key)
        self.assertEqual(archive_cfg["WaitForVideoSeconds"], 3600)

    def test_nonfinite_integer_values_fall_back_to_safe_defaults(self):
        for value in (float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value):
                self.assertEqual(
                    ad.clamp_int(value, 4, 1, 32),
                    4,
                )
                self.assertEqual(
                    ad.sanitize_config({"ConcurrentFragments": value})[
                        "ConcurrentFragments"
                    ],
                    4,
                )

    def test_first_run_marker_defaults_for_existing_installs_and_is_boolean(self):
        self.assertTrue(ad.DEFAULT_CONFIG["FirstRunComplete"])
        self.assertTrue(ad.sanitize_config({})["FirstRunComplete"])
        self.assertFalse(
            ad.sanitize_config({"FirstRunComplete": "no"})["FirstRunComplete"]
        )
        self.assertIn("FirstRunComplete", ad.BUNDLE_EXCLUDED_SETTINGS)

    def test_network_workaround_settings_are_opt_in_and_shape_checked(self):
        defaults = ad.sanitize_config({})
        self.assertEqual(defaults["ForceIPVersion"], "")
        self.assertEqual(defaults["SourceAddress"], "")
        self.assertEqual(defaults["Xff"], "")
        self.assertEqual(defaults["GeoVerificationProxy"], "")

        valid = ad.sanitize_config({
            "ForceIPVersion": "IPV4",
            "SourceAddress": "2001:db8::10",
            "Xff": "us",
            "GeoVerificationProxy": "https://proxy.example:8443",
        })
        self.assertEqual(valid["ForceIPVersion"], "ipv4")
        self.assertEqual(valid["SourceAddress"], "2001:db8::10")
        self.assertEqual(valid["Xff"], "US")
        self.assertEqual(valid["GeoVerificationProxy"], "https://proxy.example:8443")

        invalid = ad.sanitize_config({
            "ForceIPVersion": "dual-stack",
            "SourceAddress": "not-an-ip",
            "Xff": "US; --no-playlist",
            "GeoVerificationProxy": "http://[",
        })
        self.assertEqual(invalid["ForceIPVersion"], "")
        self.assertEqual(invalid["SourceAddress"], "")
        self.assertEqual(invalid["Xff"], "")
        self.assertEqual(invalid["GeoVerificationProxy"], "")

    def test_site_profiles_are_bounded_normalized_and_secret_free(self):
        profiles, error = ad.validate_site_profiles([
            {
                "Name": "YouTube archive",
                "Domain": "https://www.youtube.com/",
                "VideoFormat": "mp4",
                "Quality": "1080",
                "Proxy": "https://proxy.example:8443",
                "SleepIntervalSeconds": 4,
                "MaxSleepIntervalSeconds": 2,
            },
        ])
        self.assertIsNone(error)
        self.assertEqual(profiles[0]["Domain"], "youtube.com")
        self.assertEqual(profiles[0]["MaxSleepIntervalSeconds"], 4)
        self.assertNotIn("cookies", profiles[0])
        self.assertNotIn("password", profiles[0])
        self.assertEqual(ad.sanitize_config({"SiteProfiles": profiles})["SiteProfiles"], profiles)

        for value in (
            [{"Name": "same", "Domain": "youtube.com"},
             {"Name": "SAME", "Domain": "vimeo.com"}],
            [{"Name": "bad", "Domain": "youtube.com/watch"}],
            "not-json",
        ):
            with self.subTest(value=value):
                normalized, error = ad.validate_site_profiles(value)
                self.assertIsNone(normalized)
                self.assertTrue(error)

    def test_site_profiles_match_subdomains_and_allow_explicit_one_off_choice(self):
        profiles = [
            {"Name": "YouTube", "Domain": "youtube.com", "Quality": "1080"},
            {"Name": "Studio", "Domain": "studio.youtube.com", "Quality": "720"},
        ]
        self.assertEqual(
            ad.select_site_profile(
                "https://media.studio.youtube.com/watch?v=1", profiles
            )["Name"],
            "Studio",
        )
        self.assertIsNone(
            ad.select_site_profile("https://notyoutube.com/watch?v=1", profiles)
        )
        self.assertEqual(
            ad.select_site_profile(
                "https://vimeo.com/1", profiles, "YouTube"
            )["Quality"],
            "1080",
        )
        self.assertIsNone(
            ad.select_site_profile("https://youtube.com/watch?v=1", profiles, "")
        )

    def test_output_template_bounds_split_long_text_and_preserve_literals(self):
        import config as config_module

        template = "%%(title)s/%(uploader)s/%(title)s.%(ext)s"
        bounded = config_module.bound_output_template_fields(template)

        self.assertEqual(
            bounded,
            "%%(title)s/%(uploader).100B/%(title).100B.%(ext)s",
        )
        self.assertEqual(config_module.bound_output_template_fields(bounded), bounded)
        # Clamped to the split budget and converted to a byte bound; a
        # character precision does not survive because it is not a bound.
        self.assertIn(
            "%(title).100B",
            config_module.bound_output_template_fields(
                "%(title).999s/%(uploader)s.%(ext)s"
            ),
        )

    def test_paths_are_bounded_by_bytes_not_characters(self):
        import config as config_module

        # A four-byte emoji fills a Windows path component three times faster
        # than the character count suggests. This is the case a character
        # bound silently fails.
        emoji = "\U0001f3ac"
        self.assertEqual(len(emoji.encode("utf-8")), 4)

        self.assertEqual(config_module.truncate_utf8_bytes(emoji * 10, 12), emoji * 3)
        self.assertEqual(
            config_module.truncate_utf8_bytes(emoji * 10, 11), emoji * 2,
            "a truncation must never split a character",
        )
        self.assertEqual(config_module.truncate_utf8_bytes("abc", 10), "abc")
        self.assertEqual(config_module.truncate_utf8_bytes("", 10), "")
        self.assertEqual(config_module.truncate_utf8_bytes("abc", 0), "")

        original = config_module._OUTPUT_TEMPLATE_PREVIEW_VALUES["title"]
        config_module._OUTPUT_TEMPLATE_PREVIEW_VALUES["title"] = emoji * 100
        try:
            preview = config_module.output_template_preview(
                "%(title)s.%(ext)s", r"C:\Videos",
            )
        finally:
            config_module._OUTPUT_TEMPLATE_PREVIEW_VALUES["title"] = original

        rendered = preview["relative"].rsplit(".", 1)[0]
        self.assertLessEqual(
            len(rendered.encode("utf-8")), 200,
            "the preview must report the byte-bounded name yt-dlp will write",
        )
        self.assertEqual(
            rendered, emoji * 50,
            "200 bytes of a four-byte character is 50 characters, not 200",
        )

    def test_preview_names_a_folder_segment_over_the_component_limit(self):
        import config as config_module

        # A field expansion cannot exceed the limit - the split budget caps it
        # at 100 bytes - but a literal folder name in the template can, and the
        # total-path check cannot say which component is the problem.
        preview = config_module.output_template_preview(
            ("A" * 260) + "/%(title)s.%(ext)s", "C:\\V",
        )

        self.assertEqual(preview["maxComponentBytes"], 255)
        self.assertEqual(preview["oversizedComponents"], ("A" * 260,))
        self.assertTrue(preview["too_long"])

        safe = config_module.output_template_preview(
            "%(uploader)s/%(title)s.%(ext)s", r"C:\Videos",
        )
        self.assertEqual(safe["oversizedComponents"], ())

    def test_output_template_preview_flags_reserved_names_and_long_paths(self):
        import config as config_module

        normal = config_module.output_template_preview(
            "%(uploader)s/%(title)s.%(ext)s", r"C:\Videos"
        )
        self.assertTrue(normal["valid"])
        self.assertEqual(normal["relative"], "Astra channel\\Example video.mp4")
        self.assertFalse(normal["reserved"])
        self.assertFalse(normal["too_long"])

        reserved = config_module.output_template_preview(
            "CON.%(ext)s", r"C:\Videos"
        )
        self.assertEqual(reserved["reserved"], ("CON",))

        long_path = config_module.output_template_preview(
            "folder/" + ("x" * 250) + ".%(ext)s", r"C:\Videos"
        )
        self.assertTrue(long_path["too_long"])
        invalid = config_module.output_template_preview(
            "%(title)s", r"C:\Videos"
        )
        self.assertFalse(invalid["valid"])

    def test_output_template_preview_matches_literal_percent_and_windows_safety(self):
        import config as config_module

        literal = config_module.output_template_preview(
            "%%(title)s.%(ext)s", r"C:\Videos"
        )
        self.assertEqual(literal["relative"], "%(title)s.mp4")

        for reserved_name in ("CONIN$", "CONOUT$", "COM0", "LPT0"):
            report = config_module.output_template_preview(
                reserved_name + ".%(ext)s", r"C:\Videos"
            )
            self.assertEqual(report["reserved"], (reserved_name,))

        safe = config_module.output_template_preview(
            "CONIN$.%(ext)s", r"C:\Videos", windows_filenames=True
        )
        self.assertEqual(safe["relative"], "_CONIN$.mp4")
        self.assertFalse(safe["reserved"])
        self.assertTrue(safe["windowsFilenames"])

    def test_output_template_preview_checks_the_staging_prefix(self):
        import config as config_module

        staging = "C:\\" + ("staging-" * 30)
        report = config_module.output_template_preview(
            "%(title)s.%(ext)s",
            r"C:\Videos",
            staging_prefix=staging,
        )
        self.assertFalse(report["length"] > report["max_path"])
        self.assertGreater(report["stagingLength"], report["max_path"])
        self.assertTrue(report["too_long"])

    def test_default_download_path_prefers_the_windows_known_folder(self):
        import config as config_module

        known = Path(tempfile.gettempdir()) / "Redirected Videos"
        with mock.patch.object(config_module, "_known_folder_path_windows", return_value=known):
            self.assertEqual(config_module.default_download_path(), str(known))
            self.assertEqual(
                ad.sanitize_config({"DownloadPath": str(known)})["DownloadPath"],
                str(known),
                "an existing configured path must not be rewritten",
            )

    def test_default_download_path_falls_back_to_profile_videos(self):
        import config as config_module

        with mock.patch.object(config_module, "_known_folder_path_windows", return_value=None):
            self.assertEqual(
                config_module.default_download_path(),
                str(Path.home() / "Videos"),
            )

    def test_output_directory_must_be_absolute(self):
        path, err = ad.normalize_output_dir("relative-folder")
        self.assertIsNone(path)
        self.assertEqual(err, "Choose an absolute output folder.")

    def test_output_directory_rejects_overlong_values(self):
        path, err = ad.normalize_output_dir("C:\\" + ("a" * 3000))
        self.assertIsNone(path)
        self.assertEqual(err, "Output folder path is too long.")

    def test_playlist_item_selection_is_bounded_normalized_and_injection_safe(self):
        items, err = ad.normalize_playlist_items(["5", 1, 3, 3])
        self.assertEqual(items, [1, 3, 5])
        self.assertIsNone(err)

        invalid = (
            [],
            "1,2",
            [0],
            [-1],
            [True],
            ["1-3"],
            ["1,3"],
            ["1 --exec calc.exe"],
            list(range(1, 202)),
        )
        for value in invalid:
            with self.subTest(value=value):
                items, err = ad.normalize_playlist_items(value)
                self.assertIsNone(items)
                self.assertTrue(err)


class PersistenceTests(unittest.TestCase):
    def test_owned_config_store_uses_injected_persistence_and_rolls_back(self):
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "owned-config.json"
            durable = {"value": 1}
            errors = []

            def loader(_path, _default):
                return dict(durable)

            def writer(_path, data):
                if data.get("value") == 3:
                    raise OSError("disk full")
                durable.clear()
                durable.update(data)

            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=path,
                sanitizer=lambda data: dict(data),
                loader=loader,
                writer=writer,
                logger=errors.append,
            )
            self.assertTrue(store.update({"value": 2}))
            self.assertEqual(store.get("value"), 2)
            self.assertFalse(store.update({"value": 3}))
            self.assertEqual(store.get("value"), 2)
            self.assertEqual(durable, {"value": 2})
            self.assertEqual(errors, ["Config save failed: disk full"])
            self.assertEqual(Path(config_module.__file__).name, "config.py")

    def test_read_only_config_store_never_writes_on_init_or_explicit_save(self):
        import importlib

        config_module = importlib.import_module("config")
        writes = []
        with tempfile.TemporaryDirectory() as tmp:
            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=Path(tmp) / "cfg.json",
                sanitizer=lambda data: dict(data),
                loader=lambda _path, _default: {"value": 1},
                writer=lambda _path, data: writes.append(dict(data)),
                logger=self.fail,
                read_only=True,
            )
            self.assertEqual(store.get("value"), 1)
            store.set("value", 2)
            self.assertFalse(store.save())
            self.assertFalse(store.update({"value": 3}))

        self.assertEqual(writes, [])

    def test_nonfinite_config_values_fall_back_before_defaults_are_saved(self):
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            for index, literal in enumerate(("1e999", "-1e999", "NaN")):
                with self.subTest(literal=literal):
                    path = Path(tmp) / f"config-{index}.json"
                    path.write_text(
                        '{"ConcurrentFragments": ' + literal + '}',
                        encoding="utf-8",
                    )
                    errors = []
                    store = config_module.ConfigStore(
                        install_dir=Path(tmp),
                        path=path,
                        sanitizer=config_module.sanitize_config,
                        loader=config_module.load_json_file,
                        writer=config_module.atomic_write_json,
                        logger=errors.append,
                    )

                    self.assertEqual(store.get("ConcurrentFragments"), 4)
                    self.assertEqual(
                        json.loads(path.read_text(encoding="utf-8"))[
                            "ConcurrentFragments"
                        ],
                        4,
                    )
                    self.assertEqual(errors, [])

    def test_config_writes_a_schema_version_and_preserves_future_keys(self):
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            future_version = config_module.CONFIG_SCHEMA_VERSION + 1
            future_value = {"enabled": True, "options": ["future", 7]}
            path.write_text(json.dumps({
                "schemaVersion": future_version,
                "ConcurrentFragments": 8,
                "FutureSetting": future_value,
            }), encoding="utf-8")
            messages = []
            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=path,
                sanitizer=config_module.sanitize_config,
                loader=config_module.load_json_file,
                writer=config_module.atomic_write_json,
                logger=messages.append,
                schema_version=config_module.CONFIG_SCHEMA_VERSION,
            )

            self.assertEqual(store.get("ConcurrentFragments"), 8)
            self.assertEqual(store.get("FutureSetting"), None)
            self.assertTrue(any("newer version" in message for message in messages))

            self.assertTrue(store.update({"DownloadRetries": 12}))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schemaVersion"], future_version)
            self.assertEqual(saved["FutureSetting"], future_value)
            self.assertEqual(saved["DownloadRetries"], 12)

    def test_config_migrates_a_missing_schema_version(self):
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"ConcurrentFragments": 6}), encoding="utf-8")
            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=path,
                sanitizer=config_module.sanitize_config,
                loader=config_module.load_json_file,
                writer=config_module.atomic_write_json,
                logger=self.fail,
                schema_version=config_module.CONFIG_SCHEMA_VERSION,
            )

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schemaVersion"], config_module.CONFIG_SCHEMA_VERSION)
            self.assertEqual(store.get("ConcurrentFragments"), 6)

    def test_config_store_quarantines_when_sanitization_rejects_a_document(self):
        import importlib

        config_module = importlib.import_module("config")
        original_records = list(config_module.quarantined_state_files())
        self.addCleanup(
            lambda: config_module._quarantined_state_files.__setitem__(
                slice(None), original_records
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"mode": "reject"}', encoding="utf-8")

            def sanitizer(data):
                if data.get("mode") == "reject":
                    raise ValueError("unsupported configuration document")
                return dict(data)

            errors = []
            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=path,
                sanitizer=sanitizer,
                loader=config_module.load_json_file,
                writer=config_module.atomic_write_json,
                logger=errors.append,
            )

            self.assertEqual(store.data, {})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})
            record = next(
                record
                for record in config_module.quarantined_state_files()
                if record["path"] == str(path)
            )
            self.assertEqual(
                Path(record["backup"]).read_text(encoding="utf-8"),
                '{"mode": "reject"}',
            )
            self.assertTrue(errors)

    def test_session_override_is_never_persisted_by_later_saves(self):
        # Session-only port fallback regression: a bind conflict overrides
        # ServerPort for the running process, but ANY later full-config save
        # (e.g. the yt-dlp update-check timestamp write) must keep the user's
        # configured port on disk.
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            durable = {"ServerPort": 9751}

            def writer(_path, data):
                durable.clear()
                durable.update(data)

            store = config_module.ConfigStore(
                install_dir=Path(tmp),
                path=Path(tmp) / "cfg.json",
                sanitizer=lambda data: dict(data),
                loader=lambda _path, _default: dict(durable),
                writer=writer,
                logger=self.fail,
            )
            store.set_session("ServerPort", 9761)
            # Live readers see the fallback; persistence helpers do not.
            self.assertEqual(store.get("ServerPort"), 9761)
            self.assertEqual(store.data["ServerPort"], 9761)
            self.assertEqual(store.get_persisted("ServerPort"), 9751)
            # An unrelated timestamp save must not leak the fallback port.
            store.set("LastYtDlpUpdateCheck", "2026-07-27T00:00:00")
            self.assertTrue(store.save())
            self.assertEqual(durable["ServerPort"], 9751)
            self.assertTrue(store.update({"AutoUpdateYtDlp": False}))
            self.assertEqual(durable["ServerPort"], 9751)
            # Explicitly saving the key clears the override.
            self.assertTrue(store.update({"ServerPort": 9800}))
            self.assertEqual(durable["ServerPort"], 9800)
            self.assertEqual(store.get("ServerPort"), 9800)

    def test_start_server_port_fallback_uses_session_override(self):
        import gui as gui_module

        class SessionConfig(FakeConfig):
            def __init__(self):
                super().__init__({"ServerPort": 9751})
                self.session = {}

            def set_session(self, key, value):
                self.session[key] = value

            def get(self, key, default=None):
                return self.session.get(key, super().get(key, default))

            def get_persisted(self, key, default=None):
                return super().get(key, default)

        class Server:
            backend = "fixture"

            def run(self):
                raise AssertionError("the serving thread must be startable without running in the test")

        class Thread:
            created = []

            def __init__(self, target=None, name=None, daemon=None):
                self.target = target
                self.name = name
                self.daemon = daemon
                self.created.append(self)

            def start(self):
                return None

        config = SessionConfig()
        logs = []
        window = types.SimpleNamespace(
            config=config,
            _server_starting=True,
            _server_start_cancel=None,
            _server_start_thread=object(),
            _dependencies={
                "clamp_int": ad.clamp_int,
                "maybe_auto_update_ytdlp": lambda *_args: None,
            },
            _value=lambda name: {
                "SERVER_PORT": 9751,
            }[name],
            _append_log=logs.append,
            _sync_connection_ui=lambda: logs.append("connection synced"),
            _update_server_ui=lambda: None,
            _show_server_error=lambda message: logs.append(message),
            _subscription_manager=lambda: None,
            dl_manager=types.SimpleNamespace(active_count=lambda: 0),
            log_message=types.SimpleNamespace(emit=lambda *_args: None),
        )

        with mock.patch.object(gui_module.threading, "Thread", Thread):
            gui_module.MainWindowCore._finish_server_start(
                window,
                {"ok": True, "port": 9761, "server": Server()},
            )

        self.assertEqual(config.get_persisted("ServerPort"), 9751)
        self.assertEqual(config.get("ServerPort"), 9761)
        self.assertEqual(config.session["ServerPort"], 9761)
        self.assertIn("connection synced", logs)
        self.assertEqual([thread.name for thread in Thread.created], ["server-serve"])

    def test_settings_port_row_explains_a_session_fallback(self):
        # During a bind-conflict session the dashboard shows the bound fallback
        # port while the Settings spinbox shows the configured one. Without the
        # hint the two surfaces silently disagree.
        class SessionConfig(FakeConfig):
            def __init__(self):
                super().__init__({"ServerPort": 9751})
                self.session_port = 9761

            def get(self, key, default=None):
                if key == "ServerPort":
                    return self.session_port
                return super().get(key, default)

            def get_persisted(self, key, default=None):
                return super().get(key, default)

        class Field:
            def __init__(self):
                self.value = None
                self.description = None
                self.visible = None

            def setText(self, value):
                self.value = value

            def setAccessibleDescription(self, value):
                self.description = value

        config = SessionConfig()
        hint = Field()
        port = Field()
        visibility = []
        window = types.SimpleNamespace(
            config=config,
            _dependencies={"clamp_int": ad.clamp_int},
            _value=lambda name: {"SERVER_PORT": 9751}[name],
            dash_endpoint=Field(),
            stat_port=Field(),
            cfg_port_session_hint=hint,
            cfg_port=port,
            _set_settings_filter_hidden=lambda widget, hidden: (
                visibility.append((widget, hidden))
            ),
        )

        gui_module_for_tests().MainWindowCore._sync_connection_ui(window)

        self.assertEqual(window.dash_endpoint.value, "http://127.0.0.1:9761")
        self.assertEqual(window.stat_port.value, "9761")
        self.assertIn("fallback port 9761", hint.value)
        self.assertIn("retry 9751", port.description)
        self.assertEqual(visibility[-1], (hint, False))

    def test_owned_history_store_enforces_injected_retention_limit(self):
        import importlib

        config_module = importlib.import_module("config")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "owned-history.json"
            durable = []

            def loader(_path, _default):
                return list(durable)

            def writer(actual_path, data):
                durable[:] = data
                actual_path.touch(exist_ok=True)

            store = config_module.HistoryStore(
                path=path,
                sanitizer=lambda entries: list(entries),
                loader=loader,
                writer=writer,
                logger=self.fail,
                limit=2,
            )
            for value in (1, 2, 3):
                self.assertTrue(store.add({"value": value}))
            self.assertEqual(store.load(), [{"value": 2}, {"value": 3}])
            self.assertEqual(Path(config_module.__file__).name, "config.py")

    def test_history_retention_reads_updated_config_without_restarting_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = ad.HISTORY_PATH
            ad.HISTORY_PATH = Path(tmp) / "history.json"
            config = FakeConfig({"HistoryRetentionLimit": 100})
            try:
                history = ad.History(config)
                history.replace([
                    {"id": f"old-{index}", "title": str(index)}
                    for index in range(100)
                ])
                self.assertEqual(history.retention_limit(), 100)
                config.set("HistoryRetentionLimit", 102)
                self.assertEqual(history.retention_limit(), 102)
                for index in range(3):
                    history.add({"id": f"new-{index}", "title": str(index)})
                retained = history.load()
                self.assertEqual(
                    len(retained),
                    102,
                )
                self.assertEqual(retained[0]["id"], "old-1")
                self.assertEqual(retained[-1]["id"], "new-2")
            finally:
                ad.HISTORY_PATH = old_path

    def test_history_load_backs_up_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.HISTORY_PATH
            try:
                ad.HISTORY_PATH = Path(tmp) / "history.json"
                ad.HISTORY_PATH.write_text("{not-json", encoding="utf-8")
                history = ad.History()
                self.assertEqual(history.load(), [])
                backups = list(Path(tmp).glob("history.json.corrupt-*"))
                self.assertEqual(len(backups), 1)
            finally:
                ad.HISTORY_PATH = original

    def test_history_view_can_identify_a_quarantined_store(self):
        import gui

        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.json"
            window = types.SimpleNamespace(
                history_mgr=types.SimpleNamespace(
                    _resolve_path=lambda: history_path,
                ),
                _dependencies={
                    "quarantined_state_files": lambda: [{
                        "path": str(history_path),
                        "backup": str(history_path) + ".corrupt-fixture",
                    }],
                },
            )
            self.assertTrue(gui.MainWindowCore._history_is_quarantined(window))

    def test_history_view_explains_loading_and_unreadable_states(self):
        from PySide6.QtWidgets import QApplication, QLabel, QPushButton

        _get_qapp_or_skip(self)

        class BrokenHistory(FakeHistory):
            def load(self):
                raise OSError("fixture history is unreadable")

        history = BrokenHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                window._refresh_history()
                QApplication.processEvents()
                labels = [label.text() for label in window.findChildren(QLabel)]
                buttons = [button.text() for button in window.findChildren(QPushButton)]
                self.assertEqual(window.history_meta.text(), "History unavailable")
                self.assertIn("History could not be read", labels)
                self.assertIn("Open diagnostics", buttons)
                self.assertIn(
                    "fixture history is unreadable",
                    window.history_page_status.text(),
                )
            finally:
                _retire_test_window(window)

    def test_json_loader_quarantines_oversized_state_before_parsing(self):
        import importlib

        config_module = importlib.import_module('config')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'history.json'
            path.write_bytes(b'[' + (b' ' * 32) + b']')
            result = config_module.load_json_file(path, ['fallback'], max_bytes=8)
            self.assertEqual(result, ['fallback'])
            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(tmp).glob('history.json.corrupt-*'))), 1)

    def test_history_replace_restores_cleared_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.HISTORY_PATH
            try:
                ad.HISTORY_PATH = Path(tmp) / "history.json"
                history = ad.History()
                snapshot = [
                    {"id": "1", "url": "https://example.com/1", "title": "One"},
                    {"id": "2", "url": "https://example.com/2", "title": "Two"},
                ]
                expected = ad.sanitize_history_entries(snapshot)
                history.replace(snapshot)
                self.assertEqual(history.load(), expected)

                history.clear()
                self.assertEqual(history.load(), [])

                history.replace(snapshot)
                self.assertEqual(history.load(), expected)
            finally:
                ad.HISTORY_PATH = original

    def test_history_undo_snapshot_survives_a_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.HISTORY_PATH
            try:
                ad.HISTORY_PATH = Path(tmp) / "history.json"
                history = ad.History()
                snapshot = [{
                    "id": "durable",
                    "url": "https://example.com/durable",
                    "title": "Durable",
                }]
                self.assertTrue(history.save_undo("clearHistory", snapshot))
                reopened = ad.History()
                self.assertEqual(reopened.load_undo("clearHistory"), snapshot)
                self.assertTrue(reopened.clear_undo("clearHistory"))
                self.assertIsNone(reopened.load_undo("clearHistory"))
            finally:
                ad.HISTORY_PATH = original

    def test_config_update_failure_rolls_back_memory_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.CONFIG_PATH
            try:
                ad.CONFIG_PATH = Path(tmp) / "config.json"
                config = ad.Config()
                old_port = config.get("ServerPort")
                old_file = ad.CONFIG_PATH.read_text(encoding="utf-8")

                with mock.patch.object(ad, "atomic_write_json", side_effect=PermissionError("denied")):
                    saved = config.update({"ServerPort": old_port + 1})

                self.assertFalse(saved)
                self.assertEqual(config.get("ServerPort"), old_port)
                self.assertEqual(ad.CONFIG_PATH.read_text(encoding="utf-8"), old_file)
            finally:
                ad.CONFIG_PATH = original

    def test_config_undo_snapshot_survives_a_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.CONFIG_PATH
            try:
                ad.CONFIG_PATH = Path(tmp) / "config.json"
                config = ad.Config()
                snapshot = {"settings": {"Proxy": "https://proxy.example.test"}}
                self.assertTrue(config.save_undo("restoreDefaults", snapshot))
                reopened = ad.Config()
                self.assertEqual(
                    reopened.load_undo("restoreDefaults"), snapshot
                )
                self.assertTrue(reopened.clear_undo("restoreDefaults"))
                self.assertIsNone(reopened.load_undo("restoreDefaults"))
            finally:
                ad.CONFIG_PATH = original

    def test_history_write_failure_is_reported_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ad.HISTORY_PATH
            try:
                ad.HISTORY_PATH = Path(tmp) / "history.json"
                history = ad.History()
                snapshot = [{"id": "1", "url": "https://example.com/1", "title": "One"}]
                self.assertTrue(history.replace(snapshot))
                old_file = ad.HISTORY_PATH.read_text(encoding="utf-8")

                with mock.patch.object(ad, "atomic_write_json", side_effect=OSError("disk full")):
                    self.assertFalse(history.clear())
                    self.assertFalse(history.replace([]))

                self.assertEqual(ad.HISTORY_PATH.read_text(encoding="utf-8"), old_file)
                self.assertEqual(history.load(), ad.sanitize_history_entries(snapshot))
            finally:
                ad.HISTORY_PATH = original


class SiteLoginImportBoundTests(unittest.TestCase):
    def test_first_youtube_sign_in_shows_and_persists_the_linked_warning(self):
        _get_qapp_or_skip(self)
        config = FakeConfig({"YouTubeSignInRiskNoticeShown": False})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            self.assertTrue(window.youtube_sign_in_warning.isHidden())
            self.assertTrue(window._apply_site_login_result({
                "site": "youtube.com",
                "cookies": 3,
                "skipped": 0,
            }, None))
            self.assertFalse(window.youtube_sign_in_warning.isHidden())
            self.assertTrue(window.youtube_sign_in_warning.openExternalLinks())
            self.assertIn("yt-dlp/wiki/Extractors", window.youtube_sign_in_warning.text())
            self.assertIn("public videos unplayable", window.youtube_sign_in_warning.text())
            self.assertTrue(config.get("YouTubeSignInRiskNoticeShown"))

            window.youtube_sign_in_warning.hide()
            self.assertFalse(
                window._show_youtube_sign_in_warning_once("youtube.com")
            )
            self.assertTrue(window.youtube_sign_in_warning.isHidden())
        finally:
            _retire_test_window(window)

    def test_cookie_file_import_reads_bounded_text_and_applies_store_result(self):
        class TextField:
            def __init__(self, value):
                self.value = value

            def text(self):
                return self.value

        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookies.txt"
            cookie_text = (
                "# Netscape HTTP Cookie File\n"
                ".example.com\tTRUE\t/\tTRUE\t2000000000\tsid\tsecret\n"
            )
            cookie_path.write_text(cookie_text, encoding="utf-8")
            imported = {"site": "example.com", "cookies": 1}
            store = mock.Mock()
            store.import_netscape_text.return_value = (imported, None)
            applied = []
            window = types.SimpleNamespace(
                _site_login_store=lambda: store,
                _value=lambda name: ad.MAX_SITE_LOGIN_TEXT_BYTES
                if name == "MAX_SITE_LOGIN_TEXT_BYTES" else None,
                site_login_url=TextField("https://example.com/video"),
                _apply_site_login_result=lambda result, error: applied.append(
                    (result, error)
                ),
                _show_site_login_status=lambda *_args: self.fail(
                    "a valid cookie file should not show an error"
                ),
            )
            with mock.patch.object(
                ad.QFileDialog,
                "getOpenFileName",
                return_value=(str(cookie_path), "Cookie files (*.txt)"),
            ):
                ad.MainWindow._import_site_login_from_file(window)

        store.import_netscape_text.assert_called_once_with(
            "https://example.com/video", cookie_text, source="cookies.txt"
        )
        self.assertEqual(applied, [(imported, None)])

    def test_an_oversized_cookie_file_is_rejected_before_it_is_read(self):
        # The 1 MB cap lives downstream of the read, and the read is on the
        # GUI thread — a huge pick froze the window before the cap applied.
        _get_qapp_or_skip(self)
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with tempfile.TemporaryDirectory() as tmp:
            oversized = Path(tmp) / "cookies.txt"
            oversized.write_bytes(b"x" * (ad.MAX_SITE_LOGIN_TEXT_BYTES + 1))

            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
                try:
                    reads = []
                    real_read_text = Path.read_text

                    def tracking_read_text(self, *args, **kwargs):
                        reads.append(str(self))
                        return real_read_text(self, *args, **kwargs)

                    with mock.patch.object(
                        ad.QFileDialog, "getOpenFileName",
                        return_value=(str(oversized), ""),
                    ), mock.patch.object(Path, "read_text", tracking_read_text):
                        window._import_site_login_from_file()

                    self.assertNotIn(
                        str(oversized), reads,
                        "the oversized file must never be read into memory",
                    )
                    self.assertIn("too large", window.site_login_status.text())
                finally:
                    _retire_test_window(window)


class PathConfinementTests(unittest.TestCase):
    """v1.2.0 S1 — outputDir allowlist.

    The server accepts a client-supplied `outputDir` on /download. Before
    v1.2.0 it only checked that the path was absolute — a compromised
    extension could write anywhere the server user had access to. These
    tests lock down the rejection path and the permissive subfolder path.
    """

    def test_confinement_accepts_subfolder_of_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "downloads"
            root.mkdir()
            subfolder = root / "channel-a" / "2026"
            out, err = ad.normalize_output_dir(
                str(subfolder),
                default_dir=str(root),
                allowed_roots=[root.resolve()],
            )
            self.assertIsNone(err)
            self.assertTrue(Path(out).resolve() == subfolder.resolve())
            self.assertTrue(subfolder.exists())

    def test_confinement_rejects_path_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as allowed_tmp, tempfile.TemporaryDirectory() as forbidden_tmp:
            allowed_root = Path(allowed_tmp).resolve()
            forbidden = Path(forbidden_tmp) / "escape" / "target"
            out, err = ad.normalize_output_dir(
                str(forbidden),
                default_dir=str(allowed_root),
                allowed_roots=[allowed_root],
            )
            self.assertIsNone(out)
            self.assertEqual(err, "Output folder is outside the configured download locations.")
            # Critical: confinement must reject BEFORE mkdir; a rejected
            # request should not create the forbidden directory.
            self.assertFalse(forbidden.exists())

    def test_confinement_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp) / "downloads"
            allowed_root.mkdir()
            # .. traversal: resolve() normalizes before the check.
            traversal = str(allowed_root / ".." / ".." / "somewhere")
            out, err = ad.normalize_output_dir(
                traversal,
                default_dir=str(allowed_root),
                allowed_roots=[allowed_root.resolve()],
            )
            self.assertIsNone(out)
            self.assertEqual(err, "Output folder is outside the configured download locations.")

    def test_allowed_output_roots_dedupes_and_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "videos"
            audio = Path(tmp) / "audio"
            video.mkdir()
            audio.mkdir()

            class _Cfg:
                def get(self, key, default=None):
                    return {
                        "DownloadPath": str(video),
                        # Same dir under DownloadPath and ExtraOutputRoots
                        # must collapse in the final list.
                        "AudioDownloadPath": str(video),
                        "ExtraOutputRoots": [str(audio), str(audio)],
                    }.get(key, default)

            roots = ad.allowed_output_roots(_Cfg())
            resolved_video = video.resolve()
            resolved_audio = audio.resolve()
            self.assertIn(resolved_video, roots)
            self.assertIn(resolved_audio, roots)
            self.assertEqual(len(roots), 2)


class YtDlpLinkFilePolicyTests(unittest.TestCase):
    """Defense in depth for the yt-dlp flags this program never sends."""

    def test_process_boundary_rejects_link_flags_and_abbreviations(self):
        hostile_options = {
            *ad.YTDLP_FORBIDDEN_LINK_FLAGS,
            '--write-l',
            '--write-u',
            '--write-d',
            '--write-w',
            # yt-dlp accepts unambiguous long-option abbreviations, so the
            # guard has to refuse the prefixes too.
            '--exe',
            '--netr',
            '--down',
            '--external-down',
        }
        for option in hostile_options:
            for suffix in ('', '=true'):
                with self.subTest(option=option, suffix=suffix), \
                     mock.patch.object(ad.subprocess, 'Popen') as popen:
                    with self.assertRaisesRegex(ValueError, 'Refusing unsafe yt-dlp flag'):
                        ad.spawn_ytdlp(['yt-dlp.exe', option + suffix, 'https://example.test'])
                    popen.assert_not_called()

    def test_process_boundary_covers_the_2026_advisory_flags(self):
        # Named explicitly so the set cannot silently shrink back to the
        # four link-file flags it started as.
        for option in (
            '--exec', '--exec-before-download',
            '--netrc', '--netrc-cmd', '--netrc-location',
            '--downloader', '--external-downloader',
            '--downloader-args', '--external-downloader-args',
        ):
            with self.subTest(option=option):
                self.assertIn(option, ad.YTDLP_FORBIDDEN_LINK_FLAGS)

    def test_every_spawn_disables_the_plugin_auto_load_path(self):
        # --ignore-config stops config FILES. Plugin directories are separate,
        # and module-level code in one executes inside the spawned process —
        # reproduced against the real binary on 2026-08-06. Refusing --exec at
        # this boundary while leaving that open would be decorative.
        sentinel = object()
        with mock.patch.object(ad.subprocess, 'Popen', return_value=sentinel) as popen:
            ad.spawn_ytdlp([
                'yt-dlp.exe', '--ignore-config', '--no-config',
                'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            ])
        argv = popen.call_args.args[0]
        self.assertEqual(argv[0], 'yt-dlp.exe', 'the executable must stay first')
        self.assertIn('--no-plugin-dirs', argv)
        self.assertIn('--no-remote-components', argv)
        self.assertEqual(argv[-1], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                         'the URL must stay last')

    def test_hardening_flags_are_not_duplicated(self):
        argv = ad.validate_ytdlp_spawn_args(
            ['yt-dlp.exe', '--no-plugin-dirs', 'https://example.test'])
        self.assertEqual(argv.count('--no-plugin-dirs'), 1)
        self.assertEqual(argv.count('--no-remote-components'), 1)

    def test_the_real_binary_accepts_the_hardening_flags(self):
        # A flag the installed yt-dlp rejects would break every download, so
        # this is checked against the binary rather than assumed.
        ytdlp = ad.YTDLP_PATH
        if not Path(ytdlp).exists():
            self.skipTest('yt-dlp is not installed in this environment')
        result = subprocess.run(
            [str(ytdlp), *ad.YTDLP_HARDENING_FLAGS, '--help'],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-400:])

    def test_process_boundary_allows_reviewed_download_args(self):
        sentinel = object()
        with mock.patch.object(ad.subprocess, 'Popen', return_value=sentinel) as popen:
            result = ad.spawn_ytdlp([
                'yt-dlp.exe', '--write-subs', '--no-playlist',
                'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            ], text=True)
        self.assertIs(result, sentinel)
        popen.assert_called_once()


class SiteLoginPolicyTests(unittest.TestCase):
    """Scoping rules that keep one stored sign-in from becoming a cookie dump."""

    def test_registrable_domain_collapses_subdomains(self):
        for host, expected in (
            ("www.reddit.com", "reddit.com"),
            ("old.reddit.com", "reddit.com"),
            ("x.com", "x.com"),
            ("video.twimg.com", "twimg.com"),
            ("a.b.c.example.co.uk", "example.co.uk"),
            ("site.com.au", "site.com.au"),
            ("localhost", "localhost"),
            ("", ""),
        ):
            self.assertEqual(ad.registrable_domain(host), expected, host)

    def test_site_login_key_accepts_urls_and_bare_hosts(self):
        for value, expected in (
            ("https://x.com/someone/status/1", "x.com"),
            ("https://www.instagram.com/reel/abc/", "instagram.com"),
            ("instagram.com", "instagram.com"),
            ("WWW.Vimeo.COM", "vimeo.com"),
            ("https://example.co.uk:8443/watch", "example.co.uk"),
            ("../../etc/passwd", ""),
            ("", ""),
        ):
            self.assertEqual(ad.site_login_key(value), expected, value)

    def test_site_login_key_never_escapes_the_store_directory(self):
        for hostile in ("../../secrets", "a/../../b", "..", "C:\\Windows\\System32"):
            key = ad.site_login_key(hostile)
            self.assertNotIn("/", key, hostile)
            self.assertNotIn("\\", key, hostile)
            self.assertNotIn("..", key, hostile)

    def test_cookie_domain_membership_is_suffix_exact(self):
        self.assertTrue(ad.cookie_domain_in_site(".x.com", "x.com"))
        self.assertTrue(ad.cookie_domain_in_site("api.x.com", "x.com"))
        self.assertTrue(ad.cookie_domain_in_site("x.com", "x.com"))
        # The classic suffix-matching bug: a lookalike domain must not match.
        self.assertFalse(ad.cookie_domain_in_site("notx.com", "x.com"))
        self.assertFalse(ad.cookie_domain_in_site("x.com.evil.net", "x.com"))
        self.assertFalse(ad.cookie_domain_in_site("youtube.com", "x.com"))
        self.assertFalse(ad.cookie_domain_in_site("", "x.com"))
        self.assertFalse(ad.cookie_domain_in_site("x.com", ""))

    def test_parse_netscape_cookies_reads_real_exporter_output(self):
        text = "\n".join([
            "# Netscape HTTP Cookie File",
            "",
            ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tsecret",
            "#HttpOnly_.x.com\tTRUE\t/\tTRUE\t0\tct0\tsession-value",
            "broken-line-without-columns",
            ".x.com\tTRUE\t/\tFALSE\tnot-a-number\tpref\tvalue with spaces",
        ])
        records = ad.parse_netscape_cookies(text)
        self.assertEqual([r["name"] for r in records], ["auth_token", "ct0", "pref"])
        self.assertTrue(records[0]["secure"])
        self.assertFalse(records[0]["httpOnly"])
        self.assertTrue(records[1]["httpOnly"], "#HttpOnly_ is a cookie, not a comment")
        self.assertEqual(records[1]["expirationDate"], 0, "session cookie")
        self.assertEqual(records[2]["expirationDate"], 0, "unparseable expiry is not fatal")
        self.assertEqual(records[2]["value"], "value with spaces")

    def test_parse_netscape_cookies_is_bounded(self):
        text = "\n".join(
            f".x.com\tTRUE\t/\tTRUE\t2000000000\tc{index}\tv"
            for index in range(ad.MAX_SITE_LOGIN_COOKIES + 50)
        )
        self.assertEqual(len(ad.parse_netscape_cookies(text)), ad.MAX_SITE_LOGIN_COOKIES)

    def test_browser_args_reject_injection_and_unknown_browsers(self):
        self.assertEqual(
            ad.build_browser_cookie_args("firefox"), ["--cookies-from-browser", "firefox"]
        )
        self.assertEqual(
            ad.build_browser_cookie_args("chrome", "Profile 2"),
            ["--cookies-from-browser", "chrome:Profile 2"],
        )
        # ':' and '+' are yt-dlp's own separators for keyring/container
        # selection — a profile name must never be able to smuggle them in.
        self.assertEqual(ad.build_browser_cookie_args("chrome", "a:b"), [])
        self.assertEqual(ad.build_browser_cookie_args("chrome", "a+gnomekeyring"), [])
        self.assertEqual(ad.build_browser_cookie_args("netscape-navigator"), [])
        self.assertEqual(ad.build_browser_cookie_args(""), [])

    def test_browser_failures_are_explained_in_users_terms(self):
        self.assertIn(
            "cookies.txt",
            ad.describe_browser_cookie_failure(
                "ERROR: Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927"
            ),
        )
        self.assertIn(
            "profile",
            ad.describe_browser_cookie_failure("could not find chrome cookies database"),
        )
        self.assertEqual(ad.describe_browser_cookie_failure("Extracted 12 cookies"), "")

    def test_chromium_browser_readiness_is_warned_before_import(self):
        for browser in ("brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"):
            with self.subTest(browser=browser):
                self.assertIn(
                    "likely unreadable",
                    ad.describe_browser_cookie_readiness(browser),
                )
        self.assertEqual(ad.describe_browser_cookie_readiness("firefox"), "")


class SiteLoginBrowserImportTests(unittest.TestCase):
    """Reading a browser cookie store: filtered on the way in, cleaned up after."""

    def test_browser_import_filters_and_removes_the_staging_jar(self):
        staged = {}
        real_popen = ad.subprocess.Popen

        def popen(args, **kwargs):
            # icacls protects the stored jar through this same Popen.
            if args and str(args[0]).lower().endswith(('icacls', 'icacls.exe')):
                return real_popen(args, **kwargs)
            jar = Path(args[args.index('--cookies') + 1])
            staged['path'] = jar
            jar.write_text(
                "# Netscape HTTP Cookie File\n"
                ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tX-SECRET\n"
                ".bank.example\tTRUE\t/\tTRUE\t2000000000\tsession\tBANK-SECRET\n",
                encoding="utf-8",
            )

            class Proc:
                returncode = 0

                def communicate(self, *_a, **_k):
                    return ("Extracted 2 cookies from firefox", "")

            return Proc()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                result, error = manager.import_site_login_from_browser("x.com", "firefox")

            self.assertIsNone(error)
            self.assertEqual(result["cookies"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertFalse(
                staged['path'].exists(),
                "the staging jar holds every browser cookie and must not survive",
            )
            stored = manager.site_logins.export_jar_for("https://x.com/a", Path(tmpdir) / "out.txt")
            body = Path(stored).read_text(encoding="utf-8")
            self.assertIn("X-SECRET", body)
            self.assertNotIn("BANK-SECRET", body)

    def test_app_bound_encryption_failure_is_explained_not_swallowed(self):
        def popen(args, **_kwargs):
            class Proc:
                returncode = 1

                def communicate(self, *_a, **_k):
                    return (
                        "ERROR: Failed to decrypt with DPAPI. See "
                        "https://github.com/yt-dlp/yt-dlp/issues/10927 for more info",
                        "",
                    )

            return Proc()

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.subprocess, 'Popen', popen), \
                 mock.patch.object(ad, 'write_persistent_log', return_value=None):
                result, error = manager.import_site_login_from_browser("x.com", "chrome")
        self.assertIsNone(result)
        self.assertIn("cookies.txt", error)

    def test_unsupported_browser_never_spawns_a_process(self):
        def popen(*_args, **_kwargs):
            raise AssertionError("no process may be spawned for an unknown browser")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir})
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.subprocess, 'Popen', popen):
                result, error = manager.import_site_login_from_browser("x.com", "netscape")
        self.assertIsNone(result)
        self.assertIn("supported browsers", error)


class OutputTemplatePreviewHonoursPaddingTests(unittest.TestCase):
    """A preview that under-reports the length is worse than none."""

    def test_a_pad_width_reaches_the_reported_length(self):
        # yt-dlp treats the pad as a minimum width, verified against its own
        # prepare_filename: `%(title)60.5B` writes 55 spaces and five
        # characters. The preview parsed the pad and discarded it, so it
        # reported five and told the caller the path fit.
        normalized = ad.normalize_output_template("%(title)200.5s.%(ext)s")
        report = ad.output_template_preview(normalized, "C:/downloads")
        self.assertGreaterEqual(
            report["length"], 200,
            "the preview reports a path shorter than yt-dlp will write",
        )
        self.assertTrue(report["relative"].endswith("Examp.mp4"))

    def test_a_zero_pad_previews_the_way_it_renders(self):
        normalized = ad.normalize_output_template("%(playlist_index)03d.%(ext)s")
        report = ad.output_template_preview(normalized, "C:/downloads")
        self.assertEqual(report["relative"], "001.mp4")

    def test_an_unpadded_template_is_unchanged(self):
        normalized = ad.normalize_output_template("%(title)s.%(ext)s")
        report = ad.output_template_preview(normalized, "C:/downloads")
        self.assertEqual(report["relative"], "Example video.mp4")

    def test_a_padded_template_can_now_be_seen_to_be_too_long(self):
        deep = "C:/downloads/" + "/".join(["folder"] * 12)
        report = ad.output_template_preview(
            ad.normalize_output_template("%(title)200.5s.%(ext)s"), deep,
        )
        self.assertTrue(
            report["too_long"],
            "the length that decides this used to be the unpadded one",
        )


class HistoryDateFilterTests(unittest.TestCase):
    """A saved-date bound has to mean what the person typing it meant.

    The filter compares dates as text against the ISO date on each row, and
    nothing normalised the bound, so an unpadded or non-ISO date became a
    filter that quietly excluded everything. The GUI had no validation at
    all; the API had strptime, which accepts 2026-8-1 and then hands the
    text comparison a string that sorts after every real date.
    """

    ROWS = [
        {"title": "Cat", "filename": "cat.mp4", "status": "complete",
         "format": "mp4", "date": "2026-08-22T10:00:00"},
        {"title": "Dog", "filename": "dog.mp4", "status": "complete",
         "format": "mp4", "date": "2026-01-05T10:00:00"},
    ]

    def test_an_unpadded_date_filters_the_way_it_reads(self):
        result = ad.query_history_entries(self.ROWS, date_from="2026-8-1")
        self.assertEqual(result["unreadableDates"], [])
        self.assertEqual(result["dateFrom"], "2026-08-01")
        self.assertEqual(result["filteredTotal"], 1)
        self.assertEqual(
            result["filteredTotal"],
            ad.query_history_entries(self.ROWS, date_from="2026-08-01")["filteredTotal"],
        )

    def test_a_date_that_is_not_a_date_is_named_rather_than_applied(self):
        for value in ("08/22/2026", "3", "tomorrow", "2026-13-45", "2026-02-30"):
            with self.subTest(value=value):
                result = ad.query_history_entries(self.ROWS, date_to=value)
                self.assertEqual(result["unreadableDates"], ["to"])
                self.assertEqual(result["dateTo"], "")
                self.assertEqual(
                    result["filteredTotal"], len(self.ROWS),
                    "an unreadable bound must not filter anything out",
                )

    def test_both_bounds_are_reported_independently(self):
        result = ad.query_history_entries(
            self.ROWS, date_from="nonsense", date_to="also nonsense",
        )
        self.assertEqual(result["unreadableDates"], ["from", "to"])
        result = ad.query_history_entries(
            self.ROWS, date_from="2026-01-01", date_to="nonsense",
        )
        self.assertEqual(result["unreadableDates"], ["to"])

    def test_normalize_history_date_separates_empty_from_unreadable(self):
        self.assertEqual(ad.normalize_history_date(""), "")
        self.assertEqual(ad.normalize_history_date(None), "")
        self.assertEqual(ad.normalize_history_date("  2026-8-1 "), "2026-08-01")
        self.assertIsNone(ad.normalize_history_date("2026/08/01"))
        self.assertIsNone(ad.normalize_history_date("2026-08-01T00:00:00"))


if __name__ == "__main__":
    unittest.main()
