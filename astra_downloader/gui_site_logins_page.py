"""Site sign-in page layout.

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


class SiteLoginsPageMixin:
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
            tr("Restore the sign-in removed by the last action.")
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
            tr("Site address you signed in to, such as x.com, instagram.com, or vimeo.com")
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

        source_fields = QHBoxLayout()
        source_fields.setSpacing(8)
        source_fields.addWidget(make_label(tr("Read from"), "fieldHint"))
        self.site_login_browser = QComboBox()
        self.site_login_browser.setAccessibleName(tr("Browser to read cookies from"))
        for browser in self._value('SITE_LOGIN_BROWSERS'):
            label = browser.title()
            warning = self._dependencies['describe_browser_cookie_readiness'](browser)
            if warning:
                label = tr_format(
                    "{browser}. {warning}",
                    browser=label,
                    warning=tr("likely unreadable on Windows 127+"),
                )
            self.site_login_browser.addItem(label, browser)
        # Firefox is the one browser whose cookie store can still be read from
        # outside on Windows, so it is the default rather than whichever name
        # sorts first.
        firefox_index = self.site_login_browser.findData("firefox")
        if firefox_index >= 0:
            self.site_login_browser.setCurrentIndex(firefox_index)
        self.site_login_browser.setMinimumWidth(170)
        source_fields.addWidget(self.site_login_browser)
        self.site_login_profile = QLineEdit()
        self.site_login_profile.setAccessibleName(tr("Browser profile name or path"))
        self.site_login_profile.setPlaceholderText(tr("Profile (optional)"))
        self.site_login_profile.setMinimumWidth(180)
        self.site_login_profile.setMaximumWidth(300)
        source_fields.addWidget(self.site_login_profile, 1)
        add_layout.addLayout(source_fields)

        source_actions = QHBoxLayout()
        source_actions.setSpacing(8)
        source_actions.addStretch()
        self.btn_site_login_browser = self._make_tool_button("Read from browser", "primary")
        self.btn_site_login_browser.clicked.connect(self._import_site_login_from_browser)
        source_actions.addWidget(self.btn_site_login_browser)
        self.btn_site_login_file = self._make_tool_button("Import cookies.txt", "ghost")
        self.btn_site_login_file.clicked.connect(self._import_site_login_from_file)
        source_actions.addWidget(self.btn_site_login_file)
        add_layout.addLayout(source_actions)

        add_layout.addWidget(make_label(
            tr("Chromium browsers such as Chrome, Edge, Brave, Opera, Vivaldi, "
               "and Chromium 127+ encrypt their cookie store, so reading them "
               "from outside the browser usually fails. Export a cookies.txt "
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

        site_login_filter_panel = make_card("filterBar")
        site_login_filters = QHBoxLayout(site_login_filter_panel)
        site_login_filters.setContentsMargins(14, 12, 14, 12)
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
        layout.addWidget(site_login_filter_panel)
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
        self.tabs.addTab(page, tr("Sign-ins"))
        self._refresh_site_logins(force=True)
