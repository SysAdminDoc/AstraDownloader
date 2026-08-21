"""Subscriptions page layout.

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


class SubscriptionsPageMixin:
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
            tr("Restore the subscription removed by the last action.")
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
        self.subscription_url.setPlaceholderText(
            tr("https://www.youtube.com/@channel or playlist URL")
        )
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

        subscription_filter_panel = make_card("filterBar")
        subscription_filters = QHBoxLayout(subscription_filter_panel)
        subscription_filters.setContentsMargins(14, 12, 14, 12)
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
        layout.addWidget(subscription_filter_panel)
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
        self.tabs.addTab(page, tr("Subscriptions"))
        self._refresh_subscriptions(force=True)
