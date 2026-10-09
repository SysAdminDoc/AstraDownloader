"""Sites page layout.

Only the page builder and its rendering helpers live here; actions and
lifecycle stay on the injected MainWindowCore so the existing dependency
contract is unchanged.

The page answers one question the downloader could not answer before: what can
I actually paste in here? The curated registry renders immediately, and the
installed yt-dlp's own extractor list is merged in when the probe returns, so
the count on screen is the real one rather than the size of a table someone
maintained by hand.
"""

import threading

from PySide6.QtCore import Qt
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

try:
    from .gui_support import *
except ImportError:  # Flat source-path compatibility.
    from gui_support import *

try:
    from .sites import (
        CATALOG_SOURCE_CURATED, SITE_AUTH_OPTIONAL, SITE_AUTH_REQUIRED,
        SITE_CATEGORIES, merge_extractor_names, search_site_catalog,
        site_catalog,
    )
except ImportError:  # Flat source-path compatibility.
    from sites import (
        CATALOG_SOURCE_CURATED, SITE_AUTH_OPTIONAL, SITE_AUTH_REQUIRED,
        SITE_CATEGORIES, merge_extractor_names, search_site_catalog,
        site_catalog,
    )


# Rendering every row builds a widget per site, and the installed yt-dlp knows
# over 1,700 of them. Past this many the page is not readable anyway, so the
# list is capped and says so rather than freezing the window building cards
# nobody will scroll to.
SITE_ROW_RENDER_LIMIT = 150

def category_label(value):
    """Return the translated display label for a category key.

    The `tr()` calls are literal on purpose. The string extractor that feeds
    the translation catalogues reads source text, so `tr(some_variable)` is
    invisible to it: the label would ship untranslated in every locale while
    the translation gate reported full coverage. Building the map per call
    also means a locale switch is picked up without rebuilding the page.
    """
    return {
        "video": tr("Video"),
        "live": tr("Live streaming"),
        "social": tr("Social"),
        "music": tr("Music and audio"),
        "news": tr("News and broadcast"),
        "learning": tr("Learning"),
        "anime": tr("Anime"),
        "sports": tr("Sports"),
        "archive": tr("Archive"),
        "adult": tr("Adult"),
    }.get(str(value or ""), tr("Video"))


def auth_badge(value):
    """Return `(label, tone)` for a sign-in expectation, or None.

    Literal `tr()` calls here for the same reason as `category_label`.
    """
    if value == SITE_AUTH_REQUIRED:
        return tr("Sign-in needed"), "warning"
    if value == SITE_AUTH_OPTIONAL:
        return tr("Sometimes"), "neutral"
    return None


def describe_catalog_counts(rows, shown):
    """Return the one-line summary under the filter bar.

    Kept as a function so the count logic is testable without a window: the
    interesting cases are "everything fits", "the cap truncated the list", and
    "the filter matched nothing", and each reads differently.
    """
    total = len(rows)
    if not total:
        return tr("No sites match this search.")
    if shown < total:
        return tr_format(
            "Showing {shown} of {total} matching sites. Narrow the search to see the rest.",
            shown=shown,
            total=total,
        )
    if total == 1:
        return tr("1 matching site.")
    return tr_format("{total} matching sites.", total=total)


