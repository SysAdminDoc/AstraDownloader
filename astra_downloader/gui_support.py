"""Presentation primitives shared by the page modules and GUI shell.

This module has no application composition-root imports.  Page modules receive
their state from ``MainWindowCore`` and use these small, dependency-neutral
builders for the common visual language.
"""

from PySide6.QtCore import QCoreApplication, QSize, Qt
from PySide6.QtGui import (
    QAccessible, QAccessibleEvent, QColor, QIcon, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)


__all__ = (
    "GUI_ACCESSIBILITY_COLORS", "describe_rejected_links", "download_status_tone", "filter_site_login_entries",
    "filter_subscription_records", "format_duration", "human_status", "make_card",
    "make_divider", "make_empty_state", "make_label", "make_line_icon", "make_section_label",
    "line_icon_glyph", "make_stat", "make_state_label", "make_status_badge",
    "make_vertical_divider",
    "announce_status", "refresh_line_icons", "repolish", "sanitize_csv_cell",
    "set_gui_theme", "set_line_icon", "set_status_tone",
    "SUBTITLE_LANGUAGE_CHOICES", "PREFLIGHT_ROW_SPECS", "tr", "tr_format",
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


def announce_status(label):
    """Raise a screen-reader Alert for a status label whose text just changed.

    WCAG 2.2 SC 4.1.3 asks that a status message reach assistive technology
    without moving focus. Qt does not infer that from ``setText`` — nothing is
    delivered unless an accessibility event is posted, so a screen-reader user
    who presses Download and is rejected otherwise hears nothing.

    Returns whether the event was posted, which is what the test asserts.
    """
    if not isinstance(label, QWidget):
        # Several harnesses drive lightweight doubles through the same status
        # setters; an accessibility event needs a real QObject.
        return False
    if QApplication.instance() is None:
        return False
    QAccessible.updateAccessibility(
        QAccessibleEvent(label, QAccessible.Event.Alert)
    )
    return True


class StatusLabel(QLabel):
    """A label that tells assistive technology when its text changes.

    Routing the announcement through the status *setters* left every call site
    that writes the label directly silent, and there are dozens — the whole
    first-run sequence, every subscription message, the Settings save result.
    Announcing from ``setText`` covers all of them, including ones written
    later, and it is the only place that can see whether the text actually
    changed. Repeating an unchanged message would interrupt a screen reader
    mid-word on every keystroke of a live preview.
    """

    def setText(self, text):
        changed = text != self.text()
        super().setText(text)
        if changed:
            announce_status(self)


def set_status_tone(label, state, *, announce=True):
    """Give a status label a visible tone.

    Accepts the historical setter values — "error" maps onto the stylesheet's
    "danger" tone so every status label shares the one settingsStatus
    convention instead of setting a `state` property no stylesheet rule ever
    matched.

    The screen-reader Alert is raised by StatusLabel.setText, not here: a tone
    change on its own is not a status message, and half the call sites that
    write these labels never come through this function. ``announce`` is kept
    because it marks the two clearing call sites, and a label that is not a
    StatusLabel still gets an Alert from here so a plain QLabel used as a
    status surface is not silent.
    """
    tone = str(state or "neutral")
    tone = {"error": "danger"}.get(tone, tone)
    label.setProperty("tone", tone)
    if announce and not isinstance(label, StatusLabel):
        announce_status(label)
    # The caller repolishes: gui.py's imported `repolish` is what the test
    # harnesses patch, and a repolish buried here would bypass that seam.


def tr(text):
    """Translate a static companion UI string through the installed catalogue."""
    return QCoreApplication.translate("AstraDownloader", str(text))


def tr_format(template, **values):
    """Translate a format-string template before inserting runtime values."""
    return tr(template).format(**values)


def make_label(text, class_name=None, word_wrap=False, status=False):
    """Build a body label. ``status`` marks one that reports an outcome.

    A status label announces its own text changes; see StatusLabel.
    """
    label = (StatusLabel if status else QLabel)(tr(text))
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


# Matched in order, first hit wins, so a more specific name has to come first:
# "Undo remove" is an undo, not a remove, and "Import settings" is an import,
# not the Settings page. The fallback is reserved for a name nothing here
# One table, because there were two: the Download page built its rows from
# its own copy while `_apply_preflight` wrote statuses from another, so a
# check added to one list existed as a row nobody ever updated. Both modules
# import gui_support, so this is the only place both can see.
PREFLIGHT_ROW_SPECS = (
    ("ytdlp-freshness", "yt-dlp freshness", "refresh-ytdlp"),
    ("javascript-runtime", "JavaScript runtime", "provision-runtime"),
    ("ffmpeg-capabilities", "FFmpeg security and filters", "refresh-ffmpeg"),
    ("sign-in-expiry", "Stored sign-in expiry", "refresh-sign-in"),
    ("github-api-budget", "Anonymous GitHub API budget", "retry-github"),
    ("po-token-provider", "Proof-of-origin token provider", "use-sign-in"),
    ("output-folder", "Download folder", "choose-output-folder"),
    ("state-location", "Settings and queue storage", "review-state-location"),
    ("site-availability", "Site availability", "review-site-refusals"),
    ("system-clock", "System clock", "sync-system-clock"),
)


# claims — a named button reaching it is the bug this table exists to prevent,
# and a test enumerates every button label to say so.
_ICON_MATCHERS = (
    ("dashboard", lambda key: key == "dashboard"),
    ("extension", lambda key: "extension" in key or "browser" in key),
    ("download", lambda key: key == "downloads" or "download" in key),
    ("history", lambda key: key == "history"),
    ("undo", lambda key: "undo" in key),
    ("restore", lambda key: "restore" in key or "roll back" in key),
    ("pin", lambda key: key in ("pin", "unpin") or key.startswith("pin ")),
    ("start", lambda key: "start" in key or "resume" in key),
    ("stop", lambda key: "stop" in key),
    ("pause", lambda key: "pause" in key),
    ("copy", lambda key: "copy" in key),
    ("folder", lambda key: "folder" in key or "browse" in key or key == "show"),
    ("clear", lambda key: "clear" in key or "cancel" in key),
    ("save", lambda key: "save" in key),
    ("refresh", lambda key: any(
        word in key for word in ("regenerate", "reinstall", "update", "retry")
    )),
    ("reveal", lambda key: "reveal" in key),
    ("diagnostic", lambda key: "diagnostic" in key),
    ("updown", lambda key: key in ("up", "down")),
    ("prevnext", lambda key: "previous" in key or "next" in key),
    ("signin", lambda key: "sign-in" in key or "signin" in key),
    ("export", lambda key: "export" in key),
    ("import", lambda key: "import" in key),
    ("command", lambda key: any(
        word in key for word in ("command", "terminal", "inspect")
    )),
    ("playlist", lambda key: any(
        word in key for word in ("playlist", "stage", "staging", "items")
    )),
    ("remove", lambda key: "remove" in key or "delete" in key),
    ("dismiss", lambda key: "dismiss" in key or key == "close"),
    ("scan", lambda key: "scan" in key),
    ("test", lambda key: "test" in key),
    ("checks", lambda key: "checks" in key),
    ("password", lambda key: "password" in key or "credential" in key),
    ("register", lambda key: "register" in key or "pair" in key),
    ("link", lambda key: "link" in key or "url" in key),
    ("clip", lambda key: "clip" in key or "30 s" in key or "seconds" in key),
    ("options", lambda key: "option" in key or "advanced" in key),
    ("add", lambda key: key.startswith("add") or key.startswith("new ")),
    ("subscriptions", lambda key: "subscription" in key or "feed" in key),
    ("settings", lambda key: "setting" in key or "preference" in key),
)


def line_icon_glyph(name):
    """Name the glyph a button label resolves to.

    Exposed so a test can enumerate every label without rendering, and so the
    painter below dispatches on the same decision the test inspects.
    """
    key = str(name).lower()
    for glyph, matches in _ICON_MATCHERS:
        if matches(key):
            return glyph
    return "fallback"


def _paint_line_icon(painter, glyph):
    if glyph == "dashboard":
        for x, y in ((2, 2), (10, 2), (2, 10), (10, 10)):
            painter.drawRoundedRect(x, y, 6, 6, 1, 1)
    elif glyph == "extension":
        painter.drawRoundedRect(5, 7, 8, 9, 1, 1)
        painter.drawLine(7, 7, 7, 3)
        painter.drawLine(11, 7, 11, 3)
        painter.drawLine(9, 16, 9, 17)
    elif glyph == "download":
        painter.drawLine(9, 2, 9, 12)
        painter.drawLine(5, 9, 9, 13)
        painter.drawLine(13, 9, 9, 13)
        painter.drawLine(3, 16, 15, 16)
    elif glyph == "history":
        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(9, 5, 9, 9)
        painter.drawLine(9, 9, 12, 11)
    elif glyph == "undo":
        # A counter-clockwise arrow, deliberately the mirror of "refresh" and
        # nothing like the action it reverses.
        painter.drawArc(3, 4, 12, 12, 145 * 16, 275 * 16)
        painter.drawLine(3, 3, 3, 8)
        painter.drawLine(3, 8, 8, 8)
    elif glyph == "restore":
        painter.drawArc(3, 4, 12, 12, 145 * 16, 275 * 16)
        painter.drawLine(3, 3, 3, 8)
        painter.drawLine(3, 8, 8, 8)
        painter.drawLine(9, 7, 9, 11)
        painter.drawLine(7, 9, 11, 9)
    elif glyph == "pin":
        # A pushpin seen from the side: head, shaft, point.
        painter.drawLine(5, 3, 13, 3)
        painter.drawLine(7, 3, 7, 9)
        painter.drawLine(11, 3, 11, 9)
        painter.drawLine(4, 9, 14, 9)
        painter.drawLine(9, 9, 9, 16)
    elif glyph == "start":
        painter.drawLine(5, 3, 15, 9)
        painter.drawLine(15, 9, 5, 15)
        painter.drawLine(5, 15, 5, 3)
    elif glyph == "stop":
        painter.drawRoundedRect(4, 4, 10, 10, 1, 1)
    elif glyph == "pause":
        painter.drawLine(6, 3, 6, 15)
        painter.drawLine(12, 3, 12, 15)
    elif glyph == "copy":
        painter.drawRoundedRect(5, 3, 9, 11, 1, 1)
        painter.drawRoundedRect(2, 6, 9, 10, 1, 1)
    elif glyph == "folder":
        painter.drawLine(2, 6, 7, 6)
        painter.drawLine(7, 6, 9, 8)
        painter.drawLine(9, 8, 16, 8)
        painter.drawRoundedRect(2, 5, 14, 11, 1, 1)
    elif glyph == "clear":
        painter.drawLine(5, 6, 6, 16)
        painter.drawLine(13, 6, 12, 16)
        painter.drawLine(6, 16, 12, 16)
        painter.drawLine(4, 5, 14, 5)
        painter.drawLine(7, 2, 11, 2)
    elif glyph == "save":
        painter.drawRoundedRect(3, 2, 12, 14, 1, 1)
        painter.drawLine(6, 2, 6, 7)
        painter.drawLine(6, 7, 12, 7)
        painter.drawEllipse(6, 10, 6, 4)
    elif glyph == "refresh":
        painter.drawArc(3, 3, 12, 12, 35 * 16, 275 * 16)
        painter.drawLine(12, 2, 15, 4)
        painter.drawLine(15, 4, 14, 8)
    elif glyph == "reveal":
        painter.drawEllipse(2, 5, 14, 8)
        painter.drawEllipse(7, 7, 4, 4)
    elif glyph == "diagnostic":
        painter.drawRoundedRect(3, 2, 12, 14, 1, 1)
        painter.drawLine(6, 6, 12, 6)
        painter.drawLine(6, 9, 12, 9)
        painter.drawLine(6, 12, 10, 12)
    elif glyph in ("up", "down"):
        direction = -1 if glyph == "up" else 1
        y_tip = 4 if direction == -1 else 14
        y_tail = 14 if direction == -1 else 4
        painter.drawLine(9, y_tail, 9, y_tip)
        painter.drawLine(9, y_tip, 5, y_tip - (4 * direction))
        painter.drawLine(9, y_tip, 13, y_tip - (4 * direction))
    elif glyph in ("previous", "next"):
        direction = -1 if glyph == "previous" else 1
        x_tip = 5 if direction == -1 else 13
        x_tail = 12 if direction == -1 else 6
        painter.drawLine(x_tail, 3, x_tip, 9)
        painter.drawLine(x_tip, 9, x_tail, 15)
    elif glyph == "signin":
        painter.drawEllipse(2, 6, 7, 7)
        painter.drawLine(8, 9, 16, 9)
        painter.drawLine(13, 9, 13, 13)
        painter.drawLine(16, 9, 16, 12)
    elif glyph == "export":
        painter.drawLine(9, 2, 9, 12)
        painter.drawLine(5, 6, 9, 2)
        painter.drawLine(13, 6, 9, 2)
        painter.drawLine(3, 10, 3, 16)
        painter.drawLine(3, 16, 15, 16)
        painter.drawLine(15, 16, 15, 10)
    elif glyph == "import":
        # The export tray with the arrow reversed: into the box, not out of it.
        painter.drawLine(9, 2, 9, 12)
        painter.drawLine(5, 8, 9, 12)
        painter.drawLine(13, 8, 9, 12)
        painter.drawLine(3, 10, 3, 16)
        painter.drawLine(3, 16, 15, 16)
        painter.drawLine(15, 16, 15, 10)
    elif glyph == "command":
        painter.drawRoundedRect(2, 3, 14, 12, 1, 1)
        painter.drawLine(5, 7, 7, 9)
        painter.drawLine(7, 9, 5, 11)
        painter.drawLine(9, 11, 12, 11)
    elif glyph == "playlist":
        painter.drawEllipse(3, 4, 2, 2)
        painter.drawEllipse(3, 8, 2, 2)
        painter.drawEllipse(3, 12, 2, 2)
        painter.drawLine(7, 5, 15, 5)
        painter.drawLine(7, 9, 15, 9)
        painter.drawLine(7, 13, 15, 13)
    elif glyph == "remove":
        # A bin. Nothing else in this set has a lid.
        painter.drawLine(3, 5, 15, 5)
        painter.drawLine(7, 5, 7, 2)
        painter.drawLine(11, 5, 11, 2)
        painter.drawLine(7, 2, 11, 2)
        painter.drawLine(5, 5, 6, 16)
        painter.drawLine(13, 5, 12, 16)
        painter.drawLine(6, 16, 12, 16)
        painter.drawLine(9, 8, 9, 13)
    elif glyph == "dismiss":
        painter.drawLine(4, 4, 14, 14)
        painter.drawLine(14, 4, 4, 14)
    elif glyph == "scan":
        painter.drawEllipse(3, 3, 9, 9)
        painter.drawLine(11, 11, 16, 16)
        painter.drawLine(6, 7, 9, 7)
    elif glyph == "test":
        painter.drawLine(3, 9, 7, 14)
        painter.drawLine(7, 14, 15, 4)
    elif glyph == "checks":
        painter.drawLine(3, 5, 5, 7)
        painter.drawLine(5, 7, 8, 3)
        painter.drawLine(10, 5, 16, 5)
        painter.drawLine(3, 12, 5, 14)
        painter.drawLine(5, 14, 8, 10)
        painter.drawLine(10, 12, 16, 12)
    elif glyph == "password":
        painter.drawEllipse(2, 6, 7, 7)
        painter.drawEllipse(4, 8, 3, 3)
        painter.drawLine(8, 9, 16, 9)
        painter.drawLine(12, 9, 12, 12)
        painter.drawLine(15, 9, 15, 13)
    elif glyph == "register":
        painter.drawRoundedRect(2, 4, 9, 10, 1, 1)
        painter.drawLine(11, 9, 16, 9)
        painter.drawLine(14, 7, 16, 9)
        painter.drawLine(14, 11, 16, 9)
    elif glyph == "link":
        painter.drawArc(2, 6, 8, 6, 90 * 16, 180 * 16)
        painter.drawArc(8, 6, 8, 6, 270 * 16, 180 * 16)
        painter.drawLine(6, 9, 12, 9)
    elif glyph == "clip":
        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(9, 5, 9, 9)
        painter.drawLine(9, 9, 13, 9)
        painter.drawLine(2, 9, 5, 9)
    elif glyph == "options":
        painter.drawLine(2, 5, 16, 5)
        painter.drawLine(2, 13, 16, 13)
        painter.drawEllipse(5, 3, 4, 4)
        painter.drawEllipse(10, 11, 4, 4)
    elif glyph == "add":
        painter.drawEllipse(2, 2, 14, 14)
        painter.drawLine(9, 5, 9, 13)
        painter.drawLine(5, 9, 13, 9)
    elif glyph == "subscriptions":
        painter.drawArc(3, 4, 12, 12, 0, 90 * 16)
        painter.drawArc(3, 9, 7, 7, 0, 90 * 16)
        painter.drawEllipse(3, 13, 3, 3)
    elif glyph == "settings":
        painter.drawEllipse(5, 5, 8, 8)
        painter.drawEllipse(7, 7, 4, 4)
        painter.drawLine(9, 1, 9, 4)
        painter.drawLine(9, 14, 9, 17)
        painter.drawLine(1, 9, 4, 9)
        painter.drawLine(14, 9, 17, 9)
    else:
        painter.drawLine(2, 5, 16, 5)
        painter.drawLine(2, 9, 16, 9)
        painter.drawLine(2, 13, 16, 13)
        painter.drawEllipse(5, 3, 4, 4)
        painter.drawEllipse(10, 7, 4, 4)
        painter.drawEllipse(4, 11, 4, 4)


def make_line_icon(name, size=18, dpr=None):
    """Draw the rail icons from one quiet monochrome system.

    The backing pixmap is allocated at the device pixel ratio — at 125/150/200
    percent scaling an 18 px allocation would otherwise be upscaled by Qt and
    every stroke goes soft. ``dpr`` is overridable for tests; the default asks
    the running application.
    """
    glyph = line_icon_glyph(name)
    key = str(name).lower()
    if glyph == "updown":
        glyph = key
    elif glyph == "prevnext":
        glyph = "previous" if "previous" in key else "next"
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
    _paint_line_icon(painter, glyph)
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
