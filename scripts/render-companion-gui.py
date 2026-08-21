#!/usr/bin/env python3
"""Render deterministic companion operational states for visual QA."""

import os
import shutil
import subprocess
import sys
import tempfile
import json
import time
import traceback
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "build" / "companion-ui-smoke"
CAPTURE_NAMES = (
    "dashboard-starting",
    "dashboard-online",
    "dashboard-light-theme",
    "dashboard-log-populated",
    "dashboard-error-degraded",
    "dashboard-german",
    "dashboard-spanish",
    "dashboard-french",
    "dashboard-italian",
    "dashboard-japanese",
    "dashboard-korean",
    "dashboard-portuguese",
    "dashboard-russian",
    "dashboard-chinese",
    "downloads-first-run",
    "downloads-arabic-rtl",
    "downloads-active-pending",
    "downloads-advanced-options",
    "downloads-health-error",
    "downloads-focus-1x",
    "downloads-light-theme",
    "downloads-clipboard-staged",
    "downloads-subtitles-only",
    "downloads-recovery-terminal",
    "downloads-rate-limited",
    "downloads-quarantine",
    "downloads-paused-intake",
    "downloads-queue-full",
    "downloads-format-probe",
    "history-populated",
    "history-light-theme",
    "history-cleared-undo",
    "history-restored",
    "history-unreadable",
    "history-filter-empty",
    "history-pagination",
    "subscriptions-empty",
    "subscriptions-populated",
    "subscriptions-light-theme",
    "subscriptions-scanning",
    "subscriptions-error",
    "subscriptions-filter-empty",
    "subscriptions-disabled",
    "site-logins-empty",
    "site-logins-stored",
    "site-logins-light-theme",
    "site-logins-error",
    "site-logins-filter-empty",
    "settings-dirty",
    "settings-light-theme",
    "settings-subtitles",
    "settings-bundle-imported",
    "settings-fallback-port",
    "settings-invalid",
    "settings-search-active",
    "settings-invalid-site-profiles",
    "settings-save-failed",
    "settings-update-busy",
    "settings-focus-125x",
    "reflow-900x620-hidpi-large-font",
    "diagnostics-review",
    "diagnostics-review-light-theme",
    "playlist-review",
    "playlist-review-light-theme",
    "command-review",
    "command-review-light-theme",
)

LOCALE_SCENARIOS = {
    "dashboard-spanish": "es",
    "dashboard-french": "fr",
    "dashboard-italian": "it",
    "dashboard-japanese": "ja",
    "dashboard-korean": "ko",
    "dashboard-portuguese": "pt_BR",
    "dashboard-russian": "ru",
    "dashboard-chinese": "zh_CN",
}

SCALE_SCENARIOS = {
    "downloads-focus-1x": 1.0,
    "settings-focus-125x": 1.25,
    "reflow-900x620-hidpi-large-font": 2.0,
}