class SitesPageMixin:
    def _build_sites(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 32, 38, 24)
        layout.setSpacing(20)
        header = QHBoxLayout()
        header.addLayout(self._make_page_header(
            "Sites",
            "Find a site, then paste its link on the Download page.",
        ), 1)
        self.btn_catalog_download = self._make_tool_button("Open downloads", "ghost")
        self.btn_catalog_download.clicked.connect(lambda: self._nav_click("Download"))
        header.addWidget(self.btn_catalog_download, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        # The curated rows are available with no subprocess, so the page is
        # never empty while the extractor list is being read.
        self._site_catalog_rows = list(site_catalog())

        filter_panel = QWidget()
        filters = QHBoxLayout(filter_panel)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(12)
        self.site_catalog_search = QLineEdit()
        self.site_catalog_search.setAccessibleName(tr("Search supported sites"))
        self.site_catalog_search.setPlaceholderText(
            tr("Search by site name or domain")
        )
        self.site_catalog_search.setClearButtonEnabled(True)
        self.site_catalog_search.textChanged.connect(self._refresh_site_catalog)
        filters.addWidget(self.site_catalog_search, 2)

        self.site_catalog_category = ChoiceBox()
        self.site_catalog_category.setAccessibleName(tr("Site category"))
        self.site_catalog_category.addItem(tr("All categories"), "")
        for key in SITE_CATEGORIES:
            self.site_catalog_category.addItem(category_label(key), key)
        self.site_catalog_category.currentIndexChanged.connect(
            self._refresh_site_catalog
        )
        filters.addWidget(self.site_catalog_category)
        layout.addWidget(filter_panel)

        self.site_catalog_meta = make_label("", "toolbarMeta", word_wrap=True)
        layout.addWidget(self.site_catalog_meta)

        list_panel = make_card("listPanel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        columns = QFrame()
        columns.setProperty("class", "listHeader")
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(20, 12, 20, 12)
        columns_layout.setSpacing(20)
        columns_layout.addWidget(make_label("Site", "columnLabel"), 3)
        columns_layout.addWidget(make_label("Category", "columnLabel"), 2)
        columns_layout.addWidget(make_label("Sign-in", "columnLabel"), 1)
        list_layout.addWidget(columns)
        self.site_catalog_scroll = QScrollArea()
        self.site_catalog_scroll.setWidgetResizable(True)
        content = QWidget()
        self.site_catalog_container = QVBoxLayout(content)
        self.site_catalog_container.setContentsMargins(0, 0, 0, 0)
        self.site_catalog_container.setSpacing(0)
        self.site_catalog_scroll.setWidget(content)
        list_layout.addWidget(self.site_catalog_scroll, 1)
        layout.addWidget(list_panel, 1)

        self.tabs.addTab(page, tr("Sites"))
        self._refresh_site_catalog()
        self._load_site_catalog_extractors()

    # --- rendering --------------------------------------------------------

    def _make_site_catalog_row(self, row):
        card = make_card("siteRow")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(6)

        heading = QHBoxLayout()
        heading.setSpacing(20)
        identity = QVBoxLayout()
        identity.setSpacing(4)
        name = make_label(row.get("name") or "", "fieldLabel", word_wrap=True)
        identity.addWidget(name)
        key = row.get("key") or ""
        if key:
            identity.addWidget(make_label(key, "fieldHint", word_wrap=True))
        heading.addLayout(identity, 3)
        if row.get("source") == CATALOG_SOURCE_CURATED:
            category = category_label(row.get("category"))
        else:
            category = ""
        heading.addWidget(make_label(category, "toolbarMeta", word_wrap=True), 2)
        auth = auth_badge(row.get("auth"))
        if auth:
            label, tone = auth
            sign_in = make_label(label, "toolbarMeta", word_wrap=True)
            if tone == "warning":
                set_status_tone(sign_in, tone)
        else:
            sign_in = make_label("", "toolbarMeta")
        heading.addWidget(sign_in, 1)
        outer.addLayout(heading)

        # The sign-in note is the reason a row is worth reading, so it comes
        # before the general note when a site carries both.
        for text in (row.get("auth_note"), row.get("notes")):
            if text:
                outer.addWidget(make_label(text, "toolbarMeta", word_wrap=True))
        return card

    def _clear_site_catalog_rows(self):
        while self.site_catalog_container.count():
            item = self.site_catalog_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _refresh_site_catalog(self, *_args):
        if not hasattr(self, "site_catalog_container"):
            return
        matches = search_site_catalog(
            self._site_catalog_rows,
            self.site_catalog_search.text(),
            self.site_catalog_category.currentData() or "",
        )
        self._clear_site_catalog_rows()
        shown = matches[:SITE_ROW_RENDER_LIMIT]
        for row in shown:
            self.site_catalog_container.addWidget(self._make_site_catalog_row(row))
        self.site_catalog_container.addStretch(1)
        self.site_catalog_meta.setText(describe_catalog_counts(matches, len(shown)))

    # --- extractor list ---------------------------------------------------

    def _load_site_catalog_extractors(self):
        """Merge the installed yt-dlp's extractor list in, off the GUI thread.

        Listing every extractor imports the whole extractor package inside
        yt-dlp and takes seconds, which is why it never runs on the GUI thread
        and why the page is already usable before it finishes.
        """
        def run():
            try:
                names = [
                    name
                    for name, _working in self._dependencies['probe_extractor_list']()
                ]
            except Exception:
                # reason: the catalogue is a reference surface; a probe that
                # cannot run leaves the curated rows on screen rather than
                # emptying the page
                return
            if names:
                try:
                    self.site_catalog_ready.emit(names)
                except RuntimeError:
                    # The probe can finish after the window's QObject was
                    # destroyed. Its result then has no live receiver.
                    if isValid(self):
                        raise

        threading.Thread(
            target=run, name="site-catalog-extractors", daemon=True
        ).start()

    def _on_site_catalog_ready(self, names):
        self._site_catalog_rows = list(merge_extractor_names(names))
        self._refresh_site_catalog()
