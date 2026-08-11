"""Download page layout and controls.

The page owns its construction; cross-page actions remain on the
injected MainWindowCore.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

try:
    from .gui_support import *
    from .config import default_download_path
    from .i18n import ADVERTISED_LOCALES
except ImportError:  # Flat source-path compatibility.
    from gui_support import *
    from config import default_download_path
    from i18n import ADVERTISED_LOCALES


_PREFLIGHT_ROW_SPECS = (
    ("ytdlp-freshness", "yt-dlp freshness", "refresh-ytdlp"),
    ("javascript-runtime", "JavaScript runtime", "provision-runtime"),
    ("ffmpeg-capabilities", "FFmpeg security and filters", "refresh-ffmpeg"),
    ("sign-in-expiry", "Stored sign-in expiry", "refresh-sign-in"),
    ("github-api-budget", "Anonymous GitHub API budget", "retry-github"),
    ("po-token-provider", "Proof-of-origin token provider", "use-sign-in"),
)


class DownloadPageMixin:
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
        self.first_run_browse = self._make_tool_button(
            "Browse", target="First-run download folder"
        )
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

        # These controls used to share one HBox. At the documented minimum
        # size, a large system font made Qt squeeze the combo boxes until
        # their text and drop-down arrows painted over their neighbours.
        # Keep the controls in deliberate rows so every current value remains
        # a readable label instead of relying on accidental elision.
        self.quick_download_options_container = QWidget()
        options_layout = QVBoxLayout(self.quick_download_options_container)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(6)
        self.quick_download_options_layout = options_layout

        profile_row_widget = QWidget(self.quick_download_options_container)
        profile_row = QHBoxLayout(profile_row_widget)
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.setSpacing(8)
        profile_row.addWidget(make_label("Profile", "fieldHint"))
        self.quick_download_profile = QComboBox()
        self.quick_download_profile.setAccessibleName(tr("Site profile"))
        self.quick_download_profile.setMinimumWidth(210)
        self.quick_download_profile.setToolTip(tr("Automatic site profile"))
        self.quick_download_profile.currentIndexChanged.connect(
            self._quick_download_profile_changed
        )
        profile_row.addWidget(self.quick_download_profile)
        self.quick_download_type = QComboBox()
        self.quick_download_type.setAccessibleName(tr("Download type"))
        self.quick_download_type.addItem(tr("Video"), "video")
        self.quick_download_type.addItem(tr("Audio"), "audio")
        self.quick_download_type.addItem(tr("Subtitles"), "subtitles")
        self.quick_download_type.currentIndexChanged.connect(
            self._sync_quick_download_options
        )
        profile_row.addWidget(self.quick_download_type)
        profile_row.addStretch(1)
        options_layout.addWidget(profile_row_widget)

        media_row_widget = QWidget(self.quick_download_options_container)
        media_row = QHBoxLayout(media_row_widget)
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.setSpacing(8)
        self.quick_download_format = QComboBox()
        self.quick_download_format.setAccessibleName(tr("Download format"))
        self.quick_download_format.setMinimumWidth(100)
        media_row.addWidget(self.quick_download_format)
        self.quick_download_quality = QComboBox()
        self.quick_download_quality.setAccessibleName(tr("Download quality"))
        self.quick_download_quality.setMinimumWidth(100)
        self._set_quality_choices(self._value('QUALITY_LADDER'))
        media_row.addWidget(self.quick_download_quality)
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
        media_row.addWidget(self.btn_quick_download_dest)
        media_row.addStretch(1)
        options_layout.addWidget(media_row_widget)

        clip_row_widget = QWidget(self.quick_download_options_container)
        clip_row = QHBoxLayout(clip_row_widget)
        clip_row.setContentsMargins(0, 0, 0, 0)
        clip_row.setSpacing(8)
        clip_row.addWidget(make_label("Clip from", "fieldHint"))
        self.quick_download_start = QLineEdit()
        self.quick_download_start.setAccessibleName(tr("Clip start timestamp"))
        self.quick_download_start.setPlaceholderText("0:00")
        self.quick_download_start.setMaximumWidth(84)
        clip_row.addWidget(self.quick_download_start)
        clip_row.addWidget(make_label("to", "fieldHint"))
        self.quick_download_end = QLineEdit()
        self.quick_download_end.setAccessibleName(tr("Clip end timestamp"))
        self.quick_download_end.setPlaceholderText("1:30")
        self.quick_download_end.setMaximumWidth(84)
        clip_row.addWidget(self.quick_download_end)
        self.btn_quick_clip_from_url = self._make_tool_button(
            "From link", "ghost"
        )
        self.btn_quick_clip_from_url.setToolTip(tr(
            "Use the timestamp in the pasted link as the clip start."
        ))
        self.btn_quick_clip_from_url.clicked.connect(
            self._set_quick_clip_from_url
        )
        clip_row.addWidget(self.btn_quick_clip_from_url)
        self.btn_quick_clip_last_30 = self._make_tool_button(
            "Last 30 s", "ghost"
        )
        self.btn_quick_clip_last_30.setToolTip(tr(
            "Download only the last 30 seconds using yt-dlp."
        ))
        self.btn_quick_clip_last_30.clicked.connect(
            self._set_quick_clip_last_30
        )
        clip_row.addWidget(self.btn_quick_clip_last_30)
        clip_row.addStretch(1)
        options_layout.addWidget(clip_row_widget)
        quick_layout.addWidget(self.quick_download_options_container)
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

        preflight_panel = QFrame()
        preflight_panel.setProperty("class", "readiness")
        preflight_layout = QVBoxLayout(preflight_panel)
        preflight_layout.setContentsMargins(18, 10, 18, 8)
        preflight_layout.setSpacing(1)
        preflight_header = QHBoxLayout()
        preflight_header.addWidget(make_label("Pre-flight", "panelTitle"))
        preflight_header.addStretch()
        preflight_layout.addLayout(preflight_header)
        preflight_layout.addWidget(make_label(
            "Checks known download failure causes before a job starts. Each row names the remedy.",
            "fieldHint", word_wrap=True,
        ))
        for key, label_text, action_text in _PREFLIGHT_ROW_SPECS:
            preflight_layout.addWidget(
                self._make_preflight_row(key, label_text, action_text)
            )
        self.preflight_panel = preflight_panel
        layout.addWidget(preflight_panel)

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
        # The download page has a fixed collection of setup, readiness and
        # queue surfaces above its own queue scroller. Let the page itself
        # scroll at the documented minimum window size so a wrapped options
        # row keeps its full height instead of being compressed into the
        # neighbouring controls.
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setWidget(page)
        self.download_page_scroll = page_scroll
        self.tabs.addTab(page_scroll, tr("Download"))