def main():
    scenario = os.environ.get("ASTRA_COMPANION_RENDER_SCENARIO")
    if not scenario:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for old_capture in OUTPUT_DIR.glob("*.png"):
            old_capture.unlink()
        for name in CAPTURE_NAMES:
            env = dict(os.environ)
            env["ASTRA_COMPANION_RENDER_SCENARIO"] = name
            child_kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                child_kwargs.update(
                    startupinfo=startupinfo,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, **child_kwargs,
            )
            if result.returncode:
                if result.stdout:
                    print(result.stdout, end="")
                raise subprocess.CalledProcessError(
                    result.returncode, result.args,
                )
        for name in CAPTURE_NAMES:
            output = OUTPUT_DIR / f"{name}.png"
            if not output.exists() or output.stat().st_size < 10_000:
                raise RuntimeError(f"Companion render is missing or unexpectedly small: {output}")
        print(f"Rendered {len(CAPTURE_NAMES)} companion states in {OUTPUT_DIR}")
        return 0
    if scenario not in CAPTURE_NAMES:
        raise RuntimeError(f"Unknown companion render scenario: {scenario}")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_SCALE_FACTOR"] = str(SCALE_SCENARIOS.get(scenario, 1.0))
    os.environ["ASTRA_DOWNLOADER_NO_BOOTSTRAP"] = "1"
    try:
        hold_seconds = max(0.0, min(30.0, float(os.environ.get("ASTRA_COMPANION_RENDER_HOLD_SECONDS", "0"))))
    except ValueError:
        hold_seconds = 0.0

    with tempfile.TemporaryDirectory(prefix="astra-companion-render-") as temp_dir:
        os.environ["LOCALAPPDATA"] = temp_dir
        sys.path.insert(0, str(ROOT))

        from astra_downloader import astra_downloader as app_module
        from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
        from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QImage
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

        install_dir = Path(temp_dir) / "AstraDownloader"
        install_dir.mkdir(parents=True, exist_ok=True)
        source_icon = ROOT / "AstraDownloader.ico"
        if source_icon.exists():
            shutil.copy2(source_icon, install_dir / "AstraDownloader.ico")

        app = QApplication(["render-companion-gui"])
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(app_module.APP_NAME)
        app.setApplicationVersion(app_module.APP_VERSION)
        if scenario == "downloads-arabic-rtl":
            app._astra_translator = app_module.install_companion_translator(app, "ar")
        else:
            locale = {
                "dashboard-german": "de",
                **LOCALE_SCENARIOS,
            }.get(scenario)
            if locale:
                app._astra_translator = app_module.install_companion_translator(app, locale)
        for font_name in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
            font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / font_name
            if font_path.exists():
                QFontDatabase.addApplicationFont(str(font_path))
        default_font = QFont("Segoe UI", 9)
        app.setFont(default_font)
        render_theme = "light" if scenario.endswith("-light-theme") else "dark"
        app_module.apply_application_theme(render_theme)
        if app_module.ICON_PATH.exists():
            app.setWindowIcon(QIcon(str(app_module.ICON_PATH)))
        retained_windows = []

        # Visual fixtures never listen on a real port or probe external tools.
        # The state application below still calls the production render paths.
        app_module.MainWindow._start_instance_command_listener = lambda self: None
        app_module.MainWindow._stop_instance_command_listener = lambda self: None
        app_module.MainWindow._start_readiness_probe = lambda self: None
        app_module.MainWindow._refresh_tools_status = (
            lambda self: self._set_tools_status_text("yt-dlp 2026.07.04    •    ffmpeg 7.1")
        )

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        class FixtureSubscriptions:
            def __init__(self):
                self._records = [{
                    "id": "sub-fixture",
                    "url": "https://www.youtube.com/@astra-channel",
                    "title": "Astra channel",
                    "intervalMinutes": 60,
                    "enabled": True,
                    "nextScanAt": 1_800_000_000,
                    "lastError": "",
                }]

            def snapshot(self):
                return {
                    "subscriptions": list(self._records),
                    "archive": {"total": 12, "complete": 10, "queued": 2},
                    "schedulerRunning": False,
                    "scanning": [],
                }

            def start(self):
                return True

            def stop(self):
                return None

        def make_context():
            config = app_module.Config()
            config.update({
                "CloseToTray": False,
                "StartMinimized": False,
                "DownloadPath": str(Path(temp_dir) / "Videos"),
                "AudioDownloadPath": str(Path(temp_dir) / "Music"),
                "Theme": render_theme,
                "FirstRunComplete": scenario != "downloads-first-run",
            })
            history = app_module.History()
            manager = app_module.DownloadManager(config, history)
            subscriptions = FixtureSubscriptions()
            return config, history, manager, subscriptions

        def make_window(*, large_font=False, minimum_size=False):
            app.setFont(QFont("Segoe UI", 12 if large_font else 9))
            config, history, manager, subscriptions = make_context()
            window = app_module.MainWindow(
                config,
                manager,
                history,
                subscriptions=subscriptions,
                first_run=scenario == "downloads-first-run",
            )
            window._animate_page = lambda: None
            window.update_timer.stop()
            window.cleanup_timer.stop()
            window.tools_status_timer.stop()
            if minimum_size:
                window.resize(900, 620)
            window.show()
            app.processEvents()
            QTest.qWait(120)
            return window, config, history, manager

        def select_page(window, page_name):
            expected_index = (
                "Download", "History", "Sign-ins", "Subscriptions",
                "Browser extension", "Settings",
            ).index(page_name)
            focus_targets = {
                "Download": window.quick_download_url,
                "History": window.history_search,
                "Sign-ins": window.site_login_url,
                "Subscriptions": window.subscription_search,
                "Browser extension": window.btn_startstop,
                "Settings": window.settings_filter,
            }
            focus_target = focus_targets[page_name]
            window._nav_click(page_name)
            for nav_button in window.nav_buttons:
                nav_button.clearFocus()
            focus_target.setFocus(Qt.FocusReason.OtherFocusReason)
            app.processEvents()
            window.repaint()
            app.processEvents()
            QTest.qWait(80)
            if window.tabs.currentIndex() != expected_index:
                raise RuntimeError(f"Companion navigation did not activate {page_name}")
            if not window.brand_widget.isVisible() or not all(
                    button.isVisible() for button in window.nav_buttons):
                raise RuntimeError(f"Companion navigation rail is incomplete on {page_name}")
            for nav_button in window.nav_buttons:
                if not window.sidebar.rect().contains(nav_button.geometry()):
                    raise RuntimeError(f"Navigation control escaped the native rail on {page_name}")
            if not focus_target.hasFocus() or app.focusWidget() is None:
                raise RuntimeError(f"Companion page has no focused control on {page_name}")
            if app.focusWidget().window() is not window:
                raise RuntimeError(f"Focused control escaped the companion window on {page_name}")
            window._render_focus_target = focus_target

        def assert_download_options_reflow(window):
            """Pin the minimum-size fixture's option rows, not its screenshot."""
            container = window.quick_download_options_container
            if window.quick_download_options_layout.count() < 2:
                raise RuntimeError("Download options did not wrap into multiple rows")
            controls = [
                window.quick_download_profile,
                window.quick_download_type,
                window.quick_download_format,
                window.quick_download_quality,
                window.btn_quick_download_dest,
                window.quick_download_start,
                window.quick_download_end,
            ]
            rects = []
            common_parent = container.parentWidget()
            for control in controls:
                if not control.isVisible():
                    raise RuntimeError(
                        f"Download option is hidden: {control.objectName() or type(control).__name__}"
                    )
                owner = (
                    container
                    if container.isAncestorOf(control)
                    else window.quick_download_advanced
                )
                owner_top_left = owner.mapTo(common_parent, QPoint(0, 0))
                container_rect = QRect(owner_top_left, owner.size())
                top_left = control.mapTo(common_parent, QPoint(0, 0))
                rect = QRect(top_left, control.size())
                rects.append(rect)
                if not (
                    container_rect.contains(rect.topLeft())
                    and container_rect.contains(rect.bottomRight())
                ):
                    raise RuntimeError(
                        f"Download option escaped its row container: {type(control).__name__} "
                        f"rect={rect}, container={container_rect}"
                    )
                if hasattr(control, "currentText"):
                    text = control.currentText()
                    reserved = 44  # padding plus the native drop-down arrow
                else:
                    text = control.text()
                    reserved = 26  # horizontal stylesheet padding
                if text and control.fontMetrics().horizontalAdvance(text) > max(
                    0, control.width() - reserved
                ):
                    raise RuntimeError(
                        f"Download option text is clipped: {text!r} in {control.width()}px"
                    )
            for index, rect in enumerate(rects):
                for other in rects[index + 1:]:
                    if rect.intersects(other):
                        raise RuntimeError(
                            "Download option controls overlap at the minimum size"
                        )

        def scroll_current_page_to_bottom(window):
            current = window.tabs.currentWidget()
            scroll = current if isinstance(current, QScrollArea) else current.findChild(QScrollArea)
            if scroll is not None:
                scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                app.processEvents()
                QTest.qWait(40)

        def scroll_current_page_to_top(window):
            current = window.tabs.currentWidget()
            scroll = current if isinstance(current, QScrollArea) else current.findChild(QScrollArea)
            if scroll is not None:
                scroll.verticalScrollBar().setValue(0)
                app.processEvents()
                QTest.qWait(40)

        def visible_text(window):
            return {
                label.text()
                for label in window.findChildren(QLabel)
                if label.isVisible() and label.text()
            }

        def assert_visible_text(window, expected):
            rendered = visible_text(window)
            missing = [text for text in expected if text not in rendered]
            if missing:
                raise RuntimeError(
                    f"Operational state text is not visible: {missing}; "
                    f"visible={sorted(rendered)}"
                )

        def capture_window(window, name, *, dpr=1):
            if name not in CAPTURE_NAMES:
                raise RuntimeError(f"Undeclared companion fixture: {name}")
            app.processEvents()
            window.repaint()
            # Qt's offscreen backing store can discard untouched sibling
            # regions after a tall page scroll. Repaint the rail subtree and
            # warm its native backing surface before grabbing the complete
            # window, otherwise a valid Settings state can produce a blank
            # navigation rail in the evidence image.
            window.sidebar.update()
            for rail_widget in (
                    window.brand_widget,
                    *window.nav_buttons,
                    *window.sidebar.findChildren(QWidget)):
                rail_widget.update()
            window.sidebar.repaint()
            app.processEvents()
            QTest.qWait(100)
            rail_probe = window.sidebar.grab().toImage()
            if rail_probe.isNull():
                raise RuntimeError(f"Native navigation rail probe failed for {name}")
            app.processEvents()
            logical_size = window.size()
            # Grab the complete native backing store in one pass. This pins the
            # shipped rail/page composition instead of recreating it in QPainter.
            image = window.grab().toImage()
            if image.isNull() or image.deviceIndependentSize().toSize() != logical_size:
                raise RuntimeError(f"Companion capture geometry is invalid for {name}")
            actual_dpr = float(image.devicePixelRatio())
            if abs(actual_dpr - float(dpr)) > 0.01:
                raise RuntimeError(
                    f"Companion capture {name} expected {dpr}x DPI, got {image.devicePixelRatio():.1f}x"
                )
            focus_target = getattr(window, "_render_focus_target", None)
            if focus_target is not None and not focus_target.hasFocus():
                raise RuntimeError(f"Companion capture lost focus before painting: {name}")
            rail_x = int(round(max(1, min(window.sidebar.width() - 1, 116)) * actual_dpr))
            rail_colors = {
                image.pixelColor(rail_x, int(round(y * actual_dpr))).name()
                for y in range(12, max(13, window.height() - 12), 24)
            }
            if len(rail_colors) < 3:
                raise RuntimeError(f"Native navigation rail did not paint for {name}")
            for rail_widget in (window.brand_widget, *window.nav_buttons):
                top_left = rail_widget.mapTo(window, QPoint(0, 0))
                x0 = max(0, int(round(top_left.x() * actual_dpr)))
                y0 = max(0, int(round(top_left.y() * actual_dpr)))
                x1 = min(
                    image.width(),
                    x0 + int(round(rail_widget.width() * actual_dpr)),
                )
                y1 = min(
                    image.height(),
                    y0 + int(round(rail_widget.height() * actual_dpr)),
                )
                colors = {
                    image.pixelColor(x, y).name()
                    for y in range(y0, y1, max(1, int(round(4 * actual_dpr))))
                    for x in range(x0, x1, max(1, int(round(4 * actual_dpr))))
                }
                if len(colors) < 3:
                    raise RuntimeError(
                        f"Navigation control did not paint for {name}: "
                        f"{rail_widget.accessibleName() or type(rail_widget).__name__}"
                    )
            output = OUTPUT_DIR / f"{name}.png"
            if not image.save(str(output), "PNG"):
                raise RuntimeError(f"Failed to save companion render: {output}")
            print(f"captured {name}", flush=True)

        def fixture_download(manager, dl_id, title, status, order, **values):
            download = app_module.Download(
                dl_id,
                f"https://www.youtube.com/watch?v={dl_id:0<11}",
                fmt=values.pop("fmt", "mp4"),
                quality=values.pop("quality", "1080"),
                output_dir=str(Path(temp_dir) / "Videos"),
                title=title,
                created_at=1_750_000_000 + order,
                queue_order=order,
                clock=lambda: 1_750_001_000,
            )
            download.status = status
            for key, value in values.items():
                setattr(download, key, value)
            manager.downloads[download.id] = download
            if status in app_module.DOWNLOAD_RUNNING_STATES:
                manager._running_ids.add(download.id)
            return download

        def seed_download_matrix(manager):
            fixture_download(manager, "pending", "Queued lecture", "pending", 1)
            fixture_download(
                manager, "active", "Downloading documentary", "downloading", 2,
                progress=63.4, speed="8.2 MiB/s", eta="00:18",
            )
            fixture_download(
                manager, "paused", "Recovered interview", "paused", 3,
                error="Recovered after restart. Resume when ready.",
            )
            fixture_download(
                manager, "needsauth", "Members-only archive", "needs-auth", 4,
                requires_auth=True,
                error="Fresh sign-in is required.",
            )
            fixture_download(
                manager, "failed", "Unavailable livestream", "failed", 5,
                error="The video is unavailable in this region.",
                error_code="network",
                error_advice="Check the video in your browser and retry.",
                error_action="Open the video, then send it to Astra Downloader again.",
            )
            fixture_download(
                manager, "complete", "Finished tutorial", "complete", 6,
                progress=100,
                filename=str(Path(temp_dir) / "Videos" / "Finished tutorial.mp4"),
            )
            manager.total_completed = 1

        def seed_history(history, count=2):
            records = [
                {
                    "id": "history-1",
                    "url": "https://www.youtube.com/watch?v=history00001",
                    "title": "Keyboard navigation deep dive",
                    "filename": str(Path(temp_dir) / "Videos" / "Keyboard navigation deep dive.mp4"),
                    "format": "mp4",
                    "quality": "1080",
                    "duration": 754,
                    "date": "2026-07-28",
                },
                {
                    "id": "history-2",
                    "url": "https://www.youtube.com/watch?v=history00002",
                    "title": "Offline media workflow",
                    "filename": str(Path(temp_dir) / "Music" / "Offline media workflow.m4a"),
                    "format": "m4a",
                    "quality": "best",
                    "duration": 263,
                    "date": "2026-07-29",
                },
            ]
            for index in range(len(records) + 1, max(len(records), count) + 1):
                records.append({
                    "id": f"history-{index}",
                    "url": f"https://www.youtube.com/watch?v=history{index:05d}",
                    "title": f"Archived workflow {index}",
                    "filename": str(
                        Path(temp_dir) / "Videos" / f"Archived workflow {index}.mp4"
                    ),
                    "format": "mp4",
                    "quality": "720",
                    "duration": 180 + index,
                    "date": f"2026-07-{(index % 28) + 1:02d}",
                })
            history.replace(records)

        def capture_dashboard_state(window):
            select_page(window, "Browser extension")
            if scenario == "dashboard-german":
                assert_visible_text(window, {"Browser-Erweiterung"})
                nav_text = [button.text() for button in window.nav_buttons]
                if nav_text != [
                    "Herunterladen", "Verlauf", "Anmeldungen",
                    "Abonnements", "Browser-Erweiterung", "Einstellungen",
                ]:
                    raise RuntimeError(
                        f"German navigation catalogue did not render: {nav_text}"
                    )
                # The rail is the one surface every locale translates, so a
                # rail-only assertion passes against a catalogue that has
                # nothing else in it — which is exactly what nine of the
                # eleven locales still are. Assert body copy on EVERY page,
                # so an English string surviving anywhere fails here.
                for page, expected_german in (
                    ("Download", {"Ausschnitt von",
                                  "Ausschnitte gelten nur für einen einzelnen Link."}),
                    ("History", {"Verlauf", "Datei", "Gespeichert ab"}),
                    ("Sign-ins", {"Anmeldungen", "Website-Anmeldung hinzufügen",
                                  "Lesen aus"}),
                    ("Subscriptions", {"Abonnements", "Neues Abonnement"}),
                    ("Browser extension", {"Browser-Erweiterung", "Kopplung",
                                           "Laufzeit"}),
                    ("Settings", {"Einstellungen", "Formatwünsche",
                                  "Dateinamenvorlage", "Aktion"}),
                ):
                    select_page(window, page)
                    scroll_current_page_to_top(window)
                    if page == "Download":
                        window.btn_quick_options.setChecked(True)
                        app.processEvents()
                    assert_visible_text(window, expected_german)
                select_page(window, "Browser extension")
            elif scenario in LOCALE_SCENARIOS:
                source_nav = [
                    "Download", "History", "Sign-ins", "Subscriptions",
                    "Browser extension", "Settings",
                ]
                nav_text = [button.text() for button in window.nav_buttons]
                if nav_text == source_nav:
                    raise RuntimeError(
                        f"{LOCALE_SCENARIOS[scenario]} navigation catalogue did not render"
                    )
                if scenario in {"dashboard-japanese", "dashboard-korean", "dashboard-chinese"}:
                    for button in window.nav_buttons:
                        if button.fontMetrics().horizontalAdvance(button.text()) > max(
                                0, button.width() - 36
                        ):
                            raise RuntimeError(
                                f"CJK navigation text is clipped: {button.text()!r}"
                            )
                for page in (
                    "Download", "History", "Sign-ins", "Subscriptions",
                    "Browser extension", "Settings",
                ):
                    select_page(window, page)
                    scroll_current_page_to_top(window)
                select_page(window, "Browser extension")
            elif scenario == "dashboard-starting":
                window.status_label.setText("Starting")
                window.status_label.setProperty("tone", "warning")
                window.status_dot.setProperty("tone", "warning")
                window.server_badge.setProperty("tone", "warning")
                window.dash_status.setText("Starting local server")
                window.dash_hint.setText("Checking the local API and installed tools…")
                window._set_readiness("server", "Starting", "warning")
                for status_widget in (
                        window.status_label, window.status_dot, window.server_badge):
                    app_module.repolish(status_widget)
                # "Checking" used to come from the tool readiness rows that
                # shared this page. They live with the paste box now, so the
                # server page's own hint carries the in-flight wording.
                assert_visible_text(window, {
                    "Starting", "Starting local server",
                    "Checking the local API and installed tools…",
                })
            elif scenario in {
                    "dashboard-online", "dashboard-light-theme",
                    "dashboard-log-populated"}:
                window.status_label.setText("Running")
                window.status_label.setProperty("tone", "success")
                window.status_dot.setProperty("tone", "success")
                window.dash_status.setText("Server online")
                window.dash_hint.setText("Local only · ready for Astra Deck")
                window.server_badge.setProperty("tone", "success")
                window.btn_startstop.setText("Stop Server")
                for status_widget in (
                        window.status_label, window.status_dot, window.server_badge):
                    app_module.repolish(status_widget)
                window._set_readiness("server", "Running", "success")
                window._set_readiness("ytDlp", "2026.07.04", "success")
                window._set_readiness("ffmpeg", "7.1", "success")
                window._set_readiness("deno", "Deno 2.7.11", "success")
                window._set_readiness("sabr", "Supported", "success")
                assert_visible_text(window, {"Running", "Server online"})
                # Tool versions render on the Download page now, so prove
                # they reached the widgets there rather than asserting them
                # on a page that no longer carries those rows.
                select_page(window, "Download")
                assert_visible_text(window, {"2026.07.04", "7.1", "Deno 2.7.11"})
                select_page(window, "Browser extension")
                if scenario == "dashboard-log-populated":
                    window._append_log("Browser extension paired with the local server.")
                    window._append_log("Download request accepted from Astra Deck.")
                    window._restore_log_view()
                    scroll_current_page_to_bottom(window)
                    if not window.log_text.isVisible():
                        raise RuntimeError("Populated server log is hidden")
                    if "Download request accepted" not in window.log_text.toPlainText():
                        raise RuntimeError("Populated server log text is missing")
            else:
                window.status_label.setText("Server error")
                window.status_label.setProperty("tone", "danger")
                window.status_dot.setProperty("tone", "danger")
                window.server_badge.setProperty("tone", "danger")
                for status_widget in (
                        window.status_label, window.status_dot, window.server_badge):
                    app_module.repolish(status_widget)
                window.dash_status.setText("Server unavailable")
                window.dash_hint.setText(
                    "Server failed to start. The configured port is already in use."
                )
                degraded = {
                    "server": ("Error", "danger"),
                    "ytDlp": ("Missing", "danger"),
                    "ffmpeg": ("7.1", "success"),
                    "deno": ("Update Deno", "warning"),
                    "sabr": ("Limited", "warning"),
                }
                for key, (text, tone) in degraded.items():
                    window._set_readiness(key, text, tone)
                assert_visible_text(
                    window, {"Server error", "Server unavailable"}
                )
                # The degraded tool rows render on the Download page.
                select_page(window, "Download")
                assert_visible_text(window, {"Missing", "Update Deno"})
                select_page(window, "Browser extension")
            capture_window(window, scenario)

        def check_rtl_hero_proportions(window):
            """The page must actually mirror, and mirroring must not resize.

            Measured rather than assumed: the Download button is narrower
            under Arabic than under English, but only because the translated
            word is shorter — it sits at its size hint in both directions. So
            the property worth pinning is not its width, it is that the row
            reversed, the rail moved, and the paste box still dominates.
            """
            button = window.btn_quick_download
            field = window.quick_download_url
            rail = window.nav_buttons[0]
            if button.x() >= field.x():
                raise RuntimeError(
                    "RTL did not reverse the hero row: the Download button is "
                    f"at x={button.x()} against a paste box at x={field.x()}"
                )
            rail_x = rail.mapTo(window, rail.rect().topLeft()).x()
            if rail_x < window.width() / 2:
                raise RuntimeError(
                    f"RTL left the navigation rail on the left at x={rail_x}"
                )
            if button.width() < button.sizeHint().width():
                raise RuntimeError(
                    f"RTL collapsed the Download button to {button.width()}px "
                    f"below its {button.sizeHint().width()}px hint"
                )
            if field.width() < button.width() * 2:
                raise RuntimeError(
                    f"RTL starved the paste box: {field.width()}px against a "
                    f"{button.width()}px button"
                )

        def capture_download_state(window, manager):
            seed_download_matrix(manager)
            if scenario == "downloads-clipboard-staged":
                manager.downloads = {}
                manager._running_ids.clear()
            elif scenario == "downloads-recovery-terminal":
                manager.downloads = {
                    dl_id: manager.downloads[dl_id]
                    for dl_id in ("paused", "needsauth", "failed", "complete")
                }
                manager._running_ids.clear()
            elif scenario == "downloads-rate-limited":
                limited = manager.downloads["failed"]
                limited.error = "HTTP 429: Too Many Requests"
                limited.error_code = "rate-limited"
                limited.error_advice = (
                    "This site is paused for the rest of its retry window."
                )
                limited.error_action = "slow-down-and-retry"
                manager.downloads = {
                    dl_id: manager.downloads[dl_id]
                    for dl_id in ("failed",)
                }
                manager._host_backoffs["youtube.com"] = {
                    "until": time.monotonic() + 125,
                    "retry_after": 125,
                    "failures": 1,
                }
                manager._running_ids.clear()
            elif scenario == "downloads-quarantine":
                manager.downloads = {}
                manager._running_ids.clear()
                quarantine_path = Path(temp_dir) / "state" / "queue.json"
                window._dependencies["quarantined_state_files"] = lambda: [{
                    "path": str(quarantine_path),
                    "backup": str(quarantine_path) + ".corrupt-fixture",
                }]
                window._refresh_quarantine_notice()
            elif scenario == "downloads-paused-intake":
                if not manager.pause_intake():
                    raise RuntimeError("Could not pause the queue for the fixture")
            elif scenario == "downloads-queue-full":
                manager.capacity = lambda: {
                    "running": 0,
                    "runningLimit": 3,
                    "pending": 200,
                    "total": 200,
                    "totalLimit": 200,
                    "available": 0,
                    "intakePaused": False,
                }
                manager.start_download = lambda **_kwargs: (
                    None,
                    "Download queue is full (200/200). Remove a queued item before adding another.",
                )
            elif scenario == "downloads-format-probe":
                def hold_format_probe(_url):
                    time.sleep(5)
                    return {}, ""

                manager.list_formats = hold_format_probe
            elif scenario == "downloads-first-run":
                manager.downloads = {}
                manager._running_ids.clear()
            elif scenario == "reflow-900x620-hidpi-large-font":
                manager.downloads = {
                    dl_id: manager.downloads[dl_id]
                    for dl_id in ("active", "needsauth", "failed", "complete")
                }
            window._downloads_signature = None
            window._update_ui()
            select_page(window, "Download")
            if scenario == "downloads-first-run":
                if window.first_run_panel.isHidden():
                    raise RuntimeError("First-run panel is not visible on Download")
                if not window.first_run_confirm.isVisible():
                    raise RuntimeError("First-run destination confirmation is unavailable")
                assert_visible_text(window, {
                    "Welcome to Astra Downloader",
                    "Video download folder",
                    "Confirm a folder before your first download.",
                })
                if window.first_run_pair.text() != "Open extension pairing":
                    raise RuntimeError("First-run pairing action is not visible")
                window._start_server = lambda: None
                window._open_first_run_pairing()
                if window.tabs.currentIndex() != window._page_names.index(
                        "Browser extension"):
                    raise RuntimeError("First-run pairing did not open the extension page")
                select_page(window, "Download")
            elif scenario == "downloads-clipboard-staged":
                window.config.set("ClipboardLinkGrabber", True)
                window.tray.hide()
                window._handle_clipboard_change(
                    "https://www.youtube.com/watch?v=clipboard01"
                )
                app.processEvents()
                scroll_current_page_to_top(window)
                assert_visible_text(
                    window,
                    {
                        "Copied video link staged. Review the options, then choose Add to queue.",
                    },
                )
                if window.quick_download_url.text() != (
                    "https://www.youtube.com/watch?v=clipboard01"
                ):
                    raise RuntimeError("Clipboard fixture did not stage the copied URL")
                if manager.downloads:
                    raise RuntimeError("Clipboard fixture enqueued a download without confirmation")
            elif scenario == "downloads-active-pending":
                scroll_current_page_to_top(window)
                assert_visible_text(window, {"Downloading documentary", "Queued lecture"})
            elif scenario == "downloads-advanced-options":
                window.btn_quick_options.setChecked(True)
                app.processEvents()
                scroll_current_page_to_top(window)
                if not window.quick_download_advanced.isVisible():
                    raise RuntimeError("Advanced download controls did not open")
                if window.quick_download_video_password.placeholderText() != (
                        "Video password (one link only, optional)"):
                    raise RuntimeError("Advanced password guidance is missing")
                assert_visible_text(
                    window,
                    {"Clip from", "Save as"},
                )
            elif scenario == "downloads-health-error":
                for key in window.preflight_values:
                    window._set_preflight_row(key, "ok")
                window._set_preflight_row("javascript-runtime", "error")
                window._update_preflight_summary()
                app.processEvents()
                scroll_current_page_to_top(window)
                if not window.preflight_details.isVisible():
                    raise RuntimeError("Failing download health checks stayed collapsed")
                assert_visible_text(
                    window,
                    {"One check needs repair. Open the checks to see the fix."},
                )
            elif scenario == "downloads-subtitles-only":
                # Subtitles is a third download type, not a settings toggle.
                # Neither picker beside it describes a subtitle, so both are
                # disabled and the page says what will actually be fetched.
                window.config.update({
                    "SubtitleMode": "manual",
                    "SubLangs": "en,es",
                    "SubtitleFormat": "srt",
                })
                combo = window.quick_download_type
                index = combo.findData("subtitles")
                if index < 0:
                    raise RuntimeError("The Subtitles download type is missing")
                combo.setCurrentIndex(index)
                window._sync_quick_download_options()
                app.processEvents()
                scroll_current_page_to_top(window)
                if window.quick_download_format.isEnabled():
                    raise RuntimeError(
                        "A container format is meaningless for a subtitle"
                    )
                if window.quick_download_quality.isEnabled():
                    raise RuntimeError(
                        "A video quality is meaningless for a subtitle"
                    )
                assert_visible_text(window, {
                    "Downloads creator subtitles only in en,es as SRT, "
                    "without the video. Change this under Settings, "
                    "Post-processing."
                })
            else:
                if scenario == "downloads-arabic-rtl":
                    if app.layoutDirection() != Qt.LayoutDirection.RightToLeft:
                        raise RuntimeError(
                            "Arabic fixture did not flip the layout direction"
                        )
                    check_rtl_hero_proportions(window)
                if scenario == "reflow-900x620-hidpi-large-font":
                    window.resize(900, 620)
                    app.setFont(QFont("Segoe UI", 12))
                    window.setFont(app.font())
                    window.btn_quick_options.setChecked(True)
                    window.style().unpolish(window)
                    window.style().polish(window)
                    app.processEvents()
                    if window.size().width() != 900 or window.size().height() != 620:
                        raise RuntimeError("Companion minimum-size fixture did not reach 900x620")
                    assert_download_options_reflow(window)
                scroll_current_page_to_top(window)
                if scenario == "downloads-recovery-terminal":
                    assert_visible_text(
                        window,
                        {
                            "Recovered interview",
                            "Members-only archive",
                            "Unavailable livestream",
                            "Finished tutorial",
                        },
                    )
                elif scenario == "downloads-rate-limited":
                    rendered = visible_text(window)
                    if not any("retry in" in text.lower() for text in rendered):
                        raise RuntimeError("Rate-limited queue item has no host countdown")
                    if not any("This host is paused" in text for text in rendered):
                        raise RuntimeError("Rate-limited recovery callout is missing")
                elif scenario == "downloads-quarantine":
                    if not window.quarantine_panel.isVisible():
                        raise RuntimeError("Download quarantine panel is not visible")
                    if "queue.json could not be read" not in window.quarantine_notice.text():
                        raise RuntimeError("Download quarantine notice is incomplete")
                elif scenario == "downloads-paused-intake":
                    if window.btn_queue_pause.text() != "Resume queue":
                        raise RuntimeError("Paused intake fixture did not expose Resume queue")
                    if not window.btn_queue_pause.toolTip().startswith(
                            "Resume pending downloads explicitly"
                    ):
                        raise RuntimeError("Paused intake fixture has the wrong recovery hint")
                elif scenario == "downloads-queue-full":
                    window.quick_download_url.setText(
                        "https://www.youtube.com/watch?v=queuefull01"
                    )
                    window._start_quick_download()
                    if window.queue_capacity_badge.text() != "200 / 200 jobs":
                        raise RuntimeError("Queue-full fixture did not expose the full capacity")
                    if "Download queue is full" not in window.quick_download_status.text():
                        raise RuntimeError("Queue-full fixture did not surface the rejection")
                elif scenario == "downloads-format-probe":
                    window.quick_download_url.setText(
                        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                    )
                    window._probe_quick_download_formats()
                    if not window._format_probe_in_flight:
                        raise RuntimeError("Format-probe fixture did not stay in flight")
                    if window.quick_download_status.text() != "Looking up available formats…":
                        raise RuntimeError("Format-probe fixture did not expose its pending state")
            capture_window(
                window, scenario,
                dpr=SCALE_SCENARIOS.get(scenario, 1.0),
            )
            if scenario == "reflow-900x620-hidpi-large-font":
                output = QImage(str(OUTPUT_DIR / f"{scenario}.png"))
                if output.width() != 1800 or output.height() != 1240:
                    raise RuntimeError("High-DPI fixture was not captured at 2x resolution")

        def capture_history_state(window, history):
            if scenario == "history-unreadable":
                history_path = history._resolve_path()
                window._dependencies["quarantined_state_files"] = lambda: [{
                    "path": str(history_path),
                    "backup": str(history_path) + ".corrupt-fixture",
                }]
            elif scenario == "history-pagination":
                seed_history(history, count=55)
            else:
                seed_history(history)
            select_page(window, "History")
            window._refresh_history()
            if scenario == "history-unreadable":
                assert_visible_text(window, {"History could not be read", "History unavailable"})
            elif scenario == "history-cleared-undo":
                window._clear_history()
                app.processEvents()
                QTest.qWait(40)
                assert_visible_text(window, {"No downloads yet"})
                if not window.btn_undo_clear_history.isVisible():
                    raise RuntimeError("History clear fixture does not expose Undo")
            elif scenario == "history-restored":
                window._clear_history()
                window._undo_clear_history()
                app.processEvents()
                QTest.qWait(40)
                assert_visible_text(
                    window, {"Keyboard navigation deep dive", "Offline media workflow"}
                )
            elif scenario == "history-filter-empty":
                window.history_search.setText("does-not-match")
                window._refresh_history()
                app.processEvents()
                QTest.qWait(60)
                app.processEvents()
                assert_visible_text(window, {"No matching downloads"})
            elif scenario == "history-pagination":
                if not window.btn_history_next.isEnabled():
                    raise RuntimeError("History pagination fixture has no next page")
                window._move_history_page(1)
                if not window.btn_history_prev.isEnabled():
                    raise RuntimeError("History pagination fixture did not enable previous")
                if "51 to 55 of 55 filtered" not in window.history_meta.text():
                    raise RuntimeError(
                        f"History pagination metadata is wrong: {window.history_meta.text()!r}"
                    )
            else:
                assert_visible_text(
                    window, {"Keyboard navigation deep dive", "Offline media workflow"}
                )
            capture_window(window, scenario)

        def capture_subscription_state(window):
            manager = window._subscription_manager()
            if scenario == "subscriptions-empty":
                manager._records = []
            elif scenario == "subscriptions-error":
                def failing_snapshot():
                    raise RuntimeError("fixture subscription read failure")

                manager.snapshot = failing_snapshot
            elif scenario == "subscriptions-disabled":
                manager._records[0]["enabled"] = False
                manager._records[0]["nextScanAt"] = None
            select_page(window, "Subscriptions")
            if scenario == "subscriptions-scanning":
                window._subscription_scan_pending.add("sub-fixture")
                window._refresh_subscriptions(force=True)
                app.processEvents()
                if not any("scanning now" in text for text in visible_text(window)):
                    raise RuntimeError("Subscription scan fixture did not expose its active state")
            elif scenario == "subscriptions-empty":
                assert_visible_text(window, {"No scheduled subscriptions"})
            elif scenario in {"subscriptions-populated", "subscriptions-light-theme"}:
                assert_visible_text(window, {"Astra channel"})
                if not any("Every 60 min" in text for text in visible_text(window)):
                    raise RuntimeError("Subscription fixture did not render its scan interval")
            elif scenario == "subscriptions-error":
                assert_visible_text(window, {
                    "Subscriptions unavailable",
                    "Could not read subscriptions: fixture subscription read failure",
                })
            elif scenario == "subscriptions-filter-empty":
                window.subscription_search.setText("does-not-match")
                window._refresh_subscriptions(force=True)
                app.processEvents()
                QTest.qWait(60)
                app.processEvents()
                assert_visible_text(window, {"No subscriptions match these filters"})
            elif scenario == "subscriptions-disabled":
                index = window.subscription_status_filter.findData("disabled")
                if index < 0:
                    raise RuntimeError("Subscription disabled filter is missing")
                window.subscription_status_filter.setCurrentIndex(index)
                window._refresh_subscriptions(force=True)
                assert_visible_text(window, {"Astra channel"})
                if not any("paused" in text for text in visible_text(window)):
                    raise RuntimeError("Disabled subscription fixture did not show paused state")
                if window.subscription_status_filter.currentData() != "disabled":
                    raise RuntimeError("Disabled subscription filter did not stay selected")
            else:
                raise RuntimeError(f"Unhandled subscription fixture: {scenario}")
            capture_window(window, scenario)

        def capture_site_login_state(window):
            select_page(window, "Sign-ins")
            if window.site_login_profile.width() < 160:
                raise RuntimeError(
                    "Browser profile field is clipped in the standard viewport"
                )
            store = window.dl_manager.site_logins
            if scenario == "site-logins-error":
                def failing_entries():
                    raise RuntimeError("fixture sign-in store failure")

                store.entries = failing_entries
                window._refresh_site_logins(force=True)
                app.processEvents()
                QTest.qWait(60)
                app.processEvents()
                assert_visible_text(window, {
                    "Site sign-ins are unavailable in this session.",
                    "Could not read stored sign-ins: fixture sign-in store failure",
                })
            elif scenario == "site-logins-empty":
                window._refresh_site_logins(force=True)
                app.processEvents()
                QTest.qWait(60)
                app.processEvents()
                assert_visible_text(window, {"No stored sign-ins"})
            else:
                # Fixture only: a stored sign-in with no cookie values anywhere
                # in the rendered page, which is the property this view must hold.
                store.import_netscape_text(
                    "x.com",
                    ".x.com	TRUE	/	TRUE	2000000000	auth_token	fixture-value",
                )
                if scenario == "site-logins-filter-empty":
                    window.site_login_search.setText("does-not-match")
                window._refresh_site_logins(force=True)
                app.processEvents()
                QTest.qWait(60)
                app.processEvents()
                if scenario == "site-logins-filter-empty":
                    assert_visible_text(window, {"No sign-ins match these filters"})
                else:
                    assert_visible_text(window, {"x.com"})
                rendered = " ".join(visible_text(window))
                if "fixture-value" in rendered or "auth_token" in rendered:
                    raise RuntimeError("Cookie values must never render in the sign-ins view")
            capture_window(window, scenario)

        def capture_settings_state(window, config):
            select_page(window, "Settings")
            expected = ""
            if scenario == "settings-dirty":
                window.cfg_dl_path.setText(str(Path(temp_dir) / "Videos" / "Edited"))
                expected = "Unsaved changes"
            elif scenario == "settings-light-theme":
                expected = "Settings"
            elif scenario == "settings-bundle-imported":
                # Drive the real round trip: export the live settings, change
                # them, import the bundle back, and check the FORM shows the
                # restored values. A stale form is not cosmetic here — the
                # next Save would write the pre-import values back over it.
                bundle_path = Path(temp_dir) / "bundle.json"
                window.cfg_sublangs.setText("de,fr")
                window.cfg_subs.setChecked(True)
                window._save_settings()
                app.processEvents()
                with mock.patch.object(
                    app_module.QFileDialog, "getSaveFileName",
                    staticmethod(lambda *a, **k: (str(bundle_path), "")),
                ):
                    if not window._export_settings_bundle():
                        raise RuntimeError("Export refused to write the bundle")
                if not bundle_path.exists():
                    raise RuntimeError("The bundle was not written")
                payload = json.loads(bundle_path.read_text(encoding="utf-8"))
                settings_json = json.dumps(payload.get("settings", {}))
                token = str(config.get("ServerToken") or "")
                if "ServerToken" in settings_json or (token and token in json.dumps(payload)):
                    raise RuntimeError("The bundle leaked the API token")
                # Move the settings away from what the bundle holds.
                window.cfg_sublangs.setText("en")
                window.cfg_subs.setChecked(False)
                window._save_settings()
                app.processEvents()
                if config.get("SubLangs") != "en":
                    raise RuntimeError("Fixture failed to change the setting")
                with mock.patch.object(
                    app_module.QFileDialog, "getOpenFileName",
                    staticmethod(lambda *a, **k: (str(bundle_path), "")),
                ):
                    if not window._import_settings_bundle():
                        raise RuntimeError("Import refused the bundle it wrote")
                app.processEvents()
                if config.get("SubLangs") != "de,fr":
                    raise RuntimeError(
                        f"Import did not restore the setting: {config.get('SubLangs')}"
                    )
                if window.cfg_sublangs.text() != "de,fr":
                    raise RuntimeError(
                        "The form still shows the pre-import value; the next "
                        "Save would undo the import"
                    )
                if not window.cfg_subs.isChecked():
                    raise RuntimeError("The form checkbox did not refresh")
                current = window.tabs.currentWidget()
                scroll = (current if isinstance(current, QScrollArea)
                          else current.findChild(QScrollArea))
                if scroll is not None:
                    scroll.ensureWidgetVisible(window.btn_export_settings, 0, 200)
                    app.processEvents()
                    QTest.qWait(40)
                status = window.settings_status.text()
                if not status.startswith("Imported "):
                    raise RuntimeError(f"Import reported {status!r}")
                if "changed settings" not in status:
                    raise RuntimeError(
                        f"The import must say what it changed: {status!r}"
                    )
                # Pin the exact sentence so the capture proves it is legible
                # on the page, not merely present in a variable.
                expected = status
            elif scenario == "settings-subtitles":
                # The subtitle controls sit mid-page, so every other settings
                # capture scrolls straight past them. Turn them on and bring
                # them into view: this is the only shot that proves the track
                # picker, the format picker and the language checkboxes
                # actually lay out at the shipped width.
                window.cfg_subs.setChecked(True)
                mode = window.cfg_subtitle_mode
                mode.setCurrentIndex(max(0, mode.findData("manual")))
                fmt = window.cfg_subtitle_format
                fmt.setCurrentIndex(max(0, fmt.findData("srt")))
                window.cfg_sublangs.setText("en,es,zh-Hans")
                window._sync_sublang_checkboxes(window.cfg_sublangs.text())
                app.processEvents()
                current = window.tabs.currentWidget()
                scroll = (current if isinstance(current, QScrollArea)
                          else current.findChild(QScrollArea))
                if scroll is not None:
                    scroll.ensureWidgetVisible(window.cfg_sublangs, 0, 220)
                    app.processEvents()
                    QTest.qWait(40)
                ticked = [
                    box._sublang_code for box in window._sublang_boxes
                    if box.isChecked()
                ]
                if ticked != ["en", "es", "zh-Hans"]:
                    raise RuntimeError(
                        f"Language checkboxes do not match the field: {ticked}"
                    )
                if not window.cfg_subtitle_mode.isVisible():
                    raise RuntimeError("The subtitle track picker is not visible")
                expected = "Subtitle languages"
            elif scenario == "settings-fallback-port":
                # A bind conflict binds a fallback port for the session only.
                # The dashboard shows it; the spinbox keeps the configured
                # port, so the page has to explain the difference.
                config.set_session("ServerPort", 9761)
                window._sync_connection_ui()
                if window.cfg_port.value() != 9751:
                    raise RuntimeError("Session fallback must not move the configured port")
                expected = (
                    "Port 9751 was unavailable at startup; bound to fallback "
                    "port 9761 for this session. Restart to retry 9751."
                )
            elif scenario == "settings-invalid":
                window.cfg_outtmpl.setText("../%(title)s")
                window._save_settings()
                if window.cfg_outtmpl.property("state") != "error":
                    raise RuntimeError("Invalid settings fixture did not highlight the field")
                window._render_focus_target = window.cfg_outtmpl
                expected = "Check the highlighted fields before saving."
            elif scenario == "settings-search-active":
                window.settings_filter.setText("proxy")
                app.processEvents()
                if not window.cfg_proxy.isVisible():
                    raise RuntimeError("Settings search did not reveal the proxy field")
                if window.cfg_dl_path.isVisible():
                    raise RuntimeError("Settings search left an unrelated field visible")
                expected = "Connection"
            elif scenario == "settings-invalid-site-profiles":
                window.cfg_site_profiles.setPlainText("{not valid JSON")
                window._save_settings()
                if window.cfg_site_profiles.property("state") != "error":
                    raise RuntimeError(
                        "Invalid site-profile JSON fixture did not highlight the field"
                    )
                window._render_focus_target = window.cfg_site_profiles
                expected = "Named site profiles"
            elif scenario == "settings-save-failed":
                config.update = lambda _mapping: False
                window._save_settings()
                expected = (
                    "Could not save settings. Nothing changed; "
                    "check disk permissions and retry."
                )
            else:
                window.btn_check_updates.setEnabled(False)
                window.btn_check_updates.setText("Checking…")
                expected = (
                    "Checking yt-dlp. The verified current copy stays available "
                    "until the update passes."
                )
                window._show_settings_status(expected, "warning")
            if scenario in {"settings-fallback-port", "settings-light-theme"}:
                # The Connection card is the top of the page.
                scroll_current_page_to_top(window)
            elif scenario == "settings-search-active":
                current = window.tabs.currentWidget()
                scroll = (current if isinstance(current, QScrollArea)
                          else current.findChild(QScrollArea))
                if scroll is not None:
                    scroll.ensureWidgetVisible(window.cfg_proxy, 0, 160)
                    app.processEvents()
                    QTest.qWait(40)
            elif scenario == "settings-invalid-site-profiles":
                current = window.tabs.currentWidget()
                scroll = (current if isinstance(current, QScrollArea)
                          else current.findChild(QScrollArea))
                if scroll is not None:
                    scroll.ensureWidgetVisible(window.cfg_site_profiles, 0, 160)
                    app.processEvents()
                    QTest.qWait(40)
            elif scenario not in ("settings-subtitles", "settings-bundle-imported"):
                # That scenario already scrolled to the controls it exists to
                # show; scrolling to the bottom here would hide them again.
                scroll_current_page_to_bottom(window)
            assert_visible_text(window, {expected})
            capture_window(
                window, scenario,
                dpr=SCALE_SCENARIOS.get(scenario, 1.0),
            )

        def capture_modal_dialog(output_name, expected_title, trigger, validate):
            dialog_output = OUTPUT_DIR / f"{output_name}.png"

            def capture_dialog():
                dialog = app.activeModalWidget()
                if dialog is None or dialog.windowTitle() != expected_title:
                    raise RuntimeError(f"{expected_title} dialog did not open")
                validate(dialog)
                dialog.repaint()
                app.processEvents()
                QTest.qWait(80)
                image = dialog.grab().toImage()
                if image.isNull() or image.deviceIndependentSize().toSize() != dialog.size():
                    raise RuntimeError(
                        f"Dialog capture geometry is invalid for {output_name}"
                    )
                if not image.save(str(dialog_output), "PNG"):
                    raise RuntimeError(f"Failed to save {output_name} render")
                print(f"captured {output_name}", flush=True)
                dialog.reject()

            QTimer.singleShot(150, capture_dialog)
            trigger()

        def capture_diagnostics(window):
            def validate(dialog):
                preview = dialog.findChild(app_module.QTextEdit)
                if preview is None or '"schemaVersion": 1' not in preview.toPlainText():
                    raise RuntimeError(
                        "Diagnostics review does not expose the redacted payload"
                    )

            capture_modal_dialog(
                scenario,
                "Review Diagnostics",
                window._copy_diagnostics,
                validate,
            )

        def capture_playlist_review(window):
            preview = {
                "title": "Design Systems Field Notes",
                "channel": "Astra Studio",
                "items": [
                    {"index": 1, "title": "Build a dependable spacing scale", "duration": 612},
                    {"index": 2, "title": "Keyboard focus that survives every theme", "duration": 845},
                    {"index": 3, "title": "Writing recovery states people can use", "duration": 497},
                    {"index": 4, "title": "Testing desktop layouts at minimum size", "duration": 731},
                ],
            }

            def trigger():
                dialog = app_module.PlaylistStagingDialog(window, preview)
                dialog.exec()

            def validate(dialog):
                if len(dialog.checkboxes) != 4:
                    raise RuntimeError("Playlist review did not render all videos")
                if not all(cb.accessibleName() for cb, _item in dialog.checkboxes):
                    raise RuntimeError("Playlist review checkboxes lack accessible names")
                if dialog.btn_download.text() != "Download selected (4)":
                    raise RuntimeError(
                        "Playlist review count is not reflected in its action"
                    )

            capture_modal_dialog(
                scenario, "Review Playlist", trigger, validate
            )

        def capture_command_review(window, manager):
            download = fixture_download(
                manager,
                "command",
                "Design Systems Field Notes",
                "complete",
                1,
            )
            download.command_args = [
                "yt-dlp.exe",
                "--format",
                "bestvideo+bestaudio",
                "--output",
                r"C:\Users\<redacted>\Videos\%(title)s.%(ext)s",
                "<redacted-url>",
            ]

            def validate(dialog):
                preview = dialog.findChild(app_module.QTextEdit)
                if preview is None or "--format" not in preview.toPlainText():
                    raise RuntimeError(
                        "Command review does not expose the redacted command"
                    )
                copy_button = next(
                    (
                        button
                        for button in dialog.findChildren(app_module.QPushButton)
                        if button.text() == "Copy command"
                    ),
                    None,
                )
                if copy_button is None:
                    raise RuntimeError("Command review has no copy action")
                copy_button.click()
                app.processEvents()
                if "Copied to clipboard." not in visible_text(dialog):
                    raise RuntimeError(
                        "Copy command action has no visible confirmation"
                    )

            capture_modal_dialog(
                scenario,
                "yt-dlp Command",
                lambda: window._show_download_command_dialog(download),
                validate,
            )

        capture_failures = []

        def capture_all():
            try:
                window, config, history, manager = make_window()
                if scenario.startswith("dashboard-"):
                    capture_dashboard_state(window)
                elif scenario.startswith("downloads-") or scenario.startswith("reflow-"):
                    capture_download_state(window, manager)
                elif scenario.startswith("history-"):
                    capture_history_state(window, history)
                elif scenario.startswith("subscriptions-"):
                    capture_subscription_state(window)
                elif scenario.startswith("site-logins-"):
                    capture_site_login_state(window)
                elif scenario.startswith("settings-"):
                    capture_settings_state(window, config)
                elif scenario.startswith("diagnostics-review"):
                    capture_diagnostics(window)
                elif scenario.startswith("playlist-review"):
                    capture_playlist_review(window)
                elif scenario.startswith("command-review"):
                    capture_command_review(window, manager)
                else:
                    raise RuntimeError(f"Unhandled companion fixture: {scenario}")
                output = OUTPUT_DIR / f"{scenario}.png"
                if not output.exists() or output.stat().st_size < 10_000:
                    raise RuntimeError(
                        f"Companion render is missing or unexpectedly small: {output}"
                    )
            except BaseException as error:
                capture_failures.append(error)
                traceback.print_exc()
            finally:
                if "window" in locals():
                    if hold_seconds <= 0:
                        window.hide()
                        retained_windows.append(window)
                if hold_seconds > 0:
                    QTimer.singleShot(int(hold_seconds * 1000), app.quit)
                else:
                    app.quit()

        QTimer.singleShot(0, capture_all)
        exit_code = app.exec()
        if capture_failures:
            raise capture_failures[0]
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
