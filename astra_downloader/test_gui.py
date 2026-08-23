"""Tests for the window, its pages and what they render."""

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


class CompanionListFilterTests(unittest.TestCase):
    def setUp(self):
        import gui

        self.gui = gui

    def test_subscription_filters_cover_search_and_attention_state(self):
        records = [
            {"title": "Astra", "url": "https://youtube.com/@astra", "enabled": True},
            {"title": "Paused", "url": "https://youtube.com/@paused", "enabled": False},
            {"title": "Broken", "url": "https://youtube.com/@broken", "enabled": True, "lastError": "403"},
        ]

        self.assertEqual(
            [item["title"] for item in self.gui.filter_subscription_records(records, "astra")],
            ["Astra"],
        )
        self.assertEqual(
            [item["title"] for item in self.gui.filter_subscription_records(records, status="disabled")],
            ["Paused"],
        )
        self.assertEqual(
            [item["title"] for item in self.gui.filter_subscription_records(records, status="needs-attention")],
            ["Broken"],
        )

    def test_site_login_filters_distinguish_expired_and_missing_jars(self):
        entries = [
            {"site": "x.com", "source": "firefox", "stored": True, "expired": False},
            {"site": "vimeo.com", "source": "cookies.txt", "stored": True, "expired": True},
            {"site": "instagram.com", "source": "firefox", "stored": False, "expired": False},
        ]

        self.assertEqual(
            [item["site"] for item in self.gui.filter_site_login_entries(entries, status="stored")],
            ["x.com"],
        )
        self.assertEqual(
            [item["site"] for item in self.gui.filter_site_login_entries(entries, status="expired")],
            ["vimeo.com"],
        )
        self.assertEqual(
            [item["site"] for item in self.gui.filter_site_login_entries(entries, "instagram")],
            ["instagram.com"],
        )

    def test_failed_sign_in_probe_leaves_a_visible_row_marker(self):
        show_status = mock.Mock()
        window = types.SimpleNamespace(
            _site_login_testing=True,
            _site_login_test_states={},
            _show_site_login_status=show_status,
            _refresh_site_logins=mock.Mock(),
        )
        with mock.patch.object(self.gui, "repolish"):
            self.gui.MainWindowCore._finish_site_login_test(
                window,
                {
                    "site": "x.com",
                    "result": {},
                    "error": "The stored session was rejected.",
                },
            )

        self.assertFalse(window._site_login_testing)
        self.assertEqual(
            window._site_login_test_states["x.com"]["ok"], False
        )
        self.assertIn("Test failed", window._site_login_test_states["x.com"]["message"])
        show_status.assert_called_once_with(
            "The stored session was rejected.", "error"
        )
        window._refresh_site_logins.assert_called_once_with(force=True)


