"""PyQt presentation helpers and lazy legacy GUI compatibility boundary."""

import os
import csv
import hmac
import json
import math
import queue
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QByteArray, QCoreApplication, QEasingCurve, QObject, QPropertyAnimation, QSize,
    QThread, QTimer, Qt, Signal,
)
from PySide6.QtGui import QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenu, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSystemTrayIcon, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

try:
    from ._compat import make_legacy_resolver
except ImportError:  # Flat source-path compatibility.
    from _compat import make_legacy_resolver

try:
    from .config import default_download_path
except ImportError:  # Flat source-path compatibility.
    from config import default_download_path

try:
    from .i18n import ADVERTISED_LOCALES
except ImportError:  # Flat source-path compatibility.
    from i18n import ADVERTISED_LOCALES

try:
    from .gui_download_page import DownloadPageMixin, PREFLIGHT_ROW_SPECS
    from .gui_extension_page import ExtensionPageMixin
    from .gui_history_page import HistoryPageMixin
    from .gui_site_logins_page import SiteLoginsPageMixin
    from .gui_sites_page import SitesPageMixin
    from .gui_subscriptions_page import SubscriptionsPageMixin
    from .gui_settings_page import SettingsPageMixin
except ImportError:  # Flat source-path compatibility.
    from gui_download_page import DownloadPageMixin, PREFLIGHT_ROW_SPECS
    from gui_extension_page import ExtensionPageMixin
    from gui_history_page import HistoryPageMixin
    from gui_site_logins_page import SiteLoginsPageMixin
    from gui_sites_page import SitesPageMixin
    from gui_subscriptions_page import SubscriptionsPageMixin
    from gui_settings_page import SettingsPageMixin


__all__ = (
    "MainWindow", "SetupWorker", "FolderPickerService", "repolish",
    "make_label", "make_section_label", "make_divider", "make_card",
    "tr_format",
    "make_stat", "make_empty_state", "STYLESHEET", "_folder_pick_q",
    "run_uninstall", "is_safe_install_dir_for_removal",
    "spawn_delayed_install_dir_removal", "check_single_instance", "main",
    "make_status_badge", "download_status_tone", "human_status",
    "format_duration",
    "sanitize_csv_cell",
    "ReadinessProbe",
    "SetupWorkerCore",
    "MainWindowCore",
    "GUI_ACCESSIBILITY_COLORS", "system_reduced_motion_enabled",
    "set_gui_theme", "set_line_icon", "refresh_line_icons",
    "default_download_path",
    "filter_subscription_records", "filter_site_login_entries",
)



def system_reduced_motion_enabled():
    """Honor the Windows animation accessibility preference.

    ``ASTRA_REDUCED_MOTION`` is an explicit test/automation override; the
    production path reads SPI_GETCLIENTAREAANIMATION, which is disabled by
    Windows when the user turns off UI animations.
    """
    override = str(os.environ.get("ASTRA_REDUCED_MOTION", "")).strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    if os.name != "nt":
        return False
    try:
        import ctypes
        animations_enabled = ctypes.c_bool(True)
        success = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(animations_enabled), 0
        )
        return bool(success) and not animations_enabled.value
    except Exception:
        # reason: an unavailable SystemParametersInfoW means no reduced-motion preference to honour
        return False




# Shared page primitives live outside the window shell so extracted page
# modules can import them without reaching back into the composition root.
try:
    from . import gui_support as _gui_support
    from .gui_support import (
        GUI_ACCESSIBILITY_COLORS, SUBTITLE_LANGUAGE_CHOICES,
        describe_rejected_links, download_status_tone,
        filter_site_login_entries, filter_subscription_records,
        format_duration, human_status, make_card, make_divider,
        make_empty_state, make_label, make_line_icon, make_section_label,
        make_stat, make_state_label, make_status_badge, make_vertical_divider,
        refresh_line_icons, repolish, sanitize_csv_cell, set_gui_theme,
        short_error_text,
        set_line_icon, set_status_tone, tr, tr_format,
    )
except ImportError:  # Flat source-path compatibility.
    import gui_support as _gui_support
    from gui_support import (
        GUI_ACCESSIBILITY_COLORS, SUBTITLE_LANGUAGE_CHOICES,
        describe_rejected_links, download_status_tone,
        filter_site_login_entries, filter_subscription_records,
        format_duration, human_status, make_card, make_divider,
        make_empty_state, make_label, make_line_icon, make_section_label,
        make_stat, make_state_label, make_status_badge, make_vertical_divider,
        refresh_line_icons, repolish, sanitize_csv_cell, set_gui_theme,
        short_error_text,
        set_line_icon, set_status_tone, tr, tr_format,
    )

# Keep the legacy module's private theme probe stable for the renderer and
# older callers while the mutable implementation lives in gui_support.
_ICON_THEME = _gui_support._ICON_THEME


def set_gui_theme(theme):
    normalized = _gui_support.set_gui_theme(theme)
    globals()["_ICON_THEME"] = _gui_support._ICON_THEME
    return normalized


class ReadinessProbe(QObject):
    """Collect injected toolchain health away from the GUI thread."""

    completed = Signal(dict)

    def __init__(self, configured_runtime='auto', *, runtime_probe,
                 provider_probe, ytdlp_version, ffmpeg_version, logger,
                 impersonate_targets=None, whisper_model_state=None,
                 whisper_runtime_state=None, readiness_sink=None,
                 preflight_evaluator=None, ffmpeg_capabilities=None,
                 sign_in_entries=None, github_api_budget=None,
                 output_folder=None, state_location=None,
                 site_refusals=None, system_clock=None,
                 managed_binaries=None):
        super().__init__()
        self.configured_runtime = configured_runtime
        self._runtime_probe = runtime_probe
        self._provider_probe = provider_probe
        self._ytdlp_version = ytdlp_version
        self._ffmpeg_version = ffmpeg_version
        self._logger = logger
        self._impersonate_targets = impersonate_targets
        self._whisper_model_state = whisper_model_state
        self._whisper_runtime_state = whisper_runtime_state
        self._readiness_sink = readiness_sink
        self._preflight_evaluator = preflight_evaluator
        self._ffmpeg_capabilities = ffmpeg_capabilities
        self._sign_in_entries = sign_in_entries
        self._github_api_budget = github_api_budget
        self._output_folder = output_folder
        self._state_location = state_location
        self._site_refusals = site_refusals
        self._system_clock = system_clock
        self._managed_binaries = managed_binaries

    def _environment_probe(self, probe, label):
        if probe is None:
            return None
        try:
            return probe()
        except Exception as error:
            self._logger(f"{label} pre-flight failed: {error}")
            return None

    def run(self):
        try:
            runtime = self._runtime_probe(configured_runtime=self.configured_runtime)
            provider = self._provider_probe()
            targets = (
                self._impersonate_targets() if self._impersonate_targets else []
            )
            whisper_model = (
                self._whisper_model_state()
                if self._whisper_model_state else None
            )
            whisper_runtime = (
                self._whisper_runtime_state()
                if self._whisper_runtime_state else None
            )
            payload = {
                "configuredRuntime": self.configured_runtime,
                "ytDlp": self._ytdlp_version() or "",
                "ffmpeg": self._ffmpeg_version() or "",
                "runtime": runtime or {},
                "deno": runtime or {},
                "provider": provider or {},
                "impersonateTargets": targets or [],
                "whisperModel": whisper_model,
                "whisperRuntime": whisper_runtime,
                "managedBinaries": self._environment_probe(
                    self._managed_binaries, "Managed binary inventory") or [],
            }
            if self._preflight_evaluator is not None:
                ffmpeg_capabilities = None
                sign_in_entries = None
                github_api_budget = None
                if self._ffmpeg_capabilities is not None:
                    try:
                        ffmpeg_capabilities = self._ffmpeg_capabilities()
                    except Exception as error:
                        self._logger(f"FFmpeg capability pre-flight failed: {error}")
                if self._sign_in_entries is not None:
                    try:
                        sign_in_entries = self._sign_in_entries()
                    except Exception as error:
                        self._logger(f"Sign-in pre-flight failed: {error}")
                if self._github_api_budget is not None:
                    try:
                        github_api_budget = self._github_api_budget()
                    except Exception as error:
                        self._logger(f"GitHub budget pre-flight failed: {error}")
                try:
                    preflight = self._preflight_evaluator(
                        ytdlp_version=payload["ytDlp"],
                        ffmpeg_capabilities=ffmpeg_capabilities,
                        javascript_runtime=runtime,
                        sign_in_entries=sign_in_entries,
                        github_api_budget=github_api_budget,
                        po_token_provider=provider,
                        # An environment probe that raises leaves its own check
                        # unmeasured rather than taking the pre-flight down.
                        output_folder=self._environment_probe(
                            self._output_folder, "Download folder"),
                        state_location=self._environment_probe(
                            self._state_location, "Settings storage"),
                        site_refusals=self._environment_probe(
                            self._site_refusals, "Site refusals"),
                        system_clock=self._environment_probe(
                            self._system_clock, "System clock"),
                    )
                except Exception as error:
                    self._logger(f"Pre-flight evaluation failed: {error}")
                    preflight = {
                        "status": "unknown",
                        "blocking": [],
                        "attention": [],
                        "checks": [],
                        "error": "preflight-evaluation-failed",
                    }
                payload["ffmpegCapabilities"] = ffmpeg_capabilities or {}
                payload["githubApiBudget"] = github_api_budget or {}
                payload["preflight"] = preflight
        except Exception as error:
            self._logger(f"Readiness probe failed: {error}")
            payload = {
                "configuredRuntime": self.configured_runtime,
                "error": str(error),
            }
        if self._readiness_sink is not None:
            try:
                # This worker owns the slow probe results. Publishing before
                # the Qt signal keeps the manager's cache independent of the
                # GUI thread and lets callers use it without spawning probes.
                self._readiness_sink(payload)
            except Exception as error:
                self._logger(f"Readiness cache update failed: {error}")
        self.completed.emit(payload)


class FolderPickerService(QObject):
    """Bridge HTTP folder requests onto the Qt GUI thread."""

    DIALOG_WATCHDOG_THRESHOLD_SECONDS = 60

    def __init__(self, *, request_queue, dialog_factory=None, dialog_types=None,
                 clock=time.time, logger=None, parent=None):
        super().__init__(parent)
        self._request_queue = request_queue
        self._dialog_factory = dialog_factory or QFileDialog
        self._dialog_types = dialog_types or (lambda: QFileDialog)
        self._clock = clock
        self._logger = logger or (lambda _message: None)
        self._dialog_open = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(150)

    def _tick(self):
        if self._dialog_open:
            # dialog.exec() below spins a nested event loop that keeps
            # delivering this 150 ms timer. Draining the queue here would
            # stack a second native dialog on top of the open one. Leave the
            # request queued — the bounded request queue keeps the route's
            # 409 "already open" contract for further callers — and service
            # it on the first tick after the open dialog closes.
            return
        try:
            request = self._request_queue.get_nowait()
        except queue.Empty:
            return
        cancellation = request.get('cancelled')
        if cancellation is not None:
            is_cancelled = (
                cancellation.is_set()
                if hasattr(cancellation, 'is_set')
                else bool(cancellation)
            )
            if is_cancelled:
                # The Flask caller can time out while an earlier dialog is
                # open.  Do not turn that orphaned request into a new native
                # dialog when the first one finally closes.
                return
        response_queue = request['response']
        self._dialog_open = True
        try:
            cancellation = request.get('cancelled')
            if cancellation is not None:
                is_cancelled = (
                    cancellation.is_set()
                    if hasattr(cancellation, 'is_set')
                    else bool(cancellation)
                )
                if is_cancelled:
                    return
            initial = request.get('initial') or default_download_path()
            dialog_class = self._dialog_types()
            dialog = self._dialog_factory(None, "Choose download folder", initial)
            dialog.setFileMode(dialog_class.FileMode.Directory)
            dialog.setOption(dialog_class.Option.ShowDirsOnly, True)
            dialog.setOption(dialog_class.Option.DontResolveSymlinks, True)
            dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            dialog.activateWindow()
            dialog.raise_()
            started_at = self._clock()
            result = dialog.exec()
            elapsed = self._clock() - started_at
            if elapsed > self.DIALOG_WATCHDOG_THRESHOLD_SECONDS:
                self._logger(
                    f"FolderPickerService: dialog blocked for {elapsed:.1f}s "
                    f"(threshold {self.DIALOG_WATCHDOG_THRESHOLD_SECONDS}s; "
                    f"initial='{initial}'). Possible Qt event-loop or file-system hang."
                )
            if result == dialog_class.DialogCode.Accepted:
                paths = dialog.selectedFiles()
                response_queue.put({
                    'path': paths[0] if paths else None,
                    'cancelled': not bool(paths),
                })
            else:
                response_queue.put({'path': None, 'cancelled': True})
        except Exception:
            self._logger("FolderPickerService failed")
            response_queue.put({
                'error': 'Folder picker failed. Check Astra Downloader logs for details.'
            })
        finally:
            self._dialog_open = False


_REQUIRED_SETUP_DEPENDENCIES = frozenset({
    'managed_binary_pin_for',
    'retain_managed_binary_rollback',
    'MANAGED_BINARY_ANTIVIRUS_ADVICE',
    'managed_binary_state',
    'check_ffmpeg_capabilities',
    'DEFAULT_CONFIG',
    'check_download_disk_space',
    'FFMPEG_PATH',
    'FFMPEG_SHA256_ASSET',
    'FFMPEG_SHA256_URL',
    'FFMPEG_URL',
    'HELPER_DOWNLOAD_MAX_BYTES',
    'ICON_PATH',
    'ICON_URL',
    'INSTALL_DIR',
    'is_portable_mode',
    'WHISPER_MODEL_MIN_BYTES',
    'WHISPER_MODEL_PATH',
    'WHISPER_BIN_MIN_BYTES',
    'WHISPER_BIN_PATH',
    'YTDLP_PATH',
    'YTDLP_SHA256_ASSET',
    'YTDLP_SHA256_URL',
    'YTDLP_URL',
    '_set_integrations_stamp',
    'download_file_atomic',
    'extract_archive_executable_atomic',
    'fetch_expected_sha256',
    'get_ffmpeg_version',
    'get_ytdlp_version',
    'http_get',
    'launch_command_parts',
    'log_crash',
    'probe_javascript_runtime',
    'provision_deno',
    'provision_quickjs',
    'provision_whisper_model',
    'provision_whisper_runtime',
    'probe_whisper_runtime',
    'register_desktop_shortcut',
    'register_protocol_handlers',
    'register_startup_task',
    'register_uninstall_entry',
    'run_ytdlp_self_update',
    'verify_file_sha256',
    'write_persistent_log',
    'ytdlp_needs_external_runtime',
})


