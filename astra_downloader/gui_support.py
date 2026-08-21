"""Presentation primitives shared by the page modules and GUI shell.

This module has no application composition-root imports.  Page modules receive
their state from ``MainWindowCore`` and use these small, dependency-neutral
builders for the common visual language.
"""

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)


__all__ = (
    "GUI_ACCESSIBILITY_COLORS", "describe_rejected_links", "download_status_tone", "filter_site_login_entries",
    "filter_subscription_records", "format_duration", "human_status", "make_card",
    "make_divider", "make_empty_state", "make_label", "make_line_icon", "make_section_label",
    "make_stat", "make_state_label", "make_status_badge", "make_vertical_divider",
    "refresh_line_icons", "repolish", "sanitize_csv_cell", "set_gui_theme", "set_line_icon",
    "set_status_tone",
    "SUBTITLE_LANGUAGE_CHOICES", "tr", "tr_format",
)


_THEME_ACCESSIBILITY_COLORS = {
    "dark": {
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
        "accent": "#ff6552",
        "accent_hover": "#ff7867",
        "accent_text": "#170806",
    },
    "light": {
        "surface": "#f6f8fb",
        "sidebar": "#e8edf3",
        "log_surface": "#ffffff",
        "primary": "#18212b",
        "muted": "#536273",
        "neutral": "#536273",
        "neutral_indicator": "#5c6c7b",
        "readiness_text": "#253343",
        "log_text": "#445466",
        "success": "#087f55",
        "warning": "#8a5700",
        "danger": "#b52f25",
        "accent": "#d94c3b",
        "accent_hover": "#e05b49",
        "accent_text": "#2c0d08",
    },
}

GUI_ACCESSIBILITY_COLORS = dict(_THEME_ACCESSIBILITY_COLORS["dark"])
_ICON_THEME = "dark"
_ICON_STROKE_COLORS = {"dark": "#aab2bd", "light": "#445466"}

SUBTITLE_LANGUAGE_CHOICES = (
    ("English", "en"), ("Spanish", "es"), ("Portuguese", "pt"),
    ("French", "fr"), ("German", "de"), ("Italian", "it"),
    ("Russian", "ru"), ("Japanese", "ja"), ("Korean", "ko"),
    ("Chinese", "zh-Hans"), ("Hindi", "hi"), ("Arabic", "ar"),
)


def set_gui_theme(theme):
    """Select the inline GUI palette and return its normalized scheme."""
    normalized = str(theme or "dark").strip().lower()
    normalized = normalized if normalized in _THEME_ACCESSIBILITY_COLORS else "dark"
    GUI_ACCESSIBILITY_COLORS.clear()
    GUI_ACCESSIBILITY_COLORS.update(_THEME_ACCESSIBILITY_COLORS[normalized])
    global _ICON_THEME
    _ICON_THEME = normalized
    return normalized


CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value):
    """Keep untrusted history text literal when opened by a spreadsheet."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_status_tone(label, state, *, announce=True):
    """Give a status label a visible tone.

    Accepts the historical setter values — "error" maps onto the stylesheet's
    "danger" tone so every status label shares the one settingsStatus
    convention instead of setting a `state` property no stylesheet rule ever
    matched. ``announce`` marks the call sites that should raise a
    screen-reader Alert (WCAG 2.2 SC 4.1.3); PySide6 binds QAccessible,
    so the event itself can only be wired once the GUI runs on a binding that
    does.
    """
    tone = str(state or "neutral")
    tone = {"error": "danger"}.get(tone, tone)
    label.setProperty("tone", tone)
    # The caller repolishes: gui.py's imported `repolish` is what the test
    # harnesses patch, and a repolish buried here would bypass that seam.


def tr(text):
    """Translate a static companion UI string through the installed catalogue."""
    return QCoreApplication.translate("AstraDownloader", str(text))


def tr_format(template, **values):
    """Translate a format-string template before inserting runtime values."""
    return tr(template).format(**values)


def make_label(text, class_name=None, word_wrap=False):
    label = QLabel(tr(text))
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
    badge.setAccessibleName(
        tr_format("{label}: {value}", label=tr("Status"), value=translated)
    )
    return badge


def make_state_label(text, tone="neutral"):
    translated = tr(text)
    label = QLabel(tr_format("●  {status}", status=translated))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("class", "stateLabel")
    label.setProperty("tone", tone)
    label.setAccessibleName(
        tr_format("{label}: {value}", label=tr("Status"), value=translated)
    )
    return label


def make_line_icon(name, size=18, dpr=None):
    """Draw the rail icons from one quiet monochrome system.

    The backing pixmap is allocated at the device pixel ratio — at 125/150/200
    percent scaling an 18 px allocation would otherwise be upscaled by Qt and
    every stroke goes soft. ``dpr`` is overridable for tests; the default asks
    the running application.
    """
    key = str(name).lower()
    if dpr is None:
        app = QApplication.instance()
        dpr = float(app.devicePixelRatio()) if app is not None else 1.0
    dpr = max(1.0, float(dpr))
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if size != 18:
        painter.scale(size / 18, size / 18)
    painter.setPen(QPen(
        QColor(_ICON_STROKE_COLORS[_ICON_THEME]),
        1.5,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    ))
    if key == "dashboard":
        for x, y in ((2, 2), (10, 2), (2, 10), (10, 10)):
            painter.drawRoundedRect(x, y, 6, 6, 1, 1)
    elif "extension" in key or "browser" in key:
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
    elif any(word in key for word in ("command", "terminal", "inspect")):
        painter.drawRoundedRect(2, 3, 14, 12, 1, 1)
        painter.drawLine(5, 7, 7, 9)
        painter.drawLine(7, 9, 5, 11)
        painter.drawLine(9, 11, 12, 11)
    elif any(word in key for word in ("playlist", "stage", "staging", "items")):
        painter.drawEllipse(3, 4, 2, 2)
        painter.drawEllipse(3, 8, 2, 2)
        painter.drawEllipse(3, 12, 2, 2)
        painter.drawLine(7, 5, 15, 5)
        painter.drawLine(7, 9, 15, 9)
        painter.drawLine(7, 13, 15, 13)
    else:
        painter.drawLine(2, 5, 16, 5)
        painter.drawLine(2, 9, 16, 9)
        painter.drawLine(2, 13, 16, 13)
        painter.drawEllipse(5, 3, 4, 4)
        painter.drawEllipse(10, 7, 4, 4)
        painter.drawEllipse(4, 11, 4, 4)
    painter.end()
    return QIcon(pixmap)


def set_line_icon(widget, name, size=18):
    widget.setProperty("astraIconName", str(name))
    widget.setProperty("astraIconSize", int(size))
    icon = make_line_icon(name, size=size)
    if hasattr(widget, "setIcon"):
        widget.setIcon(icon)
        widget.setIconSize(QSize(size, size))
    elif hasattr(widget, "setPixmap"):
        widget.setPixmap(icon.pixmap(size, size))
    return icon


def refresh_line_icons(root=None):
    root = root or QApplication.instance()
    if root is None:
        return 0
    if isinstance(root, QApplication):
        widgets = []
        for top_level in root.topLevelWidgets():
            widgets.extend((top_level, *top_level.findChildren(QWidget)))
    elif isinstance(root, QWidget):
        widgets = [root, *root.findChildren(QWidget)]
    else:
        widgets = []
    refreshed = 0
    for widget in widgets:
        name = widget.property("astraIconName")
        if not name:
            continue
        size = widget.property("astraIconSize") or 18
        set_line_icon(widget, name, int(size))
        refreshed += 1
    return refreshed


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
    """Describe rejected links without inventing a single shared cause."""
    reasons = []
    for _url, reason in failures:
        if reason not in reasons:
            reasons.append(reason)
    noun = tr("link") if len(failures) == 1 else tr("links")
    if len(reasons) == 1:
        return tr_format(
            "{count} {noun} rejected: {reason}",
            count=len(failures), noun=noun, reason=reasons[0],
        )
    return tr_format(
        "{count} {noun} rejected for {reasons} different reasons. First: {first}",
        count=len(failures),
        noun=noun,
        reasons=len(reasons),
        first=reasons[0],
    )


def filter_subscription_records(records, query="", status="all"):
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
        "queued": "Queued", "pending": "Pending", "paused": "Paused",
        "needs-auth": "Needs sign-in", "downloading": "Downloading",
        "fetching": "Fetching metadata",
        "merging": "Merging", "extracting": "Extracting", "trimming": "Trimming",
        "embedding": "Embedding metadata",
        "transcribing": "Generating subtitles", "complete": "Complete",
        "failed": "Failed", "cancelled": "Cancelled", "skipped": "Nothing downloaded",
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
    set_line_icon(glyph, "Download" if "Queue" in title else "History", size=36)
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
