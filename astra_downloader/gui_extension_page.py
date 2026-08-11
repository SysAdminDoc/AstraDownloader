"""Extension page layout and local server activity.

Only the page builder lives here; actions and lifecycle stay on the
injected MainWindowCore so the existing dependency contract is unchanged.
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

try:
    from .gui_support import *
except ImportError:  # Flat source-path compatibility.
    from gui_support import *


class ExtensionPageMixin:
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
        self.log_empty_state = make_empty_state(
            tr("No server events yet"),
            tr(
                "Start the local API or pair the browser extension to see "
                "recent activity here."
            ),
            "Start server",
            self._start_server,
        )
        layout.addWidget(self.log_empty_state, 1)
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

        self.tabs.addTab(page, tr("Browser extension"))
