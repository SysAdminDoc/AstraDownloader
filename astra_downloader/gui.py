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

from PyQt6.QtCore import (
    QByteArray, QCoreApplication, QEasingCurve, QObject, QPropertyAnimation, QSize,
    QThread, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
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


__all__ = (
    "MainWindow", "SetupWorker", "FolderPickerService", "repolish",
    "make_label", "make_section_label", "make_divider", "make_card",
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
    "default_download_path",
    "filter_subscription_records", "filter_site_login_entries",
)

GUI_ACCESSIBILITY_COLORS = {
    "surface": "#0a0d12",
    "sidebar": "#080b0f",
    "log_surface": "#0d1218",
    "primary": "#fff8f4",
    "muted": "#8d97a4",
    "neutral": "#9ca5b0",
    "neutral_indicator": "#747f8d",
    "readiness_text": "#d9dde2",
    "log_text": "#b4bcc6",
    "success": "#75dcb1",
    "warning": "#edbd76",
    "danger": "#ff8d82",
}

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value):
    """Keep untrusted history text literal when opened by a spreadsheet."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


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
        return False


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def tr(text):
    """Translate a static companion UI string through the installed catalogue."""
    return QCoreApplication.translate("AstraDownloader", str(text))


# The languages worth a checkbox. The free-text field beside them still takes
# any code yt-dlp accepts — these exist so picking Simplified Chinese does not
# require knowing it is spelled zh-Hans.
SUBTITLE_LANGUAGE_CHOICES = (
    ("English", "en"), ("Spanish", "es"), ("Portuguese", "pt"),
    ("French", "fr"), ("German", "de"), ("Italian", "it"),
    ("Russian", "ru"), ("Japanese", "ja"), ("Korean", "ko"),
    ("Chinese", "zh-Hans"), ("Hindi", "hi"), ("Arabic", "ar"),
)


def make_label(text, class_name=None, word_wrap=False):
    label = QLabel(tr(text))
    # Plain text, always. Most strings reaching a label are not ours — video
    # and channel titles come from remote metadata and error text is yt-dlp
    # output, and `clean_text` deliberately preserves `<` and `>`. Qt's default
    # AutoText would parse those as HTML: a title like
    # `Clip <img src="http://host/beacon.png">` renders as rich text and Qt
    # fetches the image, turning a queue row into an outbound request from a
    # loopback-only app. Setting the format at the one construction point
    # covers every current and future caller.
    label.setTextFormat(Qt.TextFormat.PlainText)
    if class_name:
        label.setProperty("class", class_name)
    label.setWordWrap(word_wrap)
    return label


def make_section_label(text):
    return make_label(text, "section")


def make_divider():
    divider = QFrame()
    divider.setProperty("class", "divider")
    return divider


def make_vertical_divider():
    divider = QFrame()
    divider.setProperty("class", "verticalDivider")
    return divider


def make_card(class_name="card"):
    frame = QFrame()
    frame.setProperty("class", class_name)
    return frame


def make_status_badge(text, tone="neutral"):
    translated = tr(text)
    badge = QLabel(translated)
    badge.setTextFormat(Qt.TextFormat.PlainText)
    badge.setProperty("class", "badge")
    badge.setProperty("tone", tone)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setMinimumHeight(22)
    badge.setAccessibleName(f"{tr('Status')}: {translated}")
    return badge


def make_state_label(text, tone="neutral"):
    translated = tr(text)
    label = QLabel(f"\u25cf  {translated}")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("class", "stateLabel")
    label.setProperty("tone", tone)
    label.setAccessibleName(f"{tr('Status')}: {translated}")
    return label


def make_line_icon(name, size=18):
    """Draw the rail icons from one quiet monochrome system.

    Geometry is authored on an 18 px grid. Pass a larger ``size`` (e.g. the
    36 px empty-state glyph) to rasterize the same paths crisply instead of
    upscaling an 18 px pixmap — the painter is scaled so both the coordinates
    and the 1.5 px stroke grow proportionally.
    """
    key = str(name).lower()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if size != 18:
        painter.scale(size / 18, size / 18)
    painter.setPen(QPen(QColor("#aab2bd"), 1.5, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if key == "dashboard":
        for x, y in ((2, 2), (10, 2), (2, 10), (10, 10)):
            painter.drawRoundedRect(x, y, 6, 6, 1, 1)
    elif "extension" in key or "browser" in key:
        # A puzzle-piece read badly at 18px, so this is a plug: the server
        # is the socket the extension connects into. Ordered before the
        # "browse"/folder branch, which "browser" would otherwise match.
        painter.drawRoundedRect(5, 7, 8, 9, 1, 1)
        painter.drawLine(7, 7, 7, 3)
        painter.drawLine(11, 7, 11, 3)
        painter.drawLine(9, 16, 9, 17)
    elif key == "downloads" or "download" in key:
        painter.drawLine(9, 2, 9, 12)
        painter.drawLine(5, 9, 9, 13)
        painter.drawLine(13, 9, 9, 13)
        painter.drawLine(3, 16, 15, 16)
    elif key == "history":
        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(9, 5, 9, 9)
        painter.drawLine(9, 9, 12, 11)
    elif "start" in key or "resume" in key:
        painter.drawLine(5, 3, 15, 9)
        painter.drawLine(15, 9, 5, 15)
        painter.drawLine(5, 15, 5, 3)
    elif "stop" in key:
        painter.drawRoundedRect(4, 4, 10, 10, 1, 1)
    elif "pause" in key:
        painter.drawLine(6, 3, 6, 15)
        painter.drawLine(12, 3, 12, 15)
    elif "copy" in key:
        painter.drawRoundedRect(5, 3, 9, 11, 1, 1)
        painter.drawRoundedRect(2, 6, 9, 10, 1, 1)
    elif "folder" in key or "browse" in key or key == "show":
        painter.drawLine(2, 6, 7, 6)
        painter.drawLine(7, 6, 9, 8)
        painter.drawLine(9, 8, 16, 8)
        painter.drawRoundedRect(2, 5, 14, 11, 1, 1)
    elif "clear" in key or "cancel" in key:
        painter.drawLine(5, 6, 6, 16)
        painter.drawLine(13, 6, 12, 16)
        painter.drawLine(6, 16, 12, 16)
        painter.drawLine(4, 5, 14, 5)
        painter.drawLine(7, 2, 11, 2)
    elif "save" in key:
        painter.drawRoundedRect(3, 2, 12, 14, 1, 1)
        painter.drawLine(6, 2, 6, 7)
        painter.drawLine(6, 7, 12, 7)
        painter.drawEllipse(6, 10, 6, 4)
    elif any(word in key for word in ("regenerate", "reinstall", "update", "retry")):
        painter.drawArc(3, 3, 12, 12, 35 * 16, 275 * 16)
        painter.drawLine(12, 2, 15, 4)
        painter.drawLine(15, 4, 14, 8)
    elif "reveal" in key:
        painter.drawEllipse(2, 5, 14, 8)
        painter.drawEllipse(7, 7, 4, 4)
    elif "diagnostic" in key:
        painter.drawRoundedRect(3, 2, 12, 14, 1, 1)
        painter.drawLine(6, 6, 12, 6)
        painter.drawLine(6, 9, 12, 9)
        painter.drawLine(6, 12, 10, 12)
    elif key in ("up", "down"):
        direction = -1 if key == "up" else 1
        y_tip = 4 if direction == -1 else 14
        y_tail = 14 if direction == -1 else 4
        painter.drawLine(9, y_tail, 9, y_tip)
        painter.drawLine(9, y_tip, 5, y_tip - (4 * direction))
        painter.drawLine(9, y_tip, 13, y_tip - (4 * direction))
    elif "previous" in key or "next" in key:
        direction = -1 if "previous" in key else 1
        x_tip = 5 if direction == -1 else 13
        x_tail = 12 if direction == -1 else 6
        painter.drawLine(x_tail, 3, x_tip, 9)
        painter.drawLine(x_tip, 9, x_tail, 15)
    elif "sign-in" in key or "signin" in key:
        painter.drawEllipse(2, 6, 7, 7)
        painter.drawLine(8, 9, 16, 9)
        painter.drawLine(13, 9, 13, 13)
        painter.drawLine(16, 9, 16, 12)
    elif "export" in key:
        painter.drawLine(9, 2, 9, 12)
        painter.drawLine(5, 6, 9, 2)
        painter.drawLine(13, 6, 9, 2)
        painter.drawLine(3, 10, 3, 16)
        painter.drawLine(3, 16, 15, 16)
        painter.drawLine(15, 16, 15, 10)
    else:
        painter.drawLine(2, 5, 16, 5)
        painter.drawLine(2, 9, 16, 9)
        painter.drawLine(2, 13, 16, 13)
        painter.drawEllipse(5, 3, 4, 4)
        painter.drawEllipse(10, 7, 4, 4)
        painter.drawEllipse(4, 11, 4, 4)
    painter.end()
    return QIcon(pixmap)


def download_status_tone(status):
    if status == "complete":
        return "success"
    if status in ("failed", "cancelled"):
        return "danger"
    if status == "skipped":
        return "warning"
    if status in ("merging", "extracting", "trimming", "transcribing", "queued", "pending", "paused", "needs-auth"):
        return "warning"
    if status == "downloading":
        return "info"
    return "neutral"


def describe_rejected_links(failures):
    """Describe rejected links without inventing a single shared cause.

    Reporting only the first reason made two different failures read as one,
    so distinct reasons are counted and the leading one is named.
    """
    reasons = []
    for _url, reason in failures:
        if reason not in reasons:
            reasons.append(reason)
    noun = "link" if len(failures) == 1 else "links"
    if len(reasons) == 1:
        return f"{len(failures)} {noun} rejected: {reasons[0]}"
    return (
        f"{len(failures)} {noun} rejected for {len(reasons)} different "
        f"reasons. First: {reasons[0]}"
    )


def filter_subscription_records(records, query="", status="all"):
    """Filter subscription rows without touching the durable manager state."""
    query = str(query or "").strip().casefold()
    status = str(status or "all").casefold()
    visible = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        haystack = " ".join(
            str(record.get(field) or "")
            for field in ("title", "url", "lastError")
        ).casefold()
        if query and query not in haystack:
            continue
        enabled = bool(record.get("enabled", True))
        has_error = bool(str(record.get("lastError") or "").strip())
        if status == "active" and not enabled:
            continue
        if status == "disabled" and enabled:
            continue
        if status == "needs-attention" and not has_error:
            continue
        visible.append(record)
    return visible


def filter_site_login_entries(entries, query="", status="all"):
    """Filter stored sign-ins by site and whether their jar is usable."""
    query = str(query or "").strip().casefold()
    status = str(status or "all").casefold()
    visible = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(
            str(entry.get(field) or "") for field in ("site", "source")
        ).casefold()
        if query and query not in haystack:
            continue
        expired = bool(entry.get("expired"))
        stored = bool(entry.get("stored"))
        if status == "stored" and (expired or not stored):
            continue
        if status == "expired" and not expired:
            continue
        if status == "missing" and stored:
            continue
        visible.append(entry)
    return visible


def human_status(status):
    return {
        "queued": "Queued",
        "pending": "Pending",
        "paused": "Paused",
        "needs-auth": "Needs sign-in",
        "downloading": "Downloading",
        "merging": "Merging",
        "extracting": "Extracting",
        "trimming": "Trimming",
        "transcribing": "Generating subtitles",
        "complete": "Complete",
        "failed": "Failed",
        "cancelled": "Cancelled",
        "skipped": "Nothing downloaded",
    }.get(status, str(status).title())


def format_duration(seconds):
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def make_empty_state(title, body, action_text=None, action=None):
    frame = make_card("empty")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(36, 28, 36, 28)
    layout.setSpacing(9)
    layout.addStretch(2)
    glyph = QLabel()
    glyph.setProperty("class", "emptyGlyph")
    glyph.setPixmap(make_line_icon("Download" if "Queue" in title else "History", size=36).pixmap(36, 36))
    glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(glyph)
    empty_title = make_label(title, "emptyTitle")
    empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(empty_title)
    empty_body = make_label(body, "emptyBody", word_wrap=True)
    empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(empty_body)
    if action_text and callable(action):
        translated_action = tr(action_text)
        button = QPushButton(translated_action)
        button.setProperty("class", "secondary")
        button.setAccessibleName(translated_action)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(action)
        layout.addSpacing(8)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
    layout.addStretch(3)
    return frame


def make_stat(label_text, value_text="0", hint_text=""):
    frame = QFrame()
    frame.setProperty("class", "stat")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 20, 10)
    layout.setSpacing(4)
    label = make_label(label_text, "metricLabel")
    value = QLabel(value_text)
    value.setTextFormat(Qt.TextFormat.PlainText)
    value.setAlignment(Qt.AlignmentFlag.AlignLeft)
    value.setProperty("class", "metricValue")
    value.setObjectName(f"stat_{label_text.lower()}")
    layout.addWidget(label)
    layout.addWidget(value)
    if hint_text:
        layout.addWidget(make_label(hint_text, "fieldHint"))
    return frame, value


class ReadinessProbe(QObject):
    """Collect injected toolchain health away from the GUI thread."""

    completed = pyqtSignal(dict)

    def __init__(self, configured_runtime='auto', *, runtime_probe,
                 provider_probe, ytdlp_version, ffmpeg_version, logger,
                 impersonate_targets=None, whisper_model_state=None,
                 whisper_runtime_state=None):
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
                "ytDlp": self._ytdlp_version() or "",
                "ffmpeg": self._ffmpeg_version() or "",
                "runtime": runtime or {},
                "deno": runtime or {},
                "provider": provider or {},
                "impersonateTargets": targets or [],
                "whisperModel": whisper_model,
                "whisperRuntime": whisper_runtime,
            }
        except Exception as error:
            self._logger(f"Readiness probe failed: {error}")
            payload = {"error": str(error)}
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
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

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
        """Return whether ffmpeg is absent, stale, damaged, or forced."""
        if self.force_ffmpeg or state != 'ok':
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
            ready = bool(self._dependencies['provision_deno']())
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
                self._dependencies['download_file_atomic'](
                    self._value('YTDLP_URL'), self._value('YTDLP_PATH'), timeout=60, chunk_size=65536,
                    progress_cb=self._ranged_progress_cb(10, 28),
                )
                # Verify against the release SHA-256 sidecar before trusting
                # the binary — it'll be executed with user privileges for
                # every download from now on.
                self._verify_required_checksum(
                    self._value('YTDLP_PATH'), self._value('YTDLP_SHA256_URL'),
                    asset_name=self._value('YTDLP_SHA256_ASSET'), label="yt-dlp",
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
    'spawn_detached',
    'summarize_taskbar_progress',
    'build_settings_bundle',
    'read_settings_bundle',
    'describe_bundle_changes',
    'TaskbarProgress',
    'APP_NAME',
    'APP_VERSION',
    'DEFAULT_CONFIG',
    'DOWNLOAD_PENDING_STATES',
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
    'estimate_download_bytes',
    'sabr_only_formats',
    'SABR_LIMITED_NOTICE',
    'quality_choices_for_heights',
    'looks_like_media_link',
    'MANAGED_BINARY_ANTIVIRUS_ADVICE',
    'managed_binary_state',
    'managed_binary_usable',
    'maybe_auto_update_ytdlp',
    'normalize_output_dir',
    'normalize_download_section',
    'normalize_output_template',
    'output_template_preview',
    'normalize_playlist_date',
    'normalize_impersonate_target',
    'probe_impersonate_targets',
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
})


class MainWindowCore(QMainWindow):
    log_message = pyqtSignal(str)
    instance_command = pyqtSignal(str)
    tools_update_finished = pyqtSignal(dict)
    tools_status_text_ready = pyqtSignal(str)
    server_start_finished = pyqtSignal(object)
    site_login_finished = pyqtSignal(dict)
    site_login_test_finished = pyqtSignal(dict)
    format_probe_finished = pyqtSignal(dict)

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
        self._restoring_window_state = False
        self.log_message.connect(self._append_log)
        self.instance_command.connect(self._handle_instance_command)
        self.tools_update_finished.connect(self._finish_ytdlp_update)
        self.tools_status_text_ready.connect(self._set_tools_status_text)
        self.server_start_finished.connect(self._finish_server_start)
        self.site_login_finished.connect(self._finish_site_login_import)
        self.site_login_test_finished.connect(self._finish_site_login_test)
        self.format_probe_finished.connect(self._apply_format_probe)
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
            brand_icon.setStyleSheet(
                "background:#ff6552;color:#180706;border-radius:8px;"
                "font-size:18px;font-weight:800;"
            )
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(2)
        title_lbl = make_label("ASTRA DOWNLOADER")
        title_lbl.setStyleSheet(
            "font-size: 12px; font-weight: 750; "
            f"color: {GUI_ACCESSIBILITY_COLORS['primary']}; letter-spacing: .35px;"
        )
        ver_lbl = make_label(f"LOCAL  ·  v{self._value('APP_VERSION')}", "muted")
        ver_lbl.setStyleSheet(
            f"font-size: 11px; color: {GUI_ACCESSIBILITY_COLORS['muted']};"
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
            "Download", "History", "Sign-ins", "Subscriptions",
            "Browser extension", "Settings",
        ]
        for name in self._page_names:
            translated_name = tr(name)
            btn = QPushButton(translated_name)
            btn.setProperty("class", "nav")
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setAccessibleName(f"{translated_name} {tr('page')}")
            btn.setIcon(make_line_icon(name))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{tr('Open')} {translated_name}")
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
        self.tabs.tabBar().hide()
        self.tabs.setAccessibleName(tr("Companion pages"))
        main_layout.addWidget(self.tabs)

        # readiness_values is populated by every page that owns a status
        # row, so it has to exist before the first _build_* call rather
        # than inside whichever page happened to be built first.
        self.readiness_values = {}
        self._build_download()
        self._build_history()
        self._build_site_logins()
        self._build_subscriptions()
        self._build_extension()
        self._build_settings()

        self._restore_window_state(start_minimized)

        # System tray
        self.tray = QSystemTrayIcon(self)
        if self._value('ICON_PATH').exists():
            self.tray.setIcon(QIcon(str(self._value('ICON_PATH'))))
        else:
            self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Astra Downloader")
        show_action.triggered.connect(self._show_from_tray)
        self.tray_startstop = tray_menu.addAction("Stop server")
        self.tray_startstop.triggered.connect(self._toggle_server)
        folder_action = tray_menu.addAction("Open Downloads Folder")
        folder_action.triggered.connect(self._open_folder)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Quit Astra Downloader")
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
        self.tray.setToolTip(f"{self._value('APP_NAME')} - {tr('Running')}")
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
        outer.setContentsMargins(0, 13, 0, 13)
        outer.setSpacing(24)
        heading = make_label(title, "settingsSection")
        heading.setFixedWidth(142)
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
                value = ""
            if value:
                parts.append(str(value))
        if isinstance(widget, (QLabel, QCheckBox, QPushButton)):
            try:
                value = widget.text()
            except Exception:
                value = ""
            if value:
                parts.append(str(value))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                try:
                    parts.append(widget.itemText(index))
                except Exception:
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
            widget.setVisible(bool(visible))
            return
        layout = item.layout()
        if layout is None:
            return
        for index in range(layout.count()):
            self._set_settings_item_visible(layout.itemAt(index), visible)

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
        btn.setIcon(make_line_icon(text))
        btn.setIconSize(QSize(15, 15))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        target = str(target or "").strip()
        btn.setAccessibleName(f"{translated}: {target}" if target else translated)
        return btn

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

    def _start_readiness_probe(self):
        if self.readiness_thread is not None:
            return
        self.readiness_thread = QThread(self)
        self.readiness_worker = self._dependencies['ReadinessProbe'](
            self.config.get('JavaScriptRuntime', 'auto'),
            impersonate_targets=self._dependencies['probe_impersonate_targets'],
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
                combo.addItem(f"{configured} (unavailable)", configured)
            restored = combo.findData(configured)
            combo.setCurrentIndex(restored if restored >= 0 else 0)
        finally:
            combo.blockSignals(False)

    def _apply_readiness(self, payload):
        subtitles_enabled = bool(
            getattr(self, 'config', {}).get("GenerateSubtitles", False)
        )
        if payload.get("error"):
            self._apply_impersonate_targets([])
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
        self._apply_impersonate_targets(payload.get("impersonateTargets"))
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
                "No proof-of-origin provider is running. Downloads fall back to "
                "the token-exempt tv and android_vr clients.",
            )


    def _value(self, name):
        value = self._dependencies[name]
        return value() if callable(value) else value

    def _build_extension(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 38, 24)
        layout.setSpacing(16)

        layout.addLayout(self._make_page_header(
            "Browser extension",
            "Astra Downloader runs a local API so the Astra Deck browser "
            "extension can send downloads straight from a page. Downloading "
            "by pasting a link never needs this server.",
        ))

        # Server control
        ctrl = make_card("serverControl")
        ctrl_layout = QVBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(0, 10, 20, 14)
        ctrl_layout.setSpacing(13)

        state_row = QHBoxLayout()
        state_row.setSpacing(10)
        self.server_badge = make_label("\u25cf", "stateDot")
        self.server_badge.setProperty("tone", "neutral")
        self.server_badge.setAccessibleName(
            tr("Extension server status indicator: Offline")
        )
        self.dash_status = make_label("Server offline", "heroTitle")
        state_row.addWidget(self.server_badge)
        state_row.addWidget(self.dash_status)
        state_row.addStretch()
        ctrl_layout.addLayout(state_row)

        endpoint_row = QHBoxLayout()
        endpoint_row.setSpacing(14)
        self.dash_endpoint = make_label(f"http://127.0.0.1:{self.config.get('ServerPort', self._value('SERVER_PORT'))}", "secondary")
        self.dash_endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dash_hint = make_label("Local only \u00b7 token required", "fieldHint")
        endpoint_row.addWidget(self.dash_endpoint)
        endpoint_row.addWidget(make_vertical_divider())
        endpoint_row.addWidget(self.dash_hint)
        endpoint_row.addStretch()
        ctrl_layout.addLayout(endpoint_row)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_startstop = self._make_tool_button("Start server", "primary")
        self.btn_startstop.clicked.connect(self._toggle_server)
        actions.addWidget(self.btn_startstop)
        btn_copy = self._make_tool_button("Copy endpoint")
        btn_copy.clicked.connect(self._copy_endpoint)
        actions.addWidget(btn_copy)
        btn_folder = self._make_tool_button("Open folder")
        btn_folder.clicked.connect(self._open_folder)
        actions.addWidget(btn_folder)
        actions.addStretch()
        ctrl_layout.addLayout(actions)

        readiness = make_card("readiness")
        readiness_layout = QVBoxLayout(readiness)
        readiness_layout.setContentsMargins(22, 10, 0, 8)
        readiness_layout.setSpacing(1)
        readiness_header = QHBoxLayout()
        readiness_header.addWidget(make_label("Pairing", "panelTitle"))
        readiness_header.addStretch()
        readiness_layout.addLayout(readiness_header)
        readiness_layout.addWidget(self._make_readiness_row("server", "Local API", "Stopped"))
        readiness_layout.addWidget(make_label(
            "The extension finds this server on its own once it is running. "
            "Requests are accepted from this machine only and must carry the "
            "session token.",
            "fieldHint",
            word_wrap=True,
        ))
        readiness_layout.addStretch()

        hero = QHBoxLayout()
        hero.setSpacing(0)
        hero.addWidget(ctrl, 3)
        hero.addWidget(make_vertical_divider())
        hero.addWidget(readiness, 2)
        layout.addLayout(hero)

        layout.addWidget(make_divider())

        # Metrics — one strip, with rhythm supplied by separators rather than cards.
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(0)
        self._stat_frame_active, self.stat_active = make_stat("Active", "0", "In progress")
        self.stat_active.setProperty("tone", "accent")
        self._stat_frame_completed, self.stat_completed = make_stat("Completed", "0", "This session")
        self._stat_frame_uptime, self.stat_uptime = make_stat("Uptime", "--", "Since launch")
        self._stat_frame_port, self.stat_port = make_stat("Port", str(self.config.get("ServerPort", self._value('SERVER_PORT'))), "Local API")
        for frame in (self._stat_frame_active, self._stat_frame_completed,
                      self._stat_frame_uptime, self._stat_frame_port):
            stats_layout.addWidget(frame)
        self._stat_frame_port.setProperty("last", "true")
        layout.addLayout(stats_layout)
        layout.addWidget(make_divider())

        log_header = QHBoxLayout()
        log_header.addWidget(make_label("Server log", "panelTitle"))
        log_header.addStretch()
        btn_clear_log = self._make_tool_button("Clear", "ghost")
        btn_clear_log.clicked.connect(self._clear_log)
        log_header.addWidget(btn_clear_log)
        btn_diag = self._make_tool_button("Review diagnostics", "ghost")
        btn_diag.setToolTip(tr("Review the redacted support payload before copying it."))
        btn_diag.clicked.connect(self._copy_diagnostics)
        log_header.addWidget(btn_diag)
        btn_reveal_log = self._make_tool_button("Reveal log file", "ghost")
        btn_reveal_log.setToolTip(tr("Open the persisted server log in File Explorer."))
        btn_reveal_log.clicked.connect(self._reveal_log_file)
        log_header.addWidget(btn_reveal_log)
        layout.addLayout(log_header)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setAccessibleName(tr("Server log"))
        self.log_text.setAccessibleDescription(
            tr("Recent local companion events. Use Clear to remove visible entries.")
        )
        self.log_text.setMinimumHeight(180)
        self.log_text.document().setMaximumBlockCount(300)
        self._restore_log_view()
        layout.addWidget(self.log_text, 1)

        self.tabs.addTab(page, "Browser extension")

    def _build_download(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 38, 24)
        layout.setSpacing(12)
        layout.addLayout(self._make_page_header(
            "Download a video",
            "Paste a link from almost any site — YouTube, Reddit, X, TikTok, "
            "Vimeo, Instagram, Twitch and hundreds more.",
        ))

        # A fresh install needs one decision before the first download. Keep
        # it beside the paste box so setup, destination and extension pairing
        # are all discoverable from the product's landing page.
        self.first_run_panel = make_card("firstRun")
        first_run_layout = QVBoxLayout(self.first_run_panel)
        first_run_layout.setContentsMargins(16, 13, 16, 13)
        first_run_layout.setSpacing(8)
        first_run_layout.addWidget(make_label(
            "Welcome to Astra Downloader", "panelTitle"
        ))
        first_run_layout.addWidget(make_label(
            "Confirm where finished videos should go. You can change this later "
            "in Settings.",
            "fieldHint",
            word_wrap=True,
        ))
        first_run_layout.addWidget(make_label(
            "This choice is saved once for this install.",
            "fieldHint",
            word_wrap=True,
        ))
        destination_row = QHBoxLayout()
        destination_row.setSpacing(8)
        destination_copy = QVBoxLayout()
        destination_copy.setSpacing(2)
        destination_copy.addWidget(make_label(
            "Video download folder", "fieldLabel"
        ))
        destination_row.addLayout(destination_copy, 1)
        self.first_run_destination = QLineEdit(
            self.config.get("DownloadPath", self._value("DEFAULT_CONFIG")["DownloadPath"])
        )
        self.first_run_destination.setAccessibleName(tr("First-run download folder"))
        destination_row.addWidget(self.first_run_destination, 2)
        self.first_run_browse = self._make_tool_button("Browse")
        self.first_run_browse.clicked.connect(
            lambda: self._browse(self.first_run_destination)
        )
        destination_row.addWidget(self.first_run_browse)
        self.first_run_confirm = self._make_tool_button(
            "Confirm folder", "primary"
        )
        self.first_run_confirm.clicked.connect(self._confirm_first_run_destination)
        destination_row.addWidget(self.first_run_confirm)
        first_run_layout.addLayout(destination_row)
        self.first_run_status = make_label("", "fieldHint", word_wrap=True)
        self.first_run_status.setAccessibleName(tr("First-run setup status"))
        first_run_layout.addWidget(self.first_run_status)
        first_run_layout.addWidget(make_divider())
        pairing_row = QHBoxLayout()
        pairing_copy = QVBoxLayout()
        pairing_copy.setSpacing(2)
        pairing_copy.addWidget(make_label(
            "Browser extension", "fieldLabel"
        ))
        pairing_copy.addWidget(make_label(
            "When setup finishes, pair Astra Deck from the local extension page.",
            "fieldHint",
            word_wrap=True,
        ))
        pairing_row.addLayout(pairing_copy, 1)
        self.first_run_pair = self._make_tool_button(
            "Open extension pairing", "ghost"
        )
        self.first_run_pair.clicked.connect(self._open_first_run_pairing)
        pairing_row.addWidget(self.first_run_pair)
        first_run_layout.addLayout(pairing_row)
        layout.addWidget(self.first_run_panel)
        self._apply_first_run_panel_state()

        quick_card = make_card()
        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(16, 14, 16, 14)
        quick_layout.setSpacing(10)
        url_row = QHBoxLayout()
        self.quick_download_url = QLineEdit()
        self.quick_download_url.setProperty("class", "heroUrl")
        self.quick_download_url.setAccessibleName(tr("Video URL"))
        self.quick_download_url.setPlaceholderText(
            tr("Paste a video link, or several at once")
        )
        self.quick_download_url.returnPressed.connect(self._start_quick_download)
        self.quick_download_url.textEdited.connect(self._quick_download_url_edited)
        url_row.addWidget(self.quick_download_url, 1)
        self.btn_quick_download = self._make_tool_button("Download", "primary")
        self.btn_quick_download.clicked.connect(self._start_quick_download)
        url_row.addWidget(self.btn_quick_download)
        quick_layout.addLayout(url_row)

        password_row = QHBoxLayout()
        self.quick_download_video_password = QLineEdit()
        self.quick_download_video_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.quick_download_video_password.setAccessibleName(
            tr("One-link video password")
        )
        self.quick_download_video_password.setPlaceholderText(
            tr("Video password — one link only (optional)")
        )
        self.quick_download_video_password.setClearButtonEnabled(True)
        password_row.addWidget(self.quick_download_video_password, 1)
        password_row.addWidget(make_label(
            tr("For a single protected link. Stored site credentials live under Sign-ins."),
            "fieldHint",
            word_wrap=True,
        ))
        quick_layout.addLayout(password_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        options_row.addWidget(make_label("Profile", "fieldHint"))
        self.quick_download_profile = QComboBox()
        self.quick_download_profile.setAccessibleName(tr("Site profile"))
        self.quick_download_profile.setMinimumWidth(170)
        self.quick_download_profile.setToolTip(tr("Automatic site profile"))
        self.quick_download_profile.currentIndexChanged.connect(
            self._quick_download_profile_changed
        )
        options_row.addWidget(self.quick_download_profile)
        self.quick_download_type = QComboBox()
        self.quick_download_type.setAccessibleName(tr("Download type"))
        self.quick_download_type.addItem(tr("Video"), "video")
        self.quick_download_type.addItem(tr("Audio"), "audio")
        self.quick_download_type.addItem(tr("Subtitles"), "subtitles")
        self.quick_download_type.currentIndexChanged.connect(
            self._sync_quick_download_options
        )
        options_row.addWidget(self.quick_download_type)
        self.quick_download_format = QComboBox()
        self.quick_download_format.setAccessibleName(tr("Download format"))
        options_row.addWidget(self.quick_download_format)
        self.quick_download_quality = QComboBox()
        self.quick_download_quality.setAccessibleName(tr("Download quality"))
        self._set_quality_choices(self._value('QUALITY_LADDER'))
        options_row.addWidget(self.quick_download_quality)
        # A pasted link is probed for the formats it really has, so the picker
        # stops offering 2160p on a 720p video. Debounced, because a paste
        # arrives one keystroke at a time when typed.
        self._format_probe_timer = QTimer(self)
        self._format_probe_timer.setSingleShot(True)
        self._format_probe_timer.setInterval(700)
        self._format_probe_timer.timeout.connect(self._probe_quick_download_formats)
        # A one-off destination for this download, without disturbing the
        # default in Settings. Cleared once the download is queued.
        self._quick_download_dir = ""
        self.btn_quick_download_dest = self._make_tool_button("Save to", "ghost")
        self.btn_quick_download_dest.setToolTip(
            tr("Send this download somewhere other than the default folder.")
        )
        self.btn_quick_download_dest.clicked.connect(self._pick_quick_download_dir)
        options_row.addWidget(self.btn_quick_download_dest)
        options_row.addStretch()
        options_row.addWidget(make_label("Clip from", "fieldHint"))
        self.quick_download_start = QLineEdit()
        self.quick_download_start.setAccessibleName(tr("Clip start timestamp"))
        self.quick_download_start.setPlaceholderText("0:00")
        self.quick_download_start.setMaximumWidth(84)
        options_row.addWidget(self.quick_download_start)
        options_row.addWidget(make_label("to", "fieldHint"))
        self.quick_download_end = QLineEdit()
        self.quick_download_end.setAccessibleName(tr("Clip end timestamp"))
        self.quick_download_end.setPlaceholderText("1:30")
        self.quick_download_end.setMaximumWidth(84)
        options_row.addWidget(self.quick_download_end)
        quick_layout.addLayout(options_row)
        self.quick_download_clip_hint = make_label(
            tr("Clip ranges apply to a single link."), "fieldHint",
            word_wrap=True,
        )
        quick_layout.addWidget(self.quick_download_clip_hint)
        self.quick_download_profile_hint = make_label(
            "", "fieldHint", word_wrap=True
        )
        self.quick_download_profile_hint.setAccessibleName(tr("Site profile summary"))
        quick_layout.addWidget(self.quick_download_profile_hint)
        self.quick_download_subs_hint = make_label("", "fieldHint", word_wrap=True)
        self.quick_download_subs_hint.setAccessibleName(tr("Subtitle request summary"))
        self.quick_download_subs_hint.hide()
        quick_layout.addWidget(self.quick_download_subs_hint)
        # Whether the link in the box serves nothing but SABR streams.
        self._sabr_limited = False
        self.quick_download_status = make_label("", "fieldHint")
        self.quick_download_status.setAccessibleName(tr("Quick download status"))
        self.quick_download_status.hide()
        quick_layout.addWidget(self.quick_download_status)
        layout.addWidget(quick_card)
        self._sync_quick_download_options()
        self._rebuild_quick_site_profiles()

        # Tool setup progress lives with the paste box, not on the server
        # page: it reports on yt-dlp/FFmpeg, which is what makes a download
        # work, and a user who never opens the extension page still needs to
        # see it.
        self.setup_status = make_label("", "fieldHint")
        self.setup_status.setAccessibleName(tr("Download tool setup status"))
        self.setup_status.hide()
        self.setup_progress = QProgressBar()
        self.setup_progress.setRange(0, 100)
        self.setup_progress.setAccessibleName(tr("Download tool setup progress"))
        self.setup_progress.setValue(0)
        self.setup_progress.setTextVisible(False)
        self.setup_progress.hide()
        layout.addWidget(self.setup_status)
        layout.addWidget(self.setup_progress)

        # The strip that answers "why did that fail?" without leaving the
        # page. SABR is derived from the yt-dlp version by the async
        # readiness probe (_apply_readiness) — never probe yt-dlp --version
        # synchronously here: this runs on the GUI thread before first paint
        # and a cold probe costs up to 5s.
        # Three per line: a QLabel will not shrink below its text, so a fourth
        # and fifth entry on one line overlap their neighbours on a narrow
        # window at a large font rather than eliding.
        #
        # 'provider' is the PO-token provider. _apply_readiness has always
        # computed its state and the 'po-provider' failure advice refers to
        # it; with no row here _set_readiness discarded every update, so the
        # status was never visible.
        tools_grid = QVBoxLayout()
        tools_grid.setSpacing(0)
        readiness_rows = [
            ("ytDlp", "yt-dlp", "Checking"),
            ("ffmpeg", "FFmpeg", "Checking"),
            ("deno", "JavaScript runtime", "Checking"),
            ("sabr", "SABR", "Limited"),
            ("provider", "PO provider", "Fallback"),
            ("whisper", "Transcription model", "Optional"),
        ]
        for start in range(0, len(readiness_rows), 3):
            line = QHBoxLayout()
            line.setSpacing(18)
            chunk = readiness_rows[start:start + 3]
            for index, (key, label_text, initial) in enumerate(chunk):
                if index:
                    line.addWidget(make_vertical_divider())
                line.addWidget(self._make_readiness_row(key, label_text, initial), 1)
            for _ in range(3 - len(chunk)):
                line.addStretch(1)
            tools_grid.addLayout(line)
        layout.addLayout(tools_grid)

        # Durability problems that no other surface can report: a completed
        # download whose history entry could not be written, or a queue that
        # could not be saved. Both leave the app looking like it worked.
        self.persistence_notice = make_label("", "errorCallout", word_wrap=True)
        self.persistence_notice.setAccessibleName(tr("Storage problem"))
        self.persistence_notice.hide()
        layout.addWidget(self.persistence_notice)

        # A quarantined state file is set aside silently at the read site, so
        # this is the only place the user learns that config.json regenerated
        # its server token, or that a queue of pending work was discarded.
        # The original bytes are still there; restoring them is one click.
        self.quarantine_panel = QFrame()
        self.quarantine_panel.setProperty("class", "readinessRow")
        quarantine_layout = QVBoxLayout(self.quarantine_panel)
        quarantine_layout.setContentsMargins(0, 0, 0, 0)
        quarantine_layout.setSpacing(6)
        self.quarantine_notice = make_label("", "errorCallout", word_wrap=True)
        self.quarantine_notice.setAccessibleName(tr("Quarantined state file"))
        quarantine_layout.addWidget(self.quarantine_notice)
        quarantine_actions = QHBoxLayout()
        quarantine_actions.addStretch()
        self.btn_quarantine_restore = self._make_tool_button("Restore", "primary")
        self.btn_quarantine_restore.clicked.connect(self._restore_quarantined_state)
        self.btn_quarantine_dismiss = self._make_tool_button("Dismiss")
        self.btn_quarantine_dismiss.clicked.connect(self._dismiss_quarantine_notice)
        quarantine_actions.addWidget(self.btn_quarantine_restore)
        quarantine_actions.addWidget(self.btn_quarantine_dismiss)
        quarantine_layout.addLayout(quarantine_actions)
        self.quarantine_panel.hide()
        layout.addWidget(self.quarantine_panel)
        self._dismissed_quarantines = set()
        self._refresh_quarantine_notice()

        self._set_readiness("sabr", "Limited", "warning")
        layout.addWidget(make_divider())

        toolbar = QHBoxLayout()
        self.queue_capacity_badge = make_label("0 / 200 jobs", "toolbarMeta")
        self.queue_capacity_badge.setToolTip(
            tr("Running and pending downloads stored in the durable queue.")
        )
        toolbar.addWidget(self.queue_capacity_badge)
        toolbar.addStretch()
        self.btn_queue_pause = self._make_tool_button(
            "Pause intake", "ghost"
        )
        self.btn_queue_pause.setToolTip(
            tr("Pause starting pending downloads. Downloads already running will continue.")
        )
        self.btn_queue_pause.clicked.connect(self._toggle_queue_intake)
        toolbar.addWidget(self.btn_queue_pause)
        layout.addLayout(toolbar)
        layout.addWidget(make_divider())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.downloads_list_layout = QVBoxLayout(content)
        self.downloads_list_layout.setContentsMargins(0, 0, 0, 0)
        self.downloads_list_layout.setSpacing(10)
        scroll.setWidget(content)
        self.downloads_scroll = scroll
        layout.addWidget(scroll, 1)
        self.tabs.addTab(page, "Download")

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
            "manual": "creator subtitles only",
            "auto": "auto-generated subtitles only",
        }.get(mode, "creator subtitles, falling back to auto-generated")
        fmt = self._dependencies['normalize_subtitle_format'](
            self.config.get("SubtitleFormat")
        )
        as_format = f" as {fmt.upper()}" if fmt else ""
        return (
            f"Downloads {kind} in {langs}{as_format}, without the video. "
            "Change this under Settings, Post-processing."
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
            self.quick_download_format.addItem(label, value)
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

    def _start_quick_download(self):
        if (
            getattr(self, "_first_run", False)
            and not getattr(self, "_first_run_destination_confirmed", False)
        ):
            self._set_quick_download_status(
                "Confirm your download folder before adding a download.",
                "warning",
            )
            self.first_run_destination.setFocus(Qt.FocusReason.OtherFocusReason)
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

        # A format probe is the only honest size estimate yt-dlp gives us
        # before a run. Use it for one-link quick downloads; batches and
        # unprobed links retain the normal queue path rather than pretending
        # an unknown size is safe or unsafe.
        kind = self.quick_download_type.currentData()
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
                estimate = self._dependencies['estimate_download_bytes'](
                    getattr(self, "_format_probe_summary", {}),
                    audio_only=kind == "audio",
                    quality=self.quick_download_quality.currentData() or "best",
                )
                if estimate:
                    output_dir = self._quick_download_dir or (
                        self.config.get("AudioDownloadPath")
                        if kind == "audio" and self.config.get("AudioDownloadPath")
                        else self.config.get("DownloadPath")
                    )
                    space_failure = self._dependencies['check_download_disk_space'](
                        output_dir, estimate
                    )
                    if space_failure:
                        self._set_quick_download_status(
                            space_failure.get("error") or "Not enough free disk space.",
                            "error",
                        )
                        self._append_log(
                            f"Quick download refused before start: "
                            f"{space_failure.get('error', 'insufficient disk space')}"
                        )
                        return

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
            )
            if error:
                failures.append((url, error))
            else:
                queued.append(dl_id)

        if queued:
            if len(queued) == 1:
                message = f"Queued {queued[0]}" + (
                    " for an accurate ffmpeg clip." if section else "."
                )
            else:
                message = f"Queued {len(queued)} downloads."
            if self._quick_download_dir:
                message += f" Saving to {self._quick_download_dir}."
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
            self, "Save this download to", str(current))
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
                f"{tr('Save to')}: {self._quick_download_dir}")
        else:
            self.btn_quick_download_dest.setText(tr("Save to"))
            self.btn_quick_download_dest.setToolTip(
                tr("Send this download somewhere other than the default folder.")
            )
            self.btn_quick_download_dest.setAccessibleName(tr("Save to"))

    def _set_quick_download_status(self, message, state):
        self.quick_download_status.setText(message)
        self.quick_download_status.setProperty("state", state)
        self.quick_download_status.show()
        repolish(self.quick_download_status)

    def _build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 38, 24)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addLayout(self._make_page_header("History", ""), 1)
        self.btn_clear_history = self._make_tool_button("Clear history", "ghost")
        self.btn_clear_history.setToolTip(
            tr("Remove saved history entries. Downloaded files are not deleted.")
        )
        self.btn_clear_history.clicked.connect(self._clear_history)
        header.addWidget(self.btn_clear_history, 0, Qt.AlignmentFlag.AlignTop)
        self.btn_undo_clear_history = self._make_tool_button("Undo clear", "ghost")
        self.btn_undo_clear_history.setToolTip(
            tr("Restore the history entries cleared in this session.")
        )
        self.btn_undo_clear_history.clicked.connect(self._undo_clear_history)
        self.btn_undo_clear_history.hide()
        header.addWidget(self.btn_undo_clear_history, 0, Qt.AlignmentFlag.AlignTop)
        self.btn_export_history = self._make_tool_button("Export filtered", "secondary")
        self.btn_export_history.setToolTip(
            tr("Export every row matching the current filters as CSV.")
        )
        self.btn_export_history.clicked.connect(self._export_history)
        header.addWidget(self.btn_export_history, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.history_search = QLineEdit()
        self.history_search.setAccessibleName(tr("Search download history"))
        self.history_search.setPlaceholderText("Search title or filename")
        self.history_search.setClearButtonEnabled(True)
        filters.addWidget(self.history_search, 2)
        self.history_status = QComboBox()
        self.history_status.setAccessibleName(tr("History status"))
        self.history_status.addItem(tr("All statuses"), "")
        self.history_status.addItem(tr("Complete"), "complete")
        for status, label in (
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
            ("skipped", "Nothing downloaded"),
        ):
            self.history_status.addItem(tr(label), status)
        filters.addWidget(self.history_status)
        self.history_format = QComboBox()
        self.history_format.setAccessibleName(tr("History format"))
        self.history_format.addItem(tr("All formats"), "")
        for fmt in ("mp4", "mkv", "webm", "mp3", "m4a", "opus", "flac", "wav"):
            self.history_format.addItem(fmt.upper(), fmt)
        filters.addWidget(self.history_format)
        self.history_sort = QComboBox()
        self.history_sort.setAccessibleName(tr("History sort order"))
        self.history_sort.addItem(tr("Newest first"), "newest")
        self.history_sort.addItem(tr("Oldest first"), "oldest")
        filters.addWidget(self.history_sort)
        layout.addLayout(filters)

        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(make_label("Saved from", "fieldHint"))
        self.history_date_from = QLineEdit()
        self.history_date_from.setAccessibleName(tr("History start date"))
        self.history_date_from.setPlaceholderText("YYYY-MM-DD")
        self.history_date_from.setMaximumWidth(125)
        range_row.addWidget(self.history_date_from)
        range_row.addWidget(make_label("through", "fieldHint"))
        self.history_date_to = QLineEdit()
        self.history_date_to.setAccessibleName(tr("History end date"))
        self.history_date_to.setPlaceholderText("YYYY-MM-DD")
        self.history_date_to.setMaximumWidth(125)
        range_row.addWidget(self.history_date_to)
        range_row.addStretch()
        self.history_meta = make_label("0 of 0 retained", "toolbarMeta")
        range_row.addWidget(self.history_meta)
        self.btn_history_prev = self._make_tool_button("Previous", "ghost")
        self.btn_history_prev.clicked.connect(lambda: self._move_history_page(-1))
        range_row.addWidget(self.btn_history_prev)
        self.btn_history_next = self._make_tool_button("Next", "ghost")
        self.btn_history_next.clicked.connect(lambda: self._move_history_page(1))
        range_row.addWidget(self.btn_history_next)
        layout.addLayout(range_row)

        # Clear, Undo and Export used to report through _append_log, whose
        # widget lives on the Browser extension page — so a permissions error
        # here produced no visible response at all. Every other page has one
        # of these.
        self.history_page_status = make_label("", "fieldHint", word_wrap=True)
        self.history_page_status.setAccessibleName(tr("History status message"))
        self.history_page_status.hide()
        layout.addWidget(self.history_page_status)

        self._history_filter_timer = QTimer(self)
        self._history_filter_timer.setSingleShot(True)
        self._history_filter_timer.setInterval(250)
        self._history_filter_timer.timeout.connect(self._apply_history_filters)
        for signal in (
            self.history_search.textChanged,
            self.history_status.currentIndexChanged,
            self.history_format.currentIndexChanged,
            self.history_sort.currentIndexChanged,
            self.history_date_from.textChanged,
            self.history_date_to.textChanged,
        ):
            signal.connect(self._history_filters_changed)

        columns = QFrame()
        columns.setProperty("class", "listHeader")
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 8, 0, 10)
        columns_layout.setSpacing(12)
        columns_layout.addWidget(make_label("File", "columnLabel"), 4)
        for text in ("Format", "Quality", "Duration", "Saved"):
            label = make_label(text, "columnLabel")
            label.setFixedWidth(92)
            columns_layout.addWidget(label)
        columns_layout.addSpacing(54)
        layout.addWidget(columns)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.history_container = QVBoxLayout(content)
        self.history_container.setContentsMargins(0, 0, 0, 0)
        self.history_container.setSpacing(10)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.tabs.addTab(page, "History")

    def _subscription_manager(self):
        value = self._dependencies.get('subscription_manager')
        return value() if callable(value) else value

    def _build_subscriptions(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 38, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addLayout(self._make_page_header(
            "Subscriptions",
            "Watch YouTube channels or playlists on a schedule and queue only new uploads.",
        ), 1)
        self.btn_undo_subscription = self._make_tool_button("Undo remove", "ghost")
        self.btn_undo_subscription.setToolTip(
            tr("Restore the subscription removed in this session.")
        )
        self.btn_undo_subscription.clicked.connect(self._undo_subscription)
        self.btn_undo_subscription.hide()
        header.addWidget(self.btn_undo_subscription, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        add_card, add_layout = self._make_settings_group("New subscription")
        url_row = QHBoxLayout()
        self.subscription_url = QLineEdit()
        self.subscription_url.setAccessibleName(
            tr("Subscription channel or playlist URL")
        )
        self.subscription_url.setPlaceholderText("https://www.youtube.com/@channel or playlist URL")
        url_row.addWidget(self.subscription_url, 1)
        interval_label = make_label("Every", "fieldHint")
        url_row.addWidget(interval_label)
        self.subscription_interval = QSpinBox()
        self.subscription_interval.setRange(5, 10080)
        self.subscription_interval.setValue(60)
        self.subscription_interval.setSuffix(" min")
        self.subscription_interval.setAccessibleName(
            tr("Subscription scan interval in minutes")
        )
        url_row.addWidget(self.subscription_interval)
        self.btn_add_subscription = self._make_tool_button("Add subscription", "primary")
        self.btn_add_subscription.clicked.connect(self._add_subscription)
        url_row.addWidget(self.btn_add_subscription)
        add_layout.addLayout(url_row)
        self.subscription_status = make_label("Subscriptions are ready when the local companion is running.", "toolbarMeta", word_wrap=True)
        add_layout.addWidget(self.subscription_status)
        layout.addWidget(add_card)

        subscription_filters = QHBoxLayout()
        subscription_filters.setSpacing(8)
        self.subscription_search = QLineEdit()
        self.subscription_search.setAccessibleName(tr("Search subscriptions"))
        self.subscription_search.setPlaceholderText(tr("Search title, URL, or error"))
        self.subscription_search.setClearButtonEnabled(True)
        subscription_filters.addWidget(self.subscription_search, 2)
        self.subscription_status_filter = QComboBox()
        self.subscription_status_filter.setAccessibleName(tr("Subscription status"))
        for label, value in (
            ("All subscriptions", "all"),
            ("Active", "active"),
            ("Disabled", "disabled"),
            ("Needs attention", "needs-attention"),
        ):
            self.subscription_status_filter.addItem(tr(label), value)
        subscription_filters.addWidget(self.subscription_status_filter)
        self.subscription_filter_meta = make_label("", "toolbarMeta")
        subscription_filters.addWidget(self.subscription_filter_meta)
        layout.addLayout(subscription_filters)
        self._subscription_filter_timer = QTimer(self)
        self._subscription_filter_timer.setSingleShot(True)
        self._subscription_filter_timer.setInterval(250)
        self._subscription_filter_timer.timeout.connect(
            lambda: self._refresh_subscriptions(force=True)
        )
        self.subscription_search.textChanged.connect(
            self._subscription_filters_changed
        )
        self.subscription_status_filter.currentIndexChanged.connect(
            self._subscription_filters_changed
        )

        self.subscription_scroll = QScrollArea()
        self.subscription_scroll.setWidgetResizable(True)
        content = QWidget()
        self.subscription_container = QVBoxLayout(content)
        self.subscription_container.setContentsMargins(0, 0, 0, 0)
        self.subscription_container.setSpacing(10)
        self.subscription_scroll.setWidget(content)
        layout.addWidget(self.subscription_scroll, 1)
        self.tabs.addTab(page, "Subscriptions")
        self._refresh_subscriptions(force=True)

    def _refresh_subscriptions(self, force=False):
        manager = self._subscription_manager()
        if manager is None:
            records = []
            payload = {}
        else:
            try:
                payload = manager.snapshot()
                records = payload.get("subscriptions", []) if isinstance(payload, dict) else []
            except Exception as error:  # noqa: BLE001
                payload = {}
                records = []
                self.subscription_status.setText(f"Could not read subscriptions: {error}")
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
            {"records": records, "scanning": sorted(scanning)},
            sort_keys=True,
            default=str,
        )
        if not force and signature == self._subscriptions_signature:
            return
        self._subscriptions_signature = signature
        self._clear_layout(self.subscription_container)
        if manager is None:
            self.subscription_container.addWidget(make_empty_state(
                "Subscriptions unavailable",
                "Start the Astra Downloader companion to manage scheduled channel scans.",
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
            f"{len(records)} configured · {archive.get('complete', 0)} archived · "
            f"{archive.get('queued', 0)} queued"
        )
        if not records:
            self.subscription_container.addWidget(make_empty_state(
                "No scheduled subscriptions",
                "Add a YouTube channel or playlist above. New uploads will be queued on its interval.",
            ))
            self.subscription_container.addStretch()
            return
        if not visible_records:
            self.subscription_container.addWidget(make_empty_state(
                tr("No subscriptions match these filters"),
                tr("Try a different search or choose All subscriptions."),
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
                f"{tr('Enable subscription')} {record.get('title') or record.get('url')}"
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
                detail = (
                    f"Every {record.get('intervalMinutes', 60)} min · next scan {next_text}"
                )
            if record.get("lastError"):
                detail += f" · {record['lastError']}"
            copy_layout.addWidget(make_label(detail, "toolbarMeta", word_wrap=True))
            row_layout.addLayout(copy_layout, 1)
            row_target = str(record.get("title") or record.get("url") or "")
            scan = self._make_tool_button("Scan now", "ghost", row_target)
            scan.clicked.connect(lambda checked=False, sub_id=record.get("id"): self._scan_subscription(sub_id))
            row_layout.addWidget(scan, 0, Qt.AlignmentFlag.AlignTop)
            remove = self._make_tool_button("Remove", "ghost", row_target)
            remove.clicked.connect(lambda checked=False, sub_id=record.get("id"): self._remove_subscription(sub_id))
            row_layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
            self.subscription_container.addWidget(row)
        self.subscription_container.addStretch()

    def _subscription_filters_changed(self):
        if hasattr(self, "_subscription_filter_timer"):
            self._subscription_filter_timer.start()

    # ── Site sign-ins ────────────────────────────────────────────────────
    def _build_site_logins(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 38, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addLayout(self._make_page_header(
            "Sign-ins",
            tr("Store a signed-in session so private or members-only videos "
               "download. Cookies or stored credentials stay on this PC and "
               "are only ever sent to the site they belong to."),
        ), 1)
        self.btn_undo_site_login = self._make_tool_button("Undo remove", "ghost")
        self.btn_undo_site_login.setToolTip(
            tr("Restore the sign-in removed in this session.")
        )
        self.btn_undo_site_login.clicked.connect(self._undo_site_login)
        self.btn_undo_site_login.hide()
        header.addWidget(self.btn_undo_site_login, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        add_card, add_layout = self._make_settings_group(tr("Add a site sign-in"))
        site_row = QHBoxLayout()
        self.site_login_url = QLineEdit()
        self.site_login_url.setAccessibleName(tr("Site address for the sign-in"))
        self.site_login_url.setPlaceholderText(
            tr("Site address you signed in to — x.com, instagram.com, vimeo.com")
        )
        site_row.addWidget(self.site_login_url, 1)
        add_layout.addLayout(site_row)

        credentials_row = QHBoxLayout()
        credentials_row.setSpacing(8)
        self.site_login_username = QLineEdit()
        self.site_login_username.setAccessibleName(tr("Site sign-in username"))
        self.site_login_username.setPlaceholderText(tr("Username or email"))
        credentials_row.addWidget(self.site_login_username, 1)
        self.site_login_password = QLineEdit()
        self.site_login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.site_login_password.setAccessibleName(tr("Site sign-in password"))
        self.site_login_password.setPlaceholderText(tr("Password"))
        self.site_login_password.setClearButtonEnabled(True)
        credentials_row.addWidget(self.site_login_password, 1)
        self.btn_site_login_credentials = self._make_tool_button(
            "Store username/password", "primary"
        )
        self.btn_site_login_credentials.clicked.connect(
            self._store_site_login_credentials
        )
        credentials_row.addWidget(self.btn_site_login_credentials)
        add_layout.addLayout(credentials_row)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_row.addWidget(make_label(tr("Read from"), "fieldHint"))
        self.site_login_browser = QComboBox()
        self.site_login_browser.setAccessibleName(tr("Browser to read cookies from"))
        for browser in self._value('SITE_LOGIN_BROWSERS'):
            label = browser.title()
            warning = self._dependencies['describe_browser_cookie_readiness'](browser)
            if warning:
                label += f" — {tr('likely unreadable on Windows 127+') }"
            self.site_login_browser.addItem(label, browser)
        # Firefox is the one browser whose cookie store can still be read from
        # outside on Windows, so it is the default rather than whichever name
        # sorts first.
        firefox_index = self.site_login_browser.findData("firefox")
        if firefox_index >= 0:
            self.site_login_browser.setCurrentIndex(firefox_index)
        source_row.addWidget(self.site_login_browser)
        self.site_login_profile = QLineEdit()
        self.site_login_profile.setAccessibleName(tr("Browser profile name or path"))
        self.site_login_profile.setPlaceholderText(tr("Profile (optional)"))
        self.site_login_profile.setMaximumWidth(220)
        source_row.addWidget(self.site_login_profile)
        self.btn_site_login_browser = self._make_tool_button("Read from browser", "primary")
        self.btn_site_login_browser.clicked.connect(self._import_site_login_from_browser)
        source_row.addWidget(self.btn_site_login_browser)
        self.btn_site_login_file = self._make_tool_button("Import cookies.txt", "ghost")
        self.btn_site_login_file.clicked.connect(self._import_site_login_from_file)
        source_row.addWidget(self.btn_site_login_file)
        source_row.addStretch()
        add_layout.addLayout(source_row)

        add_layout.addWidget(make_label(
            tr("Chromium browsers such as Chrome, Edge, Brave, Opera, Vivaldi, "
               "and Chromium 127+ encrypt their cookie store, so reading them "
               "from outside the browser usually fails — export a cookies.txt "
               "file or use username/password instead. Firefox can normally be "
               "read directly."),
            "toolbarMeta",
            word_wrap=True,
        ))
        self.site_login_status = make_label("", "fieldHint", word_wrap=True)
        self.site_login_status.setAccessibleName(tr("Site sign-in status"))
        self.site_login_status.hide()
        add_layout.addWidget(self.site_login_status)
        layout.addWidget(add_card)

        site_login_filters = QHBoxLayout()
        site_login_filters.setSpacing(8)
        self.site_login_search = QLineEdit()
        self.site_login_search.setAccessibleName(tr("Search stored sign-ins"))
        self.site_login_search.setPlaceholderText(tr("Search site or source"))
        self.site_login_search.setClearButtonEnabled(True)
        site_login_filters.addWidget(self.site_login_search, 2)
        self.site_login_status_filter = QComboBox()
        self.site_login_status_filter.setAccessibleName(tr("Stored sign-in status"))
        for label, value in (
            ("All sign-ins", "all"),
            ("Stored and valid", "stored"),
            ("Expired", "expired"),
            ("Missing on disk", "missing"),
        ):
            self.site_login_status_filter.addItem(tr(label), value)
        site_login_filters.addWidget(self.site_login_status_filter)
        self.site_login_filter_meta = make_label("", "toolbarMeta")
        site_login_filters.addWidget(self.site_login_filter_meta)
        layout.addLayout(site_login_filters)
        self._site_login_filter_timer = QTimer(self)
        self._site_login_filter_timer.setSingleShot(True)
        self._site_login_filter_timer.setInterval(250)
        self._site_login_filter_timer.timeout.connect(
            lambda: self._refresh_site_logins(force=True)
        )
        self.site_login_search.textChanged.connect(self._site_login_filters_changed)
        self.site_login_status_filter.currentIndexChanged.connect(
            self._site_login_filters_changed
        )

        self.site_login_scroll = QScrollArea()
        self.site_login_scroll.setWidgetResizable(True)
        content = QWidget()
        self.site_login_container = QVBoxLayout(content)
        self.site_login_container.setContentsMargins(0, 0, 0, 0)
        self.site_login_container.setSpacing(10)
        self.site_login_scroll.setWidget(content)
        layout.addWidget(self.site_login_scroll, 1)
        self.tabs.addTab(page, "Sign-ins")
        self._refresh_site_logins(force=True)

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
        if store is not None:
            try:
                entries = store.entries()
            except Exception as error:  # noqa: BLE001
                self._show_site_login_status(
                    f"Could not read stored sign-ins: {error}", "error"
                )
        signature = json.dumps(entries, sort_keys=True, default=str)
        if not force and signature == getattr(self, "_site_logins_signature", None):
            return
        self._site_logins_signature = signature
        self._clear_layout(self.site_login_container)
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
                   "signed-in viewers. YouTube downloads use the browser "
                   "extension instead and need nothing here."),
            ))
            self.site_login_container.addStretch()
            return
        if not visible_entries:
            self.site_login_container.addWidget(make_empty_state(
                tr("No sign-ins match these filters"),
                tr("Try a different search or choose All sign-ins."),
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
                state = tr("Username/password — stored securely")
                if entry.get("expired") and count:
                    state += f" · {tr('cookie session expired')}"
            elif entry.get("expired"):
                state = tr("Expired — sign in again to refresh it")
            elif not entry.get("stored"):
                state = tr("Missing on disk — import it again")
            elif entry.get("earliestExpiry"):
                try:
                    expires = time.strftime(
                        "%Y-%m-%d", time.localtime(float(entry["earliestExpiry"]))
                    )
                except (TypeError, ValueError, OverflowError, OSError):
                    expires = tr("unknown")
                state = f"{tr('First cookie expires')} {expires}"
            else:
                state = tr("Session cookies — valid until the site signs you out")
            test_state = self._site_login_test_states.get(entry.get("site"))
            if test_state:
                state += f" · {test_state.get('message', '')}"
            if credentialed and count:
                auth_label = tr("cookies + username/password")
            elif credentialed:
                auth_label = tr("username/password")
            else:
                auth_label = (
                    tr("cookie") if count == 1 else tr("cookies")
                )
            copy_layout.addWidget(make_label(
                f"{count} {auth_label} · "
                f"{tr('from')} {entry.get('source', 'import')} · {state}",
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

    def _show_history_status(self, message, state="neutral"):
        """Report a History action on the History page, and in the log."""
        self.history_page_status.setText(message)
        self.history_page_status.setProperty("state", state)
        self.history_page_status.show()
        repolish(self.history_page_status)
        self._append_log(message)

    def _show_site_login_status(self, message, state="neutral"):
        self.site_login_status.setText(message)
        self.site_login_status.setProperty("state", state)
        self.site_login_status.show()
        repolish(self.site_login_status)

    def _apply_site_login_result(self, result, error):
        if error:
            self._show_site_login_status(error, "error")
            return False
        site = (result or {}).get("site", "")
        count = (result or {}).get("cookies", 0)
        skipped = (result or {}).get("skipped", 0)
        message = f"{tr('Signed in to')} {site} — {count} {tr('cookies stored')}."
        if skipped:
            message += f" {skipped} {tr('cookies for other sites were discarded.')}"
        self._show_site_login_status(message, "success")
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
            f"{tr('Signed in to')} {site} — {tr('username/password stored securely.')}",
            "success",
        )
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
            "Select the exported cookies.txt",
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
            self._show_site_login_status(f"Could not read that file: {error}", "error")
            return
        if size > limit:
            self._show_site_login_status(
                "That cookie file is too large to be a browser export.", "error"
            )
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self._show_site_login_status(f"Could not read that file: {error}", "error")
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
                f"{tr('Removed the stored sign-in for')} {site}.", "neutral"
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
                "message": f"{tr('Test failed')}: {error[:200]}",
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
            self.subscription_status.setText("Start the local companion before adding a subscription.")
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
            f"Added {record.get('title') or record.get('url')}. The first scan is scheduled now."
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
        getter = getattr(manager, "get_subscription", None)
        if callable(getter):
            record = getter(sub_id)
        if record is None:
            try:
                record = next(
                    (
                        item for item in manager.list_subscriptions()
                        if str(item.get("id")) == str(sub_id)
                    ),
                    None,
                )
            except Exception:
                record = None
        self._subscription_scan_pending.discard(str(sub_id))
        self._subscription_scan_seen.discard(str(sub_id))
        _removed, error = manager.remove_subscription(sub_id)
        if error:
            self.subscription_status.setText(error)
        else:
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
        self._subscription_undo = None
        self.btn_undo_subscription.hide()
        self.subscription_status.setText(tr("The subscription was restored."))
        self._refresh_subscriptions(force=True)

    def _build_settings(self):
        self._settings_group_specs = []
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 30, 24)
        layout.setSpacing(0)

        layout.addLayout(self._make_page_header("Settings", ""))
        layout.addSpacing(14)
        layout.addWidget(make_divider())

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 14, 0, 0)
        filter_row.addWidget(make_label("Find a setting", "fieldLabel"))
        self.settings_filter = QLineEdit()
        self.settings_filter.setAccessibleName(tr("Filter settings"))
        self.settings_filter.setPlaceholderText(
            tr("Search settings by name or group")
        )
        self.settings_filter.setClearButtonEnabled(True)
        self.settings_filter.textChanged.connect(self._filter_settings)
        filter_row.addWidget(self.settings_filter, 1)
        layout.addLayout(filter_row)
        self.settings_filter_empty = make_label(
            "No settings match this search.", "fieldHint"
        )
        self.settings_filter_empty.setVisible(False)
        layout.addWidget(self.settings_filter_empty)

        # Connection
        conn_card, conn_l = self._make_settings_group("Connection")
        port_row = QHBoxLayout()
        port_copy = QVBoxLayout()
        port_copy.setSpacing(2)
        port_copy.addWidget(make_label("Local API port", "fieldLabel"))
        port_copy.addWidget(make_label("Default 9751. Change only for custom clients.", "fieldHint", word_wrap=True))
        # The dashboard shows the port actually bound, which during a bind
        # conflict is a session-only fallback. Without this line the spinbox
        # silently disagreed with it.
        self.cfg_port_session_hint = make_label("", "fieldHint", word_wrap=True)
        self.cfg_port_session_hint.setVisible(False)
        port_copy.addWidget(self.cfg_port_session_hint)
        port_row.addLayout(port_copy, 1)
        self.cfg_port = QSpinBox()
        self.cfg_port.setAccessibleName(tr("Local API port"))
        self.cfg_port.setRange(1024, 65535)
        # Read the PERSISTED port: a session fallback must never be echoed back
        # into the spinbox, or the next save would write it to disk.
        _persisted_get = getattr(self.config, 'get_persisted', self.config.get)
        self.cfg_port.setValue(self._dependencies['clamp_int'](_persisted_get("ServerPort", self._value('SERVER_PORT')), self._value('SERVER_PORT'), 1024, 65535))
        self.cfg_port.setFixedWidth(100)
        port_row.addWidget(self.cfg_port)
        conn_l.addLayout(port_row)
        conn_l.addWidget(make_divider())
        token_copy = QVBoxLayout()
        token_copy.setSpacing(2)
        token_copy.addWidget(make_label("Private token", "fieldLabel"))
        token_copy.addWidget(make_label("Authorizes extension requests on this computer.", "fieldHint", word_wrap=True))
        conn_l.addLayout(token_copy)
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self.cfg_token = QLineEdit(self.config.get("ServerToken", ""))
        self.cfg_token.setAccessibleName(tr("Private API token"))
        self.cfg_token.setReadOnly(True)
        self.cfg_token.setEchoMode(QLineEdit.EchoMode.Password)
        token_row.addWidget(self.cfg_token, 1)
        self.btn_token_reveal = self._make_tool_button("Reveal")
        self.btn_token_reveal.setAccessibleName(tr("Reveal private token"))
        self.btn_token_reveal.clicked.connect(self._toggle_token_visible)
        token_row.addWidget(self.btn_token_reveal)
        btn_token_copy = self._make_tool_button("Copy")
        btn_token_copy.clicked.connect(self._copy_token)
        token_row.addWidget(btn_token_copy)
        btn_token_reset = self._make_tool_button("Regenerate", "danger")
        btn_token_reset.clicked.connect(self._regenerate_token)
        token_row.addWidget(btn_token_reset)
        conn_l.addLayout(token_row)
        conn_l.addWidget(make_divider())

        force_ip_row = QHBoxLayout()
        force_ip_copy = QVBoxLayout()
        force_ip_copy.setSpacing(2)
        force_ip_copy.addWidget(make_label("Force IP version", "fieldLabel"))
        force_ip_copy.addWidget(make_label(
            "Use IPv4 or IPv6 for every request. Off uses the system route.",
            "fieldHint", word_wrap=True,
        ))
        force_ip_row.addLayout(force_ip_copy, 1)
        self.cfg_force_ip_version = QComboBox()
        self.cfg_force_ip_version.setAccessibleName(tr("Force IP version"))
        self.cfg_force_ip_version.addItem(tr("Off"), "")
        self.cfg_force_ip_version.addItem(tr("IPv4"), "ipv4")
        self.cfg_force_ip_version.addItem(tr("IPv6"), "ipv6")
        force_ip = self._dependencies['normalize_force_ip_version'](
            self.config.get("ForceIPVersion", "")
        )
        restored_force_ip = self.cfg_force_ip_version.findData(force_ip)
        self.cfg_force_ip_version.setCurrentIndex(
            restored_force_ip if restored_force_ip >= 0 else 0
        )
        force_ip_row.addWidget(self.cfg_force_ip_version)
        conn_l.addLayout(force_ip_row)

        source_row = QHBoxLayout()
        source_copy = QVBoxLayout()
        source_copy.setSpacing(2)
        source_copy.addWidget(make_label("Source address", "fieldLabel"))
        source_copy.addWidget(make_label(
            "Bind requests to a local IPv4 or IPv6 address. Blank uses the system route.",
            "fieldHint", word_wrap=True,
        ))
        source_row.addLayout(source_copy, 1)
        self.cfg_source_address = QLineEdit(self.config.get("SourceAddress", ""))
        self.cfg_source_address.setAccessibleName(tr("Source address"))
        self.cfg_source_address.setPlaceholderText("192.0.2.10")
        self.cfg_source_address.setMinimumWidth(260)
        source_row.addWidget(self.cfg_source_address)
        conn_l.addLayout(source_row)

        xff_row = QHBoxLayout()
        xff_copy = QVBoxLayout()
        xff_copy.setSpacing(2)
        xff_copy.addWidget(make_label("Geo X-Forwarded-For", "fieldLabel"))
        xff_copy.addWidget(make_label(
            "Country code (US) or CIDR block for geo verification. Blank leaves it off.",
            "fieldHint", word_wrap=True,
        ))
        xff_row.addLayout(xff_copy, 1)
        self.cfg_xff = QLineEdit(self.config.get("Xff", ""))
        self.cfg_xff.setAccessibleName(tr("Geo X-Forwarded-For"))
        self.cfg_xff.setPlaceholderText("US or 203.0.113.0/24")
        self.cfg_xff.setMinimumWidth(260)
        xff_row.addWidget(self.cfg_xff)
        conn_l.addLayout(xff_row)

        geo_proxy_row = QHBoxLayout()
        geo_proxy_copy = QVBoxLayout()
        geo_proxy_copy.setSpacing(2)
        geo_proxy_copy.addWidget(make_label("Geo verification proxy", "fieldLabel"))
        geo_proxy_copy.addWidget(make_label(
            "Optional HTTP(S) or SOCKS proxy used only for region checks.",
            "fieldHint", word_wrap=True,
        ))
        geo_proxy_row.addLayout(geo_proxy_copy, 1)
        self.cfg_geo_verification_proxy = QLineEdit(
            self.config.get("GeoVerificationProxy", "")
        )
        self.cfg_geo_verification_proxy.setAccessibleName(tr("Geo verification proxy"))
        self.cfg_geo_verification_proxy.setPlaceholderText("https://proxy.example:8080")
        self.cfg_geo_verification_proxy.setMinimumWidth(260)
        geo_proxy_row.addWidget(self.cfg_geo_verification_proxy)
        conn_l.addLayout(geo_proxy_row)
        layout.addWidget(conn_card)

        # Site profiles. This is intentionally a bounded JSON editor rather
        # than a secret-bearing account form: names and defaults are portable,
        # while cookies and credentials stay in the per-site Sign-ins store.
        profiles_card, profiles_l = self._make_settings_group("Site profiles")
        profiles_l.addWidget(make_label("Named site profiles", "fieldLabel"))
        profiles_l.addWidget(make_label(
            "One JSON object per profile. Match a domain automatically, or "
            "choose a profile for one download in the paste box. Supported "
            "defaults include format, quality, proxy, impersonation and "
            "request pacing; do not put cookies or passwords here.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_site_profiles = QTextEdit()
        self.cfg_site_profiles.setAccessibleName(tr("Named site profiles"))
        self.cfg_site_profiles.setAcceptRichText(False)
        self.cfg_site_profiles.setMinimumHeight(170)
        self.cfg_site_profiles.setPlainText(json.dumps(
            self.config.get("SiteProfiles", []), indent=2, ensure_ascii=False
        ))
        profiles_l.addWidget(self.cfg_site_profiles)
        profiles_l.addWidget(make_label(
            'Example: [{"Name":"YouTube archive","Domain":"youtube.com",'
            '"VideoFormat":"mp4","Quality":"1080"}]',
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(profiles_card)

        # Storage
        paths_card, paths_l = self._make_settings_group("Storage")
        paths_l.addWidget(make_label("Video download folder", "fieldLabel"))
        paths_l.addWidget(make_label("Default destination for video downloads.", "fieldHint", word_wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.cfg_dl_path = QLineEdit(self.config.get("DownloadPath", ""))
        self.cfg_dl_path.setAccessibleName(tr("Video download folder"))
        self.cfg_dl_path.setPlaceholderText(
            str(Path(default_download_path()) / "YouTube")
        )
        row.addWidget(self.cfg_dl_path, 1)
        btn = self._make_tool_button("Browse")
        btn.clicked.connect(lambda: self._browse(self.cfg_dl_path))
        row.addWidget(btn)
        paths_l.addLayout(row)
        paths_l.addWidget(make_divider())
        paths_l.addWidget(make_label("Audio download folder", "fieldLabel"))
        paths_l.addWidget(make_label("Leave blank to use the video folder.", "fieldHint", word_wrap=True))
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.cfg_audio_path = QLineEdit(self.config.get("AudioDownloadPath", ""))
        self.cfg_audio_path.setAccessibleName(tr("Audio download folder"))
        self.cfg_audio_path.setPlaceholderText("Same as video folder")
        row2.addWidget(self.cfg_audio_path, 1)
        btn2 = self._make_tool_button("Browse")
        btn2.clicked.connect(lambda: self._browse(self.cfg_audio_path))
        row2.addWidget(btn2)
        paths_l.addLayout(row2)
        paths_l.addWidget(make_divider())
        paths_l.addWidget(make_label("Filename template", "fieldLabel"))
        paths_l.addWidget(make_label(
            "Optional yt-dlp output template, relative to the folder above "
            "(e.g. %(uploader)s/%(title)s.%(ext)s). Must keep %(ext)s. "
            "Title and channel fields are length-bounded on save so long "
            "titles cannot overrun the maximum path length. "
            "Blank uses the default.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_outtmpl = QLineEdit(self.config.get("OutputTemplate", ""))
        self.cfg_outtmpl.setAccessibleName(tr("Filename template"))
        self.cfg_outtmpl.setPlaceholderText("%(title)s.%(ext)s")
        paths_l.addWidget(self.cfg_outtmpl)
        self.outtmpl_preview = make_label("", "fieldHint", word_wrap=True)
        self.outtmpl_preview.setAccessibleName(tr("Filename template preview"))
        paths_l.addWidget(self.outtmpl_preview)
        self.cfg_windows_filenames = QCheckBox(tr("Use Windows-safe filenames"))
        self.cfg_windows_filenames.setToolTip(tr(
            "Ask yt-dlp to replace characters and names that Windows cannot store."
        ))
        self.cfg_windows_filenames.setChecked(
            self.config.get("WindowsFilenames", True)
        )
        paths_l.addWidget(self.cfg_windows_filenames)
        self.cfg_outtmpl.textChanged.connect(self._update_output_template_preview)
        self.cfg_dl_path.textChanged.connect(self._update_output_template_preview)
        self._update_output_template_preview()
        layout.addWidget(paths_card)

        # Post-processing
        pp_card, pp_l = self._make_settings_group("Post-processing")
        self.cfg_metadata = QCheckBox(tr("Embed metadata"))
        self.cfg_metadata.setChecked(self.config.get("EmbedMetadata", True))
        self.cfg_thumbnail = QCheckBox(tr("Embed thumbnail"))
        self.cfg_thumbnail.setChecked(self.config.get("EmbedThumbnail", True))
        self.cfg_chapters = QCheckBox(tr("Embed chapters"))
        self.cfg_chapters.setChecked(self.config.get("EmbedChapters", True))
        self.cfg_subs = QCheckBox(tr("Download subtitles"))
        self.cfg_subs.setToolTip(tr(
            "Fetch subtitle tracks and embed them in the file. The Subtitles "
            "download type fetches them without the video."
        ))
        self.cfg_subs.setChecked(self.config.get("EmbedSubs", False))
        self.cfg_generate_subtitles = QCheckBox(
            tr("Generate local subtitles when no track exists")
        )
        self.cfg_generate_subtitles.setToolTip(tr(
            "After a video download, use the locally provisioned Whisper model "
            "to write an SRT sidecar only when yt-dlp found no subtitle track."
        ))
        self.cfg_generate_subtitles.setChecked(
            self.config.get("GenerateSubtitles", False)
        )
        self.generate_subtitles_hint = make_label(
            tr(
                "Uses the bundled multilingual Whisper model and the first "
                "language in Subtitle languages. Setup downloads the model "
                "when this option is enabled."
            ),
            "fieldHint", word_wrap=True,
        )
        self.cfg_keep_intermediates = QCheckBox(tr("Keep intermediate files"))
        self.cfg_keep_intermediates.setToolTip(tr(
            "Put .part, .f### and .ytdl files beside the output and keep them "
            "for diagnosis. Off by default: they use a private temporary "
            "folder and are removed after a successful download."
        ))
        self.cfg_keep_intermediates.setChecked(
            self.config.get("KeepIntermediateFiles", False))
        self.cfg_write_info = QCheckBox(tr("Write info JSON sidecar"))
        self.cfg_write_info.setChecked(self.config.get("WriteInfoJson", False))
        self.cfg_write_description = QCheckBox(tr("Write description sidecar"))
        self.cfg_write_description.setChecked(
            self.config.get("WriteDescription", False)
        )
        self.cfg_write_thumbnail = QCheckBox(tr("Write thumbnail sidecar"))
        self.cfg_write_thumbnail.setChecked(
            self.config.get("WriteThumbnail", False)
        )
        self.cfg_split_chapters = QCheckBox(tr("Split chapters into files"))
        self.cfg_split_chapters.setChecked(
            self.config.get("SplitChapters", False)
        )
        self.cfg_live_from_start = QCheckBox(tr("Start live streams from the beginning"))
        self.cfg_live_from_start.setChecked(
            self.config.get("LiveFromStart", False)
        )
        self.cfg_wait_for_video = QSpinBox()
        self.cfg_wait_for_video.setAccessibleName(tr("Wait for live video"))
        self.cfg_wait_for_video.setRange(0, 3600)
        self.cfg_wait_for_video.setSuffix(tr(" seconds"))
        self.cfg_wait_for_video.setValue(
            self._dependencies["clamp_int"](
                self.config.get("WaitForVideoSeconds", 0), 0, 0, 3600
            )
        )
        # cfg_keep_intermediates is added after the subtitle rows below: the
        # track, format and language controls belong directly under the
        # checkbox that turns them on, not separated from it.
        for w in [self.cfg_metadata, self.cfg_thumbnail, self.cfg_chapters,
                  self.cfg_subs, self.cfg_generate_subtitles]:
            pp_l.addWidget(w)
        pp_l.addWidget(self.generate_subtitles_hint)
        # Which of the two catalogues to ask for. Measured against the
        # installed yt-dlp: sending both flags never yields two files for one
        # language — the creator's track wins — so "both" is a preference,
        # not a duplicate, and the new capability is asking for one kind only.
        track_row = QHBoxLayout()
        track_row.setSpacing(8)
        track_row.addSpacing(28)
        track_row.addWidget(make_label("Tracks", "fieldHint"))
        self.cfg_subtitle_mode = QComboBox()
        self.cfg_subtitle_mode.setAccessibleName(tr("Subtitle tracks"))
        for label, value in (
            ("Creator, else auto-generated", "prefer-manual"),
            ("Creator only", "manual"),
            ("Auto-generated only", "auto"),
        ):
            self.cfg_subtitle_mode.addItem(tr(label), value)
        self.cfg_subtitle_mode.setCurrentIndex(max(0, self.cfg_subtitle_mode.findData(
            self._dependencies['normalize_subtitle_mode'](
                self.config.get("SubtitleMode")
            )
        )))
        track_row.addWidget(self.cfg_subtitle_mode)
        track_row.addSpacing(12)
        track_row.addWidget(make_label("Save as", "fieldHint"))
        self.cfg_subtitle_format = QComboBox()
        self.cfg_subtitle_format.setAccessibleName(tr("Subtitle format"))
        for label, value in (
            ("Same as source", ""), ("SRT", "srt"), ("WebVTT", "vtt"),
            ("ASS", "ass"), ("LRC", "lrc"),
        ):
            self.cfg_subtitle_format.addItem(tr(label), value)
        self.cfg_subtitle_format.setCurrentIndex(max(0, self.cfg_subtitle_format.findData(
            self._dependencies['normalize_subtitle_format'](
                self.config.get("SubtitleFormat")
            )
        )))
        track_row.addWidget(self.cfg_subtitle_format)
        track_row.addStretch()
        pp_l.addLayout(track_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addSpacing(28)
        sub_row.addWidget(make_label("Subtitle languages", "fieldHint"))
        self.cfg_sublangs = QLineEdit(self.config.get("SubLangs", "en"))
        self.cfg_sublangs.setAccessibleName(tr("Subtitle languages"))
        self.cfg_sublangs.setPlaceholderText("en,es")
        self.cfg_sublangs.setFixedWidth(140)
        self.cfg_sublangs.textEdited.connect(self._sync_sublang_checkboxes)
        sub_row.addWidget(self.cfg_sublangs)
        sub_row.addStretch()
        pp_l.addLayout(sub_row)
        # The field above still accepts any code yt-dlp knows; these are the
        # common ones, so picking two languages does not mean knowing that
        # Simplified Chinese is spelled zh-Hans. Three per row, because a
        # single long row of labels overflows at 900x620 with a large font.
        self._sublang_boxes = []
        lang_row = None
        for index, (label, code) in enumerate(SUBTITLE_LANGUAGE_CHOICES):
            if index % 3 == 0:
                lang_row = QHBoxLayout()
                lang_row.setSpacing(8)
                lang_row.addSpacing(28)
                pp_l.addLayout(lang_row)
            box = QCheckBox(tr(label))
            box.setAccessibleName(f"{tr('Subtitle language')} {tr(label)}")
            box.toggled.connect(self._sublang_box_toggled)
            box._sublang_code = code
            self._sublang_boxes.append(box)
            lang_row.addWidget(box, 1)
        if lang_row is not None:
            for _ in range(-len(SUBTITLE_LANGUAGE_CHOICES) % 3):
                lang_row.addStretch(1)
        self._sync_sublang_checkboxes(self.cfg_sublangs.text())
        pp_l.addWidget(self.cfg_keep_intermediates)
        pp_l.addWidget(make_divider())
        pp_l.addWidget(make_label("Archive output", "fieldLabel"))
        pp_l.addWidget(make_label(
            "Optional sidecars, chapter splitting and live-event controls. "
            "These do not change the existing embed options.",
            "fieldHint", word_wrap=True,
        ))
        for w in (
            self.cfg_write_info, self.cfg_write_description,
            self.cfg_write_thumbnail, self.cfg_split_chapters,
            self.cfg_live_from_start,
        ):
            pp_l.addWidget(w)
        wait_row = QHBoxLayout()
        wait_row.setSpacing(8)
        wait_row.addSpacing(28)
        wait_row.addWidget(make_label("Wait for live video", "fieldHint"))
        wait_row.addWidget(self.cfg_wait_for_video)
        wait_row.addWidget(make_label(
            "0 disables waiting; use this when a scheduled live event has not started.",
            "fieldHint", word_wrap=True,
        ), 1)
        pp_l.addLayout(wait_row)
        pp_l.addWidget(make_divider())
        self.cfg_sponsorblock = QCheckBox(tr("Use SponsorBlock segments"))
        self.cfg_sponsorblock.setChecked(self.config.get("SponsorBlock", False))
        pp_l.addWidget(self.cfg_sponsorblock)
        sb_row = QHBoxLayout()
        sb_row.setSpacing(8)
        sb_row.addSpacing(28)
        sb_row.addWidget(make_label("Action", "fieldHint"))
        self.cfg_sb_action = QComboBox()
        self.cfg_sb_action.setAccessibleName(tr("SponsorBlock action"))
        self.cfg_sb_action.addItem(tr("Remove segments"), "remove")
        self.cfg_sb_action.addItem(tr("Mark segments"), "mark")
        current_action = self.config.get("SponsorBlockAction", "remove")
        self.cfg_sb_action.setCurrentIndex(1 if current_action == "mark" else 0)
        self.cfg_sb_action.setEnabled(self.cfg_sponsorblock.isChecked())
        self.cfg_sponsorblock.toggled.connect(self.cfg_sb_action.setEnabled)
        sb_row.addWidget(self.cfg_sb_action)
        sb_row.addStretch()
        pp_l.addLayout(sb_row)

        # Without a per-category choice the app sent the literal `all`, so
        # asking it to skip sponsors also removed intros, outros and self-promo.
        self.cfg_sb_categories = {}
        selected = set(
            self._dependencies['normalize_sponsorblock_categories'](
                self.config.get("SponsorBlockCategories", "")
            ).split(",")
        )
        category_labels = {
            "sponsor": "Sponsor", "intro": "Intro", "outro": "Outro",
            "selfpromo": "Self-promotion", "preview": "Recap or preview",
            "filler": "Filler", "interaction": "Interaction reminder",
            "music_offtopic": "Non-music section",
            "poi_highlight": "Highlight", "chapter": "Chapter",
        }
        category_grid = QVBoxLayout()
        category_grid.setSpacing(0)
        names = list(self._value('SPONSORBLOCK_CATEGORIES'))
        for start in range(0, len(names), 3):
            line = QHBoxLayout()
            line.setSpacing(10)
            line.addSpacing(28)
            for name in names[start:start + 3]:
                box = QCheckBox(tr(category_labels.get(name, name)))
                box.setChecked(name in selected)
                box.setEnabled(self.cfg_sponsorblock.isChecked())
                self.cfg_sponsorblock.toggled.connect(box.setEnabled)
                self.cfg_sb_categories[name] = box
                line.addWidget(box, 1)
            line.addStretch()
            category_grid.addLayout(line)
        pp_l.addLayout(category_grid)
        pp_l.addWidget(make_label(
            "With nothing ticked, every category is acted on.",
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(pp_card)

        # Format preferences. The container above is a hard constraint —
        # MP4 forces H.264 + AAC so an editor imports the result without
        # transcoding — and these order whatever that leaves open. Resolution
        # stays the primary axis; the quality picker owns it.
        fmt_card, fmt_l = self._make_settings_group("Format preferences")
        fmt_l.addWidget(make_label(
            "Preferences, not requirements: a link that has none of these "
            "still downloads. The MP4 container overrides them, because an "
            "editor-safe file is the point of choosing MP4.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_video_codec = self._add_format_preference(
            fmt_l, "Preferred video codec", "Preferred video codec",
            (
                (tr("No preference"), "auto"),
                ("H.264 (most compatible)", "h264"),
                ("VP9", "vp9"),
                ("AV1 (smallest)", "av1"),
            ),
            self.config.get("VideoCodecPreference", "auto"),
        )
        self.cfg_audio_codec = self._add_format_preference(
            fmt_l, "Preferred audio codec", "Preferred audio codec",
            (
                (tr("No preference"), "auto"),
                ("AAC (most compatible)", "aac"),
                ("Opus", "opus"),
            ),
            self.config.get("AudioCodecPreference", "auto"),
        )
        self.cfg_frame_rate = self._add_format_preference(
            fmt_l, "Preferred frame rate", "Preferred frame rate",
            (
                (tr("No preference"), 0),
                ("30 fps", 30),
                ("60 fps", 60),
            ),
            self._dependencies['clamp_int'](
                self.config.get("PreferredFrameRate", 0), 0, 0, 120),
        )
        layout.addWidget(fmt_card)

        # Playlist bounds. A pasted playlist otherwise queues everything it
        # contains; these apply only to a run that walks one.
        pl_card, pl_l = self._make_settings_group("Playlist limits")
        pl_l.addWidget(make_label(
            "These apply when you paste a playlist or channel. A single "
            "video is never filtered by them.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_playlist_max = self._add_settings_number(
            pl_l, "Maximum items",
            "Stop after this many items from one playlist. 0 takes all of them.",
            "Maximum playlist items", 0, 1000,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMaxItems", 0), 0, 0, 1000),
        )
        date_row = QHBoxLayout()
        date_copy = QVBoxLayout()
        date_copy.setSpacing(2)
        date_copy.addWidget(make_label("Uploaded after", "fieldLabel"))
        date_copy.addWidget(make_label(
            "A date as YYYYMMDD, or a relative one such as today-30days. "
            "Empty takes any date.", "fieldHint", word_wrap=True,
        ))
        date_row.addLayout(date_copy, 1)
        self.cfg_playlist_dateafter = QLineEdit(
            str(self.config.get("PlaylistDateAfter", "") or ""))
        self.cfg_playlist_dateafter.setAccessibleName(tr("Playlist uploaded after"))
        self.cfg_playlist_dateafter.setPlaceholderText("today-30days")
        self.cfg_playlist_dateafter.setFixedWidth(160)
        date_row.addWidget(self.cfg_playlist_dateafter)
        pl_l.addLayout(date_row)
        self.cfg_playlist_min_duration = self._add_settings_number(
            pl_l, "Shortest item (seconds)",
            "Skip items shorter than this, which is how a channel's shorts "
            "are left behind. 0 takes any length.",
            "Shortest playlist item in seconds", 0, 86400,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMinDurationSeconds", 0), 0, 0, 86400),
        )
        self.cfg_playlist_max_duration = self._add_settings_number(
            pl_l, "Longest item (seconds)",
            "Skip items longer than this, which is how multi-hour streams "
            "are left behind. 0 takes any length.",
            "Longest playlist item in seconds", 0, 86400,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMaxDurationSeconds", 0), 0, 0, 86400),
        )
        layout.addWidget(pl_card)

        # Performance
        perf_card, perf_l = self._make_settings_group("Performance")
        frag_row = QHBoxLayout()
        frag_copy = QVBoxLayout()
        frag_copy.setSpacing(2)
        frag_copy.addWidget(make_label("Concurrent fragments", "fieldLabel"))
        frag_copy.addWidget(make_label("More can improve fast connections.", "fieldHint", word_wrap=True))
        frag_row.addLayout(frag_copy, 1)
        self.cfg_fragments = QSpinBox()
        self.cfg_fragments.setAccessibleName(tr("Concurrent fragments"))
        self.cfg_fragments.setRange(1, 32)
        self.cfg_fragments.setValue(self._dependencies['clamp_int'](self.config.get("ConcurrentFragments", 4), 4, 1, 32))
        self.cfg_fragments.setFixedWidth(86)
        frag_row.addWidget(self.cfg_fragments)
        perf_l.addLayout(frag_row)
        perf_l.addWidget(make_divider())

        conc_row = QHBoxLayout()
        conc_copy = QVBoxLayout()
        conc_copy.setSpacing(2)
        conc_copy.addWidget(make_label("Simultaneous downloads", "fieldLabel"))
        conc_copy.addWidget(make_label("How many downloads run at once.", "fieldHint", word_wrap=True))
        conc_row.addLayout(conc_copy, 1)
        self.cfg_maxconcurrent = QSpinBox()
        self.cfg_maxconcurrent.setAccessibleName(tr("Simultaneous downloads"))
        self.cfg_maxconcurrent.setRange(1, 10)
        self.cfg_maxconcurrent.setValue(self._dependencies['clamp_int'](self.config.get("MaxConcurrentDownloads", 3), 3, 1, 10))
        self.cfg_maxconcurrent.setFixedWidth(86)
        conc_row.addWidget(self.cfg_maxconcurrent)
        perf_l.addLayout(conc_row)
        perf_l.addWidget(make_divider())

        retries_row = QHBoxLayout()
        retries_copy = QVBoxLayout()
        retries_copy.setSpacing(2)
        retries_copy.addWidget(make_label("Download retries", "fieldLabel"))
        retries_copy.addWidget(make_label("Retry attempts on transient network errors.", "fieldHint", word_wrap=True))
        retries_row.addLayout(retries_copy, 1)
        self.cfg_retries = QSpinBox()
        self.cfg_retries.setAccessibleName(tr("Download retries"))
        self.cfg_retries.setRange(0, 50)
        self.cfg_retries.setValue(self._dependencies['clamp_int'](self.config.get("DownloadRetries", 10), 10, 0, 50))
        self.cfg_retries.setFixedWidth(86)
        retries_row.addWidget(self.cfg_retries)
        perf_l.addLayout(retries_row)
        perf_l.addWidget(make_divider())
        rate_row = QHBoxLayout()
        rate_copy = QVBoxLayout()
        rate_copy.setSpacing(2)
        rate_copy.addWidget(make_label("Rate limit", "fieldLabel"))
        rate_copy.addWidget(make_label("Optional, such as 500K or 2M.", "fieldHint", word_wrap=True))
        rate_row.addLayout(rate_copy, 1)
        self.cfg_ratelimit = QLineEdit(self.config.get("RateLimit", ""))
        self.cfg_ratelimit.setAccessibleName(tr("Rate limit"))
        self.cfg_ratelimit.setPlaceholderText("No limit")
        self.cfg_ratelimit.setFixedWidth(120)
        rate_row.addWidget(self.cfg_ratelimit)
        perf_l.addLayout(rate_row)
        perf_l.addWidget(make_divider())
        throttle_row = QHBoxLayout()
        throttle_copy = QVBoxLayout()
        throttle_copy.setSpacing(2)
        throttle_copy.addWidget(make_label("Throttle floor", "fieldLabel"))
        throttle_copy.addWidget(make_label(
            "Below this rate the server is assumed to be throttling and the "
            "video is re-extracted. Empty disables it.",
            "fieldHint", word_wrap=True,
        ))
        throttle_row.addLayout(throttle_copy, 1)
        self.cfg_throttled = QLineEdit(self.config.get("ThrottledRate", ""))
        self.cfg_throttled.setAccessibleName(tr("Throttle floor"))
        self.cfg_throttled.setPlaceholderText("Off")
        self.cfg_throttled.setFixedWidth(120)
        throttle_row.addWidget(self.cfg_throttled)
        perf_l.addLayout(throttle_row)
        perf_l.addWidget(make_divider())
        socket_row = QHBoxLayout()
        socket_copy = QVBoxLayout()
        socket_copy.setSpacing(2)
        socket_copy.addWidget(make_label("Socket timeout", "fieldLabel"))
        socket_copy.addWidget(make_label(
            "Seconds before a stalled connection is abandoned. 0 uses yt-dlp's "
            "own default.", "fieldHint", word_wrap=True,
        ))
        socket_row.addLayout(socket_copy, 1)
        self.cfg_socket_timeout = QSpinBox()
        self.cfg_socket_timeout.setAccessibleName(tr("Socket timeout in seconds"))
        self.cfg_socket_timeout.setRange(0, 300)
        self.cfg_socket_timeout.setValue(self._dependencies['clamp_int'](
            self.config.get("SocketTimeoutSeconds", 0), 0, 0, 300))
        self.cfg_socket_timeout.setFixedWidth(86)
        socket_row.addWidget(self.cfg_socket_timeout)
        perf_l.addLayout(socket_row)
        perf_l.addWidget(make_divider())
        extractor_row = QHBoxLayout()
        extractor_copy = QVBoxLayout()
        extractor_copy.setSpacing(2)
        extractor_copy.addWidget(make_label("Extractor retries", "fieldLabel"))
        extractor_copy.addWidget(make_label(
            "Retries while reading the page, before any transfer starts. "
            "0 uses yt-dlp's own default.", "fieldHint", word_wrap=True,
        ))
        extractor_row.addLayout(extractor_copy, 1)
        self.cfg_extractor_retries = QSpinBox()
        self.cfg_extractor_retries.setAccessibleName(tr("Extractor retries"))
        self.cfg_extractor_retries.setRange(0, 20)
        self.cfg_extractor_retries.setValue(self._dependencies['clamp_int'](
            self.config.get("ExtractorRetries", 0), 0, 0, 20))
        self.cfg_extractor_retries.setFixedWidth(86)
        extractor_row.addWidget(self.cfg_extractor_retries)
        perf_l.addLayout(extractor_row)
        perf_l.addWidget(make_divider())
        self.cfg_verify_formats = QCheckBox(tr("Verify formats before downloading"))
        self.cfg_verify_formats.setToolTip(tr(
            "Check that a chosen format can actually be downloaded before "
            "committing to it. Costs an extra request per candidate format."
        ))
        self.cfg_verify_formats.setChecked(self.config.get("VerifyFormats", False))
        perf_l.addWidget(self.cfg_verify_formats)
        perf_l.addWidget(make_divider())
        pace_row = QHBoxLayout()
        pace_copy = QVBoxLayout()
        pace_copy.setSpacing(2)
        pace_copy.addWidget(make_label("Pause between downloads", "fieldLabel"))
        pace_copy.addWidget(make_label(
            "Seconds to wait before each download. A bandwidth cap does not "
            "prevent an HTTP 429; spacing the requests does. 0 disables it.",
            "fieldHint", word_wrap=True,
        ))
        pace_row.addLayout(pace_copy, 1)
        self.cfg_sleep_interval = QSpinBox()
        self.cfg_sleep_interval.setAccessibleName(tr("Pause between downloads in seconds"))
        self.cfg_sleep_interval.setRange(0, 600)
        self.cfg_sleep_interval.setValue(self._dependencies['clamp_int'](
            self.config.get("SleepIntervalSeconds", 0), 0, 0, 600))
        self.cfg_sleep_interval.setFixedWidth(86)
        pace_row.addWidget(self.cfg_sleep_interval)
        perf_l.addLayout(pace_row)
        pace_max_row = QHBoxLayout()
        pace_max_copy = QVBoxLayout()
        pace_max_copy.setSpacing(2)
        pace_max_copy.addWidget(make_label("Longest pause", "fieldLabel"))
        pace_max_copy.addWidget(make_label(
            "Upper bound when the pause is randomised. Ignored below the "
            "pause above.", "fieldHint", word_wrap=True,
        ))
        pace_max_row.addLayout(pace_max_copy, 1)
        self.cfg_sleep_max = QSpinBox()
        self.cfg_sleep_max.setAccessibleName(tr("Longest pause in seconds"))
        self.cfg_sleep_max.setRange(0, 600)
        self.cfg_sleep_max.setValue(self._dependencies['clamp_int'](
            self.config.get("MaxSleepIntervalSeconds", 0), 0, 0, 600))
        self.cfg_sleep_max.setFixedWidth(86)
        pace_max_row.addWidget(self.cfg_sleep_max)
        perf_l.addLayout(pace_max_row)
        pace_jitter_row = QHBoxLayout()
        pace_jitter_copy = QVBoxLayout()
        pace_jitter_copy.setSpacing(2)
        pace_jitter_copy.addWidget(make_label("Pacing jitter", "fieldLabel"))
        pace_jitter_copy.addWidget(make_label(
            "Randomise host wait times and yt-dlp pacing by ± this percentage. "
            "0 keeps fixed timing.", "fieldHint", word_wrap=True,
        ))
        pace_jitter_row.addLayout(pace_jitter_copy, 1)
        self.cfg_pacing_jitter = QSpinBox()
        self.cfg_pacing_jitter.setAccessibleName(tr("Pacing jitter percentage"))
        self.cfg_pacing_jitter.setRange(0, 100)
        self.cfg_pacing_jitter.setSuffix("%")
        self.cfg_pacing_jitter.setSpecialValueText(tr("Off"))
        self.cfg_pacing_jitter.setValue(self._dependencies['clamp_int'](
            self.config.get("PacingJitterPercent", 0), 0, 0, 100))
        self.cfg_pacing_jitter.setFixedWidth(86)
        pace_jitter_row.addWidget(self.cfg_pacing_jitter)
        perf_l.addLayout(pace_jitter_row)
        pace_req_row = QHBoxLayout()
        pace_req_copy = QVBoxLayout()
        pace_req_copy.setSpacing(2)
        pace_req_copy.addWidget(make_label("Pause between requests", "fieldLabel"))
        pace_req_copy.addWidget(make_label(
            "Seconds between the data requests inside one download.",
            "fieldHint", word_wrap=True,
        ))
        pace_req_row.addLayout(pace_req_copy, 1)
        self.cfg_sleep_requests = QSpinBox()
        self.cfg_sleep_requests.setAccessibleName(tr("Pause between requests in seconds"))
        self.cfg_sleep_requests.setRange(0, 60)
        self.cfg_sleep_requests.setValue(self._dependencies['clamp_int'](
            self.config.get("SleepRequestsSeconds", 0), 0, 0, 60))
        self.cfg_sleep_requests.setFixedWidth(86)
        pace_req_row.addWidget(self.cfg_sleep_requests)
        perf_l.addLayout(pace_req_row)
        perf_l.addWidget(make_divider())
        # MaxFileSizeMB blocks downloads outright — a run that trips it exits
        # cleanly having written nothing and reports `skipped`, whose message
        # tells the user to change this. It needs a control to change.
        maxsize_row = QHBoxLayout()
        maxsize_copy = QVBoxLayout()
        maxsize_copy.setSpacing(2)
        maxsize_copy.addWidget(make_label("Max file size", "fieldLabel"))
        maxsize_copy.addWidget(make_label(
            "Skip anything larger. 0 means no limit.", "fieldHint", word_wrap=True
        ))
        maxsize_row.addLayout(maxsize_copy, 1)
        self.cfg_maxsize = QSpinBox()
        self.cfg_maxsize.setAccessibleName(tr("Max file size in megabytes"))
        self.cfg_maxsize.setRange(0, 102400)
        self.cfg_maxsize.setSuffix(" MB")
        self.cfg_maxsize.setSpecialValueText(tr("No limit"))
        self.cfg_maxsize.setValue(self._dependencies['clamp_int'](
            self.config.get("MaxFileSizeMB", 0), 0, 0, 102400
        ))
        self.cfg_maxsize.setFixedWidth(120)
        maxsize_row.addWidget(self.cfg_maxsize)
        perf_l.addLayout(maxsize_row)
        proxy_row = QHBoxLayout()
        proxy_copy = QVBoxLayout()
        proxy_copy.setSpacing(2)
        proxy_copy.addWidget(make_label("Proxy", "fieldLabel"))
        proxy_copy.addWidget(make_label("Optional HTTP(S) or SOCKS proxy.", "fieldHint", word_wrap=True))
        proxy_row.addLayout(proxy_copy, 1)
        self.cfg_proxy = QLineEdit(self.config.get("Proxy", ""))
        self.cfg_proxy.setAccessibleName(tr("Proxy"))
        self.cfg_proxy.setPlaceholderText("https://proxy.example:8080")
        self.cfg_proxy.setMinimumWidth(260)
        proxy_row.addWidget(self.cfg_proxy)
        perf_l.addLayout(proxy_row)
        # Impersonation. Built from what the installed binary reports, because
        # yt-dlp aborts the download outright on an unknown target.
        impersonate_row = QHBoxLayout()
        impersonate_copy = QVBoxLayout()
        impersonate_copy.setSpacing(2)
        impersonate_copy.addWidget(make_label("Imitate a browser", "fieldLabel"))
        impersonate_copy.addWidget(make_label(
            "Sends a real browser's TLS fingerprint. The usual fix for a site "
            "that returns 403, though it can itself trigger rate limiting.",
            "fieldHint", word_wrap=True,
        ))
        impersonate_row.addLayout(impersonate_copy, 1)
        self.cfg_impersonate = QComboBox()
        self.cfg_impersonate.setAccessibleName(tr("Imitate a browser"))
        self.cfg_impersonate.addItem(tr("Off"), "")
        configured = self._dependencies['normalize_impersonate_target'](
            self.config.get("ImpersonateTarget", ""))
        self._configured_impersonate_target = configured
        self.cfg_impersonate.addItem(
            tr("Checking installed yt-dlp…"),
            "__impersonate_pending__",
        )
        if configured:
            self.cfg_impersonate.addItem(configured, configured)
        restored = self.cfg_impersonate.findData(configured)
        self.cfg_impersonate.setCurrentIndex(restored if restored >= 0 else 0)
        impersonate_row.addWidget(self.cfg_impersonate)
        perf_l.addLayout(impersonate_row)
        perf_l.addWidget(make_divider())
        runtime_row = QHBoxLayout()
        runtime_copy = QVBoxLayout()
        runtime_copy.setSpacing(2)
        runtime_copy.addWidget(make_label("JavaScript runtime", "fieldLabel"))
        runtime_copy.addWidget(make_label(
            "Auto prefers Deno, then Node 22+, then the QuickJS runtime the "
            "app downloads for itself (2 MB).",
            "fieldHint", word_wrap=True,
        ))
        runtime_row.addLayout(runtime_copy, 1)
        self.cfg_js_runtime = QComboBox()
        self.cfg_js_runtime.setAccessibleName(tr("JavaScript runtime"))
        self.cfg_js_runtime.addItem(tr("Auto"), "auto")
        self.cfg_js_runtime.addItem("Deno", "deno")
        self.cfg_js_runtime.addItem("Node 22+", "node")
        self.cfg_js_runtime.addItem("QuickJS", "quickjs")
        selected_runtime = self.config.get("JavaScriptRuntime", "auto")
        self.cfg_js_runtime.setCurrentIndex(max(0, self.cfg_js_runtime.findData(selected_runtime)))
        runtime_row.addWidget(self.cfg_js_runtime)
        perf_l.addLayout(runtime_row)
        perf_l.addWidget(make_divider())
        channel_row = QHBoxLayout()
        channel_copy = QVBoxLayout()
        channel_copy.setSpacing(2)
        channel_copy.addWidget(make_label("yt-dlp update channel", "fieldLabel"))
        channel_copy.addWidget(make_label(
            "Nightly ships same-day YouTube fixes; stable lags by weeks.",
            "fieldHint", word_wrap=True,
        ))
        channel_row.addLayout(channel_copy, 1)
        self.cfg_ytdlp_channel = QComboBox()
        self.cfg_ytdlp_channel.setAccessibleName(tr("yt-dlp update channel"))
        self.cfg_ytdlp_channel.addItem(tr("Nightly (recommended)"), "nightly")
        self.cfg_ytdlp_channel.addItem(tr("Stable"), "stable")
        selected_channel = self.config.get("YtDlpUpdateChannel", "nightly")
        self.cfg_ytdlp_channel.setCurrentIndex(max(0, self.cfg_ytdlp_channel.findData(selected_channel)))
        channel_row.addWidget(self.cfg_ytdlp_channel)
        perf_l.addLayout(channel_row)
        layout.addWidget(perf_card)

        # Language
        language_card, language_l = self._make_settings_group("Language")
        language_row = QHBoxLayout()
        language_row.addWidget(make_label("Language", "fieldLabel"))
        language_row.addStretch()
        self.cfg_language = QComboBox()
        self.cfg_language.setAccessibleName(tr("Companion language"))
        for label, value in (
            ("System default", "system"),
            ("العربية", "ar"),
            ("Deutsch", "de"),
            ("English", "en"),
            ("Español", "es"),
            ("Français", "fr"),
            ("Italiano", "it"),
            ("日本語", "ja"),
            ("한국어", "ko"),
            ("Português (Brasil)", "pt_BR"),
            ("Русский", "ru"),
            ("简体中文", "zh_CN"),
        ):
            self.cfg_language.addItem(label, value)
        selected_language = self.config.get("Language", "system")
        self.cfg_language.setCurrentIndex(
            max(0, self.cfg_language.findData(selected_language))
        )
        self.cfg_language.setToolTip(
            tr("Language changes apply the next time Astra Downloader starts.")
        )
        language_row.addWidget(self.cfg_language)
        language_l.addLayout(language_row)
        language_l.addWidget(make_label(
            "Language changes apply after restarting Astra Downloader.",
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(language_card)

        # Behavior
        beh_card, beh_l = self._make_settings_group("Tray behavior")
        self.cfg_autoupdate = QCheckBox(tr("Keep yt-dlp up to date automatically"))
        self.cfg_autoupdate.setChecked(self.config.get("AutoUpdateYtDlp", True))
        # The real cadence: throttled to once per 12 hours, checked when the
        # server starts and again whenever the download queue goes idle (the
        # race-free moment to swap the binary).
        self.cfg_autoupdate.setToolTip(tr(
            "Checks at most once every 12 hours - when the server starts and "
            "when the download queue goes idle."
        ))
        self.cfg_closetotray = QCheckBox(tr("Close to the system tray"))
        self.cfg_closetotray.setChecked(self.config.get("CloseToTray", True))
        self.cfg_startmin = QCheckBox(tr("Start minimized to the tray"))
        self.cfg_startmin.setChecked(self.config.get("StartMinimized", False))
        self.cfg_notify = QCheckBox(tr("Notify when a download finishes (while minimized)"))
        self.cfg_notify.setChecked(self.config.get("NotifyOnComplete", True))
        self.cfg_clipboard = QCheckBox(tr("Stage copied video links for review"))
        self.cfg_clipboard.setChecked(self.config.get("ClipboardLinkGrabber", False))
        self.cfg_clipboard.setToolTip(
            tr(
                "Watch clipboard changes for video links from any supported site. "
                "Matching links fill the Quick download field but are never "
                "downloaded until you confirm."
            )
        )
        self.cfg_clipboard.setAccessibleDescription(
            tr(
                "Off by default. Clipboard content that does not look like a video "
                "link is ignored, and a matching link is staged without starting a "
                "download."
            )
        )
        for w in [
            self.cfg_autoupdate, self.cfg_closetotray, self.cfg_startmin,
            self.cfg_notify, self.cfg_clipboard,
        ]:
            beh_l.addWidget(w)
        layout.addWidget(beh_card)

        # Tools — v1.2.0 downloader-maintenance actions
        tools_card, tools_l = self._make_settings_group("Maintenance")
        tools_l.addWidget(make_label("Installed tools", "fieldLabel"))
        self.tools_status = make_label("Checking installed tools…", "fieldHint", word_wrap=True)
        self.tools_status.setAccessibleName(tr("Installed tools status"))
        tools_l.addWidget(self.tools_status)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        self.btn_check_updates = self._make_tool_button(
            "Check for yt-dlp updates",
        )
        self.btn_check_updates.setToolTip(
            tr("Check for a yt-dlp update. Active downloads must finish first.")
        )
        self.btn_check_updates.clicked.connect(self._force_ytdlp_update)
        tools_row.addWidget(self.btn_check_updates)
        btn_reinstall_ffmpeg = self._make_tool_button(
            "Reinstall ffmpeg", "danger",
        )
        # _reinstall_ffmpeg stages and verifies a fresh copy first; nothing is
        # deleted unless the replacement verifies.
        btn_reinstall_ffmpeg.setToolTip(tr(
            "Download a fresh ffmpeg and verify its checksum. The installed copy "
            "stays in place until the replacement verifies."
        ))
        btn_reinstall_ffmpeg.clicked.connect(self._reinstall_ffmpeg)
        tools_row.addWidget(btn_reinstall_ffmpeg)
        tools_row.addStretch()
        tools_l.addLayout(tools_row)
        transfer_card, transfer_l = self._make_settings_group("Import and export")
        transfer_l.addWidget(make_label(
            "Move this install to another machine, or recover from a config "
            "you cannot open. The bundle carries settings and subscriptions. "
            "Stored sign-ins are listed by site but never exported — "
            "cookies stay on this machine.",
            "fieldHint", word_wrap=True,
        ))
        bundle_row = QHBoxLayout()
        bundle_row.setSpacing(8)
        self.btn_export_settings = self._make_tool_button("Export settings")
        self.btn_export_settings.setToolTip(tr(
            "Write settings and subscriptions to a JSON bundle."
        ))
        self.btn_export_settings.clicked.connect(self._export_settings_bundle)
        bundle_row.addWidget(self.btn_export_settings)
        self.btn_import_settings = self._make_tool_button("Import settings")
        self.btn_import_settings.setToolTip(tr(
            "Read a bundle written by Export settings and apply it."
        ))
        self.btn_import_settings.clicked.connect(self._import_settings_bundle)
        bundle_row.addWidget(self.btn_import_settings)
        self.btn_undo_settings_import = self._make_tool_button(
            "Undo import", "ghost"
        )
        self.btn_undo_settings_import.setToolTip(tr(
            "Restore settings and subscriptions changed by the last import."
        ))
        self.btn_undo_settings_import.clicked.connect(self._undo_settings_import)
        self.btn_undo_settings_import.hide()
        bundle_row.addWidget(self.btn_undo_settings_import)
        bundle_row.addStretch()
        transfer_l.addLayout(bundle_row)
        layout.addWidget(tools_card)
        layout.addWidget(transfer_card)

        save_row = QHBoxLayout()
        save_row.setContentsMargins(166, 14, 0, 0)
        self.settings_status = make_label("", "fieldHint")
        self.settings_status.setAccessibleName(tr("Settings status"))
        save_row.addWidget(self.settings_status, 1)
        btn_save = self._make_tool_button("Save changes", "primary")
        btn_save.clicked.connect(self._save_settings)
        self.btn_save = btn_save
        save_row.addWidget(btn_save)
        self.btn_restore_defaults = self._make_tool_button(
            "Restore defaults", "ghost"
        )
        self.btn_restore_defaults.setToolTip(tr(
            "Restore the editable settings to their shipped defaults."
        ))
        self.btn_restore_defaults.clicked.connect(self._restore_default_settings)
        save_row.addWidget(self.btn_restore_defaults)
        layout.addLayout(save_row)
        layout.addStretch()

        for signal in (
            self.cfg_port.valueChanged,
            self.cfg_token.textChanged,
            self.cfg_dl_path.textChanged,
            self.cfg_audio_path.textChanged,
            self.cfg_outtmpl.textChanged,
            self.cfg_metadata.toggled,
            self.cfg_thumbnail.toggled,
            self.cfg_chapters.toggled,
            self.cfg_subs.toggled,
            self.cfg_generate_subtitles.toggled,
            self.cfg_sublangs.textChanged,
            self.cfg_subtitle_mode.currentIndexChanged,
            self.cfg_subtitle_format.currentIndexChanged,
            self.cfg_sponsorblock.toggled,
            self.cfg_sb_action.currentIndexChanged,
            self.cfg_fragments.valueChanged,
            self.cfg_maxconcurrent.valueChanged,
            self.cfg_retries.valueChanged,
            self.cfg_maxsize.valueChanged,
            self.cfg_ratelimit.textChanged,
            self.cfg_throttled.textChanged,
            self.cfg_socket_timeout.valueChanged,
            self.cfg_extractor_retries.valueChanged,
            self.cfg_verify_formats.toggled,
            self.cfg_video_codec.currentIndexChanged,
            self.cfg_audio_codec.currentIndexChanged,
            self.cfg_frame_rate.currentIndexChanged,
            self.cfg_playlist_max.valueChanged,
            self.cfg_playlist_dateafter.textChanged,
            self.cfg_playlist_min_duration.valueChanged,
            self.cfg_playlist_max_duration.valueChanged,
            self.cfg_impersonate.currentIndexChanged,
            self.cfg_sleep_interval.valueChanged,
            self.cfg_sleep_max.valueChanged,
            self.cfg_pacing_jitter.valueChanged,
            self.cfg_sleep_requests.valueChanged,
            self.cfg_proxy.textChanged,
            self.cfg_force_ip_version.currentIndexChanged,
            self.cfg_source_address.textChanged,
            self.cfg_xff.textChanged,
            self.cfg_geo_verification_proxy.textChanged,
            self.cfg_js_runtime.currentIndexChanged,
            self.cfg_ytdlp_channel.currentIndexChanged,
            self.cfg_language.currentIndexChanged,
            self.cfg_autoupdate.toggled,
            self.cfg_closetotray.toggled,
            self.cfg_startmin.toggled,
            self.cfg_notify.toggled,
        self.cfg_clipboard.toggled,
        ):
            signal.connect(self._mark_settings_dirty)
        self._filter_settings("")

        self.tabs.addTab(scroll, "Settings")

    # ── Navigation ──
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
            " Your server token was regenerated, so the browser extension "
            "needs pairing again."
            if name == 'config.json' else ""
        )
        self.quarantine_notice.setText(
            f"{name} could not be read and was set aside as "
            f"{Path(entry['backup']).name}.{extra} Restore puts the original "
            "back and reloads it."
        )
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
                f"{Path(entry['path']).name} could not be restored. Its backup "
                f"is at {entry['backup']}."
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
                f"Destination confirmed: {path}. Setup can continue in the background."
            )
            self.first_run_status.setProperty("state", "success")
        else:
            self.first_run_status.setText(
                "Confirm a folder before your first download."
            )
            self.first_run_status.setProperty("state", "warning")
        repolish(self.first_run_status)

    def _confirm_first_run_destination(self):
        if not self._first_run:
            return False
        normalize = self._dependencies.get("normalize_output_dir")
        if not callable(normalize):
            self.first_run_status.setText(
                "The download folder validator is unavailable. Check the log and retry."
            )
            self.first_run_status.setProperty("state", "error")
            repolish(self.first_run_status)
            return False
        normalized, error = normalize(
            self.first_run_destination.text().strip(),
            self._value("DEFAULT_CONFIG")["DownloadPath"],
        )
        if error:
            self.first_run_status.setText(error)
            self.first_run_status.setProperty("state", "error")
            repolish(self.first_run_status)
            self.first_run_destination.setFocus(Qt.FocusReason.OtherFocusReason)
            return False
        update = getattr(self.config, "update", None)
        if not callable(update) or not update({
            "DownloadPath": normalized,
            "FirstRunComplete": True,
        }):
            self.first_run_status.setText(
                "Could not save the download folder. Check disk permissions and retry."
            )
            self.first_run_status.setProperty("state", "error")
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
            self.btn_startstop.setText(tr("Starting server…"))
            self.btn_startstop.setIcon(make_line_icon("Starting server"))
            self.btn_startstop.setProperty("class", "secondary")
            self.btn_startstop.setEnabled(False)
            self.tray_startstop.setText(tr("Starting server…"))
            self.tray_startstop.setEnabled(False)
            self.tray.setToolTip(f"{self._value('APP_NAME')} - {tr('Starting')}")
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
            self.btn_startstop.setText(tr("Stop server"))
            self.btn_startstop.setIcon(make_line_icon("Stop server"))
            self.btn_startstop.setProperty("class", "secondary")
            self.btn_startstop.setEnabled(True)
            self.tray_startstop.setText(tr("Stop server"))
            self.tray_startstop.setEnabled(True)
            self.tray.setToolTip(f"{self._value('APP_NAME')} - {tr('Running')}")
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
            self.btn_startstop.setText(tr("Start server"))
            self.btn_startstop.setIcon(make_line_icon("Start server"))
            self.btn_startstop.setProperty("class", "primary")
            self.btn_startstop.setEnabled(True)
            self.tray_startstop.setText(tr("Start server"))
            self.tray_startstop.setEnabled(True)
            self.tray.setToolTip(f"{self._value('APP_NAME')} - {tr('Stopped')}")
            self._set_readiness("server", "Stopped", "neutral")
        repolish(self.btn_startstop)
        repolish(self.server_badge)
        repolish(self.status_dot)
        repolish(self.status_label)

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
        if dl.error_code == "rate-limited":
            seconds = self._download_host_backoff_seconds(dl)
            if seconds:
                recovery_text = (
                    f"{recovery_text}\n"
                    + tr("This host is paused — retry in {duration}.").format(
                        duration=format_duration(seconds)
                    )
                )
        if dl.error_action:
            recovery_text = f"{recovery_text}\nNext: {tr(dl.error_action)}"
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
            meta_parts.append(f"{dl.progress:.1f}%")
        if dl.speed:
            meta_parts.append(dl.speed)
        if dl.eta:
            meta_parts.append(f"ETA {dl.eta}")
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
            else "Preparing download"
        )
        state_label = refs["state"]
        translated_status = tr(human_status(dl.status))
        state_label.setText(f"\u25cf  {translated_status}")
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
        """Raise a one-shot tray notification when a download finishes while
        the window is hidden (tray) or minimized to the taskbar — the states
        where the user can't see the queue. Completions seen while the window
        is visible are marked as already-notified so they never fire a stale
        toast later."""
        present = {d.id for d in downloads}
        # Prune ids that left the active queue so the set can't grow unbounded.
        self._seen_complete &= present
        # `skipped` finishes the same way a completion does — the queue slot is
        # released and the user is done waiting — so it notifies too, with the
        # reason as the body. Without this a minimized companion said nothing
        # at all about a download that produced no file.
        newly_complete = [d for d in downloads
                          if d.status in ('complete', 'skipped')
                          and d.id not in self._seen_complete]
        if not newly_complete:
            return
        notify = (self.config.get("NotifyOnComplete", True)
                  and (self.isHidden() or self.isMinimized()))
        for d in newly_complete:
            self._seen_complete.add(d.id)
            if notify:
                # What a click on this toast will act on. Windows gives no
                # per-message identity, so the most recent one wins.
                self._last_notified_file = getattr(d, 'filename', '') or ''
                title = (getattr(d, 'title', '') or '').strip() or 'Your download is finished.'
                skipped = d.status == 'skipped'
                if skipped:
                    heading = "Nothing downloaded"
                    body = (getattr(d, 'error', '') or '').strip() or title
                else:
                    heading = "Download complete"
                    body = title
                try:
                    self.tray.showMessage(
                        heading, body,
                        QSystemTrayIcon.MessageIcon.Warning if skipped
                        else QSystemTrayIcon.MessageIcon.Information,
                        4000,
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
            f"{capacity['total']} / {capacity['totalLimit']} jobs"
        )
        self.btn_queue_pause.setText(
            "Resume queue" if capacity['intakePaused'] else "Pause intake"
        )
        self.btn_queue_pause.setIcon(make_line_icon(
            "Resume queue" if capacity['intakePaused'] else "Pause intake"
        ))
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
        ("cfg_outtmpl", "OutputTemplate", "text"),
        ("cfg_windows_filenames", "WindowsFilenames", "check"),
        ("cfg_sublangs", "SubLangs", "text"),
        ("cfg_ratelimit", "RateLimit", "text"),
        ("cfg_throttled", "ThrottledRate", "text"),
        ("cfg_proxy", "Proxy", "text"),
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
        ("cfg_impersonate", "ImpersonateTarget", "combo"),
        ("cfg_force_ip_version", "ForceIPVersion", "combo"),
        ("cfg_subtitle_mode", "SubtitleMode", "combo"),
        ("cfg_subtitle_format", "SubtitleFormat", "combo"),
        ("cfg_language", "Language", "combo"),
    )

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
        current = {
            key: self.config.get(key, defaults.get(key))
            for key in values
        }
        changed = [key for key in values if current.get(key) != values[key]]
        if not changed:
            self._show_settings_status(
                tr("Settings already use their defaults."), "neutral"
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
            self._show_settings_status(
                tr("Could not restore defaults. Nothing changed; check disk permissions and retry."),
                "danger",
            )
            return False

        self._reload_settings_form()
        self._dependencies["reset_deno_runtime_cache"]()
        self._start_readiness_probe()
        new_port = self._dependencies["clamp_int"](
            values.get("ServerPort"), self._value("SERVER_PORT"), 1024, 65535,
        )
        port_changed = (
            new_port != old_port or new_port != old_effective_port
        )
        restarted_server = bool(port_changed and self.server_running)
        if restarted_server:
            self._stop_server()
            self._start_server()
        else:
            self._sync_connection_ui()

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
        self._show_settings_status(summary, "success")
        self._append_log(
            "Restored Settings defaults: " + ", ".join(changed)
        )
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
            self, "Export Settings", str(suggested), "JSON files (*.json)"
        )
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8", newline="") as output:
                json.dump(bundle, output, indent=2, ensure_ascii=False)
        except OSError as error:
            self._show_settings_status(
                f"Could not write the bundle: {error}", "danger")
            return False
        summary = (
            f"Exported {len(bundle['settings'])} settings and "
            f"{len(bundle['subscriptions'])} subscriptions."
        )
        if bundle["siteLoginSites"]:
            # Say it plainly rather than letting the user discover it on the
            # other machine: this file will not sign them back in.
            summary += (
                f" {len(bundle['siteLoginSites'])} stored sign-ins are listed "
                "by site only — add them again after importing."
            )
        self._show_settings_status(summary, "success")
        self._append_log(f"Settings bundle written to {path}")
        return True

    def _import_settings_bundle(self):
        """Apply a bundle, then say what it actually changed."""
        path, _selected = QFileDialog.getOpenFileName(
            self, "Import Settings",
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
                f"Could not read that bundle: {error}", "danger")
            return False
        bundle, error = self._dependencies['read_settings_bundle'](payload)
        if error:
            self._show_settings_status(error, "danger")
            return False
        changes = self._dependencies['describe_bundle_changes'](
            self.config, bundle)
        # Capture the incoming keys before the write. This is the same
        # session-scoped, one-step model as history undo, and it deliberately
        # excludes secrets because the bundle boundary already excludes them.
        previous_settings = {
            key: self.config.get(
                key, self._value('DEFAULT_CONFIG').get(key)
            )
            for key in bundle["settings"]
        }
        if not self.config.update(bundle["settings"]):
            self._show_settings_status(
                "Could not save the imported settings. Check disk space and "
                "permissions, then retry.",
                "danger",
            )
            return False
        manager = self._subscription_manager()
        added, skipped = 0, 0
        added_subscription_ids = []
        for record in bundle["subscriptions"]:
            if manager is None:
                break
            created, add_error = manager.add_subscription(
                record["url"],
                interval_minutes=record["intervalMinutes"],
                enabled=record["enabled"],
                title=record["title"],
            )
            if add_error:
                # A subscription already present is the ordinary case when
                # re-importing onto a machine that has some of them.
                skipped += 1
            else:
                added += 1
                if isinstance(created, dict) and created.get("id"):
                    added_subscription_ids.append(str(created["id"]))
        self._settings_import_undo = {
            "settings": previous_settings,
            "subscriptionIds": added_subscription_ids,
        }
        self.btn_undo_settings_import.show()
        parts = [f"Imported {len(changes['settings'])} changed settings"]
        if added or skipped:
            parts.append(f"{added} subscriptions added, {skipped} already present")
        if changes["siteLoginSites"]:
            parts.append(
                "sign-ins still needed for "
                + ", ".join(changes["siteLoginSites"][:5])
            )
        excluded = changes.get("excludedSettings") or []
        if excluded:
            parts.append(
                "not carried: " + ", ".join(excluded)
            )
        self._show_settings_status(". ".join(parts) + ".", "success")
        self._append_log(
            f"Imported settings bundle from {path}: "
            f"{', '.join(changes['settings']) or 'no setting changes'}"
        )
        # The form still shows the pre-import values until it is rebuilt.
        self._reload_settings_form()
        return True

    def _undo_settings_import(self):
        snapshot = self._settings_import_undo
        if not snapshot:
            self.btn_undo_settings_import.hide()
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
        restored = self.config.update(snapshot.get("settings", {}))
        snapshot["subscriptionIds"] = remaining
        if not restored:
            self._show_settings_status(
                "Could not restore the imported settings. The Undo snapshot is "
                "still available; check disk space and permissions, then retry.",
                "error",
            )
            self.btn_undo_settings_import.show()
            return
        if remaining:
            self._show_settings_status(
                tr("Settings were restored, but some imported subscriptions remain."),
                "warning",
            )
            self.btn_undo_settings_import.show()
        else:
            self._settings_import_undo = None
            self.btn_undo_settings_import.hide()
            self._show_settings_status(tr("Settings import undone."), "success")
        self._reload_settings_form()
        self._refresh_subscriptions(force=True)

    def _export_history(self):
        result = self._history_query(offset=0, limit=500)
        rows = result["history"]
        if not rows:
            self._show_history_status(
                "No filtered history rows are available to export.", "warning")
            return
        default_path = Path(self.config.get("DownloadPath", str(Path.home())))
        suggested = default_path / "astra-download-history.csv"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Download History",
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
                f"Could not export download history: {error}", "error")
            return
        self._show_history_status(
            f"Exported {len(rows)} filtered history row(s) to {path}", "success")

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
        rows = result["history"]
        start = result["offset"] + 1 if rows else 0
        end = result["offset"] + len(rows)
        self.history_meta.setText(
            f"{start}–{end} of {filtered_total} filtered · {result['total']} retained"
            if rows else
            f"0 of {filtered_total} filtered · {result['total']} retained"
        )
        self.btn_history_prev.setEnabled(result["offset"] > 0)
        self.btn_history_next.setEnabled(result["hasMore"])
        self.btn_export_history.setEnabled(filtered_total > 0)
        if not data:
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
            if h.get("error"):
                file_copy.addWidget(
                    make_label(str(h["error"]), "errorCallout", word_wrap=True)
                )
            card_l.addLayout(file_copy, 4)
            values = (
                str(h.get("format", "")).upper() if h.get("format") else "\u2014",
                h.get("quality") or "\u2014",
                format_duration(h.get("duration", 0)) or "\u2014",
                h.get("date") or "\u2014",
            )
            for value in values:
                label = make_label(str(value), "tableValue")
                label.setFixedWidth(92)
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
        if not self.history_mgr.clear():
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
        self._cleared_history_snapshot = []
        self.btn_undo_clear_history.hide()
        self._refresh_history()
        self._show_history_status(
            f"Restored {restored} download history entr{'y' if restored == 1 else 'ies'}.",
            "success",
        )

    def _retry_download(self, dl):
        ok, err = self.dl_manager.retry(dl.id)
        if not ok:
            # These controls live on the Download page, so their result has to
            # appear there. The log panel is on the Browser extension page.
            self._set_quick_download_status(err or "Retry was refused.", "error")
            self._append_log(f"Retry failed: {err}")
            return
        label = dl.title if dl.title != 'Unknown' else dl.url
        self._set_quick_download_status(f"Retry queued: {label}", "success")
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
        """Reveal whatever the last completion toast was about."""
        target = getattr(self, '_last_notified_file', '')
        self._show_from_tray()
        if target:
            self._show_download_location(target)
        return bool(target)

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

    def _copy_download_error(self, error):
        if not error:
            return False
        QApplication.clipboard().setText(str(error))
        self._set_quick_download_status("Error copied.", "success")
        return True

    def _download_card_menu(self, download, position_widget):
        """Right-click actions for one terminal download.

        Everything here is already reachable some other way; the point is
        that it is reachable *from the thing it acts on* rather than from a
        button strip that cannot afford four more buttons.
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
        menu.addSeparator()
        if self._is_retryable(download):
            retry = menu.addAction(tr("Retry"))
            retry.triggered.connect(lambda: self._retry_download(download))
        url = getattr(download, 'url', '') or ''
        copy_link = menu.addAction(tr("Copy link"))
        copy_link.setEnabled(bool(url))
        copy_link.triggered.connect(lambda: self._copy_download_url(url))
        error = getattr(download, 'error', '') or ''
        copy_error = menu.addAction(tr("Copy error"))
        copy_error.setEnabled(bool(error))
        copy_error.triggered.connect(lambda: self._copy_download_error(error))
        again = menu.addAction(tr("Download again"))
        again.setEnabled(bool(url))
        again.triggered.connect(lambda: self._redownload(download))
        return menu

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
        self.settings_status.setText(message)
        color = GUI_ACCESSIBILITY_COLORS.get(
            tone, GUI_ACCESSIBILITY_COLORS["neutral"]
        )
        self.settings_status.setStyleSheet(f"color: {color}; font-size: 12px;")
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
        self.btn_save.setText("Save changes")

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
            message = (
                f"Port {configured} was unavailable at startup; bound to "
                f"fallback port {port} for this session. Restart to retry {configured}."
            )
            hint.setText(message)
            hint.setVisible(True)
            self.cfg_port.setAccessibleDescription(
                tr(
                    "Port {configured} was unavailable at startup; bound to fallback "
                    "port {port} for this session. Restart to retry {configured}."
                ).format(configured=configured, port=port)
            )
        else:
            hint.setText("")
            hint.setVisible(False)
            self.cfg_port.setAccessibleDescription("")

    # ── Tools: yt-dlp / ffmpeg maintenance (v1.2.0) ──
    def _tools_status_text(self):
        ytv = self._dependencies['get_ytdlp_version']() or "not installed"
        ffv = self._dependencies['get_ffmpeg_version']() or "not installed"
        return f"yt-dlp {ytv}    •    ffmpeg {ffv}"

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
            self._append_log("yt-dlp is not installed yet — run setup first.")
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
        self.btn_check_updates.setText("Checking…")
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
        self.btn_check_updates.setText("Check yt-dlp Update")
        self._refresh_tools_status()
        if result.get('ok'):
            version = result.get('version_after') or 'current'
            rollback = result.get('rollback_version') or 'not retained yet'
            self._append_log(f"yt-dlp active {version}; rollback {rollback}.")
            self._show_settings_status(f"yt-dlp {version} is ready.", "success")
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

    def _update_output_template_preview(self, *_args):
        """Show the rendered example and any Windows path hazards."""
        label = getattr(self, "outtmpl_preview", None)
        builder = self._dependencies.get("output_template_preview")
        if label is None or not callable(builder):
            return
        report = builder(
            self.cfg_outtmpl.text(),
            self.cfg_dl_path.text(),
        )
        if not report.get("valid"):
            label.setText(tr("Preview unavailable until the template is valid."))
            label.setProperty("state", "error")
            repolish(label)
            return
        warnings = []
        reserved = report.get("reserved") or ()
        if reserved:
            warnings.append(tr(
                "Reserved Windows name in preview: {name}."
            ).format(name=", ".join(reserved)))
        if report.get("too_long"):
            warnings.append(tr(
                "Rendered path is {length} characters; Windows maximum is {maximum}."
            ).format(
                length=report.get("length"),
                maximum=report.get("max_path", 260),
            ))
        if warnings:
            label.setText(" ".join(warnings))
            label.setProperty("state", "error")
        else:
            label.setText(tr(
                "Preview: {path} ({length} characters)."
            ).format(
                path=report.get("path"),
                length=report.get("length"),
            ))
            label.setProperty("state", "neutral")
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

        # Compare against the PERSISTED port: during a session-only fallback
        # (bind conflict) the live port differs from the configured one, and
        # an unrelated settings save must not read that as a port change and
        # surprise-restart the server.
        persisted_get = getattr(self.config, 'get_persisted', self.config.get)
        old_port = self._dependencies['clamp_int'](persisted_get("ServerPort", self._value('SERVER_PORT')), self._value('SERVER_PORT'), 1024, 65535)
        old_token = self.config.get("ServerToken", "")
        old_clipboard_grabber = self.config.get("ClipboardLinkGrabber", False)
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

        def mark_error(field, message):
            nonlocal has_error, first_error
            self._set_input_error(field, True)
            field.setAccessibleDescription(tr(message))
            has_error = True
            if first_error is None:
                first_error = field

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
            mark_error(site_profiles_field, site_profiles_error)
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
                "%(title)s, %(id)s, %(uploader)s — no absolute paths or '..'.",
            )
        preview_builder = self._dependencies.get("output_template_preview")
        if outtmpl_raw and outtmpl and callable(preview_builder):
            report = preview_builder(outtmpl, dl_path)
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
            self._show_settings_status("Check the highlighted fields before saving.", "danger")
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

        saved = self.config.update({
            "ServerPort": new_port,
            "ServerToken": new_token,
            "DownloadPath": dl_path,
            "AudioDownloadPath": audio_path,
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
            "AutoUpdateYtDlp": self.cfg_autoupdate.isChecked(),
            "CloseToTray": self.cfg_closetotray.isChecked(),
            "StartMinimized": self.cfg_startmin.isChecked(),
            "NotifyOnComplete": self.cfg_notify.isChecked(),
            "ClipboardLinkGrabber": (
                self.cfg_clipboard.isChecked()
                if hasattr(self, "cfg_clipboard")
                else old_clipboard_grabber
            ),
        })
        if not saved:
            self.btn_save.setText("Save changes")
            self._show_settings_status(
                "Could not save settings. Nothing changed; check disk permissions and retry.",
                "danger",
            )
            self._append_log("Settings save failed. Existing settings and server state were preserved.")
            return

        self._dependencies['reset_deno_runtime_cache']()
        self._start_readiness_probe()

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
        self.btn_save.setText(tr("Saved"))
        QTimer.singleShot(1500, lambda: self.btn_save.setText(tr("Save changes")))
        status_generation = getattr(self, "_settings_status_generation", 0)
        QTimer.singleShot(3200, lambda: self._clear_settings_status_if_current(status_generation))

    def _browse(self, line_edit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", line_edit.text())
        if path:
            line_edit.setText(path)

    def _quick_download_url_edited(self, *_args):
        """Clear clipboard-specific guidance once the user edits a staged URL."""
        self._sync_quick_download_profile(apply=True)
        self._schedule_format_probe()
        if not self._clipboard_staged_url:
            return
        self._clipboard_staged_url = ""
        self.quick_download_status.hide()

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
            combo.addItem(f"{value}p", str(value))
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
        for field in (self.quick_download_start, self.quick_download_end):
            field.setEnabled(not limited)
            if limited:
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
            # is no longer in the box.
            return
        if payload.get("url") != self.quick_download_url.text().strip():
            return
        self._format_probe_in_flight = False
        self._format_probe_request_url = ""
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
            "Copied video link staged. Review the options, then choose Add to queue."
        )
        self.quick_download_status.setProperty("state", "success")
        self.quick_download_status.show()
        repolish(self.quick_download_status)
        self._append_log("Staged a copied video link for review.")
        if hasattr(self, "tray"):
            self.tray.showMessage(
                self._value('APP_NAME'),
                "Video link staged. Open Downloads to review it before adding it to the queue.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _copy_endpoint(self):
        QApplication.clipboard().setText(self.dash_endpoint.text())
        self._append_log("Endpoint copied to clipboard")
        old = self.dash_hint.text()
        self.dash_hint.setText("Endpoint copied.")
        QTimer.singleShot(1600, lambda: self.dash_hint.setText(old))

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
        dialog.setWindowTitle("Review Diagnostics")
        dialog.setModal(True)
        dialog.resize(720, 520)
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.addButton("Save diagnostics", QDialogButtonBox.ButtonRole.ActionRole)
        save_button.clicked.connect(lambda: self._save_diagnostics_text(text))
        copy_button = buttons.addButton("Copy to Clipboard", QDialogButtonBox.ButtonRole.AcceptRole)
        copy_button.setDefault(True)
        copy_button.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(heading)
        layout.addWidget(detail)
        layout.addWidget(preview, 1)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            QApplication.clipboard().setText(text)
            self._append_log("Redacted diagnostics copied to clipboard")

    def _diagnostics_text(self):
        payload = self._dependencies['build_diagnostics_bundle'](
            server_running=self.server_running,
            endpoint=self.dash_endpoint.text(),
            active_downloads=self.dl_manager.active_count(),
            completed_downloads=self.dl_manager.total_completed,
            recent_logs=self._dependencies['get_recent_log_entries'](),
            secrets=(self.config.get('ServerToken', ''), self.cfg_token.text()),
        )
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _save_diagnostics_text(self, text):
        target, _filter = QFileDialog.getSaveFileName(
            self,
            "Save diagnostics",
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
        self.log_text.setPlainText("\n".join(lines) if lines else "Ready.")

    def _clear_log(self):
        self.log_text.setPlainText("Ready.")

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
                    "Server failed to start. Check the log for details.",
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
                    "Still running in the tray so Astra Deck can keep sending downloads.",
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
        self.setup_status.setText(tr("Installing required download tools..."))
        self.setup_status.show()
        self.setup_progress.setValue(0)
        self.setup_progress.show()
        self.btn_startstop.setEnabled(False)
        self.btn_startstop.setText(tr("Setting Up"))
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
            self.setup_status.setText(tr("Installing yt-dlp..."))
        elif value < 60:
            self.setup_status.setText(tr("Installing ffmpeg..."))
        elif value < 70:
            self.setup_status.setText(tr("Preparing transcription model..."))
        elif value < 95:
            self.setup_status.setText(tr("Registering shortcuts and protocols..."))
        else:
            self.setup_status.setText(tr("Finishing setup..."))

    def _setup_done(self):
        ffmpeg_refresh = bool(getattr(getattr(self, 'setup_worker', None), 'force_ffmpeg', False))
        self._setup_running = False
        self.btn_startstop.setEnabled(True)
        self.btn_startstop.setText("Stop Server" if self.server_running else "Start Server")
        self.setup_progress.setValue(100)
        self.setup_status.setText("ffmpeg refresh complete." if ffmpeg_refresh else "Setup complete.")
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
        self.btn_startstop.setText("Stop Server" if self.server_running else "Start Server")
        self.setup_status.setText(
            "ffmpeg refresh failed. The previous copy is still installed."
            if ffmpeg_refresh else
            "Setup failed. Check the log for details."
        )
        self.setup_progress.hide()
        self._append_log(f"Setup error: {error}")

MainWindow = MainWindowCore


_OWNED_EXPORTS = {
    "repolish", "make_label", "make_section_label", "make_divider",
    "make_card", "make_status_badge", "download_status_tone",
    "human_status", "format_duration", "make_empty_state", "make_stat",
    "ReadinessProbe",
    "FolderPickerService",
    "SetupWorker", "SetupWorkerCore",
    "MainWindow", "MainWindowCore",
    "GUI_ACCESSIBILITY_COLORS", "system_reduced_motion_enabled",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
