"""Site sign-in page layout.

Only the page builder lives here; actions and lifecycle stay on the
injected MainWindowCore so the existing dependency contract is unchanged.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLayout, QLineEdit, QScrollArea,
    QVBoxLayout, QWidget,
)

try:
    from .gui_support import *
except ImportError:  # Flat source-path compatibility.
    from gui_support import *


class SiteLoginsPageMixin:
    def _build_site_logins(self):
        page = QScrollArea()
        page.setWidgetResizable(True)
        page_content = QWidget()
        layout = QVBoxLayout(page_content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(38, 32, 38, 24)
        layout.setSpacing(20)
        header = QHBoxLayout()
        header.addLayout(self._make_page_header(
            "Sign-ins",
            "Save a site sign-in for private or members-only videos.",
        ), 1)
        self.btn_undo_site_login = self._make_tool_button("Undo remove", "ghost")
        self.btn_undo_site_login.setToolTip(
            tr("Restore the sign-in removed by the last action.")
        )
        self.btn_undo_site_login.clicked.connect(self._undo_site_login)
        self.btn_undo_site_login.hide()
        header.addWidget(self.btn_undo_site_login, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        add_card = make_card()
        add_layout = QVBoxLayout(add_card)
        add_layout.setContentsMargins(24, 20, 24, 20)
        add_layout.setSpacing(14)
        add_layout.addWidget(make_label("Add a site sign-in", "sectionHeading"))
        site_row = QVBoxLayout()
        site_row.setSpacing(6)
        site_label = make_label("Site address", "fieldLabel")
        site_row.addWidget(site_label)
        self.site_login_url = QLineEdit()
        self.site_login_url.setAccessibleName(tr("Site address for the sign-in"))
        self.site_login_url.setPlaceholderText(tr("example.com"))
        site_label.setBuddy(self.site_login_url)
        site_row.addWidget(self.site_login_url)
        add_layout.addLayout(site_row)

        method_row = QVBoxLayout()
        method_row.setSpacing(6)
        method_label = make_label("Import method", "fieldLabel")
        method_row.addWidget(method_label)
        self.site_login_method = ChoiceBox()
        self.site_login_method.setAccessibleName(tr("Sign-in import method"))
        self.site_login_method.addItem(tr("Read from browser"), "browser")
        self.site_login_method.addItem(tr("Import cookies.txt"), "file")
        self.site_login_method.addItem(tr("Username and password"), "credentials")
        self.site_login_method.setMaximumWidth(520)
        method_label.setBuddy(self.site_login_method)
        method_row.addWidget(self.site_login_method)
        add_layout.addLayout(method_row)

        self.site_login_credentials_panel = QWidget()
        self.site_login_credentials_panel.setProperty("class", "formFields")
        credentials_layout = QVBoxLayout(self.site_login_credentials_panel)
        credentials_layout.setContentsMargins(0, 0, 0, 0)
        credentials_layout.setSpacing(12)
        credentials_fields = QHBoxLayout()
        credentials_fields.setSpacing(16)
        self.site_login_username = QLineEdit()
        self.site_login_username.setAccessibleName(tr("Site sign-in username"))
        self.site_login_username.setPlaceholderText(tr("name@example.com"))
        self.site_login_password = QLineEdit()
        self.site_login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.site_login_password.setAccessibleName(tr("Site sign-in password"))
        self.site_login_password.setPlaceholderText(tr("Site password"))
        self.site_login_password.setClearButtonEnabled(True)
        for title, field in (
            (tr("Username"), self.site_login_username),
            (tr("Password"), self.site_login_password),
        ):
            field_layout = QVBoxLayout()
            field_layout.setSpacing(6)
            label = make_label(title, "fieldLabel")
            label.setBuddy(field)
            field_layout.addWidget(label)
            field_layout.addWidget(field)
            credentials_fields.addLayout(field_layout, 1)
        credentials_layout.addLayout(credentials_fields)
        self.btn_site_login_credentials = self._make_tool_button(
            "Store username/password", "primary"
        )
        self.btn_site_login_credentials.clicked.connect(
            self._store_site_login_credentials
        )
        credentials_actions = QHBoxLayout()
        credentials_actions.addStretch()
        credentials_actions.addWidget(self.btn_site_login_credentials)
        credentials_layout.addLayout(credentials_actions)
        add_layout.addWidget(self.site_login_credentials_panel)

        self.site_login_browser_panel = QWidget()
        self.site_login_browser_panel.setProperty("class", "formFields")
        browser_layout = QVBoxLayout(self.site_login_browser_panel)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.setSpacing(14)
        source_fields = QHBoxLayout()
        source_fields.setSpacing(16)
        self.site_login_browser = ChoiceBox()
        self.site_login_browser.setAccessibleName(tr("Browser to read cookies from"))
        for browser in self._value('SITE_LOGIN_BROWSERS'):
            label = browser.title()
            warning = self._dependencies['describe_browser_cookie_readiness'](browser)
            if warning:
                label = tr_format(
                    "{browser}. {warning}",
                    browser=label,
                    warning=tr("likely unreadable on Chromium 127+"),
                )
            self.site_login_browser.addItem(label, browser)
        # Firefox is the one browser whose cookie store can still be read from
        # outside on Windows, so it is the default rather than whichever name
        # sorts first.
        firefox_index = self.site_login_browser.findData("firefox")
        if firefox_index >= 0:
            self.site_login_browser.setCurrentIndex(firefox_index)
        self.site_login_browser.setMinimumWidth(170)
        self.site_login_profile = QLineEdit()
        self.site_login_profile.setAccessibleName(tr("Browser profile name or path"))
        # Was "Profile (optional)", which restated the label and showed no
        # example of what a profile actually looks like.
        self.site_login_profile.setPlaceholderText(tr("Default, or a profile name"))
        self.site_login_profile.setMinimumWidth(180)
        for title, field in (
            (tr("Browser"), self.site_login_browser),
            (tr("Profile (optional)"), self.site_login_profile),
        ):
            field_layout = QVBoxLayout()
            field_layout.setSpacing(6)
            label = make_label(title, "fieldLabel")
            label.setBuddy(field)
            field_layout.addWidget(label)
            field_layout.addWidget(field)
            source_fields.addLayout(field_layout, 1)
        browser_layout.addLayout(source_fields)

        source_actions = QHBoxLayout()
        source_actions.setSpacing(16)
        source_actions.addWidget(make_label(
            "Firefox can usually be read directly. For Chrome or Edge, "
            "import a cookies.txt file.", "toolbarMeta", word_wrap=True,
        ), 1)
        self.btn_site_login_browser = self._make_tool_button("Read from browser", "primary")
        self.btn_site_login_browser.clicked.connect(self._import_site_login_from_browser)
        source_actions.addWidget(self.btn_site_login_browser)
        browser_layout.addLayout(source_actions)
        add_layout.addWidget(self.site_login_browser_panel)

        self.site_login_file_panel = QWidget()
        self.site_login_file_panel.setProperty("class", "formFields")
        file_layout = QVBoxLayout(self.site_login_file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(14)
        file_layout.addWidget(make_label(
            "Choose a cookies.txt file exported from the browser where "
            "you signed in to this site.", "toolbarMeta", word_wrap=True,
        ))
        file_actions = QHBoxLayout()
        file_actions.addStretch()
        self.btn_site_login_file = self._make_tool_button("Import cookies.txt", "primary")
        self.btn_site_login_file.clicked.connect(self._import_site_login_from_file)
        file_actions.addWidget(self.btn_site_login_file)
        file_layout.addLayout(file_actions)
        add_layout.addWidget(self.site_login_file_panel)

        self.site_login_method.currentIndexChanged.connect(self._show_site_login_method)
        self._show_site_login_method()

        add_layout.addWidget(make_divider())
        add_layout.addWidget(make_label(
            "Sign-ins stay on this PC and are sent only to their site.",
            "fieldHint", word_wrap=True,
        ))
        self.site_login_status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.site_login_status.setAccessibleName(tr("Site sign-in status"))
        self.site_login_status.hide()
        add_layout.addWidget(self.site_login_status)
        self.youtube_sign_in_warning = QLabel(tr(
            "YouTube sign-ins are risky. yt-dlp warns that account use can "
            "cause temporary or permanent bans, and some signed-in sessions "
            "can make public videos unplayable. Use cookies only for "
            "account-required videos, keep a 5 to 10 second pause, and retry "
            "public videos signed out. <a href=\"https://github.com/yt-dlp/"
            "yt-dlp/wiki/Extractors#exporting-youtube-cookies\">Read yt-dlp's "
            "YouTube guidance.</a>"
        ))
        self.youtube_sign_in_warning.setTextFormat(Qt.TextFormat.RichText)
        self.youtube_sign_in_warning.setOpenExternalLinks(True)
        self.youtube_sign_in_warning.setWordWrap(True)
        self.youtube_sign_in_warning.setProperty("class", "settingsStatus")
        self.youtube_sign_in_warning.setProperty("tone", "warning")
        self.youtube_sign_in_warning.setAccessibleName(
            tr("YouTube sign-in risk warning")
        )
        self.youtube_sign_in_warning.hide()
        add_layout.addWidget(self.youtube_sign_in_warning)
        layout.addWidget(add_card)

        layout.addWidget(make_label("Stored sign-ins", "sectionHeading"))
        site_login_filter_panel = QWidget()
        site_login_filters = QHBoxLayout(site_login_filter_panel)
        site_login_filters.setContentsMargins(0, 0, 0, 0)
        site_login_filters.setSpacing(12)
        self.site_login_search = QLineEdit()
        self.site_login_search.setAccessibleName(tr("Search stored sign-ins"))
        self.site_login_search.setPlaceholderText(tr("Search site or source"))
        self.site_login_search.setClearButtonEnabled(True)
        site_login_filters.addWidget(self.site_login_search, 2)
        self.site_login_status_filter = ChoiceBox()
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
        self.site_login_scroll.setMinimumHeight(220)
        content = QWidget()
        self.site_login_container = QVBoxLayout(content)
        self.site_login_container.setContentsMargins(0, 0, 0, 0)
        self.site_login_container.setSpacing(10)
        self.site_login_scroll.setWidget(content)
        layout.addWidget(self.site_login_scroll, 1)
        page.setWidget(page_content)
        self.tabs.addTab(page, tr("Sign-ins"))
        self._refresh_site_logins(force=True)

    def _show_site_login_method(self, *_args):
        method = self.site_login_method.currentData()
        self.site_login_browser_panel.setVisible(method == "browser")
        self.site_login_file_panel.setVisible(method == "file")
        self.site_login_credentials_panel.setVisible(method == "credentials")
