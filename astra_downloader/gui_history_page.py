"""History page layout.

Only the page builder lives here; actions and lifecycle stay on the
injected MainWindowCore so the existing dependency contract is unchanged.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QScrollArea, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

try:
    from .gui_support import *
except ImportError:  # Flat source-path compatibility.
    from gui_support import *


class HistoryPageMixin:
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

        filters_panel = make_card("filterBar")
        filters_panel_layout = QVBoxLayout(filters_panel)
        filters_panel_layout.setContentsMargins(14, 14, 14, 14)
        filters_panel_layout.setSpacing(8)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.history_search = QLineEdit()
        self.history_search.setAccessibleName(tr("Search download history"))
        self.history_search.setPlaceholderText(tr("Search title or filename"))
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
        filters_panel_layout.addLayout(filters)

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
        filters_panel_layout.addLayout(range_row)

        # Clear, Undo and Export used to report through _append_log, whose
        # widget lives on the Browser extension page — so a permissions error
        # here produced no visible response at all. Every other page has one
        # of these.
        self.history_page_status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.history_page_status.setAccessibleName(tr("History status message"))
        self.history_page_status.hide()
        filters_panel_layout.addWidget(self.history_page_status)
        layout.addWidget(filters_panel)

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
            label.setMinimumWidth(92)
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
        self.tabs.addTab(page, tr("History"))