class CompanionGuiPolicyTests(unittest.TestCase):
    def test_history_csv_cells_escape_spreadsheet_formula_prefixes(self):
        import gui as gui_module

        for value in ("=SUM(A1:A2)", "+cmd", "-1+1", "@A1", "\t=1", "\r=1"):
            with self.subTest(value=value):
                self.assertEqual(gui_module.sanitize_csv_cell(value), "'" + value)
        self.assertEqual(gui_module.sanitize_csv_cell("safe title"), "safe title")
        self.assertEqual(gui_module.sanitize_csv_cell(42), 42)

    def test_export_history_writes_filtered_rows_and_escapes_formula_cells(self):
        events = []
        window = types.SimpleNamespace(
            config=FakeConfig({"DownloadPath": tempfile.gettempdir()}),
            _history_query=lambda **_kwargs: {
                "history": [{
                    "title": "=HYPERLINK(\"https://evil.example\")",
                    "filename": "clip.mp4",
                    "format": "mp4",
                    "quality": "1080p",
                    "status": "complete",
                    "duration": 12,
                    "date": "2026-08-09",
                    "url": "https://example.com/video",
                }],
            },
            _show_history_status=lambda message, tone: events.append((message, tone)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.csv"
            with mock.patch.object(
                ad.QFileDialog,
                "getSaveFileName",
                return_value=(str(target), "CSV files (*.csv)"),
            ):
                ad.MainWindow._export_history(window)

            body = target.read_text(encoding="utf-8-sig")

        self.assertIn("'=HYPERLINK", body)
        self.assertIn("clip.mp4", body)
        self.assertEqual(events[-1][1], "success")
        self.assertIn("Exported one filtered history row", events[-1][0])

    def test_export_history_pages_past_the_query_page_size(self):
        calls = []

        def query(**kwargs):
            calls.append(kwargs)
            offset = kwargs.get("offset") or 0
            if offset == 0:
                return {
                    "history": [{"title": "one", "url": "https://a.example"}],
                    "filteredTotal": 2,
                }
            if offset == 1:
                return {
                    "history": [{"title": "two", "url": "https://b.example"}],
                    "filteredTotal": 2,
                }
            return {"history": [], "filteredTotal": 2}

        events = []
        window = types.SimpleNamespace(
            config=FakeConfig({"DownloadPath": tempfile.gettempdir()}),
            _history_query=query,
            _show_history_status=lambda message, tone: events.append((message, tone)),
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.csv"
            with mock.patch.object(
                ad.QFileDialog,
                "getSaveFileName",
                return_value=(str(target), "CSV files (*.csv)"),
            ):
                ad.MainWindow._export_history(window)
            body = target.read_text(encoding="utf-8-sig")

        self.assertGreaterEqual(len(calls), 2)
        self.assertIn("one", body)
        self.assertIn("two", body)
        self.assertIn("Exported 2", events[-1][0])

    def test_companion_qt_catalogues_cover_every_supported_locale_and_load_german(self):
        """Every advertised locale ships a compiled catalogue, and nothing ships
        a catalogue the app cannot select.

        This used to compare SUPPORTED_LOCALES against the browser
        extension's ``_locales`` directory. Astra Downloader is its own
        product now, so the invariant is stated against its own shipped
        files instead of another repository's.
        """
        import i18n as i18n_module
        from PySide6.QtCore import QTranslator

        translations = i18n_module.companion_translations_dir()
        shipped = {
            path.stem.replace("astra_downloader_", "")
            for path in translations.glob("astra_downloader_*.qm")
        }
        self.assertEqual(set(i18n_module.SUPPORTED_LOCALES), shipped)
        for locale in i18n_module.SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertTrue(
                    (translations / f"astra_downloader_{locale}.ts").exists(),
                    f"{locale} ships a compiled .qm with no .ts source",
                )
        self.assertEqual(i18n_module.normalize_companion_locale("de-DE"), "de")
        self.assertEqual(i18n_module.normalize_companion_locale("pt-BR"), "pt_BR")
        self.assertEqual(i18n_module.normalize_companion_locale("xx-YY"), "en")
        self.assertEqual(
            i18n_module.normalize_companion_locale("system", "fr-FR"),
            "en",
        )
        self.assertEqual(
            i18n_module.normalize_companion_locale("system", "de-DE"),
            "de",
        )

        translator = QTranslator()
        catalog = (
            i18n_module.companion_translations_dir()
            / "astra_downloader_de.qm"
        )
        self.assertTrue(translator.load(str(catalog)))
        self.assertEqual(
            translator.translate("AstraDownloader", "Browser extension"),
            "Browser-Erweiterung",
        )

    def test_language_picker_advertises_only_locales_above_translation_floor(self):
        import i18n as i18n_module

        self.assertEqual(i18n_module.ADVERTISED_LOCALES, ("de", "en"))
        self.assertGreaterEqual(
            i18n_module.COMPANION_LOCALE_MIN_COVERAGE, 0.8
        )
        self.assertTrue(
            set(i18n_module.ADVERTISED_LOCALES)
            <= set(i18n_module.SUPPORTED_LOCALES)
        )

    def test_companion_build_packages_qm_catalogues_and_renders_german(self):
        import importlib.util

        root = Path(ad.__file__).parents[1]
        build_spec = importlib.util.spec_from_file_location(
            "astra_translation_build", root / "astra_downloader" / "build.py"
        )
        build_module = importlib.util.module_from_spec(build_spec)
        build_spec.loader.exec_module(build_module)
        args = build_module.pyinstaller_args("onefile")
        add_data = args[args.index("--add-data") + 1]
        self.assertIn("*.qm", add_data)
        self.assertTrue(add_data.endswith(os.pathsep + "translations"))
        hidden_imports = [
            args[index + 1]
            for index, value in enumerate(args[:-1])
            if value == "--hidden-import"
        ]
        self.assertIn("i18n", hidden_imports)

        render_spec = importlib.util.spec_from_file_location(
            "astra_translation_renderer",
            root / "scripts" / "render-companion-gui.py",
        )
        renderer = importlib.util.module_from_spec(render_spec)
        render_spec.loader.exec_module(renderer)
        self.assertIn("dashboard-german", renderer.CAPTURE_NAMES)

    def test_companion_settings_save_reports_in_window_without_a_dialog(self):
        from PySide6.QtWidgets import QApplication, QMessageBox

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig({
                "ServerToken": "a" * 32,
                "DownloadPath": tmp,
                "AudioDownloadPath": tmp,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            try:
                with mock.patch.object(
                    QMessageBox, "exec", side_effect=AssertionError("blocking dialog")
                ), mock.patch.object(
                    QMessageBox, "open", side_effect=AssertionError("blocking dialog")
                ):
                    window._save_settings()
                    QApplication.processEvents()
                self.assertIn("Settings saved", window.settings_status.text())
            finally:
                _retire_test_window(window)

    def test_companion_uses_premium_command_center_and_async_readiness(self):
        probe_calls = []
        probe_payloads = []
        probe = gui_module_for_tests().ReadinessProbe(
            configured_runtime="deno",
            runtime_probe=lambda **kwargs: probe_calls.append(("runtime", kwargs)) or {"ejsReady": True},
            provider_probe=lambda: probe_calls.append(("provider", {})) or {"ok": False},
            ytdlp_version=lambda: "2026.08.04",
            ffmpeg_version=lambda: "8.1.2",
            logger=lambda message: probe_calls.append(("log", message)),
            impersonate_targets=lambda: probe_calls.append(("targets", {})) or ["chrome"],
        )
        probe.completed.connect(probe_payloads.append)
        probe.run()
        self.assertEqual(probe_payloads[0]["runtime"]["ejsReady"], True)
        self.assertEqual(probe_payloads[0]["impersonateTargets"], ["chrome"])
        self.assertEqual([name for name, _value in probe_calls[:2]], ["runtime", "provider"])
        self.assertIn("#ff6552", ad.STYLESHEET)
        self.assertIn('QFrame[class="readiness"]', ad.STYLESHEET)
        self.assertIn('QLabel[class="errorCallout"]', ad.STYLESHEET)
        import importlib.util

        renderer_path = Path(ad.__file__).parents[1] / "scripts" / "render-companion-gui.py"
        self.assertTrue(renderer_path.exists())
        render_spec = importlib.util.spec_from_file_location(
            "astra_command_center_renderer", renderer_path
        )
        renderer = importlib.util.module_from_spec(render_spec)
        render_spec.loader.exec_module(renderer)
        self.assertIn('QFrame[class="settingsGroup"]', ad.STYLESHEET)
        self.assertIn('QLabel[class="stateLabel"]', ad.STYLESHEET)
        required_states = {
            "dashboard-error-degraded", "downloads-first-run",
            "downloads-recovery-terminal", "history-cleared-undo",
            "settings-save-failed", "settings-update-busy",
            "reflow-900x620-hidpi-large-font",
            "history-german", "history-arabic-rtl",
            "settings-german", "settings-arabic-rtl",
            "site-logins-german", "site-logins-arabic-rtl",
            "subscriptions-german", "subscriptions-arabic-rtl",
        }
        self.assertTrue(required_states <= set(renderer.CAPTURE_NAMES))
        self.assertEqual(renderer.SCALE_SCENARIOS["downloads-focus-1x"], 1.0)
        self.assertEqual(renderer.SCALE_SCENARIOS["settings-focus-125x"], 1.25)
        self.assertTrue(callable(ad.make_line_icon))

        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig({
                "ServerToken": "a" * 32,
                "DownloadPath": tmp,
                "AudioDownloadPath": tmp,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            try:
                self.assertTrue(all(button.isCheckable() for button in window.nav_buttons))
                self.assertTrue(all(button.autoExclusive() for button in window.nav_buttons))
                self.assertTrue(hasattr(window, "quick_download_options_layout"))
                self.assertTrue(hasattr(window, "download_page_scroll"))
                window.cfg_proxy.setText("https://proxy.example:8443")
                QApplication.processEvents()
                self.assertEqual(window.settings_status.text(), "Unsaved changes")
                window._refresh_history()
                QApplication.processEvents()
                self.assertFalse(window.btn_clear_history.isEnabled())
            finally:
                _retire_test_window(window)

    def test_companion_status_palette_meets_wcag_aa_on_its_real_surfaces(self):
        import gui as gui_module

        def luminance(color):
            channels = [
                int(color[index:index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return (
                0.2126 * linear[0]
                + 0.7152 * linear[1]
                + 0.0722 * linear[2]
            )

        def ratio(foreground, background):
            lighter, darker = sorted(
                (luminance(foreground), luminance(background)),
                reverse=True,
            )
            return (lighter + 0.05) / (darker + 0.05)

        # Both palettes. This measured the dark one only, and the light one is
        # produced by substituting it colour for colour with nothing checking
        # the result: success on the sidebar came out at 4.27:1 and the label
        # of every primary button at 4.32:1.
        surface_pairs = {
            "muted": "surface",
            "neutral": "surface",
            "neutral_indicator": "surface",
            "readiness_text": "surface",
            "success": "surface",
            "warning": "surface",
            "danger": "surface",
            "log_text": "log_surface",
            # The sidebar is a second surface, and the running-server dot and
            # its label are the two things that sit on it.
            "success:sidebar": "sidebar",
            "warning:sidebar": "sidebar",
            "danger:sidebar": "sidebar",
            "muted:sidebar": "sidebar",
            "neutral:sidebar": "sidebar",
            "readiness_text:sidebar": "sidebar",
            # A primary button's own label, on the button.
            "accent_text": "accent",
        }
        original_theme = gui_module._ICON_THEME
        palettes = {}
        try:
            for theme in ("dark", "light"):
                gui_module.set_gui_theme(theme)
                palettes[theme] = dict(gui_module.GUI_ACCESSIBILITY_COLORS)
        finally:
            gui_module.set_gui_theme(original_theme)
        sheets = {"dark": ad.STYLESHEET, "light": ad.LIGHT_STYLESHEET}
        for theme, colors in palettes.items():
            for foreground, background in surface_pairs.items():
                token = foreground.split(":")[0]
                with self.subTest(theme=theme, foreground=foreground,
                                  background=background):
                    measured = ratio(colors[token], colors[background])
                    self.assertGreaterEqual(
                        measured, 4.5,
                        f"[{theme}] {token} {colors[token]} on {background} "
                        f"{colors[background]} is {measured:.2f}:1",
                    )
            for color in colors.values():
                self.assertIn(
                    color, sheets[theme],
                    f"[{theme}] {color} is declared as a semantic colour but "
                    f"the sheet does not use it",
                )

    def test_companion_theme_switch_resolves_palette_and_icon_scheme(self):
        from PySide6.QtCore import Qt
        import gui as gui_module

        self.assertEqual(ad.resolve_theme("system", Qt.ColorScheme.Light), "light")
        self.assertEqual(ad.resolve_theme("system", Qt.ColorScheme.Dark), "dark")
        self.assertEqual(ad.stylesheet_for_theme("dark"), ad.STYLESHEET)
        self.assertIn("#f6f8fb", ad.LIGHT_STYLESHEET)
        self.assertNotIn("#0a0d12", ad.LIGHT_STYLESHEET)
        self.assertIn("#445466", ad.LIGHT_STYLESHEET)

        original = gui_module._ICON_THEME
        try:
            gui_module.set_gui_theme("light")
            self.assertEqual(gui_module._ICON_THEME, "light")
            self.assertEqual(
                gui_module.GUI_ACCESSIBILITY_COLORS["surface"],
                "#f6f8fb",
            )
        finally:
            gui_module.set_gui_theme(original)

    def test_failed_settings_write_keeps_server_running_and_form_dirty(self):
        class TextField:
            def __init__(self, value=""):
                self.value_text = value
                self.accessible_description = ""
                self.focused = False

            def text(self):
                return self.value_text

            def setText(self, value):
                self.value_text = value

            def setAccessibleDescription(self, value):
                self.accessible_description = value

            def setFocus(self, _reason):
                self.focused = True

        class NumberField:
            def __init__(self, value):
                self.number = value

            def value(self):
                return self.number

        class CheckField:
            def __init__(self, checked=False):
                self.checked = checked

            def isChecked(self):
                return self.checked

        class ComboField:
            def __init__(self, value="remove"):
                self.value = value

            def currentData(self):
                return self.value

        class Button:
            def __init__(self):
                self.text_value = "Save changes"

            def setText(self, value):
                self.text_value = value

        class FailingConfig(FakeConfig):
            def update(self, mapping):
                self.attempted = mapping
                return False

        class Harness:
            pass

        window = Harness()
        window.config = FailingConfig({"ServerPort": ad.SERVER_PORT, "ServerToken": "a" * 32})
        window.server_running = True
        window.cfg_port = NumberField(ad.SERVER_PORT + 1)
        window.cfg_token = TextField("b" * 32)
        window.cfg_dl_path = TextField(window.config.get("DownloadPath"))
        window.cfg_audio_path = TextField("")
        window.cfg_outtmpl = TextField("")
        window.cfg_sublangs = TextField("en")
        window.cfg_ratelimit = TextField("")
        window.cfg_throttled = TextField("")
        window.cfg_proxy = TextField("")
        window.cfg_force_ip_version = ComboField("")
        window.cfg_source_address = TextField("")
        window.cfg_xff = TextField("")
        window.cfg_geo_verification_proxy = TextField("")
        window.cfg_verify_formats = CheckField()
        window.cfg_metadata = CheckField()
        window.cfg_thumbnail = CheckField()
        window.cfg_chapters = CheckField()
        window.cfg_subs = CheckField()
        window.cfg_keep_intermediates = CheckField()
        window.cfg_sponsorblock = CheckField()
        window.cfg_sb_categories = {"sponsor": CheckField(True)}
        window.cfg_sb_action = ComboField()
        window.cfg_js_runtime = ComboField("auto")
        window.cfg_ytdlp_channel = ComboField("nightly")
        window.cfg_video_codec = ComboField("auto")
        window.cfg_audio_codec = ComboField("auto")
        window.cfg_frame_rate = ComboField(0)
        window.cfg_prefer_original = CheckField(True)
        window.cfg_playlist_max = NumberField(0)
        window.cfg_playlist_dateafter = TextField("")
        window.cfg_playlist_min_duration = NumberField(0)
        window.cfg_playlist_max_duration = NumberField(0)
        window.cfg_impersonate = ComboField("")
        window.cfg_subtitle_mode = ComboField("prefer-manual")
        window.cfg_subtitle_format = ComboField("")
        window.cfg_fragments = NumberField(4)
        window.cfg_maxconcurrent = NumberField(3)
        window.cfg_retries = NumberField(10)
        window.cfg_socket_timeout = NumberField(0)
        window.cfg_extractor_retries = NumberField(0)
        window.cfg_sleep_interval = NumberField(0)
        window.cfg_sleep_max = NumberField(0)
        window.cfg_pacing_jitter = NumberField(0)
        window.cfg_sleep_requests = NumberField(0)
        window.cfg_maxsize = NumberField(0)
        window.cfg_autoupdate = CheckField()
        window.cfg_closetotray = CheckField()
        window.cfg_startmin = CheckField()
        window.cfg_notify = CheckField()
        window.btn_save = Button()
        window.statuses = []
        window.logs = []
        window.server_calls = []
        window._set_input_error = lambda *_args: None
        window._show_settings_status = lambda message, tone="neutral": window.statuses.append((message, tone))
        window._append_log = window.logs.append
        window._sync_connection_ui = lambda: window.server_calls.append("sync")
        window._set_control_label = (
            lambda widget, text, _window=window:
                ad.MainWindow._set_control_label(_window, widget, text)
        )
        window._sync_sublang_checkboxes = lambda *_args: None
        window._stop_server = lambda: window.server_calls.append("stop")
        window._start_server = lambda: window.server_calls.append("start")
        window._dependencies = {
            "clamp_int": ad.clamp_int,
            "normalize_output_dir": ad.normalize_output_dir,
            "normalize_proxy": ad.normalize_proxy,
            "normalize_force_ip_version": ad.normalize_force_ip_version,
            "normalize_source_address": ad.normalize_source_address,
            "normalize_xff": ad.normalize_xff,
            "normalize_rate_limit": ad.normalize_rate_limit,
            "normalize_playlist_date": ad.normalize_playlist_date,
            "normalize_impersonate_target": ad.normalize_impersonate_target,
            "normalize_sublangs": ad.normalize_sublangs,
            "normalize_subtitle_mode": ad.normalize_subtitle_mode,
            "normalize_subtitle_format": ad.normalize_subtitle_format,
        }
        values = {"DEFAULT_CONFIG": ad.DEFAULT_CONFIG, "SERVER_PORT": ad.SERVER_PORT}
        window._value = values.__getitem__

        ad.MainWindow._save_settings(window)

        self.assertEqual(window.server_calls, [])
        self.assertEqual(window.btn_save.text_value, "Save changes")
        self.assertEqual(window.statuses[-1][1], "danger")
        self.assertIn("Nothing changed", window.statuses[-1][0])
        self.assertIn("server state were preserved", window.logs[-1])
        self.assertIn("UseSystemProxy", window.config.attempted)

    def test_settings_validation_focuses_and_describes_first_invalid_field(self):
        class Field:
            def __init__(self, value=""):
                self.value_text = value
                self.description = None
                self.focused = False

            def text(self):
                return self.value_text

            def setText(self, value):
                self.value_text = value

            def setAccessibleDescription(self, value):
                self.description = value

            def setFocus(self, _reason):
                self.focused = True

        class NumberField:
            def value(self):
                return ad.SERVER_PORT

        class Harness:
            pass

        window = Harness()
        window.config = FakeConfig({"ServerPort": ad.SERVER_PORT, "ServerToken": "a" * 32})
        window.cfg_port = NumberField()
        window.cfg_token = Field("a" * 32)
        window.cfg_dl_path = Field("bad-video")
        window.cfg_audio_path = Field("bad-audio")
        window.cfg_sublangs = Field("en")
        window.cfg_ratelimit = Field("")
        window.cfg_proxy = Field("")
        window.cfg_force_ip_version = type("ComboField", (), {
            "currentData": lambda self: "",
        })()
        window.cfg_source_address = Field("")
        window.cfg_xff = Field("")
        window.cfg_geo_verification_proxy = Field("")
        window.cfg_outtmpl = Field("%(filepath)s.%(ext)s")
        window.statuses = []
        window._set_input_error = lambda field, value: setattr(field, "has_error", value)
        window._show_settings_status = lambda message, tone="neutral": window.statuses.append((message, tone))
        window._dependencies = {
            "clamp_int": ad.clamp_int,
            "normalize_output_dir": lambda value, fallback: (fallback, "invalid"),
            "normalize_output_template": ad.normalize_output_template,
            "normalize_proxy": ad.normalize_proxy,
            "normalize_force_ip_version": ad.normalize_force_ip_version,
            "normalize_source_address": ad.normalize_source_address,
            "normalize_xff": ad.normalize_xff,
            "normalize_rate_limit": ad.normalize_rate_limit,
            "normalize_playlist_date": ad.normalize_playlist_date,
            "normalize_impersonate_target": ad.normalize_impersonate_target,
            "normalize_sublangs": ad.normalize_sublangs,
        }
        window._value = {"DEFAULT_CONFIG": ad.DEFAULT_CONFIG, "SERVER_PORT": ad.SERVER_PORT}.__getitem__

        ad.MainWindow._save_settings(window)

        self.assertTrue(window.cfg_dl_path.has_error)
        self.assertTrue(window.cfg_audio_path.has_error)
        self.assertTrue(window.cfg_outtmpl.has_error)
        self.assertIn("Keep %(ext)s", window.cfg_outtmpl.description)
        self.assertTrue(window.cfg_dl_path.focused)
        self.assertIn("video download folder", window.cfg_dl_path.description)
        self.assertEqual(window.statuses[-1][1], "danger")

    def test_manual_ytdlp_update_defers_while_downloads_are_active(self):
        class ExistingPath:
            @staticmethod
            def exists():
                return True

        class Manager:
            @staticmethod
            def active_count():
                return 2

        class Button:
            def setEnabled(self, _value):
                raise AssertionError("deferred update must not enter a busy state")

        class Harness:
            pass

        window = Harness()
        window.dl_manager = Manager()
        window.btn_check_updates = Button()
        window.logs = []
        window.statuses = []
        window._append_log = window.logs.append
        window._show_settings_status = lambda message, tone="neutral": window.statuses.append((message, tone))
        window._value = lambda name: ExistingPath() if name == "YTDLP_PATH" else None

        ad.MainWindow._force_ytdlp_update(window)

        self.assertIn("2 download(s)", window.logs[-1])
        self.assertIn("active downloads", window.statuses[-1][0])
        self.assertEqual(window.statuses[-1][1], "warning")

    def test_manual_ytdlp_completion_restores_button_and_reports_recovery(self):
        class Button:
            def __init__(self):
                self.enabled = False
                self.text = "Checking…"

            def setEnabled(self, value):
                self.enabled = value

            def setText(self, value):
                self.text = value

        class Harness:
            pass

        window = Harness()
        window.btn_check_updates = Button()
        window.logs = []
        window.statuses = []
        window.refreshes = 0
        window._append_log = window.logs.append
        window._show_settings_status = lambda message, tone="neutral": window.statuses.append((message, tone))
        window._refresh_tools_status = lambda: setattr(window, "refreshes", window.refreshes + 1)
        window._set_control_label = (
            lambda widget, text, _window=window:
                ad.MainWindow._set_control_label(_window, widget, text)
        )

        ad.MainWindow._finish_ytdlp_update(window, {
            "ok": False,
            "error": "staged update failed",
            "rolled_back": True,
            "version_after": "2026.07.01",
        })

        self.assertTrue(window.btn_check_updates.enabled)
        self.assertEqual(window.btn_check_updates.text, "Check for yt-dlp updates")
        self.assertEqual(window.refreshes, 1)
        self.assertIn("Restored 2026.07.01", window.logs[-1])
        self.assertEqual(window.statuses[-1][1], "danger")

    def test_token_clipboard_clear_preserves_newer_user_content(self):
        class Clipboard:
            def __init__(self, text):
                self.value = text
                self.clear_calls = 0

            def text(self):
                return self.value

            def clear(self):
                self.value = ""
                self.clear_calls += 1

        class Harness:
            pass

        window = Harness()
        window.statuses = []
        window._show_settings_status = lambda message, tone="neutral": window.statuses.append((message, tone))
        clipboard = Clipboard("newer clipboard content")
        qapplication = ad.MainWindow._clear_copied_token.__globals__["QApplication"]
        with mock.patch.object(qapplication, "clipboard", return_value=clipboard):
            ad.MainWindow._clear_copied_token(window, "private-token")
            self.assertEqual(clipboard.clear_calls, 0)

            clipboard.value = "private-token"
            ad.MainWindow._clear_copied_token(window, "private-token")

        self.assertEqual(clipboard.clear_calls, 1)
        self.assertIn("cleared", window.statuses[-1][0])

    def test_failed_history_clear_and_undo_preserve_recovery_state(self):
        class History:
            def load(self):
                return [{"id": "1", "title": "One"}]

            def clear(self):
                return False

            def replace(self, _entries):
                return False

        class Button:
            def __init__(self):
                self.hidden = False

            def hide(self):
                self.hidden = True

            def show(self):
                self.hidden = False

        class Harness:
            pass

        window = Harness()
        window.history_mgr = History()
        window._cleared_history_snapshot = [{"id": "prior", "title": "Prior"}]
        window.btn_undo_clear_history = Button()
        window.logs = []
        window.refreshes = 0
        window._append_log = window.logs.append
        window.statuses = []
        window._show_history_status = lambda text, state="neutral": (
            window.statuses.append((text, state)) or window.logs.append(text)
        )
        window._refresh_history = lambda: setattr(window, "refreshes", window.refreshes + 1)

        ad.MainWindow._clear_history(window)
        self.assertEqual(window._cleared_history_snapshot, [{"id": "prior", "title": "Prior"}])
        self.assertEqual(window.refreshes, 0)
        self.assertIn("preserved", window.logs[-1])

        ad.MainWindow._undo_clear_history(window)
        self.assertEqual(window._cleared_history_snapshot, [{"id": "prior", "title": "Prior"}])
        self.assertFalse(window.btn_undo_clear_history.hidden)
        self.assertEqual(window.refreshes, 0)
        self.assertIn("still available", window.logs[-1])

        # Both failures have to reach the History page, not only the server
        # log panel that lives on another page.
        self.assertEqual([state for _text, state in window.statuses], ["error", "error"])


class RepeatedRowAccessibilityTests(unittest.TestCase):
    """"Show, Show, Show" tells a screen-reader user nothing about which file."""

    def test_every_history_row_action_names_its_own_file(self):
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)

        class ThreeRowHistory(FakeHistory):
            def load(self):
                return [
                    {
                        "id": f"h{index}", "url": f"https://example.com/{index}",
                        "title": f"Video {index}", "filename": f"C:/Videos/clip{index}.mp4",
                        "format": "mp4", "quality": "1080", "status": "complete",
                        "date": "2026-08-06 10:00:00", "duration": 12,
                    }
                    for index in range(3)
                ]

        history = ThreeRowHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                window._refresh_history()
                QApplication.processEvents()

                names = [
                    button.accessibleName()
                    for button in window.findChildren(QPushButton)
                    if button.text() == "Show"
                ]
                self.assertEqual(len(names), 3, names)
                self.assertEqual(len(set(names)), 3,
                                 f"repeated row actions must be distinguishable: {names}")
                for index, name in enumerate(sorted(names)):
                    self.assertIn(f"clip{index}.mp4", name)
            finally:
                _retire_test_window(window)

    def test_a_saved_date_the_filter_cannot_read_is_marked_and_explained(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)

        class OneRowHistory(FakeHistory):
            def load(self):
                return [{
                    "id": "row", "url": "https://example.com/a", "title": "A",
                    "filename": "a.mp4", "format": "mp4", "quality": "1080",
                    "status": "complete", "date": "2026-08-22 10:00:00",
                    "duration": 4,
                }]

        history = OneRowHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                # An American-format date used to hide every row with the
                # ordinary empty state as the only thing on screen.
                window.history_date_to.setText("08/22/2026")
                window._refresh_history()
                QApplication.processEvents()
                self.assertEqual(
                    window.history_date_to.property("state"), "error",
                    "the field the filter could not read is not marked",
                )
                self.assertTrue(window.history_page_status.isVisible()
                                or window.history_page_status.text())
                self.assertIn("YYYY-MM-DD", window.history_page_status.text())
                self.assertEqual(
                    len(window._history_query(entries=history.load())["history"]), 1,
                    "an unreadable bound must not filter the row out",
                )

                # An inverted range matches nothing, and says so instead of
                # leaving the user to guess at an empty list.
                window.history_date_to.setText("2026-01-01")
                window.history_date_from.setText("2026-08-01")
                window._refresh_history()
                QApplication.processEvents()
                self.assertFalse(window.history_date_to.property("state"))
                self.assertIn("after", window.history_page_status.text())

                # And a note about the filter bar clears itself once the
                # filter bar is valid again.
                window.history_date_from.clear()
                window.history_date_to.clear()
                window._refresh_history()
                QApplication.processEvents()
                self.assertEqual(window.history_page_status.text(), "")
            finally:
                _retire_test_window(window)

    def test_a_subscription_folder_is_checked_when_it_is_typed(self):
        from PySide6.QtWidgets import QApplication, QDialog

        _get_qapp_or_skip(self)

        history = FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                saved = []
                window._dependencies['subscription_manager'] = types.SimpleNamespace(
                    get_subscription=lambda _sub_id: {"id": "s", "title": "T",
                                                      "url": "https://youtube.com/@t"},
                    update_subscription=lambda sub_id, **fields: (
                        saved.append(fields) or ({"id": sub_id}, None)
                    ),
                    stop=lambda: None,
                )

                def deliver(folder):
                    return lambda self_dialog: {
                        "outputDir": folder, "format": "", "quality": "",
                        "outputTemplate": "", "audioOnly": False,
                        "upgradeIfBetter": False,
                    }

                # Stored unchecked, a relative path failed once per video on
                # every scan and never at the moment it was typed.
                with mock.patch.object(ad.SubscriptionDeliveryDialog, "exec",
                                       lambda _self: QDialog.DialogCode.Accepted), \
                        mock.patch.object(ad.SubscriptionDeliveryDialog, "delivery",
                                          deliver("not-an-absolute-path")):
                    self.assertFalse(window._edit_subscription_delivery("s"))
                QApplication.processEvents()
                self.assertEqual(saved, [], "an unusable folder must not be stored")
                self.assertIn("absolute", window.subscription_status.text().lower())

                # Inside the configured download root, because the dialog
                # applies the same confinement the download path will.
                with tempfile.TemporaryDirectory() as tmpdir:
                    window.config = FakeConfig({"DownloadPath": tmpdir})
                    target = str(Path(tmpdir) / "feed")
                    with mock.patch.object(ad.SubscriptionDeliveryDialog, "exec",
                                           lambda _self: QDialog.DialogCode.Accepted), \
                            mock.patch.object(ad.SubscriptionDeliveryDialog, "delivery",
                                              deliver(target)):
                        self.assertTrue(window._edit_subscription_delivery("s"))
                    self.assertEqual(len(saved), 1)
                    self.assertEqual(
                        saved[0]["delivery"]["outputDir"], target,
                        "a usable folder is stored resolved",
                    )
            finally:
                _retire_test_window(window)

    def test_a_terminal_card_offers_its_menu_without_a_right_click(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)

        history = FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                download = types.SimpleNamespace(
                    id="dl-1", url="https://example.com/a", title="A",
                    status="cancelled", filename="", error="", error_code="",
                    progress=0, speed="", eta="", size="", command_args=None,
                    quality="1080", format="mp4", audio_only=False,
                    subscription_id="", archive_key="", recovery=None,
                )
                card = window._download_card(download, recent=True)
                QApplication.processEvents()
                labels = [
                    button.text() for button in card.findChildren(QPushButton)
                ]
                self.assertIn(
                    "More", labels,
                    "a cancelled card has no button at all, and six of its "
                    f"eight actions live only in the menu: {labels}",
                )
                more = next(
                    button for button in card.findChildren(QPushButton)
                    if button.text() == "More"
                )
                # Tab-reachable, unlike the right-click the actions used to
                # need, and it says what it opens.
                self.assertNotEqual(
                    more.focusPolicy(), Qt.FocusPolicy.NoFocus
                )
                self.assertTrue(more.toolTip())

                menu = window._download_card_menu(download, card)
                actions = [action.text() for action in menu.actions()]
                for expected in ("Play", "Delete file", "Copy link",
                                 "Download again"):
                    self.assertIn(expected, actions)
                menu.deleteLater()
                card.deleteLater()
            finally:
                _retire_test_window(window)

    def test_a_rejected_settings_field_says_why_on_screen(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)

        history = FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                # The reason used to go to setAccessibleDescription only, so a
                # sighted user got a slightly redder border and "Check the
                # highlighted fields before saving."
                window.cfg_token.setText("")
                window._save_settings()
                QApplication.processEvents()
                self.assertEqual(window.cfg_token.property("state"), "error")
                reason = "The private API token cannot be empty."
                self.assertEqual(window.cfg_token.toolTip(), reason)
                self.assertEqual(
                    window.cfg_token.accessibleDescription(), reason)
                self.assertEqual(window.settings_status.text(), reason)
            finally:
                _retire_test_window(window)

    def test_failed_history_row_shows_status_error_and_terminal_filters(self):
        from PySide6.QtWidgets import QApplication, QLabel

        _get_qapp_or_skip(self)

        class FailedHistory(FakeHistory):
            def load(self):
                return [{
                    "id": "failed-row", "url": "https://example.com/private",
                    "title": "Private video", "filename": "",
                    "format": "mp4", "quality": "1080", "status": "failed",
                    "errorCode": "sign-in-required", "error": "Sign in first.",
                    "date": "2026-08-06 10:00:00", "duration": 4,
                }]

        history = FailedHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                window._refresh_history()
                QApplication.processEvents()

                labels = [label.text() for label in window.findChildren(QLabel)]
                self.assertTrue(any("Failed" in label for label in labels), labels)
                self.assertTrue(any("Sign in first." in label for label in labels), labels)
                self.assertEqual(
                    [window.history_status.itemData(index)
                     for index in range(window.history_status.count())],
                    ["", "complete", "failed", "cancelled", "skipped"],
                )
            finally:
                _retire_test_window(window)

    def test_retryable_failed_card_exposes_retry_link_and_error_actions(self):
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)
        history = FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        download = ad.Download(
            "failed-card", "https://example.com/private", title="Private video"
        )
        download.status = "failed"
        download.error_code = "network-unreachable"
        download.error = "Network is unavailable."
        manager.downloads[download.id] = download

        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                card = window._download_card(download, recent=True)
                QApplication.processEvents()
                self.assertEqual(
                    [button.text() for button in card.findChildren(QPushButton)],
                    ["Retry", "More"],
                    "a terminal card carries its one immediate action and the "
                    "button that opens the rest",
                )
                menu = window._download_card_menu(download, card)
                action_text = [action.text() for action in menu.actions()]
                self.assertIn("Retry", action_text)
                self.assertIn("Copy link", action_text)
                self.assertIn("Copy error text", action_text)
            finally:
                _retire_test_window(window)

    def test_rate_limited_card_shows_the_live_host_countdown(self):
        from PySide6.QtWidgets import QApplication, QLabel

        _get_qapp_or_skip(self)
        history = FakeHistory()
        manager = ad.DownloadManager(FakeConfig(), history)
        download = ad.Download(
            "rate-card", "https://www.example.com/video", title="Rate-limited video"
        )
        download.status = "failed"
        download.error_code = "rate-limited"
        download.error = "HTTP 429"
        download.error_advice = "This site is temporarily rate-limited."
        manager.downloads[download.id] = download

        with mock.patch.object(manager, "host_backoff_remaining", return_value=65), \
                mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, history)
            try:
                card = window._download_card(download, recent=True)
                QApplication.processEvents()
                labels = [label.text() for label in card.findChildren(QLabel)]
                self.assertTrue(any("1m 5s" in label for label in labels), labels)
                self.assertTrue(any("This host is paused" in label for label in labels), labels)
            finally:
                _retire_test_window(window)


class DragAndDropTests(unittest.TestCase):
    def _window(self):
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            return ad.MainWindow(FakeConfig(), manager, FakeHistory()), manager

    def _drop(self, text=None, urls=()):
        from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
        from PySide6.QtGui import QDropEvent

        mime = QMimeData()
        if text is not None:
            mime.setText(text)
        if urls:
            mime.setUrls([QUrl(url) for url in urls])
        # QDropEvent does not take ownership of the mime data. Without this
        # reference Python frees it and the C++ side reads freed memory.
        self._retained_mime = mime
        return QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_a_dropped_link_is_queued(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window, manager = self._window()
        try:
            self.assertTrue(window.acceptDrops())
            with mock.patch.object(
                manager, "start_download", return_value=("dl_dropped", None)
            ) as start:
                window.dropEvent(self._drop("https://example.com/video"))
                QApplication.processEvents()

            start.assert_called_once()
            self.assertEqual(
                start.call_args.kwargs["url"], "https://example.com/video")
            self.assertEqual(
                window.tabs.currentIndex(), window._page_names.index("Download"),
                "a drop must land the user on the page showing the queue",
            )
        finally:
            _retire_test_window(window)

    def test_a_dropped_text_file_of_links_becomes_a_batch(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window, manager = self._window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                listing = Path(tmp) / "links.txt"
                listing.write_text(
                    "https://example.com/one\n"
                    "not a url\n"
                    "https://example.com/two\n"
                    "https://example.com/one\n",
                    encoding="utf-8",
                )
                with mock.patch.object(
                    manager, "start_download", return_value=("dl_batch", None)
                ) as start:
                    window.dropEvent(self._drop(
                        urls=[QUrl.fromLocalFile(str(listing)).toString()]))
                    QApplication.processEvents()

            queued = [call.kwargs["url"] for call in start.call_args_list]
            self.assertEqual(
                queued, ["https://example.com/one", "https://example.com/two"],
                "junk lines are dropped and duplicates collapse",
            )
        finally:
            _retire_test_window(window)

    def test_an_oversized_link_file_is_ignored(self):
        from PySide6.QtCore import QUrl

        _get_qapp_or_skip(self)
        window, _manager = self._window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                huge = Path(tmp) / "links.txt"
                huge.write_bytes(
                    b"https://example.com/x\n"
                    * (ad.MainWindow.MAX_DROPPED_LINK_FILE_BYTES // 10)
                )
                event = self._drop(urls=[QUrl.fromLocalFile(str(huge)).toString()])
                self.assertEqual(window._links_from_mime(event.mimeData()), [])
        finally:
            _retire_test_window(window)

    def test_a_drop_with_nothing_downloadable_is_refused(self):
        _get_qapp_or_skip(self)
        window, manager = self._window()
        try:
            with mock.patch.object(manager, "start_download") as start:
                window.dropEvent(self._drop("just some prose"))
            start.assert_not_called()
        finally:
            _retire_test_window(window)


class DownloadCardFocusTests(unittest.TestCase):
    def test_focus_survives_a_card_rebuild_on_status_change(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        download = ad.Download("dl_focus", "https://example.com/video", title="Clip")
        download.status = "downloading"
        manager.downloads[download.id] = download

        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                window.show()
                window._update_ui()
                QApplication.processEvents()

                card = window._download_widgets[("download", download.id)]
                cancel = next(button for button in card.findChildren(QPushButton)
                              if button.text() == "Cancel")
                cancel.setFocus(Qt.FocusReason.OtherFocusReason)
                QApplication.processEvents()
                self.assertIs(QApplication.focusWidget(), cancel)

                # Completing the download changes the card's structure, so the
                # widget holding focus is destroyed and rebuilt.
                download.status = "complete"
                download.filename = "C:/Videos/clip.mp4"
                download.mark_terminal()
                window._update_ui()
                QApplication.processEvents()

                rebuilt = window._download_widgets[("download", download.id)]
                self.assertIsNot(rebuilt, card, "the card must have been rebuilt")
                focus = QApplication.focusWidget()
                self.assertIsNotNone(focus, "focus must not be lost to nowhere")
                self.assertTrue(
                    focus is rebuilt or rebuilt.isAncestorOf(focus),
                    "focus must stay on the download the user was working with",
                )
            finally:
                _retire_test_window(window)


class GuiSmokeTests(unittest.TestCase):
    """v4.47.0 NF22 — live Qt smoke tests for the downloader GUI.

    These tests construct a real QApplication and exercise the
    FolderPickerService timer-driven dispatch end-to-end. Previously
    the GUI side had only source-shape pins (FolderPickerWatchdogTests
    above) — a regression in the dialog code-path would only surface
    via the user reports it was supposed to make easier to file.

    Tests skip gracefully if QApplication can't be constructed
    (CI runner without a display server). The shared FolderPickerService
    tests cover both the happy paths (Accepted, Rejected) and the
    watchdog log path with a mocked-slow QFileDialog.exec.
    """

    _retained_windows = []

    def setUp(self):
        _get_qapp_or_skip(self)
        # Drain any leftover queue entries from prior test interactions
        # so each test starts from a clean slate.
        while True:
            try:
                ad._folder_pick_q.get_nowait()
            except Exception:  # queue.Empty or anything weird
                # reason: draining a leftover queue; an empty queue is the exit condition
                break

    def test_qapplication_constructs(self):
        # If we got past setUp without skipping, QApplication is alive.
        from PySide6.QtWidgets import QApplication
        self.assertIsNotNone(QApplication.instance(),
                             "QApplication.instance() must be available after setUp")

    def test_main_window_construction_defers_executable_version_probes(self):
        from PySide6.QtWidgets import QApplication

        calls = []

        def ytdlp_version(*_args, **_kwargs):
            calls.append("yt-dlp")
            return "2026.07.04"

        def ffmpeg_version(*_args, **_kwargs):
            calls.append("ffmpeg")
            return "8.1.2"

        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad, "get_ytdlp_version", side_effect=ytdlp_version), \
                mock.patch.object(ad, "get_ffmpeg_version", side_effect=ffmpeg_version), \
                mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                self.assertEqual(calls, [],
                                 "MainWindow construction must not shell out before first paint")
                self.assertEqual(window.tools_status.text(), "Checking installed tools…")

                deadline = time.monotonic() + 2
                while len(calls) < 2 and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.01)
                self.assertCountEqual(calls, ["yt-dlp", "ffmpeg"])

                deadline = time.monotonic() + 2
                while "yt-dlp 2026.07.04" not in window.tools_status.text() \
                        and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.01)
                self.assertEqual(
                    window.tools_status.text(),
                    "yt-dlp 2026.07.04    •    ffmpeg 8.1.2",
                )
            finally:
                window.update_timer.stop()
                window.cleanup_timer.stop()
                window.tray.hide()
                window._force_exit = True
                window.close()
                QApplication.processEvents()
                # Keep the closed C++ object alive for the remainder of the
                # shared-QApplication suite. Deleting a complex Qt window
                # immediately can invalidate queued animation callbacks owned
                # by Qt itself; application shutdown performs final disposal.
                self._retained_windows.append(window)

    def test_download_progress_patches_one_card_and_preserves_scroll_and_focus(self):
        from PySide6.QtWidgets import QApplication, QProgressBar, QPushButton

        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        for index in range(24):
            download = ad.Download(
                f"download-{index}",
                f"https://www.youtube.com/watch?v=fixture{index:04d}",
                title=f"Fixture download {index}",
                created_at=float(index + 1),
            )
            download.status = "downloading"
            download.progress = float(index)
            manager.downloads[download.id] = download

        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.MainWindow, "_refresh_tools_status"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                window.resize(900, 620)
                window.show()
                window._nav_click("Download")
                window._update_ui()
                QApplication.processEvents()

                key = ("download", "download-12")
                card = window._download_widgets[key]
                progress = card.findChild(QProgressBar)
                cancel = card.findChild(QPushButton)
                self.assertIsNotNone(progress)
                self.assertIsNotNone(cancel)
                cancel.setFocus()
                QApplication.processEvents()
                self.assertIs(QApplication.focusWidget(), cancel)

                scroll_bar = window.downloads_scroll.verticalScrollBar()
                self.assertGreater(scroll_bar.maximum(), 0)
                scroll_bar.setValue(scroll_bar.maximum() // 2)
                old_scroll = scroll_bar.value()

                manager.downloads["download-12"].progress = 73.4
                manager.downloads["download-12"].speed = "2.1 MiB/s"
                window._update_ui()
                QApplication.processEvents()

                self.assertIs(window._download_widgets[key], card)
                self.assertEqual(progress.value(), 73)
                self.assertEqual(scroll_bar.value(), old_scroll)
                self.assertIs(QApplication.focusWidget(), cancel)

                window._set_readiness("ffmpeg", "7.1", "success")
                readiness_dot, readiness_value = window.readiness_values["ffmpeg"]
                self.assertEqual(
                    readiness_dot.accessibleName(),
                    "FFmpeg status indicator: 7.1",
                )
                self.assertEqual(
                    readiness_value.accessibleName(),
                    "FFmpeg status: 7.1",
                )
                self.assertEqual(window.log_text.accessibleName(), "Server log")
                self.assertIn("Server status", window.status_dot.accessibleName())
                self.assertTrue(window.status_label.text())

                with mock.patch.dict(os.environ, {"ASTRA_REDUCED_MOTION": "1"}):
                    window._animate_page()
                self.assertIsNone(window._page_anim)
                self.assertIsNone(window.tabs.currentWidget().graphicsEffect())
            finally:
                window.update_timer.stop()
                window.cleanup_timer.stop()
                window.tools_status_timer.stop()
                window.tray.hide()
                window._force_exit = True
                window.close()
                QApplication.processEvents()
                self._retained_windows.append(window)

    def test_download_queue_and_settings_actions_stay_in_the_primary_view(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication, QScrollArea

        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.MainWindow, "_refresh_tools_status"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                window.resize(1120, 760)
                window.show()
                window._nav_click("Download")
                window._update_ui()
                QApplication.processEvents()

                self.assertTrue(window.quick_download_advanced.isHidden())
                self.assertTrue(window.preflight_details.isHidden())
                self.assertTrue(window.downloads_scroll.isVisible())
                queue_top = window.downloads_scroll.mapTo(window, QPoint(0, 0)).y()
                self.assertLess(queue_top, window.height())

                window.btn_quick_options.setChecked(True)
                QApplication.processEvents()
                self.assertTrue(window.quick_download_advanced.isVisible())
                self.assertEqual(window.btn_quick_options.text(), "Fewer options")

                for key in window.preflight_values:
                    window._set_preflight_row(key, "ok")
                window._update_preflight_summary()
                self.assertEqual(
                    window.preflight_summary.text(),
                    f"All {len(window.preflight_values)} checks passed. "
                    "Downloads are ready.",
                )
                window._set_preflight_row("ffmpeg-capabilities", "error")
                window._update_preflight_summary()
                self.assertTrue(window.preflight_details.isVisible())

                window._nav_click("Settings")
                QApplication.processEvents()
                settings_root = window.tabs.currentWidget()
                settings_scroll = settings_root.findChild(QScrollArea)
                self.assertIsNotNone(settings_scroll)
                settings_scroll.verticalScrollBar().setValue(
                    settings_scroll.verticalScrollBar().maximum()
                )
                QApplication.processEvents()
                self.assertTrue(window.btn_save.isVisible())
                save_top = window.btn_save.mapTo(window, QPoint(0, 0)).y()
                self.assertLess(save_top, window.height())
            finally:
                window.update_timer.stop()
                window.cleanup_timer.stop()
                window.tools_status_timer.stop()
                window.tray.hide()
                window._force_exit = True
                window.close()
                QApplication.processEvents()
                self._retained_windows.append(window)

    def test_make_line_icon_renders_glyph_at_native_requested_size(self):
        from PySide6.QtCore import QSize
        # The default 18 px icon cannot satisfy a 36 px request without
        # upscaling, so QIcon.actualSize caps at the stored 18 px pixmap.
        small = ad.make_line_icon("history")
        self.assertEqual(small.actualSize(QSize(36, 36)), QSize(18, 18))
        # Requesting size=36 authors the glyph natively, so the empty-state
        # rasterizes crisply instead of doubling an 18 px pixmap.
        native = ad.make_line_icon("history", size=36)
        self.assertEqual(native.actualSize(QSize(36, 36)), QSize(36, 36))
        self.assertFalse(native.pixmap(36, 36).isNull())

    def test_make_line_icon_allocates_the_backing_store_at_the_device_ratio(self):
        # At 125/150/200 % scaling an 18 px backing pixmap is upscaled by Qt
        # and every stroke goes soft. The backing store must be allocated at
        # size × dpr with the ratio stamped on the pixmap.
        gs = gui_module_for_tests()
        hidpi = gs.make_line_icon("history", size=18, dpr=2.0)
        sizes = hidpi.availableSizes()
        self.assertTrue(sizes, "the icon must expose its pixmap size")
        self.assertEqual((sizes[0].width(), sizes[0].height()), (36, 36))
        fractional = gs.make_line_icon("history", size=18, dpr=1.25)
        sizes = fractional.availableSizes()
        self.assertEqual((sizes[0].width(), sizes[0].height()), (22, 22))

    def test_folder_picker_service_constructs_and_starts_timer(self):
        svc = ad.FolderPickerService()
        try:
            self.assertIsNotNone(svc._timer,
                                 "FolderPickerService must own a QTimer for the dispatch loop")
            self.assertTrue(svc._timer.isActive(),
                            "FolderPickerService timer must start active so the dispatch loop polls")
            # 150 ms cadence matches the pick-folder Flask handler's
            # expectation that the GUI side is responsive enough to
            # service a request within the 120 s overall timeout.
            self.assertEqual(svc._timer.interval(), 150,
                             "FolderPickerService timer cadence must be 150 ms")
        finally:
            svc._timer.stop()
            svc.deleteLater()

    def test_folder_picker_tick_no_pending_request_is_noop(self):
        # Empty queue must not raise and must not emit any response.
        svc = ad.FolderPickerService()
        try:
            # Verify queue is empty.
            self.assertTrue(ad._folder_pick_q.empty())
            # Direct tick call — no request enqueued, must return cleanly.
            svc._tick()
            # Queue still empty; no side effects.
            self.assertTrue(ad._folder_pick_q.empty())
        finally:
            svc._timer.stop()
            svc.deleteLater()

    def test_folder_picker_tick_returns_accepted_path(self):
        # Mock QFileDialog so .exec() returns Accepted + selectedFiles
        # without actually opening a dialog. The patch targets the
        # bound name in ad's namespace so the FolderPickerService
        # picks up the fake.
        import queue
        response_q = queue.Queue(maxsize=1)
        ad._folder_pick_q.put({'initial': '', 'response': response_q})

        from PySide6.QtWidgets import QFileDialog as RealQFileDialog
        fake_dialog = mock.MagicMock()
        fake_dialog.exec.return_value = RealQFileDialog.DialogCode.Accepted
        fake_dialog.selectedFiles.return_value = ['/tmp/picked-folder']
        fake_dialog.windowFlags.return_value = 0
        with mock.patch.object(ad, 'QFileDialog', autospec=False) as FakeFileDialog:
            FakeFileDialog.return_value = fake_dialog
            # Re-export the DialogCode/FileMode enums the real class
            # carried so the source code's qualified-name references
            # still resolve.
            FakeFileDialog.DialogCode = RealQFileDialog.DialogCode
            FakeFileDialog.FileMode = RealQFileDialog.FileMode
            FakeFileDialog.Option = RealQFileDialog.Option
            svc = ad.FolderPickerService()
            try:
                svc._tick()
            finally:
                svc._timer.stop()
                svc.deleteLater()

        result = response_q.get(timeout=1.0)
        self.assertEqual(result.get('path'), '/tmp/picked-folder',
                         "Accepted dialog must enqueue the chosen path")
        self.assertFalse(result.get('cancelled'),
                         "Accepted dialog must report cancelled=False")

    def test_folder_picker_tick_returns_cancelled_on_reject(self):
        import queue
        response_q = queue.Queue(maxsize=1)
        ad._folder_pick_q.put({'initial': '', 'response': response_q})

        from PySide6.QtWidgets import QFileDialog as RealQFileDialog
        fake_dialog = mock.MagicMock()
        fake_dialog.exec.return_value = RealQFileDialog.DialogCode.Rejected
        fake_dialog.windowFlags.return_value = 0
        with mock.patch.object(ad, 'QFileDialog', autospec=False) as FakeFileDialog:
            FakeFileDialog.return_value = fake_dialog
            FakeFileDialog.DialogCode = RealQFileDialog.DialogCode
            FakeFileDialog.FileMode = RealQFileDialog.FileMode
            FakeFileDialog.Option = RealQFileDialog.Option
            svc = ad.FolderPickerService()
            try:
                svc._tick()
            finally:
                svc._timer.stop()
                svc.deleteLater()

        result = response_q.get(timeout=1.0)
        self.assertIsNone(result.get('path'),
                          "Rejected dialog must enqueue path=None")
        self.assertTrue(result.get('cancelled'),
                        "Rejected dialog must report cancelled=True")

    def test_folder_picker_nested_timer_tick_does_not_stack_second_dialog(self):
        # dialog.exec() spins a nested Qt event loop that keeps delivering
        # the 150 ms QTimer. Before the _dialog_open guard, a /pick-folder
        # request arriving mid-exec was drained by the re-entrant tick and
        # opened a second native dialog stacked on the first. The nested
        # tick must now no-op, leaving the request queued for the first
        # tick after the open dialog closes.
        import queue as queue_mod
        response_a = queue_mod.Queue(maxsize=1)
        response_b = queue_mod.Queue(maxsize=1)
        ad._folder_pick_q.put({'initial': '', 'response': response_a})

        from PySide6.QtWidgets import QFileDialog as RealQFileDialog
        created = []
        svc_ref = {}

        def fake_dialog(*_args, **_kwargs):
            dialog = mock.MagicMock()
            created.append(dialog)

            def nested_exec():
                if len(created) == 1:
                    # Simulate a second /pick-folder arriving and the QTimer
                    # firing inside the first dialog's nested event loop.
                    ad._folder_pick_q.put({'initial': '', 'response': response_b})
                    svc_ref['svc']._tick()
                return RealQFileDialog.DialogCode.Rejected

            dialog.exec.side_effect = nested_exec
            dialog.windowFlags.return_value = 0
            dialog.selectedFiles.return_value = []
            return dialog

        with mock.patch.object(ad, 'QFileDialog', autospec=False) as FakeFileDialog:
            FakeFileDialog.side_effect = fake_dialog
            FakeFileDialog.DialogCode = RealQFileDialog.DialogCode
            FakeFileDialog.FileMode = RealQFileDialog.FileMode
            FakeFileDialog.Option = RealQFileDialog.Option
            svc = ad.FolderPickerService()
            svc_ref['svc'] = svc
            try:
                svc._tick()
                self.assertEqual(len(created), 1,
                                 "the re-entrant tick must not stack a second dialog")
                result_a = response_a.get(timeout=1.0)
                self.assertTrue(result_a.get('cancelled'))
                # The second request stayed queued (not dropped, not answered)
                # and is serviced sequentially by the next tick.
                self.assertTrue(response_b.empty())
                self.assertFalse(ad._folder_pick_q.empty())
                svc._tick()
                self.assertEqual(len(created), 2)
                result_b = response_b.get(timeout=1.0)
                self.assertTrue(result_b.get('cancelled'))
            finally:
                svc._timer.stop()
                svc.deleteLater()

    def test_folder_picker_discards_request_cancelled_after_http_timeout(self):
        # A second request can remain queued while the first native dialog is
        # open. The route marks it cancelled when its 120 s wait expires; the
        # next GUI tick must consume it without opening an orphaned dialog.
        import queue as queue_mod
        response_a = queue_mod.Queue(maxsize=1)
        response_b = queue_mod.Queue(maxsize=1)
        cancellation_b = threading.Event()
        ad._folder_pick_q.put({'initial': '', 'response': response_a})

        from PySide6.QtWidgets import QFileDialog as RealQFileDialog
        created = []

        def fake_dialog(*_args, **_kwargs):
            dialog = mock.MagicMock()
            created.append(dialog)

            def first_exec():
                # This is the request that timed out while the first dialog
                # was open; it is still in the bounded queue.
                ad._folder_pick_q.put({
                    'initial': '',
                    'response': response_b,
                    'cancelled': cancellation_b,
                })
                cancellation_b.set()
                return RealQFileDialog.DialogCode.Rejected

            dialog.exec.side_effect = first_exec
            dialog.windowFlags.return_value = 0
            dialog.selectedFiles.return_value = []
            return dialog

        with mock.patch.object(ad, 'QFileDialog', autospec=False) as FakeFileDialog:
            FakeFileDialog.side_effect = fake_dialog
            FakeFileDialog.DialogCode = RealQFileDialog.DialogCode
            FakeFileDialog.FileMode = RealQFileDialog.FileMode
            FakeFileDialog.Option = RealQFileDialog.Option
            svc = ad.FolderPickerService()
            try:
                svc._tick()
                self.assertEqual(len(created), 1)
                response_a.get(timeout=1.0)
                svc._tick()
                self.assertEqual(
                    len(created),
                    1,
                    'a timed-out request must not open a ghost folder dialog',
                )
                self.assertTrue(ad._folder_pick_q.empty())
                self.assertTrue(response_b.empty())
            finally:
                svc._timer.stop()
                svc.deleteLater()

    def test_folder_picker_watchdog_fires_when_dialog_blocks_past_threshold(self):
        # Mock time.time so the watchdog believes the dialog blocked
        # for (threshold + 5) seconds. write_persistent_log is
        # spied so we can assert the log line shape.
        import queue
        response_q = queue.Queue(maxsize=1)
        ad._folder_pick_q.put({'initial': '/initial/path', 'response': response_q})

        from PySide6.QtWidgets import QFileDialog as RealQFileDialog
        fake_dialog = mock.MagicMock()
        fake_dialog.exec.return_value = RealQFileDialog.DialogCode.Rejected
        fake_dialog.windowFlags.return_value = 0

        threshold = ad.FolderPickerService.DIALOG_WATCHDOG_THRESHOLD_SECONDS
        # Two ticks of time.time(): start, then end (start + threshold + 5)
        time_seq = iter([1000.0, 1000.0 + threshold + 5])

        log_lines = []
        orig_log = ad.write_persistent_log
        ad.write_persistent_log = lambda msg, path=None: log_lines.append(msg)
        try:
            with mock.patch.object(ad, 'QFileDialog', autospec=False) as FakeFileDialog, \
                 mock.patch.object(ad.time, 'time', side_effect=lambda: next(time_seq)):
                FakeFileDialog.return_value = fake_dialog
                FakeFileDialog.DialogCode = RealQFileDialog.DialogCode
                FakeFileDialog.FileMode = RealQFileDialog.FileMode
                FakeFileDialog.Option = RealQFileDialog.Option
                svc = ad.FolderPickerService()
                try:
                    svc._tick()
                finally:
                    svc._timer.stop()
                    svc.deleteLater()
        finally:
            ad.write_persistent_log = orig_log

        # Drain the response queue (the dialog code still enqueues
        # cancelled=True; the watchdog runs in parallel with the
        # normal completion path).
        response_q.get(timeout=1.0)
        self.assertTrue(
            any("FolderPickerService: dialog blocked for" in line for line in log_lines),
            f"Watchdog must emit the documented log prefix; got {log_lines!r}",
        )
        self.assertTrue(
            any(f"threshold {threshold}s" in line for line in log_lines),
            f"Watchdog log must surface the threshold; got {log_lines!r}",
        )


class TrayCompletionNotifyTests(unittest.TestCase):
    """Download-complete tray notification: one-shot, out-of-sight-only,
    toggleable. 'Out of sight' = hidden to tray OR minimized to taskbar —
    both states where the user can't see the queue (the settings label says
    'while minimized')."""

    def _window(self, hidden=True, notify=True, minimized=False):
        msgs = []
        tray = types.SimpleNamespace(showMessage=lambda *a: msgs.append(a))
        win = types.SimpleNamespace(
            config=FakeConfig({"NotifyOnComplete": notify}),
            _seen_complete=set(),
            tray=tray,
            isHidden=lambda: hidden,
            isMinimized=lambda: minimized,
        )
        return win, msgs

    @staticmethod
    def _dl(dl_id, status, title="T"):
        return types.SimpleNamespace(id=dl_id, status=status, title=title)

    def test_notifies_once_per_completion_when_hidden(self):
        win, msgs = self._window(hidden=True)
        dls = [self._dl("a", "complete"), self._dl("b", "downloading")]
        ad.MainWindow._notify_completed_downloads(win, dls)
        ad.MainWindow._notify_completed_downloads(win, dls)  # second tick
        self.assertEqual(len(msgs), 1, "notifies exactly once, not every tick")

    def test_completion_seen_while_visible_never_notifies_later(self):
        win, msgs = self._window(hidden=False)
        dls = [self._dl("a", "complete")]
        ad.MainWindow._notify_completed_downloads(win, dls)
        self.assertEqual(len(msgs), 0)
        win.isHidden = lambda: True
        ad.MainWindow._notify_completed_downloads(win, dls)
        self.assertEqual(len(msgs), 0, "a completion seen while visible must not fire a stale toast")

    def test_toggle_off_suppresses_notification(self):
        win, msgs = self._window(hidden=True, notify=False)
        ad.MainWindow._notify_completed_downloads(win, [self._dl("a", "complete")])
        self.assertEqual(len(msgs), 0)

    def test_taskbar_minimized_window_notifies(self):
        # A minimized-but-not-hidden window (title-bar minimize, no
        # close-to-tray) is the most common "while minimized" state — the
        # user can't see the queue, so the toast must fire.
        win, msgs = self._window(hidden=False, minimized=True)
        ad.MainWindow._notify_completed_downloads(win, [self._dl("a", "complete")])
        self.assertEqual(len(msgs), 1)

    def test_seen_set_is_pruned_to_present_downloads(self):
        win, _ = self._window(hidden=True)
        ad.MainWindow._notify_completed_downloads(win, [self._dl("a", "complete")])
        self.assertIn("a", win._seen_complete)
        ad.MainWindow._notify_completed_downloads(win, [self._dl("b", "downloading")])
        self.assertNotIn("a", win._seen_complete, "reclaimed ids are pruned so the set can't grow")


class ClipboardLinkGrabberTests(unittest.TestCase):
    """Clipboard capture stages reviewed media URLs and never enqueues them."""

    class _TextWidget:
        def __init__(self):
            self.value = ""
            self.visible = False
            self.properties = {}

        def setText(self, value):
            self.value = value

        def text(self):
            return self.value

        def setProperty(self, key, value):
            self.properties[key] = value

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

    def _window(self, enabled=True):
        messages = []
        logs = []
        window = types.SimpleNamespace(
            config=FakeConfig({"ClipboardLinkGrabber": enabled}),
            _clipboard_last_seen="",
            _clipboard_staged_url="",
            _dependencies={
                "normalize_url": ad.normalize_url,
                "looks_like_media_link": ad.looks_like_media_link,
            },
            quick_download_url=self._TextWidget(),
            quick_download_status=self._TextWidget(),
            _append_log=logs.append,
            _value=lambda key: ad.APP_NAME if key == "APP_NAME" else None,
            tray=types.SimpleNamespace(showMessage=lambda *args: messages.append(args)),
        )
        return window, messages, logs

    def test_disabled_grabber_ignores_youtube_url(self):
        window, messages, logs = self._window(enabled=False)
        ad.MainWindow._handle_clipboard_change(
            window, "https://youtu.be/abcdefghijk"
        )
        self.assertEqual(window.quick_download_url.text(), "")
        self.assertEqual(messages, [])
        self.assertEqual(logs, [])

    def test_enabled_grabber_ignores_non_media_and_private_links(self):
        import gui as gui_module

        window, messages, logs = self._window()
        with mock.patch.object(gui_module, "repolish"):
            for ignored in (
                "https://example.com/pricing",      # public, but not media-shaped
                "http://127.0.0.1:9751/watch",      # loopback: never stageable
                "http://nas.local/videos/clip.mp4",  # private host wins over path
                "not a url at all",
            ):
                ad.MainWindow._handle_clipboard_change(window, ignored)
                self.assertEqual(window.quick_download_url.text(), "", ignored)
        self.assertEqual(messages, [])

    def test_enabled_grabber_stages_any_supported_site_and_deduplicates(self):
        import gui as gui_module

        for url in (
            "https://www.youtube.com/watch?v=abcdefghijk",
            "https://www.reddit.com/r/videos/comments/abc/clip/",
            "https://x.com/someone/status/1234567890",
            "https://vimeo.com/123456789",
            "https://cdn.example.com/assets/clip.mp4",
        ):
            window, messages, logs = self._window()
            with mock.patch.object(gui_module, "repolish"):
                ad.MainWindow._handle_clipboard_change(window, f"  {url}  ")
                ad.MainWindow._handle_clipboard_change(window, url)

            self.assertEqual(window.quick_download_url.text(), url)
            self.assertEqual(window._clipboard_staged_url, url)
            self.assertTrue(window.quick_download_status.visible)
            self.assertEqual(
                window.quick_download_status.properties["tone"], "success"
            )
            self.assertIn("Review the options", window.quick_download_status.text())
            # Deduplicated: the repeat paste must not notify or log twice.
            self.assertEqual(len(messages), 1, url)
            self.assertEqual(logs, ["Staged a copied video link for review."], url)

    def test_clearing_a_staged_url_lets_the_same_clipboard_restage(self):
        import gui as gui_module

        window, _messages, _logs = self._window()
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        with mock.patch.object(gui_module, "repolish"):
            ad.MainWindow._handle_clipboard_change(window, url)
        self.assertEqual(window._clipboard_last_seen, url)
        window._sync_quick_download_profile = lambda **_kwargs: None
        window._schedule_format_probe = lambda: None
        window._sync_playlist_staging_button = lambda: None
        ad.MainWindow._quick_download_url_edited(window)
        self.assertEqual(window._clipboard_last_seen, "")
        self.assertEqual(window._clipboard_staged_url, "")
        with mock.patch.object(gui_module, "repolish"):
            ad.MainWindow._handle_clipboard_change(window, url)
        self.assertEqual(window._clipboard_staged_url, url)


class QuickDownloadBatchTests(unittest.TestCase):
    """The standalone quick-download box accepts one link or a whole paste."""

    class _TextWidget:
        def __init__(self, value=""):
            self.value = value
            self.visible = False
            self.properties = {}

        def setText(self, value):
            self.value = value

        def text(self):
            return self.value

        def clear(self):
            self.value = ""

        def setProperty(self, key, value):
            self.properties[key] = value

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

    class _Combo:
        def __init__(self, value):
            self.value = value

        def currentData(self):
            return self.value

    def _window(self, url_text, results, start="", end="", kind="video"):
        calls = []

        def start_download(**kwargs):
            calls.append(kwargs)
            return results[len(calls) - 1]

        window = types.SimpleNamespace(
            quick_download_url=self._TextWidget(url_text),
            quick_download_start=self._TextWidget(start),
            quick_download_end=self._TextWidget(end),
            quick_download_status=self._TextWidget(),
            quick_download_type=self._Combo(kind),
            quick_download_format=self._Combo("mp4"),
            quick_download_quality=self._Combo("best"),
            dl_manager=types.SimpleNamespace(start_download=start_download),
            _dependencies={
                "normalize_download_section": ad.normalize_download_section,
            },
            _clipboard_staged_url="",
            _quick_download_dir="",
            _set_quick_download_dir=lambda _path: None,
            _append_log=lambda *_args: None,
            _update_ui=lambda: None,
        )
        window._set_quick_download_status = types.MethodType(
            gui_module_for_tests().MainWindowCore._set_quick_download_status, window
        )
        return window, calls

    def test_the_download_type_decides_which_job_is_queued(self):
        # The combo used to carry an audio_only boolean. It now names a kind,
        # because there are three of them and bool("subtitles") is True — the
        # old shape would have queued a subtitles request as an audio one.
        for kind, expected in (
            ("video", {"audio_only": False, "subtitles_only": False}),
            ("audio", {"audio_only": True, "subtitles_only": False}),
            ("subtitles", {"audio_only": False, "subtitles_only": True}),
        ):
            with self.subTest(kind=kind):
                window, calls = self._window(
                    "https://vimeo.com/1", [("dl_1", None)], kind=kind
                )
                with mock.patch.object(gui_module_for_tests(), "repolish"):
                    ad.MainWindow._start_quick_download(window)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["audio_only"], expected["audio_only"])
                self.assertEqual(
                    calls[0]["subtitles_only"], expected["subtitles_only"]
                )

    def test_single_link_queues_once(self):
        window, calls = self._window(
            " https://vimeo.com/1 ", [("dl_1", None)]
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        self.assertEqual([call["url"] for call in calls], ["https://vimeo.com/1"])
        self.assertIn("Queued dl_1", window.quick_download_status.text())
        self.assertEqual(window.quick_download_url.text(), "")

    def test_native_clip_shortcuts_fill_the_queue_section(self):
        gui = gui_module_for_tests()
        for method_name, expected in (
            (
                "_set_quick_clip_from_url",
                {"start": "*from-url", "end": "inf"},
            ),
            (
                "_set_quick_clip_last_30",
                {"start": "*-30", "end": "inf"},
            ),
        ):
            with self.subTest(method=method_name):
                window, calls = self._window(
                    "https://vimeo.com/1", [("dl_1", None)]
                )
                window._sabr_limited = False
                for name in (
                    "_set_quick_clip_selector",
                    "_set_quick_clip_from_url",
                    "_set_quick_clip_last_30",
                ):
                    setattr(
                        window,
                        name,
                        types.MethodType(
                            getattr(gui.MainWindowCore, name), window
                        ),
                    )
                getattr(window, method_name)()
                with mock.patch.object(gui, "repolish"):
                    ad.MainWindow._start_quick_download(window)
                self.assertEqual(calls[0]["section"], expected)

    def test_probed_size_reaches_the_central_queue_preflight(self):
        window, calls = self._window(
            "https://vimeo.com/1", [(None, "Not enough free disk space.")]
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            window.config = FakeConfig({"DownloadPath": tmpdir})
            window._format_probe_summary_url = "https://vimeo.com/1"
            window._format_probe_summary = {
                "formats": [{
                    "has_video": True,
                    "has_audio": True,
                    "height": 1080,
                    "filesize": 500,
                }],
            }
            window._dependencies.update({
                "normalize_url": ad.normalize_url,
            })
            with mock.patch.object(gui_module_for_tests(), "repolish"):
                ad.MainWindow._start_quick_download(window)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["format_summary"], window._format_probe_summary)
        self.assertEqual(
            window.quick_download_status.properties["tone"], "danger"
        )
        self.assertIn("free disk space", window.quick_download_status.text())

    def test_multiple_pasted_links_queue_as_a_batch(self):
        urls = [
            "https://www.youtube.com/watch?v=a",
            "https://www.reddit.com/r/videos/comments/b/c/",
            "https://x.com/u/status/3",
        ]
        window, calls = self._window(
            "  ".join(urls), [("dl_1", None), ("dl_2", None), ("dl_3", None)]
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        self.assertEqual([call["url"] for call in calls], urls)
        self.assertIn("Queued 3 downloads", window.quick_download_status.text())
        self.assertEqual(
            window.quick_download_status.properties["tone"], "success"
        )

    def test_batch_reports_rejected_links_without_losing_the_accepted_ones(self):
        window, calls = self._window(
            "https://vimeo.com/1 http://127.0.0.1/x",
            [("dl_1", None), (None, "That address is on a private network.")],
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        self.assertEqual(len(calls), 2)
        text = window.quick_download_status.text()
        self.assertIn("Queued dl_1", text)
        self.assertIn("1 link rejected", text)
        self.assertNotIn("link(s)", text, "placeholder plurals are not shipped copy")
        self.assertEqual(
            window.quick_download_status.properties["tone"], "warning"
        )

    def test_batch_pluralises_and_does_not_merge_distinct_reasons(self):
        window, calls = self._window(
            "https://vimeo.com/1 http://127.0.0.1/x http://nas/y",
            [
                ("dl_1", None),
                (None, "That address is on a private network."),
                (None, "That address is on a private network."),
            ],
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        text = window.quick_download_status.text()
        self.assertIn("2 links rejected", text)
        self.assertNotIn("different reasons", text,
                         "one shared cause should be stated once")

        window, _calls = self._window(
            "https://vimeo.com/1 http://127.0.0.1/x not-a-url",
            [
                ("dl_1", None),
                (None, "That address is on a private network."),
                (None, "Enter a valid http or https URL."),
            ],
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        text = window.quick_download_status.text()
        self.assertIn("2 links rejected for 2 different reasons", text,
                      "two causes must not be reported as one")

    def test_clip_range_requires_a_single_link(self):
        window, calls = self._window(
            "https://vimeo.com/1 https://vimeo.com/2", [], start="0:05", end="0:10"
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        self.assertEqual(calls, [], "nothing may queue when the request is ambiguous")
        self.assertIn("single link", window.quick_download_status.text())
        self.assertEqual(window.quick_download_status.properties["tone"], "danger")

    def test_empty_box_reports_instead_of_queueing_nothing(self):
        window, calls = self._window("   ", [])
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            ad.MainWindow._start_quick_download(window)
        self.assertEqual(calls, [])
        self.assertIn("Paste a video link", window.quick_download_status.text())


class TranslationCoverageTests(unittest.TestCase):
    """An advertised locale must not be an English catalogue in disguise."""

    # Every locale below `SOURCE_STRINGS` in the builder falls back to its own
    # English source, which Qt needs but which also makes an empty catalogue
    # indistinguishable from a finished one. These are the locales known to be
    # incomplete; the list is the localisation backlog, stated in code instead
    # of hidden inside XML that looks translated.
    KNOWN_INCOMPLETE = {
        "ar", "es", "fr", "it", "ja", "ko", "pt_BR", "ru", "zh_CN",
    }

    def _builder(self):
        import importlib.util
        root = Path(ad.__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "build_companion_translations",
            root / "scripts" / "build-companion-translations.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _checker(self):
        import importlib.util
        root = Path(ad.__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "check_companion_translations",
            root / "scripts" / "check-companion-translations.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_advertised_locales_clear_the_non_fallback_translation_floor(self):
        import i18n as i18n_module

        checker = self._checker()
        self.assertEqual(
            checker.ADVERTISED_LOCALES,
            i18n_module.ADVERTISED_LOCALES,
        )
        self.assertEqual(
            checker.COMPANION_LOCALE_MIN_COVERAGE,
            i18n_module.COMPANION_LOCALE_MIN_COVERAGE,
        )
        expected = set(self._builder().SOURCE_STRINGS)
        for locale in i18n_module.ADVERTISED_LOCALES:
            if locale == "en":
                continue
            translated, total = checker.translated_coverage(
                Path(ad.__file__).parents[1]
                / "astra_downloader"
                / "translations"
                / f"astra_downloader_{locale}.ts",
                expected,
            )
            self.assertGreaterEqual(
                translated / total,
                i18n_module.COMPANION_LOCALE_MIN_COVERAGE,
                f"{locale} is below the picker floor",
            )

    def test_german_is_complete(self):
        # The one locale the product actually ships. If it regresses, the
        # German smoke scenario is asserting against a catalogue that lost
        # its content.
        coverage = self._builder().catalogue_coverage()
        translated, total = coverage["de"]
        self.assertEqual(translated, total,
                         f"German lost translations: {translated}/{total}")

    def test_extractor_covers_runtime_modules_and_accessibility_help(self):
        # Recovery guidance lives outside gui.py so the extractor must prove
        # that its source boundary follows the module that owns each message.
        import importlib.util

        root = Path(ad.__file__).parents[1]
        spec = importlib.util.spec_from_file_location(
            "extract_companion_strings",
            root / "scripts" / "extract_companion_strings.py",
        )
        extractor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extractor)
        self.assertEqual(
            {path.name for path in extractor.SOURCE_FILES},
            {
                "gui.py",
                "gui_support.py",
                "gui_download_page.py",
                "gui_history_page.py",
                "gui_site_logins_page.py",
                "gui_subscriptions_page.py",
                "gui_extension_page.py",
                "gui_settings_page.py",
                "download.py",
                "health.py",
            },
        )
        strings = set(extractor.extract_all())
        for expected in (
            "The site refused further requests for now (HTTP 429).",
            "This link only offers SABR streams. {options} do not apply to them and will be ignored.",
            "Antivirus software may have removed or truncated it. Add an exclusion for {path} and let setup fetch it again.",
            "Review the redacted support payload before copying it.",
            "{label} status indicator: {value}",
            "Format",
            "Quality",
            "Duration",
            "Search title or filename",
            "Show Astra Downloader",
            "Review diagnostics",
            "{total} configured · {archived} archived · {queued} queued",
            "Added {title}. The first scan is scheduled now.",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, strings)
        for data in (
            "YYYY-MM-DD",
            "%(title)s.%(ext)s",
            "https://proxy.example:8080",
        ):
            with self.subTest(data=data):
                self.assertNotIn(data, strings)

    def test_an_undeclared_string_is_not_counted_as_translated(self):
        # The measurement itself: the builder writes a missing entry out as
        # its own English source, so only a declared key is coverage.
        builder = self._builder()
        original = builder.CATALOGS["de"].pop("Best")
        try:
            declared, total = builder.catalogue_coverage()["de"]
            self.assertEqual(declared, total - 1)
        finally:
            builder.CATALOGS["de"]["Best"] = original

    def test_a_translation_that_matches_english_still_counts(self):
        # German keeps "Video", "Audio" and "Server offline" unchanged. Those
        # are decisions, not gaps, and counting differences would report a
        # finished catalogue as incomplete.
        builder = self._builder()
        german = builder.CATALOGS["de"]
        identical = [
            source for source in builder.SOURCE_STRINGS
            if german.get(source) == source
        ]
        self.assertTrue(identical, "expected at least one identical rendering")
        declared, total = builder.catalogue_coverage()["de"]
        self.assertEqual(declared, total)

    def test_every_preflight_repair_button_reaches_the_catalogues(self):
        # `tr(labels.get(action))` passes a Call, and the extractor only reads
        # literals passed to tr(), so ten repair buttons stayed English inside
        # a fully translated panel. Each label has to be its own tr("...").
        import ast
        import textwrap

        import gui_download_page

        builder = self._builder()
        known = set(builder.SOURCE_STRINGS)
        source = textwrap.dedent(
            inspect.getsource(ad.MainWindow._set_preflight_row))
        labels = {}
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not (isinstance(value, ast.Call)
                        and getattr(value.func, "id", "") == "tr"
                        and value.args
                        and isinstance(value.args[0], ast.Constant)):
                    continue
                labels[key.value] = value.args[0].value

        actions = {action for _key, _label, action
                   in gui_download_page.PREFLIGHT_ROW_SPECS}
        self.assertTrue(actions)
        missing_labels = sorted(actions - set(labels))
        self.assertEqual(
            missing_labels, [],
            "a repair action with no tr() label falls back to a bare Fix button",
        )
        # Every advertised locale ships a .ts entry for every source string;
        # the nine incomplete ones carry English as the translation, which is
        # what Qt needs for a clean fallback and what the blocked
        # localisation item is about. What this asserts is the part that is
        # this project's to get right: the label reaches the extractor, it
        # lands in all eleven catalogue files, and the one locale with a
        # translator has a real translation for it.
        import xml.etree.ElementTree as ElementTree

        translations_dir = Path(ad.__file__).resolve().parent / "translations"
        declared = {}
        for catalogue in sorted(translations_dir.glob("astra_downloader_*.ts")):
            locale = catalogue.stem.split("astra_downloader_", 1)[1]
            declared[locale] = {
                (message.findtext("source") or ""): (
                    message.findtext("translation") or "")
                for message in ElementTree.parse(catalogue).iter("message")
            }
        self.assertEqual(len(declared), 11, sorted(declared))

        for action in sorted(actions):
            with self.subTest(action=action):
                label = labels[action]
                self.assertIn(
                    label, known,
                    f"{label!r} never reaches the extractor, so no locale can "
                    "translate it",
                )
                for locale, catalogue in declared.items():
                    self.assertIn(
                        label, catalogue, f"{locale}.ts lacks {label!r}")
                self.assertNotEqual(
                    declared["de"][label], "",
                    f"German declares {label!r} with no translation",
                )
        # German is the complete locale; a label left in English there is the
        # regression this test exists for, not a translator backlog.
        untranslated = sorted(
            labels[action] for action in actions
            if declared["de"][labels[action]] == labels[action]
        )
        self.assertEqual(
            untranslated, [],
            "these repair buttons still render English in the German window",
        )

    def test_the_incomplete_locales_are_exactly_the_declared_ones(self):
        # A new locale added with only its nav strings joins this list
        # deliberately, and a locale that gets finished has to leave it.
        coverage = self._builder().catalogue_coverage()
        incomplete = {
            locale for locale, (done, total) in coverage.items()
            if locale != "en" and done < total
        }
        self.assertEqual(incomplete, self.KNOWN_INCOMPLETE)

    def test_every_locale_translates_the_navigation_rail(self):
        # The floor: whatever else is missing, the rail is what an advertised
        # locale must at least deliver.
        builder = self._builder()
        rail = ("Download", "History", "Sign-ins", "Browser extension",
                "Settings")
        for locale, translations in builder.CATALOGS.items():
            if locale == "en":
                continue
            for source in rail:
                with self.subTest(locale=locale, source=source):
                    self.assertNotEqual(
                        translations.get(source, source), source,
                        f"{locale} does not translate the rail entry {source!r}",
                    )

    def test_the_shipped_arabic_catalogue_really_is_mostly_english(self):
        # The generated .ts is what ships, and it is where the gap becomes
        # user-visible: an Arabic window renders mirrored chrome around
        # English body text. Confirmed against the file, not only the table.
        import re
        translations = Path(ad.__file__).parent / "translations"
        text = (translations / "astra_downloader_ar.ts").read_text(
            encoding="utf-8")
        pairs = re.findall(
            r"<source>(.*?)</source>\s*<translation>(.*?)</translation>",
            text, re.S,
        )
        self.assertTrue(pairs)
        english = [source for source, value in pairs
                   if source.strip() == value.strip()]
        self.assertIn("Download a video", english)
        self.assertIn("Pause intake", english)
        # And the rail, which every locale does translate, is not among them.
        for source in ("Download", "History", "Settings"):
            self.assertNotIn(source, english)


class RightToLeftLayoutTests(unittest.TestCase):
    """Arabic flips the layout, and the smoke set now renders one."""

    def _renderer(self):
        import importlib.util

        root = Path(ad.__file__).parents[1]
        path = root / "scripts" / "render-companion-gui.py"
        spec = importlib.util.spec_from_file_location(
            "astra_rtl_renderer", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _render(self, scenario):
        renderer = self._renderer()
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["ASTRA_COMPANION_RENDER_SCENARIO"] = scenario
        result = subprocess.run(
            [sys.executable, str(Path(renderer.__file__))],
            cwd=Path(ad.__file__).parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        capture = renderer.OUTPUT_DIR / f"{scenario}.png"
        self.assertTrue(capture.is_file())
        self.assertGreater(capture.stat().st_size, 10_000)

    def test_an_rtl_scenario_is_in_the_smoke_set(self):
        # No RTL locale was ever rendered, so no gate could see what the
        # mirrored layout did to the page.
        from PySide6.QtCore import Qt
        import i18n

        renderer = self._renderer()
        self.assertTrue({
            "downloads-arabic-rtl", "history-arabic-rtl",
            "settings-arabic-rtl", "site-logins-arabic-rtl",
            "subscriptions-arabic-rtl",
        } <= set(renderer.CAPTURE_NAMES))
        app = _get_qapp_or_skip(self)
        translator = i18n.install_companion_translator(app, "ar")
        try:
            self.assertEqual(
                app.layoutDirection(), Qt.LayoutDirection.RightToLeft
            )
            self.assertEqual(app.property("astraLocale"), "ar")
        finally:
            if translator is not None:
                app.removeTranslator(translator)
            i18n.install_companion_translator(app, "en")

    def test_the_rtl_scenario_asserts_the_row_actually_mirrors(self):
        self._render("downloads-arabic-rtl")

    def test_the_german_scenario_covers_every_page(self):
        self._render("dashboard-german")

    def test_the_german_strings_it_asserts_are_really_in_the_catalogue(self):
        import i18n

        app = _get_qapp_or_skip(self)
        translator = i18n.install_companion_translator(app, "de")
        self.assertIsNotNone(translator)
        try:
            for page in (
                "Download", "History", "Sign-ins", "Subscriptions",
                "Browser extension", "Settings",
            ):
                with self.subTest(page=page):
                    self.assertNotEqual(
                        translator.translate("AstraDownloader", page), page
                    )
        finally:
            app.removeTranslator(translator)
            i18n.install_companion_translator(app, "en")

    def test_arabic_is_the_only_right_to_left_locale_advertised(self):
        import i18n as i18n_module
        from PySide6.QtCore import Qt, QLocale
        rtl = {
            locale for locale in i18n_module.SUPPORTED_LOCALES
            if QLocale(locale).textDirection() == Qt.LayoutDirection.RightToLeft
        }
        self.assertEqual(rtl, {"ar"})


class SabrDisclosureTests(unittest.TestCase):
    """A SABR-only link says what it cannot honour before the run, not after."""

    @staticmethod
    def _summary(*protocols, audio="https"):
        formats = [
            {"has_video": True, "height": 720 + index, "protocol": protocol}
            for index, protocol in enumerate(protocols)
        ]
        formats.append({"has_video": False, "protocol": audio})
        return {"formats": formats}

    # ── The detection ────────────────────────────────────────────────────

    def test_a_url_serving_only_sabr_is_limited(self):
        self.assertTrue(ad.sabr_only_formats(self._summary("sabr", "sabr")))

    def test_one_ordinary_format_is_enough_to_be_unlimited(self):
        # The non-SABR format is what would be downloaded, so nothing is void.
        self.assertFalse(ad.sabr_only_formats(self._summary("sabr", "https")))

    def test_a_probe_with_no_video_is_not_treated_as_limited(self):
        for summary in ({}, {"formats": []}, {"formats": [{"has_video": False}]},
                        None, "nonsense"):
            self.assertFalse(ad.sabr_only_formats(summary), summary)

    def test_the_protocol_survives_the_summary(self):
        # The detection reads a field the summariser has to carry; a probe
        # that drops it would silently report every link as unlimited.
        summary = ad.summarize_ytdlp_formats({"formats": [
            {"format_id": "1", "ext": "mp4", "height": 720,
             "vcodec": "avc1", "acodec": "none", "protocol": "sabr"},
        ]})
        self.assertEqual(summary["formats"][0]["protocol"], "sabr")
        self.assertTrue(ad.sabr_only_formats(summary))

    def test_the_voided_options_read_as_a_sentence(self):
        self.assertEqual(
            ad.describe_sabr_voided_options(("a", "b", "c")), "a, b and c"
        )
        self.assertEqual(ad.describe_sabr_voided_options(("a",)), "a")
        self.assertEqual(ad.describe_sabr_voided_options(()), "")

    # ── What the user is told ────────────────────────────────────────────

    def _window(self):
        window = FormatProbeTests._window(FormatProbeTests())
        return window

    def test_a_sabr_link_disables_the_clip_range_and_explains(self):
        window = self._window()
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": self._summary("sabr"),
                "error": "",
            })
        self.assertFalse(window.quick_download_start.enabled)
        self.assertFalse(window.quick_download_end.enabled)
        hint = window.quick_download_clip_hint.text()
        self.assertIn("SABR", hint)
        for option in ("clip ranges", "bandwidth cap", "concurrent fragments"):
            self.assertIn(option, hint)

    def test_a_typed_clip_range_is_cleared_rather_than_silently_ignored(self):
        # Accepting the input and not delivering it is the failure mode this
        # exists to prevent.
        window = self._window()
        window.quick_download_start.setText("0:10")
        window.quick_download_end.setText("0:20")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_sabr_limits(True)
        self.assertEqual(window.quick_download_start.text(), "")
        self.assertEqual(window.quick_download_end.text(), "")

    def test_an_ordinary_link_leaves_the_clip_range_alone(self):
        window = self._window()
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": self._summary("https"),
                "error": "",
            })
        self.assertTrue(window.quick_download_start.enabled)
        self.assertIn("single link", window.quick_download_clip_hint.text())

    def test_editing_past_a_sabr_link_restores_the_clip_range(self):
        window = self._window()
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": self._summary("sabr"),
                "error": "",
            })
            self.assertFalse(window.quick_download_start.enabled)
            window.quick_download_url.setText("https://vimeo.com/2")
            window._format_probe_timer = types.SimpleNamespace(start=lambda: None)
            window._schedule_format_probe()
        self.assertTrue(window.quick_download_start.enabled)

    def test_the_failure_advice_names_what_was_dropped(self):
        payload = ad.download_error_payload("sabr-limited")
        advice = payload["advice"]
        for option in ("Clip ranges", "bandwidth cap", "concurrent fragments"):
            self.assertIn(option, advice)


class DiskSpacePreflightTests(unittest.TestCase):
    """Size estimates refuse a known-full destination before yt-dlp starts."""

    SUMMARY = {
        "formats": [
            {"has_video": True, "has_audio": True, "height": 720,
             "filesize": 50},
            {"has_video": True, "has_audio": False, "height": 1080,
             "filesize": 90},
            {"has_video": False, "has_audio": True, "filesize": 5},
        ],
    }

    def test_estimate_uses_the_larger_muxed_or_split_path(self):
        self.assertEqual(
            ad.estimate_download_bytes(self.SUMMARY, quality="best"),
            95,
        )
        self.assertEqual(
            ad.estimate_download_bytes(self.SUMMARY, quality="720"),
            50,
        )
        self.assertEqual(
            ad.estimate_download_bytes(self.SUMMARY, audio_only=True),
            50,
        )
        self.assertEqual(
            ad.estimate_download_bytes({"formats": [{"filesize": 0}]}),
            0,
        )

    def test_estimate_accounts_for_the_uncapped_best_fallback(self):
        fallback_size = 2 * 1024 * 1024 * 1024
        summary = {
            "formats": [{
                "has_video": True,
                "has_audio": True,
                "height": 2160,
                "filesize": fallback_size,
            }],
        }

        self.assertEqual(
            ad.estimate_download_bytes(summary, quality="1080"),
            fallback_size,
        )

    def test_disk_space_check_reports_a_classified_shortfall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(
                ad.shutil,
                "disk_usage",
                return_value=types.SimpleNamespace(free=100),
            ):
                self.assertIsNone(
                    ad.check_download_disk_space(
                        tmpdir, 60, reserve_bytes=20
                    )
                )
                failure = ad.check_download_disk_space(
                    tmpdir, 90, reserve_bytes=20
                )

        self.assertEqual(failure["error_code"], "insufficient-disk-space")
        self.assertIn("short by", failure["error"])
        self.assertIn("free-disk-space-and-retry", failure["next_action"])

    def test_disk_space_check_names_the_short_output_or_staging_volume(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as staging_dir:
            with mock.patch.object(
                ad.shutil,
                "disk_usage",
                side_effect=[
                    types.SimpleNamespace(free=100),
                    types.SimpleNamespace(free=10),
                ],
            ):
                failure = ad.check_download_disk_space(
                    output_dir,
                    60,
                    reserve_bytes=20,
                    staging_path=staging_dir,
                )

        self.assertIn("staging volume", failure["error"])
        self.assertNotIn("output volume", failure["error"])

    def test_queue_preflight_passes_the_install_volume(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as install_dir:
            config = FakeConfig({
                "DownloadPath": output_dir,
                "AudioDownloadPath": output_dir,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            manager.pause_intake()
            summary = {
                "formats": [{
                    "has_video": True,
                    "has_audio": True,
                    "height": 1080,
                    "filesize": 500,
                }],
            }
            received = {}

            def check(_output, _required, **kwargs):
                received.update(kwargs)
                return None

            manager._dependencies["check_download_disk_space"] = check
            manager._dependencies["INSTALL_DIR"] = lambda: Path(install_dir)
            download_id, error = manager.start_download(
                "https://vimeo.com/1", format_summary=summary
            )

        self.assertEqual(received["staging_path"], Path(install_dir))
        self.assertIsNone(error)
        self.assertIn(download_id, manager.downloads)


class FormatProbeTests(unittest.TestCase):
    """A pasted link is probed so the picker stops offering what it lacks."""

    class _Combo:
        def __init__(self):
            self.items = []
            self.index = 0

        def blockSignals(self, _value):
            return None

        def clear(self):
            self.items = []
            self.index = 0

        def addItem(self, label, value):
            self.items.append((label, value))

        def findData(self, value):
            for position, (_label, data) in enumerate(self.items):
                if data == value:
                    return position
            return -1

        def setCurrentIndex(self, index):
            self.index = index

        def currentData(self):
            if 0 <= self.index < len(self.items):
                return self.items[self.index][1]
            return None

        def values(self):
            return [value for _label, value in self.items]

    class _Field(QuickDownloadBatchTests._TextWidget):
        def __init__(self, value=""):
            super().__init__(value)
            self.enabled = True

        def setEnabled(self, value):
            self.enabled = bool(value)

    def _window(self, url_text="https://vimeo.com/1", probed=""):
        window = types.SimpleNamespace(
            quick_download_url=QuickDownloadBatchTests._TextWidget(url_text),
            quick_download_quality=self._Combo(),
            quick_download_status=QuickDownloadBatchTests._TextWidget(),
            quick_download_start=self._Field(),
            quick_download_end=self._Field(),
            # The real label is built carrying this text, so the harness
            # starts where the window does.
            quick_download_clip_hint=QuickDownloadBatchTests._TextWidget(
                "Clip ranges apply to a single link."
            ),
            _sabr_limited=False,
            _force_exit=False,
            _probed_format_url=probed,
            _format_probe_generation=0,
            _format_probe_in_flight=False,
            _format_probe_request_url="",
            _dependencies={
                "QUALITY_LADDER": lambda: ad.QUALITY_LADDER,
                "normalize_url": ad.normalize_url,
                "is_playlist_url": ad.is_playlist_url,
                "probed_video_heights": ad.probed_video_heights,
                "quality_choices_for_heights": ad.quality_choices_for_heights,
                "sabr_only_formats": ad.sabr_only_formats,
                "describe_sabr_voided_options": ad.describe_sabr_voided_options,
                "SABR_LIMITED_NOTICE": lambda: ad.SABR_LIMITED_NOTICE,
            },
        )
        core = gui_module_for_tests().MainWindowCore
        for name in (
            "_value", "_set_quality_choices", "_reset_quality_choices",
            "_schedule_format_probe", "_apply_format_probe",
            "_probe_quick_download_formats", "_set_quick_download_status",
            "_apply_sabr_limits",
        ):
            setattr(window, name, types.MethodType(getattr(core, name), window))
        window._set_quality_choices(ad.QUALITY_LADDER)
        return window

    # ── The pure reduction ───────────────────────────────────────────────

    def test_probe_summary_yields_only_real_video_heights(self):
        summary = {"formats": [
            {"has_video": True, "height": 1080},
            {"has_video": True, "height": 720},
            {"has_video": False, "height": 0},      # audio-only
            {"has_video": True, "height": 0},       # height unknown
            {"has_video": True, "height": 1080},    # duplicate
        ]}
        self.assertEqual(ad.probed_video_heights(summary), [1080, 720])

    def test_ladder_is_cut_to_the_tallest_format_offered(self):
        self.assertEqual(
            ad.quality_choices_for_heights([720, 480, 360]), ["720", "480"]
        )

    def test_a_height_between_rungs_keeps_the_rung_below_it(self):
        # A 900p-only video still offers 720p rather than only "Best".
        self.assertEqual(ad.quality_choices_for_heights([900]), ["720", "480"])

    def test_a_link_below_the_lowest_rung_offers_only_best(self):
        # Measured against the real format table of a 240p upload: every rung
        # would name a resolution the link cannot serve.
        self.assertEqual(ad.quality_choices_for_heights([240, 144]), [])

    def test_an_unusable_probe_leaves_the_whole_ladder(self):
        for heights in ([], None, [0], ["nonsense"]):
            self.assertEqual(
                ad.quality_choices_for_heights(heights), list(ad.QUALITY_LADDER)
            )

    # ── What the picker does with it ─────────────────────────────────────

    def test_probe_narrows_the_picker_and_names_the_ceiling(self):
        window = self._window()
        self.assertIn("2160", window.quick_download_quality.values())
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": {"formats": [{"has_video": True, "height": 720}]},
                "error": "",
            })
        self.assertEqual(
            window.quick_download_quality.values(), ["best", "720", "480"]
        )
        self.assertIn("720p", window.quick_download_status.text())

    def test_a_probe_the_user_typed_past_is_discarded(self):
        window = self._window()
        window._format_probe_generation = 3
        window._apply_format_probe({
            "generation": 2,
            "url": "https://vimeo.com/1",
            "summary": {"formats": [{"has_video": True, "height": 480}]},
            "error": "",
        })
        self.assertEqual(
            window.quick_download_quality.values(),
            ["best"] + list(ad.QUALITY_LADDER),
        )

    def test_a_probe_for_a_url_no_longer_in_the_box_is_discarded(self):
        window = self._window(url_text="https://vimeo.com/2")
        window._apply_format_probe({
            "generation": 0,
            "url": "https://vimeo.com/1",
            "summary": {"formats": [{"has_video": True, "height": 480}]},
            "error": "",
        })
        self.assertEqual(
            window.quick_download_quality.values(),
            ["best"] + list(ad.QUALITY_LADDER),
        )

    def test_a_failed_probe_leaves_the_offer_alone(self):
        # The summary is deliberately populated: an error outranks whatever
        # partial table came back with it, so the guard — not an empty
        # summary — has to be what leaves the ladder intact.
        window = self._window()
        window._apply_format_probe({
            "generation": 0,
            "url": "https://vimeo.com/1",
            "summary": {"formats": [{"has_video": True, "height": 480}]},
            "error": "yt-dlp could not list formats.",
        })
        self.assertEqual(
            window.quick_download_quality.values(),
            ["best"] + list(ad.QUALITY_LADDER),
        )
        self.assertEqual(window.quick_download_status.text(), "")

    def test_a_narrowed_picker_keeps_a_choice_that_survives(self):
        window = self._window()
        window.quick_download_quality.setCurrentIndex(
            window.quick_download_quality.findData("480")
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": {"formats": [{"has_video": True, "height": 1080}]},
                "error": "",
            })
        self.assertEqual(window.quick_download_quality.currentData(), "480")

    def test_a_choice_the_link_cannot_serve_falls_back_to_best(self):
        window = self._window()
        window.quick_download_quality.setCurrentIndex(
            window.quick_download_quality.findData("2160")
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": {"formats": [{"has_video": True, "height": 720}]},
                "error": "",
            })
        self.assertEqual(window.quick_download_quality.currentData(), "best")

    # ── When a probe is worth running at all ─────────────────────────────

    def _spawned(self, window):
        started = []
        with mock.patch.object(
            gui_module_for_tests().threading, "Thread",
            lambda **kwargs: types.SimpleNamespace(
                start=lambda: started.append(kwargs)
            ),
        ), mock.patch.object(gui_module_for_tests(), "repolish"):
            window._probe_quick_download_formats()
        return started

    def test_a_batch_paste_is_not_probed(self):
        window = self._window(url_text="https://vimeo.com/1 https://vimeo.com/2")
        self.assertEqual(self._spawned(window), [])

    def test_a_playlist_is_not_probed(self):
        window = self._window(
            url_text="https://www.youtube.com/playlist?list=PL1"
        )
        self.assertEqual(self._spawned(window), [])

    def test_the_same_url_is_not_probed_twice(self):
        window = self._window(probed="https://vimeo.com/1")
        self.assertEqual(self._spawned(window), [])

    def test_a_single_pasted_link_is_probed(self):
        window = self._window()
        self.assertEqual(len(self._spawned(window)), 1)
        self.assertTrue(window._format_probe_in_flight)
        self.assertIn("Looking up", window.quick_download_status.text())

    def test_a_stale_probe_does_not_block_the_same_url(self):
        window = self._window()
        window._format_probe_generation = 1
        window._format_probe_in_flight = True
        window._format_probe_request_url = "https://vimeo.com/1"
        window.quick_download_url.setText("https://vimeo.com/changed")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 1,
                "url": "https://vimeo.com/1",
                "summary": {},
                "error": "",
            })
        self.assertFalse(window._format_probe_in_flight)
        window.quick_download_url.setText("https://vimeo.com/1")
        self.assertEqual(len(self._spawned(window)), 1)

    def test_editing_past_a_probed_url_restores_the_full_ladder(self):
        window = self._window()
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_format_probe({
                "generation": 0,
                "url": "https://vimeo.com/1",
                "summary": {"formats": [{"has_video": True, "height": 480}]},
                "error": "",
            })
        self.assertEqual(window.quick_download_quality.values(), ["best", "480"])
        window.quick_download_url.setText("https://vimeo.com/2")
        window._format_probe_timer = types.SimpleNamespace(start=lambda: None)
        window._schedule_format_probe()
        self.assertEqual(
            window.quick_download_quality.values(),
            ["best"] + list(ad.QUALITY_LADDER),
        )
        self.assertEqual(window._probed_format_url, "")


class FocusVisibilityTests(unittest.TestCase):
    """Keyboard focus must render. Qt gives QPushButton[class="…"] the same
    specificity as QPushButton:focus, so a class rule silently won the cascade
    and focus drew no pixels at all on most controls."""

    def test_focus_changes_pixels_on_ghost_primary_and_checkbox(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-focus-pin-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

qt_app = QApplication(["focus-pin"])
qt_app.setStyleSheet(app.STYLESHEET)
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
qt_app.processEvents()


def focus_changes_pixels(widget):
    widget.clearFocus()
    qt_app.processEvents()
    first = widget.grab().toImage()
    before = bytes(first.constBits())[:first.sizeInBytes()]
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    second = widget.grab().toImage()
    after = bytes(second.constBits())[:second.sizeInBytes()]
    return before != after


window._nav_click("Download")
qt_app.processEvents()

ghosts = [b for b in window.findChildren(QPushButton)
          if b.property("class") == "ghost" and b.isVisible()]
assert ghosts, "the downloads page should expose a ghost button"
assert focus_changes_pixels(ghosts[0]), "ghost buttons must show keyboard focus"

primaries = [b for b in window.findChildren(QPushButton)
             if b.property("class") == "primary" and b.isVisible()]
assert primaries, "the downloads page should expose a primary button"
assert focus_changes_pixels(primaries[0]), "primary buttons must show keyboard focus"

window._nav_click("Settings")
qt_app.processEvents()
boxes = [c for c in window.findChildren(QCheckBox) if c.isVisible()]
assert boxes, "the settings page should expose checkboxes"
assert focus_changes_pixels(boxes[0]), "checkboxes must show keyboard focus"

assert focus_changes_pixels(window.nav_buttons[0]), "nav focus must keep working"
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

    def test_every_button_variant_restates_its_focus_ring(self):
        # A bare QPushButton:focus rule cannot survive a later equally
        # specific class rule, so each exported variant needs its own.
        sheet = ad.STYLESHEET
        for variant in ("ghost", "primary", "secondary", "danger"):
            self.assertIn(
                f'QPushButton[class="{variant}"]:focus', sheet,
                f"the {variant} button variant needs an explicit focus ring",
            )
        self.assertIn("QCheckBox::indicator:focus", sheet)
        self.assertIn("QCheckBox::indicator:checked:focus", sheet)
        self.assertIn('QLineEdit[state="error"]:focus', sheet)
        self.assertIn('QSpinBox[state="error"]:focus', sheet)

    def test_tab_traversal_skips_hidden_tab_bar_and_leaves_site_profile_editor(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-tab-chain-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import astra_downloader as app
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
    QTextEdit, QWidget,
)

qt_app = QApplication(["tab-chain-pin"])
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
qt_app.processEvents()

tab_bar = window.tabs.tabBar()
assert tab_bar.focusPolicy() == Qt.FocusPolicy.NoFocus
assert window.cfg_site_profiles.tabChangesFocus()

def focus_name(widget):
    return widget.objectName() or widget.accessibleName() or type(widget).__name__

def walk_page(page_name):
    window._nav_click(page_name)
    qt_app.processEvents()
    nav = window.nav_buttons[window._page_names.index(page_name)]
    nav.setFocus(Qt.FocusReason.TabFocusReason)
    qt_app.processEvents()
    seen = []
    for _ in range(256):
        widget = qt_app.focusWidget()
        assert widget is not None, page_name
        assert widget is not tab_bar, (page_name, focus_name(widget))
        if widget is nav and seen:
            break
        seen.append(widget)
        assert window.focusNextPrevChild(True), (page_name, focus_name(widget))
        qt_app.processEvents()
    else:
        raise AssertionError((page_name, [focus_name(widget) for widget in seen]))
    assert qt_app.focusWidget() is nav, page_name
    assert len({id(widget) for widget in seen}) > 1, page_name
    return seen

for page in window._page_names:
    seen = walk_page(page)
    page_root = window.tabs.currentWidget()
    interactive_types = (
        QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QTextEdit,
    )
    focusable_set = {
        widget for widget in page_root.findChildren(QWidget)
        if widget.isVisible() and widget.isEnabled()
        and isinstance(widget, interactive_types)
        and widget.focusPolicy() != Qt.FocusPolicy.NoFocus
    }
    # QSpinBox/QComboBox expose an internal editor that is focusable as a
    # child but enters the tab chain through the composite control.
    def has_focusable_parent(widget):
        parent = widget.parentWidget()
        while parent is not None:
            if parent in focusable_set:
                return True
            parent = parent.parentWidget()
        return False

    focusable = [
        widget for widget in focusable_set
        if not has_focusable_parent(widget)
    ]
    assert focusable, page
    missing = [focus_name(widget) for widget in focusable if widget not in seen]
    assert not missing, (page, missing)

window._nav_click("Settings")
qt_app.processEvents()
window.cfg_site_profiles.setFocus(Qt.FocusReason.TabFocusReason)
before = window.cfg_site_profiles.toPlainText()
assert window.focusNextPrevChild(True)
qt_app.processEvents()
assert qt_app.focusWidget() is not window.cfg_site_profiles
assert qt_app.focusWidget() is not tab_bar
assert window.cfg_site_profiles.toPlainText() == before
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


class LabelPlainTextTests(unittest.TestCase):
    """Labels render remote-supplied strings literally. Qt's default AutoText
    parsed video titles and yt-dlp output as HTML, so a crafted title made the
    companion fetch a remote image."""

    def test_labels_never_interpret_remote_markup(self):
        script = r'''
import os
import sys
import tempfile

temp_dir = tempfile.mkdtemp(prefix="astra-plaintext-")
os.environ["LOCALAPPDATA"] = temp_dir
os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"

from astra_downloader import gui
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication(["plaintext-pin"])
hostile = 'Clip <img src="http://198.51.100.7/beacon.png" width="40" height="40">'

builders = {
    "make_label": gui.make_label(hostile, "cardTitle"),
    "make_status_badge": gui.make_status_badge(hostile),
    "make_state_label": gui.make_state_label(hostile),
}
for name, label in builders.items():
    assert label.textFormat() == Qt.TextFormat.PlainText, name
    assert "<img" in label.text(), name + " should keep the markup literal"

benign = gui.make_label("Cat video", "cardTitle")
benign.adjustSize()
attack = gui.make_label(hostile, "cardTitle")
attack.adjustSize()
assert benign.sizeHint().height() == attack.sizeHint().height(), (
    "an <img> tag must not reserve an image box, which is Qt resolving a remote URL"
)
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

    def test_every_label_constructor_pins_the_text_format(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            config = FakeConfig({
                "ServerToken": "a" * 32,
                "DownloadPath": tmp,
                "AudioDownloadPath": tmp,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            try:
                labels = window.findChildren(QLabel)
                offenders = [
                    (label.objectName(), label.text())
                    for label in labels
                    if label.text()
                    and label.textFormat() != Qt.TextFormat.PlainText
                    and not (
                        label.openExternalLinks()
                        and "<a href=" in label.text()
                    )
                ]
            finally:
                _retire_test_window(window)
        self.assertTrue(labels, "the real window should build labels")
        self.assertEqual(
            offenders, [],
            "every text-carrying label must render markup as plain text",
        )


class SettingsBundleTests(unittest.TestCase):
    """A portable bundle carries settings and subscriptions — never secrets."""

    SUBSCRIPTION = {
        "id": "sub_1",
        "url": "https://www.youtube.com/@astra",
        "title": "Astra",
        "intervalMinutes": 120,
        "enabled": True,
        "lastScanAt": 1754400000.0,
        "lastError": "quota exceeded",
        "lastQueued": 7,
    }

    def _bundle(self, **overrides):
        settings = {"SubLangs": "de,fr", "EmbedSubs": True,
                    "ServerToken": "s" * 32}
        settings.update(overrides)
        return ad.build_settings_bundle(
            ad.sanitize_config(settings),
            [self.SUBSCRIPTION],
            [{"site": "x.com"}, {"site": "vimeo.com"}],
            app_version="2.4.0", now=1754500000.0,
        )

    # -- What must never be in it -----------------------------------------

    def test_the_api_token_is_never_exported(self):
        # It is a working credential for the local API, and a bundle is
        # exactly the kind of file people email to themselves.
        payload = json.dumps(self._bundle())
        self.assertNotIn("s" * 32, payload)
        self.assertNotIn("ServerToken", self._bundle()["settings"])

    def test_no_cookie_value_can_reach_a_bundle(self):
        # SiteLoginStore states that cookie values never leave the jar files.
        # The export names the sites and stops there — there is deliberately
        # no option to include them, because an option to break that rule is
        # still a way to break it.
        bundle = self._bundle()
        self.assertEqual(bundle["siteLoginSites"], ["x.com", "vimeo.com"])
        signature = inspect.signature(ad.build_settings_bundle)
        self.assertNotIn("cookies", signature.parameters)
        self.assertNotIn("include_cookies", signature.parameters)

    def test_the_store_still_has_no_way_to_read_a_cookie_out(self):
        # Guards the rule itself rather than this one caller: if a reader is
        # ever added, this is the test that says the bundle must be revisited.
        readers = [
            name for name in dir(ad.SiteLoginStore)
            if not name.startswith("_") and "cookie" in name.lower()
        ]
        self.assertEqual(readers, ["save_cookies"])

    def test_one_machines_scan_history_is_not_carried(self):
        payload = json.dumps(self._bundle())
        for field in ("lastScanAt", "lastError", "lastQueued", "nextScanAt"):
            with self.subTest(field=field):
                self.assertNotIn(field, payload)

    def test_environment_driven_settings_are_left_out(self):
        # They are read from the environment at startup, so exporting them
        # would promise something the import cannot deliver.
        settings = self._bundle()["settings"]
        for key in ("LegacyHealthTokenEcho", "LegacyHealthTokenOrigins"):
            with self.subTest(key=key):
                self.assertNotIn(key, settings)

    def test_native_extension_allowlists_are_excluded_and_reported(self):
        bundle = self._bundle()
        settings = bundle["settings"]
        self.assertNotIn("NativeChromeExtensionIds", settings)
        self.assertNotIn("NativeFirefoxExtensionIds", settings)
        self.assertIn("NativeChromeExtensionIds", bundle["excludedSettings"])
        self.assertIn("NativeFirefoxExtensionIds", bundle["excludedSettings"])
        imported, error = ad.read_settings_bundle(bundle)
        self.assertIsNone(error)
        changes = ad.describe_bundle_changes(ad.sanitize_config({}), imported)
        self.assertIn("NativeChromeExtensionIds", changes["excludedSettings"])
        self.assertIn("NativeFirefoxExtensionIds", changes["excludedSettings"])

    def test_bundle_exclusions_are_pinned_to_known_local_or_sensitive_settings(self):
        expected = {
            "ServerToken", "LegacyHealthTokenEcho", "LegacyHealthTokenOrigins",
            "NativeChromeExtensionIds", "NativeFirefoxExtensionIds",
            "WindowGeometry", "WindowMaximized", "LastPage", "FirstRunComplete",
            "Proxy", "UseSystemProxy", "GeoVerificationProxy", "SourceAddress",
            "Xff", "SiteProfiles", "ExtraOutputRoots",
        }
        self.assertEqual(set(ad.BUNDLE_EXCLUDED_SETTINGS), expected)
        self.assertTrue(
            set(ad.BUNDLE_EXCLUDED_SETTINGS) <= set(ad.DEFAULT_CONFIG),
            "every excluded bundle key must be a real setting",
        )

    def test_network_credentials_profiles_and_output_allowlist_stay_out_on_export_and_import(self):
        sensitive = {
            "Proxy": "https://user:secret@example.invalid:8443",
            "GeoVerificationProxy": "https://geo:secret@example.invalid:9443",
            "SourceAddress": "192.0.2.10",
            "Xff": "US",
            "SiteProfiles": [{
                "Name": "private archive",
                "Domain": "youtube.com",
                "Proxy": "https://profile:secret@example.invalid:10443",
            }],
            "ExtraOutputRoots": [str(Path(tempfile.gettempdir()) / "wide")],
        }
        bundle = ad.build_settings_bundle(ad.sanitize_config(sensitive))
        for key in sensitive:
            with self.subTest(direction="export", key=key):
                self.assertNotIn(key, bundle["settings"])
                self.assertIn(key, bundle["excludedSettings"])
        self.assertNotIn("secret", json.dumps(bundle))

        planted = dict(bundle)
        planted["settings"] = dict(bundle["settings"], **sensitive)
        imported, error = ad.read_settings_bundle(planted)
        self.assertIsNone(error)
        for key in sensitive:
            with self.subTest(direction="import", key=key):
                self.assertNotIn(key, imported["settings"])

    def test_window_state_is_local_and_invalid_pages_fall_back_to_download(self):
        config = ad.sanitize_config({
            "WindowGeometry": "A" * 9000,
            "WindowMaximized": "yes",
            "LastPage": "Not a page",
        })
        self.assertEqual(len(config["WindowGeometry"]), 8192)
        self.assertTrue(config["WindowMaximized"])
        self.assertEqual(config["LastPage"], "Download")
        bundle = ad.build_settings_bundle(config)
        for key in ("WindowGeometry", "WindowMaximized", "LastPage"):
            with self.subTest(key=key):
                self.assertNotIn(key, bundle["settings"])
                self.assertIn(key, bundle["excludedSettings"])

    # -- The round trip ---------------------------------------------------

    def test_settings_survive_a_write_and_a_read(self):
        bundle, error = ad.read_settings_bundle(
            json.loads(json.dumps(self._bundle())))
        self.assertIsNone(error)
        self.assertEqual(bundle["settings"]["SubLangs"], "de,fr")
        self.assertIs(bundle["settings"]["EmbedSubs"], True)

    def test_subscriptions_survive_with_what_matters(self):
        bundle, _error = ad.read_settings_bundle(self._bundle())
        self.assertEqual(len(bundle["subscriptions"]), 1)
        record = bundle["subscriptions"][0]
        self.assertEqual(record["url"], self.SUBSCRIPTION["url"])
        self.assertEqual(record["intervalMinutes"], 120)
        self.assertIs(record["enabled"], True)

    def test_subscription_delivery_round_trips_in_schema_two(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_root = root / "video"
            audio_root = root / "audio"
            delivery_root = audio_root / "feeds" / "astra"
            settings = ad.sanitize_config({
                "DownloadPath": str(video_root),
                "AudioDownloadPath": str(audio_root),
            })
            subscription = dict(
                self.SUBSCRIPTION,
                outputDir=str(delivery_root),
                format="opus",
                quality="best",
                outputTemplate="%(channel)s/%(title)s.%(ext)s",
                audioOnly=True,
                upgradeIfBetter=True,
            )

            exported = ad.build_settings_bundle(settings, [subscription])
            imported, error = ad.read_settings_bundle(
                json.loads(json.dumps(exported))
            )

        self.assertIsNone(error)
        self.assertEqual(exported["schemaVersion"], 2)
        exported_record = exported["subscriptions"][0]
        self.assertNotIn("outputDir", exported_record)
        self.assertEqual(exported_record["delivery"]["format"], "opus")
        self.assertEqual(imported["subscriptions"][0]["delivery"], {
            "outputDir": str(delivery_root.resolve()),
            "format": "opus",
            "quality": "best",
            "outputTemplate": "%(channel)s/%(title)s.%(ext)s",
            "audioOnly": True,
            "upgradeIfBetter": True,
        })

    def test_schema_one_subscription_migrates_without_delivery_overrides(self):
        imported, error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": 1,
            "settings": {"SubLangs": "en"},
            "subscriptions": [{
                "url": "https://www.youtube.com/@legacy",
                "title": "Legacy",
                "intervalMinutes": 90,
                "enabled": True,
            }],
        })

        self.assertIsNone(error)
        self.assertEqual(imported["subscriptions"][0]["title"], "Legacy")
        self.assertNotIn("delivery", imported["subscriptions"][0])

    def test_subscription_output_outside_incoming_roots_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_root = root / "video"
            audio_root = root / "audio"
            outside = root / "outside" / "feed"
            imported, error = ad.read_settings_bundle({
                "schema": ad.SETTINGS_BUNDLE_SCHEMA,
                "schemaVersion": 2,
                "settings": {
                    "DownloadPath": str(video_root),
                    "AudioDownloadPath": str(audio_root),
                    "ExtraOutputRoots": [str(outside)],
                },
                "subscriptions": [{
                    "url": "https://www.youtube.com/@outside",
                    "title": "Outside",
                    "intervalMinutes": 60,
                    "enabled": True,
                    "delivery": {
                        "outputDir": str(outside),
                        "format": "mp4",
                        "quality": "1080",
                    },
                }],
            })

        self.assertIsNone(error)
        self.assertEqual(
            imported["subscriptions"][0]["delivery"]["outputDir"], ""
        )
        self.assertNotIn("ExtraOutputRoots", imported["settings"])
        self.assertTrue(imported["warnings"])
        self.assertIn("Outside", imported["warnings"][0])

    def test_every_exported_setting_is_one_the_app_knows(self):
        # A key the app no longer has would be silently dropped at import;
        # a key it has but never exports cannot be migrated at all.
        exported = set(self._bundle()["settings"])
        self.assertEqual(
            exported, set(ad.DEFAULT_CONFIG) - set(ad.BUNDLE_EXCLUDED_SETTINGS)
        )

    # -- Validation -------------------------------------------------------

    def test_a_file_that_is_not_ours_is_refused(self):
        for payload in ({}, {"schema": "something-else"}, [], "text", None):
            with self.subTest(payload=payload):
                bundle, error = ad.read_settings_bundle(payload)
                self.assertIsNone(bundle)
                self.assertTrue(error)

    def test_a_newer_format_is_refused_with_the_reason(self):
        bundle, error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": ad.SETTINGS_BUNDLE_VERSION + 1,
            "settings": {},
        })
        self.assertIsNone(bundle)
        self.assertIn("newer version", error)

    def test_a_bundle_with_no_settings_is_refused(self):
        bundle, error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": 1,
        })
        self.assertIsNone(bundle)
        self.assertIn("no settings", error)

    def test_a_hand_edited_value_is_normalised_not_trusted(self):
        # An import overwrites the live config, so a bundle must not be able
        # to introduce a value the app would reject from its own config file.
        bundle, error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": 1,
            "settings": {
                "SubLangs": "en; rm -rf /",
                "MaxConcurrentDownloads": 9999,
                "JavaScriptRuntime": "bun",
                "SubtitleMode": "whatever",
            },
        })
        self.assertIsNone(error)
        self.assertEqual(bundle["settings"]["SubLangs"], "enrm-rf")
        self.assertLessEqual(bundle["settings"]["MaxConcurrentDownloads"], 10)
        self.assertEqual(bundle["settings"]["JavaScriptRuntime"], "auto")
        self.assertEqual(bundle["settings"]["SubtitleMode"], "prefer-manual")

    def test_nonfinite_bundle_values_are_rejected_with_an_error(self):
        for literal in ("1e999", "-1e999", "NaN"):
            with self.subTest(literal=literal):
                payload = self._bundle()
                payload["settings"] = dict(
                    payload["settings"],
                    ConcurrentFragments=json.loads(literal),
                )
                imported, error = ad.read_settings_bundle(payload)

                self.assertIsNone(imported)
                self.assertIn("non-finite", error)

    def test_a_token_planted_in_a_bundle_is_not_imported(self):
        # The exclusion has to hold on the way in too — otherwise a
        # hand-written bundle could overwrite the local API credential.
        bundle, _error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": 1,
            "settings": {"ServerToken": "attacker" * 4, "SubLangs": "en"},
        })
        self.assertNotIn("ServerToken", bundle["settings"])

    def test_a_subscription_with_a_bad_url_is_dropped_not_imported(self):
        bundle, _error = ad.read_settings_bundle({
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": 1,
            "settings": {"SubLangs": "en"},
            "subscriptions": [
                {"url": "not a url"},
                {"url": "file:///etc/passwd"},
                {"url": "https://www.youtube.com/@ok"},
            ],
        })
        self.assertEqual([record["url"] for record in bundle["subscriptions"]],
                         ["https://www.youtube.com/@ok"])

    # -- Reporting --------------------------------------------------------

    def test_the_import_names_the_settings_it_would_change(self):
        current = ad.sanitize_config({"SubLangs": "en", "EmbedSubs": False})
        bundle, _error = ad.read_settings_bundle(self._bundle())
        changes = ad.describe_bundle_changes(current, bundle)
        self.assertEqual(sorted(changes["settings"]), ["EmbedSubs", "SubLangs"])
        self.assertEqual(changes["subscriptions"], 1)

    def test_an_identical_bundle_reports_no_changes(self):
        # "Imported 0 changed settings" is a useful answer; "done" is not.
        current = ad.sanitize_config({"SubLangs": "de,fr", "EmbedSubs": True})
        bundle, _error = ad.read_settings_bundle(self._bundle())
        self.assertEqual(
            ad.describe_bundle_changes(current, bundle)["settings"], [])

    def test_the_sites_needing_a_sign_in_are_reported(self):
        bundle, _error = ad.read_settings_bundle(self._bundle())
        changes = ad.describe_bundle_changes(ad.sanitize_config({}), bundle)
        self.assertEqual(changes["siteLoginSites"], ["x.com", "vimeo.com"])


class SettingsFormReloadTests(unittest.TestCase):
    """The form is redrawn after an import, and knows every setting."""

    def test_every_settings_widget_can_be_refreshed(self):
        # An import replaces the stored settings under a form already on
        # screen. A widget missing from the table keeps its pre-import value,
        # and the next Save writes that value straight back over the import —
        # so a new setting that forgets this table is a silent data loss.
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        gui = gui_module_for_tests()
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            QApplication.processEvents()
            built = {
                name for name in vars(window)
                if name.startswith("cfg_")
            }
        finally:
            _retire_test_window(window)
        # Not a stored setting: it reports the session's bound port.
        built.discard("cfg_port_session_hint")
        # Not a stored setting: it reports what Windows currently advertises.
        built.discard("cfg_system_proxy_hint")
        # A dict of checkboxes, refreshed separately by name.
        built.discard("cfg_sb_categories")
        # ServerToken is read-only and never travels in a bundle, so an
        # import cannot make this field stale.
        built.discard("cfg_token")
        # NativeChromeExtensionIds is BUNDLE_EXCLUDED and the Extension page's
        # Register button saves it immediately, outside the Settings form —
        # an import can never change it, so a reload cannot make it stale.
        built.discard("cfg_native_chrome_ids")
        tabled = {name for name, _key, _kind
                  in gui.MainWindowCore._SETTINGS_FORM_FIELDS}
        self.assertEqual(
            built - tabled, set(),
            "these settings widgets would keep stale values after an import",
        )

    def test_every_tabled_key_is_a_real_setting(self):
        gui = gui_module_for_tests()
        unknown = [
            key for _name, key, _kind
            in gui.MainWindowCore._SETTINGS_FORM_FIELDS
            if key not in ad.DEFAULT_CONFIG
        ]
        self.assertEqual(unknown, [])

    def test_the_kinds_are_ones_the_reloader_handles(self):
        gui = gui_module_for_tests()
        kinds = {kind for _name, _key, kind
                 in gui.MainWindowCore._SETTINGS_FORM_FIELDS}
        self.assertEqual(
            kinds, {"text", "check", "number", "decimal", "combo"}
        )

    def test_every_form_key_is_written_on_save(self):
        # Reload coverage used to hide a save hole: UseSystemProxy was in
        # the form table and survived an import, then Save dropped it.
        from PySide6.QtWidgets import QApplication

        class RecordingConfig(FakeConfig):
            def __init__(self, data=None):
                super().__init__(data)
                self.updates = []

            def update(self, mapping):
                self.updates.append(dict(mapping))
                return super().update(mapping)

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmp:
            config = RecordingConfig({
                "ServerToken": "a" * 32,
                "DownloadPath": tmp,
                "AudioDownloadPath": tmp,
            })
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            try:
                config.updates.clear()
                window._save_settings()
                QApplication.processEvents()
                written = set(config.updates[-1])
            finally:
                _retire_test_window(window)
        expected = {
            key for _name, key, _kind
            in ad.MainWindow._SETTINGS_FORM_FIELDS
        }
        self.assertEqual(expected - written, set())


class SettingsNavigationTests(unittest.TestCase):
    def _window(self, config, subscriptions=None):
        manager = ad.DownloadManager(config, FakeHistory())
        patches = [
            mock.patch.object(ad.MainWindow, "_start_instance_command_listener"),
            mock.patch.object(ad.MainWindow, "_start_readiness_probe"),
            mock.patch.object(ad.QSystemTrayIcon, "show"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        window = ad.MainWindow(
            config,
            manager,
            FakeHistory(),
            subscriptions=subscriptions,
        )
        self.addCleanup(_retire_test_window, window)
        return window

    def test_pacing_guidance_tracks_the_current_hourly_implication(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig({"MaxConcurrentDownloads": 3}))
        window.cfg_sleep_interval.setValue(5)
        window.cfg_sleep_max.setValue(10)
        window.cfg_pacing_jitter.setValue(0)
        window.cfg_sleep_requests.setValue(2)
        QApplication.processEvents()

        guidance = window.pacing_guidance.text()
        self.assertIn("5 to 10 seconds", guidance)
        self.assertIn("480 per hour each", guidance)
        self.assertIn("1,440 total with concurrency set to 3", guidance)
        self.assertIn("2 seconds between requests", guidance)
        self.assertIn("300 videos/hour signed out", guidance)
        self.assertIn("2,000/hour signed in", guidance)
        self.assertTrue(window.pacing_guidance.openExternalLinks())

        window.cfg_maxconcurrent.setValue(1)
        QApplication.processEvents()
        self.assertIn(
            "480 total with concurrency set to 1",
            window.pacing_guidance.text(),
        )

    def test_filter_narrows_rows_without_losing_their_group(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        window._filter_settings("proxy")
        QApplication.processEvents()
        groups = {title: group for group, _content, title in window._settings_group_specs}
        self.assertFalse(window.cfg_proxy.isHidden())
        self.assertTrue(window.cfg_metadata.isHidden())
        self.assertFalse(groups["Performance"].isHidden())
        self.assertTrue(groups["Post-processing"].isHidden())

        window._filter_settings("language")
        self.assertFalse(window.cfg_language.isHidden())
        self.assertFalse(groups["Appearance and language"].isHidden())
        self.assertTrue(groups["Window and tray"].isHidden())

        # Every setting must be findable by its own words, whichever heading it
        # ended up under.
        for term, widget, heading in (
            ("theme", window.cfg_theme, "Appearance and language"),
            ("clipboard", window.cfg_clipboard, "Clipboard"),
            ("yt-dlp up to date", window.cfg_autoupdate, "Maintenance"),
            ("tray", window.cfg_closetotray, "Window and tray"),
        ):
            with self.subTest(term=term):
                window._filter_settings(term)
                QApplication.processEvents()
                self.assertFalse(widget.isHidden(), f"{term} must survive its own search")
                self.assertFalse(groups[heading].isHidden())

    def test_language_picker_hides_partial_catalogues(self):
        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        self.assertEqual(
            [window.cfg_language.itemData(index)
             for index in range(window.cfg_language.count())],
            ["system", "de", "en"],
        )

    def test_settings_search_indexes_safe_site_profile_fields(self):
        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        window.cfg_site_profiles.setPlainText(json.dumps([{
            "Name": "YouTube archive",
            "Domain": "youtube.com",
            "Quality": "1080",
            "Proxy": "https://user:secret@example.invalid:8443",
        }]))
        indexed = window._settings_search_text(window.cfg_site_profiles)
        self.assertIn("youtube archive", indexed)
        self.assertIn("youtube.com", indexed)
        self.assertIn("1080", indexed)
        self.assertNotIn("secret", indexed)
        window._filter_settings("youtube.com")
        self.assertFalse(window.cfg_site_profiles.isHidden())

    def test_browse_buttons_have_distinct_accessible_names(self):
        from PySide6.QtWidgets import QPushButton

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        self.assertEqual(
            window.first_run_browse.accessibleName(),
            "Browse: First-run download folder",
        )
        self.assertEqual(
            next(
                button for button in window.findChildren(QPushButton)
                if button.text() == "Browse"
                and button.accessibleName() == "Browse: Video download folder"
            ).accessibleName(),
            "Browse: Video download folder",
        )
        self.assertEqual(
            next(
                button for button in window.findChildren(QPushButton)
                if button.text() == "Browse"
                and button.accessibleName() == "Browse: Audio download folder"
            ).accessibleName(),
            "Browse: Audio download folder",
        )

    def test_empty_states_offer_recovery_actions_and_log_has_a_real_empty_state(self):
        from PySide6.QtWidgets import QPushButton

        _get_qapp_or_skip(self)
        subscriptions = types.SimpleNamespace(snapshot=lambda: {
            "subscriptions": [],
            "archive": {},
            "scanning": [],
        }, stop=lambda: None)
        window = self._window(FakeConfig(), subscriptions=subscriptions)
        window.dl_manager.site_logins = types.SimpleNamespace(entries=lambda: [])
        window._refresh_site_logins(force=True)
        window._refresh_history()
        window._clear_log()

        def empty_actions(container_layout):
            empty = container_layout.itemAt(0).widget()
            return [button.text() for button in empty.findChildren(QPushButton)]

        self.assertIn(
            "Add subscription", empty_actions(window.subscription_container)
        )
        self.assertIn(
            "Add a site sign-in", empty_actions(window.site_login_container)
        )
        self.assertIn(
            "View download queue", empty_actions(window.history_container)
        )
        self.assertFalse(window.log_empty_state.isHidden())
        self.assertTrue(window.log_text.isHidden())

        window._append_log("empty-state fixture")
        self.assertTrue(window.log_empty_state.isHidden())
        self.assertFalse(window.log_text.isHidden())
        window._clear_log()
        self.assertFalse(window.log_empty_state.isHidden())
        self.assertTrue(window.log_text.isHidden())

    def test_live_wait_setting_is_labeled_as_a_retry_interval(self):
        from PySide6.QtWidgets import QApplication, QLabel

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        self.assertEqual(
            window.cfg_wait_for_video.accessibleName(),
            "Live-video retry interval",
        )
        self.assertIn(
            "Live-video retry interval",
            [label.text() for label in window.findChildren(QLabel)],
        )
        self.assertTrue(any(
            "bounded wait window" in label.text()
            for label in window.findChildren(QLabel)
        ))

    def test_sponsorblock_attribution_is_visible_and_linked(self):
        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        attribution = window.sponsorblock_attribution
        self.assertIn("(Using SponsorBlock)", attribution.text())
        self.assertIn("https://sponsor.ajay.app/", attribution.text())
        self.assertTrue(attribution.openExternalLinks())
        self.assertIn("CC BY-NC-SA 4.0", " ".join(
            label.text() for label in window.findChildren(type(attribution))
        ))

    def test_settings_filter_preserves_controls_hidden_by_their_own_state(self):
        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        self.assertTrue(window.btn_undo_settings_import.isHidden())
        window._filter_settings("proxy")
        window._filter_settings("")
        self.assertTrue(window.btn_undo_settings_import.isHidden())

    def test_every_registered_settings_control_marks_the_form_dirty(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())

        for attribute, _key, kind in window._SETTINGS_FORM_FIELDS:
            with self.subTest(attribute=attribute):
                widget = getattr(window, attribute)
                window._show_settings_status("")
                if kind == "text":
                    if hasattr(widget, "toPlainText"):
                        widget.setPlainText(widget.toPlainText() + " ")
                    else:
                        widget.setText(widget.text() + " ")
                elif kind == "check":
                    widget.setChecked(not widget.isChecked())
                elif kind == "number":
                    value = widget.value()
                    widget.setValue(
                        value + 1 if value < widget.maximum() else value - 1
                    )
                elif kind == "decimal":
                    value = widget.value()
                    widget.setValue(
                        value + widget.singleStep()
                        if value < widget.maximum()
                        else value - widget.singleStep()
                    )
                elif kind == "combo":
                    self.assertGreater(widget.count(), 1)
                    widget.setCurrentIndex((widget.currentIndex() + 1) % widget.count())
                QApplication.processEvents()
                self.assertEqual(
                    window.settings_status.text(),
                    "Unsaved changes",
                )

        for name, widget in window.cfg_sb_categories.items():
            with self.subTest(attribute=f"cfg_sb_categories[{name}]"):
                window._show_settings_status("")
                widget.setChecked(not widget.isChecked())
                QApplication.processEvents()
                self.assertEqual(window.settings_status.text(), "Unsaved changes")

    def test_restore_defaults_reports_changes_and_refreshes_the_form(self):
        class MutableConfig(FakeConfig):
            def __init__(self, data=None):
                super().__init__(data)
                self.undo = {}

            def update(self, mapping):
                self.data.update(mapping)
                return True

            def save_undo(self, key, value):
                self.undo[key] = json.loads(json.dumps(value))
                return True

            def clear_undo(self, key):
                self.undo.pop(key, None)
                return True

        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        config = MutableConfig({
            "Proxy": "https://proxy.example.test:8443",
            "Language": "de",
            "PacingJitterPercent": 35,
            "SponsorBlockCategories": "sponsor",
        })
        window = self._window(config)

        self.assertTrue(window._restore_default_settings())
        QApplication.processEvents()
        self.assertEqual(config.get("Proxy"), "")
        self.assertEqual(config.get("Language"), "system")
        self.assertEqual(config.get("PacingJitterPercent"), 0)
        self.assertEqual(
            config.get("SponsorBlockCategories"),
            ad.DEFAULT_CONFIG["SponsorBlockCategories"],
        )
        self.assertEqual(window.cfg_proxy.text(), "")
        self.assertEqual(window.cfg_language.currentData(), "system")
        self.assertIn("Restored defaults", window.settings_status.text())
        self.assertFalse(window.btn_undo_restore_defaults.isHidden())
        self.assertTrue(window._undo_restore_defaults())
        QApplication.processEvents()
        self.assertEqual(config.get("Proxy"), "https://proxy.example.test:8443")
        self.assertEqual(config.get("Language"), "de")
        self.assertTrue(window.btn_undo_restore_defaults.isHidden())
        self.assertNotIn("restoreDefaults", config.undo)

    def test_settings_import_status_names_the_changed_fields(self):
        class MutableConfig(FakeConfig):
            def __init__(self, data=None):
                super().__init__(data)
                self.undo = {}

            def update(self, mapping):
                self.data.update(mapping)
                return True

            def save_undo(self, key, value):
                self.undo[key] = json.loads(json.dumps(value))
                return True

            def clear_undo(self, key):
                self.undo.pop(key, None)
                return True

        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        config = MutableConfig(ad.sanitize_config({
            "SubLangs": "en",
            "EmbedSubs": False,
        }))
        window = self._window(config)
        payload = {
            "schema": ad.SETTINGS_BUNDLE_SCHEMA,
            "schemaVersion": ad.SETTINGS_BUNDLE_VERSION,
            "settings": {"SubLangs": "de", "EmbedSubs": True},
            "subscriptions": [],
            "siteLoginSites": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(
                ad.QFileDialog,
                "getOpenFileName",
                return_value=(str(path), "JSON files (*.json)"),
            ):
                self.assertTrue(window._import_settings_bundle())
        QApplication.processEvents()
        status = window.settings_status.text()
        self.assertIn(window.cfg_sublangs.accessibleName(), status)
        self.assertIn(window.cfg_subs.accessibleName(), status)
        self.assertEqual(config.get("SubLangs"), "de")
        self.assertTrue(config.get("EmbedSubs"))
        self.assertIn("settingsImport", config.undo)
        self.assertTrue(window._undo_settings_import() is None)
        self.assertEqual(config.get("SubLangs"), "en")
        self.assertFalse(config.get("EmbedSubs"))
        self.assertNotIn("settingsImport", config.undo)

    def test_settings_import_passes_delivery_and_reports_a_confined_path(self):
        class MutableConfig(FakeConfig):
            def __init__(self, data=None):
                super().__init__(data)
                self.undo = {}

            def update(self, mapping):
                self.data.update(mapping)
                return True

            def save_undo(self, key, value):
                self.undo[key] = json.loads(json.dumps(value))
                return True

            def clear_undo(self, key):
                self.undo.pop(key, None)
                return True

        class ImportedSubscriptions:
            def __init__(self):
                self.calls = []

            def snapshot(self):
                return {"subscriptions": [], "archive": {}, "scanning": []}

            def add_subscription(self, url, **kwargs):
                self.calls.append({"url": url, **kwargs})
                return {"id": f"imported-{len(self.calls)}"}, None

            def remove_subscription(self, _sub_id):
                return True, None

            def stop(self):
                return None

        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video_root = root / "video"
            audio_root = root / "audio"
            valid_output = audio_root / "feed"
            outside_output = root / "outside"
            config = MutableConfig({
                "DownloadPath": str(video_root),
                "AudioDownloadPath": str(audio_root),
                "ExtraOutputRoots": [str(root / "local-only")],
            })
            subscriptions = ImportedSubscriptions()
            window = self._window(config, subscriptions=subscriptions)
            payload = {
                "schema": ad.SETTINGS_BUNDLE_SCHEMA,
                "schemaVersion": 2,
                "settings": {
                    "DownloadPath": str(video_root),
                    "AudioDownloadPath": str(audio_root),
                    "ExtraOutputRoots": [str(outside_output)],
                },
                "subscriptions": [
                    {
                        "url": "https://www.youtube.com/@inside",
                        "title": "Inside",
                        "intervalMinutes": 60,
                        "enabled": True,
                        "delivery": {
                            "outputDir": str(valid_output),
                            "format": "opus",
                            "quality": "best",
                            "audioOnly": True,
                        },
                    },
                    {
                        "url": "https://www.youtube.com/@outside",
                        "title": "Outside",
                        "intervalMinutes": 60,
                        "enabled": True,
                        "delivery": {
                            "outputDir": str(outside_output),
                            "format": "mp4",
                        },
                    },
                ],
            }
            path = root / "settings.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(
                ad.QFileDialog,
                "getOpenFileName",
                return_value=(str(path), "JSON files (*.json)"),
            ):
                self.assertTrue(window._import_settings_bundle())
            QApplication.processEvents()

            self.assertEqual(
                subscriptions.calls[0]["delivery"]["outputDir"],
                str(valid_output.resolve()),
            )
            self.assertEqual(
                subscriptions.calls[1]["delivery"]["outputDir"], ""
            )
            self.assertEqual(
                config.get("ExtraOutputRoots"), [str(root / "local-only")]
            )
            self.assertIn("Outside", window.settings_status.text())
            self.assertEqual(
                window.settings_status.property("tone"), "warning"
            )

    def test_sign_in_browser_list_marks_chromium_entries_before_selection(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())
        QApplication.processEvents()
        chrome_index = window.site_login_browser.findData("chrome")
        firefox_index = window.site_login_browser.findData("firefox")
        self.assertIn("likely unreadable", window.site_login_browser.itemText(chrome_index))
        self.assertNotIn("likely unreadable", window.site_login_browser.itemText(firefox_index))

    def test_sign_in_page_can_store_credentials_without_rendering_them(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        window = self._window(FakeConfig())
        with tempfile.TemporaryDirectory() as tmp:
            window.dl_manager.site_logins = ad.SiteLoginStore(tmp)
            window.site_login_url.setText("vimeo.com")
            window.site_login_username.setText("member@example.com")
            window.site_login_password.setText("GUI-PASSWORD-SECRET")
            window.btn_site_login_credentials.click()
            QApplication.processEvents()
            self.assertEqual(
                window.dl_manager.site_logins.credentials_for_url(
                    "https://vimeo.com/video"
                )["password"],
                "GUI-PASSWORD-SECRET",
            )
            self.assertNotIn("GUI-PASSWORD-SECRET", window.site_login_status.text())


class CompletionNotificationTests(unittest.TestCase):
    """A completion toast can be clicked, and it leads to the file."""

    def _window(self, notified=""):
        gui = gui_module_for_tests()
        window = types.SimpleNamespace(
            _last_notified_file=notified, shown=[], revealed=[])
        window._show_from_tray = lambda: window.shown.append("shown")
        window._show_download_location = window.revealed.append
        window._notification_clicked = types.MethodType(
            gui.MainWindowCore._notification_clicked, window)
        return window

    def test_clicking_a_toast_reveals_the_file_it_announced(self):
        window = self._window(r"C:\Videos\clip.mp4")
        self.assertTrue(window._notification_clicked())
        self.assertEqual(window.revealed, [r"C:\Videos\clip.mp4"])
        self.assertEqual(window.shown, ["shown"])

    def test_a_toast_with_no_file_still_raises_the_window(self):
        window = self._window("")
        self.assertFalse(window._notification_clicked())
        self.assertEqual(window.revealed, [])
        self.assertEqual(window.shown, ["shown"])

    def test_the_signal_is_connected(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            shown = []
            revealed = []
            window._show_from_tray = lambda: shown.append(True)
            window._show_download_location = revealed.append
            window._last_notified_file = r"C:\Videos\notified.mp4"
            window.tray.messageClicked.emit()
            QApplication.processEvents()
            self.assertEqual(shown, [True])
            self.assertEqual(revealed, [r"C:\Videos\notified.mp4"])
        finally:
            _retire_test_window(window)


class DownloadCardMenuTests(unittest.TestCase):
    """A terminal card offers what is useful for that outcome."""

    def _window(self):
        gui = gui_module_for_tests()
        window = types.SimpleNamespace(
            logs=[], statuses=[], navigated=[],
            quick_download_url=QuickDownloadBatchTests._TextWidget(),
        )
        window._append_log = window.logs.append
        window._nav_click = window.navigated.append
        window._set_quick_download_status = (
            lambda message, tone="neutral": window.statuses.append((message, tone))
        )
        for name in ("_redownload", "_copy_download_url", "_play_download"):
            setattr(window, name,
                    types.MethodType(getattr(gui.MainWindowCore, name), window))
        return window

    def test_download_again_stages_the_link_instead_of_queueing_it(self):
        # Re-running the original request silently would ignore whatever the
        # user has changed in the format and quality pickers since.
        window = self._window()
        self.assertTrue(window._redownload(
            types.SimpleNamespace(url="https://vimeo.com/1")))
        self.assertEqual(window.quick_download_url.text(), "https://vimeo.com/1")
        self.assertEqual(window.navigated, ["Download"])
        self.assertIn("Download", window.statuses[-1][0])

    def test_download_again_on_a_record_with_no_link_does_nothing(self):
        window = self._window()
        self.assertFalse(window._redownload(types.SimpleNamespace(url="")))
        self.assertEqual(window.quick_download_url.text(), "")

    def test_playing_a_missing_file_reports_instead_of_failing_silently(self):
        window = self._window()
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(
                window._play_download(str(Path(tmpdir) / "gone.mp4")))
        self.assertTrue(any("no longer" in line for line in window.logs))


class QuickJsRuntimeTests(unittest.TestCase):
    """The runtime the app can fetch for itself when Deno is not there."""

    # -- The pin ----------------------------------------------------------

    def test_the_pinned_version_and_the_floor_agree(self):
        # The floor is the version this project ships and has verified. If a
        # bump moves one and not the other, the app would either refuse its
        # own binary or accept an unverified one.
        self.assertEqual(ad.QUICKJS_VERSION, ad.QUICKJS_MIN_VERSION)

    def test_the_download_url_names_the_pinned_version(self):
        # The digest below is only meaningful for the release it was taken
        # from; a URL that drifted to "latest" would verify nothing.
        self.assertIn(f"/v{ad.QUICKJS_VERSION}/", ad.QUICKJS_EXE_URL)
        self.assertNotIn("/latest/", ad.QUICKJS_EXE_URL)

    def test_the_digest_is_a_real_sha256(self):
        self.assertRegex(ad.QUICKJS_SHA256, r"^[0-9a-f]{64}$")

    def test_the_licence_policy_records_the_same_release(self):
        # The inventory gate reports what is distributed; a policy entry that
        # named a different version would attest to the wrong artifact.
        policy = json.loads(
            (Path(ad.__file__).parent / "license-policy.json")
            .read_text(encoding="utf-8")
        )
        entry = next(h for h in policy["runtimeHelpers"] if h["key"] == "quickjs")
        self.assertEqual(entry["version"], ad.QUICKJS_VERSION)
        self.assertEqual(entry["licenseExpression"], "MIT")
        self.assertIn(ad.QUICKJS_VERSION, entry["distributionUrl"])

    # -- The vocabulary ---------------------------------------------------

    def test_config_accepts_exactly_the_runtimes_the_prober_knows(self):
        self.assertEqual(
            ad.JAVASCRIPT_RUNTIME_CHOICES - {"auto"},
            set(ad.JS_RUNTIMES),
        )

    def test_a_stored_runtime_outside_the_list_falls_back_to_auto(self):
        for value in ("bun", "; calc", "deno2"):
            with self.subTest(value=value):
                self.assertEqual(
                    ad.sanitize_config({"JavaScriptRuntime": value})["JavaScriptRuntime"],
                    "auto",
                )
        self.assertEqual(
            ad.sanitize_config({"JavaScriptRuntime": "quickjs"})["JavaScriptRuntime"],
            "quickjs",
        )

    # -- Selection --------------------------------------------------------

    def test_quickjs_compiles_into_the_runtime_argv(self):
        self.assertEqual(
            ad.build_javascript_runtime_args({
                "supported": True, "ejsReady": True,
                "runtime": "quickjs", "path": r"C:\\qjs.exe",
            }),
            ["--no-js-runtimes", "--js-runtimes", r"quickjs:C:\\qjs.exe"],
        )

    def test_a_runtime_the_app_cannot_probe_is_never_sent(self):
        # yt-dlp also accepts bun. Nothing here provisions or probes it, so
        # offering it would be a claim without evidence.
        self.assertEqual(
            ad.build_javascript_runtime_args({
                "supported": True, "ejsReady": True,
                "runtime": "bun", "path": r"C:\\bun.exe",
            }),
            [],
        )

    def test_the_version_floor_is_enforced_for_quickjs_too(self):
        self.assertTrue(
            ad._javascript_runtime_supported("quickjs", ad.QUICKJS_MIN_VERSION))
        self.assertFalse(ad._javascript_runtime_supported("quickjs", "0.1.0"))

    def test_the_execution_probe_uses_the_flag_quickjs_understands(self):
        # Verified against the shipped build: `qjs -e` evaluates and prints.
        # deno's `eval` subcommand and node's --input-type are both rejected.
        seen = []

        def runner(args, timeout=None):
            seen.append(args)
            return "MARKER"

        self.assertTrue(ad._owned_probe_javascript_execution(
            "quickjs", "qjs.exe", runner=runner, marker="MARKER"))
        self.assertEqual(seen[0][:2], ["qjs.exe", "-e"])
        # And the wrapper the app actually calls reaches the same branch.
        with mock.patch.object(ad, "_run_captured",
                               lambda args, timeout=None: (
                                   seen.append(args),
                                   ad.JS_RUNTIME_CAPABILITY_MARKER)[1]):
            self.assertTrue(ad._probe_javascript_execution("quickjs", "qjs.exe"))
        self.assertEqual(seen[-1][:2], ["qjs.exe", "-e"])

    def test_quickjs_is_offered_after_deno_and_node(self):
        # yt-dlp's own priority is deno > node > quickjs. An install that
        # already has Deno should keep using it.
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = Path(tmpdir) / "qjs.exe"
            fake.write_bytes(b"\0" * (2 * 1024 * 1024))
            with mock.patch.object(ad, "QUICKJS_PATH", fake), \
                 mock.patch.object(ad.shutil, "which", lambda name: (
                     f"C:\\{name}.exe" if name in ("deno", "node") else None)):
                order = [
                    runtime for runtime, _path, _source
                    in ad._javascript_runtime_candidates("auto")
                ]
        self.assertEqual(order[-1], "quickjs")
        self.assertLess(order.index("deno"), order.index("quickjs"))
        self.assertLess(order.index("node"), order.index("quickjs"))

    def test_only_the_provisioned_copy_is_offered(self):
        # Nothing on PATH is pinned to a digest or verified end-to-end, so a
        # system qjs is not a candidate.
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "absent" / "qjs.exe"
            with mock.patch.object(ad, "QUICKJS_PATH", missing), \
                 mock.patch.object(ad.shutil, "which",
                                   lambda name: f"C:\\{name}.exe"):
                runtimes = [
                    runtime for runtime, _path, _source
                    in ad._javascript_runtime_candidates("auto")
                ]
        self.assertNotIn("quickjs", runtimes)

    def test_a_truncated_binary_is_not_offered(self):
        # The antivirus-stub case: present, so every exists() check passes,
        # but far too small to be the real runtime.
        with tempfile.TemporaryDirectory() as tmpdir:
            stub = Path(tmpdir) / "qjs.exe"
            stub.write_bytes(b"")
            with mock.patch.object(ad, "QUICKJS_PATH", stub), \
                 mock.patch.object(ad.shutil, "which", lambda _name: None):
                runtimes = [
                    runtime for runtime, _path, _source
                    in ad._javascript_runtime_candidates("auto")
                ]
        self.assertEqual(runtimes, [])


class QuickJsProvisioningTests(unittest.TestCase):
    """Provisioning verifies before it keeps, and does not re-fetch."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.path = Path(self.tmpdir) / "quickjs" / "qjs.exe"
        self.enterContext(mock.patch.object(ad, "QUICKJS_PATH", self.path))
        self.enterContext(mock.patch.object(ad, "QUICKJS_DIR", self.path.parent))
        self.enterContext(mock.patch.object(ad, "write_persistent_log",
                                            lambda *_a, **_k: None))

    def _plant(self, payload=b"\0" * (2 * 1024 * 1024)):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(payload)

    def test_a_mismatched_digest_is_deleted_rather_than_kept(self):
        # The whole point of pinning: a substituted binary must not survive
        # the download and become the runtime every YouTube job executes.
        def fake_download(_url, destination, **_kwargs):
            Path(destination).parent.mkdir(parents=True, exist_ok=True)
            Path(destination).write_bytes(b"\0" * (2 * 1024 * 1024))

        with mock.patch.object(ad, "download_file_atomic", fake_download):
            result = ad.provision_quickjs()
        self.assertIsNone(result)
        self.assertFalse(self.path.exists(),
                         "an unverified runtime must not be left on disk")

    def test_a_failed_download_leaves_nothing_behind(self):
        def fake_download(*_args, **_kwargs):
            raise RuntimeError("network unreachable")

        with mock.patch.object(ad, "download_file_atomic", fake_download):
            self.assertIsNone(ad.provision_quickjs())
        self.assertFalse(self.path.exists())

    def test_a_good_binary_is_not_fetched_again(self):
        # This regressed once: the version probe called a name that does not
        # exist in this module, the bare except swallowed the NameError, and
        # every call re-downloaded 2 MB.
        self._plant()
        calls = []
        with mock.patch.object(ad, "download_file_atomic",
                               lambda *a, **k: calls.append(a)), \
             mock.patch.object(ad, "_probe_quickjs_binary_version",
                               lambda _path: ad.QUICKJS_VERSION):
            result = ad.provision_quickjs()
        self.assertEqual(result, str(self.path))
        self.assertEqual(calls, [], "an already-verified runtime was re-fetched")

    def test_the_version_probe_reports_a_real_version(self):
        # Guards the swallowed-NameError shape directly: the helper must
        # return the parsed version, not None, for output the binary emits.
        with mock.patch.object(ad, "_run_captured", lambda *_a, **_k: "0.16.1\n"):
            self.assertEqual(
                ad._probe_quickjs_binary_version(Path("qjs.exe")), "0.16.1")

    def test_a_binary_below_the_floor_is_replaced(self):
        self._plant()
        calls = []

        def fake_download(_url, destination, **_kwargs):
            calls.append(destination)
            Path(destination).write_bytes(b"\0" * (2 * 1024 * 1024))

        with mock.patch.object(ad, "download_file_atomic", fake_download), \
             mock.patch.object(ad, "_probe_quickjs_binary_version",
                               lambda _path: "0.1.0"), \
             mock.patch.object(ad, "verify_file_sha256", lambda *_a: True):
            result = ad.provision_quickjs()
        self.assertEqual(result, str(self.path))
        self.assertEqual(len(calls), 1)

    def test_a_failed_refresh_keeps_the_previous_runtime(self):
        self._plant(b"previous runtime" + (b"\0" * (2 * 1024 * 1024)))

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"bad replacement")

        with mock.patch.object(ad, "download_file_atomic", fake_download), \
             mock.patch.object(ad, "_probe_quickjs_binary_version",
                               lambda _path: "0.1.0"), \
             mock.patch.object(ad, "verify_file_sha256",
                               side_effect=RuntimeError("bad digest")):
            result = ad.provision_quickjs()

        self.assertIsNone(result)
        self.assertTrue(self.path.exists())
        self.assertTrue(self.path.read_bytes().startswith(b"previous runtime"))
        self.assertEqual(list(self.path.parent.glob(".qjs.exe.*.verified")), [])


class QuickJsSetupFallbackTests(unittest.TestCase):
    """Setup falls back to QuickJS when Deno cannot be had."""

    def _worker(self, *, deno_ok, runtime_ready=False, configured="auto"):
        gui = gui_module_for_tests()
        worker = gui.SetupWorkerCore.__new__(gui.SetupWorkerCore)
        worker.configured_runtime = configured
        messages = []
        calls = []
        worker.log = types.SimpleNamespace(emit=messages.append)
        worker.progress = types.SimpleNamespace(emit=lambda _value: None)
        worker._dependencies = {
            "get_ytdlp_version": lambda: "2026.08.04",
            "ytdlp_needs_external_runtime": lambda _v: True,
            "probe_javascript_runtime": lambda **_k: {
                "ejsReady": runtime_ready, "canProvisionDeno": True,
                "runtime": "deno", "path": "C:/deno.exe",
            },
            "provision_deno": lambda _config=None: (calls.append("deno"),
                                                    "C:/deno.exe" if deno_ok else None)[1],
            "provision_quickjs": lambda: (calls.append("quickjs"),
                                          "C:/qjs.exe")[1],
        }
        return worker, messages, calls

    def test_a_failed_deno_download_falls_back_to_quickjs(self):
        # The 40 MB archive is the part of setup most likely to fail. Before
        # this, that left the install with no runtime at all.
        worker, messages, calls = self._worker(deno_ok=False)
        gui_module_for_tests().SetupWorkerCore._provision_javascript_runtime(worker)
        self.assertEqual(calls, ["deno", "quickjs"])
        self.assertTrue(any("QuickJS" in message for message in messages))

    def test_a_working_deno_is_not_second_guessed(self):
        worker, _messages, calls = self._worker(deno_ok=True)
        gui_module_for_tests().SetupWorkerCore._provision_javascript_runtime(worker)
        self.assertEqual(calls, ["deno"])

    def test_an_existing_runtime_downloads_nothing(self):
        worker, _messages, calls = self._worker(deno_ok=True, runtime_ready=True)
        gui_module_for_tests().SetupWorkerCore._provision_javascript_runtime(worker)
        self.assertEqual(calls, [])

    def test_choosing_node_does_not_silently_install_quickjs(self):
        # An explicit choice is a choice; only Auto and QuickJS may fetch it.
        worker, _messages, calls = self._worker(deno_ok=False, configured="node")
        gui_module_for_tests().SetupWorkerCore._provision_javascript_runtime(worker)
        self.assertNotIn("quickjs", calls)

    def test_the_user_is_told_when_no_runtime_could_be_had(self):
        worker, messages, _calls = self._worker(deno_ok=False, configured="node")
        gui_module_for_tests().SetupWorkerCore._provision_javascript_runtime(worker)
        self.assertTrue(
            any("No JavaScript runtime" in message for message in messages),
            messages,
        )


class SubtitleLanguagePickerTests(unittest.TestCase):
    """The checkboxes and the free-text field describe the same languages."""

    def _window(self):
        gui = gui_module_for_tests()
        window = types.SimpleNamespace(
            cfg_sublangs=QuickDownloadBatchTests._TextWidget("en"),
            _sublang_boxes=[],
        )
        for _label, code in gui.SUBTITLE_LANGUAGE_CHOICES:
            box = types.SimpleNamespace(_sublang_code=code, checked=False)
            box.setChecked = lambda value, b=box: setattr(b, "checked", value)
            box.isChecked = lambda b=box: b.checked
            box.blockSignals = lambda _value: None
            window._sublang_boxes.append(box)
        for name in ("_split_sublangs", "_sync_sublang_checkboxes",
                     "_sublang_box_toggled"):
            member = getattr(gui.MainWindowCore, name)
            setattr(window, name, member if isinstance(member, staticmethod)
                    else types.MethodType(member, window))
        window._split_sublangs = gui.MainWindowCore._split_sublangs
        return window

    def _checked(self, window):
        return [box._sublang_code for box in window._sublang_boxes
                if box.isChecked()]

    def test_the_stored_codes_tick_their_boxes(self):
        window = self._window()
        window._sync_sublang_checkboxes("en,zh-Hans")
        self.assertEqual(self._checked(window), ["en", "zh-Hans"])

    def test_a_code_with_no_box_still_shows_the_ones_that_have_boxes(self):
        # The field accepts anything yt-dlp knows; only some have a checkbox.
        window = self._window()
        window._sync_sublang_checkboxes("en,cy,ga")
        self.assertEqual(self._checked(window), ["en"])

    def test_ticking_a_box_adds_only_that_language(self):
        window = self._window()
        window.cfg_sublangs.setText("en,cy")
        box = next(b for b in window._sublang_boxes if b._sublang_code == "fr")
        window.sender = lambda: box
        window._sublang_box_toggled(True)
        self.assertEqual(window.cfg_sublangs.text(), "en,cy,fr")

    def test_clearing_a_box_keeps_the_codes_that_have_no_box(self):
        # The regression this guards: rebuilding the field from the checkboxes
        # alone would silently delete every language the picker cannot show.
        window = self._window()
        window.cfg_sublangs.setText("en,cy,fr")
        box = next(b for b in window._sublang_boxes if b._sublang_code == "fr")
        window.sender = lambda: box
        window._sublang_box_toggled(False)
        self.assertEqual(window.cfg_sublangs.text(), "en,cy")

    def test_clearing_the_last_language_falls_back_rather_than_emptying(self):
        window = self._window()
        window.cfg_sublangs.setText("fr")
        box = next(b for b in window._sublang_boxes if b._sublang_code == "fr")
        window.sender = lambda: box
        window._sublang_box_toggled(False)
        self.assertEqual(window.cfg_sublangs.text(), "en")

    def test_a_duplicate_code_is_not_added_twice(self):
        window = self._window()
        window.cfg_sublangs.setText("en,fr")
        box = next(b for b in window._sublang_boxes if b._sublang_code == "fr")
        window.sender = lambda: box
        window._sublang_box_toggled(True)
        self.assertEqual(window.cfg_sublangs.text(), "en,fr")

    def test_every_offered_code_survives_the_normaliser(self):
        # A checkbox that writes a code the save path then rewrites would tick
        # itself off again the moment the user saved.
        for _label, code in gui_module_for_tests().SUBTITLE_LANGUAGE_CHOICES:
            with self.subTest(code=code):
                self.assertEqual(ad.normalize_sublangs(code), code)


class StylesheetContrastTests(unittest.TestCase):
    """Control boundaries meet the WCAG non-text contrast floor."""

    PAGE_BACKGROUND = "#0a0d12"

    INPUT_BOUNDARIES = (
        ("line edit", "QLineEdit", None),
        ("spin box", "QSpinBox", None),
        ("combo box", "QComboBox", None),
        ("disabled line edit", "QLineEdit:disabled", "QLineEdit"),
        ("disabled spin box", "QSpinBox:disabled", "QSpinBox"),
        ("disabled combo box", "QComboBox:disabled", "QComboBox"),
        ("hero paste box", 'QLineEdit[class="heroUrl"]', "QLineEdit"),
        ("text edit", "QTextEdit", None),
        ("menu", "QMenu", None),
    )
    BUTTON_BOUNDARIES = (
        ("button", "QPushButton", None),
        ("hover button", "QPushButton:hover", None),
        ("disabled button", "QPushButton:disabled", None),
        ("secondary button", 'QPushButton[class="secondary"]', None),
        ("danger button", 'QPushButton[class="danger"]', None),
        ("ghost button", 'QPushButton[class="ghost"]', None),
        ("hover ghost button", 'QPushButton[class="ghost"]:hover', None),
        ("checkbox indicator", "QCheckBox::indicator", None),
    )

    @staticmethod
    def _relative_luminance(hex_colour):
        raw = hex_colour.lstrip("#")
        channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]
        linear = [
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def _contrast(cls, foreground, background):
        first = cls._relative_luminance(foreground)
        second = cls._relative_luminance(background)
        lighter, darker = max(first, second), min(first, second)
        return (lighter + 0.05) / (darker + 0.05)

    @staticmethod
    def _stylesheet_rules(sheet=None):
        # Keep this parser deliberately small: the companion sheet only uses
        # flat selector blocks, and parsing the declarations makes the test
        # follow the palette instead of baking in a guessed background.
        import re
        sheet = re.sub(r"/\*.*?\*/", "", ad.STYLESHEET if sheet is None else sheet, flags=re.S)
        rules = {}
        for selector_text, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet):
            for selector in selector_text.split(","):
                rules[selector.strip()] = body
        return rules

    @staticmethod
    def _declared_colour(body, properties):
        import re
        for property_name in properties:
            match = re.search(
                rf"(?:^|;)\s*{re.escape(property_name)}\s*:\s*([^;]+)",
                body,
            )
            if not match:
                continue
            value = match.group(1).strip()
            if value == "transparent":
                return value
            colour = re.search(r"#[0-9a-fA-F]{6}", value)
            if colour:
                return colour.group(0).lower()
        return None

    @classmethod
    def _effective_background(cls, rules, selector, fallback=None):
        page = cls._declared_colour(
            rules["QWidget"], ("background-color", "background")
        )
        for candidate in (selector, fallback):
            if not candidate or candidate not in rules:
                continue
            colour = cls._declared_colour(
                rules[candidate], ("background-color", "background")
            )
            if colour == "transparent":
                return page
            if colour:
                return colour
        return page

    def _assert_declared_boundaries(self, specifications, sheet=None, theme="dark"):
        rules = self._stylesheet_rules(sheet)
        for label, selector, fallback in specifications:
            with self.subTest(control=label, theme=theme):
                self.assertIn(selector, rules, f"missing {selector} rule")
                border = self._declared_colour(
                    rules[selector], ("border-color", "border")
                )
                self.assertRegex(
                    border or "", r"^#[0-9a-f]{6}$",
                    f"{selector} needs an explicit coloured boundary",
                )
                background = self._effective_background(
                    rules, selector, fallback
                )
                self.assertRegex(
                    background or "", r"^#[0-9a-f]{6}$",
                    f"{selector} needs a declared or inherited fill",
                )
                ratio = self._contrast(border, background)
                self.assertGreaterEqual(
                    ratio, 3.0,
                    f"[{theme}] {selector} border {border} is {ratio:.2f}:1 "
                    f"against {background}",
                )

    # Every keyboard focus ring, and the colour the eye actually compares it
    # against. A filled control is compared against its own fill, not the
    # page behind it; that distinction is what the checked checkbox got wrong,
    # drawing a light ring at 1.5:1 on top of its own accent face.
    FOCUS_RINGS = (
        ("QLineEdit:focus", "border-color", "#0a0d12"),
        ("QSpinBox:focus", "border-color", "#0a0d12"),
        ("QComboBox:focus", "border-color", "#0a0d12"),
        ("QTextEdit:focus", "border-color", "#0a0d12"),
        ('QLineEdit[class="heroUrl"]:focus', "border-color", "#0a0d12"),
        ("QPushButton:focus", "border-color", "#0a0d12"),
        ('QPushButton[class="ghost"]:focus', "border-color", "#171d25"),
        ('QPushButton[class="secondary"]:focus', "border-color", "#0a0d12"),
        ('QPushButton[class="danger"]:focus', "border-color", "#0a0d12"),
        ('QPushButton[class="primary"]:focus', "border-color", "#ff6552"),
        ("QCheckBox::indicator:focus", "border-color", "#0a0d12"),
        ("QCheckBox::indicator:checked:focus", "border-color", "#ff7867"),
        ('QPushButton[class="nav"]:focus', "border-left-color", "#0a0d12"),
        ('QPushButton[class="nav"][active="true"]:focus',
         "border-left-color", "#0a0d12"),
    )

    def test_every_focus_ring_separates_from_what_is_behind_it(self):
        # SC 2.4.13 wants 3:1 between the focus indicator and the colours
        # adjacent to it. Nothing measured these, and the sheet's own comments
        # carried the numbers by hand.
        for theme, sheet in (("dark", ad.STYLESHEET), ("light", ad.LIGHT_STYLESHEET)):
            rules = self._stylesheet_rules(sheet)
            replacements = ad._LIGHT_THEME_COLOR_REPLACEMENTS
            for selector, prop, dark_background in self.FOCUS_RINGS:
                with self.subTest(theme=theme, selector=selector):
                    self.assertIn(
                        selector, rules,
                        f"[{theme}] {selector} draws no focus indicator",
                    )
                    ring = self._declared_colour(rules[selector], (prop,))
                    self.assertRegex(
                        ring or "", r"^#[0-9a-f]{6}$",
                        f"[{theme}] {selector} declares no {prop}",
                    )
                    background = (
                        dark_background if theme == "dark"
                        else replacements.get(dark_background, dark_background)
                    )
                    measured = self._contrast(ring, background)
                    self.assertGreaterEqual(
                        measured, 3.0,
                        f"[{theme}] {selector} ring {ring} is {measured:.2f}:1 "
                        f"against {background}",
                    )

    def test_a_state_rule_cannot_swallow_hover_or_focus(self):
        # Qt's CSS2 cascade gives `[class][state]` and `[class]:hover` the
        # same weight, so whichever is written last wins. The state rules
        # were written after the hover rule, which meant a cancelled or
        # failed card stopped answering the mouse the moment it had a state.
        # The sheet already documents this trap twice, for heroUrl and the
        # nav buttons.
        lines = ad.STYLESHEET.splitlines()

        def line_of(fragment):
            matches = [
                index for index, line in enumerate(lines) if fragment in line
            ]
            self.assertEqual(len(matches), 1, f"{fragment!r} x{len(matches)}")
            return matches[0]

        states = max(
            line_of('QFrame[class="download"][state="failed"]'),
            line_of('QFrame[class="download"][state="complete"]'),
            line_of('QFrame[class="download"][state="cancelled"]'),
        )
        for transient in ('QFrame[class="download"]:hover',
                          'QFrame[class="download"]:focus'):
            self.assertGreater(
                line_of(transient), states,
                f"{transient} is declared before the state rules, so a card "
                f"with a state renders it and this rule never applies",
            )

    def test_a_focused_rejected_field_keeps_its_error_ground(self):
        # QTextEdit:focus is declared far below the error rule and carries the
        # same weight, so it won the background. _save_settings focuses the
        # first invalid field, which is exactly when the error has to show.
        rules = self._stylesheet_rules()
        error = self._declared_colour(
            rules['QTextEdit[state="error"]'], ("background", "background-color")
        )
        focused = self._declared_colour(
            rules['QTextEdit[state="error"]:focus'],
            ("background", "background-color"),
        )
        self.assertEqual(
            focused, error,
            "focusing a rejected multi-line field drops its error background",
        )

    def test_the_light_theme_boundaries_clear_the_same_floor(self):
        # LIGHT_STYLESHEET is generated by substituting the dark palette, so a
        # token added later can fail 3:1 in light while dark stays green. Same
        # controls, same floor, measured against the light sheet's own
        # backgrounds rather than an assumed one.
        light_rules = self._stylesheet_rules(ad.LIGHT_STYLESHEET)
        light_page = self._declared_colour(
            light_rules["QWidget"], ("background-color", "background")
        )
        self.assertRegex(light_page or "", r"^#[0-9a-f]{6}$")
        self.assertNotEqual(
            light_page, self.PAGE_BACKGROUND,
            "the light sheet must not still be the dark page colour",
        )

        self._assert_declared_boundaries(
            self.INPUT_BOUNDARIES + self.BUTTON_BOUNDARIES,
            sheet=ad.LIGHT_STYLESHEET,
            theme="light",
        )

    def test_every_authored_colour_has_a_light_counterpart(self):
        # The direction the old gate did not check. It asserted that the
        # colours IN the map were substituted, which says nothing about a
        # colour added to the sheet and never added to the map — that one is
        # simply carried into the light theme unchanged, and every existing
        # assertion still passes.
        authored = {
            match.group(0).lower()
            for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b", ad.STYLESHEET)
        }
        mapped = {colour.lower() for colour in ad._LIGHT_THEME_COLOR_REPLACEMENTS}
        self.assertEqual(
            sorted(authored - mapped), [],
            "colours in the dark sheet with no light counterpart; they reach "
            "the light theme unchanged",
        )
        self.assertEqual(
            sorted(mapped - authored), [],
            "light-map rows for colours the dark sheet no longer contains",
        )

    def test_the_light_substitution_is_one_pass(self):
        # It was a str.replace per colour, so an earlier row's output could
        # match a later row's key: #394350 -> #718092 -> #526272 left the
        # light scrollbar handle wearing its own hover colour, and hover
        # feedback gone. A colour may legitimately appear on both sides of
        # the map; what must not happen is the second rewrite.
        replacements = ad._LIGHT_THEME_COLOR_REPLACEMENTS
        self.assertTrue(replacements)
        chained = sorted(
            {value.lower() for value in replacements.values()}
            & {key.lower() for key in replacements}
        )
        expected = ad._LIGHT_THEME_COLOR_PATTERN.sub(
            lambda match: replacements[match.group(0)], ad.STYLESHEET
        )
        self.assertEqual(ad.LIGHT_STYLESHEET, expected)
        for aliased in chained:
            dark_source = sorted(
                key for key, value in replacements.items()
                if value.lower() == aliased
            )
            self.assertTrue(
                dark_source,
                f"{aliased} is a map key and a map value with no source row",
            )

    def test_the_light_scrollbar_still_answers_a_hover(self):
        # The concrete casualty of the chained substitution, pinned so the
        # single-pass derivation cannot quietly go back.
        for theme, sheet in (("dark", ad.STYLESHEET), ("light", ad.LIGHT_STYLESHEET)):
            rules = self._stylesheet_rules(sheet)
            resting = self._declared_colour(
                rules["QScrollBar::handle:vertical"], ("background", "background-color")
            )
            hovered = self._declared_colour(
                rules["QScrollBar::handle:vertical:hover"],
                ("background", "background-color"),
            )
            self.assertNotEqual(
                resting, hovered,
                f"[{theme}] the scrollbar handle does not change on hover",
            )

    def test_a_row_hover_is_visible_in_both_themes(self):
        # #11161d was the card surface as well as the row hover, and the light
        # map sent both to #ffffff, so hovering a history row in the light
        # theme changed nothing at all.
        for theme, sheet in (("dark", ad.STYLESHEET), ("light", ad.LIGHT_STYLESHEET)):
            rules = self._stylesheet_rules(sheet)
            surface = ("background", "background-color")
            page = self._declared_colour(rules["QWidget"], surface)
            card = self._declared_colour(rules['QFrame[class="card"]'], surface)
            for selector, resting in (
                ('QFrame[class="historyRow"]:hover', page),
                ('QFrame[class="download"]:hover', page),
                ('QFrame[class="playlistRow"]:hover', card),
            ):
                hovered = self._declared_colour(rules[selector], surface)
                ratio = self._contrast(hovered, resting)
                self.assertGreaterEqual(
                    ratio, 1.10,
                    f"[{theme}] {selector} is {ratio:.3f}:1 against the "
                    f"surface underneath it, which reads as no hover at all",
                )

    def test_every_download_card_state_is_styled(self):
        # _update_download_card writes the property for four statuses. Two of
        # them matched no rule, so a cancelled or skipped card paid a repolish
        # and rendered exactly like a pending one.
        rules = self._stylesheet_rules()
        for state in ("failed", "complete", "cancelled", "skipped"):
            selector = next(
                (key for key in rules if f'[state="{state}"]' in key
                 and 'class="download"' in key),
                None,
            )
            self.assertIsNotNone(
                selector, f"no download-card rule for state {state!r}"
            )

    def test_a_focusable_download_card_shows_its_focus(self):
        # _restore_card_focus falls back to giving the card itself StrongFocus
        # when a rebuild leaves it with no button to hand focus to, so focus
        # stays on the row the user was reading. Every recent card now carries
        # a More button, which makes that fallback hard to reach in practice;
        # the rule is here so the case it exists for is not invisible.
        rules = self._stylesheet_rules()
        self.assertIn('QFrame[class="download"]:focus', rules)

    def test_the_multi_line_settings_field_can_show_an_error(self):
        # cfg_site_profiles is a QTextEdit and goes through the same
        # mark_error path as every QLineEdit, which styled two widget types.
        for sheet_name, sheet in (("dark", ad.STYLESHEET), ("light", ad.LIGHT_STYLESHEET)):
            rules = self._stylesheet_rules(sheet)
            selector = next(
                (key for key in rules
                 if 'QTextEdit[state="error"]' in key and ':focus' not in key),
                None,
            )
            self.assertIsNotNone(
                selector,
                f"[{sheet_name}] a rejected QTextEdit is marked but not drawn",
            )

    def test_the_page_background_is_what_this_measures_against(self):
        # The ratios below are meaningless if this drifts, and an earlier
        # measurement of this palette was wrong precisely because it assumed
        # a background the sheet does not contain.
        rules = self._stylesheet_rules()
        self.assertEqual(
            self._declared_colour(
                rules["QWidget"], ("background-color", "background")
            ),
            self.PAGE_BACKGROUND,
        )

    def test_input_boundaries_clear_the_non_text_contrast_floor(self):
        # WCAG 2.2 SC 1.4.11 wants 3:1 for a control's visual boundary. The
        # fill cannot carry it here — #11161d against the page is 1.07:1 —
        # so the border is the only thing marking where a field is.
        self._assert_declared_boundaries(self.INPUT_BOUNDARIES)

    def test_button_and_indicator_boundaries_clear_the_non_text_floor(self):
        self._assert_declared_boundaries(self.BUTTON_BOUNDARIES)

    def test_the_input_fill_alone_cannot_identify_the_control(self):
        # Documents why the border has to carry it, so a future change does
        # not "fix" this by darkening the border and trusting the fill.
        rules = self._stylesheet_rules()
        fill = self._declared_colour(
            rules["QLineEdit"], ("background-color", "background")
        )
        page = self._declared_colour(
            rules["QWidget"], ("background-color", "background")
        )
        ratio = self._contrast(fill, page)
        self.assertLess(ratio, 3.0)

    def test_a_ghost_button_is_not_a_bare_label(self):
        # With a transparent background AND a transparent border, a ghost
        # button rendered pixel-identically to the static labels beside it —
        # "Save to" was indistinguishable from "Clip from".
        import re
        rule = re.search(
            r'QPushButton\[class="ghost"\] \{([^}]*)\}', ad.STYLESHEET
        )
        self.assertIsNotNone(rule)
        body = rule.group(1)
        self.assertNotIn("background: transparent", body)
        self.assertRegex(body, r"background-color: #[0-9a-fA-F]{6}")
        self.assertRegex(body, r"border-color: #[0-9a-fA-F]{6}")


class DownloadPageFeedbackTests(unittest.TestCase):
    """Download-page controls report where the user is standing."""

    def _window(self):
        window = types.SimpleNamespace(
            quick_download_status=QuickDownloadBatchTests._TextWidget(),
            logs=[],
        )
        window._append_log = window.logs.append
        window._nav_click = lambda _page: None
        window._set_quick_download_status = types.MethodType(
            gui_module_for_tests().MainWindowCore._set_quick_download_status, window
        )
        for name in ("_retry_download", "_toggle_queue_intake",
                     "_resume_download_queue", "_move_pending_download",
                     "_resume_one_download"):
            setattr(window, name, types.MethodType(
                getattr(gui_module_for_tests().MainWindowCore, name), window))
        return window

    def test_a_refused_retry_is_reported_on_the_page(self):
        window = self._window()
        window.dl_manager = types.SimpleNamespace(
            retry=lambda _id: (False, "Queue is full."))
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._retry_download(types.SimpleNamespace(
                id="dl_1", title="Unknown", url="https://example.com/v"))
        self.assertEqual(window.quick_download_status.text(), "Queue is full.")
        self.assertEqual(window.quick_download_status.properties["tone"], "danger")

    def test_a_refused_reorder_is_reported_on_the_page(self):
        window = self._window()
        window.dl_manager = types.SimpleNamespace(
            move_pending_by=lambda _id, _offset: (False, "Only pending downloads can be reordered."))
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._move_pending_download("dl_1", -1)
        self.assertIn("reordered", window.quick_download_status.text())

    def test_a_failed_pause_is_reported_on_the_page(self):
        window = self._window()
        window.dl_manager = types.SimpleNamespace(
            capacity=lambda: {"intakePaused": False},
            pause_intake=lambda: False)
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._toggle_queue_intake()
        self.assertIn("Could not pause", window.quick_download_status.text())

    def test_resuming_one_card_does_not_resume_the_queue(self):
        # The card button used to call resume_intake(), which clears the
        # global pause and starts every paused download at once.
        window = self._window()
        calls = []
        window.dl_manager = types.SimpleNamespace(
            resume_download=lambda dl_id: (calls.append(dl_id), (True, None))[1],
            resume_intake=lambda: calls.append("INTAKE") or True,
        )
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._resume_one_download("dl_2")
        self.assertEqual(calls, ["dl_2"])
        self.assertNotIn("INTAKE", calls)


class WindowTeardownTests(unittest.TestCase):
    """Nothing the window scheduled outlives it."""

    def test_force_close_persists_state_cancels_work_and_accepts_event(self):
        class Event:
            def __init__(self):
                self.accepted = False
                self.ignored = False

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        class Timer:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        class Tray:
            def __init__(self):
                self.hidden = False
                self.messages = []

            def isVisible(self):
                return True

            def showMessage(self, *args):
                self.messages.append(args)

            def hide(self):
                self.hidden = True

        logs = []
        cancelled = []
        timers = [Timer() for _ in range(6)]
        window = types.SimpleNamespace(
            _force_exit=True,
            config=FakeConfig({"CloseToTray": False}),
            server_running=False,
            _server_starting=False,
            tray=Tray(),
            dl_manager=types.SimpleNamespace(
                cancel_all=lambda: cancelled.append(True),
            ),
            _persist_window_state=lambda: logs.append("persisted"),
            _stop_instance_command_listener=lambda: logs.append("listener stopped"),
            _subscription_manager=lambda: None,
            _downloads_that_will_be_cancelled=lambda: 3,
            _append_log=logs.append,
            _value=lambda name: "Astra Downloader" if name == "APP_NAME" else None,
            tools_status_timer=timers[0],
            update_timer=timers[1],
            cleanup_timer=timers[2],
            _format_probe_timer=timers[3],
            _ui_refresh_timer=timers[4],
            _history_filter_timer=timers[5],
        )
        event = Event()

        ad.MainWindow.closeEvent(window, event)

        self.assertTrue(event.accepted)
        self.assertFalse(event.ignored)
        self.assertEqual(cancelled, [True])
        self.assertEqual(logs[:2], ["persisted", "listener stopped"])
        self.assertTrue(any("cancel 3 active downloads" in text for text in logs))
        self.assertEqual(len(window.tray.messages), 1)
        self.assertTrue(window.tray.hidden)
        self.assertTrue(all(timer.stopped for timer in timers))

    def test_close_to_tray_hides_without_cancelling_work(self):
        class Event:
            def __init__(self):
                self.accepted = False
                self.ignored = False

            def accept(self):
                self.accepted = True

            def ignore(self):
                self.ignored = True

        class Tray:
            def __init__(self):
                self.messages = []

            def isVisible(self):
                return True

            def showMessage(self, *args):
                self.messages.append(args)

        hidden = []
        cancelled = []
        window = types.SimpleNamespace(
            _force_exit=False,
            config=FakeConfig({"CloseToTray": True}),
            tray=Tray(),
            _tray_hint_shown=False,
            _persist_window_state=lambda: None,
            hide=lambda: hidden.append(True),
            _value=lambda name: "Astra Downloader" if name == "APP_NAME" else None,
            dl_manager=types.SimpleNamespace(
                cancel_all=lambda: cancelled.append(True),
            ),
        )
        event = Event()

        ad.MainWindow.closeEvent(window, event)

        self.assertTrue(event.ignored)
        self.assertFalse(event.accepted)
        self.assertEqual(hidden, [True])
        self.assertEqual(cancelled, [])
        self.assertEqual(len(window.tray.messages), 1)
        self.assertTrue(window._tray_hint_shown)

    def test_close_reports_the_work_cancelled_before_calling_cancel_all(self):
        events = []

        class Event:
            def __init__(self):
                self.accepted = False

            def accept(self):
                self.accepted = True

            def ignore(self):
                raise AssertionError("forced close must not be ignored")

        class Timer:
            def stop(self):
                events.append("timer stopped")

        class Tray:
            def isVisible(self):
                return True

            def showMessage(self, _title, message, *_args):
                events.append(("message", message))

            def hide(self):
                events.append("tray hidden")

        window = types.SimpleNamespace(
            _force_exit=True,
            config=FakeConfig({"CloseToTray": False}),
            server_running=False,
            _server_starting=False,
            tray=Tray(),
            _persist_window_state=lambda: events.append("persisted"),
            _stop_instance_command_listener=lambda: events.append("listener stopped"),
            _subscription_manager=lambda: None,
            _downloads_that_will_be_cancelled=lambda: 3,
            _append_log=lambda message: events.append(("log", message)),
            _value=lambda name: "Astra Downloader" if name == "APP_NAME" else None,
            dl_manager=types.SimpleNamespace(
                cancel_all=lambda: events.append("cancelled"),
            ),
            tools_status_timer=Timer(),
            update_timer=Timer(),
            cleanup_timer=Timer(),
            _format_probe_timer=Timer(),
            _ui_refresh_timer=Timer(),
            _history_filter_timer=Timer(),
        )

        event = Event()
        ad.MainWindow.closeEvent(window, event)

        messages = [
            event[1] for event in events
            if isinstance(event, tuple) and event[0] == "message"
        ]
        self.assertEqual(len(messages), 1)
        self.assertIn("cancel 3 active downloads", messages[0])
        self.assertLess(events.index(("message", messages[0])), events.index("cancelled"))
        self.assertTrue(event.accepted)

    def test_window_state_is_saved_on_navigation_and_close(self):
        gui = gui_module_for_tests()

        class Tabs:
            def setCurrentIndex(self, index):
                self.index = index

            def currentIndex(self):
                return 1

        class Button:
            def setChecked(self, _value):
                pass

            def setProperty(self, *_args):
                pass

        class Config:
            def __init__(self):
                self.data = {
                    "LastPage": "History",
                    "WindowMaximized": False,
                }
                self.saved = None

            def get(self, key, default=None):
                return self.data.get(key, default)

            def update(self, values):
                self.saved = dict(values)
                self.data.update(values)
                return True

        config = Config()
        persisted = []
        window = types.SimpleNamespace(
            _page_names=["Download", "History"],
            _restoring_window_state=False,
            _first_run=False,
            config=config,
            tabs=Tabs(),
            nav_buttons=[Button(), Button()],
            _animate_page=lambda: None,
            _refresh_history=lambda: None,
            _refresh_subscriptions=lambda **_kwargs: None,
            _persist_window_state=lambda: persisted.append(True),
            saveGeometry=lambda: types.SimpleNamespace(
                toBase64=lambda: b"geometry"
            ),
            isMaximized=lambda: True,
            _append_log=lambda _message: None,
        )

        with mock.patch.object(gui, "repolish"):
            gui.MainWindowCore._nav_click(window, "History")
        self.assertEqual(persisted, [True])

        restored = types.SimpleNamespace(
            _page_names=["Download", "History"],
            _first_run=False,
            _restoring_window_state=False,
            config=config,
            restoreGeometry=lambda _geometry: persisted.append("geometry"),
            showMaximized=lambda: persisted.append("maximized"),
            _nav_click=lambda page: persisted.append(page),
        )
        config.data["WindowMaximized"] = True
        gui.MainWindowCore._restore_window_state(restored)
        self.assertIn("History", persisted)
        self.assertIn("maximized", persisted)

        self.assertTrue(gui.MainWindowCore._persist_window_state(window))
        self.assertEqual(config.saved["LastPage"], "History")
        self.assertTrue(config.saved["WindowMaximized"])

    def test_a_probe_already_in_flight_is_abandoned_on_exit(self):
        # closeEvent can be called while the debounce is mid-flight, so the
        # timer stop alone is not enough.
        window = types.SimpleNamespace(
            _force_exit=True,
            quick_download_url=QuickDownloadBatchTests._TextWidget(
                "https://vimeo.com/1"),
        )
        started = []
        window._probe_quick_download_formats = types.MethodType(
            gui_module_for_tests().MainWindowCore._probe_quick_download_formats,
            window,
        )
        with mock.patch.object(
            gui_module_for_tests().threading, "Thread",
            lambda **kwargs: types.SimpleNamespace(
                start=lambda: started.append(kwargs)),
        ):
            window._probe_quick_download_formats()
        self.assertEqual(started, [])


class ButtonLabelCaseTests(unittest.TestCase):
    """Labels are sentence case, matching the rest of the product."""

    def test_no_tool_button_label_is_title_case(self):
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            QApplication.processEvents()
            labels = {
                button.text()
                for button in window.findChildren(QPushButton)
                if button.property("class") in {"primary", "secondary", "ghost", "danger"}
            }
        finally:
            _retire_test_window(window)
        self.assertTrue(labels, "expected to find tool button labels")
        offenders = []
        for label in labels:
            words = [w for w in label.split() if w and w[0].isalpha()]
            # Sentence case: only the first word may start with a capital.
            capitals = [w for w in words[1:] if w[0].isupper()]
            # Proper nouns and file names keep their own casing.
            capitals = [w for w in capitals
                        if w not in {
                            "Server", "Deck", "Astra", "SponsorBlock", "FFmpeg",
                        }]
            if capitals:
                offenders.append((label, capitals))
        self.assertEqual(offenders, [], f"Title Case labels: {offenders}")


class DownloaderFirstLayoutTests(unittest.TestCase):
    """The product is a video downloader; the extension server is a feature
    of it. That ordering is a design decision, so exercise the constructed
    window rather than pinning the implementation text that creates it.
    """

    def _window(self, config=None, *, first_run=False):
        _get_qapp_or_skip(self)
        config = config or FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        for patcher in (
            mock.patch.object(ad.MainWindow, "_start_instance_command_listener"),
            mock.patch.object(ad.MainWindow, "_start_readiness_probe"),
            mock.patch.object(ad.QSystemTrayIcon, "show"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        window = ad.MainWindow(
            config,
            manager,
            FakeHistory(),
            first_run=first_run,
        )
        self.addCleanup(_retire_test_window, window)
        return window

    def test_an_active_download_is_visible_without_scrolling(self):
        """The design invariant is downloader first, so the download you just
        started must not be below the fold at the documented window size.

        The older pin only checked that the queue scroller *began* inside the
        window, which a one-pixel sliver satisfies. This asserts the first real
        row is wholly inside it and that the page does not scroll to get there.
        """
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication

        window = self._window()
        window.resize(1120, 760)
        window.show()
        window._nav_click("Download")
        QApplication.processEvents()

        download = ad.Download(
            "active",
            "https://www.youtube.com/watch?v=abcdefghijk",
            fmt="mp4",
            quality="1080",
            output_dir=".",
            title="Downloading documentary",
            created_at=1_750_000_000,
            queue_order=1,
            clock=lambda: 1_750_001_000,
        )
        download.status = "downloading"
        download.progress = 63.4
        window.dl_manager.downloads[download.id] = download
        window.dl_manager._running_ids.add(download.id)
        window._update_ui()
        QApplication.processEvents()

        # QLabel derives from QFrame, so an isinstance check picks up the
        # section heading — twelve pixels tall and always inside the viewport,
        # which is exactly the widget that cannot fail this assertion. Match
        # the card by the object name gui.py gives it.
        rows = [
            window.downloads_list_layout.itemAt(index).widget()
            for index in range(window.downloads_list_layout.count())
        ]
        cards = [
            row for row in rows
            if row is not None and row.isVisible()
            and row.objectName().startswith("download_")
        ]
        self.assertTrue(cards, "an active download must render a queue row")

        card = cards[0]
        self.assertGreater(
            card.height(), 40,
            "the row must be a real card, not a collapsed placeholder",
        )
        # Clipping is against the queue's own viewport, not the window: a row
        # can sit inside the window and still be cut off by a short scroller.
        viewport = window.downloads_scroll.viewport()
        top = card.mapTo(viewport, QPoint(0, 0)).y()
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(
            top + card.height(), viewport.height(),
            "the first queue row must be wholly inside the queue viewport",
        )
        window_top = card.mapTo(window, QPoint(0, 0)).y()
        self.assertLessEqual(
            window_top + card.height(), window.height(),
            "the first queue row must be wholly inside a 1120x760 window",
        )

        page_bar = window.download_page_scroll.verticalScrollBar()
        self.assertEqual(
            page_bar.maximum(), 0,
            "reaching the queue must not require scrolling the Download page",
        )
        queue_bar = window.downloads_scroll.verticalScrollBar()
        self.assertEqual(
            (queue_bar.value(), queue_bar.maximum()), (0, 0),
            "the queue must show its first row without any scrolling at all",
        )

        # The contrast is what gives the assertion above its teeth: with the
        # optional controls and the passing checks expanded, the same queue is
        # pushed out of the viewport. Progressive disclosure is what keeps the
        # downloader first, not a taller window.
        window.btn_quick_options.setChecked(True)
        window.btn_preflight_toggle.setChecked(True)
        QApplication.processEvents()
        expanded_top = card.mapTo(window, QPoint(0, 0)).y()
        self.assertGreater(
            expanded_top, window_top,
            "expanding the optional controls must move the queue down",
        )
        self.assertGreater(
            expanded_top, window.height(),
            "the expanded page is the state that pushes the queue off screen",
        )
        self.assertGreater(
            window.download_page_scroll.verticalScrollBar().maximum(), 0,
            "the expanded page is the state that needs scrolling",
        )

    def test_download_is_the_first_page_and_the_landing_page(self):
        window = self._window()
        self.assertEqual(
            window._page_names[0],
            "Download",
            "Download must be the first rail entry - the paste box is the "
            "product, not a page you navigate to",
        )
        self.assertEqual(window.tabs.currentIndex(), 0)

        window.config.set("LastPage", "History")
        window._restore_window_state()
        self.assertEqual(
            window._page_names[window.tabs.currentIndex()],
            "History",
            "a saved page should replace the default landing page",
        )

        first_run_window = self._window(
            FakeConfig({"LastPage": "History"}), first_run=True
        )
        self.assertEqual(
            first_run_window._page_names[first_run_window.tabs.currentIndex()],
            "Download",
            "first-run onboarding must always open beside the paste box",
        )

    def test_first_run_confirms_destination_before_queueing_and_reaches_pairing(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)

        class MutableConfig(FakeConfig):
            def update(self, mapping):
                self.data.update(mapping)
                return True

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MutableConfig({
                "DownloadPath": str(Path(tmpdir) / "Videos"),
                "FirstRunComplete": False,
                "LastPage": "Settings",
            })
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(
                    config, manager, FakeHistory(), first_run=True
                )
            try:
                self.assertEqual(window.tabs.currentIndex(), 0)
                self.assertFalse(window.first_run_panel.isHidden())
                self.assertFalse(window.first_run_confirm.isHidden())

                window.quick_download_url.setText("https://example.com/video")
                window._start_quick_download()
                self.assertIn(
                    "Confirm your download folder",
                    window.quick_download_status.text(),
                )
                window.quick_download_url.setText(
                    "https://www.youtube.com/playlist?list=PLtest"
                )
                window._open_playlist_staging()
                self.assertIn(
                    "Confirm your download folder",
                    window.quick_download_status.text(),
                )
                self.assertFalse(config.get("FirstRunComplete"))

                confirmed = Path(tmpdir) / "Confirmed videos"
                window.first_run_destination.setText(str(confirmed))
                self.assertTrue(window._confirm_first_run_destination())
                self.assertTrue(config.get("FirstRunComplete"))
                self.assertTrue(window.first_run_destination.isReadOnly())
                self.assertTrue(window.first_run_confirm.isHidden())

                window._start_server = lambda: None
                window._open_first_run_pairing()
                self.assertEqual(
                    window.tabs.currentIndex(),
                    window._page_names.index("Browser extension"),
                )
            finally:
                _retire_test_window(window)

    def test_first_run_launches_setup_from_the_visible_download_page(self):
        from PySide6.QtWidgets import QApplication

        config = FakeConfig({"LastPage": "History"})
        manager = ad.DownloadManager(config, FakeHistory())
        started = []

        class Signal:
            def connect(self, callback):
                self.callback = callback

        class Worker:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.log = Signal()
                self.progress = Signal()
                self.finished_ok = Signal()
                self.finished_err = Signal()

            def start(self):
                started.append(self)

            def isRunning(self):
                return False

        _get_qapp_or_skip(self)
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"), \
                mock.patch.object(ad, "SetupWorker", Worker):
            window = ad.MainWindow(
                config,
                manager,
                FakeHistory(),
                first_run=True,
            )
            window._run_setup()
        self.addCleanup(_retire_test_window, window)
        self.assertEqual(window.tabs.currentIndex(), 0)
        QApplication.processEvents()
        self.assertEqual(len(started), 1)
        self.assertFalse(window.setup_progress.isHidden())
        self.assertFalse(window.setup_status.isHidden())
        self.assertFalse(window.btn_startstop.isEnabled())

    def test_server_page_is_named_for_the_extension_it_serves(self):
        from PySide6.QtWidgets import QLabel

        window = self._window()
        page = window.tabs.widget(window._page_names.index("Browser extension"))
        labels = [label.text() for label in page.findChildren(QLabel)]
        self.assertIn("Browser extension", labels)
        self.assertTrue(
            any("by pasting a link never needs this server." in text for text in labels),
            "the server page must say the downloader works without it",
        )

    def test_download_tool_readiness_lives_with_the_paste_box(self):
        from PySide6.QtWidgets import QLabel, QScrollArea

        window = self._window()
        download_page = window.tabs.widget(0)
        if isinstance(download_page, QScrollArea):
            download_page = download_page.widget()
        server_page = window.tabs.widget(window._page_names.index("Browser extension"))

        def readiness_labels(page):
            return {
                str(dot.property("statusLabel"))
                for _key, (dot, _value) in window.readiness_values.items()
                if page.isAncestorOf(dot)
            }

        self.assertEqual(
            readiness_labels(download_page),
            {
                "yt-dlp", "FFmpeg", "JavaScript runtime", "SABR",
                "PO provider", "Transcription model",
            },
        )
        self.assertEqual(readiness_labels(server_page), {"Local API"})

    def test_every_readiness_key_the_probe_writes_has_a_row(self):
        # Feed a complete probe result through the real update path. A missing
        # row would make one of these updates disappear silently.
        window = self._window()
        expected = {"ytDlp", "ffmpeg", "deno", "sabr", "provider", "whisper"}
        self.assertTrue(expected.issubset(window.readiness_values))
        window._apply_readiness({
            "ytDlp": "2026.08.01",
            "ffmpeg": "8.0",
            "runtime": {
                "runtime": "deno",
                "version": "2.0",
                "supported": True,
                "ejsReady": True,
            },
            "provider": {"ok": True, "version": "1.3.0"},
        })
        for key in expected:
            with self.subTest(key=key):
                self.assertNotEqual(window.readiness_values[key][1].text(), "")

    def test_provider_readiness_row_is_built_on_the_download_page(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                self.assertIn("provider", window.readiness_values)
                window._apply_readiness({"provider": {"ok": True, "version": "1.3.0"}})
                _dot, value = window.readiness_values["provider"]
                self.assertEqual(value.text(), "1.3.0")
                self.assertIn("proof-of-origin", value.toolTip())

                window._apply_readiness({})
                self.assertEqual(window.readiness_values["provider"][1].text(), "Fallback")
            finally:
                _retire_test_window(window)

    def test_a_storage_failure_is_shown_on_the_download_page(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(FakeConfig(), manager, FakeHistory())
            try:
                # The window is never shown in an offscreen run, so isHidden()
                # is the honest question: was it explicitly hidden?
                window._update_ui()
                self.assertTrue(window.persistence_notice.isHidden())

                manager._history_error = "Disk is full."
                window._update_ui()
                QApplication.processEvents()
                self.assertFalse(window.persistence_notice.isHidden())
                self.assertEqual(window.persistence_notice.text(), "Disk is full.")

                manager._history_error = ""
                window._update_ui()
                QApplication.processEvents()
                self.assertTrue(window.persistence_notice.isHidden())
            finally:
                _retire_test_window(window)

    def test_empty_queue_points_at_the_paste_box_not_the_server(self):
        from PySide6.QtWidgets import QApplication, QPushButton

        window = self._window()
        focused = []
        window._focus_download_url = lambda: focused.append(True)
        window._reconcile_download_list([], [], [])
        QApplication.processEvents()
        empty = window._download_widgets[("empty",)]
        buttons = [button for button in empty.findChildren(QPushButton)]
        self.assertEqual([button.text() for button in buttons], ["Paste a link"])
        self.assertNotIn(
            "Open dashboard",
            [button.text() for button in empty.findChildren(QPushButton)],
        )

        buttons[0].click()
        self.assertEqual(focused, [True])


class PlaylistStagingSelectionTests(unittest.TestCase):
    """Per-item playlist edits collapse into the fewest downloads that honour them."""

    def test_untouched_rows_stay_one_download(self):
        selection = [
            {"index": 1, "format": "mp4", "quality": "best", "output_name": ""},
            {"index": 2, "format": "mp4", "quality": "best", "output_name": ""},
            {"index": 5, "format": "mp4", "quality": "best", "output_name": ""},
        ]
        self.assertEqual(
            ad.group_playlist_selection(selection),
            [{"format": "mp4", "quality": "best", "output_name": "",
              "items": [1, 2, 5]}],
        )

    def test_an_edited_row_splits_off_and_the_rest_stay_together(self):
        selection = [
            {"index": 1, "format": "mp4", "quality": "best", "output_name": ""},
            {"index": 2, "format": "mkv", "quality": "1080", "output_name": ""},
            {"index": 3, "format": "mp4", "quality": "best", "output_name": ""},
            {"index": 4, "format": "mkv", "quality": "1080", "output_name": ""},
        ]
        self.assertEqual(
            ad.group_playlist_selection(selection),
            [
                {"format": "mp4", "quality": "best", "output_name": "",
                 "items": [1, 3]},
                {"format": "mkv", "quality": "1080", "output_name": "",
                 "items": [2, 4]},
            ],
        )

    def test_a_named_row_is_always_its_own_download(self):
        # --output names a single file, so two items cannot share one.
        selection = [
            {"index": 1, "format": "mp4", "quality": "best", "output_name": "Intro"},
            {"index": 2, "format": "mp4", "quality": "best", "output_name": "Outro"},
            {"index": 3, "format": "mp4", "quality": "best", "output_name": ""},
        ]
        self.assertEqual(
            [group["items"] for group in ad.group_playlist_selection(selection)],
            [[1], [2], [3]],
        )

    def test_junk_entries_are_dropped_rather_than_queued(self):
        selection = [
            "not a row",
            {"index": 0},
            {"index": "seven"},
            {"index": 2, "format": "mp4"},
        ]
        self.assertEqual(
            ad.group_playlist_selection(selection),
            [{"format": "mp4", "quality": "best", "output_name": "",
              "items": [2]}],
        )
        self.assertEqual(ad.group_playlist_selection(None), [])


class PlaylistStagingDialogTests(unittest.TestCase):
    """The staging dialog edits items; it no longer only prunes them."""

    _PREVIEW = {
        "title": "Field notes",
        "channel": "Astra Studio",
        "items": [
            {"index": 1, "id": "aaa", "title": "First", "duration": 60},
            {"index": 2, "id": "bbb", "title": "Second", "duration": 90},
            {"index": 3, "id": "ccc", "title": "Third", "duration": 30},
        ],
    }

    def _dialog(self, **kwargs):
        options = {
            "format_choices": [("MP4", "mp4"), ("MKV", "mkv")],
            "quality_choices": [("Best", "best"), ("1080p", "1080")],
            "default_format": "mp4",
            "default_quality": "best",
        }
        options.update(kwargs)
        return ad.PlaylistStagingDialog(None, self._PREVIEW, **options)

    def test_an_archived_item_is_flagged_and_starts_unselected(self):
        _get_qapp_or_skip(self)
        dialog = self._dialog(archived_indices={2})
        try:
            archived = [row for row in dialog.rows if row["archived"]]
            self.assertEqual([row["index"] for row in archived], [2])
            self.assertFalse(archived[0]["checkbox"].isChecked())
            self.assertEqual(dialog.get_selected_indices(), [1, 3])
            self.assertIn(
                "subscription archive",
                archived[0]["checkbox"].accessibleDescription(),
            )
            # Flagged, not forbidden: ticking it queues the item again.
            archived[0]["checkbox"].setChecked(True)
            self.assertEqual(dialog.get_selected_indices(), [1, 2, 3])
        finally:
            dialog.deleteLater()

    def test_a_per_item_edit_only_changes_that_item(self):
        _get_qapp_or_skip(self)
        dialog = self._dialog()
        try:
            second = dialog.rows[1]
            second["format"].setCurrentIndex(second["format"].findData("mkv"))
            second["quality"].setCurrentIndex(second["quality"].findData("1080"))
            second["name"].setText("  Chapter two  ")
            selection = dialog.get_selection()
            self.assertEqual(selection[0], {
                "index": 1, "format": "mp4", "quality": "best", "output_name": "",
            })
            self.assertEqual(selection[1], {
                "index": 2, "format": "mkv", "quality": "1080",
                "output_name": "Chapter two",
            })
            self.assertEqual(selection[2]["format"], "mp4")
        finally:
            dialog.deleteLater()

    def test_batch_apply_writes_onto_selected_rows_only(self):
        _get_qapp_or_skip(self)
        dialog = self._dialog()
        try:
            dialog.rows[2]["checkbox"].setChecked(False)
            dialog.batch_format.setCurrentIndex(
                dialog.batch_format.findData("mkv"))
            dialog.batch_quality.setCurrentIndex(
                dialog.batch_quality.findData("1080"))
            dialog._apply_batch()
            self.assertEqual(
                [row["format"].currentData() for row in dialog.rows],
                ["mkv", "mkv", "mp4"],
            )
            self.assertEqual(
                [row["quality"].currentData() for row in dialog.rows],
                ["1080", "1080", "best"],
            )
            self.assertEqual(dialog.batch_result.text(), "Applied to 2 videos")
            # The selected-count readout is not the place for that message.
            self.assertEqual(dialog.lbl_selected_count.text(), "2 of 3 selected")
        finally:
            dialog.deleteLater()

    def test_two_rows_with_the_same_name_are_refused_rather_than_overwritten(self):
        from PySide6.QtWidgets import QDialog

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "FirstRunComplete": True})
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"),                     mock.patch.object(ad.MainWindow, "_start_readiness_probe"),                     mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            queued = []

            def fake_exec(dialog_self):
                dialog_self.rows[0]["name"].setText("Same name")
                dialog_self.rows[1]["name"].setText("Same name")
                return QDialog.DialogCode.Accepted

            try:
                window.quick_download_url.setText(
                    "https://www.youtube.com/playlist?list=PLtest")
                with mock.patch.object(
                    manager, "preview_playlist",
                    return_value=(self._PREVIEW, None),
                ), mock.patch.object(
                    manager, "start_download",
                    side_effect=lambda **kwargs: queued.append(kwargs) or ("d", None),
                ), mock.patch.object(
                    ad.PlaylistStagingDialog, "exec", fake_exec,
                ):
                    window._open_playlist_staging()
                self.assertEqual(queued, [])
                self.assertIn("Same name", window.quick_download_status.text())
            finally:
                _retire_test_window(window)

    def test_staging_queues_one_download_per_distinct_choice(self):
        from PySide6.QtWidgets import QDialog

        _get_qapp_or_skip(self)
        with tempfile.TemporaryDirectory() as tmpdir:
            config = FakeConfig({"DownloadPath": tmpdir, "FirstRunComplete": True})
            manager = ad.DownloadManager(config, FakeHistory())
            with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                    mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                    mock.patch.object(ad.QSystemTrayIcon, "show"):
                window = ad.MainWindow(config, manager, FakeHistory())
            calls = []

            def fake_start(**kwargs):
                calls.append(kwargs)
                return f"dl{len(calls)}", None

            def fake_exec(dialog_self):
                dialog_self.rows[1]["format"].setCurrentIndex(
                    dialog_self.rows[1]["format"].findData("mkv"))
                dialog_self.rows[2]["name"].setText("Finale")
                return QDialog.DialogCode.Accepted

            try:
                window.quick_download_url.setText(
                    "https://www.youtube.com/playlist?list=PLtest")
                with mock.patch.object(
                    manager, "preview_playlist",
                    return_value=(self._PREVIEW, None),
                ), mock.patch.object(
                    manager, "start_download", side_effect=fake_start,
                ), mock.patch.object(
                    ad.PlaylistStagingDialog, "exec", fake_exec,
                ), mock.patch.object(
                    ad.MainWindow, "_combo_choices",
                    staticmethod(lambda _combo: [("MP4", "mp4"), ("MKV", "mkv")]),
                ):
                    window._open_playlist_staging()
                self.assertEqual(
                    [(call["playlist_items"], call["fmt"], call["output_name"])
                     for call in calls],
                    [([1], "mp4", None), ([2], "mkv", None), ([3], "mp4", "Finale")],
                )
                self.assertIn("Queued 3 items", window.quick_download_status.text())
            finally:
                _retire_test_window(window)


class WindowsShellIntegrationTests(unittest.TestCase):
    """Jump list, restart registration, and a recoverable delete."""

    def test_a_deleted_file_goes_to_the_recycle_bin(self):
        # Not mocked: SHFileOperationW either moves the file into the Recycle
        # Bin or it does not, and a double would only prove the arguments.
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "astra recycle probe.mp4"
            target.write_bytes(b"delete me")
            ok, reason = ad.send_to_recycle_bin(target)
            self.assertTrue(ok, reason)
            self.assertFalse(target.exists())

    def test_the_delete_refuses_what_it_cannot_recycle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(
                ad.send_to_recycle_bin(Path(tmpdir) / "not-there.mp4"),
                (False, "not-a-file"),
            )
            # Path('') is Path('.'), a directory that exists, so an empty
            # value has to be refused before it becomes a path.
            self.assertEqual(ad.send_to_recycle_bin(""), (False, "no-path"))
            self.assertEqual(ad.send_to_recycle_bin(None), (False, "no-path"))
            self.assertEqual(
                ad.send_to_recycle_bin(tmpdir), (False, "not-a-file"),
                "a folder is not a queue item and must not be recycled",
            )

    def test_a_symlink_is_refused_rather_than_recycled_as_its_target(self):
        # resolve() would hand the shell the target and leave the link
        # dangling, and is_file() follows the link, so the check has to come
        # first.
        with tempfile.TemporaryDirectory() as tmpdir:
            real = Path(tmpdir) / "real.mp4"
            real.write_bytes(b"the actual download")
            link = Path(tmpdir) / "link.mp4"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("this account cannot create a symlink")
            self.assertEqual(ad.send_to_recycle_bin(link), (False, "symlink"))
            self.assertTrue(real.is_file(), "the target must be untouched")

    def test_the_delete_asks_before_destroying_what_it_cannot_recycle(self):
        # FOF_ALLOWUNDO is a request: a file over the drive's Recycle Bin
        # quota, or one on a network volume, is deleted outright and the call
        # still returns 0. WANTNUKEWARNING is the only signal Windows gives,
        # and reporting "moved to the Recycle Bin" for a destroyed file is
        # the failure it prevents.
        source = inspect.getsource(ad.send_to_recycle_bin)
        self.assertIn("FOF_WANTNUKEWARNING", source)
        self.assertNotIn(
            "target.resolve()", source,
            "resolving the path defeats the symlink refusal above",
        )

    def test_a_jump_task_reaches_a_running_instance(self):
        # Both allowlists have to admit it. Either one dropping it means a
        # jump-list click on a running app starts a process the guard throws
        # away and nothing happens at all.
        sent = []
        with mock.patch.object(ad.socket, "create_connection") as connect, \
                mock.patch.object(ad, "instance_control_token", return_value="t" * 32):
            connect.return_value.__enter__.return_value.sendall = sent.append
            self.assertTrue(ad.send_instance_command("jump paste"))
        self.assertEqual(len(sent), 1)
        self.assertIn(b"jump paste", sent[0])

        listener = inspect.getsource(
            gui_module_for_tests().MainWindowCore._start_instance_command_listener)
        self.assertIn("startswith('jump ')", listener)

    def test_a_background_start_outranks_a_jump_argument(self):
        # A launch carrying both used to read as a jump, so a start-server
        # launch stopped counting as one and popped a window.
        self.assertEqual(
            ad.startup_command_from_argv(["--start-server", "--paste-download"]),
            "start",
        )
        self.assertEqual(
            ad.startup_command_from_argv(["--paste-download", "--start-server"]),
            "start",
        )
        self.assertEqual(
            ad.startup_command_from_argv(["ytdl://start", "--paste-download"]),
            "start",
        )

    def test_the_restart_command_line_is_bounded_by_whole_arguments(self):
        self.assertEqual(
            ad.build_restart_command_line(["--start-server"]), "--start-server")
        self.assertEqual(
            ad.build_restart_command_line(["--start-server", "--portable"]),
            "--start-server --portable",
        )
        self.assertEqual(ad.build_restart_command_line([]), "")
        self.assertEqual(ad.build_restart_command_line(["", "  "]), "")
        # RegisterApplicationRestart rejects 1024 characters or more. Half an
        # argument is a different request from the registered one, so the
        # overflowing argument is dropped rather than cut.
        long_argument = "--x" * 400
        bounded = ad.build_restart_command_line(
            ["--start-server", long_argument, "--portable"])
        self.assertEqual(bounded, "--start-server")
        self.assertLess(len(bounded), ad.RESTART_MAX_COMMAND_LINE)

    def test_windows_accepts_the_restart_registration(self):
        self.assertTrue(ad.register_application_restart(["--start-server"]))

    def test_the_registered_restart_argument_starts_the_server_again(self):
        # The reboot itself cannot be driven from a test. What can be driven
        # is the whole path either side of it: the arguments Windows is given,
        # and what this app does when it is launched with them.
        _get_qapp_or_skip(self)
        registered = ad.build_restart_command_line(["--start-server"])
        self.assertEqual(
            ad.startup_command_from_argv(registered.split()), "start")

        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        started = []
        try:
            window._start_server = lambda: started.append(True)
            window._handle_instance_command("start")
            self.assertEqual(started, [True])
        finally:
            _retire_test_window(window)

    def test_a_portable_copy_registers_its_own_mode(self):
        # A portable copy relaunched without --portable would come back
        # reading the installed AppData state instead of its own.
        self.assertEqual(
            ad.build_restart_command_line(["--start-server", "--portable"]),
            "--start-server --portable",
        )
        source = inspect.getsource(ad.main)
        self.assertIn("register_application_restart(", source)
        self.assertIn("['--portable'] if is_portable_mode() else []", source)

    def test_a_jump_list_task_survives_a_cold_start(self):
        # Windows offers these whether or not the app is running, so argv has
        # to name them and a second launch has to delegate rather than die in
        # the single-instance guard.
        self.assertEqual(
            ad.jump_list_command_from_argv(["--paste-download"]), "paste")
        self.assertEqual(
            ad.jump_list_command_from_argv(["--open-downloads"]), "downloads")
        self.assertEqual(ad.jump_list_command_from_argv(["--start-server"]), "")
        self.assertEqual(
            ad.startup_command_from_argv(["--paste-download"]), "jump paste")
        self.assertEqual(
            ad.startup_command_from_argv(["--open-downloads"]), "jump downloads")
        self.assertEqual(
            ad.startup_command_from_argv(["--start-server"]), "start")

    def test_every_task_names_an_argument_the_app_understands(self):
        tasks = ad.jump_list_tasks()
        self.assertTrue(tasks)
        for task in tasks:
            with self.subTest(task=task["title"]):
                self.assertTrue(task["title"])
                self.assertTrue(task["description"])
                self.assertTrue(
                    ad.jump_list_command_from_argv([task["arguments"]]),
                    f"{task['arguments']} is offered but never handled",
                )

    def test_windows_accepts_and_stores_the_jump_list(self):
        published = ad.JumpList().publish(
            ad.current_executable_path(),
            app_id="SysAdminDoc.AstraDownloader.Test",
        )
        self.assertTrue(published, "Windows refused the jump list")

    def test_a_shortcut_carries_the_taskbar_identity(self):
        # Without this the jump list is published and never shown: Windows
        # keys it to the shortcut's AppUserModelID, and WScript.Shell — which
        # writes every .lnk here — cannot set a property-store value.
        with tempfile.TemporaryDirectory() as tmpdir:
            lnk = Path(tmpdir) / "Astra Downloader.lnk"
            subprocess.run(
                [ad.system32_command("powershell"), "-NoProfile", "-Command",
                 ad.build_shortcut_command(lnk, sys.executable, ["--start-server"])],
                capture_output=True, timeout=60,
            )
            if not lnk.is_file():
                self.skipTest("PowerShell did not write a shortcut here")
            self.assertTrue(ad.stamp_shortcut_app_user_model_id(lnk))
            read_back = subprocess.run(
                [ad.system32_command("powershell"), "-NoProfile", "-Command",
                 "$s=New-Object -ComObject Shell.Application;"
                 f"$f=$s.Namespace('{tmpdir}');"
                 "$i=$f.ParseName('Astra Downloader.lnk');"
                 "$i.ExtendedProperty('System.AppUserModel.ID')"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(
                (read_back.stdout or "").strip(), ad.APP_USER_MODEL_ID,
                "the shell does not see the identity we wrote",
            )
            self.assertFalse(
                ad.stamp_shortcut_app_user_model_id(Path(tmpdir) / "gone.lnk"))

    def test_the_paste_task_refuses_a_clipboard_that_is_not_a_link(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        started = []
        try:
            window._start_quick_download = lambda: started.append(True)
            QApplication.clipboard().setText("just some prose, not a link")
            self.assertFalse(window.run_jump_list_task("paste"))
            self.assertEqual(started, [])
            self.assertIn("Copy a video link", window.quick_download_status.text())

            QApplication.clipboard().setText(
                "https://www.youtube.com/watch?v=abc12345678")
            self.assertTrue(window.run_jump_list_task("paste"))
            self.assertEqual(started, [True])
            self.assertIn("youtube.com", window.quick_download_url.text())

            opened = []
            window._open_folder = lambda: opened.append(True)
            self.assertTrue(window.run_jump_list_task("downloads"))
            self.assertEqual(opened, [True])
            self.assertFalse(window.run_jump_list_task("nonsense"))
        finally:
            QApplication.clipboard().clear()
            _retire_test_window(window)

    def test_the_queue_menu_deletes_through_the_recycle_bin(self):
        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                target = Path(tmpdir) / "clip.mp4"
                target.write_bytes(b"finished download")
                download = ad.Download("dl_bin", "https://example.com/clip")
                download.status = "complete"
                download.filename = str(target)

                menu = window._download_card_menu(download, window)
                actions = {action.text(): action for action in menu.actions()}
                self.assertIn("Delete file", actions)
                self.assertTrue(actions["Delete file"].isEnabled())

                self.assertTrue(window._delete_download_file(download))
                self.assertFalse(target.exists())
                self.assertIn("Recycle Bin", window.quick_download_status.text())

                # A file that is already gone reports the failure rather than
                # claiming a delete that did not happen.
                self.assertFalse(window._delete_download_file(download))
        finally:
            _retire_test_window(window)


class SubscriptionArchiveViewTests(unittest.TestCase):
    """What the archive dialog is allowed to claim about a file."""

    def test_an_unreachable_drive_is_not_reported_as_a_deleted_file(self):
        # Path.is_file() swallows "drive exists but is not ready" and answers
        # False, so an ejected USB stick used to read as "the file is no
        # longer on this machine" — the one claim this must never make.
        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                present = Path(tmpdir) / "here.mp4"
                present.write_bytes(b"downloaded")
                page = {"total": 3, "offset": 0, "items": [
                    {"key": "id:1", "title": "Here", "status": "complete",
                     "filePath": str(present)},
                    {"key": "id:2", "title": "Deleted", "status": "complete",
                     "filePath": str(Path(tmpdir) / "gone.mp4")},
                    {"key": "id:3", "title": "Unplugged", "status": "complete",
                     "filePath": str(Path(tmpdir) / "not-ready.mp4")},
                ]}
                manager_double = types.SimpleNamespace(
                    get_subscription=lambda _sub_id: {"id": "s", "title": "T"},
                    archive_page=lambda _sub_id: page,
                    forget_archive_entry=lambda _key: (True, ""),
                    stop=lambda: None,
                )
                window._dependencies['subscription_manager'] = manager_double

                real_stat = os.stat

                def stat(path, *args, **kwargs):
                    # ERROR_NOT_READY, which a drive with no media in it
                    # raises. It cannot be produced on demand here, and it is
                    # the one Path.is_file() swallows into a plain False.
                    if str(path).endswith("not-ready.mp4"):
                        raise OSError(5, "The device is not ready", str(path), 21)
                    return real_stat(path, *args, **kwargs)

                with mock.patch.object(ad.SubscriptionArchiveDialog, "exec",
                                       lambda _self: None), \
                        mock.patch.object(ad.os, "stat", stat):
                    self.assertTrue(window._open_subscription_archive("s"))
                by_key = {item["key"]: item for item in page["items"]}
                self.assertFalse(by_key["id:1"]["fileMissing"])
                self.assertTrue(by_key["id:2"]["fileMissing"])
                self.assertFalse(
                    by_key["id:3"]["fileMissing"],
                    "an unreachable drive is not proof of a deletion",
                )
        finally:
            _retire_test_window(window)


if __name__ == "__main__":
    unittest.main()