class SetupWorkerCore(QThread):
    log = Signal(str)
    progress = Signal(int)
    finished_ok = Signal()
    finished_err = Signal(str)

    def __init__(self, parent=None, force_ffmpeg=False, auto_update_ytdlp=True,
                 configured_runtime='auto', config=None, *, dependencies):
        missing = sorted(set(_REQUIRED_SETUP_DEPENDENCIES) - set(dependencies))
        if missing:
            raise ValueError("Missing setup worker dependencies: " + ", ".join(missing))
        super().__init__(parent)
        self._dependencies = dict(dependencies)
        self.force_ffmpeg = bool(force_ffmpeg)
        self.auto_update_ytdlp = bool(auto_update_ytdlp)
        self.configured_runtime = configured_runtime
        self.config = config if config is not None else {}

    def _value(self, name):
        value = self._dependencies[name]
        return value() if callable(value) else value

    def _ranged_progress_cb(self, low, high):
        """Return a progress callback that maps bytes into [low, high]% of overall.

        We can only report a bounded range because the setup flow has many
        steps; the callback closes over the ffmpeg zip's download bounds and
        emits integers so the Qt signal connection stays cheap.
        """
        def cb(downloaded, total):
            if total and total > 0:
                pct = low + ((high - low) * downloaded / total)
                self.progress.emit(int(max(low, min(high, pct))))
        return cb

    def _report_managed_binary(self, path, label):
        """Classify a managed binary and name antivirus when it is damaged.

        A quarantine that leaves a zero-byte stub behind passes every
        existence check, so setup would report the tool as already installed
        and the app would run downloads against something it cannot execute.
        """
        state = self._dependencies['managed_binary_state'](path)
        if state == 'damaged':
            advice = tr(self._value('MANAGED_BINARY_ANTIVIRUS_ADVICE')).format(
                path=self._value('INSTALL_DIR')
            )
            message = (
                f"{label} is present but unusable, so it is being downloaded "
                f"again. {advice}"
            )
            self.log.emit(message)
            self._dependencies['write_persistent_log'](message)
        return state

    def _ffmpeg_needs_refresh(self, state):
        """Return whether ffmpeg is absent, stale, damaged, or forced.

        A pin outranks the staleness check but not a missing or damaged file:
        freezing a version cannot mean running one that will not execute.
        """
        if state != 'ok':
            return True
        pinned = self._dependencies['managed_binary_pin_for'](self.config, 'ffmpeg')
        if pinned and pinned == self._dependencies['get_ffmpeg_version']():
            message = f"ffmpeg is pinned to {pinned}; leaving it in place."
            self.log.emit(message)
            self._dependencies['write_persistent_log'](message)
            return False
        if self.force_ffmpeg:
            return True
        try:
            capabilities = self._dependencies['check_ffmpeg_capabilities'](force=True)
        except Exception as exc:  # noqa: BLE001 - health is advisory during setup
            self.log.emit(f"ffmpeg freshness check skipped: {exc}")
            return False
        if capabilities.get('current') is False:
            message = (
                "Installed ffmpeg is below the verified security floor; "
                "downloading a fresh copy."
            )
            self.log.emit(message)
            self._dependencies['write_persistent_log'](message)
            return True
        return False

    def _verify_required_checksum(self, path, sidecar_url, asset_name=None, label=""):
        """Fetch the SHA-256 sidecar and verify before trusting a helper exe."""
        label = label or Path(path).name
        expected = self._dependencies['fetch_expected_sha256'](sidecar_url, target_asset=asset_name)
        if not expected:
            message = (
                f"{label} SHA-256 sidecar missing or malformed; "
                "refusing to trust the downloaded helper."
            )
            self.log.emit(f"  {message}")
            self._dependencies['write_persistent_log'](f"{message} ({sidecar_url})")
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                # reason: an absent or locked failed download is already unusable
                pass
            raise RuntimeError(message)
        try:
            self._dependencies['verify_file_sha256'](path, expected)
        except RuntimeError as e:
            # Mismatch: nuke the downloaded file so the next retry re-fetches
            # from scratch instead of trusting a poisoned copy on disk.
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                # reason: checksum recovery cleanup is best-effort before the retry
                pass
            raise
        self.log.emit(f"  {label} checksum OK")
        return True

    def _download_verified_binary(
        self, url, destination, sidecar_url, asset_name=None, label="", **download_kwargs
    ):
        """Stage a helper download until its release checksum has passed."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.verified"
        )
        try:
            self._dependencies['download_file_atomic'](
                url, staged, **download_kwargs
            )
            self._verify_required_checksum(
                staged, sidecar_url, asset_name=asset_name, label=label
            )
            os.replace(staged, destination)
            return destination
        finally:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                # reason: failed staging cleanup may race with antivirus
                pass

    def _provision_javascript_runtime(self):
        """Make sure some JavaScript runtime exists, preferring Deno.

        yt-dlp's own priority is deno > node > quickjs, so an install that
        can have Deno gets Deno. QuickJS is the fallback: the 40 MB Deno
        archive is the part of setup most likely to fail, and QuickJS is a
        2 MB executable, so a failed Deno fetch no longer leaves the install
        with no runtime at all — which meant every YouTube download failed.
        """
        runtime = self._dependencies['probe_javascript_runtime'](
            force=True, configured_runtime=self.configured_runtime
        )
        if runtime.get('ejsReady'):
            label = str(runtime.get('runtime') or 'JavaScript').title()
            self.log.emit(f"{label} runtime ready: {runtime.get('path')}")
            return True
        ready = False
        if runtime.get('canProvisionDeno'):
            self.log.emit("Downloading Deno runtime...")
            ready = bool(
                self._dependencies['provision_deno'](getattr(self, 'config', None))
            )
            self.log.emit(
                "  Done" if ready else "  Deno download failed; trying QuickJS"
            )
        # An explicit Deno or Node choice is a choice; only Auto and QuickJS
        # may reach for it.
        if not ready and self.configured_runtime in ('auto', 'quickjs'):
            self.log.emit("Downloading QuickJS runtime...")
            ready = bool(self._dependencies['provision_quickjs']())
            self.log.emit(
                "  Done" if ready else "  QuickJS download failed (non-critical)"
            )
        if not ready:
            self.log.emit(
                "No JavaScript runtime is available; YouTube downloads may "
                "fail until one is installed"
            )
        return ready

    def run(self):
        try:
            self._value('INSTALL_DIR').mkdir(parents=True, exist_ok=True)
            dl_path = Path(self._value('DEFAULT_CONFIG')["DownloadPath"])
            dl_path.mkdir(parents=True, exist_ok=True)

            # yt-dlp (10-30% of overall progress)
            ytdlp_state = self._report_managed_binary(
                self._value('YTDLP_PATH'), "yt-dlp")
            if ytdlp_state != 'ok':
                self.log.emit("Downloading yt-dlp...")
                self.progress.emit(10)
                self._download_verified_binary(
                    self._value('YTDLP_URL'), self._value('YTDLP_PATH'),
                    self._value('YTDLP_SHA256_URL'),
                    asset_name=self._value('YTDLP_SHA256_ASSET'), label="yt-dlp",
                    timeout=60, chunk_size=65536,
                    progress_cb=self._ranged_progress_cb(10, 28),
                )
                self.log.emit("  Done")
            else:
                self.log.emit("yt-dlp already installed")
            self.progress.emit(30)

            # ffmpeg (35-58% — the heaviest step, now byte-level progress)
            ffmpeg_state = self._report_managed_binary(
                self._value('FFMPEG_PATH'), "ffmpeg")
            if self._ffmpeg_needs_refresh(ffmpeg_state):
                self.log.emit("Downloading ffmpeg (this may take a moment)...")
                space_failure = self._dependencies['check_download_disk_space'](
                    self._value('INSTALL_DIR'),
                    self._value('HELPER_DOWNLOAD_MAX_BYTES'),
                    reserve_bytes=0,
                )
                if space_failure:
                    raise RuntimeError(space_failure.get(
                        'error', 'Not enough free disk space for ffmpeg.'
                    ))
                self.progress.emit(35)
                tmp_zip = self._value('INSTALL_DIR') / f".ffmpeg.{uuid.uuid4().hex}.zip"
                zip_progress_cb = self._ranged_progress_cb(35, 55)
                try:
                    with self._dependencies['http_get'](self._value('FFMPEG_URL'), stream=True, timeout=120) as r:
                        r.raise_for_status()
                        total = None
                        try:
                            total = int(r.headers.get('content-length', '') or 0) or None
                        except (TypeError, ValueError):
                            total = None
                        # Audit fix: same byte ceiling as self._dependencies['download_file_atomic'] —
                        # a misbehaving CDN must not fill the disk before the
                        # SHA-256 sidecar check. Breach raises; the outer
                        # finally removes the partial tmp_zip.
                        if total and total > self._value('HELPER_DOWNLOAD_MAX_BYTES'):
                            raise RuntimeError(
                                f"ffmpeg archive too large: server advertises {total} "
                                f"bytes (limit {self._value('HELPER_DOWNLOAD_MAX_BYTES')})"
                            )
                        downloaded = 0
                        last_cb = 0.0
                        with open(tmp_zip, 'wb') as data:
                            for chunk in r.iter_content(65536):
                                if chunk:
                                    data.write(chunk)
                                    downloaded += len(chunk)
                                    if downloaded > self._value('HELPER_DOWNLOAD_MAX_BYTES'):
                                        raise RuntimeError(
                                            f"ffmpeg archive exceeded the "
                                            f"{self._value('HELPER_DOWNLOAD_MAX_BYTES')} byte limit; aborted"
                                        )
                                    now = time.monotonic()
                                    if now - last_cb > 0.1:
                                        last_cb = now
                                        zip_progress_cb(downloaded, total)
                            data.flush()
                            os.fsync(data.fileno())
                    if tmp_zip.stat().st_size <= 0:
                        raise RuntimeError("Downloaded ffmpeg archive was empty")
                    # Verify the zip before we crack it open.
                    try:
                        self._verify_required_checksum(
                            tmp_zip, self._value('FFMPEG_SHA256_URL'),
                            asset_name=self._value('FFMPEG_SHA256_ASSET'), label="ffmpeg",
                        )
                    except RuntimeError:
                        # Verification failed — cleanup handled by finally + raise
                        raise
                    self.progress.emit(56)
                    # Keep the copy about to be overwritten, or a rollback
                    # after a bad refresh has nothing to return to.
                    self._dependencies['retain_managed_binary_rollback']('ffmpeg')
                    self._dependencies['extract_archive_executable_atomic'](
                        tmp_zip,
                        self._value('FFMPEG_PATH'),
                        'ffmpeg.exe',
                        max_bytes=self._value('HELPER_DOWNLOAD_MAX_BYTES'),
                    )
                    self.log.emit("  Done")
                finally:
                    try:
                        if tmp_zip.exists():
                            tmp_zip.unlink()
                    except Exception:
                        # reason: helper archive cleanup is best-effort after verification or failure
                        pass
            else:
                self.log.emit("ffmpeg already installed")
            self.progress.emit(55)

            # JavaScript runtime (56-60% — only when yt-dlp needs one).
            ytdlp_ver = self._dependencies['get_ytdlp_version']()
            if self._dependencies['ytdlp_needs_external_runtime'](ytdlp_ver or ''):
                self._provision_javascript_runtime()
            self.progress.emit(60)

            # Local transcription is opt-in because the multilingual model is
            # a separate download and CPU transcription can be expensive. Its
            # pinned fetch is still part of setup once the user enables the
            # setting, so a media job never reaches a half-provisioned model.
            if bool(self.config.get('GenerateSubtitles', False)):
                self.log.emit('Preparing local subtitle transcription runtime...')
                runtime = self._dependencies['probe_whisper_runtime'](
                    self._value('WHISPER_BIN_PATH'),
                    self._value('WHISPER_BIN_MIN_BYTES'),
                )
                if not runtime.get('usable'):
                    runtime_path = self._dependencies['provision_whisper_runtime'](
                        progress_cb=self._ranged_progress_cb(60, 64),
                    )
                    if runtime_path:
                        self.log.emit(f'  Whisper runtime ready: {runtime_path}')
                    else:
                        self.log.emit(
                            '  Whisper runtime is unavailable; local subtitle '
                            'generation will remain unavailable until setup succeeds.'
                        )
                else:
                    self.log.emit(
                        f"  Whisper runtime already ready: {runtime.get('path')}"
                    )
                self.log.emit('Preparing local subtitle transcription model...')
                model = self._dependencies['provision_whisper_model'](
                    progress_cb=self._ranged_progress_cb(64, 68),
                )
                if model:
                    self.log.emit(f'  Whisper model ready: {model}')
                else:
                    self.log.emit(
                        '  Whisper model is unavailable; local subtitle generation '
                        'will remain unavailable until setup succeeds.'
                    )
            self.progress.emit(70)

            # Icon
            if not self._value('ICON_PATH').exists():
                self.log.emit("Downloading icon...")
                try:
                    self._dependencies['download_file_atomic'](self._value('ICON_URL'), self._value('ICON_PATH'), timeout=10, chunk_size=65536)
                except Exception as e:
                    # reason: icon is cosmetic; a failure here shouldn't
                    # block the rest of setup. Log so it's debuggable.
                    self._dependencies['write_persistent_log'](f"Icon download skipped: {e}")
            self.progress.emit(70)

            if self._dependencies['is_portable_mode']():
                self.log.emit(
                    "Portable mode: keeping application state beside the executable."
                )
                self.progress.emit(95)
            else:
                # Desktop shortcut
                self.log.emit("Creating desktop shortcut...")
                self._create_shortcut()
                self.progress.emit(80)

                # Startup task
                self.log.emit("Registering startup task...")
                self._register_startup()
                self.progress.emit(85)

                # Protocol handlers
                self.log.emit("Registering protocol handlers...")
                self._register_protocols()
                self.progress.emit(90)

                # Add/Remove Programs
                self.log.emit("Registering in Apps & Features...")
                self._register_uninstall()
                self.progress.emit(95)

                # Persist the integrations stamp so subsequent launches skip
                # the registration pass (v1.2.0 idempotency).
                self._dependencies['_set_integrations_stamp']()

            # Verify/update yt-dlp through the staged health-check + rollback
            # path. Setup remains successful if this optional maintenance step
            # cannot run; the downloaded helper has already passed its release
            # checksum above.
            if self.auto_update_ytdlp:
                self.log.emit("Updating yt-dlp...")
                try:
                    update = self._dependencies['run_ytdlp_self_update'](
                        self.config, source_tag='setup',
                    )
                except Exception as exc:  # noqa: BLE001
                    self._dependencies['write_persistent_log'](
                        f"Safe yt-dlp update failed during setup: {exc}"
                    )
                    update = {
                        'ok': False,
                        'error': 'The update check failed; the verified installed copy was retained.',
                    }
                if update.get('ok'):
                    version = update.get('version_after') or 'current'
                    self.log.emit(f"  yt-dlp ready: {version}")
                else:
                    message = update.get('error') or 'The active yt-dlp copy was retained.'
                    self.log.emit(f"  Update skipped safely: {message}")

            self.progress.emit(100)
            self.log.emit("\nSetup complete!")
            self.finished_ok.emit()

        except Exception as e:
            self._dependencies['log_crash']("Setup worker")
            self.finished_err.emit(str(e))

    def _create_shortcut(self):
        target, base_args = self._dependencies['launch_command_parts'](prefer_installed=True)
        self._dependencies['register_desktop_shortcut'](target, base_args)

    def _register_startup(self):
        target, base_args = self._dependencies['launch_command_parts'](prefer_installed=True)
        self._dependencies['register_startup_task'](target, base_args)

    def _register_protocols(self):
        target, base_args = self._dependencies['launch_command_parts'](prefer_installed=True)
        self._dependencies['register_protocol_handlers'](target, base_args)

    def _register_uninstall(self):
        target, base_args = self._dependencies['launch_command_parts'](prefer_installed=True)
        self._dependencies['register_uninstall_entry'](target, base_args)

SetupWorker = SetupWorkerCore


_REQUIRED_MAIN_WINDOW_DEPENDENCIES = frozenset({
    'build_reveal_command',
    'set_first_party_network_policy',
    'spawn_detached',
    'summarize_taskbar_progress',
    'build_settings_bundle',
    'read_settings_bundle',
    'describe_bundle_changes',
    'TaskbarProgress',
    'APP_NAME',
    'APP_VERSION',
    'DEFAULT_CONFIG',
    'HISTORY_RETENTION_DEFAULT',
    'HISTORY_RETENTION_MIN',
    'HISTORY_RETENTION_MAX',
    'DOWNLOAD_PENDING_STATES',
    'DOWNLOAD_INTERMEDIATE_DIRNAME',
    'DOWNLOAD_RETRYABLE_ERROR_CODES',
    'DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES',
    'DOWNLOAD_RUNNING_STATES',
    'DOWNLOAD_TERMINAL_STATES',
    'FFMPEG_PATH',
    'ICON_PATH',
    'INSTALL_DIR',
    'INSTANCE_CONTROL_HOST',
    'INSTANCE_CONTROL_PORT',
    'LOG_PATH',
    'MAX_SITE_LOGIN_TEXT_BYTES',
    'MODULE_FILE',
    'PORT_FALLBACKS',
    'QUALITY_LADDER',
    'ReadinessProbe',
    'SERVER_PORT',
    'SetupWorker',
    'YTDLP_PATH',
    'WHISPER_MODEL_MIN_BYTES',
    'WHISPER_MODEL_PATH',
    'WHISPER_BIN_MIN_BYTES',
    'WHISPER_BIN_PATH',
    'probe_whisper_runtime',
    '_build_wsgi_server',
    '_ffmpeg_version_probe',
    '_run_ytdlp_self_update',
    'build_diagnostics_bundle',
    'check_download_disk_space',
    'clamp_int',
    'create_api',
    'evaluate_sabr_support',
    'get_ffmpeg_version',
    'get_recent_log_entries',
    'get_ytdlp_version',
    'SITE_LOGIN_BROWSERS',
    'describe_browser_cookie_readiness',
    'is_playlist_url',
    'is_youtube_url',
    'probed_video_heights',
    'describe_sabr_voided_options',
    'sabr_only_formats',
    'SABR_LIMITED_NOTICE',
    'quality_choices_for_heights',
    'looks_like_media_link',
    'MANAGED_BINARY_ANTIVIRUS_ADVICE',
    'managed_binary_state',
    'managed_binary_usable',
    'maybe_auto_update_ytdlp',
    'allowed_output_roots',
    'normalize_output_dir',
    'parse_native_extension_ids',
    'refresh_native_messaging_registration',
    'detect_system_proxy',
    'normalize_download_section',
    'normalize_output_name',
    'normalize_output_template',
    'output_template_preview',
    'normalize_playlist_date',
    'normalize_impersonate_target',
    'probe_impersonate_targets',
    'probe_extractor_list',
    'probe_output_folder',
    'group_playlist_selection',
    'send_to_recycle_bin',
    'subscription_archive_key',
    'MANAGED_BINARY_NAMES',
    'managed_binary_inventory',
    'set_managed_binary_pin',
    'rollback_managed_binary',
    'normalize_proxy',
    'normalize_force_ip_version',
    'normalize_source_address',
    'normalize_xff',
    'normalize_rate_limit',
    'select_site_profile',
    'validate_site_profiles',
    'normalize_sponsorblock_categories',
    'normalize_sublangs',
    'normalize_subtitle_mode',
    'normalize_subtitle_format',
    'normalize_url',
    'SPONSORBLOCK_CATEGORIES',
    'quarantined_state_files',
    'query_history_entries',
    'reset_deno_runtime_cache',
    'reset_ffmpeg_capabilities_cache',
    'restore_quarantined_file',
    'write_persistent_log',
    'DOWNLOAD_PIPELINE_STEPS',
    'format_redacted_command_args',
})


class PlaylistStagingDialog(QDialog):
    """Interactive staging dialog to review and edit playlist videos before downloading."""

    def __init__(self, parent, playlist_info, *, format_choices=None,
                 quality_choices=None, default_format=None,
                 default_quality=None, archived_indices=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Review playlist"))
        self.setMinimumSize(640, 480)
        self.resize(880, 620)
        self.setModal(True)
        self.setAccessibleName(tr("Review playlist videos"))
        self.setAccessibleDescription(
            tr("Choose which videos should be added to the download queue, "
               "and change the format, quality or name of any of them.")
        )
        self.playlist_info = playlist_info or {}
        self.items = self.playlist_info.get("items") or []
        self._format_choices = list(format_choices or [])
        self._quality_choices = list(quality_choices or [(tr("Best"), "best")])
        self._default_format = default_format
        self._default_quality = default_quality or "best"
        # Indices the subscription archive already holds. They start
        # unselected: re-fetching what an archive captured is the mistake the
        # flag exists to prevent, not a choice to make silently.
        self.archived_indices = {
            int(value) for value in (archived_indices or [])
            if str(value).lstrip("-").isdigit()
        }
        self.checkboxes = []
        self.rows = []
        self._build_ui()

    def _make_choice_combo(self, choices, current, accessible_name):
        combo = QComboBox()
        combo.setAccessibleName(accessible_name)
        for label, value in choices:
            combo.addItem(label, value)
        found = combo.findData(current)
        if found >= 0:
            combo.setCurrentIndex(found)
        combo.setMinimumWidth(96)
        return combo

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_text = self.playlist_info.get("title") or tr("(untitled playlist)")
        channel_text = self.playlist_info.get("channel") or ""
        total_count = len(self.items)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(make_label(title_text, "panelTitle", word_wrap=True))
        sub_text = tr_format("{count} videos", count=total_count)
        if channel_text:
            sub_text = f"{channel_text} · {sub_text}"
        header.addWidget(make_label(sub_text, "fieldHint", word_wrap=True))
        layout.addLayout(header)

        # Action toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_all = QPushButton(tr("Select all"))
        btn_all.setProperty("class", "ghost")
        btn_all.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_all.setAccessibleDescription(
            tr("Select every video in this playlist preview.")
        )
        set_line_icon(btn_all, "select", size=15)
        btn_all.clicked.connect(self._select_all)
        toolbar.addWidget(btn_all)

        btn_none = QPushButton(tr("Deselect all"))
        btn_none.setProperty("class", "ghost")
        btn_none.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_none.setAccessibleDescription(
            tr("Clear every selection in this playlist preview.")
        )
        set_line_icon(btn_none, "clear", size=15)
        btn_none.clicked.connect(self._deselect_all)
        toolbar.addWidget(btn_none)

        btn_invert = QPushButton(tr("Invert"))
        btn_invert.setProperty("class", "ghost")
        btn_invert.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_invert.setAccessibleDescription(
            tr("Select unselected videos and clear selected videos.")
        )
        set_line_icon(btn_invert, "update", size=15)
        btn_invert.clicked.connect(self._invert_selection)
        toolbar.addWidget(btn_invert)

        toolbar.addStretch()
        self.lbl_selected_count = make_label("", "fieldHint")
        toolbar.addWidget(self.lbl_selected_count)
        layout.addLayout(toolbar)

        # Batch apply. Editing fifty rows one at a time is the reason
        # LinkGrabber grew this bar; it writes onto the selected rows only,
        # so an unselected row keeps whatever it already had.
        batch = QHBoxLayout()
        batch.setSpacing(8)
        batch.addWidget(make_label("Apply to selected", "fieldHint"))
        self.batch_format = self._make_choice_combo(
            self._format_choices, self._default_format,
            tr("Format to apply to the selected videos"),
        )
        batch.addWidget(self.batch_format)
        self.batch_quality = self._make_choice_combo(
            self._quality_choices, self._default_quality,
            tr("Quality to apply to the selected videos"),
        )
        batch.addWidget(self.batch_quality)
        self.btn_batch_apply = QPushButton(tr("Apply"))
        self.btn_batch_apply.setProperty("class", "ghost")
        self.btn_batch_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_batch_apply.setAccessibleDescription(
            tr("Give every selected video the format and quality chosen here.")
        )
        self.btn_batch_apply.clicked.connect(self._apply_batch)
        batch.addWidget(self.btn_batch_apply)
        # Its own label: writing the result over the selected-count readout
        # left that count wrong until the next checkbox toggle.
        self.batch_result = make_label("", "fieldHint")
        batch.addWidget(self.batch_result)
        batch.addStretch()
        layout.addLayout(batch)

        # Scrollable items area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(8, 8, 8, 8)
        items_layout.setSpacing(6)

        for item in self.items:
            items_layout.addWidget(self._build_item_row(item))

        if not self.items:
            items_layout.addWidget(
                make_empty_state(
                    tr("No videos found"),
                    tr(
                        "This playlist did not return any videos. Close this review "
                        "and try the link again."
                    ),
                ),
                1,
            )

        items_layout.addStretch()
        scroll.setWidget(items_widget)
        layout.addWidget(scroll, 1)

        # Bottom buttons
        bottom = QHBoxLayout()
        btn_cancel = QPushButton(tr("Cancel"))
        btn_cancel.setProperty("class", "secondary")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setAccessibleDescription(
            tr("Close the playlist review without adding anything to the queue.")
        )
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        bottom.addStretch()

        self.btn_download = QPushButton(tr("Download selected"))
        self.btn_download.setProperty("class", "primary")
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        set_line_icon(self.btn_download, "download", size=15)
        self.btn_download.setDefault(True)
        self.btn_download.setAccessibleDescription(
            tr("Add the selected playlist videos to the download queue.")
        )
        self.btn_download.clicked.connect(self.accept)
        bottom.addWidget(self.btn_download)

        layout.addLayout(bottom)
        self._update_count()
        if self.checkboxes:
            self.checkboxes[0][0].setFocus(Qt.FocusReason.TabFocusReason)

    def _build_item_row(self, item):
        row_frame = QFrame()
        row_frame.setProperty("class", "playlistRow")
        row_layout = QVBoxLayout(row_frame)
        row_layout.setContentsMargins(12, 9, 12, 9)
        row_layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(10)
        cb = QCheckBox()
        idx = item.get("index", len(self.checkboxes) + 1)
        archived = idx in self.archived_indices
        cb.setChecked(not archived)
        cb.stateChanged.connect(self._update_count)
        self.checkboxes.append((cb, item))
        top.addWidget(cb)

        item_title = item.get("title") or tr("(untitled)")
        dur = format_duration(item.get("duration", 0))
        cb.setAccessibleName(
            tr_format(
                "Select playlist item {index}: {title}",
                index=idx,
                title=item_title,
            )
        )
        description = tr_format("Duration {duration}", duration=dur) if dur else ""
        if archived:
            archived_note = tr("Already in the subscription archive.")
            description = f"{description} {archived_note}".strip()
        if description:
            cb.setAccessibleDescription(description)
        lbl = make_label(f"#{idx}  {item_title}", "fieldLabel", word_wrap=True)
        lbl.setToolTip(item_title)
        top.addWidget(lbl, 1)
        if archived:
            badge = make_label("In archive", "toolbarMeta")
            badge.setToolTip(tr(
                "A subscription scan already captured this video. Tick it to "
                "download it again."
            ))
            top.addWidget(badge)
        if dur:
            duration_label = make_label(dur, "toolbarMeta")
            duration_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            top.addWidget(duration_label)
        row_layout.addLayout(top)

        edits = QHBoxLayout()
        edits.setSpacing(8)
        edits.addSpacing(26)
        name_field = QLineEdit()
        name_field.setPlaceholderText(tr("Use the naming template"))
        name_field.setAccessibleName(
            tr_format("File name for playlist item {index}", index=idx)
        )
        name_field.setToolTip(tr(
            "Leave empty to name this file the way every other download is "
            "named. A name here applies to this video only."
        ))
        edits.addWidget(name_field, 1)
        format_combo = self._make_choice_combo(
            self._format_choices, self._default_format,
            tr_format("Format for playlist item {index}", index=idx),
        )
        edits.addWidget(format_combo)
        quality_combo = self._make_choice_combo(
            self._quality_choices, self._default_quality,
            tr_format("Quality for playlist item {index}", index=idx),
        )
        edits.addWidget(quality_combo)
        row_layout.addLayout(edits)

        self.rows.append({
            "index": idx,
            "checkbox": cb,
            "name": name_field,
            "format": format_combo,
            "quality": quality_combo,
            "archived": archived,
        })
        return row_frame

    def _select_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(True)

    def _deselect_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(False)

    def _invert_selection(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(not cb.isChecked())

    def _apply_batch(self):
        fmt = self.batch_format.currentData()
        quality = self.batch_quality.currentData()
        applied = 0
        for row in self.rows:
            if not row["checkbox"].isChecked():
                continue
            for field, value in (("format", fmt), ("quality", quality)):
                combo = row[field]
                found = combo.findData(value)
                if found >= 0:
                    combo.setCurrentIndex(found)
            applied += 1
        self.batch_result.setText(
            tr_format("Applied to {count} videos", count=applied)
        )

    def _update_count(self):
        selected = sum(1 for cb, _ in self.checkboxes if cb.isChecked())
        total = len(self.checkboxes)
        self.lbl_selected_count.setText(tr_format("{selected} of {total} selected", selected=selected, total=total))
        self.btn_download.setEnabled(selected > 0)
        self.btn_download.setText(tr_format("Download selected ({count})", count=selected))

    def get_selected_indices(self):
        """Return 1-based playlist indices of selected items."""
        return [item.get("index", i + 1) for i, (cb, item) in enumerate(self.checkboxes) if cb.isChecked()]

    def get_selection(self):
        """Return the per-item choices for every selected row, in order."""
        selection = []
        for row in self.rows:
            if not row["checkbox"].isChecked():
                continue
            selection.append({
                "index": row["index"],
                "format": row["format"].currentData(),
                "quality": row["quality"].currentData(),
                "output_name": row["name"].text().strip(),
            })
        return selection


class SubscriptionDeliveryDialog(QDialog):
    """Where one subscription's videos land, and in what shape.

    Every field is optional and empty means "use the global setting", so a
    subscription nobody has configured behaves exactly as it did before these
    fields existed.
    """

    VIDEO_FORMATS = (("MP4", "mp4"), ("MKV", "mkv"), ("WebM", "webm"))
    AUDIO_FORMATS = (
        ("MP3", "mp3"), ("M4A", "m4a"), ("Opus", "opus"),
        ("FLAC", "flac"), ("WAV", "wav"),
    )
    QUALITIES = (
        ("Best", "best"), ("2160p", "2160"), ("1440p", "1440"),
        ("1080p", "1080"), ("720p", "720"), ("480p", "480"),
    )

    def __init__(self, parent, record):
        super().__init__(parent)
        self.record = record or {}
        self.setWindowTitle(tr("Subscription delivery"))
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setAccessibleName(tr("Subscription delivery settings"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = self.record.get("title") or self.record.get("url") or tr("Subscription")
        layout.addWidget(make_label(title, "panelTitle", word_wrap=True))
        layout.addWidget(make_label(
            "Anything left empty follows the settings every other download "
            "uses. Fill one in to give this subscription its own.",
            "fieldHint", word_wrap=True,
        ))

        self.audio_only = QCheckBox(tr("Download audio only"))
        self.audio_only.setChecked(bool(self.record.get("audioOnly")))
        self.audio_only.toggled.connect(self._sync_formats)
        layout.addWidget(self.audio_only)

        self.upgrade_if_better = QCheckBox(
            tr("Fetch again when a better version appears")
        )
        self.upgrade_if_better.setChecked(bool(self.record.get("upgradeIfBetter")))
        self.upgrade_if_better.setToolTip(tr(
            "Re-download a captured video only when the site offers a taller "
            "one than the copy on disk. This checks every captured video on "
            "every scan, so it costs a lookup per item."
        ))
        layout.addWidget(self.upgrade_if_better)

        folder_row = QHBoxLayout()
        folder_row.addWidget(make_label("Save to", "fieldLabel"))
        self.output_dir = QLineEdit(str(self.record.get("outputDir") or ""))
        self.output_dir.setPlaceholderText(tr("The usual download folder"))
        self.output_dir.setAccessibleName(tr("Subscription download folder"))
        folder_row.addWidget(self.output_dir, 1)
        browse = QPushButton(tr("Browse"))
        browse.setProperty("class", "ghost")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        set_line_icon(browse, "Browse", size=15)
        browse.setAccessibleDescription(tr("Choose where this subscription saves"))
        browse.clicked.connect(self._choose_folder)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        picker_row = QHBoxLayout()
        picker_row.addWidget(make_label("Format", "fieldLabel"))
        self.format_combo = QComboBox()
        self.format_combo.setAccessibleName(tr("Subscription format"))
        picker_row.addWidget(self.format_combo)
        picker_row.addWidget(make_label("Quality", "fieldLabel"))
        self.quality_combo = QComboBox()
        self.quality_combo.setAccessibleName(tr("Subscription quality"))
        self.quality_combo.addItem(tr("No preference"), "")
        for label, value in self.QUALITIES:
            self.quality_combo.addItem(tr(label), value)
        quality = str(self.record.get("quality") or "")
        self.quality_combo.setCurrentIndex(
            max(0, self.quality_combo.findData(quality)))
        picker_row.addWidget(self.quality_combo)
        picker_row.addStretch()
        layout.addLayout(picker_row)
        self._sync_formats()

        layout.addWidget(make_label("Naming template", "fieldLabel"))
        self.output_template = QLineEdit(str(self.record.get("outputTemplate") or ""))
        self.output_template.setPlaceholderText(tr("The usual naming template"))
        self.output_template.setAccessibleName(tr("Subscription naming template"))
        self.output_template.setToolTip(tr(
            "A yt-dlp output template, relative to the folder above. Only the "
            "allowed fields are accepted, and it must keep %(ext)s."
        ))
        layout.addWidget(self.output_template)

        buttons = QHBoxLayout()
        cancel = QPushButton(tr("Cancel"))
        cancel.setProperty("class", "secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch()
        save = QPushButton(tr("Save"))
        save.setProperty("class", "primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _sync_formats(self):
        """Offer only the formats the chosen kind can actually produce."""
        choices = (self.AUDIO_FORMATS if self.audio_only.isChecked()
                   else self.VIDEO_FORMATS)
        current = self.format_combo.currentData() if self.format_combo.count() else \
            str(self.record.get("format") or "")
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        self.format_combo.addItem(tr("No preference"), "")
        for label, value in choices:
            self.format_combo.addItem(label, value)
        found = self.format_combo.findData(current)
        self.format_combo.setCurrentIndex(found if found >= 0 else 0)
        self.format_combo.blockSignals(False)
        self.quality_combo.setEnabled(not self.audio_only.isChecked())

    def _choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Choose where this subscription saves"),
            self.output_dir.text().strip() or str(Path.home()),
        )
        if chosen:
            self.output_dir.setText(chosen)

    def delivery(self):
        return {
            "outputDir": self.output_dir.text().strip(),
            "format": self.format_combo.currentData() or "",
            "quality": ("" if self.audio_only.isChecked()
                        else (self.quality_combo.currentData() or "")),
            "outputTemplate": self.output_template.text().strip(),
            "audioOnly": self.audio_only.isChecked(),
            "upgradeIfBetter": self.upgrade_if_better.isChecked(),
        }


class SubscriptionArchiveDialog(QDialog):
    """What a subscription has captured, and a way to change your mind.

    The Subscriptions page used to show one number — "10 archived" — with no
    way to see which ten. Allowing one through again removes the archive
    claim; it never touches the file on disk.
    """

    def __init__(self, parent, record, page, on_forget):
        super().__init__(parent)
        self.record = record or {}
        self.page = page or {}
        self._on_forget = on_forget
        self.rows = []
        self.setWindowTitle(tr("Subscription archive"))
        self.setModal(True)
        self.setMinimumSize(640, 420)
        self.resize(820, 560)
        self.setAccessibleName(tr("Captured subscription items"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        title = self.record.get("title") or self.record.get("url") or tr("Subscription")
        layout.addWidget(make_label(title, "panelTitle", word_wrap=True))
        total = int(self.page.get("total") or 0)
        layout.addWidget(make_label(
            tr_format("{count} captured", count=total), "fieldHint",
        ))
        self.status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.status.setAccessibleName(tr("Archive action result"))
        layout.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        items_layout = QVBoxLayout(content)
        items_layout.setContentsMargins(8, 8, 8, 8)
        items_layout.setSpacing(6)
        for item in self.page.get("items") or []:
            items_layout.addWidget(self._build_row(item))
        if not self.page.get("items"):
            items_layout.addWidget(make_empty_state(
                tr("Nothing captured yet"),
                tr("Items appear here after this subscription's first scan "
                   "queues something."),
            ), 1)
        items_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton(tr("Close"))
        close.setProperty("class", "secondary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _build_row(self, item):
        row = QFrame()
        row.setProperty("class", "playlistRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 9, 12, 9)
        row_layout.setSpacing(10)
        copy_layout = QVBoxLayout()
        copy_layout.setSpacing(2)
        title = str(item.get("title") or item.get("url") or tr("(untitled)"))
        copy_layout.addWidget(make_label(title, "fieldLabel", word_wrap=True))
        status = str(item.get("status") or "")
        detail = tr(status.title()) if status else ""
        if item.get("lastError"):
            detail = f"{detail} · {item['lastError']}".strip(" ·")
        copy_layout.addWidget(make_label(detail, "toolbarMeta", word_wrap=True))
        notes = []
        if item.get("missingUpstream"):
            notes.append(tr("The source no longer lists this video."))
        if item.get("fileMissing"):
            notes.append(tr("The file is no longer on this machine."))
        if notes:
            note = make_label(" ".join(notes), "toolbarMeta", word_wrap=True)
            set_status_tone(note, "warning")
            copy_layout.addWidget(note)
        row_layout.addLayout(copy_layout, 1)
        allow = self._make_tool_button("Allow again", "ghost", title)
        allow.setToolTip(tr(
            "Forget this item so the next scan can fetch it again. The file "
            "already on disk is left alone."
        ))
        # An item still being downloaded has a claim the queue is using.
        allow.setEnabled(status not in {"reserved", "queued"})
        allow.clicked.connect(
            lambda _checked=False, key=item.get("key"), button=allow:
            self._allow_again(key, button)
        )
        row_layout.addWidget(allow, 0, Qt.AlignmentFlag.AlignTop)
        self.rows.append({"key": item.get("key"), "button": allow,
                          "status": status})
        return row

    def _allow_again(self, key, button):
        forgotten, error = self._on_forget(key)
        if forgotten:
            button.setEnabled(False)
            button.setText(tr("Allowed"))
            self.status.setText(tr("The next scan can fetch that item again."))
            set_status_tone(self.status, "success")
        else:
            self.status.setText(tr(str(error or "That item could not be forgotten.")))
            set_status_tone(self.status, "danger")
        repolish(self.status)

    def _make_tool_button(self, text, class_name="secondary", target=""):
        parent = self.parent()
        factory = getattr(parent, "_make_tool_button", None)
        if callable(factory):
            return factory(text, class_name, target)
        button = QPushButton(tr(text))
        button.setProperty("class", class_name)
        return button


class MainWindowCore(
    DownloadPageMixin,
    ExtensionPageMixin,
    HistoryPageMixin,
    SiteLoginsPageMixin,
    SitesPageMixin,
    SubscriptionsPageMixin,
    SettingsPageMixin,
    QMainWindow,
):
    log_message = Signal(str)
    instance_command = Signal(str)
    tools_update_finished = Signal(dict)
    tools_status_text_ready = Signal(str)
    server_start_finished = Signal(object)
    site_login_finished = Signal(dict)
    site_login_test_finished = Signal(dict)
    format_probe_finished = Signal(dict)
    site_catalog_ready = Signal(list)

    def __init__(self, config, dl_manager, history, start_minimized=False,
                 first_run=False, *, dependencies):
        missing = sorted(set(_REQUIRED_MAIN_WINDOW_DEPENDENCIES) - set(dependencies))
        if missing:
            raise ValueError("Missing main window dependencies: " + ", ".join(missing))
        self._dependencies = dict(dependencies)
        super().__init__()
        self.config = config
        self.dl_manager = dl_manager
        self.history_mgr = history
        self._force_exit = False
        self._page_anim = None
        self._setup_running = False
        self._model_setup_attempted = False
        self._first_run = bool(first_run)
        self._first_run_destination_confirmed = bool(
            self._first_run and self.config.get("FirstRunComplete", False)
        )
        self._tray_hint_shown = False
        # Download ids already accounted for by the completion notifier, so a
        # finished download notifies at most once and never re-fires each tick.
        self._seen_complete = set()
        # Failure attempts need their generation as well as their id. Retry
        # reuses the Download object and id, but it is a new terminal event.
        self._seen_failures = {}
        self._cleared_history_snapshot = []
        self._history_offset = 0
        self._history_page_size = 50
        self._downloads_signature = None
        self._subscriptions_signature = None
        self._download_widgets = {}
        self._clipboard_last_seen = ""
        self._clipboard_staged_url = ""
        self._site_login_test_states = {}
        self._site_login_testing = False
        self._site_login_undo = None
        self._subscription_undo = None
        self._settings_import_undo = None
        self._restore_defaults_undo = None
        self._restoring_window_state = False
        self.log_message.connect(self._append_log)
        self.instance_command.connect(self._handle_instance_command)
        self.tools_update_finished.connect(self._finish_ytdlp_update)
        self.tools_status_text_ready.connect(self._set_tools_status_text)
        self.server_start_finished.connect(self._finish_server_start)
        self.site_login_finished.connect(self._finish_site_login_import)
        self.site_login_test_finished.connect(self._finish_site_login_test)
        self.format_probe_finished.connect(self._apply_format_probe)
        self.site_catalog_ready.connect(self._on_site_catalog_ready)
        # Format probing: the URL whose probe is currently reflected in the
        # quality picker, and a generation counter so a probe that lands
        # after the user has typed on is discarded rather than applied.
        self._probed_format_url = ""
        self._format_probe_generation = 0
        self._format_probe_summary = {}
        self._format_probe_summary_url = ""
        self._format_probe_in_flight = False
        self._format_probe_request_url = ""

        self.setWindowTitle(self._value('APP_NAME'))
        # Dropping a link on a downloader should download it.
        self.setAcceptDrops(True)
        self.setMinimumSize(900, 620)
        self.resize(1120, 760)

        # Icon
        display_icon_path = self._value('ICON_PATH')
        source_icon_path = Path(self._value('MODULE_FILE')).resolve().parents[1] / "AstraDownloader.ico"
        if not display_icon_path.exists() and source_icon_path.exists():
            display_icon_path = source_icon_path
        if display_icon_path.exists():
            self.setWindowIcon(QIcon(str(display_icon_path)))

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setProperty("class", "sidebar")
        sidebar.setFixedWidth(232)
        self.sidebar = sidebar
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Brand
        brand = QWidget()
        self.brand_widget = brand
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(20, 22, 16, 28)
        brand_layout.setSpacing(10)
        brand_icon = QLabel()
        brand_icon.setFixedSize(36, 36)
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if display_icon_path.exists():
            brand_pixmap = QIcon(str(display_icon_path)).pixmap(32, 32)
            if not brand_pixmap.isNull():
                brand_icon.setPixmap(brand_pixmap)
        if brand_icon.pixmap().isNull():
            brand_icon.setText("A")
            brand_icon.setProperty("class", "brandFallback")
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(2)
        title_lbl = make_label("ASTRA DOWNLOADER", "brandTitle")
        ver_lbl = make_label(
            f"LOCAL  ·  v{self._value('APP_VERSION')}", "brandVersion"
        )
        brand_copy.addWidget(title_lbl)
        brand_copy.addWidget(ver_lbl)
        brand_layout.addWidget(brand_icon)
        brand_layout.addLayout(brand_copy, 1)
        sidebar_layout.addWidget(brand)

        # Nav buttons
        self.nav_buttons = []
        # Download is index 0 and the landing page: this is a video
        # downloader first, and the local API that serves the browser
        # extension is one of the things it happens to run. Ordering the
        # rail any other way makes the paste box something you navigate to.
        self._page_names = [
            "Download", "History", "Sites", "Sign-ins", "Subscriptions",
            "Browser extension", "Settings",
        ]
        for name in self._page_names:
            translated_name = tr(name)
            btn = QPushButton(translated_name)
            btn.setProperty("class", "nav")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setAccessibleName(
                tr_format(
                    "{name} {page}",
                    name=translated_name,
                    page=tr("page"),
                )
            )
            set_line_icon(btn, name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(
                tr_format(
                    "{open_label} {name}",
                    open_label=tr("Open"),
                    name=translated_name,
                )
            )
            btn.clicked.connect(lambda checked, n=name: self._nav_click(n))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        # Status dot. It reports the extension server, which is now a
        # secondary feature \u2014 an unlabelled "Stopped" in the rail of a
        # downloader reads as "the app is broken", so the caption names
        # what is actually stopped.
        status_caption = make_label("Extension server", "fieldHint")
        status_caption.setContentsMargins(22, 0, 18, 0)
        sidebar_layout.addWidget(status_caption)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(22, 0, 18, 22)
        status_row.setSpacing(8)
        self.status_dot = make_label("\u2022", "stateDot")
        self.status_dot.setProperty("tone", "neutral")
        self.status_dot.setAccessibleName(tr("Server status indicator: Stopped"))
        self.status_label = make_state_label("Stopped", "neutral")
        self.status_label.setText(tr("Stopped"))
        self.status_label.setAccessibleName(tr("Server status: Stopped"))
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        sidebar_layout.addLayout(status_row)

        main_layout.addWidget(sidebar)

        # Tab stack
        self.tabs = QTabWidget()
        tab_bar = self.tabs.tabBar()
        tab_bar.hide()
        # The hidden tab bar is QTabWidget's focus proxy. Leaving it
        # focusable makes Tab appear to succeed while focus is sent back to
        # the same invisible widget, trapping keyboard users on every page.
        tab_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabs.setAccessibleName(tr("Companion pages"))
        main_layout.addWidget(self.tabs)

        # readiness_values is populated by every page that owns a status
        # row, so it has to exist before the first _build_* call rather
        # than inside whichever page happened to be built first.
        self.readiness_values = {}
        self.preflight_values = {}
        self._preflight_actions = {}
        self._build_download()
        self._build_history()
        self._build_sites()
        self._build_site_logins()
        self._build_subscriptions()
        self._build_extension()
        self._build_settings()
        self._load_durable_undo_state()

        self._restore_window_state(start_minimized)

        # System tray
        self.tray = QSystemTrayIcon(self)
        if self._value('ICON_PATH').exists():
            self.tray.setIcon(QIcon(str(self._value('ICON_PATH'))))
        else:
            self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        tray_menu = QMenu()
        show_action = tray_menu.addAction(tr("Show Astra Downloader"))
        show_action.triggered.connect(self._show_from_tray)
        self.tray_startstop = tray_menu.addAction(tr("Stop server"))
        self.tray_startstop.triggered.connect(self._toggle_server)
        folder_action = tray_menu.addAction(tr("Open downloads folder"))
        folder_action.triggered.connect(self._open_folder)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction(tr("Quit Astra Downloader"))
        exit_action.triggered.connect(self._force_close)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._tray_activated)
        # A toast that cannot be acted on is just an interruption. Clicking
        # one reveals the download it announced.
        self.tray.messageClicked.connect(self._notification_clicked)
        # Qt 6 dropped QtWinExtras, so this talks to ITaskbarList3 directly.
        # It fails soft: no taskbar bar is a missing nicety, not a broken app.
        self._taskbar_progress = self._dependencies['TaskbarProgress']()
        self._last_notified_file = ""
        self._last_notified_download_id = ""
        self._last_notification_kind = ""
        self.tray.setToolTip(
            tr_format(
                "{app} · {status}",
                app=self._value("APP_NAME"),
                status=tr("Running"),
            )
        )
        self.tray.show()
        self._clipboard = QApplication.clipboard()
        self._clipboard.dataChanged.connect(self._handle_clipboard_change)

        # Timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_ui)
        self.update_timer.start(500)

        # Cleanup timer (every 60s)
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.timeout.connect(dl_manager.cleanup_old)
        self.cleanup_timer.start(60000)

        # Connect signals. yt-dlp emits a progress line per output line, each
        # of which reaches this on the GUI thread, on top of the 500 ms timer.
        # Coalesce them: one repaint per tick is all a human can read.
        self._ui_refresh_timer = QTimer(self)
        self._ui_refresh_timer.setSingleShot(True)
        self._ui_refresh_timer.setInterval(120)
        self._ui_refresh_timer.timeout.connect(self._update_ui)
        dl_manager.progress_updated.connect(self._request_ui_refresh)

        # Server state
        self.server_running = False
        self.server_thread = None
        self.server_obj = None
        self.server_start_time = None
        self._server_starting = False
        self._server_start_cancel = None
        self._server_start_thread = None
        self._subscription_scan_pending = set()
        self._subscription_scan_seen = set()
        self.readiness_thread = None
        self.readiness_worker = None
        self._instance_command_stop = threading.Event()
        self._instance_command_thread = None
        self._start_instance_command_listener()
        self._start_readiness_probe()
        # Let the first window frame render before probing external tools.
        # Both getters can shell out for up to five seconds on a cold cache;
        # scheduling the existing worker-backed refresh after construction
        # keeps startup responsive without sacrificing version visibility.
        self.tools_status_timer = QTimer(self)
        self.tools_status_timer.setSingleShot(True)
        self.tools_status_timer.timeout.connect(self._refresh_tools_status)
        self.tools_status_timer.start(0)

    def _restore_window_state(self, start_minimized=False):
        """Restore local geometry/page state, then apply background startup."""
        self._restoring_window_state = True
        try:
            encoded = str(self.config.get("WindowGeometry", "") or "").strip()
            if encoded:
                try:
                    self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
                except (UnicodeEncodeError, TypeError, ValueError):
                    # reason: a hand-edited or legacy geometry value is not a startup blocker
                    pass
            if self.config.get("WindowMaximized", False):
                self.showMaximized()
            page = "Download" if self._first_run else self.config.get("LastPage", "Download")
            if page not in self._page_names:
                page = "Download"
            self._nav_click(page)
        finally:
            self._restoring_window_state = False
        if start_minimized:
            QTimer.singleShot(100, self._minimize_to_tray)

    def _persist_window_state(self):
        """Save local window state without putting it in portable settings."""
        if not hasattr(self, "tabs") or not hasattr(self, "_page_names"):
            return False
        try:
            geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
            state = {
                "WindowGeometry": geometry,
                "WindowMaximized": bool(self.isMaximized()),
                "LastPage": self._page_names[self.tabs.currentIndex()],
            }
            update = getattr(self.config, "update", None)
            if callable(update):
                return bool(update(state))
            for key, value in state.items():
                setter = getattr(self.config, "set", None)
                if callable(setter):
                    setter(key, value)
            saver = getattr(self.config, "save", None)
            return bool(saver()) if callable(saver) else True
        except (IndexError, OSError, TypeError, ValueError) as error:
            self._append_log(f"Could not save window state: {error}")
            return False

    def _make_page_header(self, title, subtitle):
        header = QVBoxLayout()
        header.setSpacing(4)
        header.addWidget(make_label(title, "title"))
        if subtitle:
            header.addWidget(make_label(subtitle, "subtitle", word_wrap=True))
        return header

    def _add_settings_number(self, target, label, hint, accessible,
                             minimum, maximum, current):
        """Add one labelled spin box with its explanation to a settings group."""
        row = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(2)
        copy.addWidget(make_label(label, "fieldLabel"))
        copy.addWidget(make_label(hint, "fieldHint", word_wrap=True))
        row.addLayout(copy, 1)
        box = QSpinBox()
        box.setAccessibleName(tr(accessible))
        box.setRange(minimum, maximum)
        box.setValue(current)
        box.setFixedWidth(86)
        row.addWidget(box)
        target.addLayout(row)
        return box

    def _add_format_preference(self, target, label, accessible, choices,
                               current):
        """Add one labelled preference combo to a settings group."""
        row = QHBoxLayout()
        row.addWidget(make_label(label, "fieldLabel"), 1)
        combo = QComboBox()
        combo.setAccessibleName(tr(accessible))
        for text_label, value in choices:
            combo.addItem(text_label, value)
        restored = combo.findData(current)
        combo.setCurrentIndex(restored if restored >= 0 else 0)
        row.addWidget(combo)
        target.addLayout(row)
        return combo

    def _make_settings_group(self, title):
        group = QFrame()
        group.setProperty("class", "settingsGroup")
        group.setProperty("settingsSearchTitle", str(title))
        outer = QHBoxLayout(group)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(26)
        heading = make_label(title, "settingsSection")
        heading.setMinimumWidth(150)
        heading.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(heading)
        content = QVBoxLayout()
        content.setSpacing(9)
        outer.addLayout(content, 1)
        if hasattr(self, "_settings_group_specs"):
            self._settings_group_specs.append((group, content, str(title)))
        return group, content

    def _settings_search_text(self, widget):
        """Return safe, user-visible text used by the Settings filter."""
        parts = []
        try:
            property_text = widget.property("settingsSearchText")
        except Exception:
            # reason: a widget with no search property contributes nothing to the settings filter
            property_text = ""
        if property_text:
            parts.append(str(property_text))
        for method_name in (
            "accessibleName", "accessibleDescription", "toolTip",
            "placeholderText",
        ):
            method = getattr(widget, method_name, None)
            if not callable(method):
                continue
            try:
                value = method()
            except Exception:
                # reason: a widget accessor that raises contributes no text to the settings filter
                value = ""
            if value:
                parts.append(str(value))
        if isinstance(widget, (QLabel, QCheckBox, QPushButton)):
            try:
                value = widget.text()
            except Exception:
                # reason: a widget with no text contributes nothing to the settings filter
                value = ""
            if value:
                parts.append(str(value))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                try:
                    parts.append(widget.itemText(index))
                except Exception:
                    # reason: a combo box that will not yield an item label contributes nothing to the settings filter
                    continue
        # Never put a private token or an arbitrary path value into the search
        # index. Labels, accessible names and placeholders already identify
        # those controls without treating their current contents as metadata.
        if widget is getattr(self, "cfg_token", None):
            return " ".join(parts)
        if isinstance(widget, QLineEdit):
            try:
                parts.append(widget.text())
            except Exception:
                # reason: a transient Qt widget can disappear during a filter refresh
                pass
        if isinstance(widget, QTextEdit):
            # Site profiles are JSON rather than a line edit. Index only the
            # non-secret fields so a proxy URL or other private value never
            # becomes searchable metadata, while profile names and domains do.
            try:
                profile_value = json.loads(widget.toPlainText() or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                profile_value = []
            safe_profile_keys = {
                "Name", "Domain", "VideoFormat", "AudioFormat", "Quality",
                "ImpersonateTarget", "ForceIPVersion", "Xff",
            }
            if isinstance(profile_value, list):
                for profile in profile_value:
                    if isinstance(profile, dict):
                        parts.extend(
                            str(profile[key])
                            for key in safe_profile_keys
                            if profile.get(key) not in (None, "")
                        )
        return " ".join(str(part) for part in parts if part).casefold()

    def _settings_item_search_text(self, item):
        widget = item.widget()
        if widget is not None:
            return self._settings_search_text(widget)
        layout = item.layout()
        if layout is None:
            return ""
        return " ".join(
            self._settings_item_search_text(layout.itemAt(index))
            for index in range(layout.count())
        ).casefold()

    def _set_settings_item_visible(self, item, visible):
        widget = item.widget()
        if widget is not None:
            if bool(widget.property("settingsFilterHidden")):
                widget.setVisible(False)
            else:
                widget.setVisible(bool(visible))
            return
        layout = item.layout()
        if layout is None:
            return
        for index in range(layout.count()):
            self._set_settings_item_visible(layout.itemAt(index), visible)

    @staticmethod
    def _set_settings_filter_hidden(widget, hidden):
        """Keep a control's own hidden state outside search filtering."""
        widget.setProperty("settingsFilterHidden", bool(hidden))
        widget.setVisible(not hidden)

    def _load_durable_undo_state(self):
        """Restore one-step undo affordances after every store is constructed."""
        load_history = getattr(self.history_mgr, "load_undo", None)
        if callable(load_history):
            try:
                snapshot = load_history("clearHistory")
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read history undo state: {error}")
                snapshot = None
            if isinstance(snapshot, list) and snapshot:
                self._cleared_history_snapshot = snapshot
                self.btn_undo_clear_history.show()

        store = self._site_login_store()
        load_site_login = getattr(store, "load_removed_undo", None) if store else None
        if callable(load_site_login):
            try:
                self._site_login_undo = load_site_login()
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read sign-in undo state: {error}")
                self._site_login_undo = None
            if self._site_login_undo:
                self.btn_undo_site_login.show()

        manager = self._subscription_manager()
        load_subscription = getattr(manager, "load_removal_undo", None) if manager else None
        if callable(load_subscription):
            try:
                self._subscription_undo = load_subscription()
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read subscription undo state: {error}")
                self._subscription_undo = None
            if self._subscription_undo:
                self.btn_undo_subscription.show()

        load_config = getattr(self.config, "load_undo", None)
        if callable(load_config):
            try:
                self._settings_import_undo = load_config("settingsImport")
                self._restore_defaults_undo = load_config("restoreDefaults")
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read settings undo state: {error}")
                self._settings_import_undo = None
                self._restore_defaults_undo = None
        self._set_settings_filter_hidden(
            self.btn_undo_settings_import, not bool(self._settings_import_undo)
        )
        self._set_settings_filter_hidden(
            self.btn_undo_restore_defaults, not bool(self._restore_defaults_undo)
        )

    def _save_config_undo(self, key, snapshot):
        """Persist a settings recovery snapshot when the store supports it."""
        save = getattr(self.config, "save_undo", None)
        if not callable(save):
            # Small test doubles and older embedders retain the original
            # in-memory behavior until they adopt the adjacent journal API.
            return True
        try:
            return bool(save(key, snapshot))
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not save {key} undo state: {error}")
            return False

    def _clear_config_undo(self, key):
        """Clear a settings recovery snapshot and report persistence failure."""
        clear = getattr(self.config, "clear_undo", None)
        if not callable(clear):
            return True
        try:
            return bool(clear(key))
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not clear {key} undo state: {error}")
            return False

    def _filter_settings(self, query):
        """Show only matching settings rows while keeping their group visible."""
        query = str(query or "").strip().casefold()
        matched_groups = 0
        for group, content, title in getattr(self, "_settings_group_specs", []):
            group_matches = not query or query in str(title).casefold()
            row_matches = False
            for index in range(content.count()):
                item = content.itemAt(index)
                matches = group_matches or query in self._settings_item_search_text(item)
                self._set_settings_item_visible(item, matches)
                row_matches = row_matches or matches
            visible = not query or group_matches or row_matches
            group.setVisible(visible)
            if visible and query:
                matched_groups += 1
        empty = getattr(self, "settings_filter_empty", None)
        if empty is not None:
            empty.setVisible(bool(query) and matched_groups == 0)

    def _make_tool_button(self, text, class_name="secondary", target=""):
        """A tool button, optionally named for the row it acts on.

        In a repeated list every button carries the same word, so a screen
        reader announces "Show, Show, Show" with nothing to tell them apart.
        `target` is what distinguishes them; the visible label is unchanged.
        """
        translated = tr(text)
        btn = QPushButton(translated)
        btn.setProperty("class", class_name)
        set_line_icon(btn, text, size=15)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        target = str(target or "").strip()
        target_label = tr(target) if target else ""
        btn.setAccessibleName(
            f"{translated}: {target_label}" if target_label else translated
        )
        return btn

    def _set_control_label(self, widget, text):
        """Keep the visible label and the accessible name in lockstep.

        Lightweight test doubles implement `setText` and nothing else, so the
        accessible-name write is skipped when the widget has no such method.
        """
        widget.setText(text)
        setter = getattr(widget, "setAccessibleName", None)
        if callable(setter):
            setter(text)

    def _make_readiness_row(self, key, label_text, value_text="Checking"):
        row = QFrame()
        row.setProperty("class", "readinessRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 8, 0, 8)
        row_layout.setSpacing(8)
        dot = make_label("●", "readinessDot")
        dot.setProperty("tone", "neutral")
        dot.setProperty("statusLabel", label_text)
        dot.setAccessibleName(
            tr("{label} status indicator: {value}").format(
                label=tr(label_text), value=tr(value_text)
            )
        )
        dot.setFixedWidth(12)
        row_layout.addWidget(dot)
        name = make_label(label_text, "fieldHint")
        row_layout.addWidget(name, 1)
        value = make_label(value_text, "readinessValue")
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value.setAccessibleName(
            tr("{label} status: {value}").format(
                label=tr(label_text), value=tr(value_text)
            )
        )
        row_layout.addWidget(value)
        self.readiness_values[key] = (dot, value)
        return row

    def _set_readiness(self, key, text, tone="neutral", tooltip=""):
        widgets = self.readiness_values.get(key)
        if not widgets:
            return
        dot, value = widgets
        dot.setProperty("tone", tone)
        translated_text = tr(text)
        value.setText(translated_text)
        label_text = str(dot.property("statusLabel") or key)
        translated_label = tr(label_text)
        dot.setAccessibleName(
            tr("{label} status indicator: {value}").format(
                label=translated_label, value=translated_text
            )
        )
        value.setAccessibleName(
            tr("{label} status: {value}").format(
                label=translated_label, value=translated_text
            )
        )
        translated_tooltip = tr(tooltip)
        value.setToolTip(translated_tooltip)
        dot.setToolTip(translated_tooltip)
        repolish(dot)

    def _make_preflight_row(self, key, label_text, action_text):
        row = QFrame()
        row.setProperty("class", "readinessRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 6, 0, 6)
        row_layout.setSpacing(8)
        dot = make_label("●", "readinessDot")
        dot.setProperty("tone", "neutral")
        dot.setProperty("statusLabel", label_text)
        name = make_label(label_text, "fieldHint")
        detail = make_label("Checking", "readinessValue")
        detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        button = self._make_tool_button(action_text, "ghost", label_text)
        button.clicked.connect(
            lambda _checked=False, check_key=key: self._run_preflight_action(check_key)
        )
        row_layout.addWidget(dot)
        row_layout.addWidget(name, 1)
        row_layout.addWidget(detail)
        row_layout.addWidget(button)
        self.preflight_values[key] = (dot, detail, button)
        self._preflight_actions[key] = action_text
        self._set_preflight_row(key, "unknown", "Checking", action_text)
        return row

    def _set_preflight_row(self, key, status, message="", action=""):
        widgets = self.preflight_values.get(key)
        if not widgets:
            return
        dot, detail, button = widgets
        status = str(status or "unknown").strip().lower()
        if hasattr(self, "_preflight_statuses"):
            self._preflight_statuses[key] = status
        tone = {
            "ok": "success",
            "not-applicable": "neutral",
            "warning": "warning",
            "unknown": "warning",
            "error": "danger",
        }.get(status, "neutral")
        status_text = {
            "ok": "Ready",
            "not-applicable": "Not needed",
            "warning": "Attention",
            "unknown": "Checking",
            "error": "Repair needed",
        }.get(status, "Checking")
        dot.setProperty("tone", tone)
        dot.setAccessibleName(
            tr("{label} status indicator: {value}").format(
                label=tr(str(dot.property("statusLabel") or key)),
                value=tr(status_text),
            )
        )
        detail.setText(tr(status_text))
        detail.setAccessibleName(
            tr("{label} status: {value}").format(
                label=tr(str(dot.property("statusLabel") or key)),
                value=tr(status_text),
            )
        )
        detail.setToolTip(str(message or ""))
        dot.setToolTip(str(message or ""))
        if action:
            self._preflight_actions[key] = str(action)
            # `tr()` around each literal, not around the lookup: the string
            # extractor reads literals passed to tr(), and `tr(map.get(...))`
            # passes a Call, so every one of these buttons stayed English in
            # a fully translated panel.
            action_labels = {
                "refresh-ytdlp": tr("Refresh yt-dlp"),
                "provision-runtime": tr("Provision runtime"),
                "refresh-ffmpeg": tr("Refresh ffmpeg"),
                "refresh-sign-in": tr("Open sign-ins"),
                "retry-github": tr("Try again later"),
                "use-sign-in": tr("Open sign-ins"),
                "choose-output-folder": tr("Choose a folder"),
                "review-state-location": tr("Open settings"),
                "review-site-refusals": tr("Open sign-ins"),
                "sync-system-clock": tr("Check the clock"),
            }
            button.setText(action_labels.get(str(action), tr("Fix")))
        button.setEnabled(status not in {"ok", "not-applicable"})
        button.setAccessibleName(
            tr("{action} for {label}").format(
                action=button.text(),
                label=tr(str(dot.property("statusLabel") or key)),
            )
        )
        repolish(dot)

    def _set_preflight_expanded(self, expanded):
        """Keep readiness repairs one click away without hiding the queue."""
        expanded = bool(expanded)
        self.preflight_details.setVisible(expanded)
        label = tr("Hide checks") if expanded else tr("Show checks")
        self.btn_preflight_toggle.setText(label)
        self.btn_preflight_toggle.setAccessibleName(label)

    def _update_preflight_summary(self):
        summary = getattr(self, "preflight_summary", None)
        if summary is None:
            return
        statuses = list(getattr(self, "_preflight_statuses", {}).values())
        checking = sum(status == "unknown" for status in statuses)
        errors = sum(status == "error" for status in statuses)
        warnings = sum(status == "warning" for status in statuses)
        if checking:
            message = tr("Checking download readiness…")
            tone = "neutral"
        elif errors:
            if errors == 1:
                message = tr(
                    "One check needs repair. Open the checks to see the fix."
                )
            else:
                message = tr(
                    "{count} checks need repair. Open the checks to see the fixes."
                ).format(count=errors)
            tone = "danger"
        elif warnings:
            if warnings == 1:
                message = tr(
                    "One check needs attention. Downloads can still run."
                )
            else:
                message = tr(
                    "{count} checks need attention. Downloads can still run."
                ).format(count=warnings)
            tone = "warning"
        else:
            # Not "all six": the row set grows, and a count written into the
            # sentence goes stale silently the next time it does.
            message = tr("All {count} checks passed. Downloads are ready.").format(
                count=len(statuses)
            )
            tone = "success"
        summary.setText(message)
        set_status_tone(summary, tone)
        repolish(summary)
        toggle = getattr(self, "btn_preflight_toggle", None)
        if errors and toggle is not None and not toggle.isChecked():
            toggle.setChecked(True)

    def _apply_preflight(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        checks = payload.get("checks")
        by_id = {
            str(item.get("id")): item
            for item in checks or ()
            if isinstance(item, dict) and item.get("id")
        }
        for key, _label, fallback_action in PREFLIGHT_ROW_SPECS:
            item = by_id.get(key) or {}
            self._set_preflight_row(
                key,
                item.get("status", "unknown"),
                item.get("message", ""),
                item.get("action", fallback_action),
            )
        self._update_preflight_summary()

    def _run_preflight_action(self, key):
        action = self._preflight_actions.get(key, "")
        if action == "refresh-ytdlp":
            if self._value('YTDLP_PATH').exists():
                self._force_ytdlp_update()
            else:
                self._run_setup()
            return
        if action == "refresh-ffmpeg":
            self._reinstall_ffmpeg()
            return
        if action == "provision-runtime":
            self._run_setup()
            return
        if action in {"refresh-sign-in", "use-sign-in"}:
            self._nav_click("Sign-ins")
            return
        if action == "choose-output-folder":
            self._nav_click("Settings")
            self._show_settings_status(
                tr("Choose a download folder this machine can write to."),
                "warning",
            )
            return
        if action == "review-state-location":
            self._nav_click("Settings")
            self._show_settings_status(
                tr(
                    "Settings, queue and history live at {path}. Copy that "
                    "folder before replacing this build."
                ).format(path=self._value('INSTALL_DIR')),
                "warning",
            )
            return
        if action == "review-site-refusals":
            self._nav_click("Sign-ins")
            self._append_log(
                "A site refused repeatedly; downloads to it are paused."
            )
            return
        if action == "sync-system-clock":
            self._show_settings_status(
                tr(
                    "This machine's clock is out of step. Turn on automatic "
                    "time in Windows Settings, then re-check."
                ),
                "warning",
            )
            self._append_log("System clock drift can expire sign-ins early.")
            return
        if action == "retry-github":
            self._show_settings_status(
                tr("GitHub's anonymous budget is exhausted; retry after its reset."),
                "warning",
            )
            self._append_log("GitHub API budget is exhausted; retry after reset.")

    def _start_readiness_probe(self):
        if self.readiness_thread is not None:
            return
        self.readiness_thread = QThread(self)
        readiness_args = {
            'impersonate_targets': self._dependencies['probe_impersonate_targets'],
            'sign_in_entries': lambda: (
                self.dl_manager.site_logins.entries()
                if getattr(self.dl_manager, 'site_logins', None) is not None
                else []
            ),
            'output_folder': lambda: self._dependencies['probe_output_folder'](
                self.config.get('DownloadPath', '')
            ),
            'site_refusals': lambda: (
                self.dl_manager.refusing_sites()
                if callable(getattr(self.dl_manager, 'refusing_sites', None))
                else []
            ),
            'managed_binaries': lambda: self._dependencies[
                'managed_binary_inventory'](self.config),
        }
        readiness_sink = getattr(self.dl_manager, 'update_readiness_snapshot', None)
        if callable(readiness_sink):
            readiness_args['readiness_sink'] = readiness_sink
        self.readiness_worker = self._dependencies['ReadinessProbe'](
            self.config.get('JavaScriptRuntime', 'auto'),
            **readiness_args,
        )
        self.readiness_worker.moveToThread(self.readiness_thread)
        self.readiness_thread.started.connect(self.readiness_worker.run)
        self.readiness_worker.completed.connect(self._apply_readiness)
        self.readiness_worker.completed.connect(self.readiness_thread.quit)
        self.readiness_thread.finished.connect(self.readiness_worker.deleteLater)
        self.readiness_thread.finished.connect(self._readiness_probe_finished)
        self.readiness_thread.start()

    def _readiness_probe_finished(self):
        thread = self.readiness_thread
        self.readiness_worker = None
        self.readiness_thread = None
        if thread is not None:
            thread.deleteLater()

    def _set_tool_readiness(self, key, version, path):
        """Report a managed tool, naming antivirus when a stub was left behind.

        A version that will not report while the file is on disk is the same
        symptom as a truncated one, and has the same remedy, so both say so.
        """
        if version:
            self._set_readiness(key, version, "success")
            return
        state = self._dependencies['managed_binary_state'](path)
        if state == 'missing':
            self._set_readiness(key, "Missing", "danger")
            return
        self._set_readiness(
            key, "Removed?", "danger",
            tr(self._value('MANAGED_BINARY_ANTIVIRUS_ADVICE')).format(
                path=self._value('INSTALL_DIR')
            ),
        )

    def _apply_impersonate_targets(self, targets):
        combo = getattr(self, "cfg_impersonate", None)
        if combo is None:
            return
        configured = getattr(self, "_configured_impersonate_target", "")
        values = []
        for target in targets or []:
            target = str(target or "").strip()
            if target and target not in values:
                values.append(target)
        combo.blockSignals(True)
        try:
            pending = combo.findData("__impersonate_pending__")
            if pending >= 0:
                combo.removeItem(pending)
            for target in values:
                if combo.findData(target) < 0:
                    combo.addItem(target, target)
            if configured and combo.findData(configured) < 0:
                combo.addItem(
                    tr_format("{target} (unavailable)", target=configured),
                    configured,
                )
            restored = combo.findData(configured)
            combo.setCurrentIndex(restored if restored >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _apply_managed_binaries(self, inventory):
        """Show each managed tool's version, pin and rollback candidate.

        The readiness worker owns the probes; every one of them spawns a
        process, so none of this may happen on the Qt thread.
        """
        rows = getattr(self, "managed_pin_rows", None)
        if not rows:
            return
        for entry in inventory or []:
            row = rows.get(str((entry or {}).get("name", "")))
            if row is None:
                continue
            installed = str(entry.get("installed") or "")
            pinned = str(entry.get("pinned") or "")
            rollback = str(entry.get("rollback") or "")
            row["installed"].setText(
                tr_format("Installed {version}", version=installed)
                if installed else tr("Not installed")
            )
            # An ffmpeg master snapshot is longer than the column, so the
            # full string has to be readable somewhere.
            row["installed"].setToolTip(installed)
            if not row["field"].hasFocus():
                row["field"].setText(pinned)
            row["field"].setPlaceholderText(
                tr_format("Not pinned. {version} installed", version=installed)
                if installed else tr("Not pinned")
            )
            row["pin"].setText(tr("Unpin") if pinned else tr("Pin"))
            digest = str(entry.get("sha256") or "")
            row["field"].setToolTip(
                tr_format("Pinned bytes are SHA-256 {digest}", digest=digest)
                if digest else
                tr("Type the version to hold this tool at, then choose Pin.")
            )
            row["rollback"].setEnabled(bool(rollback))
            row["rollback"].setToolTip(
                tr_format("Put {version} back and pin there.", version=rollback)
                if rollback else
                tr("Nothing has been replaced yet, so there is nothing to go back to.")
            )

    def _show_managed_pin_result(self, result):
        label = getattr(self, "managed_pin_status", None)
        if label is None:
            return
        label.setText(tr(str(result.get("message") or "")))
        set_status_tone(label, "success" if result.get("ok") else "danger")
        repolish(label)
        label.show()

    def _apply_managed_binary_pin(self, name):
        row = getattr(self, "managed_pin_rows", {}).get(name)
        if row is None:
            return
        # The button reads Unpin while a pin is stored, so pressing it then
        # clears the pin whatever is left in the field.
        version = (
            "" if row["pin"].text() == tr("Unpin") else row["field"].text().strip()
        )
        result = self._dependencies['set_managed_binary_pin'](
            self.config, name, version,
        )
        self._show_managed_pin_result(result)
        self._append_log(str(result.get("message") or ""))
        if result.get("ok"):
            row["field"].setText(result.get("version") or "")
            row["pin"].setText(tr("Unpin") if result.get("version") else tr("Pin"))

    def _roll_back_managed_binary(self, name):
        result = self._dependencies['rollback_managed_binary'](self.config, name)
        self._show_managed_pin_result(result)
        self._append_log(str(result.get("message") or ""))
        if result.get("ok"):
            # Versions changed under the panel; re-probe rather than guess.
            self._start_readiness_probe()

    def _apply_readiness(self, payload):
        subtitles_enabled = bool(
            getattr(self, 'config', {}).get("GenerateSubtitles", False)
        )
        if payload.get("error"):
            self._apply_impersonate_targets([])
            apply_preflight = getattr(self, "_apply_preflight", None)
            if callable(apply_preflight):
                apply_preflight(payload.get("preflight") or {})
            for key in ("ytDlp", "ffmpeg", "deno", "provider"):
                self._set_readiness(key, "Unavailable", "danger")
            self._set_readiness(
                "whisper",
                "Unavailable" if subtitles_enabled else "Optional",
                "danger" if subtitles_enabled else "neutral",
            )
            return

        yt_dlp = payload.get("ytDlp")
        ffmpeg = payload.get("ffmpeg")
        runtime = payload.get("runtime") or payload.get("deno") or {}
        provider = payload.get("provider") or {}
        apply_preflight = getattr(self, "_apply_preflight", None)
        if callable(apply_preflight):
            apply_preflight(payload.get("preflight") or {})
        self._apply_impersonate_targets(payload.get("impersonateTargets"))
        self._apply_managed_binaries(payload.get("managedBinaries"))
        self._set_tool_readiness("ytDlp", yt_dlp, self._value('YTDLP_PATH'))
        self._set_tool_readiness("ffmpeg", ffmpeg, self._value('FFMPEG_PATH'))

        if subtitles_enabled:
            whisper_state = payload.get("whisperModel")
            whisper_runtime = payload.get("whisperRuntime") or {}
            if whisper_state == "ok" and whisper_runtime.get("usable"):
                self._set_readiness(
                    "whisper", "Ready", "success",
                    "Local transcription is enabled and the pinned Whisper model and runtime are ready.",
                )
            elif whisper_state == "damaged" or whisper_runtime.get("state") == "damaged":
                self._set_readiness(
                    "whisper", "Repair needed", "warning",
                    "The local Whisper model or whisper.cpp runtime is incomplete or damaged. Run setup to fetch it again.",
                )
            else:
                self._set_readiness(
                    "whisper", "Missing", "danger",
                    "Run setup to provision the local Whisper model and whisper.cpp runtime before downloading.",
                )
        else:
            self._set_readiness("whisper", "Optional", "neutral")

        try:
            sabr = self._dependencies['evaluate_sabr_support'](yt_dlp or "")
        except Exception:
            # reason: an unevaluable version is treated as limited SABR support, which is the cautious answer
            sabr = "limited"
        if sabr == "supported":
            self._set_readiness("sabr", "Supported", "success")
        else:
            self._set_readiness(
                "sabr", "Limited", "warning",
                "The installed yt-dlp streams SABR formats through fallback "
                "clients. Updates flip this automatically once native "
                "support ships.",
            )

        runtime_name = str(runtime.get('runtime') or 'JS').title()
        runtime_version = runtime.get("version")
        if runtime.get("supported") and runtime.get('ejsReady'):
            self._set_readiness("deno", f"{runtime_name} {runtime_version or 'ready'}", "success")
        elif runtime.get("reason") == "runtime-version-below-security-floor":
            self._set_readiness(
                "deno", tr("Security floor"), "danger",
                tr("{runtime} {version} is below the security floor {floor}; update it before downloading.").format(
                    runtime=runtime_name,
                    version=runtime_version or tr("unknown"),
                    floor=runtime.get("securityMinVersion") or tr("required"),
                ),
            )
        elif runtime.get("reason") == "runtime-version-unsupported":
            self._set_readiness(
                "deno", tr("Runtime floor"), "danger",
                tr("{runtime} {version} is below the runtime floor {floor}; update it before downloading.").format(
                    runtime=runtime_name,
                    version=runtime_version or tr("unknown"),
                    floor=runtime.get("minVersion") or tr("required"),
                ),
            )
        elif runtime.get("installed"):
            self._set_readiness("deno", f"{runtime_name} {runtime_version or 'repair'}", "warning")
        elif runtime.get("ytdlpNeedsRuntime"):
            self._set_readiness("deno", "Required", "danger")
        else:
            self._set_readiness("deno", "Optional", "neutral")

        if provider.get("ok") and provider.get("stale"):
            self._set_readiness(
                "provider", "Update", "warning",
                "Proof-of-origin provider is running but out of date. "
                "Downloads use the web client with PO tokens.",
            )
        elif provider.get("ok"):
            self._set_readiness(
                "provider", provider.get("version") or "Ready", "success",
                "Downloads use the web client with proof-of-origin tokens.",
            )
        else:
            self._set_readiness(
                "provider", "Fallback", "neutral",
                "Plugin-based proof-of-origin providers are disabled. Downloads "
                "use the verified token-exempt YouTube client chain.",
            )


    def _value(self, name):
        value = self._dependencies[name]
        return value() if callable(value) else value


    @staticmethod
    def _split_sublangs(text):
        """The language codes in a `--sub-langs` string, order preserved."""
        seen = []
        for part in str(text or "").split(","):
            code = part.strip()
            if code and code not in seen:
                seen.append(code)
        return seen

    def _sync_sublang_checkboxes(self, text):
        """Tick the boxes that match what the field says.

        The field stays the source of truth — it is the only one of the two
        that can express a code with no checkbox, and clearing a box must not
        silently drop such a code.
        """
        codes = {code.lower() for code in self._split_sublangs(text)}
        for box in getattr(self, "_sublang_boxes", ()):
            box.blockSignals(True)
            box.setChecked(box._sublang_code.lower() in codes)
            box.blockSignals(False)

    def _sublang_box_toggled(self, checked):
        """Add or remove one language, leaving every other code untouched."""
        box = self.sender()
        code = getattr(box, "_sublang_code", "")
        if not code:
            return
        codes = self._split_sublangs(self.cfg_sublangs.text())
        present = [item for item in codes if item.lower() == code.lower()]
        if checked and not present:
            codes.append(code)
        elif not checked and present:
            codes = [item for item in codes if item.lower() != code.lower()]
        else:
            return
        # yt-dlp needs at least one language, and the normaliser would put
        # "en" back on save anyway — say so now rather than at save time.
        self.cfg_sublangs.setText(",".join(codes) or "en")
        if not codes:
            self._sync_sublang_checkboxes(self.cfg_sublangs.text())

    def _describe_subtitle_request(self):
        """Say what a subtitles-only job will fetch, in the user's terms."""
        mode = self._dependencies['normalize_subtitle_mode'](
            self.config.get("SubtitleMode")
        )
        langs = self._dependencies['normalize_sublangs'](
            self.config.get("SubLangs", "en")
        )
        kind = {
            "manual": tr("creator subtitles only"),
            "auto": tr("auto-generated subtitles only"),
        }.get(mode, tr("creator subtitles, falling back to auto-generated"))
        fmt = self._dependencies['normalize_subtitle_format'](
            self.config.get("SubtitleFormat")
        )
        as_format = (
            tr_format("as {format}", format=fmt.upper()) if fmt else ""
        )
        return tr_format(
            "Downloads {kind} in {languages}{format}, without the video. "
            "Change this under Settings, Post-processing.",
            kind=kind,
            languages=langs,
            format=(" " + as_format if as_format else ""),
        )

    def _site_profiles(self):
        value = self.config.get("SiteProfiles", [])
        if not isinstance(value, (list, tuple)):
            return []
        return [profile for profile in value if isinstance(profile, dict)]

    def _rebuild_quick_site_profiles(self):
        combo = getattr(self, "quick_download_profile", None)
        if combo is None:
            return
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("Automatic site profile"), None)
        combo.addItem(tr("No profile (one-off)"), "")
        for profile in self._site_profiles():
            name = str(profile.get("Name") or "").strip()
            if name:
                combo.addItem(name, name)
        restored = combo.findData(current)
        combo.setCurrentIndex(restored if restored >= 0 else 0)
        combo.blockSignals(False)
        self._sync_quick_download_profile(apply=True)

    def _quick_download_profile_changed(self, *_args):
        self._sync_quick_download_profile(apply=True)

    def _set_quick_options_expanded(self, expanded):
        """Reveal infrequent download controls without burying the queue."""
        expanded = bool(expanded)
        self.quick_download_advanced.setVisible(expanded)
        label = tr("Fewer options") if expanded else tr("More options")
        self.btn_quick_options.setText(label)
        self.btn_quick_options.setAccessibleName(label)
        description = (
            tr("Hide password, clip range, and custom file name controls.")
            if expanded
            else tr("Show password, clip range, and custom file name controls.")
        )
        self.btn_quick_options.setToolTip(description)
        self.btn_quick_options.setAccessibleDescription(description)

    def _sync_quick_download_profile(self, *, apply=False):
        combo = getattr(self, "quick_download_profile", None)
        if combo is None:
            return None
        selection = combo.currentData()
        raw = getattr(self, "quick_download_url", None)
        parts = raw.text().strip().split() if raw is not None else []
        raw = parts[0] if parts else ""
        normalize_url = self._dependencies.get("normalize_url")
        url = raw
        if callable(normalize_url):
            url, _error = normalize_url(raw)
        profile = self._dependencies["select_site_profile"](
            url or "", self._site_profiles(), selection
        )
        if selection == "":
            summary = tr("No site profile for this download.")
        elif profile:
            summary = tr("Using site profile: {name}.").format(
                name=profile.get("Name") or ""
            )
        else:
            summary = tr("Automatic matching is on; no profile matches this link.")
        if hasattr(self, "quick_download_profile_hint"):
            self.quick_download_profile_hint.setText(summary)
        self._active_quick_site_profile = profile
        if apply and profile:
            self._apply_quick_site_profile(profile)
        return profile

    def _apply_quick_site_profile(self, profile):
        """Apply a profile's request preferences to the paste controls."""
        kind = str(profile.get("DownloadType") or "").strip().lower()
        if kind:
            index = self.quick_download_type.findData(kind)
            if index >= 0:
                self.quick_download_type.blockSignals(True)
                self.quick_download_type.setCurrentIndex(index)
                self.quick_download_type.blockSignals(False)
        self._sync_quick_download_options()
        kind = self.quick_download_type.currentData()
        preferred_format = profile.get(
            "AudioFormat" if kind == "audio" else "VideoFormat"
        )
        if kind != "subtitles" and preferred_format:
            index = self.quick_download_format.findData(preferred_format)
            if index >= 0:
                self.quick_download_format.setCurrentIndex(index)
        preferred_quality = profile.get("Quality")
        if kind == "video" and preferred_quality:
            index = self.quick_download_quality.findData(preferred_quality)
            if index >= 0:
                self.quick_download_quality.setCurrentIndex(index)

    def _sync_quick_download_options(self, *_args):
        if not hasattr(self, "quick_download_format"):
            return
        kind = self.quick_download_type.currentData()
        audio_only = kind == "audio"
        subtitles_only = kind == "subtitles"
        current = self.quick_download_format.currentData()
        values = (
            (("MP3", "mp3"), ("M4A", "m4a"), ("Opus", "opus"),
             ("FLAC", "flac"), ("WAV", "wav"))
            if audio_only else
            (("MP4", "mp4"), ("MKV", "mkv"), ("WebM", "webm"))
        )
        self.quick_download_format.blockSignals(True)
        self.quick_download_format.clear()
        for label, value in values:
            self.quick_download_format.addItem(tr(label), value)
        restored = self.quick_download_format.findData(current)
        if restored >= 0:
            self.quick_download_format.setCurrentIndex(restored)
        self.quick_download_format.blockSignals(False)
        # Neither picker describes a subtitle: the track kind, languages and
        # output format come from Settings, which the hint below names.
        self.quick_download_format.setEnabled(not subtitles_only)
        self.quick_download_quality.setEnabled(not (audio_only or subtitles_only))
        if hasattr(self, "quick_download_subs_hint"):
            self.quick_download_subs_hint.setText(
                self._describe_subtitle_request() if subtitles_only else ""
            )
            self.quick_download_subs_hint.setVisible(subtitles_only)

    def _sync_system_proxy_hint(self, *_args):
        """Show what "use the system proxy" would actually route through."""
        hint = getattr(self, "cfg_system_proxy_hint", None)
        checkbox = getattr(self, "cfg_use_system_proxy", None)
        if hint is None or checkbox is None:
            return
        typed = self.cfg_proxy.text().strip() if hasattr(self, "cfg_proxy") else ""
        if typed:
            hint.setText(tr(
                "A proxy is typed above, so it is used and the system proxy is ignored."
            ))
            return
        if not checkbox.isChecked():
            hint.setText(tr("Downloads connect directly."))
            return
        detected = self._dependencies['detect_system_proxy']()
        hint.setText(
            tr_format("Windows reports {proxy}.", proxy=detected) if detected
            else tr("Windows reports no proxy, so downloads connect directly.")
        )

    def _sync_quick_download_name_hint(self, *_args):
        """Tell the user before they press Download whether the name is usable."""
        field = getattr(self, "quick_download_name", None)
        hint = getattr(self, "quick_download_name_hint", None)
        if field is None or hint is None:
            return
        raw = field.text().strip()
        if not raw:
            hint.hide()
            hint.setText("")
            return
        normalized = self._dependencies['normalize_output_name'](raw)
        if not normalized:
            hint.setText(tr(
                "That name cannot be used. Remove any folder separators, "
                "drive letters, %, or reserved device names such as CON."
            ))
        elif normalized != raw:
            hint.setText(tr_format("Trimmed to {name}.<ext>", name=normalized))
        else:
            hint.setText(tr_format("Saves as {name}.<ext>", name=normalized))
        hint.show()

    def _require_first_run_destination(self):
        if (
            getattr(self, "_first_run", False)
            and not getattr(self, "_first_run_destination_confirmed", False)
        ):
            self._set_quick_download_status(
                "Confirm your download folder before adding a download.",
                "warning",
            )
            first_run = getattr(self, "first_run_destination", None)
            if first_run is not None:
                first_run.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        return True

    def _start_quick_download(self):
        require = getattr(self, "_require_first_run_destination", None)
        if callable(require) and not require():
            return
        # A URL can never contain whitespace (normalize_url rejects it), so
        # splitting on whitespace safely turns a multi-link paste — the common
        # case when the companion is used standalone — into a batch enqueue.
        urls = self.quick_download_url.text().split()
        start = self.quick_download_start.text().strip()
        end = self.quick_download_end.text().strip()
        password_field = getattr(self, "quick_download_video_password", None)
        video_password = password_field.text() if password_field is not None else ""
        section = None
        if not urls:
            self._set_quick_download_status(
                "Paste a video link first.", "error"
            )
            return
        if video_password and len(urls) != 1:
            self._set_quick_download_status(
                tr("Video passwords are available for a single link only."),
                "error",
            )
            return
        name_field = getattr(self, "quick_download_name", None)
        requested_name = name_field.text().strip() if name_field is not None else ""
        output_name = ""
        if requested_name:
            if len(urls) != 1:
                self._set_quick_download_status(
                    tr("A saved file name applies to a single link only."),
                    "error",
                )
                return
            output_name = self._dependencies['normalize_output_name'](requested_name)
            if not output_name:
                self._set_quick_download_status(
                    tr(
                        "That name cannot be used. Remove any folder separators, "
                        "drive letters, %, or reserved device names such as CON."
                    ),
                    "error",
                )
                name_field.setFocus(Qt.FocusReason.OtherFocusReason)
                return
        if start or end:
            if len(urls) > 1:
                self._set_quick_download_status(
                    "Clip ranges apply to a single link. Remove the extra "
                    "links or clear the clip range.",
                    "error",
                )
                return
            section, error = self._dependencies['normalize_download_section']({
                "start": start,
                "end": end,
            })
            if error:
                self._set_quick_download_status(error, "error")
                return

        # Hand the queue boundary the asynchronous probe this page already
        # owns. The manager applies the actual storage policy for every caller.
        kind = self.quick_download_type.currentData()
        format_summary = None
        if len(urls) == 1 and kind != "subtitles":
            normalize_url = self._dependencies.get('normalize_url')
            normalized, normalize_error = (
                normalize_url(urls[0]) if normalize_url else ("", "")
            )
            if (
                not normalize_error
                and normalized
                and normalized == getattr(self, "_format_probe_summary_url", "")
            ):
                format_summary = getattr(self, "_format_probe_summary", {})

        queued = []
        failures = []
        profile_widget = getattr(self, "quick_download_profile", None)
        profile_name = (
            profile_widget.currentData() if profile_widget is not None else None
        )
        for url in urls:
            dl_id, error = self.dl_manager.start_download(
                url=url,
                audio_only=self.quick_download_type.currentData() == "audio",
                subtitles_only=(
                    self.quick_download_type.currentData() == "subtitles"
                ),
                fmt=self.quick_download_format.currentData(),
                quality=self.quick_download_quality.currentData() or "best",
                section=section,
                output_dir=self._quick_download_dir or None,
                video_password=video_password if len(urls) == 1 else None,
                profile_name=profile_name,
                output_name=output_name or None,
                format_summary=format_summary,
            )
            if error:
                failures.append((url, error))
            else:
                queued.append(dl_id)

        clip_suffix = ""
        if section:
            if str(section.get("start", "")).startswith("*"):
                clip_suffix = " " + tr("for a yt-dlp clip")
            else:
                clip_suffix = " " + tr("for an accurate ffmpeg clip")
        if queued:
            if len(queued) == 1:
                message = tr_format(
                    "Queued {id}{suffix}.",
                    id=queued[0],
                    suffix=clip_suffix,
                )
            else:
                message = tr_format(
                    "Queued {count} downloads.", count=len(queued)
                )
            if self._quick_download_dir:
                message += " " + tr_format(
                    "Saving to {path}.", path=self._quick_download_dir
                )
            if failures:
                message += " " + describe_rejected_links(failures)
            self._set_quick_download_status(
                message, "warning" if failures else "success"
            )
            self._clipboard_staged_url = ""
            self.quick_download_url.clear()
            self.quick_download_start.clear()
            self.quick_download_end.clear()
            if password_field is not None:
                password_field.clear()
            # The override was for this download; the default takes over again.
            self._set_quick_download_dir("")
            if profile_widget is not None:
                automatic = profile_widget.findData(None)
                if automatic >= 0:
                    profile_widget.setCurrentIndex(automatic)
            self._append_log(
                f"Queued {len(queued)} download"
                f"{'' if len(queued) == 1 else 's'} from the quick download box."
            )
            self._update_ui()
        else:
            self._set_quick_download_status(
                describe_rejected_links(failures)
                if len(failures) > 1 else failures[0][1],
                "error",
            )

    # ── Drag and drop ────────────────────────────────────────────────────
    # A downloader should accept a link you drop on it. Both a dragged link
    # and a dropped text file of links end up in the same batch path the
    # paste box already uses.
    MAX_DROPPED_LINK_FILE_BYTES = 1024 * 1024

    def _links_from_mime(self, mime):
        """Pull candidate links out of a drop, from text or a dropped file."""
        candidates = []
        if mime.hasText():
            candidates.extend(mime.text().split())
        for url in mime.urls() if mime.hasUrls() else ():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                try:
                    if (path.suffix.lower() not in ('.txt', '.url', '.csv')
                            or path.stat().st_size > self.MAX_DROPPED_LINK_FILE_BYTES):
                        continue
                    candidates.extend(
                        path.read_text(encoding='utf-8', errors='replace').split()
                    )
                except OSError:
                    # reason: an unreadable drop is not an application error
                    continue
            else:
                candidates.append(url.toString())
        links, seen = [], set()
        for candidate in candidates:
            candidate = candidate.strip().strip('<>"\'')
            normalized, error = self._dependencies['normalize_url'](candidate)
            if error or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            links.append(normalized)
        return links

    def dragEnterEvent(self, event):
        if self._links_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        links = self._links_from_mime(event.mimeData())
        if not links:
            event.ignore()
            return
        event.acceptProposedAction()
        self._nav_click("Download")
        self.quick_download_url.setText(" ".join(links))
        # A clip range can only apply to one link, and a drop is a batch.
        if len(links) > 1:
            self.quick_download_start.clear()
            self.quick_download_end.clear()
        self._start_quick_download()

    def _pick_quick_download_dir(self):
        """Choose a destination for the next download only.

        Clicking again with an override already set clears it, so there is no
        second control and no way to end up not knowing where a download went.
        """
        if self._quick_download_dir:
            self._set_quick_download_dir("")
            return
        current = self._quick_download_dir or self.config.get(
            "AudioDownloadPath"
            if self.quick_download_type.currentData() == "audio"
            else "DownloadPath",
            str(Path.home()),
        )
        chosen = QFileDialog.getExistingDirectory(
            self, tr("Save this download to"), str(current))
        if chosen:
            self._set_quick_download_dir(chosen)

    def _set_quick_download_dir(self, path):
        self._quick_download_dir = str(path or "")
        if self._quick_download_dir:
            name = Path(self._quick_download_dir).name or self._quick_download_dir
            self.btn_quick_download_dest.setText(name)
            self.btn_quick_download_dest.setToolTip(
                tr("This download goes to {path}. Click to use the default folder again.")
                .format(path=self._quick_download_dir)
            )
            self.btn_quick_download_dest.setAccessibleName(
                tr_format(
                    "{label}: {path}",
                    label=tr("Save to"),
                    path=self._quick_download_dir,
                )
            )
        else:
            self.btn_quick_download_dest.setText(tr("Save to"))
            self.btn_quick_download_dest.setToolTip(
                tr("Send this download somewhere other than the default folder.")
            )
            self.btn_quick_download_dest.setAccessibleName(tr("Save to"))

    def _set_quick_download_status(self, message, state):
        self.quick_download_status.setText(tr(message))
        self.quick_download_status.show()
        set_status_tone(self.quick_download_status, state)
        repolish(self.quick_download_status)


    def _subscription_manager(self):
        value = self._dependencies.get('subscription_manager')
        return value() if callable(value) else value


    def _refresh_subscriptions(self, force=False):
        manager = self._subscription_manager()
        if manager is None:
            records = []
            payload = {}
            load_error = tr("Subscriptions are unavailable in this session.")
        else:
            load_error = None
            try:
                payload = manager.snapshot()
                records = payload.get("subscriptions", []) if isinstance(payload, dict) else []
            except Exception as error:  # noqa: BLE001
                payload = {}
                records = []
                load_error = f"Could not read subscriptions: {error}"
        manager_scanning = {
            str(sub_id) for sub_id in (payload.get("scanning", []) or [])
        } if isinstance(payload, dict) else set()
        pending = getattr(self, "_subscription_scan_pending", set())
        # The request thread may not have entered SubscriptionManager yet when
        # this refresh runs. Keep the row honest across that tiny hand-off,
        # then retire the local marker once the scheduler reports completion.
        seen = getattr(self, "_subscription_scan_seen", set())
        seen.update(manager_scanning.intersection(pending))
        for sub_id in list(pending):
            if sub_id in seen and sub_id not in manager_scanning:
                pending.discard(sub_id)
                seen.discard(sub_id)
        scanning = manager_scanning | {str(sub_id) for sub_id in pending}
        signature = json.dumps(
            {
                "records": records,
                "scanning": sorted(scanning),
                "error": load_error,
            },
            sort_keys=True,
            default=str,
        )
        if not force and signature == self._subscriptions_signature:
            return
        self._subscriptions_signature = signature
        self._clear_layout(self.subscription_container)
        if manager is None:
            self.subscription_status.setText(load_error)
            set_status_tone(self.subscription_status, "error")
            repolish(self.subscription_status)
            self.subscription_container.addWidget(make_empty_state(
                "Subscriptions unavailable",
                "Start the Astra Downloader companion to manage scheduled channel scans.",
                "Reveal log file",
                self._reveal_log_file,
            ))
            self.subscription_container.addStretch()
            return
        if load_error:
            self.subscription_status.setText(load_error)
            set_status_tone(self.subscription_status, "error")
            repolish(self.subscription_status)
            self.subscription_container.addWidget(make_empty_state(
                "Subscriptions unavailable",
                load_error,
                "Reveal log file",
                self._reveal_log_file,
            ))
            self.subscription_container.addStretch()
            return
        archive = payload.get("archive", {}) if isinstance(payload, dict) else {}
        visible_records = filter_subscription_records(
            records,
            self.subscription_search.text() if hasattr(self, "subscription_search") else "",
            self.subscription_status_filter.currentData()
            if hasattr(self, "subscription_status_filter") else "all",
        )
        if hasattr(self, "subscription_filter_meta"):
            self.subscription_filter_meta.setText(
                tr("{shown} of {total} shown").format(
                    shown=len(visible_records), total=len(records)
                )
            )
        self.subscription_status.setText(
            tr_format(
                "{total} configured · {archived} archived · {queued} queued",
                total=len(records),
                archived=archive.get("complete", 0),
                queued=archive.get("queued", 0),
            )
        )
        set_status_tone(self.subscription_status, "neutral", announce=False)
        repolish(self.subscription_status)
        if not records:
            self.subscription_container.addWidget(make_empty_state(
                "No scheduled subscriptions",
                "Add a YouTube channel or playlist above. New uploads will be queued on its interval.",
                "Add subscription",
                self._focus_subscription_url,
            ))
            self.subscription_container.addStretch()
            return
        if not visible_records:
            self.subscription_container.addWidget(make_empty_state(
                tr("No subscriptions match these filters"),
                tr("Try a different search or choose All subscriptions."),
                "Clear",
                self._clear_subscription_filters,
            ))
            self.subscription_container.addStretch()
            return
        for record in visible_records:
            row = QFrame()
            row.setProperty("class", "card")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(16, 12, 16, 12)
            row_layout.setSpacing(10)
            enabled = QCheckBox()
            enabled.setChecked(bool(record.get("enabled", True)))
            enabled.setAccessibleName(
                tr_format(
                    "{label} {title}",
                    label=tr("Enable subscription"),
                    title=record.get("title") or record.get("url"),
                )
            )
            enabled.toggled.connect(
                lambda checked, sub_id=record.get("id"): self._set_subscription_enabled(sub_id, checked)
            )
            row_layout.addWidget(enabled, 0, Qt.AlignmentFlag.AlignTop)
            copy_layout = QVBoxLayout()
            copy_layout.setSpacing(3)
            title = record.get("title") or record.get("url") or "Subscription"
            copy_layout.addWidget(make_label(title, "cardTitle"))
            copy_layout.addWidget(make_label(record.get("url", ""), "muted", word_wrap=True))
            next_scan = record.get("nextScanAt")
            if next_scan:
                try:
                    next_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(next_scan)))
                except (TypeError, ValueError, OverflowError, OSError):
                    next_text = "pending"
            else:
                next_text = "paused"
            if str(record.get("id") or "") in scanning:
                detail = tr("Every {minutes} min · scanning now…").format(
                    minutes=record.get("intervalMinutes", 60)
                )
            else:
                detail = tr_format(
                    "Every {minutes} min · next scan {next_scan}",
                    minutes=record.get("intervalMinutes", 60),
                    next_scan=next_text,
                )
            if record.get("lastError"):
                detail += " · " + str(record["lastError"])
            copy_layout.addWidget(make_label(detail, "toolbarMeta", word_wrap=True))
            row_layout.addLayout(copy_layout, 1)
            row_target = str(record.get("title") or record.get("url") or "")
            scan = self._make_tool_button("Scan now", "ghost", row_target)
            scan.clicked.connect(lambda checked=False, sub_id=record.get("id"): self._scan_subscription(sub_id))
            row_layout.addWidget(scan, 0, Qt.AlignmentFlag.AlignTop)
            delivery = self._make_tool_button("Delivery", "ghost", row_target)
            delivery.setToolTip(tr(
                "Where this subscription saves, and in what format, quality "
                "and naming."
            ))
            delivery.clicked.connect(
                lambda checked=False, sub_id=record.get("id"):
                self._edit_subscription_delivery(sub_id)
            )
            row_layout.addWidget(delivery, 0, Qt.AlignmentFlag.AlignTop)
            archive = self._make_tool_button("Archive", "ghost", row_target)
            archive.setToolTip(tr(
                "What this subscription has captured, and which items to let "
                "through again."
            ))
            archive.clicked.connect(
                lambda checked=False, sub_id=record.get("id"):
                self._open_subscription_archive(sub_id)
            )
            row_layout.addWidget(archive, 0, Qt.AlignmentFlag.AlignTop)
            remove = self._make_tool_button("Remove", "ghost", row_target)
            remove.clicked.connect(lambda checked=False, sub_id=record.get("id"): self._remove_subscription(sub_id))
            row_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            self.subscription_container.addWidget(row)
        self.subscription_container.addStretch()

    def _show_subscription_status(self, text, tone="neutral"):
        """Write the Subscriptions page's status line."""
        label = getattr(self, "subscription_status", None)
        if label is None:
            return
        label.setText(str(text or ""))
        set_status_tone(label, tone)
        repolish(label)

    def _subscription_record(self, sub_id):
        manager = self._subscription_manager()
        getter = getattr(manager, "get_subscription", None) if manager else None
        if not callable(getter):
            return None
        try:
            return getter(sub_id)
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not read that subscription: {error}")
            return None

    def _edit_subscription_delivery(self, sub_id):
        record = self._subscription_record(sub_id)
        if not record:
            self._show_subscription_status(
                tr("That subscription no longer exists."), "danger")
            return False
        dialog = SubscriptionDeliveryDialog(self, record)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        delivery = dialog.delivery()
        # The folder is checked here rather than at download time. Stored
        # unchecked, an unusable path did not fail until the next scan, and
        # then once per video: the subscription looked configured and simply
        # never delivered anything.
        folder = str(delivery.get("outputDir") or "").strip()
        if folder:
            resolved, folder_error = self._dependencies['normalize_output_dir'](
                folder, self.config.get("DownloadPath", ""),
                # The same roots the download path applies to this folder when
                # the scheduler enqueues against it. Without them the dialog
                # accepts a folder every scheduled download then refuses,
                # which is the failure this check exists to move forward.
                allowed_roots=self._dependencies['allowed_output_roots'](self.config),
            )
            if folder_error:
                self._show_subscription_status(tr(str(folder_error)), "danger")
                return False
            delivery["outputDir"] = resolved
        manager = self._subscription_manager()
        try:
            updated, error = manager.update_subscription(
                sub_id, delivery=delivery)
        except Exception as exc:  # noqa: BLE001
            updated, error = None, str(exc)
        if error or not updated:
            self._show_subscription_status(
                tr(str(error or "That change could not be saved.")), "danger")
            return False
        self._show_subscription_status(
            tr("Delivery settings saved."), "success")
        self._refresh_subscriptions(force=True)
        return True

    def _open_subscription_archive(self, sub_id):
        record = self._subscription_record(sub_id)
        manager = self._subscription_manager()
        pager = getattr(manager, "archive_page", None) if manager else None
        if not record or not callable(pager):
            self._show_subscription_status(
                tr("That subscription no longer exists."), "danger")
            return False
        try:
            page = pager(sub_id)
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not read the subscription archive: {error}")
            self._show_subscription_status(
                tr("The archive could not be read."), "danger")
            return False
        # Whether the media is still on disk is a filesystem question, and the
        # store deliberately never asks it: an archive record must not change
        # because a drive was unplugged. It is answered here, once, for the
        # rows about to be shown.
        for item in page.get("items") or []:
            path = str(item.get("filePath") or "")
            if not path:
                continue
            try:
                # `os.stat`, not `Path.is_file()`: is_file swallows the
                # "drive exists but is not ready" error and answers False, so
                # an ejected USB stick would be reported as a deleted file —
                # the one claim this must never make. Only FileNotFoundError
                # is a deletion.
                os.stat(path)
                item["fileMissing"] = False
            except FileNotFoundError:
                item["fileMissing"] = True
            except OSError:
                # reason: an unreachable drive is not proof the file was deleted
                item["fileMissing"] = False

        def forget(key):
            try:
                return manager.forget_archive_entry(key)
            except Exception as exc:  # noqa: BLE001
                return False, str(exc)

        dialog = SubscriptionArchiveDialog(self, record, page, forget)
        dialog.exec()
        self._refresh_subscriptions(force=True)
        return True

    def _subscription_filters_changed(self):
        if hasattr(self, "_subscription_filter_timer"):
            self._subscription_filter_timer.start()

    # ── Site sign-ins ────────────────────────────────────────────────────

    def _site_login_store(self):
        return getattr(self.dl_manager, "site_logins", None)

    def _open_site_login_for(self, url):
        """Jump to Sign-ins with the blocked download's site already filled in."""
        self._nav_click("Sign-ins")
        if url:
            self.site_login_url.setText(url)
            self.site_login_url.setFocus()
        self._show_site_login_status(
            tr("Import this site's cookies or store its username/password to unblock the download waiting on it."),
            "neutral",
        )

    def _refresh_site_logins(self, force=False):
        store = self._site_login_store()
        entries = []
        load_error = None
        if store is None:
            load_error = tr("Site sign-ins are unavailable in this session.")
        else:
            try:
                entries = store.entries()
            except Exception as error:  # noqa: BLE001
                load_error = tr_format(
                    "Could not read stored sign-ins: {error} Check that the "
                    "install folder is readable, then reopen this page.",
                    error=short_error_text(error),
                )
        signature = json.dumps(
            {"entries": entries, "error": load_error},
            sort_keys=True,
            default=str,
        )
        if not force and signature == getattr(self, "_site_logins_signature", None):
            return
        self._site_logins_signature = signature
        self._clear_layout(self.site_login_container)
        if load_error:
            self._show_site_login_status(load_error, "error")
            self.site_login_container.addWidget(make_empty_state(
                "Site sign-ins are unavailable in this session.",
                load_error,
                "Reveal log file",
                self._reveal_log_file,
            ))
            self.site_login_container.addStretch()
            return
        visible_entries = filter_site_login_entries(
            entries,
            self.site_login_search.text() if hasattr(self, "site_login_search") else "",
            self.site_login_status_filter.currentData()
            if hasattr(self, "site_login_status_filter") else "all",
        )
        if hasattr(self, "site_login_filter_meta"):
            self.site_login_filter_meta.setText(
                tr("{shown} of {total} shown").format(
                    shown=len(visible_entries), total=len(entries)
                )
            )
        if not entries:
            self.site_login_container.addWidget(make_empty_state(
                tr("No stored sign-ins"),
                tr("Add one above for any site that only serves video to "
                   "signed-in viewers. Reserve YouTube sign-ins for videos "
                   "that require an account."),
                "Add a site sign-in",
                self._focus_site_login_url,
            ))
            self.site_login_container.addStretch()
            return
        if not visible_entries:
            self.site_login_container.addWidget(make_empty_state(
                tr("No sign-ins match these filters"),
                tr("Try a different search or choose All sign-ins."),
                "Clear",
                self._clear_site_login_filters,
            ))
            self.site_login_container.addStretch()
            return
        for entry in visible_entries:
            row = QFrame()
            row.setProperty("class", "card")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(16, 12, 16, 12)
            row_layout.setSpacing(10)
            copy_layout = QVBoxLayout()
            copy_layout.setSpacing(3)
            copy_layout.addWidget(make_label(entry.get("site", ""), "cardTitle"))
            credentialed = bool(entry.get("credentialed"))
            count = int(entry.get("cookies", 0) or 0)
            if credentialed:
                state = tr("Username and password. Stored securely.")
                if entry.get("expired") and count:
                    state += " · " + tr("cookie session expired")
            elif entry.get("expired"):
                state = tr("Expired. Sign in again to refresh it.")
            elif not entry.get("stored"):
                state = tr("Missing on disk. Import it again.")
            elif entry.get("earliestExpiry"):
                try:
                    expires = time.strftime(
                        "%Y-%m-%d", time.localtime(float(entry["earliestExpiry"]))
                    )
                except (TypeError, ValueError, OverflowError, OSError):
                    expires = tr("unknown")
                state = tr_format(
                    "{label} {date}",
                    label=tr("First cookie expires"),
                    date=expires,
                )
            else:
                state = tr("Session cookies. Valid until the site signs you out.")
            test_state = self._site_login_test_states.get(entry.get("site"))
            if test_state:
                state += " · " + str(test_state.get("message", ""))
            if credentialed and count:
                auth_label = tr("cookies + username/password")
            elif credentialed:
                auth_label = tr("username/password")
            else:
                auth_label = (
                    tr("cookie") if count == 1 else tr("cookies")
                )
            copy_layout.addWidget(make_label(
                tr_format(
                    "{count} {auth} · {from_label} {source} · {state}",
                    count=count,
                    auth=auth_label,
                    from_label=tr("from"),
                    source=entry.get("source", "import"),
                    state=state,
                ),
                "toolbarMeta",
                word_wrap=True,
            ))
            row_layout.addLayout(copy_layout, 1)
            test = self._make_tool_button(
                "Test", "ghost", str(entry.get("site") or "")
            )
            test.setToolTip(tr("Run a bounded metadata-only sign-in test."))
            test.clicked.connect(
                lambda checked=False, site=entry.get("site"): self._test_site_login(site)
            )
            row_layout.addWidget(test, 0, Qt.AlignmentFlag.AlignTop)
            remove = self._make_tool_button(
                "Remove", "ghost", str(entry.get("site") or ""))
            remove.clicked.connect(
                lambda checked=False, site=entry.get("site"): self._remove_site_login(site)
            )
            row_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            self.site_login_container.addWidget(row)
        self.site_login_container.addStretch()

    def _site_login_filters_changed(self):
        if hasattr(self, "_site_login_filter_timer"):
            self._site_login_filter_timer.start()

    def _show_history_status(self, message, state="neutral", *, log=True):
        """Report a History action on the History page, and in the log.

        ``log`` is off for notes written on every refresh; an action the user
        took is worth a log line, an observation about the filter bar is not.
        """
        self._history_status_is_filter_note = not log
        self.history_page_status.setText(tr(message))
        self.history_page_status.show()
        set_status_tone(self.history_page_status, state)
        repolish(self.history_page_status)
        if log:
            self._append_log(message)

    def _show_site_login_status(self, message, state="neutral"):
        self.site_login_status.setText(tr(message))
        self.site_login_status.show()
        set_status_tone(self.site_login_status, state)
        repolish(self.site_login_status)

    def _show_youtube_sign_in_warning_once(self, site):
        if str(site or "").lower() not in {
            "youtube.com", "youtube-nocookie.com", "youtu.be",
        }:
            return False
        if self.config.get("YouTubeSignInRiskNoticeShown", False):
            return False
        warning = getattr(self, "youtube_sign_in_warning", None)
        if warning is None:
            return False
        warning.show()
        repolish(warning)
        if not self.config.update({"YouTubeSignInRiskNoticeShown": True}):
            self._append_log(
                "Could not save the one-time YouTube sign-in warning state."
            )
        return True

    def _apply_site_login_result(self, result, error):
        if error:
            self._show_site_login_status(error, "error")
            return False
        site = (result or {}).get("site", "")
        count = (result or {}).get("cookies", 0)
        skipped = (result or {}).get("skipped", 0)
        message = tr_format(
            "{signed_in} {site}. {count} {stored}.",
            signed_in=tr("Signed in to"),
            site=site,
            count=count,
            stored=tr("cookies stored"),
        )
        if skipped:
            message += " " + tr_format(
                "{count} {discarded}",
                count=skipped,
                discarded=tr("cookies for other sites were discarded."),
            )
        self._show_site_login_status(message, "success")
        self._show_youtube_sign_in_warning_once(site)
        self._append_log(f"Stored a site sign-in for {site} ({count} cookies).")
        self._discard_site_login_undo()
        self._site_login_test_states.pop(site, None)
        self.site_login_url.clear()
        self._refresh_site_logins(force=True)
        return True

    def _store_site_login_credentials(self):
        store = self._site_login_store()
        if store is None:
            self._show_site_login_status(
                tr("Site sign-ins are unavailable in this session."), "error"
            )
            return False
        result, error = store.save_credentials(
            self.site_login_url.text(),
            self.site_login_username.text(),
            self.site_login_password.text(),
            source="credentials",
        )
        if error:
            self._show_site_login_status(error, "error")
            return False
        site = (result or {}).get("site", "")
        self._show_site_login_status(
            tr_format(
                "{signed_in} {site}. {stored}",
                signed_in=tr("Signed in to"),
                site=site,
                stored=tr("username/password stored securely."),
            ),
            "success",
        )
        self._show_youtube_sign_in_warning_once(site)
        self._append_log(f"Stored a username/password sign-in for {site}.")
        self._discard_site_login_undo()
        self._site_login_test_states.pop(site, None)
        self.site_login_url.clear()
        self.site_login_username.clear()
        self.site_login_password.clear()
        self._refresh_site_logins(force=True)
        return True

    def _import_site_login_from_browser(self):
        store = self._site_login_store()
        if store is None:
            self._show_site_login_status(
                tr("Site sign-ins are unavailable in this session."), "error"
            )
            return
        if getattr(self, "_site_login_reading", False):
            return
        # Reading a browser cookie store spawns yt-dlp and can take tens of
        # seconds (or hit a decryption failure), so it never runs on the GUI
        # thread — the window stays responsive and the result arrives by signal.
        self._site_login_reading = True
        self.btn_site_login_browser.setEnabled(False)
        self._show_site_login_status(tr("Reading cookies from the browser…"), "neutral")
        site = self.site_login_url.text()
        browser = self.site_login_browser.currentData()
        profile = self.site_login_profile.text()

        def worker():
            try:
                result, error = self.dl_manager.import_site_login_from_browser(
                    site, browser, profile
                )
            except Exception as exc:  # noqa: BLE001
                result, error = None, f"Reading browser cookies failed: {exc}"
            self.site_login_finished.emit({"result": result or {}, "error": error or ""})

        threading.Thread(target=worker, daemon=True).start()

    def _finish_site_login_import(self, payload):
        self._site_login_reading = False
        if hasattr(self, "btn_site_login_browser"):
            self.btn_site_login_browser.setEnabled(True)
        if not isinstance(payload, dict):
            return
        self._apply_site_login_result(
            payload.get("result") or None, payload.get("error") or None
        )

    def _import_site_login_from_file(self):
        store = self._site_login_store()
        if store is None:
            self._show_site_login_status(
                tr("Site sign-ins are unavailable in this session."), "error"
            )
            return
        path, _filter = QFileDialog.getOpenFileName(
            self,
            tr("Select the exported cookies.txt"),
            str(Path.home()),
            "Cookie files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        # The size is checked before the read, not after. import_netscape_text
        # rejects anything over MAX_SITE_LOGIN_TEXT_BYTES, but this runs on the
        # GUI thread — picking a multi-gigabyte file froze the window solid
        # before that limit ever got a chance to apply.
        limit = self._value('MAX_SITE_LOGIN_TEXT_BYTES')
        try:
            size = Path(path).stat().st_size
        except OSError as error:
            self._show_site_login_status(
                tr_format(
                    "Could not read that file: {error} Check the path and its "
                    "permissions, then choose the file again.",
                    error=short_error_text(error),
                ),
                "error",
            )
            return
        if size > limit:
            self._show_site_login_status(
                tr("That cookie file is too large to be a browser export."),
                "error",
            )
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self._show_site_login_status(
                tr_format(
                    "Could not read that file: {error} Check the path and its "
                    "permissions, then choose the file again.",
                    error=short_error_text(error),
                ),
                "error",
            )
            return
        result, error = store.import_netscape_text(
            self.site_login_url.text(), text, source="cookies.txt"
        )
        self._apply_site_login_result(result, error)

    def _discard_site_login_undo(self):
        undo = self._site_login_undo
        self._site_login_undo = None
        store = self._site_login_store()
        discard = getattr(store, "discard_removed", None) if store else None
        if undo and callable(discard):
            discard(undo)
        if hasattr(self, "btn_undo_site_login"):
            self.btn_undo_site_login.hide()

    def _remove_site_login(self, site):
        store = self._site_login_store()
        if store is None or not site:
            return
        remove_with_undo = getattr(store, "remove_with_undo", None)
        undo = None
        error = None
        if callable(remove_with_undo):
            undo, error = remove_with_undo(site)
            removed = bool(undo)
        else:
            removed = bool(store.remove(site))
        if error:
            self._show_site_login_status(error, "error")
        elif removed:
            if self._site_login_undo:
                previous = self._site_login_undo
                self._site_login_undo = None
                discard = getattr(store, "discard_removed", None)
                if callable(discard):
                    discard(previous)
            self._site_login_undo = undo
            if undo and hasattr(self, "btn_undo_site_login"):
                self.btn_undo_site_login.show()
            self._show_site_login_status(
                tr_format(
                    "{removed} {site}.",
                    removed=tr("Removed the stored sign-in for"),
                    site=site,
                ),
                "neutral",
            )
            self._append_log(f"Removed the stored site sign-in for {site}.")
        self._refresh_site_logins(force=True)

    def _undo_site_login(self):
        undo = self._site_login_undo
        store = self._site_login_store()
        restore = getattr(store, "restore_removed", None) if store else None
        if not undo or not callable(restore):
            if hasattr(self, "btn_undo_site_login"):
                self.btn_undo_site_login.hide()
            self._show_site_login_status(
                tr("No sign-in removal is available to undo."), "warning"
            )
            return
        restored, error = restore(undo)
        if not restored:
            self._show_site_login_status(
                error or tr("Could not restore the stored sign-in."), "error"
            )
            return
        self._site_login_undo = None
        self.btn_undo_site_login.hide()
        self._show_site_login_status(tr("The sign-in was restored."), "success")
        self._refresh_site_logins(force=True)

    def _test_site_login(self, site):
        manager = self.dl_manager
        if manager is None or not site or self._site_login_testing:
            return
        self._site_login_testing = True
        self._show_site_login_status(
            tr("Testing the stored sign-in…"), "neutral"
        )

        def worker():
            try:
                result, error = manager.test_site_login(site)
            except Exception as exc:  # noqa: BLE001
                result, error = None, str(exc)
            self.site_login_test_finished.emit({
                "site": site,
                "result": result or {},
                "error": error or "",
            })

        threading.Thread(
            target=worker, name="site-login-test", daemon=True
        ).start()

    def _finish_site_login_test(self, payload):
        self._site_login_testing = False
        site = str(payload.get("site") or "")
        error = str(payload.get("error") or "").strip()
        if error:
            self._site_login_test_states[site] = {
                "ok": False,
                "message": tr_format(
                    "{label}: {error} Update the stored sign-in for this site, "
                    "then test again.",
                    label=tr("Test failed"),
                    error=short_error_text(error),
                ),
            }
            self._show_site_login_status(error, "error")
        else:
            result = payload.get("result") or {}
            self._site_login_test_states[site] = {
                "ok": True,
                "message": tr("Test passed"),
            }
            self._show_site_login_status(
                result.get("message") or tr("Stored sign-in test passed."),
                "success",
            )
        self._refresh_site_logins(force=True)

    def _add_subscription(self):
        manager = self._subscription_manager()
        if manager is None:
            self.subscription_status.setText(
                tr("Start the local companion before adding a subscription.")
            )
            return
        record, error = manager.add_subscription(
            self.subscription_url.text(),
            interval_minutes=self.subscription_interval.value(),
        )
        if error:
            self.subscription_status.setText(error)
            return
        self.subscription_url.clear()
        self.subscription_status.setText(
            tr_format(
                "Added {title}. The first scan is scheduled now.",
                title=record.get("title") or record.get("url"),
            )
        )
        self._refresh_subscriptions(force=True)

    def _set_subscription_enabled(self, sub_id, enabled):
        manager = self._subscription_manager()
        if manager is None:
            return
        _record, error = manager.update_subscription(sub_id, enabled=enabled)
        if error:
            self.subscription_status.setText(error)
        self._refresh_subscriptions(force=True)

    def _scan_subscription(self, sub_id):
        manager = self._subscription_manager()
        if manager is None:
            return
        result, error = manager.request_scan(sub_id)
        if error:
            self._subscription_scan_pending.discard(str(sub_id))
            self.subscription_status.setText(error)
        else:
            self._subscription_scan_pending.add(str(sub_id))
        self._refresh_subscriptions(force=True)
        if not error:
            QTimer.singleShot(
                500,
                lambda pending_id=str(sub_id): self._finish_pending_scan_marker(pending_id),
            )
        if error:
            self.subscription_status.setText(error)
        else:
            self.subscription_status.setText(
                tr("Subscription scan started. This row will update when it finishes.")
            )

    def _finish_pending_scan_marker(self, sub_id):
        """Retire the local scan marker when a very fast scan beats the poller."""
        sub_id = str(sub_id)
        if sub_id not in getattr(self, "_subscription_scan_pending", set()):
            return
        manager = self._subscription_manager()
        if manager is None:
            self._subscription_scan_pending.discard(sub_id)
            return
        try:
            payload = manager.snapshot()
            scanning = {
                str(value) for value in (payload.get("scanning", []) or [])
            } if isinstance(payload, dict) else set()
        except Exception:
            # reason: the marker is refreshed on the next snapshot; a failed read must not stop the timer
            return
        if sub_id not in scanning:
            self._subscription_scan_pending.discard(sub_id)
            self._subscription_scan_seen.discard(sub_id)
            self._refresh_subscriptions(force=True)

    def _remove_subscription(self, sub_id):
        manager = self._subscription_manager()
        if manager is None:
            return
        record = None
        remove_with_undo = getattr(manager, "remove_subscription_with_undo", None)
        if callable(remove_with_undo):
            record, error = remove_with_undo(sub_id)
            removed = bool(record)
        else:
            error = None
            removed = None
        getter = getattr(manager, "get_subscription", None)
        if removed is None and callable(getter):
            record = getter(sub_id)
        if removed is None and record is None:
            try:
                record = next(
                    (
                        item for item in manager.list_subscriptions()
                        if str(item.get("id")) == str(sub_id)
                    ),
                    None,
                )
            except Exception:
                # reason: without the record there is nothing to offer undo
                # from, so the removal below proceeds and undo stays unavailable
                record = None
        self._subscription_scan_pending.discard(str(sub_id))
        self._subscription_scan_seen.discard(str(sub_id))
        if removed is None:
            removed, error = manager.remove_subscription(sub_id)
        if error:
            self.subscription_status.setText(error)
        elif removed:
            self._subscription_undo = record
            if record and hasattr(self, "btn_undo_subscription"):
                self.btn_undo_subscription.show()
            self.subscription_status.setText(
                tr("Subscription removed. Downloaded files were not deleted.")
            )
        self._refresh_subscriptions(force=True)

    def _undo_subscription(self):
        record = self._subscription_undo
        manager = self._subscription_manager()
        restore = getattr(manager, "restore_subscription", None) if manager else None
        if not record or not callable(restore):
            if hasattr(self, "btn_undo_subscription"):
                self.btn_undo_subscription.hide()
            self.subscription_status.setText(
                tr("No subscription removal is available to undo.")
            )
            return
        restored, error = restore(record)
        if not restored:
            self.subscription_status.setText(
                error or tr("Could not restore the subscription.")
            )
            return
        clear_undo = getattr(manager, "clear_removal_undo", None)
        journal_cleared = not callable(clear_undo) or clear_undo()
        if journal_cleared:
            self._subscription_undo = None
            self.btn_undo_subscription.hide()
        message = tr("The subscription was restored.")
        if not journal_cleared:
            message += " The Undo record is still available; clear it before closing."
        self.subscription_status.setText(message)
        self._refresh_subscriptions(force=True)

    def _nav_click(self, name):
        idx = self._page_names.index(name)
        self.tabs.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)
            btn.setProperty("active", "true" if i == idx else "false")
            repolish(btn)
        self._animate_page()
        if name == "History":
            self._refresh_history()
        elif name == "Subscriptions":
            self._refresh_subscriptions(force=True)
        if not self._restoring_window_state:
            self._persist_window_state()

    def _pending_quarantines(self):
        read = self._dependencies.get('quarantined_state_files')
        if not callable(read):
            return []
        return [entry for entry in read()
                if entry.get('backup') not in self._dismissed_quarantines]

    def _refresh_quarantine_notice(self):
        pending = self._pending_quarantines()
        if not pending:
            self.quarantine_panel.hide()
            return
        entry = pending[0]
        name = Path(entry['path']).name
        extra = (
            tr(
                "Your server token was regenerated, so the browser extension "
                "needs pairing again."
            )
            if name == "config.json" else ""
        )
        message = tr_format(
            "{label} could not be read and was set aside as {backup}. "
            "Restore puts the original back and reloads it.",
            label=name,
            backup=Path(entry["backup"]).name,
        )
        if extra:
            message += " " + extra
        self.quarantine_notice.setText(message)
        self.quarantine_panel.show()

    def _restore_quarantined_state(self):
        pending = self._pending_quarantines()
        if not pending:
            self._refresh_quarantine_notice()
            return
        entry = pending[0]
        restore = self._dependencies.get('restore_quarantined_file')
        restored = restore(entry['backup']) if callable(restore) else None
        if not restored:
            self._append_log(f"Could not restore {Path(entry['path']).name}.")
            self.quarantine_notice.setText(
                tr_format(
                    "{label} could not be restored. Its backup is at {backup}.",
                    label=Path(entry["path"]).name,
                    backup=entry["backup"],
                )
            )
            return
        reload_config = getattr(self.config, 'reload', None)
        if Path(entry['path']).name == 'config.json' and callable(reload_config):
            reload_config()
            self._append_log("Restored config.json and reloaded settings.")
        else:
            self._append_log(
                f"Restored {Path(entry['path']).name}. It is used from the next start."
            )
        self._refresh_quarantine_notice()

    def _dismiss_quarantine_notice(self):
        for entry in self._pending_quarantines():
            self._dismissed_quarantines.add(entry['backup'])
        self._refresh_quarantine_notice()

    def _focus_download_url(self):
        """Put the caret in the paste box, wherever the user is."""
        self._nav_click("Download")
        self.quick_download_url.setFocus(Qt.FocusReason.OtherFocusReason)

    def _focus_subscription_url(self):
        self._nav_click("Subscriptions")
        self.subscription_url.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_subscription_filters(self):
        self.subscription_search.clear()
        self.subscription_status_filter.setCurrentIndex(0)
        self._refresh_subscriptions(force=True)
        self.subscription_search.setFocus(Qt.FocusReason.OtherFocusReason)

    def _focus_site_login_url(self):
        self._nav_click("Sign-ins")
        self.site_login_url.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_site_login_filters(self):
        self.site_login_search.clear()
        self.site_login_status_filter.setCurrentIndex(0)
        self._refresh_site_logins(force=True)
        self.site_login_search.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_history_filters(self):
        self.history_search.clear()
        self.history_status.setCurrentIndex(0)
        self.history_format.setCurrentIndex(0)
        self.history_sort.setCurrentIndex(0)
        self.history_date_from.clear()
        self.history_date_to.clear()
        self._history_offset = 0
        self._refresh_history()
        self.history_search.setFocus(Qt.FocusReason.OtherFocusReason)

    def _apply_first_run_panel_state(self):
        panel = getattr(self, "first_run_panel", None)
        if panel is None:
            return
        active = bool(self._first_run)
        panel.setVisible(active)
        if not active:
            return
        confirmed = bool(self._first_run_destination_confirmed)
        self.first_run_destination.setReadOnly(confirmed)
        self.first_run_browse.setEnabled(not confirmed)
        self.first_run_confirm.setVisible(not confirmed)
        if confirmed:
            path = self.config.get("DownloadPath", self.first_run_destination.text())
            self.first_run_status.setText(
                tr_format(
                    "Destination confirmed: {folder}. Setup can continue in the background.",
                    folder=path,
                )
            )
            set_status_tone(self.first_run_status, "success")
            repolish(self.first_run_status)
        else:
            self.first_run_status.setText(
                tr("Confirm a folder before your first download.")
            )
            set_status_tone(self.first_run_status, "warning")
            repolish(self.first_run_status)

    def _confirm_first_run_destination(self):
        if not self._first_run:
            return False
        normalize = self._dependencies.get("normalize_output_dir")
        if not callable(normalize):
            self.first_run_status.setText(
                tr(
                    "The download folder validator is unavailable. "
                    "Check the log and retry."
                )
            )
            set_status_tone(self.first_run_status, "error")
            repolish(self.first_run_status)
            return False
        normalized, error = normalize(
            self.first_run_destination.text().strip(),
            self._value("DEFAULT_CONFIG")["DownloadPath"],
        )
        if error:
            # Wrapped like every other message this function writes. The
            # folder-policy strings live in config.py, which the extractor
            # cannot reach, so this passes through today; it is the shape the
            # rest of the file uses and the one that will work when they do.
            self.first_run_status.setText(tr(str(error)))
            set_status_tone(self.first_run_status, "error")
            repolish(self.first_run_status)
            self.first_run_destination.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        update = getattr(self.config, "update", None)
        if not callable(update) or not update({
            "DownloadPath": normalized,
            "FirstRunComplete": True,
        }):
            self.first_run_status.setText(
                tr(
                    "Could not save the download folder. "
                    "Check disk permissions and retry."
                )
            )
            set_status_tone(self.first_run_status, "error")
            repolish(self.first_run_status)
            return False
        self.first_run_destination.setText(normalized)
        self._first_run_destination_confirmed = True
        self._append_log(f"First-run download folder confirmed: {normalized}")
        self._apply_first_run_panel_state()
        return True

    def _open_first_run_pairing(self):
        self._nav_click("Browser extension")
        if self._setup_running:
            self._append_log(
                "Browser extension pairing is ready after first-run setup finishes."
            )
            return
        if not self.server_running and not self._server_starting:
            self._start_server()

    def _animate_page(self):
        widget = self.tabs.currentWidget()
        if not widget:
            return
        if system_reduced_motion_enabled():
            widget.setGraphicsEffect(None)
            self._page_anim = None
            return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(120)
        anim.setStartValue(0.86)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        self._page_anim = anim
        anim.start()

    # ── Server ──
    def _toggle_server(self):
        if self.server_running:
            self._stop_server()
        else:
            self._start_server()

    def _start_server(self):
        if self.server_running or self._server_starting:
            return
        if self._setup_running:
            self._append_log("Setup is already running. The server will start when it finishes.")
            return
        tools_ready = (
            self._dependencies['managed_binary_usable'](self._value('YTDLP_PATH'))
            and self._dependencies['managed_binary_usable'](self._value('FFMPEG_PATH'))
        )
        model_missing = (
            self.config.get('GenerateSubtitles', False)
            and not self._dependencies['managed_binary_usable'](
                self._value('WHISPER_MODEL_PATH'),
                self._value('WHISPER_MODEL_MIN_BYTES'),
            )
        )
        runtime_missing = False
        if self.config.get('GenerateSubtitles', False):
            try:
                runtime_missing = not self._dependencies['probe_whisper_runtime'](
                    self._value('WHISPER_BIN_PATH'),
                    self._value('WHISPER_BIN_MIN_BYTES'),
                ).get('usable')
            except Exception:
                # reason: an unprobeable Whisper runtime is treated as missing, which is the cautious answer
                runtime_missing = True
        if not tools_ready or ((model_missing or runtime_missing) and not self._model_setup_attempted):
            self._append_log("Required download tools are missing or unusable. Starting setup...")
            if model_missing or runtime_missing:
                self._model_setup_attempted = True
            self._run_setup()
            return

        configured_port = self._dependencies['clamp_int'](
            self.config.get("ServerPort", self._value('SERVER_PORT')),
            self._value('SERVER_PORT'), 1024, 65535,
        )
        try:
            self._dependencies["refresh_native_messaging_registration"]()
        except Exception as error:
            self._append_log(f"Native-host registration skipped: {error}")
        self._server_starting = True
        self._server_start_cancel = threading.Event()
        cancel = self._server_start_cancel
        self._update_server_ui()

        def prepare():
            server_obj = None
            try:
                api = self._dependencies['create_api'](
                    self.config, self.dl_manager, self.history_mgr
                )
                # Port discovery is local socket work. Keep it out of the GUI
                # thread so a blocked Windows/Hyper-V port table cannot freeze
                # the window while the user waits for the result.
                fallback_ports = [configured_port] + [
                    port for port in self._value('PORT_FALLBACKS')
                    if port != configured_port
                ]
                chosen_port = None
                last_err = None
                for candidate in fallback_ports:
                    if cancel.is_set():
                        self.server_start_finished.emit({"cancelled": True})
                        return
                    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        probe.bind(('127.0.0.1', candidate))
                        chosen_port = candidate
                        break
                    except OSError as error:
                        last_err = error
                    finally:
                        try:
                            probe.close()
                        except OSError:
                            # reason: a failed bind may leave no closable probe socket
                            pass

                if chosen_port is None:
                    assert last_err is not None
                    if getattr(last_err, 'winerror', None) == 10013:
                        message = (
                            "All candidate ports are blocked by Windows.\n\n"
                            "Run as Administrator in PowerShell:\n"
                            "  net stop winnat\n"
                            "  netsh int ipv4 delete excludedportrange protocol=tcp "
                            f"startport={configured_port} numberofports=1\n"
                            "  net start winnat"
                        )
                    elif getattr(last_err, 'winerror', None) == 10048:
                        message = "All candidate ports are already in use by other processes."
                    else:
                        message = f"Cannot bind any server port: {last_err}"
                    self.server_start_finished.emit({
                        "ok": False, "error": message,
                    })
                    return

                # v1.2.0: prefer waitress (production-grade WSGI) and fall
                # back to werkzeug only when waitress is unavailable.
                server_obj = self._dependencies['_build_wsgi_server'](
                    chosen_port, api
                )
                if cancel.is_set():
                    try:
                        server_obj.stop()
                    except Exception:
                        # reason: a server object that was never run has no
                        # listener to close; the cancellation is still safe
                        pass
                    self.server_start_finished.emit({"cancelled": True})
                    return
                self.server_start_finished.emit({
                    "ok": True,
                    "port": chosen_port,
                    "server": server_obj,
                })
            except Exception as error:
                if server_obj is not None:
                    try:
                        server_obj.stop()
                    except Exception:
                        # reason: setup failure cleanup must not hide the root error
                        pass
                self.server_start_finished.emit({
                    "ok": False, "error": str(error),
                })

        self._server_start_thread = threading.Thread(
            target=prepare, name="server-prepare", daemon=True
        )
        self._server_start_thread.start()

    def _finish_server_start(self, payload):
        """Apply the worker result on the GUI thread and start serving."""
        payload = payload if isinstance(payload, dict) else {}
        cancel = self._server_start_cancel
        self._server_start_thread = None
        if not self._server_starting or (cancel is not None and cancel.is_set()):
            server_obj = payload.get("server")
            if server_obj is not None:
                try:
                    server_obj.stop()
                except Exception:
                    # reason: a cancelled server was never exposed to the user
                    pass
            return
        self._server_starting = False
        self._server_start_cancel = None
        if payload.get("cancelled"):
            self._append_log("Server start cancelled")
            self._update_server_ui()
            return
        if not payload.get("ok"):
            message = str(payload.get("error") or "Could not start the server.")
            self._append_log(f"Server error: {message}")
            self._show_server_error(message)
            self._update_server_ui()
            return

        chosen_port = int(payload.get("port"))
        configured_port = self._dependencies['clamp_int'](
            self.config.get("ServerPort", self._value('SERVER_PORT')),
            self._value('SERVER_PORT'), 1024, 65535,
        )
        if chosen_port != configured_port:
            self._append_log(
                f"Port {configured_port} is unavailable; using fallback port "
                f"{chosen_port} for this session."
            )
            # Session-only override: transient conflicts must never rewrite
            # the user's configured ServerPort on a later save.
            set_session = getattr(self.config, 'set_session', self.config.set)
            set_session("ServerPort", chosen_port)
            self._sync_connection_ui()

        self.server_obj = payload.get("server")
        if self.server_obj is None:
            self._append_log("Server error: no server object was prepared.")
            self._show_server_error("No server object was prepared.")
            self._update_server_ui()
            return

        def run(server_obj=self.server_obj):
            try:
                server_obj.run()
            except Exception as error:
                self.log_message.emit(f"Server error: {error}")

        self.server_thread = threading.Thread(
            target=run, name="server-serve", daemon=True
        )
        self.server_thread.start()
        self.server_running = True
        self.server_start_time = time.time()
        subscription_manager = self._subscription_manager()
        if subscription_manager is not None:
            subscription_manager.start()
        self._append_log(
            f"Server started on http://127.0.0.1:{chosen_port} "
            f"(backend: {self.server_obj.backend})"
        )
        self._update_server_ui()

        # Auto-update yt-dlp — throttled so a start never repeats the check.
        self._dependencies['maybe_auto_update_ytdlp'](
            self.config, self.dl_manager.active_count
        )

    def _stop_server(self):
        if self._server_starting:
            if self._server_start_cancel is not None:
                self._server_start_cancel.set()
            worker = self._server_start_thread
            if worker is not None and worker.is_alive():
                worker.join(timeout=2)
            self._server_start_thread = None
            self._server_starting = False
            self._server_start_cancel = None
            self._append_log("Server start cancelled")
            self._update_server_ui()
            return
        subscription_manager = self._subscription_manager()
        if subscription_manager is not None:
            subscription_manager.stop()
        if self.server_obj:
            try:
                self.server_obj.stop()
                if self.server_thread and self.server_thread.is_alive():
                    self.server_thread.join(timeout=2)
            except Exception as e:
                self._append_log(f"Server shutdown warning: {e}")
            self.server_obj = None
        self.server_thread = None
        self.server_running = False
        self.server_start_time = None
        self._append_log("Server stopped")
        self._update_server_ui()

    def _update_server_ui(self):
        if self._server_starting:
            self.status_dot.setProperty("tone", "neutral")
            self.status_dot.setAccessibleName(tr("Server status indicator: Starting"))
            self.status_label.setText(tr("Starting"))
            self.status_label.setProperty("tone", "neutral")
            self.status_label.setAccessibleName(tr("Server status: Starting"))
            self.dash_status.setText(tr("Starting server"))
            self.dash_hint.setText(tr("Checking local ports and preparing the API"))
            self.server_badge.setProperty("tone", "neutral")
            self.server_badge.setAccessibleName(
                tr("Extension server status indicator: Starting")
            )
            self._set_control_label(self.btn_startstop, tr("Starting server…"))
            set_line_icon(self.btn_startstop, "Starting server")
            self.btn_startstop.setProperty("class", "secondary")
            self.btn_startstop.setEnabled(False)
            self.tray_startstop.setText(tr("Starting server…"))
            self.tray_startstop.setEnabled(False)
            self.tray.setToolTip(
                tr_format(
                    "{app} · {status}",
                    app=self._value("APP_NAME"),
                    status=tr("Starting"),
                )
            )
            self._set_readiness("server", "Starting", "neutral")
        elif self.server_running:
            self.status_dot.setProperty("tone", "success")
            self.status_dot.setAccessibleName(tr("Server status indicator: Running"))
            self.status_label.setText(tr("Running"))
            self.status_label.setProperty("tone", "success")
            self.status_label.setAccessibleName(tr("Server status: Running"))
            self.dash_status.setText(tr("Server online"))
            self.dash_hint.setText(tr("Local only \u00b7 ready for Astra Deck"))
            self.server_badge.setProperty("tone", "success")
            self.server_badge.setAccessibleName(
                tr("Extension server status indicator: Online")
            )
            self._set_control_label(self.btn_startstop, tr("Stop server"))
            set_line_icon(self.btn_startstop, "Stop server")
            self.btn_startstop.setProperty("class", "secondary")
            self.btn_startstop.setEnabled(True)
            self.tray_startstop.setText(tr("Stop server"))
            self.tray_startstop.setEnabled(True)
            self.tray.setToolTip(
                tr_format(
                    "{app} · {status}",
                    app=self._value("APP_NAME"),
                    status=tr("Running"),
                )
            )
            self._set_readiness("server", "Running", "success")
        else:
            self.status_dot.setProperty("tone", "neutral")
            self.status_dot.setAccessibleName(tr("Server status indicator: Stopped"))
            self.status_label.setText(tr("Stopped"))
            self.status_label.setProperty("tone", "neutral")
            self.status_label.setAccessibleName(tr("Server status: Stopped"))
            self.dash_status.setText(tr("Server offline"))
            self.dash_hint.setText(tr("Local only \u00b7 start before downloading"))
            self.server_badge.setProperty("tone", "neutral")
            self.server_badge.setAccessibleName(
                tr("Extension server status indicator: Offline")
            )
            self._set_control_label(self.btn_startstop, tr("Start server"))
            set_line_icon(self.btn_startstop, "Start server")
            self.btn_startstop.setProperty("class", "primary")
            self.btn_startstop.setEnabled(True)
            self.tray_startstop.setText(tr("Start server"))
            self.tray_startstop.setEnabled(True)
            self.tray.setToolTip(
                tr_format(
                    "{app} · {status}",
                    app=self._value("APP_NAME"),
                    status=tr("Stopped"),
                )
            )
            self._set_readiness("server", "Stopped", "neutral")
        repolish(self.btn_startstop)
        repolish(self.server_badge)
        repolish(self.status_dot)
        repolish(self.status_label)
        # Every server state change lands here, so the empty log card follows
        # the same signal the badge and the start/stop button do.
        self._sync_log_empty_state()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _is_retryable(self, dl):
        """Ask the manager, which knows whether the recovery action was done.

        A runtime-missing failure stops being permanent the moment the runtime
        is installed; the failure code alone cannot see that.
        """
        ask = getattr(self.dl_manager, 'is_retryable', None)
        if callable(ask):
            return bool(ask(dl))
        return (dl.status == "skipped" or (
            dl.status == "failed"
            and dl.error_code in self._value('DOWNLOAD_RETRYABLE_ERROR_CODES')
        ) or (
            dl.status == "complete"
            and dl.error_code in self._value('DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES')
        ))

    def _download_host_backoff_seconds(self, dl):
        """Return a rounded host pause without making the GUI own policy."""
        remaining = getattr(self.dl_manager, 'host_backoff_remaining', None)
        if not callable(remaining):
            return 0
        try:
            return max(0, math.ceil(float(remaining(dl.url))))
        except (TypeError, ValueError, OverflowError, OSError):
            return 0

    def _download_recovery_text(self, dl):
        recovery_text = tr(dl.error_advice)
        if dl.error_code in {
            "rate-limited", "sign-in-required", "blocked-by-site",
        }:
            seconds = self._download_host_backoff_seconds(dl)
            if seconds:
                recovery_text = (
                    recovery_text
                    + "\n"
                    + tr("This host is paused. Retry in {duration}.").format(
                        duration=format_duration(seconds)
                    )
                )
        if dl.error_action:
            recovery_text = (
                recovery_text
                + "\n"
                + tr_format("Next: {action}", action=tr(dl.error_action))
            )
        return recovery_text

    def _download_card_structure(self, dl, recent=False):
        """Return the widget structure needed for a download's current state."""
        if recent:
            if dl.status == "failed" and self._is_retryable(dl):
                action = "retry"
            elif (
                dl.status == "complete"
                and dl.error_code in self._value('DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES')
            ):
                action = "retry-subtitles"
            elif dl.status == "skipped":
                # Nothing was written, so the whole recovery is "change the
                # setting the reason names, then run it again".
                action = "retry"
            elif dl.status == "complete" and dl.filename:
                action = "show"
            else:
                action = "none"
            phase = "recent"
        elif dl.status in self._value('DOWNLOAD_RUNNING_STATES'):
            action = "cancel"
            phase = "running"
        elif dl.status in self._value('DOWNLOAD_PENDING_STATES'):
            action = (
                "auth-cancel" if dl.status == "needs-auth"
                else "resume-cancel" if dl.status == "paused"
                else "reorder-cancel"
            )
            phase = "pending"
        else:
            action = "none"
            phase = "other"
        return recent, phase, action, bool(dl.error and dl.error_advice)

    def _download_meta_text(self, dl):
        meta_parts = []
        if dl.status in ("downloading", "merging", "extracting"):
            step = getattr(dl, 'step', None)
            if step == 'fetching':
                meta_parts.append(tr("Fetching metadata"))
            elif step == 'embedding':
                meta_parts.append(tr("Embedding metadata"))
            elif step == 'transcribing':
                meta_parts.append(tr("Generating subtitles"))
            meta_parts.append(f"{dl.progress:.1f}%")
        if dl.speed:
            meta_parts.append(dl.speed)
        if dl.eta:
            meta_parts.append(tr_format("ETA {eta}", eta=dl.eta))
        if dl.format:
            meta_parts.append(dl.format.upper())
        if dl.quality:
            meta_parts.append(str(dl.quality))
        if dl.status in self._value('DOWNLOAD_PENDING_STATES'):
            seconds = self._download_host_backoff_seconds(dl)
            if seconds:
                meta_parts.append(
                    tr("Host paused · retry in {duration}").format(
                        duration=format_duration(seconds)
                    )
                )
        if dl.error:
            meta_parts.append(dl.error)
        elif dl.filename:
            meta_parts.append(Path(dl.filename).name)
        return "  /  ".join(meta_parts) if meta_parts else dl.url

    def _update_download_card(self, card, dl):
        """Patch volatile card fields without replacing the focused widget."""
        refs = card._astra_refs
        card_state = dl.status if dl.status in (
            "failed", "cancelled", "skipped", "complete"
        ) else ""
        if card.property("state") != card_state:
            card.setProperty("state", card_state)
            repolish(card)

        refs["title"].setText(
            dl.title if dl.title and dl.title != "Unknown"
            else tr("Preparing download")
        )
        state_label = refs["state"]
        active_step = getattr(dl, "step", "")
        status_key = active_step if dl.status == "downloading" and active_step in ("fetching", "embedding", "transcribing") else dl.status
        translated_status = tr(human_status(status_key))
        state_label.setText(
            tr_format("●  {status}", status=translated_status)
        )
        state_label.setAccessibleName(
            tr("{title} status: {status}").format(
                title=dl.title or tr("Download"), status=translated_status
            )
        )
        tone = download_status_tone(dl.status)
        if state_label.property("tone") != tone:
            state_label.setProperty("tone", tone)
            repolish(state_label)

        progress = refs.get("progress")
        if progress is not None:
            progress.setValue(int(min(max(dl.progress, 0), 100)))
            progress.setAccessibleName(
                tr("{title} progress").format(title=dl.title or tr("Download"))
            )
            progress.setAccessibleDescription(
                tr("{progress} percent complete").format(
                    progress=f"{dl.progress:.1f}"
                )
            )
        refs["meta"].setText(self._download_meta_text(dl))

        recovery = refs.get("recovery")
        if recovery is not None:
            recovery.setText(self._download_recovery_text(dl))

    def _download_card(self, dl, recent=False):
        card = QFrame()
        card.setProperty("class", "download")
        card.setProperty("downloadId", dl.id)
        card.setObjectName(f"download_{dl.id}")
        if recent:
            # A terminal card carries one button when an immediate action is
            # useful; the rest of what you might want lives in its menu.
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda point, item=dl, widget=card: self._download_card_menu(
                    item, widget
                ).exec(widget.mapToGlobal(point))
            )
            card.setToolTip(
                tr("Right-click, or use More, for play, delete, copy and "
                   "download again.")
            )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(16, 13, 16, 13)
        card_l.setSpacing(9)

        top = QHBoxLayout()
        title = make_label(dl.title if dl.title and dl.title != "Unknown" else "Preparing download", "fieldLabel", word_wrap=True)
        top.addWidget(title, 1)
        state_label = make_state_label(human_status(dl.status), download_status_tone(dl.status))
        top.addWidget(state_label)
        # Repeated rows: every card carries the same words, so each control
        # is named for the download it acts on.
        card_target = title.text()
        if not recent and dl.status in self._value('DOWNLOAD_PENDING_STATES'):
            if dl.status != 'needs-auth':
                btn_up = self._make_tool_button("Up", "ghost", card_target)
                btn_up.setToolTip(tr("Move this pending download earlier."))
                btn_up.clicked.connect(
                    lambda checked=False, dl_id=dl.id: self._move_pending_download(dl_id, -1)
                )
                top.addWidget(btn_up)
                btn_down = self._make_tool_button("Down", "ghost", card_target)
                btn_down.setToolTip(tr("Move this pending download later."))
                btn_down.clicked.connect(
                    lambda checked=False, dl_id=dl.id: self._move_pending_download(dl_id, 1)
                )
                top.addWidget(btn_down)
            if dl.status == 'paused':
                # Per-item, like every other action on this row. This used to
                # call resume_intake(), which clears the global pause and
                # starts every paused download — so resuming one started all
                # of them.
                btn_resume = self._make_tool_button("Resume", "ghost", card_target)
                btn_resume.setToolTip(tr("Resume this download."))
                btn_resume.clicked.connect(
                    lambda checked=False, dl_id=dl.id: self._resume_one_download(dl_id)
                )
                top.addWidget(btn_resume)
            if (dl.status == 'needs-auth'
                    and not self._dependencies['is_youtube_url'](dl.url)):
                # The Sign-ins page is the fix for this state on every site the
                # extension's YouTube cookie bridge cannot reach, so the row
                # that reports it offers the way there instead of only Cancel.
                btn_signin = self._make_tool_button("Add sign-in", "ghost", card_target)
                btn_signin.setToolTip(
                    tr("Store this site's signed-in session so the download can run.")
                )
                btn_signin.clicked.connect(
                    lambda checked=False, url=dl.url: self._open_site_login_for(url)
                )
                top.addWidget(btn_signin)
            btn_cancel = self._make_tool_button("Cancel", "ghost", card_target)
            btn_cancel.clicked.connect(lambda checked=False, dl_id=dl.id: self.dl_manager.cancel(dl_id))
            top.addWidget(btn_cancel)
        elif not recent and dl.status in self._value('DOWNLOAD_RUNNING_STATES'):
            btn_cancel = self._make_tool_button("Cancel", "ghost", card_target)
            btn_cancel.clicked.connect(lambda checked=False, dl_id=dl.id: self.dl_manager.cancel(dl_id))
            top.addWidget(btn_cancel)
        elif recent and (
            (dl.status == "failed" and self._is_retryable(dl))
            or dl.status == "skipped"
        ):
            btn_retry = self._make_tool_button("Retry", "ghost", card_target)
            btn_retry.clicked.connect(lambda checked=False, item=dl: self._retry_download(item))
            top.addWidget(btn_retry)
        elif (
            recent
            and dl.status == "complete"
            and dl.error_code in self._value('DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES')
        ):
            btn_retry = self._make_tool_button("Retry subtitles", "ghost", card_target)
            btn_retry.setToolTip(tr("Generate subtitles again without downloading the media."))
            btn_retry.clicked.connect(lambda checked=False, item=dl: self._retry_download(item))
            top.addWidget(btn_retry)
        elif recent and dl.status == "complete" and dl.filename:
            btn_show = self._make_tool_button("Show", "ghost", card_target)
            btn_show.clicked.connect(lambda checked=False, path=dl.filename: self._show_download_location(path))
            top.addWidget(btn_show)
        if recent:
            btn_more = self._make_tool_button("More", "ghost", card_target)
            btn_more.setToolTip(
                tr("Play, reveal, delete, copy the link or error, or download "
                   "this again.")
            )
            btn_more.clicked.connect(
                lambda checked=False, item=dl, widget=card, anchor=btn_more:
                self._open_download_card_menu(item, widget, anchor)
            )
            top.addWidget(btn_more)
        card_l.addLayout(top)

        bar = None
        if dl.status in self._value('DOWNLOAD_RUNNING_STATES'):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(min(max(dl.progress, 0), 100)))
            bar.setTextVisible(False)
            card_l.addWidget(bar)

        meta = make_label(self._download_meta_text(dl), "fieldHint", word_wrap=True)
        card_l.addWidget(meta)
        recovery_label = None
        if dl.error and dl.error_advice:
            recovery_label = make_label(
                self._download_recovery_text(dl), "errorCallout", word_wrap=True
            )
            card_l.addWidget(recovery_label)
        card._astra_structure = self._download_card_structure(dl, recent)
        card._astra_refs = {
            "title": title,
            "state": state_label,
            "progress": bar,
            "meta": meta,
            "recovery": recovery_label,
        }
        self._update_download_card(card, dl)
        return card

    def _reconcile_download_list(self, active, pending, recent):
        """Key the queue layout by download id and retain unchanged widgets."""
        layout = self.downloads_list_layout
        scroll_bar = self.downloads_scroll.verticalScrollBar()
        scroll_value = scroll_bar.value()
        focused = QApplication.focusWidget()
        focused_entry = next((
            (key, widget) for key, widget in self._download_widgets.items()
            if focused is not None
            and (focused is widget or widget.isAncestorOf(focused))
        ), (None, None))
        focused_key, focused_owner = focused_entry
        # A card is destroyed and rebuilt on every status transition, so
        # identity is not enough to restore focus: a keyboard user sitting on
        # Cancel loses focus to nowhere the moment the download completes.
        # Remember which control it was, not which object.
        focused_action = focused.text() if isinstance(focused, QPushButton) else ''
        desired = []

        def retain(key, factory):
            widget = self._download_widgets.get(key)
            if widget is None:
                widget = factory()
                self._download_widgets[key] = widget
            desired.append((key, widget))
            return widget

        if not active and not pending and not recent:
            retain(("empty",), lambda: make_empty_state(
                "Nothing downloading yet",
                "Paste a video link above to start. Downloads sent from the "
                "Astra Deck browser extension land here too.",
                "Paste a link",
                self._focus_download_url,
            ))
        for section_key, section_title, downloads, is_recent in (
            ("active", "In progress", active, False),
            ("pending", "Pending", pending, False),
            ("recent", "Recent activity", recent[:8], True),
        ):
            if not downloads:
                continue
            retain(("section", section_key), lambda title=section_title: make_section_label(title))
            for dl in downloads:
                key = ("download", dl.id)
                card = self._download_widgets.get(key)
                structure = self._download_card_structure(dl, is_recent)
                if card is None or getattr(card, "_astra_structure", None) != structure:
                    if card is not None:
                        layout.removeWidget(card)
                        card.deleteLater()
                    card = self._download_card(dl, recent=is_recent)
                    self._download_widgets[key] = card
                else:
                    self._update_download_card(card, dl)
                desired.append((key, card))

        def make_spacer():
            spacer = QWidget()
            spacer.setObjectName("downloads_list_spacer")
            spacer.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Expanding,
            )
            return spacer

        retain(("spacer",), make_spacer)
        desired_keys = {key for key, _widget in desired}
        for key in tuple(self._download_widgets):
            if key in desired_keys:
                continue
            widget = self._download_widgets.pop(key)
            layout.removeWidget(widget)
            widget.deleteLater()

        for index, (_key, widget) in enumerate(desired):
            item = layout.itemAt(index)
            if item is not None and item.widget() is widget:
                continue
            layout.removeWidget(widget)
            layout.insertWidget(index, widget)

        layout.activate()
        scroll_bar.setValue(min(scroll_value, scroll_bar.maximum()))
        if focused_key in desired_keys and focused is not None:
            owner = self._download_widgets.get(focused_key)
            if owner is focused_owner:
                focused.setFocus(Qt.FocusReason.OtherFocusReason)
            elif owner is not None:
                # The card was rebuilt. Land on the same action if it still
                # exists — a completed download has no Cancel — and on the card
                # itself otherwise, so focus stays where the user was reading.
                replacement = next((
                    button for button in owner.findChildren(QPushButton)
                    if button.text() == focused_action and focused_action
                ), None)
                if replacement is None:
                    replacement = next(iter(owner.findChildren(QPushButton)), None)
                if replacement is None:
                    owner.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                    replacement = owner
                replacement.setFocus(Qt.FocusReason.OtherFocusReason)

    def _notify_completed_downloads(self, downloads):
        """Notify once for each terminal outcome the user cannot already see."""
        present = {d.id for d in downloads}
        # Prune ids that left the active queue so the set can't grow unbounded.
        self._seen_complete &= present
        failed = [d for d in downloads if d.status == 'failed']
        failed_ids = {d.id for d in failed}
        seen_failures = getattr(self, '_seen_failures', {})
        self._seen_failures = {
            dl_id: marker for dl_id, marker in seen_failures.items()
            if dl_id in failed_ids
        }
        # `skipped` finishes the same way a completion does — the queue slot is
        # released and the user is done waiting — so it notifies too, with the
        # reason as the body. Without this a minimized companion said nothing
        # at all about a download that produced no file.
        newly_complete = [d for d in downloads
                          if d.status in ('complete', 'skipped')
                          and d.id not in self._seen_complete]
        failure_markers = {
            d.id: (
                getattr(d, 'start_time', None),
                getattr(d, 'finished_time', None),
            )
            for d in failed
        }
        newly_failed = [
            d for d in failed
            if self._seen_failures.get(d.id) != failure_markers[d.id]
        ]
        if not newly_complete and not newly_failed:
            return
        out_of_sight = self.isHidden() or self.isMinimized()
        notify_complete = (
            self.config.get("NotifyOnComplete", True) and out_of_sight
        )
        notify_failure = (
            self.config.get("NotifyOnFailure", True) and out_of_sight
        )
        for d in newly_complete:
            self._seen_complete.add(d.id)
            if notify_complete:
                title = (getattr(d, 'title', '') or '').strip() or 'Your download is finished.'
                skipped = d.status == 'skipped'
                if skipped:
                    heading = tr("Nothing downloaded")
                    body = (getattr(d, 'error', '') or '').strip() or title
                else:
                    heading = tr("Download complete")
                    body = title
                try:
                    self.tray.showMessage(
                        heading, body,
                        QSystemTrayIcon.MessageIcon.Warning if skipped
                        else QSystemTrayIcon.MessageIcon.Information,
                        4000,
                    )
                    # Windows exposes no per-message identity. Keep the most
                    # recent successful showMessage call as the click target.
                    self._last_notified_file = getattr(d, 'filename', '') or ''
                    self._last_notified_download_id = d.id
                    self._last_notification_kind = "completion"
                except Exception:
                    # reason: tray notifications are best-effort polish
                    pass
        for d in newly_failed:
            self._seen_failures[d.id] = failure_markers[d.id]
            if not notify_failure:
                continue
            raw_reason = (
                getattr(d, 'error', '')
                or getattr(d, 'error_advice', '')
                or tr("No failure details were recorded.")
            )
            reason = " ".join(tr(str(raw_reason)).split())
            if not reason:
                reason = tr("No failure details were recorded.")
            if len(reason) > 240:
                reason = reason[:237].rstrip() + "..."
            try:
                self.tray.showMessage(
                    tr("Download failed"),
                    reason,
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )
                self._last_notified_file = ""
                self._last_notified_download_id = d.id
                self._last_notification_kind = "failure"
                # quick_download_status is a StatusLabel. Its setText path
                # posts the QAccessible Alert introduced for status messages.
                self._set_quick_download_status(
                    tr_format("Download failed: {reason}", reason=reason),
                    "error",
                )
            except Exception:
                # reason: tray notifications are best-effort polish
                pass

    def _request_ui_refresh(self):
        """Collapse a burst of progress signals into one refresh.

        A single download emits several progress lines per second and three can
        run at once; every one of them used to rebuild the queue list on the
        GUI thread, on top of the 500 ms timer that would have done it anyway.
        """
        if not self._ui_refresh_timer.isActive():
            self._ui_refresh_timer.start()

    def _update_ui(self):
        self._ui_refresh_timer.stop()
        if self.server_running and self.server_thread and not self.server_thread.is_alive():
            self.server_running = False
            self.server_start_time = None
            self.server_obj = None
            self._append_log("Server stopped unexpectedly")
            self._update_server_ui()

        # Stats
        self.stat_active.setText(str(self.dl_manager.active_count()))
        self.stat_completed.setText(str(self.dl_manager.total_completed))
        self._update_taskbar_progress()
        if self.tabs.currentIndex() == self._page_names.index("Subscriptions"):
            self._refresh_subscriptions()
        if self.server_start_time:
            elapsed = time.time() - self.server_start_time
            if elapsed >= 3600:
                self.stat_uptime.setText(f"{elapsed/3600:.0f}h")
            elif elapsed >= 60:
                self.stat_uptime.setText(f"{elapsed/60:.0f}m")
            else:
                self.stat_uptime.setText(f"{elapsed:.0f}s")
        else:
            self.stat_uptime.setText("--")

        # Downloads tab
        downloads = self.dl_manager.snapshot()
        self._notify_completed_downloads(downloads)
        active = [d for d in downloads if d.status in self._value('DOWNLOAD_RUNNING_STATES')]
        pending = [d for d in downloads if d.status in self._value('DOWNLOAD_PENDING_STATES')]
        # Every terminal status belongs here. A hardcoded tuple used to leave
        # `skipped` out of all three buckets, so a download that wrote no file
        # rendered nowhere at all — the silent outcome that status exists to
        # make visible.
        recent = [d for d in downloads
                  if d.status in self._value('DOWNLOAD_TERMINAL_STATES')]
        active.sort(key=lambda d: d.start_time)
        pending.sort(key=lambda d: (d.queue_order, d.start_time))
        recent.sort(key=lambda d: d.start_time, reverse=True)
        read_notice = getattr(self.dl_manager, 'persistence_notice', None)
        notice = read_notice() if callable(read_notice) else ''
        if notice != self.persistence_notice.text():
            self.persistence_notice.setText(notice)
            self.persistence_notice.setVisible(bool(notice))
            if notice:
                self._append_log(notice)
        capacity = self.dl_manager.capacity()
        self.queue_capacity_badge.setText(
            tr_format(
                "{total} / {limit} jobs",
                total=capacity["total"],
                limit=capacity["totalLimit"],
            )
        )
        pause_label = (
            tr("Resume queue") if capacity['intakePaused'] else tr("Pause intake")
        )
        self._set_control_label(self.btn_queue_pause, pause_label)
        set_line_icon(
            self.btn_queue_pause,
            "Resume queue" if capacity['intakePaused'] else "Pause intake",
        )
        self.btn_queue_pause.setToolTip(
            tr(
                "Resume pending downloads explicitly. Items needing sign-in remain paused."
            )
            if capacity['intakePaused'] else
            tr("Pause starting pending downloads. Downloads already running will continue.")
        )
        signature = tuple(
            (d.id, d.status, d.queue_order, round(d.progress, 1), d.speed, d.eta,
             d.title, d.error, d.error_code, d.error_advice, d.error_action,
             d.filename, d.format, d.quality, d.url,
             self._download_host_backoff_seconds(d))
            for d in active + pending + recent[:8]
        ) + ((capacity['intakePaused'], capacity['total']),)
        if signature == self._downloads_signature:
            return
        self._downloads_signature = signature

        self._reconcile_download_list(active, pending, recent)

    def _history_query(self, *, entries=None, offset=None, limit=None):
        archive_entries = None
        manager = self._subscription_manager()
        archive_reader = None
        if manager is not None:
            # Prefer the scalar projection: the full archive_entries() deep
            # copy is a multi-megabyte, lock-held operation at the 20k cap.
            archive_reader = getattr(manager, "archive_history_view", None)                 or getattr(manager, "archive_entries", None)
        if callable(archive_reader):
            try:
                archive_entries = archive_reader()
            except Exception:
                # A broken subscription state must not turn an otherwise
                # readable download history into an empty error page.
                # reason: a broken subscription state must not turn a readable download history into an empty error page
                archive_entries = None
        return self._dependencies['query_history_entries'](
            self.history_mgr.load() if entries is None else entries,
            query=self.history_search.text(),
            status=self.history_status.currentData() or "",
            fmt=self.history_format.currentData() or "",
            date_from=self.history_date_from.text().strip(),
            date_to=self.history_date_to.text().strip(),
            sort=self.history_sort.currentData() or "newest",
            offset=self._history_offset if offset is None else offset,
            limit=self._history_page_size if limit is None else limit,
            archive_entries=archive_entries,
        )

    def _history_retention_limit(self):
        reader = getattr(self.history_mgr, "retention_limit", None)
        if callable(reader):
            try:
                return int(reader())
            except (TypeError, ValueError, OverflowError):
                # reason: a malformed live value falls back to the sanitized config below
                pass
        return self._dependencies['clamp_int'](
            self.config.get("HistoryRetentionLimit"),
            self._value('HISTORY_RETENTION_DEFAULT'),
            self._value('HISTORY_RETENTION_MIN'),
            self._value('HISTORY_RETENTION_MAX'),
        )

    def _history_is_quarantined(self):
        """Return whether the history store was replaced after an unreadable file."""
        resolve = getattr(self.history_mgr, "_resolve_path", None)
        read = self._dependencies.get("quarantined_state_files")
        if not callable(resolve) or not callable(read):
            return False
        try:
            target = Path(resolve()).resolve()
        except (OSError, TypeError, ValueError):
            return False
        try:
            entries = read() or []
        except Exception:
            # reason: an unreadable history is not evidence of quarantine
            return False
        for entry in entries:
            try:
                if Path(entry.get("path", "")).resolve() == target:
                    return True
            except (AttributeError, OSError, TypeError, ValueError):
                continue
        return False

    def _history_filters_changed(self, *_args):
        # Every keystroke in the search box used to re-read and re-sanitise
        # history.json and rebuild up to 50 widgets. Wait for a pause instead.
        self._history_offset = 0
        self._history_filter_timer.start()

    def _apply_history_filters(self):
        self._history_filter_timer.stop()
        self._refresh_history()

    def _report_history_date_filters(self, result):
        """Mark and explain a saved-date bound the filter could not use.

        A bound that is not YYYY-MM-DD used to be compared as raw text
        against every row, so `2026-8-1` or a date typed the American way
        hid the whole list and the only thing on screen was the ordinary
        "no matching downloads" panel.
        """
        unreadable = result.get("unreadableDates") or []
        self._set_input_error(self.history_date_from, "from" in unreadable)
        self._set_input_error(self.history_date_to, "to" in unreadable)
        # Each of these stays a literal in the call position. Routed through a
        # `note` variable they leave the extractor's sight and never reach a
        # catalogue, and the coverage gate cannot tell: a string that stops
        # being extracted only shrinks the denominator.
        if len(unreadable) > 1:
            self._show_history_status(
                "Both dates need to be YYYY-MM-DD, so neither is being used.",
                "warning", log=False,
            )
        elif "from" in unreadable:
            self._show_history_status(
                "The saved-from date needs to be YYYY-MM-DD, so it is not being used.",
                "warning", log=False,
            )
        elif "to" in unreadable:
            self._show_history_status(
                "The through date needs to be YYYY-MM-DD, so it is not being used.",
                "warning", log=False,
            )
        elif (
            result.get("dateFrom")
            and result.get("dateTo")
            and result["dateFrom"] > result["dateTo"]
        ):
            self._show_history_status(
                "The saved-from date is after the through date, so nothing can match.",
                "warning", log=False,
            )
        elif getattr(self, "_history_status_is_filter_note", False):
            self._history_status_is_filter_note = False
            self.history_page_status.clear()
            self.history_page_status.hide()

    def _move_history_page(self, direction):
        direction = -1 if direction < 0 else 1
        next_offset = self._history_offset + (direction * self._history_page_size)
        self._history_offset = max(0, next_offset)
        self._refresh_history()

    # Every settings widget, the config key behind it, and how to write a
    # value into it. An import replaces the stored settings underneath a form
    # that is already on screen, and a stale form is not merely cosmetic: the
    # next Save would write the pre-import values straight back over the
    # import. This is also the one place that knows the full list, so a new
    # setting missing from it shows up as a field the import cannot refresh.
    _SETTINGS_FORM_FIELDS = (
        ("cfg_site_profiles", "SiteProfiles", "text"),
        ("cfg_dl_path", "DownloadPath", "text"),
        ("cfg_audio_path", "AudioDownloadPath", "text"),
        ("cfg_history_retention", "HistoryRetentionLimit", "number"),
        ("cfg_outtmpl", "OutputTemplate", "text"),
        ("cfg_windows_filenames", "WindowsFilenames", "check"),
        ("cfg_sublangs", "SubLangs", "text"),
        ("cfg_subtitle_sleep", "SubtitleSleepSeconds", "decimal"),
        ("cfg_ratelimit", "RateLimit", "text"),
        ("cfg_throttled", "ThrottledRate", "text"),
        ("cfg_proxy", "Proxy", "text"),
        ("cfg_use_system_proxy", "UseSystemProxy", "check"),
        ("cfg_source_address", "SourceAddress", "text"),
        ("cfg_xff", "Xff", "text"),
        ("cfg_geo_verification_proxy", "GeoVerificationProxy", "text"),
        ("cfg_playlist_dateafter", "PlaylistDateAfter", "text"),
        ("cfg_metadata", "EmbedMetadata", "check"),
        ("cfg_thumbnail", "EmbedThumbnail", "check"),
        ("cfg_chapters", "EmbedChapters", "check"),
        ("cfg_subs", "EmbedSubs", "check"),
        ("cfg_generate_subtitles", "GenerateSubtitles", "check"),
        ("cfg_keep_intermediates", "KeepIntermediateFiles", "check"),
        ("cfg_write_info", "WriteInfoJson", "check"),
        ("cfg_write_nfo", "WriteNfo", "check"),
        ("cfg_write_description", "WriteDescription", "check"),
        ("cfg_write_thumbnail", "WriteThumbnail", "check"),
        ("cfg_split_chapters", "SplitChapters", "check"),
        ("cfg_live_from_start", "LiveFromStart", "check"),
        ("cfg_verify_formats", "VerifyFormats", "check"),
        ("cfg_sponsorblock", "SponsorBlock", "check"),
        ("cfg_autoupdate", "AutoUpdateYtDlp", "check"),
        ("cfg_closetotray", "CloseToTray", "check"),
        ("cfg_startmin", "StartMinimized", "check"),
        ("cfg_notify", "NotifyOnComplete", "check"),
        ("cfg_notify_failure", "NotifyOnFailure", "check"),
        ("cfg_clipboard", "ClipboardLinkGrabber", "check"),
        ("cfg_port", "ServerPort", "number"),
        ("cfg_fragments", "ConcurrentFragments", "number"),
        ("cfg_maxconcurrent", "MaxConcurrentDownloads", "number"),
        ("cfg_retries", "DownloadRetries", "number"),
        ("cfg_socket_timeout", "SocketTimeoutSeconds", "number"),
        ("cfg_extractor_retries", "ExtractorRetries", "number"),
        ("cfg_sleep_interval", "SleepIntervalSeconds", "number"),
        ("cfg_sleep_max", "MaxSleepIntervalSeconds", "number"),
        ("cfg_pacing_jitter", "PacingJitterPercent", "number"),
        ("cfg_sleep_requests", "SleepRequestsSeconds", "number"),
        ("cfg_wait_for_video", "WaitForVideoSeconds", "number"),
        ("cfg_playlist_max", "PlaylistMaxItems", "number"),
        ("cfg_playlist_min_duration", "PlaylistMinDurationSeconds", "number"),
        ("cfg_playlist_max_duration", "PlaylistMaxDurationSeconds", "number"),
        ("cfg_maxsize", "MaxFileSizeMB", "number"),
        ("cfg_sb_action", "SponsorBlockAction", "combo"),
        ("cfg_js_runtime", "JavaScriptRuntime", "combo"),
        ("cfg_ytdlp_channel", "YtDlpUpdateChannel", "combo"),
        ("cfg_video_codec", "VideoCodecPreference", "combo"),
        ("cfg_audio_codec", "AudioCodecPreference", "combo"),
        ("cfg_frame_rate", "PreferredFrameRate", "combo"),
        ("cfg_prefer_original", "PreferOriginalOverUpscaled", "check"),
        ("cfg_impersonate", "ImpersonateTarget", "combo"),
        ("cfg_force_ip_version", "ForceIPVersion", "combo"),
        ("cfg_subtitle_mode", "SubtitleMode", "combo"),
        ("cfg_subtitle_format", "SubtitleFormat", "combo"),
        ("cfg_theme", "Theme", "combo"),
        ("cfg_language", "Language", "combo"),
    )

    def _settings_change_signals(self):
        """Yield the change signals for every editable settings control.

        The form registry is the source of truth for settings controls. A
        hand-maintained signal tuple used to drift whenever a new field was
        added, leaving changes silently discardable. SponsorBlock categories
        are the one compound field: their individual checkboxes are wired
        after the registry entries so they share the same dirty-state path.
        """
        signal_names = {
            "text": "textChanged",
            "check": "toggled",
            "number": "valueChanged",
            "decimal": "valueChanged",
            "combo": "currentIndexChanged",
        }
        for attribute, _key, kind in self._SETTINGS_FORM_FIELDS:
            widget = getattr(self, attribute, None)
            signal_name = signal_names.get(kind)
            signal = getattr(widget, signal_name, None) if signal_name else None
            if signal is not None:
                yield signal
        for widget in getattr(self, "cfg_sb_categories", {}).values():
            yield widget.toggled

    def _reload_settings_form(self):
        """Redraw the settings form from the stored config."""
        refreshed = 0
        for attribute, key, kind in self._SETTINGS_FORM_FIELDS:
            widget = getattr(self, attribute, None)
            if widget is None:
                continue
            value = self.config.get(key, self._value('DEFAULT_CONFIG').get(key))
            widget.blockSignals(True)
            try:
                if kind == "text":
                    if hasattr(widget, "setPlainText"):
                        widget.setPlainText(json.dumps(
                            value if isinstance(value, list) else [],
                            indent=2,
                            ensure_ascii=False,
                        ))
                    else:
                        widget.setText(str(value or ""))
                elif kind == "check":
                    widget.setChecked(bool(value))
                elif kind == "number":
                    widget.setValue(int(value or 0))
                elif kind == "decimal":
                    widget.setValue(float(value or 0))
                elif kind == "combo":
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                refreshed += 1
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not refresh {key}: {error}")
            finally:
                widget.blockSignals(False)
        # SponsorBlock categories are a dict of checkboxes rather than one
        # widget, so they do not fit the table above.
        selected = {
            item.strip() for item in
            str(self.config.get("SponsorBlockCategories", "") or "").split(",")
            if item.strip()
        }
        for name, box in getattr(self, "cfg_sb_categories", {}).items():
            box.blockSignals(True)
            box.setChecked(not selected or name in selected)
            box.blockSignals(False)
        self._sync_sublang_checkboxes(self.cfg_sublangs.text())
        self._rebuild_quick_site_profiles()
        self._update_output_template_preview()
        # Signals stay blocked throughout, so refreshing the form does not
        # mark it dirty — the import's own status line is left standing.
        return refreshed

    def _restore_default_settings(self):
        """Restore the editable Settings form and report what changed."""
        defaults = self._value("DEFAULT_CONFIG")
        keys = [key for _attribute, key, _kind in self._SETTINGS_FORM_FIELDS]
        keys.append("SponsorBlockCategories")
        values = {key: defaults.get(key) for key in dict.fromkeys(keys)}
        persisted_get = getattr(self.config, "get_persisted", self.config.get)
        current = {
            key: persisted_get(key, defaults.get(key))
            for key in values
        }
        changed = [key for key in values if current.get(key) != values[key]]
        if not changed:
            self._show_settings_status(
                tr("Settings already use their defaults."), "neutral"
            )
            return False

        undo_snapshot = {"settings": current}
        if not self._save_config_undo("restoreDefaults", undo_snapshot):
            self._show_settings_status(
                tr(
                    "Could not prepare the defaults undo snapshot. Nothing changed; "
                    "check disk permissions and retry."
                ),
                "danger",
            )
            return False
        old_port = self._dependencies["clamp_int"](
            persisted_get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        old_effective_port = self._dependencies["clamp_int"](
            self.config.get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        old_language = self.config.get("Language", "system")
        old_theme = self.config.get("Theme", "system")
        update = getattr(self.config, "update", None)
        if not callable(update):
            self._show_settings_status(
                tr("Could not restore defaults. Nothing changed; check disk permissions and retry."),
                "danger",
            )
            return False
        try:
            saved = bool(update(values))
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not restore settings defaults: {error}")
            saved = False
        if not saved:
            self._clear_config_undo("restoreDefaults")
            self._show_settings_status(
                tr("Could not restore defaults. Nothing changed; check disk permissions and retry."),
                "danger",
            )
            return False

        self._reload_settings_form()
        if self.config.get("Theme", "system") != old_theme:
            apply_theme = self._dependencies.get("apply_theme")
            if callable(apply_theme):
                try:
                    apply_theme(self.config.get("Theme", "system"))
                except Exception as error:  # noqa: BLE001
                    self._append_log(f"Could not apply the selected theme: {error}")
        self._dependencies["reset_deno_runtime_cache"]()
        self._start_readiness_probe()
        restarted_server = self._apply_saved_server_port(
            old_port, old_effective_port
        )

        labels = []
        for key in changed:
            if key == "SponsorBlockCategories":
                labels.append(tr("SponsorBlock categories"))
                continue
            attribute = next(
                (
                    attribute for attribute, field_key, _kind
                    in self._SETTINGS_FORM_FIELDS
                    if field_key == key
                ),
                "",
            )
            widget = getattr(self, attribute, None)
            label = widget.accessibleName() if widget is not None else ""
            labels.append(label or key)
        summary = tr(
            "Restored defaults for {count} settings: {names}."
        ).format(count=len(changed), names=", ".join(labels))
        if restarted_server:
            summary = tr("Settings restored and server restarted.") + " " + summary
        elif old_language != values.get("Language"):
            summary = tr(
                "Settings restored. Restart Astra Downloader to apply the language."
            ) + " " + summary
        self._restore_defaults_undo = undo_snapshot
        self._set_settings_filter_hidden(self.btn_undo_restore_defaults, False)
        self._show_settings_status(summary, "success")
        self._append_log(
            "Restored Settings defaults: " + ", ".join(changed)
        )
        return True

    def _undo_restore_defaults(self):
        """Restore the settings that preceded the last Restore defaults action."""
        snapshot = self._restore_defaults_undo
        settings = snapshot.get("settings") if isinstance(snapshot, dict) else None
        if not isinstance(settings, dict) or not settings:
            self._set_settings_filter_hidden(self.btn_undo_restore_defaults, True)
            self._show_settings_status(
                tr("No Restore defaults action is available to undo."), "warning"
            )
            return False

        persisted_get = getattr(self.config, "get_persisted", self.config.get)
        old_port = self._dependencies["clamp_int"](
            persisted_get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        old_effective_port = self._dependencies["clamp_int"](
            self.config.get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        old_language = self.config.get("Language", "system")
        old_theme = self.config.get("Theme", "system")
        update = getattr(self.config, "update", None)
        if not callable(update):
            self._show_settings_status(
                tr(
                    "Could not restore the previous settings. The Undo snapshot is "
                    "still available; check disk permissions and retry."
                ),
                "danger",
            )
            return False
        try:
            restored = bool(update(settings))
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not undo Restore defaults: {error}")
            restored = False
        if not restored:
            self._show_settings_status(
                tr(
                    "Could not restore the previous settings. The Undo snapshot is "
                    "still available; check disk permissions and retry."
                ),
                "danger",
            )
            return False

        self._reload_settings_form()
        if self.config.get("Theme", "system") != old_theme:
            apply_theme = self._dependencies.get("apply_theme")
            if callable(apply_theme):
                try:
                    apply_theme(self.config.get("Theme", "system"))
                except Exception as error:  # noqa: BLE001
                    self._append_log(f"Could not apply the selected theme: {error}")
        self._dependencies["reset_deno_runtime_cache"]()
        self._start_readiness_probe()
        restarted_server = self._apply_saved_server_port(
            old_port, old_effective_port
        )

        journal_cleared = self._clear_config_undo("restoreDefaults")
        if journal_cleared:
            self._restore_defaults_undo = None
            self._set_settings_filter_hidden(self.btn_undo_restore_defaults, True)
        message = tr("Settings from before Restore defaults were restored.")
        if restarted_server:
            message = tr("Settings restored and server restarted.") + " " + message
        elif old_language != settings.get("Language"):
            message = tr(
                "Settings restored. Restart Astra Downloader to apply the language."
            ) + " " + message
        if not journal_cleared:
            message += " " + tr(
                "The Undo record is still available; clear it before closing."
            )
        self._show_settings_status(
            message, "success" if journal_cleared else "warning"
        )
        self._append_log("Undid Restore defaults")
        return True

    def _export_settings_bundle(self):
        """Write settings and subscriptions to a portable JSON bundle."""
        manager = self._subscription_manager()
        subscriptions = []
        if manager is not None:
            try:
                subscriptions = manager.list_subscriptions()
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read subscriptions: {error}")
        sites = []
        try:
            sites = self.dl_manager.site_logins.entries()
        except Exception as error:
            self._append_log(f"Could not read stored sign-ins: {error}")
        bundle = self._dependencies['build_settings_bundle'](
            self.config, subscriptions, sites,
            app_version=self._value('APP_VERSION'),
            now=time.time(),
        )
        suggested = Path(
            self.config.get("DownloadPath", str(Path.home()))
        ) / "astra-downloader-settings.json"
        path, _selected = QFileDialog.getSaveFileName(
            self, tr("Export settings"), str(suggested), "JSON files (*.json)"
        )
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8", newline="") as output:
                json.dump(bundle, output, indent=2, ensure_ascii=False)
        except OSError as error:
            self._show_settings_status(
                tr_format(
                    "Could not write the bundle: {error} Choose a folder you "
                    "can write to, then export again.",
                    error=short_error_text(error),
                ),
                "danger",
            )
            return False
        summary = tr_format(
            "Exported {settings} settings and {subscriptions} subscriptions.",
            settings=len(bundle["settings"]),
            subscriptions=len(bundle["subscriptions"]),
        )
        if bundle["siteLoginSites"]:
            # Say it plainly rather than letting the user discover it on the
            # other machine: this file will not sign them back in.
            summary += " " + tr_format(
                "{count} stored sign-ins are listed by site only. "
                "Add them again after importing.",
                count=len(bundle["siteLoginSites"]),
            )
        self._show_settings_status(summary, "success")
        self._append_log(f"Settings bundle written to {path}")
        return True

    def _import_settings_bundle(self):
        """Apply a bundle, then say what it actually changed."""
        path, _selected = QFileDialog.getOpenFileName(
            self, tr("Import settings"),
            str(Path(self.config.get("DownloadPath", str(Path.home())))),
            "JSON files (*.json)",
        )
        if not path:
            return False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as error:
            self._show_settings_status(
                tr_format(
                    "Could not read that bundle: {error} Choose a bundle "
                    "exported by Astra Downloader, then import again.",
                    error=short_error_text(error),
                ),
                "danger",
            )
            return False
        bundle, error = self._dependencies['read_settings_bundle'](payload)
        if error:
            self._show_settings_status(error, "danger")
            return False
        changes = self._dependencies['describe_bundle_changes'](
            self.config, bundle)
        # Capture the incoming keys before the write. The bundle boundary has
        # already excluded secrets, and the adjacent config journal makes this
        # recovery survive a restart instead of living only on the window.
        persisted_get = getattr(self.config, "get_persisted", self.config.get)
        previous_settings = {
            key: persisted_get(
                key, self._value('DEFAULT_CONFIG').get(key)
            )
            for key in bundle["settings"]
        }
        self._settings_import_undo = {
            "settings": previous_settings,
            "subscriptionIds": [],
        }
        if not self._save_config_undo(
            "settingsImport", self._settings_import_undo
        ):
            self._settings_import_undo = None
            self._show_settings_status(
                tr(
                    "Could not prepare the import undo snapshot. Nothing changed; "
                    "check disk permissions and retry."
                ),
                "danger",
            )
            return False
        previous_port = self._dependencies['clamp_int'](
            self.config.get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        if not self.config.update(bundle["settings"]):
            self._clear_config_undo("settingsImport")
            self._settings_import_undo = None
            self._show_settings_status(
                "Could not save the imported settings. Check disk space and "
                "permissions, then retry.",
                "danger",
            )
            return False
        manager = self._subscription_manager()
        added, skipped = 0, 0
        added_subscription_ids = []
        import_undo_warning = False
        for record in bundle["subscriptions"]:
            if manager is None:
                break
            created, add_error = manager.add_subscription(
                record["url"],
                interval_minutes=record["intervalMinutes"],
                enabled=record["enabled"],
                title=record["title"],
                delivery=record.get("delivery"),
            )
            if add_error:
                # A subscription already present is the ordinary case when
                # re-importing onto a machine that has some of them.
                skipped += 1
            else:
                added += 1
                if isinstance(created, dict) and created.get("id"):
                    added_subscription_ids.append(str(created["id"]))
                    self._settings_import_undo["subscriptionIds"] = list(
                        added_subscription_ids
                    )
                    if not self._save_config_undo(
                        "settingsImport", self._settings_import_undo
                    ):
                        # Keep the already-persisted prefix recoverable and
                        # avoid leaving the newest subscription without a
                        # durable undo record when the journal becomes
                        # unwritable mid-import.
                        removed, _remove_error = manager.remove_subscription(
                            str(created["id"])
                        )
                        if removed:
                            added -= 1
                            added_subscription_ids.pop()
                            self._settings_import_undo["subscriptionIds"] = list(
                                added_subscription_ids
                            )
                        self._show_settings_status(
                            tr(
                                "The import was only partly applied because its "
                                "Undo snapshot could not be saved."
                            ),
                            "danger",
                        )
                        import_undo_warning = True
                        break
        self._settings_import_undo["subscriptionIds"] = list(
            added_subscription_ids
        )
        self._set_settings_filter_hidden(self.btn_undo_settings_import, False)
        changed_labels = []
        for key in changes["settings"]:
            attribute = next(
                (
                    attribute for attribute, field_key, _kind
                    in self._SETTINGS_FORM_FIELDS
                    if field_key == key
                ),
                "",
            )
            widget = getattr(self, attribute, None)
            changed_labels.append(
                widget.accessibleName() if widget is not None else key
            )
        changed_summary = tr_format(
            "Imported {count} changed settings",
            count=len(changes["settings"]),
        )
        if changed_labels:
            changed_summary += ": " + ", ".join(changed_labels)
        parts = [changed_summary]
        if added or skipped:
            parts.append(
                tr_format(
                    "{added} subscriptions added, {skipped} already present",
                    added=added,
                    skipped=skipped,
                )
            )
        if changes["siteLoginSites"]:
            parts.append(
                tr_format(
                    "sign-ins still needed for {sites}",
                    sites=", ".join(changes["siteLoginSites"][:5]),
                )
            )
        excluded = changes.get("excludedSettings") or []
        if excluded:
            parts.append(
                tr_format("not carried: {settings}", settings=", ".join(excluded))
            )
        bundle_warnings = changes.get("warnings") or []
        parts.extend(str(warning) for warning in bundle_warnings[:5] if warning)
        if import_undo_warning:
            parts.append(
                tr("The import stopped before all subscriptions were added.")
            )
        self._show_settings_status(
            ". ".join(parts) + ".",
            "warning" if import_undo_warning or bundle_warnings else "success",
        )
        self._append_log(
            f"Imported settings bundle from {path}: "
            f"{', '.join(changes['settings']) or 'no setting changes'}"
        )
        # The form still shows the pre-import values until it is rebuilt.
        self._reload_settings_form()
        self._apply_saved_server_port(previous_port)
        return True

    def _undo_settings_import(self):
        snapshot = self._settings_import_undo
        if not snapshot:
            self._set_settings_filter_hidden(self.btn_undo_settings_import, True)
            self._show_settings_status(
                tr("No settings import is available to undo."), "warning"
            )
            return
        manager = self._subscription_manager()
        remaining = []
        for sub_id in snapshot.get("subscriptionIds", []):
            if manager is None:
                remaining.append(sub_id)
                continue
            try:
                removed, error = manager.remove_subscription(sub_id)
            except Exception as exc:  # noqa: BLE001
                removed, error = False, str(exc)
            if not removed or error:
                remaining.append(sub_id)
        snapshot["subscriptionIds"] = remaining
        journal_updated = self._save_config_undo("settingsImport", snapshot)
        previous_port = self._dependencies['clamp_int'](
            self.config.get("ServerPort", self._value("SERVER_PORT")),
            self._value("SERVER_PORT"), 1024, 65535,
        )
        try:
            restored = bool(self.config.update(snapshot.get("settings", {})))
        except Exception as error:  # noqa: BLE001
            self._append_log(f"Could not undo settings import: {error}")
            restored = False
        if not restored:
            self._show_settings_status(
                "Could not restore the imported settings. The Undo snapshot is "
                "still available; check disk space and permissions, then retry.",
                "error",
            )
            self._set_settings_filter_hidden(self.btn_undo_settings_import, False)
            return
        if remaining:
            self._settings_import_undo = snapshot
            self._show_settings_status(
                tr("Settings were restored, but some imported subscriptions remain."),
                "warning",
            )
            self._set_settings_filter_hidden(self.btn_undo_settings_import, False)
        else:
            journal_cleared = self._clear_config_undo("settingsImport")
            if journal_cleared:
                self._settings_import_undo = None
                self._set_settings_filter_hidden(self.btn_undo_settings_import, True)
            else:
                self._settings_import_undo = snapshot
                self._set_settings_filter_hidden(self.btn_undo_settings_import, False)
            message = tr("Settings import undone.")
            if not journal_cleared:
                message += " " + tr(
                    "The Undo record is still available; clear it before closing."
                )
            self._show_settings_status(
                message,
                "success" if journal_cleared else "warning",
            )
        if not journal_updated:
            self._show_settings_status(
                tr(
                    "Settings were restored, but the Undo record could not be "
                    "updated on disk."
                ),
                "warning",
            )
        self._reload_settings_form()
        self._refresh_subscriptions(force=True)
        self._apply_saved_server_port(previous_port)

    def _export_history(self):
        rows = []
        offset = 0
        page = 500
        while True:
            result = self._history_query(offset=offset, limit=page)
            chunk = result.get("history") or []
            if not chunk:
                break
            rows.extend(chunk)
            offset += len(chunk)
            total = result.get("filteredTotal")
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = 0
            if total:
                if offset >= total:
                    break
            elif len(chunk) < page:
                break
        if not rows:
            self._show_history_status(
                "No filtered history rows are available to export.", "warning")
            return
        default_path = Path(self.config.get("DownloadPath", str(Path.home())))
        suggested = default_path / "astra-download-history.csv"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("Export download history"),
            str(suggested),
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=(
                        "title", "filename", "format", "quality", "status",
                        "duration", "date", "url",
                    ),
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(
                    {
                        key: sanitize_csv_cell(value)
                        for key, value in row.items()
                    }
                    for row in rows
                )
        except OSError as error:
            self._show_history_status(
                tr_format(
                    "Could not export download history: {error} Choose a "
                    "folder you can write to, then export again.",
                    error=short_error_text(error),
                ),
                "error",
            )
            return
        self._show_history_status(
            tr_format(
                "Exported one filtered history row to {path}.", path=path,
            )
            if len(rows) == 1 else
            tr_format(
                "Exported {count} filtered history rows to {path}.",
                count=len(rows),
                path=path,
            ),
            "success",
        )

    def _refresh_history(self):
        self.history_meta.setText(tr("Loading history…"))
        self.btn_clear_history.setEnabled(False)
        self.btn_history_prev.setEnabled(False)
        self.btn_history_next.setEnabled(False)
        self.btn_export_history.setEnabled(False)
        self._clear_layout(self.history_container)

        load_error = None
        try:
            data = self.history_mgr.load()
        except Exception as error:  # noqa: BLE001
            data = []
            load_error = str(error)
        unreadable = self._history_is_quarantined()
        if load_error or unreadable or not isinstance(data, list):
            self.history_meta.setText(tr("History unavailable"))
            message = (
                tr("Could not read download history. The unreadable file was set aside; "
                   "restore it from the state notice or inspect diagnostics.")
                if unreadable else
                tr("Could not read download history: {error}").format(
                    error=load_error or "invalid history data"
                )
            )
            self.history_container.addWidget(make_empty_state(
                tr("History could not be read"),
                tr("Astra Downloader kept the unreadable history aside instead of "
                   "showing an empty list."),
                tr("Open diagnostics"),
                lambda: self._nav_click("Browser extension"),
            ))
            self.history_container.addStretch()
            self._show_history_status(message, "error")
            return
        self.btn_clear_history.setEnabled(bool(data))
        result = self._history_query(entries=data)
        filtered_total = result["filteredTotal"]
        if self._history_offset and self._history_offset >= filtered_total:
            self._history_offset = max(
                0,
                ((max(0, filtered_total - 1)) // self._history_page_size)
                * self._history_page_size,
            )
            result = self._history_query(entries=data)
        self._report_history_date_filters(result)
        rows = result["history"]
        start = result["offset"] + 1 if rows else 0
        end = result["offset"] + len(rows)
        retention_limit = self._history_retention_limit()
        self.history_meta.setText(
            tr_format(
                "{start} to {end} of {filtered} filtered · {total} retained · limit {limit}",
                start=start,
                end=end,
                filtered=filtered_total,
                total=result["total"],
                limit=retention_limit,
            )
            if rows else
            tr_format(
                "0 of {filtered} filtered · {total} retained · limit {limit}",
                filtered=filtered_total,
                total=result["total"],
                limit=retention_limit,
            )
        )
        self.btn_history_prev.setEnabled(result["offset"] > 0)
        self.btn_history_next.setEnabled(result["hasMore"])
        self.btn_export_history.setEnabled(filtered_total > 0)
        if not data and result["total"] == 0:
            self.history_container.addWidget(make_empty_state(
                "No downloads yet",
                "Completed downloads will appear here.",
                "View download queue",
                lambda: self._nav_click("Download"),
            ))
            self.history_container.addStretch()
            return
        if not rows:
            self.history_container.addWidget(make_empty_state(
                "No matching downloads",
                "Adjust the search, status, format, or saved-date filters.",
                "Clear",
                self._clear_history_filters,
            ))
            self.history_container.addStretch()
            return

        for h in rows:
            card = make_card("historyRow")
            card_l = QHBoxLayout(card)
            card_l.setContentsMargins(0, 12, 0, 12)
            card_l.setSpacing(12)
            file_copy = QVBoxLayout()
            file_copy.setSpacing(3)
            file_copy.addWidget(make_label(h.get("title", "(untitled)"), "fieldLabel", word_wrap=True))
            filename = h.get("filename")
            if filename:
                file_copy.addWidget(make_label(Path(filename).name, "fieldHint", word_wrap=True))
            status = str(h.get("status") or "complete")
            file_copy.addWidget(
                make_state_label(human_status(status), download_status_tone(status))
            )
            if h.get("source") == "subscription":
                file_copy.addWidget(make_label(tr("Subscription archive"), "fieldHint"))
            if h.get("error"):
                file_copy.addWidget(
                    make_label(str(h["error"]), "errorCallout", word_wrap=True)
                )
            card_l.addLayout(file_copy, 4)
            not_set = tr("Not set")
            values = (
                str(h.get("format", "")).upper() if h.get("format") else not_set,
                h.get("quality") or not_set,
                format_duration(h.get("duration", 0)) or not_set,
                h.get("date") or not_set,
            )
            for value in values:
                label = make_label(str(value), "tableValue")
                label.setMinimumWidth(92)
                card_l.addWidget(label)
            if filename:
                btn_show = self._make_tool_button(
                    "Show", "ghost", Path(filename).name)
                btn_show.clicked.connect(lambda checked=False, path=filename: self._show_download_location(path))
                card_l.addWidget(btn_show)
            else:
                card_l.addSpacing(54)
            self.history_container.addWidget(card)
        self.history_container.addStretch()

    def _clear_history(self):
        snapshot = self.history_mgr.load()
        if not snapshot:
            self._refresh_history()
            self._show_history_status("Download history is already clear.", "neutral")
            return
        save_undo = getattr(self.history_mgr, "save_undo", None)
        clear_undo = getattr(self.history_mgr, "clear_undo", None)
        if callable(save_undo) and not save_undo("clearHistory", snapshot):
            self._show_history_status(
                "Could not prepare the history undo snapshot. The existing "
                "history was preserved; check disk permissions and retry.",
                "error",
            )
            return
        if not self.history_mgr.clear():
            if callable(clear_undo):
                clear_undo("clearHistory")
            self._show_history_status(
                "Could not clear download history. The existing history was preserved; "
                "check disk permissions and retry.",
                "error",
            )
            return
        self._cleared_history_snapshot = snapshot
        self._refresh_history()
        self.btn_undo_clear_history.show()
        self._show_history_status(
            "Download history cleared. Downloaded files were not removed.", "success")

    def _undo_clear_history(self):
        if not self._cleared_history_snapshot:
            self.btn_undo_clear_history.hide()
            self._show_history_status("No cleared history entries to restore.", "warning")
            return
        if not self.history_mgr.replace(self._cleared_history_snapshot):
            self._show_history_status(
                "Could not restore download history. The Undo snapshot is still available; "
                "check disk permissions and retry.",
                "error",
            )
            return
        restored = len(self._cleared_history_snapshot)
        clear_undo = getattr(self.history_mgr, "clear_undo", None)
        journal_cleared = (
            not callable(clear_undo) or clear_undo("clearHistory")
        )
        if journal_cleared:
            self._cleared_history_snapshot = []
            self.btn_undo_clear_history.hide()
        self._refresh_history()
        message = tr_format(
            "Restored {count} download history {entry_label}.",
            count=restored,
            entry_label=(
                tr("entry") if restored == 1 else tr("entries")
            ),
        )
        if not journal_cleared:
            message += " The Undo record is still available; clear it from disk before closing."
        self._show_history_status(message, "success" if journal_cleared else "warning")

    def _retry_download(self, dl):
        ok, err = self.dl_manager.retry(dl.id)
        if not ok:
            # These controls live on the Download page, so their result has to
            # appear there. The log panel is on the Browser extension page.
            self._set_quick_download_status(err or "Retry was refused.", "error")
            self._append_log(f"Retry failed: {err}")
            return
        label = dl.title if dl.title != 'Unknown' else dl.url
        self._set_quick_download_status(
            tr_format("Retry queued: {title}", title=label), "success"
        )
        self._append_log(f"Retry queued: {label}")
        self._nav_click("Download")

    def _toggle_queue_intake(self):
        if self.dl_manager.capacity()['intakePaused']:
            self._resume_download_queue()
            return
        if self.dl_manager.pause_intake():
            message = "Download intake paused. Running jobs will finish; new jobs will wait."
            self._set_quick_download_status(message, "warning")
            self._append_log(message)
        else:
            message = "Could not pause the queue. Check disk space and permissions."
            self._set_quick_download_status(message, "error")
            self._append_log(message)

    def _resume_one_download(self, dl_id):
        """Resume a single paused download, leaving the rest of the queue alone."""
        ok, err = self.dl_manager.resume_download(dl_id)
        if ok:
            self._set_quick_download_status("Download resumed.", "success")
            return
        self._set_quick_download_status(
            err or "That download could not be resumed.", "error"
        )
        self._append_log(f"Could not resume {dl_id}: {err}")

    def _resume_download_queue(self):
        if self.dl_manager.resume_intake():
            message = "Download queue resumed. Items needing sign-in remain paused."
            self._set_quick_download_status(message, "success")
            self._append_log(message)
        else:
            message = "Could not resume the queue. Check disk space and permissions."
            self._set_quick_download_status(message, "error")
            self._append_log(message)

    def _move_pending_download(self, dl_id, offset):
        ok, err = self.dl_manager.move_pending_by(dl_id, offset)
        if not ok:
            self._set_quick_download_status(
                err or "That download could not be reordered.", "error"
            )
            self._append_log(f"Could not reorder pending download: {err}")

    def _show_download_location(self, file_path):
        if not file_path:
            self._open_folder()
            return
        # Selecting the file beats opening its folder: a busy Downloads
        # folder otherwise leaves the user hunting for what just finished.
        command = self._dependencies['build_reveal_command'](file_path)
        if command:
            try:
                self._dependencies['spawn_detached'](command)
                return
            except Exception as e:
                # Fall through to the folder: a shell that would not take
                # /select is no reason to open nothing at all.
                self._append_log(f"Could not select the file in Explorer: {e}")
        path = Path(file_path)
        try:
            target = path.parent if path.suffix else path
            if target.exists():
                os.startfile(str(target))
                return
            self._append_log("Download location is no longer available")
        except Exception as e:
            self._append_log(f"Could not open download location: {e}")

    def _update_taskbar_progress(self):
        """Show queue progress on the taskbar button.

        The window is usually not the thing being watched — a download runs
        for minutes and the user goes elsewhere — so the taskbar button is
        where progress is actually wanted.
        """
        taskbar = getattr(self, '_taskbar_progress', None)
        if taskbar is None:
            return False
        state, completed, total = self._dependencies['summarize_taskbar_progress'](
            self.dl_manager.snapshot(),
            self._value('DOWNLOAD_RUNNING_STATES'),
            self._value('DOWNLOAD_TERMINAL_STATES'),
        )
        return taskbar.apply(int(self.winId()), state, completed, total)

    def _notification_clicked(self):
        """Reveal the file or failed card named by the latest tray message."""
        target = getattr(self, '_last_notified_file', '')
        download_id = getattr(self, '_last_notified_download_id', '')
        kind = getattr(self, '_last_notification_kind', '')
        self._show_from_tray()
        if kind == 'failure' and download_id:
            return self._focus_download_card(download_id)
        if target:
            self._show_download_location(target)
        return bool(target)

    def _focus_download_card(self, download_id):
        """Open Download, reveal one card, and focus its first useful action."""
        self._nav_click("Download")
        card = self._download_widgets.get(("download", download_id))
        if card is None:
            return False
        self.downloads_scroll.ensureWidgetVisible(card, 24, 24)
        action = next(iter(card.findChildren(QPushButton)), None)
        if action is None:
            card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            action = card
        action.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _play_download(self, file_path):
        """Open a finished file in whatever the system plays it with."""
        try:
            if file_path and Path(file_path).is_file():
                os.startfile(str(Path(file_path)))
                return True
            self._append_log("That file is no longer on disk")
        except Exception as e:
            self._append_log(f"Could not open the file: {e}")
        return False

    def _copy_download_url(self, url):
        if not url:
            return False
        QApplication.clipboard().setText(str(url))
        self._set_quick_download_status("Link copied.", "success")
        return True

    def _delete_download_file(self, download):
        """Delete a finished download's file into the Recycle Bin.

        Recoverably, because the reason to delete one of these is usually a
        mistake made a minute earlier — the wrong quality, the wrong item of
        a playlist — and an unrecoverable delete makes that mistake final.
        """
        filename = getattr(download, 'filename', '') or ''
        if not filename:
            return False
        ok, reason = self._dependencies['send_to_recycle_bin'](filename)
        if not ok:
            self._set_quick_download_status(
                tr("That file could not be moved to the Recycle Bin."), "error"
            )
            self._append_log(f"Recycle Bin delete failed ({reason}): {filename}")
            return False
        self._set_quick_download_status(
            tr("Moved to the Recycle Bin."), "success"
        )
        self._append_log(f"Moved to the Recycle Bin: {filename}")
        self._update_ui()
        return True

    def _copy_download_error(self, error):
        if not error:
            return False
        QApplication.clipboard().setText(str(error))
        self._set_quick_download_status("Error copied.", "success")
        return True

    def _open_download_card_menu(self, download, card, position_widget=None):
        """Show one terminal card's menu under the widget that asked for it.

        The right-click path and the More button both come here, so the menu
        is built once and the two entry points cannot drift.
        """
        anchor = position_widget or card
        menu = self._download_card_menu(download, card)
        return menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _download_card_menu(self, download, position_widget):
        """Actions for one terminal download.

        Six of these are here and nowhere else: play, delete the file, copy
        the link, copy the error, download again, and view the command. Only
        "Show in folder" and "Retry" have a twin elsewhere, so the More
        button beside the card is not a convenience, it is the keyboard and
        discovery route to most of what a finished download can do.
        """
        menu = QMenu(self)
        filename = getattr(download, 'filename', '') or ''
        playable = bool(filename) and Path(filename).is_file()
        play = menu.addAction(tr("Play"))
        play.setEnabled(playable)
        play.triggered.connect(lambda: self._play_download(filename))
        reveal = menu.addAction(tr("Show in folder"))
        reveal.setEnabled(bool(filename))
        reveal.triggered.connect(lambda: self._show_download_location(filename))
        delete = menu.addAction(tr("Delete file"))
        delete.setEnabled(playable)
        delete.triggered.connect(lambda: self._delete_download_file(download))
        menu.addSeparator()
        if self._is_retryable(download):
            retry = menu.addAction(tr("Retry"))
            retry.triggered.connect(lambda: self._retry_download(download))
        url = getattr(download, 'url', '') or ''
        copy_link = menu.addAction(tr("Copy link"))
        copy_link.setEnabled(bool(url))
        copy_link.triggered.connect(lambda: self._copy_download_url(url))
        error = getattr(download, 'error', '') or ''
        copy_error = menu.addAction(tr("Copy error text"))
        copy_error.setEnabled(bool(error))
        copy_error.triggered.connect(lambda: self._copy_download_error(error))
        again = menu.addAction(tr("Download again"))
        again.setEnabled(bool(url))
        again.triggered.connect(lambda: self._redownload(download))
        command_args = getattr(download, 'command_args', None)
        if command_args:
            menu.addSeparator()
            view_cmd = menu.addAction(tr("View yt-dlp command"))
            view_cmd.triggered.connect(lambda: self._show_download_command_dialog(download))
        return menu

    def _show_download_command_dialog(self, download):
        """Show the sanitized yt-dlp command for this download in a modal dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("yt-dlp command"))
        dialog.setMinimumWidth(560)
        dialog.resize(720, 410)
        dialog.setModal(True)
        dialog.setAccessibleName(tr("Review redacted yt-dlp command"))
        dialog.setAccessibleDescription(
            tr("Review or copy the redacted command used for this download.")
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = getattr(download, 'title', '') or 'Download'
        layout.addWidget(make_label(tr_format("Command for {title}", title=title), "panelTitle", word_wrap=True))
        layout.addWidget(make_label(
            tr(
                "This is the exact command line used for this job. Credentials, "
                "tokens, and cookie paths are redacted."
            ),
            "fieldHint", word_wrap=True
        ))

        command_args = getattr(download, 'command_args', []) or []
        command_text = " ".join(
            f'"{arg}"' if " " in arg and not (arg.startswith('"') and arg.endswith('"')) else str(arg)
            for arg in command_args
        )

        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(command_text or tr("No command recorded."))
        edit.setProperty("class", "monospaceLog")
        edit.setMinimumHeight(140)
        edit.setAccessibleName(tr("Redacted yt-dlp command"))
        edit.setAccessibleDescription(
            tr("Read-only command text with private values removed.")
        )
        layout.addWidget(edit)

        buttons = QHBoxLayout()
        copy_status = make_label("", "settingsStatus")
        copy_status.setAccessibleName(tr("Copy command status"))
        buttons.addWidget(copy_status)
        buttons.addStretch()
        btn_close = self._make_tool_button("Close", "secondary")
        btn_close.clicked.connect(dialog.accept)
        buttons.addWidget(btn_close)
        btn_copy = self._make_tool_button("Copy command", "primary")
        btn_copy.setEnabled(bool(command_text))
        btn_copy.setDefault(True)
        btn_copy.clicked.connect(
            lambda: self._copy_command_to_clipboard(command_text, copy_status)
        )
        buttons.addWidget(btn_copy)
        layout.addLayout(buttons)

        dialog.exec()

    def _copy_command_to_clipboard(self, command_text, status_label=None):
        QApplication.clipboard().setText(command_text)
        self._append_log("Copied redacted yt-dlp command to clipboard.")
        if status_label is not None:
            status_label.setText(tr("Copied to clipboard."))
            set_status_tone(status_label, "success")
            repolish(status_label)

    def _sync_playlist_staging_button(self):
        url = self.quick_download_url.text().strip()
        is_playlist = bool(url and self._dependencies['is_playlist_url'](url))
        if hasattr(self, 'btn_quick_stage'):
            self.btn_quick_stage.setVisible(is_playlist)

    def _open_playlist_staging(self):
        require = getattr(self, "_require_first_run_destination", None)
        if callable(require) and not require():
            return
        url = self.quick_download_url.text().strip()
        if not url:
            self._set_quick_download_status(tr("Paste a playlist link first."), "error")
            return
        if not self._dependencies['is_playlist_url'](url):
            self._set_quick_download_status(tr("Enter a playlist URL to review."), "error")
            return

        self._set_quick_download_status(tr("Scanning playlist items…"), "neutral")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            preview, err = self.dl_manager.preview_playlist(url)
        finally:
            QApplication.restoreOverrideCursor()

        if err or not preview:
            self._set_quick_download_status(err or tr("Could not preview playlist."), "error")
            return

        self.quick_download_status.hide()
        dialog = PlaylistStagingDialog(
            self,
            preview,
            format_choices=self._combo_choices(self.quick_download_format),
            quality_choices=self._combo_choices(self.quick_download_quality),
            default_format=self.quick_download_format.currentData(),
            default_quality=self.quick_download_quality.currentData() or "best",
            archived_indices=self._archived_playlist_indices(preview),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selection = dialog.get_selection()
        if not selection:
            self._set_quick_download_status(tr("No playlist items selected."), "warning")
            return
        # Two rows given the same name would write the same file twice, and
        # the second would silently replace the first. Say so instead.
        names = [entry['output_name'] for entry in selection if entry['output_name']]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            self._set_quick_download_status(
                tr_format(
                    "More than one video is named {name}. Give each a "
                    "different name, or leave the name empty.",
                    name=duplicates[0],
                ),
                "error",
            )
            return
        kind = self.quick_download_type.currentData()
        groups = self._dependencies['group_playlist_selection'](selection)
        queued = 0
        failure = ""
        for group in groups:
            _dl_id, error = self.dl_manager.start_download(
                url=url,
                audio_only=kind == "audio",
                subtitles_only=kind == "subtitles",
                fmt=group['format'],
                quality=group['quality'] or "best",
                output_dir=self._quick_download_dir or None,
                playlist_items=group['items'],
                output_name=group['output_name'] or None,
            )
            if error:
                # One rejected group must not hide the ones that queued, so
                # the first reason is reported and the rest still go.
                failure = failure or error
                continue
            queued += len(group['items'])
        if failure and not queued:
            self._set_quick_download_status(failure, "error")
            return
        if failure:
            self._set_quick_download_status(
                tr_format(
                    "Queued {count} items; the rest were refused: {reason}",
                    count=queued, reason=failure,
                ),
                "warning",
            )
        else:
            self._set_quick_download_status(
                tr_format("Queued {count} items from playlist.", count=queued),
                "success",
            )
        self.quick_download_url.clear()
        self._sync_playlist_staging_button()

    @staticmethod
    def _combo_choices(combo):
        return [(combo.itemText(row), combo.itemData(row))
                for row in range(combo.count())]

    def _archived_playlist_indices(self, preview):
        """Return the preview indices a subscription scan already captured."""
        manager = self._subscription_manager()
        lookup = getattr(manager, "archive_entry", None) if manager else None
        if not callable(lookup):
            return set()
        archive_key = self._dependencies['subscription_archive_key']
        archived = set()
        for item in (preview or {}).get("items") or []:
            key = archive_key({"id": item.get("id"), "url": item.get("url")})
            if not key:
                continue
            try:
                entry = lookup(key)
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not read the subscription archive: {error}")
                return archived
            if entry:
                archived.add(item.get("index"))
        return archived

    def _redownload(self, download):
        """Put a finished download's link back in the paste box, ready to go.

        Deliberately not an immediate re-queue: the format and quality
        pickers belong to the box, and silently repeating the original
        request would ignore whatever the user has since changed there.
        """
        url = getattr(download, 'url', '') or ''
        if not url:
            return False
        self.quick_download_url.setText(url)
        self._nav_click("Download")
        self._set_quick_download_status(
            "Link ready. Check the options, then choose Download.", "neutral"
        )
        return True

    def _set_input_error(self, widget, is_error):
        widget.setProperty("state", "error" if is_error else "")
        repolish(widget)

    def _show_settings_status(self, message, tone="neutral"):
        # Each status write bumps the generation so a delayed clear (the
        # post-save 3.2s timer) never wipes a NEWER message — e.g. the
        # "Unsaved changes" indicator from an edit made right after saving.
        self._settings_status_generation = getattr(self, "_settings_status_generation", 0) + 1
        self.settings_status.setText(tr(message))
        self.settings_status.setProperty("tone", tone if tone in {
            "neutral", "success", "warning", "danger"
        } else "neutral")
        repolish(self.settings_status)
        self.settings_status.setAccessibleName(
            tr("Settings status: {message}").format(
                message=tr(message) if message else tr("No current message")
            )
        )

    def _clear_settings_status_if_current(self, generation):
        if getattr(self, "_settings_status_generation", 0) == generation:
            self._show_settings_status("")

    def _mark_settings_dirty(self, *_args):
        if not hasattr(self, "settings_status") or not hasattr(self, "btn_save"):
            return
        self._show_settings_status("Unsaved changes", "warning")
        self._set_control_label(self.btn_save, tr("Save changes"))

    def _apply_saved_server_port(self, old_port, old_effective_port=None):
        """Restart or refresh the local API after ServerPort changed on disk."""
        clamp_int = self._dependencies["clamp_int"]
        default_port = self._value("SERVER_PORT")
        new_port = clamp_int(
            self.config.get("ServerPort", default_port), default_port, 1024, 65535,
        )
        if old_effective_port is None:
            old_effective_port = old_port
        port_changed = new_port != old_port or new_port != old_effective_port
        restarted = bool(port_changed and self.server_running)
        if restarted:
            self._stop_server()
            self._start_server()
        else:
            self._sync_connection_ui()
        return restarted

    def _sync_connection_ui(self):
        clamp_int = self._dependencies['clamp_int']
        default_port = self._value('SERVER_PORT')
        port = clamp_int(self.config.get("ServerPort", default_port), default_port, 1024, 65535)
        self.dash_endpoint.setText(f"http://127.0.0.1:{port}")
        self.stat_port.setText(str(port))
        persisted_get = getattr(self.config, 'get_persisted', self.config.get)
        configured = clamp_int(persisted_get("ServerPort", default_port), default_port, 1024, 65535)
        hint = getattr(self, 'cfg_port_session_hint', None)
        if hint is None:
            return
        if port != configured:
            message = tr_format(
                "Port {configured} was unavailable at startup; bound to fallback port "
                "{port} for this session. Restart to retry {configured}.",
                configured=configured,
                port=port,
            )
            hint.setText(message)
            self._set_settings_filter_hidden(hint, False)
            self.cfg_port.setAccessibleDescription(
                tr(
                    "Port {configured} was unavailable at startup; bound to fallback port "
                    "{port} for this session. Restart to retry {configured}."
                ).format(configured=configured, port=port)
            )
        else:
            hint.setText("")
            self._set_settings_filter_hidden(hint, True)
            self.cfg_port.setAccessibleDescription("")

    # ── Tools: yt-dlp / ffmpeg maintenance (v1.2.0) ──
    def _tools_status_text(self):
        ytv = self._dependencies['get_ytdlp_version']() or "not installed"
        ffv = self._dependencies['get_ffmpeg_version']() or "not installed"
        return tr_format(
            "yt-dlp {yt}    •    ffmpeg {ffmpeg}",
            yt=ytv,
            ffmpeg=ffv,
        )

    def _set_tools_status_text(self, text):
        try:
            self.tools_status.setText(text)
        except Exception:
            # reason: label may be gone during teardown; best-effort UI update
            pass

    def _refresh_tools_status(self):
        # The version getters shell out (up to 5s each on a cold cache, e.g.
        # right after _setup_done resets the ffmpeg probe) — never run them on
        # the GUI thread. Compute off-thread and marshal back via the signal.
        def run():
            try:
                text = self._tools_status_text()
            except Exception:
                # reason: version probes are best-effort; keep the old label
                return
            self.tools_status_text_ready.emit(text)

        threading.Thread(target=run, name='tools-status-refresh', daemon=True).start()

    def _force_ytdlp_update(self):
        if not self._value('YTDLP_PATH').exists():
            self._append_log("yt-dlp is not installed yet. Run setup first.")
            self._show_settings_status("Install yt-dlp before checking for updates.", "warning")
            return
        active_downloads = self.dl_manager.active_count()
        if active_downloads:
            self._append_log(
                f"yt-dlp update deferred: {active_downloads} download(s) are still active."
            )
            self._show_settings_status(
                "Wait for active downloads to finish before updating yt-dlp.",
                "warning",
            )
            return
        self._append_log("Forcing yt-dlp self-update…")
        self.btn_check_updates.setEnabled(False)
        self._set_control_label(self.btn_check_updates, tr("Checking…"))
        self._show_settings_status(
            "Checking yt-dlp. The verified current copy stays available until the update passes.",
            "warning",
        )

        def run():
            try:
                result = self._dependencies['_run_ytdlp_self_update'](self.config, source_tag='gui')
            except Exception as e:
                result = {
                    'ok': False,
                    'error': f'Unexpected update error: {e}',
                    'error_code': 'unexpected-update-error',
                }
            # A queued Qt signal is the thread-safe boundary back to the GUI.
            # QTimer.singleShot created inside this worker has no event loop and
            # can silently strand the button in its busy state.
            self.tools_update_finished.emit(result)

        threading.Thread(target=run, daemon=True).start()

    def _finish_ytdlp_update(self, result):
        self.btn_check_updates.setEnabled(True)
        self._set_control_label(
            self.btn_check_updates, tr("Check for yt-dlp updates")
        )
        self._refresh_tools_status()
        if result.get('ok'):
            version = result.get('version_after') or 'current'
            rollback = result.get('rollback_version') or 'not retained yet'
            self._append_log(f"yt-dlp active {version}; rollback {rollback}.")
            self._show_settings_status(
                tr_format("yt-dlp {version} is ready.", version=version),
                "success",
            )
            return
        recovery = (
            f" Restored {result.get('version_after')}."
            if result.get('rolled_back') else ''
        )
        error = result.get('error') or 'Unknown update error.'
        self._append_log(f"yt-dlp update failed: {str(error).rstrip('.')}.{recovery}")
        self._show_settings_status(
            "yt-dlp update failed. The previous working copy was kept; check the log for details.",
            "danger",
        )

    def _reinstall_ffmpeg(self):
        """Stage and verify a fresh ffmpeg before replacing the live binary."""
        if self._setup_running:
            self._append_log("Setup is already running; wait for it to finish before reinstalling ffmpeg.")
            self._show_settings_status("Setup is already running.", "warning")
            return
        active_downloads = self.dl_manager.active_count()
        if active_downloads:
            self._append_log(
                f"ffmpeg refresh deferred: {active_downloads} download(s) are still active."
            )
            self._show_settings_status(
                "Wait for active downloads to finish before refreshing ffmpeg.",
                "warning",
            )
            return
        self._append_log("Reinstalling ffmpeg from source with checksum verification.")
        self._show_settings_status(
            "Refreshing ffmpeg. The current verified copy stays available until replacement succeeds.",
            "warning",
        )
        # self._dependencies['SetupWorker'] extracts into a unique temporary file and only calls
        # os.replace after the archive checksum and executable size checks pass.
        # `force_ffmpeg` bypasses the ordinary already-installed short circuit
        # without deleting the live binary first.
        self._run_setup(force_ffmpeg=True)

    def _output_template_preview_options(self):
        checkbox = getattr(self, "cfg_windows_filenames", None)
        windows_filenames = bool(
            checkbox is not None and checkbox.isChecked()
        )
        try:
            install_dir = self._value("INSTALL_DIR")
            staging_name = self._value("DOWNLOAD_INTERMEDIATE_DIRNAME")
        except (KeyError, TypeError, AttributeError):
            staging_prefix = ""
        else:
            staging_prefix = str(Path(install_dir) / str(staging_name))
        return {
            "windows_filenames": windows_filenames,
            "staging_prefix": staging_prefix,
        }

    def _update_output_template_preview(self, *_args):
        """Show the rendered example and any Windows path hazards."""
        label = getattr(self, "outtmpl_preview", None)
        builder = self._dependencies.get("output_template_preview")
        if label is None or not callable(builder):
            return
        report = builder(
            self.cfg_outtmpl.text(),
            self.cfg_dl_path.text(),
            **self._output_template_preview_options(),
        )
        if not report.get("valid"):
            label.setText(tr("Preview unavailable until the template is valid."))
            set_status_tone(label, "error")
            repolish(label)
            return
        warnings = []
        reserved = report.get("reserved") or ()
        if reserved:
            warnings.append(tr(
                "Reserved Windows name in preview: {name}."
            ).format(name=", ".join(reserved)))
        oversized = report.get("oversizedComponents") or ()
        if oversized:
            # The whole path can be well inside MAX_PATH while one folder name
            # is over the per-component limit, so saying "the path is too long"
            # here sends the user looking in the wrong place.
            warnings.append(tr(
                "Folder or file name is too long: {name}. Windows allows {maximum} bytes per name."
            ).format(
                name=", ".join(str(item)[:40] for item in oversized),
                maximum=report.get("maxComponentBytes", 255),
            ))
        if report.get("too_long") and report.get("length", 0) > report.get("max_path", 260):
            warnings.append(tr(
                "Rendered path is {length} characters; Windows maximum is {maximum}."
            ).format(
                length=report.get("length"),
                maximum=report.get("max_path", 260),
            ))
        if warnings:
            label.setText(" ".join(warnings))
            set_status_tone(label, "error")
            repolish(label)
        else:
            label.setText(tr(
                "Preview: {path} ({length} characters)."
            ).format(
                path=report.get("path"),
                length=report.get("length"),
            ))
            set_status_tone(label, "neutral", announce=False)
            repolish(label)

    def _save_settings(self):
        site_profiles_field = getattr(self, "cfg_site_profiles", None)
        validated_fields = (
            self.cfg_token, self.cfg_dl_path, self.cfg_audio_path,
            self.cfg_sublangs, self.cfg_ratelimit, self.cfg_proxy,
            self.cfg_source_address, self.cfg_xff,
            self.cfg_geo_verification_proxy,
            self.cfg_outtmpl,
        )
        if site_profiles_field is not None:
            validated_fields += (site_profiles_field,)
        for field in validated_fields:
            self._set_input_error(field, False)
            field.setAccessibleDescription("")
            # The reason is written to the tooltip too, and a field that has
            # since been fixed must not keep the rejection text on hover.
            clear_tooltip = getattr(field, "setToolTip", None)
            if callable(clear_tooltip):
                clear_tooltip("")

        # Compare against the PERSISTED port: during a session-only fallback
        # (bind conflict) the live port differs from the configured one, and
        # an unrelated settings save must not read that as a port change and
        # surprise-restart the server.
        persisted_get = getattr(self.config, 'get_persisted', self.config.get)
        old_port = self._dependencies['clamp_int'](persisted_get("ServerPort", self._value('SERVER_PORT')), self._value('SERVER_PORT'), 1024, 65535)
        old_token = self.config.get("ServerToken", "")
        old_clipboard_grabber = self.config.get("ClipboardLinkGrabber", False)
        old_theme = self.config.get("Theme", "system")
        old_language = self.config.get("Language", "system")
        new_port = self.cfg_port.value()
        new_token = self.cfg_token.text().strip()
        dl_path = self.cfg_dl_path.text().strip()
        audio_path = self.cfg_audio_path.text().strip()
        sublangs = self._dependencies['normalize_sublangs'](self.cfg_sublangs.text())
        rate = self._dependencies['normalize_rate_limit'](self.cfg_ratelimit.text())
        proxy = self.cfg_proxy.text().strip()
        force_ip = self._dependencies['normalize_force_ip_version'](
            self.cfg_force_ip_version.currentData()
        )
        source_address_raw = self.cfg_source_address.text().strip()
        source_address = self._dependencies['normalize_source_address'](
            source_address_raw
        )
        xff_raw = self.cfg_xff.text().strip()
        xff = self._dependencies['normalize_xff'](xff_raw)
        geo_proxy_raw = self.cfg_geo_verification_proxy.text().strip()
        geo_proxy = self._dependencies['normalize_proxy'](geo_proxy_raw)
        site_profiles_raw = (
            site_profiles_field.toPlainText().strip()
            if site_profiles_field is not None else ""
        )
        validate_profiles = self._dependencies.get('validate_site_profiles')
        site_profiles, site_profiles_error = (
            validate_profiles(site_profiles_raw)
            if callable(validate_profiles) else ([], None)
        )
        has_error = False
        first_error = None

        first_reason = None

        def mark_error(field, message, translatable=True):
            """Mark one field and say why, on the field and in the summary.

            ``translatable`` is False for a reason built at runtime rather
            than written here. Those cannot reach a catalogue, so they stay
            out of the status line and the generic summary is used instead;
            the field itself still carries them.
            """
            nonlocal has_error, first_error, first_reason
            self._set_input_error(field, True)
            reason = tr(message)
            field.setAccessibleDescription(reason)
            # Guarded the way _set_control_label guards its accessible-name
            # write: the settings harness fields implement the setters this
            # validation loop needs and nothing else.
            tooltip = getattr(field, "setToolTip", None)
            if callable(tooltip):
                tooltip(reason)
            has_error = True
            if first_error is None:
                first_error = field
                # The source string, not `reason`: the status setter
                # translates what it is given, and the literals are already
                # extracted from the mark_error call sites.
                first_reason = message if translatable else None

        dl_path, dl_path_err = self._dependencies['normalize_output_dir'](dl_path, self._value('DEFAULT_CONFIG')["DownloadPath"])
        audio_path, audio_path_err = self._dependencies['normalize_output_dir'](audio_path, dl_path) if audio_path else ("", None)

        if dl_path_err:
            mark_error(self.cfg_dl_path, "Choose a valid local video download folder.")
        if audio_path_err:
            mark_error(self.cfg_audio_path, "Choose a valid local audio download folder.")
        if not sublangs:
            mark_error(self.cfg_sublangs, "Enter one or more language codes, such as en or en,es.")
        if self.cfg_ratelimit.text().strip() and not rate:
            mark_error(self.cfg_ratelimit, "Use a rate such as 500K or 2M, or leave this blank.")
        if proxy and not self._dependencies['normalize_proxy'](proxy):
            mark_error(self.cfg_proxy, "Enter an http, https, or socks proxy URL.")
        else:
            proxy = self._dependencies['normalize_proxy'](proxy)
        if source_address_raw and not source_address:
            mark_error(
                self.cfg_source_address,
                "Enter a local IPv4 or IPv6 address, or leave this blank.",
            )
        if xff_raw and not xff:
            mark_error(
                self.cfg_xff,
                "Enter a two-letter country code or CIDR block, or leave this blank.",
            )
        if geo_proxy_raw and not geo_proxy:
            mark_error(
                self.cfg_geo_verification_proxy,
                "Enter an http, https, or socks proxy URL, or leave this blank.",
            )
        if site_profiles_error and site_profiles_field is not None:
            # The validator builds this text at runtime, so it is in no
            # catalogue and must not replace a translated summary.
            mark_error(site_profiles_field, site_profiles_error, translatable=False)
        if not new_token:
            mark_error(self.cfg_token, "The private API token cannot be empty.")
        outtmpl_raw = self.cfg_outtmpl.text().strip()
        outtmpl = self._dependencies['normalize_output_template'](outtmpl_raw) if outtmpl_raw else ""
        if outtmpl_raw and not outtmpl:
            # Never silently drop a rejected template — the save used to
            # report success while sanitize blanked it to the default naming.
            mark_error(
                self.cfg_outtmpl,
                "Keep %(ext)s and use only safe yt-dlp fields such as "
                "%(title)s, %(id)s, or %(uploader)s. Absolute paths and '..' are not allowed.",
            )
        preview_builder = self._dependencies.get("output_template_preview")
        if outtmpl_raw and outtmpl and callable(preview_builder):
            report = preview_builder(
                outtmpl,
                dl_path,
                **self._output_template_preview_options(),
            )
            if report.get("reserved"):
                mark_error(
                    self.cfg_outtmpl,
                    "The template preview uses a reserved Windows name.",
                )
            if report.get("too_long"):
                mark_error(
                    self.cfg_outtmpl,
                    "The rendered template path is too long for Windows.",
                )

        if has_error:
            if first_reason:
                self._show_settings_status(first_reason, "danger")
            else:
                self._show_settings_status(
                    "Check the highlighted fields before saving.", "danger")
            if first_error is not None:
                first_error.setFocus(Qt.FocusReason.OtherFocusReason)
            return

        connection_changed = new_port != old_port or new_token != old_token
        restart_now = connection_changed and self.server_running

        self.cfg_dl_path.setText(dl_path)
        self.cfg_audio_path.setText(audio_path)
        self.cfg_sublangs.setText(sublangs)
        self._sync_sublang_checkboxes(sublangs)
        self.cfg_ratelimit.setText(rate)
        self.cfg_proxy.setText(proxy)
        self.cfg_source_address.setText(source_address)
        self.cfg_xff.setText(xff)
        self.cfg_geo_verification_proxy.setText(geo_proxy)
        if site_profiles_field is not None:
            site_profiles_field.setPlainText(json.dumps(
                site_profiles or [], indent=2, ensure_ascii=False
            ))
        self.cfg_outtmpl.setText(outtmpl)
        def checked_setting(attribute, key):
            widget = getattr(self, attribute, None)
            return widget.isChecked() if widget is not None else bool(
                self.config.get(
                    key, self._value("DEFAULT_CONFIG").get(key, False)
                )
            )

        def numeric_setting(attribute, key):
            widget = getattr(self, attribute, None)
            return widget.value() if widget is not None else int(
                self.config.get(key, 0) or 0
            )

        def decimal_setting(attribute, key):
            widget = getattr(self, attribute, None)
            return widget.value() if widget is not None else float(
                self.config.get(key, 0) or 0
            )

        saved = self.config.update({
            "ServerPort": new_port,
            "ServerToken": new_token,
            "DownloadPath": dl_path,
            "AudioDownloadPath": audio_path,
            "HistoryRetentionLimit": numeric_setting(
                "cfg_history_retention", "HistoryRetentionLimit"
            ),
            "OutputTemplate": outtmpl,
            "WindowsFilenames": checked_setting(
                "cfg_windows_filenames", "WindowsFilenames"
            ),
            "EmbedMetadata": self.cfg_metadata.isChecked(),
            "EmbedThumbnail": self.cfg_thumbnail.isChecked(),
            "EmbedChapters": self.cfg_chapters.isChecked(),
            "EmbedSubs": self.cfg_subs.isChecked(),
            "GenerateSubtitles": checked_setting(
                "cfg_generate_subtitles", "GenerateSubtitles"
            ),
            "KeepIntermediateFiles": self.cfg_keep_intermediates.isChecked(),
            "WriteInfoJson": checked_setting("cfg_write_info", "WriteInfoJson"),
            "WriteNfo": checked_setting("cfg_write_nfo", "WriteNfo"),
            "WriteDescription": checked_setting(
                "cfg_write_description", "WriteDescription"
            ),
            "WriteThumbnail": checked_setting(
                "cfg_write_thumbnail", "WriteThumbnail"
            ),
            "SplitChapters": checked_setting("cfg_split_chapters", "SplitChapters"),
            "LiveFromStart": checked_setting("cfg_live_from_start", "LiveFromStart"),
            "WaitForVideoSeconds": numeric_setting(
                "cfg_wait_for_video", "WaitForVideoSeconds"
            ),
            "VerifyFormats": self.cfg_verify_formats.isChecked(),
            "VideoCodecPreference": self.cfg_video_codec.currentData(),
            "AudioCodecPreference": self.cfg_audio_codec.currentData(),
            "PreferredFrameRate": self.cfg_frame_rate.currentData(),
            "PreferOriginalOverUpscaled": self.cfg_prefer_original.isChecked(),
            "PlaylistMaxItems": self.cfg_playlist_max.value(),
            "PlaylistDateAfter": self._dependencies['normalize_playlist_date'](
                self.cfg_playlist_dateafter.text()),
            "PlaylistMinDurationSeconds": self.cfg_playlist_min_duration.value(),
            "PlaylistMaxDurationSeconds": self.cfg_playlist_max_duration.value(),
            "ImpersonateTarget": self.cfg_impersonate.currentData() or "",
            "ThrottledRate": self.cfg_throttled.text().strip(),
            "SocketTimeoutSeconds": self.cfg_socket_timeout.value(),
            "ExtractorRetries": self.cfg_extractor_retries.value(),
            "SleepIntervalSeconds": self.cfg_sleep_interval.value(),
            "MaxSleepIntervalSeconds": self.cfg_sleep_max.value(),
            "PacingJitterPercent": self.cfg_pacing_jitter.value(),
            "SleepRequestsSeconds": self.cfg_sleep_requests.value(),
            "SubLangs": sublangs,
            "SubtitleSleepSeconds": decimal_setting(
                "cfg_subtitle_sleep", "SubtitleSleepSeconds"
            ),
            "SubtitleMode": self._dependencies['normalize_subtitle_mode'](
                self.cfg_subtitle_mode.currentData()
            ),
            "SubtitleFormat": self._dependencies['normalize_subtitle_format'](
                self.cfg_subtitle_format.currentData()
            ),
            "SponsorBlock": self.cfg_sponsorblock.isChecked(),
            "SponsorBlockAction": self.cfg_sb_action.currentData(),
            "SponsorBlockCategories": ",".join(
                name for name, box in self.cfg_sb_categories.items()
                if box.isChecked()
            ),
            "ConcurrentFragments": self.cfg_fragments.value(),
            "MaxConcurrentDownloads": self.cfg_maxconcurrent.value(),
            "DownloadRetries": self.cfg_retries.value(),
            "MaxFileSizeMB": self.cfg_maxsize.value(),
            "RateLimit": rate,
            "Proxy": proxy,
            "UseSystemProxy": checked_setting(
                "cfg_use_system_proxy", "UseSystemProxy"
            ),
            "ForceIPVersion": force_ip,
            "SourceAddress": source_address,
            "Xff": xff,
            "GeoVerificationProxy": geo_proxy,
            "SiteProfiles": site_profiles or [],
            "JavaScriptRuntime": self.cfg_js_runtime.currentData(),
            "YtDlpUpdateChannel": self.cfg_ytdlp_channel.currentData(),
            "Language": (
                self.cfg_language.currentData()
                if hasattr(self, "cfg_language")
                else old_language
            ),
            "Theme": (
                self.cfg_theme.currentData()
                if hasattr(self, "cfg_theme")
                else old_theme
            ),
            "AutoUpdateYtDlp": self.cfg_autoupdate.isChecked(),
            "CloseToTray": self.cfg_closetotray.isChecked(),
            "StartMinimized": self.cfg_startmin.isChecked(),
            "NotifyOnComplete": self.cfg_notify.isChecked(),
            "NotifyOnFailure": self.cfg_notify_failure.isChecked(),
            "ClipboardLinkGrabber": (
                self.cfg_clipboard.isChecked()
                if hasattr(self, "cfg_clipboard")
                else old_clipboard_grabber
            ),
        })
        if not saved:
            self._set_control_label(self.btn_save, tr("Save changes"))
            self._show_settings_status(
                "Could not save settings. Nothing changed; check disk permissions and retry.",
                "danger",
            )
            self._append_log("Settings save failed. Existing settings and server state were preserved.")
            return

        self._dependencies['reset_deno_runtime_cache']()
        self._start_readiness_probe()

        theme_changed = self.config.get("Theme", "system") != old_theme
        apply_theme = self._dependencies.get("apply_theme")
        if theme_changed and callable(apply_theme):
            try:
                apply_theme(self.config.get("Theme", "system"))
            except Exception as error:  # noqa: BLE001
                self._append_log(f"Could not apply the selected theme: {error}")

        if self.config.get("GenerateSubtitles", False):
            model_usable = self._dependencies.get('managed_binary_usable')
            model_ready = True
            if callable(model_usable):
                model_ready = model_usable(
                    self._value('WHISPER_MODEL_PATH'),
                    self._value('WHISPER_MODEL_MIN_BYTES'),
                )
            if not model_ready and not self._setup_running:
                self._append_log(
                    "Local subtitle generation is enabled; starting model setup."
                )
                self._run_setup()

        # The proxy and network identity the app uses for its own fetches are
        # resolved once and cached, so a saved change has to re-resolve them or
        # the updater and the native resolvers keep the previous route.
        refresh_network_policy = self._dependencies.get(
            'set_first_party_network_policy'
        )
        if callable(refresh_network_policy):
            refresh_network_policy(self.config.get)
        self._sync_connection_ui()
        language_changed = (
            hasattr(self, "cfg_language")
            and self.cfg_language.currentData() != old_language
        )
        if restart_now:
            self._append_log("Connection settings changed; restarting local server.")
            self._stop_server()
            self._start_server()
            self._show_settings_status("Settings saved and server restarted.", "success")
        elif language_changed:
            self._show_settings_status(
                "Settings saved. Restart Astra Downloader to apply the language.",
                "success",
            )
        else:
            self._show_settings_status("Settings saved.", "success")
        if (
            hasattr(self, "cfg_clipboard")
            and self.cfg_clipboard.isChecked()
            and not old_clipboard_grabber
        ):
            # Enabling is an explicit opt-in, so consider the current
            # clipboard value without making the user copy it again.
            self._handle_clipboard_change()
        self._set_control_label(self.btn_save, tr("Saved"))
        QTimer.singleShot(
            1500,
            lambda: self._set_control_label(self.btn_save, tr("Save changes")),
        )
        status_generation = getattr(self, "_settings_status_generation", 0)
        QTimer.singleShot(3200, lambda: self._clear_settings_status_if_current(status_generation))

    def _browse(self, line_edit):
        path = QFileDialog.getExistingDirectory(
            self, tr("Select folder"), line_edit.text()
        )
        if path:
            line_edit.setText(path)

    def _quick_download_url_edited(self, *_args):
        """Clear clipboard-specific guidance once the user edits a staged URL."""
        self._sync_quick_download_profile(apply=True)
        self._schedule_format_probe()
        self._sync_playlist_staging_button()
        if not self._clipboard_staged_url:
            return
        self._clipboard_staged_url = ""
        self._clipboard_last_seen = ""
        self.quick_download_status.hide()

    def _set_quick_clip_selector(self, start, end):
        """Set one of yt-dlp's URL-relative quick clip selectors."""
        if getattr(self, "_sabr_limited", False):
            self._set_quick_download_status(
                tr("Clip ranges are unavailable for this SABR-only link."),
                "warning",
            )
            return
        self.quick_download_start.setText(start)
        self.quick_download_end.setText(end)

    def _set_quick_clip_from_url(self):
        self._set_quick_clip_selector("*from-url", "inf")

    def _set_quick_clip_last_30(self):
        self._set_quick_clip_selector("*-30", "inf")

    # ── Format probing ───────────────────────────────────────────────────
    # The picker is a fixed ladder that knows nothing about the pasted link,
    # so a user can ask for 2160p on a 720p video and only learn the truth
    # from the result. One `-J` probe per settled URL narrows the offer.

    def _set_quality_choices(self, values):
        """Rebuild the quality picker, keeping the current choice if it survives."""
        combo = self.quick_download_quality
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("Best"), "best")
        for value in values:
            combo.addItem(
                tr_format("{quality}p", quality=value), str(value)
            )
        restored = combo.findData(current)
        combo.setCurrentIndex(restored if restored >= 0 else 0)
        combo.blockSignals(False)

    def _apply_sabr_limits(self, limited):
        """Disable what a SABR-only link cannot honour, and say why.

        yt-dlp ignores --download-sections, --limit-rate and -N on a SABR
        stream, so a clip range typed against one silently yields the whole
        video. Better to refuse the input than to accept it and not deliver.
        """
        limited = bool(limited)
        if getattr(self, "_sabr_limited", None) == limited:
            return
        self._sabr_limited = limited
        for field in (
            self.quick_download_start, self.quick_download_end,
            getattr(self, "btn_quick_clip_from_url", None),
            getattr(self, "btn_quick_clip_last_30", None),
        ):
            if field is None:
                continue
            field.setEnabled(not limited)
            if limited:
                if hasattr(field, "clear"):
                    field.clear()
        if limited:
            notice = tr(self._value('SABR_LIMITED_NOTICE')).format(
                options=self._dependencies['describe_sabr_voided_options']()
            )
            self.quick_download_clip_hint.setText(notice)
            self._set_quick_download_status(notice, "warning")
        else:
            self.quick_download_clip_hint.setText(
                tr("Clip ranges apply to a single link.")
            )

    def _schedule_format_probe(self):
        """Restart the debounce, and drop a stale narrowing straight away."""
        if not hasattr(self, "_format_probe_timer"):
            return
        if self.quick_download_url.text().strip() != self._probed_format_url:
            # The picker must never describe a link that is no longer in the
            # box, so the full ladder comes back before the new probe lands.
            self._reset_quality_choices()
        self._format_probe_timer.start()

    def _reset_quality_choices(self):
        self._format_probe_summary = {}
        self._format_probe_summary_url = ""
        self._format_probe_in_flight = False
        self._format_probe_request_url = ""
        if hasattr(self, "quick_download_status"):
            self.quick_download_status.clear()
            self.quick_download_status.hide()
        if not self._probed_format_url:
            return
        self._probed_format_url = ""
        self._format_probe_generation += 1
        self._apply_sabr_limits(False)
        self._set_quality_choices(self._value('QUALITY_LADDER'))

    def _probe_quick_download_formats(self):
        """Ask yt-dlp what the pasted link offers, off the GUI thread."""
        if self._force_exit:
            # The debounce can already be in flight when the window closes.
            return
        raw = self.quick_download_url.text().strip()
        parts = raw.split()
        if len(parts) != 1:
            # A batch paste has no single format table to describe.
            return
        url, error = self._dependencies['normalize_url'](parts[0])
        if error or not url:
            return
        if self._dependencies['is_playlist_url'](url):
            return
        if url == self._probed_format_url:
            return
        if self._format_probe_in_flight and url == self._format_probe_request_url:
            return
        self._format_probe_generation += 1
        generation = self._format_probe_generation
        self._format_probe_in_flight = True
        self._format_probe_request_url = url
        self._set_quick_download_status(
            tr("Looking up available formats…"), "neutral"
        )

        def worker():
            try:
                summary, probe_error = self.dl_manager.list_formats(url)
            except Exception as exc:  # noqa: BLE001
                summary, probe_error = None, str(exc)
            self.format_probe_finished.emit({
                "generation": generation,
                "url": url,
                "summary": summary or {},
                "error": probe_error or "",
            })

        threading.Thread(
            target=worker, name='format-probe', daemon=True
        ).start()

    def _apply_format_probe(self, payload):
        """Narrow the picker to what the probed link actually offers."""
        if not isinstance(payload, dict):
            return
        if payload.get("generation") != self._format_probe_generation:
            # The user typed on while this probe ran; it describes a URL that
            # is no longer in the box. A newer probe owns in-flight state.
            return
        self._format_probe_in_flight = False
        self._format_probe_request_url = ""
        if payload.get("url") != self.quick_download_url.text().strip():
            return
        if payload.get("error"):
            # A probe failure is not a download failure: the fixed ladder is
            # still a usable offer, so it stays and nothing is said.
            self._format_probe_summary = {}
            self._format_probe_summary_url = ""
            self.quick_download_status.clear()
            self.quick_download_status.hide()
            return
        summary = payload.get("summary")
        self._format_probe_summary = summary if isinstance(summary, dict) else {}
        self._format_probe_summary_url = payload.get("url") or ""
        self._apply_sabr_limits(self._dependencies['sabr_only_formats'](summary))
        heights = self._dependencies['probed_video_heights'](summary)
        if not heights:
            self.quick_download_status.clear()
            self.quick_download_status.hide()
            return
        self._probed_format_url = payload.get("url") or ""
        self._set_quality_choices(
            self._dependencies['quality_choices_for_heights'](heights)
        )
        self._set_quick_download_status(
            tr("This link tops out at {height}p.").format(height=max(heights)),
            "neutral",
        )

    def _handle_clipboard_change(self, clipboard_text=None):
        """Stage a copied media URL for review without starting a download."""
        if not self.config.get("ClipboardLinkGrabber", False):
            return
        if clipboard_text is None:
            clipboard_text = self._clipboard.text()
        if not isinstance(clipboard_text, str):
            return
        raw = clipboard_text.strip()
        if not raw or raw == self._clipboard_last_seen:
            return
        self._clipboard_last_seen = raw
        url, error = self._dependencies['normalize_url'](raw)
        # `looks_like_media_link` is a UX filter, not a security one: it keeps
        # the grabber from staging every copied http link (docs, tickets,
        # search results) while still covering any site whose URL reads like
        # media. The download itself is gated by the manager's policy check.
        if error or not self._dependencies['looks_like_media_link'](url):
            return
        if url == self._clipboard_staged_url:
            return

        self._clipboard_staged_url = url
        self.quick_download_url.setText(url)
        self.quick_download_status.setText(
            tr(
                "Copied video link staged. Review the options, then choose Add to queue."
            )
        )
        self.quick_download_status.show()
        set_status_tone(self.quick_download_status, "success")
        repolish(self.quick_download_status)
        self._append_log("Staged a copied video link for review.")
        if hasattr(self, "tray"):
            self.tray.showMessage(
                self._value('APP_NAME'),
                tr(
                    "Video link staged. Open Downloads to review it before adding it to the queue."
                ),
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _copy_endpoint(self):
        QApplication.clipboard().setText(self.dash_endpoint.text())
        self._append_log("Endpoint copied to clipboard")
        old = self.dash_hint.text()
        self.dash_hint.setText(tr("Endpoint copied."))
        QTimer.singleShot(1600, lambda: self.dash_hint.setText(old))

    def _show_native_pairing_status(self, message, state):
        self.native_pairing_status.setText(tr(message))
        self.native_pairing_status.show()
        set_status_tone(self.native_pairing_status, state)
        repolish(self.native_pairing_status)

    def _apply_native_chrome_ids(self):
        """Save the Chrome/Edge extension IDs and re-register the native host.

        An invalid ID is refused here, before it can reach a manifest's
        allowed_origins; a valid save re-runs registration immediately so the
        registry pointers follow the setting without a relaunch.
        """
        raw = self.cfg_native_chrome_ids.text().strip()
        ids = self._dependencies["parse_native_extension_ids"](raw, browser="chrome")
        if raw and not ids:
            self._show_native_pairing_status(
                "That is not a Chrome extension ID. Copy the 32-letter ID "
                "shown on chrome://extensions.",
                "error",
            )
            return
        normalized = ", ".join(ids)
        update = getattr(self.config, "update", None)
        if not callable(update) or not update({"NativeChromeExtensionIds": normalized}):
            self._show_native_pairing_status(
                "Could not save the extension IDs. Check disk permissions and retry.",
                "error",
            )
            return
        self.cfg_native_chrome_ids.setText(normalized)
        registered = bool(
            self._dependencies["refresh_native_messaging_registration"]()
        )
        if ids and registered:
            self._show_native_pairing_status(
                "Chrome and Edge are paired. Reload the extension once and "
                "its download button can hand off.",
                "success",
            )
            self._append_log(
                f"Registered the Chrome/Edge native host for {len(ids)} extension ID(s)"
            )
        elif ids:
            self._show_native_pairing_status(
                "Saved. This portable copy registers no browser hosts. "
                "Pair from an installed copy.",
                "warning",
            )
        elif registered:
            self._show_native_pairing_status(
                "Chrome and Edge pairing cleared.", "neutral"
            )
            self._append_log("Revoked the Chrome/Edge native-messaging registration")
        else:
            self._show_native_pairing_status(
                "Cleared. This copy registers no browser hosts.", "neutral"
            )

    def _copy_token(self):
        token = self.cfg_token.text()
        QApplication.clipboard().setText(token)
        self._show_settings_status(
            "Token copied. It will clear from the clipboard in 60 seconds if unchanged.",
            "success",
        )
        QTimer.singleShot(60_000, lambda expected=token: self._clear_copied_token(expected))

    def _clear_copied_token(self, expected):
        clipboard = QApplication.clipboard()
        if clipboard.text() == expected:
            clipboard.clear()
            self._show_settings_status("Copied token cleared from the clipboard.", "neutral")

    def _copy_diagnostics(self):
        text = self._diagnostics_text()

        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Review diagnostics"))
        dialog.setModal(True)
        dialog.resize(720, 520)
        dialog.setAccessibleName(tr("Review redacted diagnostics"))
        dialog.setAccessibleDescription(
            tr("Review the support data before saving or copying it.")
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = make_label("Review the redacted support payload", "section")
        detail = make_label(
            "Paths, URLs, tokens, cookie-shaped values, and opaque identifiers are removed. "
            "Only copy this payload if you are comfortable sharing what remains.",
            "fieldHint",
            word_wrap=True,
        )
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(text)
        preview.setAccessibleName(tr("Redacted diagnostics preview"))
        preview.setAccessibleDescription(
            tr("Read-only support data with private values removed.")
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.addButton(
            tr("Save diagnostics"), QDialogButtonBox.ButtonRole.ActionRole
        )
        save_button.setProperty("class", "secondary")
        save_button.setAccessibleDescription(
            tr("Save the redacted diagnostics as a JSON file.")
        )
        save_button.clicked.connect(lambda: self._save_diagnostics_text(text))
        copy_button = buttons.addButton(
            tr("Copy to clipboard"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        copy_button.setProperty("class", "primary")
        copy_button.setAccessibleDescription(
            tr("Copy the redacted diagnostics and close this review.")
        )
        copy_button.setDefault(True)
        copy_button.clicked.connect(dialog.accept)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setProperty("class", "secondary")
            cancel_button.setAccessibleDescription(
                tr("Close the diagnostics review without copying anything.")
            )
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addWidget(preview, 1)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            QApplication.clipboard().setText(text)
            self._append_log("Redacted diagnostics copied to clipboard")

    def _diagnostics_text(self):
        recent_commands = []
        for dl in self.dl_manager.snapshot():
            command_args = getattr(dl, 'command_args', None) or []
            if dl.status in ("failed", "complete", "skipped") and command_args:
                recent_commands.append({
                    'status': dl.status,
                    'command': " ".join(str(arg) for arg in command_args),
                })
        payload = self._dependencies['build_diagnostics_bundle'](
            server_running=self.server_running,
            endpoint=self.dash_endpoint.text(),
            active_downloads=self.dl_manager.active_count(),
            completed_downloads=self.dl_manager.total_completed,
            recent_logs=self._dependencies['get_recent_log_entries'](),
            secrets=(self.config.get('ServerToken', ''), self.cfg_token.text()),
            recent_commands=recent_commands,
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _save_diagnostics_text(self, text):
        target, _filter = QFileDialog.getSaveFileName(
            self,
            tr("Save diagnostics"),
            str(Path.home() / "astra-diagnostics.json"),
            "JSON files (*.json);;All files (*)",
        )
        if not target:
            return False
        try:
            Path(target).write_text(str(text), encoding="utf-8")
        except OSError as error:
            self._append_log(f"Could not save diagnostics: {error}")
            return False
        self._append_log(f"Diagnostics saved to {Path(target).name}")
        return True

    def _reveal_log_file(self):
        path = Path(self._value('LOG_PATH'))
        try:
            if not path.is_file():
                self._dependencies['write_persistent_log'](
                    "Reveal log requested; creating the persisted server log."
                )
            command = self._dependencies['build_reveal_command'](str(path))
            if not command:
                self._append_log("The persisted server log is not available yet.")
                return False
            self._dependencies['spawn_detached'](command)
            self._append_log("Revealed the persisted server log.")
            return True
        except Exception as error:
            self._append_log(f"Could not reveal the persisted server log: {error}")
            return False

    def _restore_log_view(self):
        entries = self._dependencies['get_recent_log_entries']()
        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get('msg') or '').strip()
            if not message:
                continue
            timestamp = str(entry.get('ts') or '')
            lines.append(f"{timestamp[-8:]} {message}" if timestamp else message)
        self.log_text.setPlainText("\n".join(lines))
        self.log_empty_state.setVisible(not lines)
        self.log_text.setVisible(bool(lines))
        self._sync_log_empty_state()

    def _sync_log_empty_state(self):
        """Say why the log is empty, which depends on whether the API is up.

        The card used to tell the user to start the server while the page
        beside it said Server online, Running, and offered Stop server. With
        the API up the honest answer is that nothing has happened yet, and
        there is nothing to start.
        """
        empty_state = getattr(self, "log_empty_state", None)
        if empty_state is None:
            return
        running = bool(getattr(self, "server_running", False))
        title = getattr(empty_state, "empty_title", None)
        body = getattr(empty_state, "empty_body", None)
        action = getattr(empty_state, "empty_action", None)
        if title is not None:
            title.setText(
                tr("No events yet") if running else tr("No server events yet")
            )
        if body is not None:
            body.setText(
                tr(
                    "The local API is running. Pair the browser extension or "
                    "send a download to see activity here."
                )
                if running else
                tr(
                    "Start the local API or pair the browser extension to see "
                    "recent activity here."
                )
            )
        if action is not None:
            action.setVisible(not running)

    def _clear_log(self):
        self.log_text.clear()
        self.log_empty_state.setVisible(True)
        self.log_text.setVisible(False)
        self._sync_log_empty_state()

    def _toggle_token_visible(self):
        showing = self.cfg_token.echoMode() == QLineEdit.EchoMode.Normal
        self.cfg_token.setEchoMode(QLineEdit.EchoMode.Password if showing else QLineEdit.EchoMode.Normal)
        self.btn_token_reveal.setText(tr("Reveal") if showing else tr("Hide"))
        self.btn_token_reveal.setAccessibleName(
            tr("Reveal private token") if showing else tr("Hide private token")
        )

    def _regenerate_token(self):
        self.cfg_token.setText(uuid.uuid4().hex)
        self._append_log("New server token generated. Save settings to apply it.")
        self._mark_settings_dirty()
        self._show_settings_status("New token ready. Save settings to apply it.", "warning")

    def _open_folder(self):
        p = self.config.get("DownloadPath", "")
        try:
            target = Path(p) if p else self._value('INSTALL_DIR')
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))
        except Exception as e:
            self._append_log(f"Could not open folder: {e}")

    def _append_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_empty_state.setVisible(False)
        self.log_text.setVisible(True)
        self.log_text.append(f"{ts} {msg}")
        self._dependencies['write_persistent_log'](msg)
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    def _show_server_error(self, msg):
        """Report startup failures without stealing focus from the active desktop."""
        try:
            self._append_log(f"Server failed to start: {msg}")
            self.status_label.setText(tr("Server error"))
            self.status_label.setProperty("tone", "danger")
            self.status_label.setAccessibleName(tr("Server status: Error"))
            self.status_dot.setProperty("tone", "danger")
            self.status_dot.setAccessibleName(tr("Server status indicator: Error"))
            self.server_badge.setProperty("tone", "danger")
            self.server_badge.setAccessibleName(
                tr("Extension server status indicator: Error")
            )
            repolish(self.status_label)
            repolish(self.status_dot)
            repolish(self.server_badge)
            self.dash_hint.setText(
                tr("Server failed to start. Check the log for details.")
            )
            if self.tray.isVisible():
                self.tray.showMessage(
                    "Astra Downloader",
                    tr("Server failed to start. Check the log for details."),
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )
        except Exception:
            # reason: server error reporting must not mask the startup failure
            pass

    def _start_instance_command_listener(self):
        if self._instance_command_thread and self._instance_command_thread.is_alive():
            return

        def run():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                    # SO_REUSEADDR on Windows lets a later binder take the
                    # listening port from underneath this one. The control
                    # port is single-instance arbitration, so a second binder
                    # must fail rather than win.
                    exclusive = getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)
                    if exclusive is not None:
                        server.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                    server.bind((self._value('INSTANCE_CONTROL_HOST'), self._value('INSTANCE_CONTROL_PORT')))
                    server.listen(4)
                    server.settimeout(0.5)
                    self._dependencies['write_persistent_log'](
                        f"Instance command listener started on {self._value('INSTANCE_CONTROL_HOST')}:{self._value('INSTANCE_CONTROL_PORT')}."
                    )
                    while not self._instance_command_stop.is_set():
                        try:
                            conn, _addr = server.accept()
                        except socket.timeout:
                            continue
                        except OSError:
                            if self._instance_command_stop.is_set():
                                break
                            raise
                        with conn:
                            try:
                                conn.settimeout(0.5)
                                raw = conn.recv(256)
                            except OSError:
                                continue
                        # `<token> <command>`. Without the token any local
                        # process could stop a download mid-flight or bring the
                        # local API up behind the user's back.
                        # Split on the FIRST space: the token never contains
                        # one, and `download <url>` carries its own.
                        presented, _, command = (
                            raw.decode('ascii', errors='ignore').strip().partition(' ')
                        )
                        expected = str(self.config.get('ServerToken', '') or '')
                        if not expected or not hmac.compare_digest(presented, expected):
                            self.log_message.emit(
                                "Rejected an instance command without a valid token."
                            )
                            continue
                        command = command.strip()
                        # A download command carries a URL, whose case must
                        # survive — `send_instance_command` splits the token
                        # off on the first space for exactly this reason. The
                        # fixed verbs are matched case-insensitively; folding
                        # the whole line used to drop every ytdl:// link,
                        # because `download https://…` matched nothing here.
                        if command.lower().startswith('download '):
                            self.instance_command.emit(command)
                        elif command.lower().startswith('jump '):
                            self.instance_command.emit(command.lower())
                        elif command.lower() in {'show', 'start', 'shutdown'}:
                            self.instance_command.emit(command.lower())
            except OSError as e:
                if not self._instance_command_stop.is_set():
                    self.log_message.emit(f"Instance command listener unavailable: {e}")

        self._instance_command_thread = threading.Thread(
            target=run,
            daemon=True,
            name="AstraDownloaderInstanceCommand"
        )
        self._instance_command_thread.start()

    def _stop_instance_command_listener(self):
        if not self._instance_command_thread:
            return
        self._instance_command_stop.set()
        try:
            with socket.create_connection((self._value('INSTANCE_CONTROL_HOST'), self._value('INSTANCE_CONTROL_PORT')), timeout=0.2):
                pass
        except OSError:
            # reason: the listener may already be stopped when the wake-up connection fails
            pass
        if self._instance_command_thread.is_alive():
            self._instance_command_thread.join(timeout=1)
        self._instance_command_thread = None

    def _handle_instance_command(self, command):
        command = str(command).strip()
        if command.lower().startswith('download '):
            # A ytdl:// or mediadl:// link. It goes through the paste box so it
            # meets exactly the same URL policy a typed link does.
            self.enqueue_protocol_download(command.split(' ', 1)[1].strip())
            return
        if command.lower().startswith('jump '):
            self.run_jump_list_task(command.split(' ', 1)[1].strip())
            return
        command = command.lower()
        if command == 'show':
            self._append_log("Received request to show the existing window.")
            self._show_from_tray()
            return
        if command == 'shutdown':
            self._append_log("Received uninstall shutdown request.")
            self._force_close()
            return
        if command != 'start':
            return
        self._append_log("Received browser start request.")
        if self.server_running:
            self._append_log("Server already running.")
            return
        if self._setup_running:
            self._append_log("Setup is running. The server will start when setup finishes.")
            return
        self._start_server()

    def run_jump_list_task(self, task):
        """Act on a taskbar jump-list Task, from a cold start or a live one."""
        task = str(task or '').strip().lower()
        if task == 'paste':
            self._show_from_tray()
            self._nav_click("Download")
            link = QApplication.clipboard().text().strip()
            # Only a link. The clipboard is whatever the user last copied,
            # and pasting a paragraph of text into the box would be worse
            # than pasting nothing.
            url, error = self._dependencies['normalize_url'](link)
            if error or not url:
                self.quick_download_url.setFocus()
                self._set_quick_download_status(
                    tr("Copy a video link, then choose Paste and download."),
                    "warning",
                )
                return False
            self.quick_download_url.setText(url)
            self._start_quick_download()
            return True
        if task == 'downloads':
            # The task is context-free: it opens the folder and does not need
            # the window, which is the point of offering it when the app is
            # closed. _open_folder creates the folder if it is missing.
            self._open_folder()
            return True
        self._append_log(f"Ignored an unknown jump-list task: {task}")
        return False

    def enqueue_protocol_download(self, url):
        """Queue a URL handed over by the ytdl:// / mediadl:// handler."""
        url = str(url or '').strip()
        if not url:
            self._append_log("Received a protocol link with no URL.")
            return False
        self._append_log(f"Received a protocol download request for {url}")
        self._show_from_tray()
        self._nav_click("Download")
        self.quick_download_url.setText(url)
        self.quick_download_start.clear()
        self.quick_download_end.clear()
        self._start_quick_download()
        return True

    # ── Tray ──
    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.activateWindow()

    def _minimize_to_tray(self):
        self.hide()

    def _force_close(self):
        self._force_exit = True
        self.close()

    def _downloads_that_will_be_cancelled(self):
        """Count running and pending work before ``cancel_all`` is called."""
        count = 0
        for method_name in ("active_count", "pending_count"):
            method = getattr(self.dl_manager, method_name, None)
            if not callable(method):
                continue
            try:
                count += max(0, int(method()))
            except (TypeError, ValueError, OverflowError):
                continue
        return count

    def closeEvent(self, event):
        self._persist_window_state()
        if not self._force_exit and self.config.get("CloseToTray", True):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown and self.tray.isVisible():
                self.tray.showMessage(
                    self._value('APP_NAME'),
                    tr(
                        "Still running in the tray so Astra Deck can keep sending downloads."
                    ),
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self._tray_hint_shown = True
        else:
            self._stop_instance_command_listener()
            if self.server_running or self._server_starting:
                self._stop_server()
            else:
                subscription_manager = self._subscription_manager()
                if subscription_manager is not None:
                    subscription_manager.stop()
            cancelling = self._downloads_that_will_be_cancelled()
            if cancelling:
                message = tr(
                    "Closing now will cancel {count} active downloads."
                ).format(count=cancelling)
                # The close path must stay non-blocking. The log and tray
                # warning tell the user what is about to happen immediately
                # before the queue is cancelled, including for tray exit.
                self._append_log(message)
                if self.tray.isVisible():
                    self.tray.showMessage(
                        self._value('APP_NAME'),
                        message,
                        QSystemTrayIcon.MessageIcon.Warning,
                        5000,
                    )
            self.dl_manager.cancel_all()
            worker = getattr(self, "setup_worker", None)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(5000):
                    worker.terminate()
                    worker.wait()
            readiness_thread = getattr(self, "readiness_thread", None)
            if readiness_thread is not None and readiness_thread.isRunning():
                readiness_thread.requestInterruption()
                readiness_thread.quit()
                if not readiness_thread.wait(5000):
                    readiness_thread.terminate()
                    readiness_thread.wait()
            self.tray.hide()
            self.tools_status_timer.stop()
            self.update_timer.stop()
            self.cleanup_timer.stop()
            # These three outlived the window. A link typed within the format
            # probe's debounce fired after close and spawned a `yt-dlp -J`
            # that cancel_all() does not track, so it kept running for up to
            # its 60s timeout after the user had quit.
            self._format_probe_timer.stop()
            self._ui_refresh_timer.stop()
            self._history_filter_timer.stop()
            event.accept()

    # ── First-run setup ──
    def _run_setup(self, force_ffmpeg=False):
        if self._setup_running:
            return
        if self.config.get('GenerateSubtitles', False):
            model_usable = self._dependencies.get('managed_binary_usable')
            if callable(model_usable) and not model_usable(
                self._value('WHISPER_MODEL_PATH'),
                self._value('WHISPER_MODEL_MIN_BYTES'),
            ):
                self._model_setup_attempted = True
        self._setup_running = True
        self._append_log("Refreshing ffmpeg..." if force_ffmpeg else "Running first-time setup...")
        self.setup_status.setText(tr("Installing required download tools…"))
        self.setup_status.show()
        self.setup_progress.setValue(0)
        self.setup_progress.show()
        self.btn_startstop.setEnabled(False)
        self._set_control_label(self.btn_startstop, tr("Setting up"))
        self.setup_worker = self._dependencies['SetupWorker'](
            force_ffmpeg=force_ffmpeg,
            auto_update_ytdlp=self.config.get("AutoUpdateYtDlp", True),
            configured_runtime=self.config.get("JavaScriptRuntime", "auto"),
            config=self.config,
        )
        self.setup_worker.log.connect(self._append_log)
        self.setup_worker.progress.connect(self._setup_progress)
        self.setup_worker.finished_ok.connect(self._setup_done)
        self.setup_worker.finished_err.connect(self._setup_failed)
        self.setup_worker.start()

    def _setup_progress(self, value):
        self.setup_progress.setValue(value)
        if value < 30:
            self.setup_status.setText(tr("Installing yt-dlp…"))
        elif value < 60:
            self.setup_status.setText(tr("Installing ffmpeg…"))
        elif value < 70:
            self.setup_status.setText(tr("Preparing transcription model…"))
        elif value < 95:
            self.setup_status.setText(tr("Registering shortcuts and protocols…"))
        else:
            self.setup_status.setText(tr("Finishing setup…"))

    def _setup_done(self):
        ffmpeg_refresh = bool(getattr(getattr(self, 'setup_worker', None), 'force_ffmpeg', False))
        self._setup_running = False
        self.btn_startstop.setEnabled(True)
        self._set_control_label(
            self.btn_startstop,
            tr("Stop server") if self.server_running else tr("Start server"),
        )
        self.setup_progress.setValue(100)
        self.setup_status.setText(
            tr("ffmpeg refresh complete.")
            if ffmpeg_refresh else tr("Setup complete.")
        )
        self._append_log("ffmpeg refresh complete." if ffmpeg_refresh else "Setup complete. Starting server...")
        if ffmpeg_refresh:
            self._value('_ffmpeg_version_probe').reset()
            self._dependencies['reset_ffmpeg_capabilities_cache']()
            try:
                self.config.set("LastFfmpegCheck", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self.config.save()
            except Exception as e:
                self._append_log(f"ffmpeg refreshed, but its check timestamp could not be saved: {e}")
        # v1.2.0: refresh the Tools panel version readout now that the
        # binaries are (re)installed.
        self._refresh_tools_status()
        self._start_readiness_probe()
        if not self.server_running and not ffmpeg_refresh:
            self._start_server()
        QTimer.singleShot(1400, self.setup_status.hide)
        QTimer.singleShot(1400, self.setup_progress.hide)

    def _setup_failed(self, error):
        ffmpeg_refresh = bool(getattr(getattr(self, 'setup_worker', None), 'force_ffmpeg', False))
        self._setup_running = False
        self.btn_startstop.setEnabled(True)
        self._set_control_label(
            self.btn_startstop,
            tr("Stop server") if self.server_running else tr("Start server"),
        )
        self.setup_status.setText(
            tr("ffmpeg refresh failed. The previous copy is still installed.")
            if ffmpeg_refresh else
            tr("Setup failed. Check the log for details.")
        )
        self.setup_progress.hide()
        self._append_log(f"Setup error: {error}")

MainWindow = MainWindowCore


_OWNED_EXPORTS = {
    "repolish", "tr_format", "make_label", "make_section_label", "make_divider",
    "make_card", "make_status_badge", "download_status_tone",
    "human_status", "format_duration", "make_empty_state", "make_stat",
    "ReadinessProbe",
    "FolderPickerService",
    "SetupWorker", "SetupWorkerCore",
    "MainWindow", "MainWindowCore",
    "GUI_ACCESSIBILITY_COLORS", "system_reduced_motion_enabled",
    "set_gui_theme", "set_line_icon", "refresh_line_icons",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
