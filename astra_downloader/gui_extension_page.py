"""Extension pairing with optional connection details and local activity."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
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
        layout.setSpacing(22)
        layout.addLayout(self._make_page_header(
            "Browser extension",
            "Send downloads from your browser with Astra Deck.",
        ))

        ctrl = make_card("serverControl")
        ctrl_layout = QHBoxLayout(ctrl)
        ctrl_layout.setContentsMargins(20, 20, 20, 20)
        ctrl_layout.setSpacing(14)
        self.server_badge = make_label("\u25cf", "stateDot")
        self.server_badge.setProperty("tone", "neutral")
        self.server_badge.setAccessibleName(
            tr("Extension server status indicator: Offline")
        )
        ctrl_layout.addWidget(self.server_badge)
        state_copy = QVBoxLayout()
        state_copy.setSpacing(5)
        self.dash_status = make_label("Server offline", "heroTitle", status=True)
        state_copy.addWidget(self.dash_status)
        self.dash_hint = make_label("Local only \u00b7 token required", "fieldHint", word_wrap=True)
        state_copy.addWidget(self.dash_hint)
        ctrl_layout.addLayout(state_copy, 1)
        self.btn_startstop = self._make_tool_button("Start server", "primary")
        self.btn_startstop.clicked.connect(self._toggle_server)
        ctrl_layout.addWidget(self.btn_startstop)
        layout.addWidget(ctrl)
        layout.addWidget(make_divider())

        layout.addWidget(make_label("Connect your browser", "sectionHeading"))
        pairing = QHBoxLayout()
        pairing.setSpacing(36)
        chrome = QVBoxLayout()
        chrome.setSpacing(12)
        chrome.addWidget(make_label("Chrome and Edge", "cardTitle"))
        chrome.addWidget(make_label(
            "Allow pairing, then use a download button in Astra Deck within two minutes.",
            "fieldHint", word_wrap=True,
        ))
        self.btn_allow_extension_pairing = self._make_tool_button(
            "Allow extension pairing", "secondary"
        )
        self.btn_allow_extension_pairing.setToolTip(
            tr("Let one Chrome or Edge extension pair in the next two minutes.")
        )
        self.btn_allow_extension_pairing.clicked.connect(self._open_extension_pairing)
        chrome.addWidget(self.btn_allow_extension_pairing, 0, Qt.AlignmentFlag.AlignLeft)
        self.native_pairing_status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.native_pairing_status.setAccessibleName(tr("Chrome pairing status"))
        self.native_pairing_status.hide()
        chrome.addWidget(self.native_pairing_status)
        pairing.addLayout(chrome, 1)

        userscript = QVBoxLayout()
        userscript.setSpacing(12)
        userscript.addWidget(make_label("Userscript", "cardTitle"))
        userscript.addWidget(make_label(
            "Pair the Astra Deck userscript, then use a download button on YouTube.",
            "fieldHint", word_wrap=True,
        ))
        self.btn_pair_userscript = self._make_tool_button("Pair userscript", "secondary")
        self.btn_pair_userscript.setToolTip(
            tr("Let the Astra Deck userscript collect the token once in the next two minutes.")
        )
        self.btn_pair_userscript.clicked.connect(self._open_userscript_pairing)
        userscript.addWidget(self.btn_pair_userscript, 0, Qt.AlignmentFlag.AlignLeft)
        self.userscript_pairing_status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.userscript_pairing_status.setAccessibleName(tr("Userscript pairing status"))
        self.userscript_pairing_status.hide()
        userscript.addWidget(self.userscript_pairing_status)
        pairing.addLayout(userscript, 1)
        layout.addLayout(pairing)
        layout.addWidget(make_label(
            "Firefox is registered automatically.", "fieldHint", word_wrap=True,
        ))
        layout.addWidget(make_label(
            "Downloading by pasting a link never needs this server.",
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(make_divider())

        details_header = QHBoxLayout()
        details_copy = QVBoxLayout()
        details_copy.setSpacing(5)
        details_copy.addWidget(make_label("Connection details and activity", "fieldLabel", word_wrap=True))
        details_copy.addWidget(make_label(
            "Manual extension IDs, local address and server log.", "fieldHint", word_wrap=True,
        ))
        details_header.addLayout(details_copy, 1)
        self.btn_extension_details = self._make_tool_button("More options", "ghost")
        self.btn_extension_details.setCheckable(True)
        self.btn_extension_details.setAccessibleName(tr("Connection details and activity"))
        self.btn_extension_details.toggled.connect(self._set_extension_details_expanded)
        details_header.addWidget(self.btn_extension_details)
        layout.addLayout(details_header)

        self.extension_details = QWidget()
        details = QVBoxLayout(self.extension_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(16)
        endpoint_row = QHBoxLayout()
        self.dash_endpoint = make_label(
            f"http://127.0.0.1:{self.config.get('ServerPort', self._value('SERVER_PORT'))}",
            "secondary",
        )
        self.dash_endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.dash_endpoint)
        endpoint_row.addStretch()
        btn_copy = self._make_tool_button("Copy endpoint")
        btn_copy.clicked.connect(self._copy_endpoint)
        endpoint_row.addWidget(btn_copy)
        btn_folder = self._make_tool_button("Open folder")
        btn_folder.clicked.connect(self._open_folder)
        endpoint_row.addWidget(btn_folder)
        details.addLayout(endpoint_row)
        details.addWidget(self._make_readiness_row("server", "Local API", "Stopped"))
        details.addWidget(make_label("Chrome and Edge extension IDs", "fieldLabel"))
        details.addWidget(make_label(
            "For manual pairing, paste the ID from chrome://extensions. "
            "Separate multiple IDs with commas. Only the signed .crx build pairs on its own.",
            "fieldHint", word_wrap=True,
        ))
        chrome_row = QHBoxLayout()
        self.cfg_native_chrome_ids = QLineEdit(
            str(self.config.get("NativeChromeExtensionIds", "") or "")
        )
        self.cfg_native_chrome_ids.setPlaceholderText(
            tr("32-letter extension ID. Separate multiple IDs with commas.")
        )
        self.cfg_native_chrome_ids.setAccessibleName(tr("Chrome and Edge extension IDs"))
        chrome_row.addWidget(self.cfg_native_chrome_ids, 1)
        self.btn_register_chrome_host = self._make_tool_button("Register", "secondary")
        self.btn_register_chrome_host.setToolTip(
            tr("Write the Chrome and Edge native-messaging registration for these IDs.")
        )
        self.btn_register_chrome_host.clicked.connect(self._apply_native_chrome_ids)
        chrome_row.addWidget(self.btn_register_chrome_host)
        details.addLayout(chrome_row)
        details.addWidget(make_label(
            "Regenerating the token in Settings unpairs the userscript.",
            "fieldHint", word_wrap=True,
        ))
        details.addWidget(make_divider())
        stats_layout = QGridLayout()
        stats_layout.setSpacing(0)
        self._stat_frame_active, self.stat_active = make_stat("Active", "0", "In progress")
        self.stat_active.setProperty("tone", "accent")
        self._stat_frame_completed, self.stat_completed = make_stat("Completed", "0", "This session")
        self._stat_frame_uptime, self.stat_uptime = make_stat("Uptime", tr("Off"), "Since launch")
        self._stat_frame_port, self.stat_port = make_stat(
            "Port", str(self.config.get("ServerPort", self._value('SERVER_PORT'))), "Local API"
        )
        for index, frame in enumerate((self._stat_frame_active, self._stat_frame_completed,
                                       self._stat_frame_uptime, self._stat_frame_port)):
            stats_layout.addWidget(frame, index // 2, index % 2)
        self._stat_frame_completed.setProperty("last", "true")
        self._stat_frame_port.setProperty("last", "true")
        details.addLayout(stats_layout)
        details.addWidget(make_divider())
        log_header = QHBoxLayout()
        log_header.addWidget(make_label("Server log", "panelTitle"), 1)
        btn_clear_log = self._make_tool_button("Clear", "ghost")
        btn_clear_log.clicked.connect(self._clear_log)
        log_header.addWidget(btn_clear_log)
        btn_diag = self._make_tool_button("Review diagnostics", "ghost")
        btn_diag.setToolTip(tr("Review the redacted support payload before copying it."))
        btn_diag.clicked.connect(self._copy_diagnostics)
        log_actions = QHBoxLayout()
        log_actions.addWidget(btn_diag)
        btn_reveal_log = self._make_tool_button("Reveal log file", "ghost")
        btn_reveal_log.setToolTip(tr("Open the persisted server log in File Explorer."))
        btn_reveal_log.clicked.connect(self._reveal_log_file)
        log_actions.addWidget(btn_reveal_log)
        log_actions.addStretch()
        details.addLayout(log_header)
        details.addLayout(log_actions)
        self.log_empty_state = make_empty_state(
            tr("No server events yet"),
            tr("Start the local API or pair the browser extension to see recent activity here."),
            "Start server", self._start_server,
        )
        details.addWidget(self.log_empty_state)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setAccessibleName(tr("Server log"))
        self.log_text.setAccessibleDescription(
            tr("Recent local companion events. Use Clear to remove visible entries.")
        )
        self.log_text.setMinimumHeight(180)
        self.log_text.document().setMaximumBlockCount(300)
        self._restore_log_view()
        details.addWidget(self.log_text)
        layout.addWidget(self.extension_details)
        self.extension_details.hide()
        layout.addStretch()
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setWidget(page)
        self.extension_page_scroll = page_scroll
        self.tabs.addTab(page_scroll, tr("Browser extension"))

    def _set_extension_details_expanded(self, expanded):
        self.extension_details.setVisible(bool(expanded))
        self.btn_extension_details.setText(tr("Fewer options" if expanded else "More options"))
