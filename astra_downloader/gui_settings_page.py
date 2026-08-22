"""Settings page layout and controls.

The page owns its construction; cross-page actions remain on the
injected MainWindowCore.
"""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QScrollArea, QSpinBox, QTextEdit, QVBoxLayout,
    QWidget,
)

try:
    from .gui_support import *
    from .config import default_download_path
    from .i18n import ADVERTISED_LOCALES
except ImportError:  # Flat source-path compatibility.
    from gui_support import *
    from config import default_download_path
    from i18n import ADVERTISED_LOCALES


class SettingsPageMixin:
    def _update_pacing_guidance(self, *_args):
        minimum = self.cfg_sleep_interval.value()
        configured_max = self.cfg_sleep_max.value()
        jitter = self.cfg_pacing_jitter.value()
        request_pause = self.cfg_sleep_requests.value()
        concurrent = max(1, self.cfg_maxconcurrent.value())
        if minimum <= 0:
            current = tr_format(
                "Current pacing has no pause between downloads with concurrency set "
                "to {concurrent}, so this setting does not impose an hourly ceiling",
                concurrent=concurrent,
            )
        else:
            jitter_max = (minimum * (100 + jitter) + 99) // 100
            effective_max = max(minimum, configured_max, jitter_max)
            per_worker_count = max(1, 7200 // (minimum + effective_max))
            aggregate_count = per_worker_count * concurrent
            per_worker = f"{per_worker_count:,}"
            aggregate = f"{aggregate_count:,}"
            if effective_max == minimum:
                current = tr_format(
                    "Current pacing: {minimum} seconds between downloads per worker, "
                    "about {per_worker} per hour each and {aggregate} total with "
                    "concurrency set to {concurrent}",
                    minimum=minimum,
                    per_worker=per_worker,
                    aggregate=aggregate,
                    concurrent=concurrent,
                )
            else:
                current = tr_format(
                    "Current pacing: {minimum} to {maximum} seconds between "
                    "downloads per worker, about {per_worker} per hour each and "
                    "{aggregate} total with concurrency set to {concurrent}",
                    minimum=minimum,
                    maximum=effective_max,
                    per_worker=per_worker,
                    aggregate=aggregate,
                    concurrent=concurrent,
                )
        if request_pause > 0:
            current += tr_format(
                ", plus {seconds} seconds between requests",
                seconds=request_pause,
            )
        guidance = tr(
            ". yt-dlp reports about 300 videos/hour signed out and 2,000/hour "
            "signed in, and recommends 5 to 10 seconds between downloads. "
            "<a href=\"https://github.com/yt-dlp/yt-dlp/wiki/Extractors"
            "#common-youtube-errors\">Source</a>."
        )
        self.pacing_guidance.setText(current + guidance)

    def _build_settings(self):
        self._settings_group_specs = []
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        root_layout.addWidget(scroll, 1)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(38, 26, 30, 24)
        layout.setSpacing(10)

        layout.addLayout(self._make_page_header("Settings", ""))
        layout.addSpacing(14)
        layout.addWidget(make_divider())

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 14, 0, 0)
        filter_row.addWidget(make_label("Find a setting", "fieldLabel"))
        self.settings_filter = QLineEdit()
        self.settings_filter.setAccessibleName(tr("Filter settings"))
        self.settings_filter.setPlaceholderText(
            tr("Search settings by name or group")
        )
        self.settings_filter.setClearButtonEnabled(True)
        self.settings_filter.textChanged.connect(self._filter_settings)
        filter_row.addWidget(self.settings_filter, 1)
        layout.addLayout(filter_row)
        self.settings_filter_empty = make_label(
            "No settings match this search.", "fieldHint"
        )
        self.settings_filter_empty.setVisible(False)
        layout.addWidget(self.settings_filter_empty)

        # Connection
        conn_card, conn_l = self._make_settings_group("Connection")
        port_row = QHBoxLayout()
        port_copy = QVBoxLayout()
        port_copy.setSpacing(2)
        port_copy.addWidget(make_label("Local API port", "fieldLabel"))
        port_copy.addWidget(make_label("Default 9751. Change only for custom clients.", "fieldHint", word_wrap=True))
        # The dashboard shows the port actually bound, which during a bind
        # conflict is a session-only fallback. Without this line the spinbox
        # silently disagreed with it.
        self.cfg_port_session_hint = make_label("", "fieldHint", word_wrap=True)
        self._set_settings_filter_hidden(self.cfg_port_session_hint, True)
        port_copy.addWidget(self.cfg_port_session_hint)
        port_row.addLayout(port_copy, 1)
        self.cfg_port = QSpinBox()
        self.cfg_port.setAccessibleName(tr("Local API port"))
        self.cfg_port.setRange(1024, 65535)
        # Read the PERSISTED port: a session fallback must never be echoed back
        # into the spinbox, or the next save would write it to disk.
        _persisted_get = getattr(self.config, 'get_persisted', self.config.get)
        self.cfg_port.setValue(self._dependencies['clamp_int'](_persisted_get("ServerPort", self._value('SERVER_PORT')), self._value('SERVER_PORT'), 1024, 65535))
        self.cfg_port.setFixedWidth(100)
        port_row.addWidget(self.cfg_port)
        conn_l.addLayout(port_row)
        conn_l.addWidget(make_divider())
        token_copy = QVBoxLayout()
        token_copy.setSpacing(2)
        token_copy.addWidget(make_label("Private token", "fieldLabel"))
        token_copy.addWidget(make_label("Authorizes extension requests on this computer.", "fieldHint", word_wrap=True))
        conn_l.addLayout(token_copy)
        token_row = QHBoxLayout()
        token_row.setSpacing(8)
        self.cfg_token = QLineEdit(self.config.get("ServerToken", ""))
        self.cfg_token.setAccessibleName(tr("Private API token"))
        self.cfg_token.setReadOnly(True)
        self.cfg_token.setEchoMode(QLineEdit.EchoMode.Password)
        token_row.addWidget(self.cfg_token, 1)
        self.btn_token_reveal = self._make_tool_button("Reveal")
        self.btn_token_reveal.setAccessibleName(tr("Reveal private token"))
        self.btn_token_reveal.clicked.connect(self._toggle_token_visible)
        token_row.addWidget(self.btn_token_reveal)
        btn_token_copy = self._make_tool_button("Copy")
        btn_token_copy.clicked.connect(self._copy_token)
        token_row.addWidget(btn_token_copy)
        btn_token_reset = self._make_tool_button("Regenerate", "danger")
        btn_token_reset.clicked.connect(self._regenerate_token)
        token_row.addWidget(btn_token_reset)
        conn_l.addLayout(token_row)
        conn_l.addWidget(make_divider())

        force_ip_row = QHBoxLayout()
        force_ip_copy = QVBoxLayout()
        force_ip_copy.setSpacing(2)
        force_ip_copy.addWidget(make_label("Force IP version", "fieldLabel"))
        force_ip_copy.addWidget(make_label(
            "Use IPv4 or IPv6 for every request. Off uses the system route.",
            "fieldHint", word_wrap=True,
        ))
        force_ip_row.addLayout(force_ip_copy, 1)
        self.cfg_force_ip_version = QComboBox()
        self.cfg_force_ip_version.setAccessibleName(tr("Force IP version"))
        self.cfg_force_ip_version.addItem(tr("Off"), "")
        self.cfg_force_ip_version.addItem(tr("IPv4"), "ipv4")
        self.cfg_force_ip_version.addItem(tr("IPv6"), "ipv6")
        force_ip = self._dependencies['normalize_force_ip_version'](
            self.config.get("ForceIPVersion", "")
        )
        restored_force_ip = self.cfg_force_ip_version.findData(force_ip)
        self.cfg_force_ip_version.setCurrentIndex(
            restored_force_ip if restored_force_ip >= 0 else 0
        )
        force_ip_row.addWidget(self.cfg_force_ip_version)
        conn_l.addLayout(force_ip_row)

        source_row = QHBoxLayout()
        source_copy = QVBoxLayout()
        source_copy.setSpacing(2)
        source_copy.addWidget(make_label("Source address", "fieldLabel"))
        source_copy.addWidget(make_label(
            "Bind requests to a local IPv4 or IPv6 address. Blank uses the system route.",
            "fieldHint", word_wrap=True,
        ))
        source_row.addLayout(source_copy, 1)
        self.cfg_source_address = QLineEdit(self.config.get("SourceAddress", ""))
        self.cfg_source_address.setAccessibleName(tr("Source address"))
        self.cfg_source_address.setPlaceholderText("192.0.2.10")
        self.cfg_source_address.setMinimumWidth(260)
        source_row.addWidget(self.cfg_source_address)
        conn_l.addLayout(source_row)

        xff_row = QHBoxLayout()
        xff_copy = QVBoxLayout()
        xff_copy.setSpacing(2)
        xff_copy.addWidget(make_label("Geo X-Forwarded-For", "fieldLabel"))
        xff_copy.addWidget(make_label(
            "Country code (US) or CIDR block for geo verification. Blank leaves it off.",
            "fieldHint", word_wrap=True,
        ))
        xff_row.addLayout(xff_copy, 1)
        self.cfg_xff = QLineEdit(self.config.get("Xff", ""))
        self.cfg_xff.setAccessibleName(tr("Geo X-Forwarded-For"))
        self.cfg_xff.setPlaceholderText("US or 203.0.113.0/24")
        self.cfg_xff.setMinimumWidth(260)
        xff_row.addWidget(self.cfg_xff)
        conn_l.addLayout(xff_row)

        geo_proxy_row = QHBoxLayout()
        geo_proxy_copy = QVBoxLayout()
        geo_proxy_copy.setSpacing(2)
        geo_proxy_copy.addWidget(make_label("Geo verification proxy", "fieldLabel"))
        geo_proxy_copy.addWidget(make_label(
            "Optional HTTP(S) or SOCKS proxy used only for region checks.",
            "fieldHint", word_wrap=True,
        ))
        geo_proxy_row.addLayout(geo_proxy_copy, 1)
        self.cfg_geo_verification_proxy = QLineEdit(
            self.config.get("GeoVerificationProxy", "")
        )
        self.cfg_geo_verification_proxy.setAccessibleName(tr("Geo verification proxy"))
        self.cfg_geo_verification_proxy.setPlaceholderText("https://proxy.example:8080")
        self.cfg_geo_verification_proxy.setMinimumWidth(260)
        geo_proxy_row.addWidget(self.cfg_geo_verification_proxy)
        conn_l.addLayout(geo_proxy_row)
        layout.addWidget(conn_card)

        # Site profiles. This is intentionally a bounded JSON editor rather
        # than a secret-bearing account form: names and defaults are portable,
        # while cookies and credentials stay in the per-site Sign-ins store.
        profiles_card, profiles_l = self._make_settings_group("Site profiles")
        profiles_l.addWidget(make_label("Named site profiles", "fieldLabel"))
        profiles_l.addWidget(make_label(
            "One JSON object per profile. Match a domain automatically, or "
            "choose a profile for one download in the paste box. Supported "
            "defaults include format, quality, proxy, impersonation and "
            "request pacing; do not put cookies or passwords here.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_site_profiles = QTextEdit()
        self.cfg_site_profiles.setAccessibleName(tr("Named site profiles"))
        self.cfg_site_profiles.setAcceptRichText(False)
        # Tab inserts a literal tab in a JSON editor by default. Settings is
        # a form, so hand the key to the next control instead of mutating the
        # document and trapping focus in this field.
        self.cfg_site_profiles.setTabChangesFocus(True)
        self.cfg_site_profiles.setMinimumHeight(170)
        self.cfg_site_profiles.setPlainText(json.dumps(
            self.config.get("SiteProfiles", []), indent=2, ensure_ascii=False
        ))
        profiles_l.addWidget(self.cfg_site_profiles)
        profiles_l.addWidget(make_label(
            'Example: [{"Name":"YouTube archive","Domain":"youtube.com",'
            '"VideoFormat":"mp4","Quality":"1080"}]',
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(profiles_card)

        # Storage
        paths_card, paths_l = self._make_settings_group("Storage")
        paths_l.addWidget(make_label("Video download folder", "fieldLabel"))
        paths_l.addWidget(make_label("Default destination for video downloads.", "fieldHint", word_wrap=True))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.cfg_dl_path = QLineEdit(self.config.get("DownloadPath", ""))
        self.cfg_dl_path.setAccessibleName(tr("Video download folder"))
        self.cfg_dl_path.setPlaceholderText(
            str(Path(default_download_path()) / "YouTube")
        )
        row.addWidget(self.cfg_dl_path, 1)
        btn = self._make_tool_button("Browse", target="Video download folder")
        btn.clicked.connect(lambda: self._browse(self.cfg_dl_path))
        row.addWidget(btn)
        paths_l.addLayout(row)
        paths_l.addWidget(make_divider())
        paths_l.addWidget(make_label("Audio download folder", "fieldLabel"))
        paths_l.addWidget(make_label("Leave blank to use the video folder.", "fieldHint", word_wrap=True))
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.cfg_audio_path = QLineEdit(self.config.get("AudioDownloadPath", ""))
        self.cfg_audio_path.setAccessibleName(tr("Audio download folder"))
        self.cfg_audio_path.setPlaceholderText(tr("Same as video folder"))
        row2.addWidget(self.cfg_audio_path, 1)
        btn2 = self._make_tool_button("Browse", target="Audio download folder")
        btn2.clicked.connect(lambda: self._browse(self.cfg_audio_path))
        row2.addWidget(btn2)
        paths_l.addLayout(row2)
        paths_l.addWidget(make_divider())
        retention_row = QHBoxLayout()
        retention_copy = QVBoxLayout()
        retention_copy.setSpacing(2)
        retention_copy.addWidget(make_label("History retention", "fieldLabel"))
        retention_copy.addWidget(make_label(
            "Maximum number of download records to keep locally. Files are never deleted.",
            "fieldHint", word_wrap=True,
        ))
        retention_row.addLayout(retention_copy, 1)
        self.cfg_history_retention = QSpinBox()
        self.cfg_history_retention.setAccessibleName(tr("History retention"))
        self.cfg_history_retention.setRange(
            self._value('HISTORY_RETENTION_MIN'),
            self._value('HISTORY_RETENTION_MAX'),
        )
        self.cfg_history_retention.setSuffix(tr(" entries"))
        self.cfg_history_retention.setValue(self._dependencies['clamp_int'](
            self.config.get("HistoryRetentionLimit"),
            self._value('HISTORY_RETENTION_DEFAULT'),
            self._value('HISTORY_RETENTION_MIN'),
            self._value('HISTORY_RETENTION_MAX'),
        ))
        self.cfg_history_retention.setFixedWidth(130)
        retention_row.addWidget(self.cfg_history_retention)
        paths_l.addLayout(retention_row)
        paths_l.addWidget(make_divider())
        paths_l.addWidget(make_label("Filename template", "fieldLabel"))
        paths_l.addWidget(make_label(
            "Optional yt-dlp output template, relative to the folder above "
            "(e.g. %(uploader)s/%(title)s.%(ext)s). Must keep %(ext)s. "
            "Title and channel fields are length-bounded on save so long "
            "titles cannot overrun the maximum path length. "
            "Blank uses the default.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_outtmpl = QLineEdit(self.config.get("OutputTemplate", ""))
        self.cfg_outtmpl.setAccessibleName(tr("Filename template"))
        self.cfg_outtmpl.setPlaceholderText("%(title)s.%(ext)s")
        paths_l.addWidget(self.cfg_outtmpl)
        self.outtmpl_preview = make_label("", "fieldHint", word_wrap=True)
        self.outtmpl_preview.setAccessibleName(tr("Filename template preview"))
        paths_l.addWidget(self.outtmpl_preview)
        self.cfg_windows_filenames = QCheckBox(tr("Use Windows-safe filenames"))
        self.cfg_windows_filenames.setToolTip(tr(
            "Ask yt-dlp to replace characters and names that Windows cannot store."
        ))
        self.cfg_windows_filenames.setChecked(
            self.config.get("WindowsFilenames", True)
        )
        paths_l.addWidget(self.cfg_windows_filenames)
        self.cfg_outtmpl.textChanged.connect(self._update_output_template_preview)
        self.cfg_dl_path.textChanged.connect(self._update_output_template_preview)
        self.cfg_windows_filenames.stateChanged.connect(
            self._update_output_template_preview
        )
        self._update_output_template_preview()
        layout.addWidget(paths_card)

        # Post-processing
        pp_card, pp_l = self._make_settings_group("Post-processing")
        self.cfg_metadata = QCheckBox(tr("Embed metadata"))
        self.cfg_metadata.setChecked(self.config.get("EmbedMetadata", True))
        self.cfg_thumbnail = QCheckBox(tr("Embed thumbnail"))
        self.cfg_thumbnail.setChecked(self.config.get("EmbedThumbnail", True))
        self.cfg_chapters = QCheckBox(tr("Embed chapters"))
        self.cfg_chapters.setChecked(self.config.get("EmbedChapters", True))
        self.cfg_subs = QCheckBox(tr("Download subtitles"))
        self.cfg_subs.setToolTip(tr(
            "Fetch subtitle tracks and embed them in the file. The Subtitles "
            "download type fetches them without the video."
        ))
        self.cfg_subs.setChecked(self.config.get("EmbedSubs", False))
        self.cfg_generate_subtitles = QCheckBox(
            tr("Generate local subtitles when no track exists")
        )
        self.cfg_generate_subtitles.setToolTip(tr(
            "After a video download, use the locally provisioned Whisper model "
            "to write an SRT sidecar only when yt-dlp found no subtitle track."
        ))
        self.cfg_generate_subtitles.setChecked(
            self.config.get("GenerateSubtitles", False)
        )
        self.generate_subtitles_hint = make_label(
            tr(
                "Uses the bundled multilingual Whisper model and the first "
                "language in Subtitle languages. Setup downloads the model "
                "when this option is enabled."
            ),
            "fieldHint", word_wrap=True,
        )
        self.cfg_keep_intermediates = QCheckBox(tr("Keep intermediate files"))
        self.cfg_keep_intermediates.setToolTip(tr(
            "Put .part, .f### and .ytdl files beside the output and keep them "
            "for diagnosis. Off by default: they use a private temporary "
            "folder and are removed after the download reaches a terminal state."
        ))
        self.cfg_keep_intermediates.setChecked(
            self.config.get("KeepIntermediateFiles", False))
        self.cfg_write_info = QCheckBox(tr("Write info JSON sidecar"))
        self.cfg_write_info.setChecked(self.config.get("WriteInfoJson", False))
        self.cfg_write_nfo = QCheckBox(tr("Write media-server NFO sidecar"))
        self.cfg_write_nfo.setToolTip(tr(
            "Write Kodi/Jellyfin-compatible NFO metadata beside downloaded "
            "media and create tvshow.nfo and season.nfo for channel folders."
        ))
        self.cfg_write_nfo.setChecked(self.config.get("WriteNfo", False))
        self.cfg_write_description = QCheckBox(tr("Write description sidecar"))
        self.cfg_write_description.setChecked(
            self.config.get("WriteDescription", False)
        )
        self.cfg_write_thumbnail = QCheckBox(tr("Write thumbnail sidecar"))
        self.cfg_write_thumbnail.setChecked(
            self.config.get("WriteThumbnail", False)
        )
        self.cfg_split_chapters = QCheckBox(tr("Split chapters into files"))
        self.cfg_split_chapters.setChecked(
            self.config.get("SplitChapters", False)
        )
        self.cfg_live_from_start = QCheckBox(tr("Start live streams from the beginning"))
        self.cfg_live_from_start.setChecked(
            self.config.get("LiveFromStart", False)
        )
        self.cfg_wait_for_video = QSpinBox()
        self.cfg_wait_for_video.setAccessibleName(tr("Live-video retry interval"))
        self.cfg_wait_for_video.setRange(0, 3600)
        self.cfg_wait_for_video.setSuffix(tr(" seconds"))
        self.cfg_wait_for_video.setValue(
            self._dependencies["clamp_int"](
                self.config.get("WaitForVideoSeconds", 0), 0, 0, 3600
            )
        )
        # cfg_keep_intermediates is added after the subtitle rows below: the
        # track, format and language controls belong directly under the
        # checkbox that turns them on, not separated from it.
        for w in [self.cfg_metadata, self.cfg_thumbnail, self.cfg_chapters,
                  self.cfg_subs, self.cfg_generate_subtitles]:
            pp_l.addWidget(w)
        pp_l.addWidget(self.generate_subtitles_hint)
        # Which of the two catalogues to ask for. Measured against the
        # installed yt-dlp: sending both flags never yields two files for one
        # language — the creator's track wins — so "both" is a preference,
        # not a duplicate, and the new capability is asking for one kind only.
        track_row = QHBoxLayout()
        track_row.setSpacing(8)
        track_row.addSpacing(28)
        track_row.addWidget(make_label("Tracks", "fieldHint"))
        self.cfg_subtitle_mode = QComboBox()
        self.cfg_subtitle_mode.setAccessibleName(tr("Subtitle tracks"))
        for label, value in (
            ("Creator, else auto-generated", "prefer-manual"),
            ("Creator only", "manual"),
            ("Auto-generated only", "auto"),
        ):
            self.cfg_subtitle_mode.addItem(tr(label), value)
        self.cfg_subtitle_mode.setCurrentIndex(max(0, self.cfg_subtitle_mode.findData(
            self._dependencies['normalize_subtitle_mode'](
                self.config.get("SubtitleMode")
            )
        )))
        track_row.addWidget(self.cfg_subtitle_mode)
        track_row.addSpacing(12)
        track_row.addWidget(make_label("Save as", "fieldHint"))
        self.cfg_subtitle_format = QComboBox()
        self.cfg_subtitle_format.setAccessibleName(tr("Subtitle format"))
        for label, value in (
            ("Same as source", ""), ("SRT", "srt"), ("WebVTT", "vtt"),
            ("ASS", "ass"), ("LRC", "lrc"),
        ):
            self.cfg_subtitle_format.addItem(tr(label), value)
        self.cfg_subtitle_format.setCurrentIndex(max(0, self.cfg_subtitle_format.findData(
            self._dependencies['normalize_subtitle_format'](
                self.config.get("SubtitleFormat")
            )
        )))
        track_row.addWidget(self.cfg_subtitle_format)
        track_row.addStretch()
        pp_l.addLayout(track_row)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addSpacing(28)
        sub_row.addWidget(make_label("Subtitle languages", "fieldHint"))
        self.cfg_sublangs = QLineEdit(self.config.get("SubLangs", "en"))
        self.cfg_sublangs.setAccessibleName(tr("Subtitle languages"))
        self.cfg_sublangs.setPlaceholderText("en,es")
        self.cfg_sublangs.setFixedWidth(140)
        self.cfg_sublangs.textEdited.connect(self._sync_sublang_checkboxes)
        sub_row.addWidget(self.cfg_sublangs)
        sub_row.addStretch()
        pp_l.addLayout(sub_row)
        subtitle_sleep_row = QHBoxLayout()
        subtitle_sleep_row.setSpacing(8)
        subtitle_sleep_row.addSpacing(28)
        subtitle_sleep_row.addWidget(make_label(
            "Pause between subtitle requests", "fieldHint"
        ))
        self.cfg_subtitle_sleep = QDoubleSpinBox()
        self.cfg_subtitle_sleep.setAccessibleName(
            tr("Pause between subtitle requests")
        )
        self.cfg_subtitle_sleep.setRange(0.0, 60.0)
        self.cfg_subtitle_sleep.setDecimals(2)
        self.cfg_subtitle_sleep.setSingleStep(0.5)
        self.cfg_subtitle_sleep.setSuffix(" s")
        self.cfg_subtitle_sleep.setSpecialValueText(tr("Off"))
        self.cfg_subtitle_sleep.setValue(float(
            self.config.get("SubtitleSleepSeconds", 1.0) or 0.0
        ))
        self.cfg_subtitle_sleep.setFixedWidth(100)
        subtitle_sleep_row.addWidget(self.cfg_subtitle_sleep)
        subtitle_sleep_row.addWidget(make_label(
            "Seconds between subtitle-track requests. Helps avoid subtitle "
            "rate limits; 0 disables it.",
            "fieldHint", word_wrap=True,
        ), 1)
        pp_l.addLayout(subtitle_sleep_row)
        # The field above still accepts any code yt-dlp knows; these are the
        # common ones, so picking two languages does not mean knowing that
        # Simplified Chinese is spelled zh-Hans. Three per row, because a
        # single long row of labels overflows at 900x620 with a large font.
        self._sublang_boxes = []
        lang_row = None
        for index, (label, code) in enumerate(SUBTITLE_LANGUAGE_CHOICES):
            if index % 3 == 0:
                lang_row = QHBoxLayout()
                lang_row.setSpacing(8)
                lang_row.addSpacing(28)
                pp_l.addLayout(lang_row)
            box = QCheckBox(tr(label))
            box.setAccessibleName(
                tr_format(
                    "{label}: {language}",
                    label=tr("Subtitle language"),
                    language=tr(label),
                )
            )
            box.toggled.connect(self._sublang_box_toggled)
            box._sublang_code = code
            self._sublang_boxes.append(box)
            lang_row.addWidget(box, 1)
        if lang_row is not None:
            for _ in range(-len(SUBTITLE_LANGUAGE_CHOICES) % 3):
                lang_row.addStretch(1)
        self._sync_sublang_checkboxes(self.cfg_sublangs.text())
        pp_l.addWidget(self.cfg_keep_intermediates)
        pp_l.addWidget(make_divider())
        pp_l.addWidget(make_label("Archive output", "fieldLabel"))
        pp_l.addWidget(make_label(
            "Optional sidecars, chapter splitting and live-event controls. "
            "These do not change the existing embed options.",
            "fieldHint", word_wrap=True,
        ))
        for w in (
            self.cfg_write_info, self.cfg_write_nfo, self.cfg_write_description,
            self.cfg_write_thumbnail, self.cfg_split_chapters,
            self.cfg_live_from_start,
        ):
            pp_l.addWidget(w)
        wait_row = QHBoxLayout()
        wait_row.setSpacing(8)
        wait_row.addSpacing(28)
        wait_row.addWidget(make_label("Live-video retry interval", "fieldHint"))
        wait_row.addWidget(self.cfg_wait_for_video)
        wait_row.addWidget(make_label(
            "0 disables live-event retries; otherwise yt-dlp retries at this interval within a bounded wait window.",
            "fieldHint", word_wrap=True,
        ), 1)
        pp_l.addLayout(wait_row)
        pp_l.addWidget(make_divider())
        self.cfg_sponsorblock = QCheckBox(tr("Use SponsorBlock segments"))
        self.cfg_sponsorblock.setChecked(self.config.get("SponsorBlock", False))
        sponsor_row = QHBoxLayout()
        sponsor_row.setSpacing(8)
        sponsor_row.addWidget(self.cfg_sponsorblock)
        self.sponsorblock_attribution = make_label(
            f'<a href="https://sponsor.ajay.app/">{tr("(Using SponsorBlock)")}</a>',
            "fieldHint",
        )
        self.sponsorblock_attribution.setTextFormat(Qt.TextFormat.RichText)
        self.sponsorblock_attribution.setOpenExternalLinks(True)
        self.sponsorblock_attribution.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        self.sponsorblock_attribution.setAccessibleName(
            tr("(Using SponsorBlock)")
        )
        sponsor_row.addWidget(self.sponsorblock_attribution)
        sponsor_row.addStretch()
        pp_l.addLayout(sponsor_row)
        pp_l.addWidget(make_label(
            tr(
                "SponsorBlock data and API are licensed CC BY-NC-SA 4.0; "
                "Astra Downloader is MIT."
            ),
            "fieldHint", word_wrap=True,
        ))
        sb_row = QHBoxLayout()
        sb_row.setSpacing(8)
        sb_row.addSpacing(28)
        sb_row.addWidget(make_label("Action", "fieldHint"))
        self.cfg_sb_action = QComboBox()
        self.cfg_sb_action.setAccessibleName(tr("SponsorBlock action"))
        self.cfg_sb_action.addItem(tr("Remove segments"), "remove")
        self.cfg_sb_action.addItem(tr("Mark segments"), "mark")
        current_action = self.config.get("SponsorBlockAction", "remove")
        self.cfg_sb_action.setCurrentIndex(1 if current_action == "mark" else 0)
        self.cfg_sb_action.setEnabled(self.cfg_sponsorblock.isChecked())
        self.cfg_sponsorblock.toggled.connect(self.cfg_sb_action.setEnabled)
        sb_row.addWidget(self.cfg_sb_action)
        sb_row.addStretch()
        pp_l.addLayout(sb_row)

        # Without a per-category choice the app sent the literal `all`, so
        # asking it to skip sponsors also removed intros, outros and self-promo.
        self.cfg_sb_categories = {}
        selected = set(
            self._dependencies['normalize_sponsorblock_categories'](
                self.config.get("SponsorBlockCategories", "")
            ).split(",")
        )
        category_labels = {
            "sponsor": "Sponsor", "intro": "Intro", "outro": "Outro",
            "selfpromo": "Self-promotion", "preview": "Recap or preview",
            "filler": "Filler", "interaction": "Interaction reminder",
            "music_offtopic": "Non-music section",
            "poi_highlight": "Highlight", "chapter": "Chapter",
        }
        category_grid = QVBoxLayout()
        category_grid.setSpacing(0)
        names = list(self._value('SPONSORBLOCK_CATEGORIES'))
        for start in range(0, len(names), 3):
            line = QHBoxLayout()
            line.setSpacing(10)
            line.addSpacing(28)
            for name in names[start:start + 3]:
                box = QCheckBox(tr(category_labels.get(name, name)))
                box.setChecked(name in selected)
                box.setEnabled(self.cfg_sponsorblock.isChecked())
                self.cfg_sponsorblock.toggled.connect(box.setEnabled)
                self.cfg_sb_categories[name] = box
                line.addWidget(box, 1)
            line.addStretch()
            category_grid.addLayout(line)
        pp_l.addLayout(category_grid)
        pp_l.addWidget(make_label(
            "With nothing ticked, every category is acted on.",
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(pp_card)

        # Format preferences. The container above is a hard constraint —
        # MP4 forces H.264 + AAC so an editor imports the result without
        # transcoding — and these order whatever that leaves open. Resolution
        # stays the primary axis; the quality picker owns it.
        fmt_card, fmt_l = self._make_settings_group("Format preferences")
        fmt_l.addWidget(make_label(
            "Preferences, not requirements: a link that has none of these "
            "still downloads. The MP4 container overrides them, because an "
            "editor-safe file is the point of choosing MP4.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_video_codec = self._add_format_preference(
            fmt_l, "Preferred video codec", "Preferred video codec",
            (
                (tr("No preference"), "auto"),
                ("H.264 (most compatible)", "h264"),
                ("VP9", "vp9"),
                ("AV1 (smallest)", "av1"),
            ),
            self.config.get("VideoCodecPreference", "auto"),
        )
        self.cfg_audio_codec = self._add_format_preference(
            fmt_l, "Preferred audio codec", "Preferred audio codec",
            (
                (tr("No preference"), "auto"),
                ("AAC (most compatible)", "aac"),
                ("Opus", "opus"),
            ),
            self.config.get("AudioCodecPreference", "auto"),
        )
        self.cfg_frame_rate = self._add_format_preference(
            fmt_l, "Preferred frame rate", "Preferred frame rate",
            (
                (tr("No preference"), 0),
                ("30 fps", 30),
                ("60 fps", 60),
            ),
            self._dependencies['clamp_int'](
                self.config.get("PreferredFrameRate", 0), 0, 0, 120),
        )
        fmt_l.addWidget(make_divider())
        self.cfg_prefer_original = QCheckBox(
            tr("Prefer the original upload over an AI upscale")
        )
        self.cfg_prefer_original.setToolTip(tr(
            "YouTube serves AI-upscaled copies that look higher-resolution "
            "than the creator's own file and sort above it. Try the genuine "
            "source first, and fall back to an upscale only when nothing "
            "else fits."
        ))
        self.cfg_prefer_original.setChecked(
            self.config.get("PreferOriginalOverUpscaled", True)
        )
        fmt_l.addWidget(self.cfg_prefer_original)
        layout.addWidget(fmt_card)

        # Playlist bounds. A pasted playlist otherwise queues everything it
        # contains; these apply only to a run that walks one.
        pl_card, pl_l = self._make_settings_group("Playlist limits")
        pl_l.addWidget(make_label(
            "These apply when you paste a playlist or channel. A single "
            "video is never filtered by them.",
            "fieldHint", word_wrap=True,
        ))
        self.cfg_playlist_max = self._add_settings_number(
            pl_l, "Maximum items",
            "Stop after this many items from one playlist. 0 takes all of them.",
            "Maximum playlist items", 0, 1000,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMaxItems", 0), 0, 0, 1000),
        )
        date_row = QHBoxLayout()
        date_copy = QVBoxLayout()
        date_copy.setSpacing(2)
        date_copy.addWidget(make_label("Uploaded after", "fieldLabel"))
        date_copy.addWidget(make_label(
            "A date as YYYYMMDD, or a relative one such as today-30days. "
            "Empty takes any date.", "fieldHint", word_wrap=True,
        ))
        date_row.addLayout(date_copy, 1)
        self.cfg_playlist_dateafter = QLineEdit(
            str(self.config.get("PlaylistDateAfter", "") or ""))
        self.cfg_playlist_dateafter.setAccessibleName(tr("Playlist uploaded after"))
        self.cfg_playlist_dateafter.setPlaceholderText("today-30days")
        self.cfg_playlist_dateafter.setFixedWidth(160)
        date_row.addWidget(self.cfg_playlist_dateafter)
        pl_l.addLayout(date_row)
        self.cfg_playlist_min_duration = self._add_settings_number(
            pl_l, "Shortest item (seconds)",
            "Skip items shorter than this, which is how a channel's shorts "
            "are left behind. 0 takes any length.",
            "Shortest playlist item in seconds", 0, 86400,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMinDurationSeconds", 0), 0, 0, 86400),
        )
        self.cfg_playlist_max_duration = self._add_settings_number(
            pl_l, "Longest item (seconds)",
            "Skip items longer than this, which is how multi-hour streams "
            "are left behind. 0 takes any length.",
            "Longest playlist item in seconds", 0, 86400,
            self._dependencies['clamp_int'](
                self.config.get("PlaylistMaxDurationSeconds", 0), 0, 0, 86400),
        )
        layout.addWidget(pl_card)

        # Performance
        perf_card, perf_l = self._make_settings_group("Performance")
        frag_row = QHBoxLayout()
        frag_copy = QVBoxLayout()
        frag_copy.setSpacing(2)
        frag_copy.addWidget(make_label("Concurrent fragments", "fieldLabel"))
        frag_copy.addWidget(make_label("More can improve fast connections.", "fieldHint", word_wrap=True))
        frag_row.addLayout(frag_copy, 1)
        self.cfg_fragments = QSpinBox()
        self.cfg_fragments.setAccessibleName(tr("Concurrent fragments"))
        self.cfg_fragments.setRange(1, 32)
        self.cfg_fragments.setValue(self._dependencies['clamp_int'](self.config.get("ConcurrentFragments", 4), 4, 1, 32))
        self.cfg_fragments.setFixedWidth(86)
        frag_row.addWidget(self.cfg_fragments)
        perf_l.addLayout(frag_row)
        perf_l.addWidget(make_divider())

        conc_row = QHBoxLayout()
        conc_copy = QVBoxLayout()
        conc_copy.setSpacing(2)
        conc_copy.addWidget(make_label("Simultaneous downloads", "fieldLabel"))
        conc_copy.addWidget(make_label("How many downloads run at once.", "fieldHint", word_wrap=True))
        conc_row.addLayout(conc_copy, 1)
        self.cfg_maxconcurrent = QSpinBox()
        self.cfg_maxconcurrent.setAccessibleName(tr("Simultaneous downloads"))
        self.cfg_maxconcurrent.setRange(1, 10)
        self.cfg_maxconcurrent.setValue(self._dependencies['clamp_int'](self.config.get("MaxConcurrentDownloads", 3), 3, 1, 10))
        self.cfg_maxconcurrent.setFixedWidth(86)
        conc_row.addWidget(self.cfg_maxconcurrent)
        perf_l.addLayout(conc_row)
        perf_l.addWidget(make_divider())

        retries_row = QHBoxLayout()
        retries_copy = QVBoxLayout()
        retries_copy.setSpacing(2)
        retries_copy.addWidget(make_label("Download retries", "fieldLabel"))
        retries_copy.addWidget(make_label("Retry attempts on transient network errors.", "fieldHint", word_wrap=True))
        retries_row.addLayout(retries_copy, 1)
        self.cfg_retries = QSpinBox()
        self.cfg_retries.setAccessibleName(tr("Download retries"))
        self.cfg_retries.setRange(0, 50)
        self.cfg_retries.setValue(self._dependencies['clamp_int'](self.config.get("DownloadRetries", 10), 10, 0, 50))
        self.cfg_retries.setFixedWidth(86)
        retries_row.addWidget(self.cfg_retries)
        perf_l.addLayout(retries_row)
        perf_l.addWidget(make_divider())
        rate_row = QHBoxLayout()
        rate_copy = QVBoxLayout()
        rate_copy.setSpacing(2)
        rate_copy.addWidget(make_label("Rate limit", "fieldLabel"))
        rate_copy.addWidget(make_label("Optional, such as 500K or 2M.", "fieldHint", word_wrap=True))
        rate_row.addLayout(rate_copy, 1)
        self.cfg_ratelimit = QLineEdit(self.config.get("RateLimit", ""))
        self.cfg_ratelimit.setAccessibleName(tr("Rate limit"))
        self.cfg_ratelimit.setPlaceholderText(tr("No limit"))
        self.cfg_ratelimit.setFixedWidth(120)
        rate_row.addWidget(self.cfg_ratelimit)
        perf_l.addLayout(rate_row)
        perf_l.addWidget(make_divider())
        throttle_row = QHBoxLayout()
        throttle_copy = QVBoxLayout()
        throttle_copy.setSpacing(2)
        throttle_copy.addWidget(make_label("Throttle floor", "fieldLabel"))
        throttle_copy.addWidget(make_label(
            "Below this rate the server is assumed to be throttling and the "
            "video is re-extracted. Empty disables it.",
            "fieldHint", word_wrap=True,
        ))
        throttle_row.addLayout(throttle_copy, 1)
        self.cfg_throttled = QLineEdit(self.config.get("ThrottledRate", ""))
        self.cfg_throttled.setAccessibleName(tr("Throttle floor"))
        self.cfg_throttled.setPlaceholderText(tr("Off"))
        self.cfg_throttled.setFixedWidth(120)
        throttle_row.addWidget(self.cfg_throttled)
        perf_l.addLayout(throttle_row)
        perf_l.addWidget(make_divider())
        socket_row = QHBoxLayout()
        socket_copy = QVBoxLayout()
        socket_copy.setSpacing(2)
        socket_copy.addWidget(make_label("Socket timeout", "fieldLabel"))
        socket_copy.addWidget(make_label(
            "Seconds before a stalled connection is abandoned. 0 uses yt-dlp's "
            "own default.", "fieldHint", word_wrap=True,
        ))
        socket_row.addLayout(socket_copy, 1)
        self.cfg_socket_timeout = QSpinBox()
        self.cfg_socket_timeout.setAccessibleName(tr("Socket timeout in seconds"))
        self.cfg_socket_timeout.setRange(0, 300)
        self.cfg_socket_timeout.setValue(self._dependencies['clamp_int'](
            self.config.get("SocketTimeoutSeconds", 0), 0, 0, 300))
        self.cfg_socket_timeout.setFixedWidth(86)
        socket_row.addWidget(self.cfg_socket_timeout)
        perf_l.addLayout(socket_row)
        perf_l.addWidget(make_divider())
        extractor_row = QHBoxLayout()
        extractor_copy = QVBoxLayout()
        extractor_copy.setSpacing(2)
        extractor_copy.addWidget(make_label("Extractor retries", "fieldLabel"))
        extractor_copy.addWidget(make_label(
            "Retries while reading the page, before any transfer starts. "
            "0 uses yt-dlp's own default.", "fieldHint", word_wrap=True,
        ))
        extractor_row.addLayout(extractor_copy, 1)
        self.cfg_extractor_retries = QSpinBox()
        self.cfg_extractor_retries.setAccessibleName(tr("Extractor retries"))
        self.cfg_extractor_retries.setRange(0, 20)
        self.cfg_extractor_retries.setValue(self._dependencies['clamp_int'](
            self.config.get("ExtractorRetries", 0), 0, 0, 20))
        self.cfg_extractor_retries.setFixedWidth(86)
        extractor_row.addWidget(self.cfg_extractor_retries)
        perf_l.addLayout(extractor_row)
        perf_l.addWidget(make_divider())
        self.cfg_verify_formats = QCheckBox(tr("Verify formats before downloading"))
        self.cfg_verify_formats.setToolTip(tr(
            "Check that a chosen format can actually be downloaded before "
            "committing to it. Costs an extra request per candidate format."
        ))
        self.cfg_verify_formats.setChecked(self.config.get("VerifyFormats", False))
        perf_l.addWidget(self.cfg_verify_formats)
        perf_l.addWidget(make_divider())
        pace_row = QHBoxLayout()
        pace_copy = QVBoxLayout()
        pace_copy.setSpacing(2)
        pace_copy.addWidget(make_label("Pause between downloads", "fieldLabel"))
        pace_copy.addWidget(make_label(
            "Seconds to wait before each download. A bandwidth cap does not "
            "prevent an HTTP 429; spacing the requests does. 0 disables it.",
            "fieldHint", word_wrap=True,
        ))
        pace_row.addLayout(pace_copy, 1)
        self.cfg_sleep_interval = QSpinBox()
        self.cfg_sleep_interval.setAccessibleName(tr("Pause between downloads in seconds"))
        self.cfg_sleep_interval.setRange(0, 600)
        self.cfg_sleep_interval.setValue(self._dependencies['clamp_int'](
            self.config.get("SleepIntervalSeconds", 0), 0, 0, 600))
        self.cfg_sleep_interval.setFixedWidth(86)
        pace_row.addWidget(self.cfg_sleep_interval)
        perf_l.addLayout(pace_row)
        pace_max_row = QHBoxLayout()
        pace_max_copy = QVBoxLayout()
        pace_max_copy.setSpacing(2)
        pace_max_copy.addWidget(make_label("Longest pause", "fieldLabel"))
        pace_max_copy.addWidget(make_label(
            "Upper bound when the pause is randomised. Ignored below the "
            "pause above.", "fieldHint", word_wrap=True,
        ))
        pace_max_row.addLayout(pace_max_copy, 1)
        self.cfg_sleep_max = QSpinBox()
        self.cfg_sleep_max.setAccessibleName(tr("Longest pause in seconds"))
        self.cfg_sleep_max.setRange(0, 600)
        self.cfg_sleep_max.setValue(self._dependencies['clamp_int'](
            self.config.get("MaxSleepIntervalSeconds", 0), 0, 0, 600))
        self.cfg_sleep_max.setFixedWidth(86)
        pace_max_row.addWidget(self.cfg_sleep_max)
        perf_l.addLayout(pace_max_row)
        pace_jitter_row = QHBoxLayout()
        pace_jitter_copy = QVBoxLayout()
        pace_jitter_copy.setSpacing(2)
        pace_jitter_copy.addWidget(make_label("Pacing jitter", "fieldLabel"))
        pace_jitter_copy.addWidget(make_label(
            "Randomise host wait times and yt-dlp pacing by ± this percentage. "
            "0 keeps fixed timing.", "fieldHint", word_wrap=True,
        ))
        pace_jitter_row.addLayout(pace_jitter_copy, 1)
        self.cfg_pacing_jitter = QSpinBox()
        self.cfg_pacing_jitter.setAccessibleName(tr("Pacing jitter percentage"))
        self.cfg_pacing_jitter.setRange(0, 100)
        self.cfg_pacing_jitter.setSuffix("%")
        self.cfg_pacing_jitter.setSpecialValueText(tr("Off"))
        self.cfg_pacing_jitter.setValue(self._dependencies['clamp_int'](
            self.config.get("PacingJitterPercent", 0), 0, 0, 100))
        self.cfg_pacing_jitter.setFixedWidth(86)
        pace_jitter_row.addWidget(self.cfg_pacing_jitter)
        perf_l.addLayout(pace_jitter_row)
        pace_req_row = QHBoxLayout()
        pace_req_copy = QVBoxLayout()
        pace_req_copy.setSpacing(2)
        pace_req_copy.addWidget(make_label("Pause between requests", "fieldLabel"))
        pace_req_copy.addWidget(make_label(
            "Seconds between the data requests inside one download.",
            "fieldHint", word_wrap=True,
        ))
        pace_req_row.addLayout(pace_req_copy, 1)
        self.cfg_sleep_requests = QSpinBox()
        self.cfg_sleep_requests.setAccessibleName(tr("Pause between requests in seconds"))
        self.cfg_sleep_requests.setRange(0, 60)
        self.cfg_sleep_requests.setValue(self._dependencies['clamp_int'](
            self.config.get("SleepRequestsSeconds", 0), 0, 0, 60))
        self.cfg_sleep_requests.setFixedWidth(86)
        pace_req_row.addWidget(self.cfg_sleep_requests)
        perf_l.addLayout(pace_req_row)
        self.pacing_guidance = QLabel()
        self.pacing_guidance.setTextFormat(Qt.TextFormat.RichText)
        self.pacing_guidance.setOpenExternalLinks(True)
        self.pacing_guidance.setWordWrap(True)
        self.pacing_guidance.setProperty("class", "settingsStatus")
        self.pacing_guidance.setProperty("tone", "neutral")
        self.pacing_guidance.setAccessibleName(tr("YouTube pacing guidance"))
        perf_l.addWidget(self.pacing_guidance)
        for control in (
            self.cfg_maxconcurrent,
            self.cfg_sleep_interval,
            self.cfg_sleep_max,
            self.cfg_pacing_jitter,
            self.cfg_sleep_requests,
        ):
            control.valueChanged.connect(self._update_pacing_guidance)
        self._update_pacing_guidance()
        perf_l.addWidget(make_divider())
        # MaxFileSizeMB blocks downloads outright — a run that trips it exits
        # cleanly having written nothing and reports `skipped`, whose message
        # tells the user to change this. It needs a control to change.
        maxsize_row = QHBoxLayout()
        maxsize_copy = QVBoxLayout()
        maxsize_copy.setSpacing(2)
        maxsize_copy.addWidget(make_label("Max file size", "fieldLabel"))
        maxsize_copy.addWidget(make_label(
            "Skip anything larger. 0 means no limit.", "fieldHint", word_wrap=True
        ))
        maxsize_row.addLayout(maxsize_copy, 1)
        self.cfg_maxsize = QSpinBox()
        self.cfg_maxsize.setAccessibleName(tr("Max file size in megabytes"))
        self.cfg_maxsize.setRange(0, 102400)
        self.cfg_maxsize.setSuffix(" MB")
        self.cfg_maxsize.setSpecialValueText(tr("No limit"))
        self.cfg_maxsize.setValue(self._dependencies['clamp_int'](
            self.config.get("MaxFileSizeMB", 0), 0, 0, 102400
        ))
        self.cfg_maxsize.setFixedWidth(120)
        maxsize_row.addWidget(self.cfg_maxsize)
        perf_l.addLayout(maxsize_row)
        proxy_row = QHBoxLayout()
        proxy_copy = QVBoxLayout()
        proxy_copy.setSpacing(2)
        proxy_copy.addWidget(make_label("Proxy", "fieldLabel"))
        proxy_copy.addWidget(make_label("Optional HTTP(S) or SOCKS proxy.", "fieldHint", word_wrap=True))
        proxy_row.addLayout(proxy_copy, 1)
        self.cfg_proxy = QLineEdit(self.config.get("Proxy", ""))
        self.cfg_proxy.setAccessibleName(tr("Proxy"))
        self.cfg_proxy.setPlaceholderText("https://proxy.example:8080")
        self.cfg_proxy.setMinimumWidth(260)
        proxy_row.addWidget(self.cfg_proxy)
        perf_l.addLayout(proxy_row)
        self.cfg_use_system_proxy = QCheckBox(
            tr("Use the proxy Windows is configured with")
        )
        self.cfg_use_system_proxy.setChecked(
            bool(self.config.get("UseSystemProxy", False))
        )
        self.cfg_use_system_proxy.setAccessibleName(tr("Use the system proxy"))
        self.cfg_use_system_proxy.setToolTip(tr(
            "Reads the proxy from Windows Internet Settings. A proxy typed "
            "above always wins."
        ))
        self.cfg_use_system_proxy.toggled.connect(self._sync_system_proxy_hint)
        self.cfg_proxy.textChanged.connect(self._sync_system_proxy_hint)
        perf_l.addWidget(self.cfg_use_system_proxy)
        # The detected value is shown before the setting is saved: "use the
        # system proxy" is otherwise a switch whose effect the user cannot see
        # until a download fails.
        self.cfg_system_proxy_hint = make_label("", "fieldHint", word_wrap=True)
        self.cfg_system_proxy_hint.setAccessibleName(tr("Detected system proxy"))
        perf_l.addWidget(self.cfg_system_proxy_hint)
        self._sync_system_proxy_hint()
        # Impersonation. Built from what the installed binary reports, because
        # yt-dlp aborts the download outright on an unknown target.
        impersonate_row = QHBoxLayout()
        impersonate_copy = QVBoxLayout()
        impersonate_copy.setSpacing(2)
        impersonate_copy.addWidget(make_label("Imitate a browser", "fieldLabel"))
        impersonate_copy.addWidget(make_label(
            "Sends a real browser's TLS fingerprint. The usual fix for a site "
            "that returns 403, though it can itself trigger rate limiting.",
            "fieldHint", word_wrap=True,
        ))
        impersonate_row.addLayout(impersonate_copy, 1)
        self.cfg_impersonate = QComboBox()
        self.cfg_impersonate.setAccessibleName(tr("Imitate a browser"))
        self.cfg_impersonate.addItem(tr("Off"), "")
        configured = self._dependencies['normalize_impersonate_target'](
            self.config.get("ImpersonateTarget", ""))
        self._configured_impersonate_target = configured
        self.cfg_impersonate.addItem(
            tr("Checking installed yt-dlp…"),
            "__impersonate_pending__",
        )
        if configured:
            self.cfg_impersonate.addItem(configured, configured)
        restored = self.cfg_impersonate.findData(configured)
        self.cfg_impersonate.setCurrentIndex(restored if restored >= 0 else 0)
        impersonate_row.addWidget(self.cfg_impersonate)
        perf_l.addLayout(impersonate_row)
        perf_l.addWidget(make_divider())
        runtime_row = QHBoxLayout()
        runtime_copy = QVBoxLayout()
        runtime_copy.setSpacing(2)
        runtime_copy.addWidget(make_label("JavaScript runtime", "fieldLabel"))
        runtime_copy.addWidget(make_label(
            "Auto prefers Deno, then Node 22+, then the QuickJS runtime the "
            "app downloads for itself (2 MB).",
            "fieldHint", word_wrap=True,
        ))
        runtime_row.addLayout(runtime_copy, 1)
        self.cfg_js_runtime = QComboBox()
        self.cfg_js_runtime.setAccessibleName(tr("JavaScript runtime"))
        self.cfg_js_runtime.addItem(tr("Auto"), "auto")
        self.cfg_js_runtime.addItem(tr("Deno"), "deno")
        self.cfg_js_runtime.addItem(tr("Node 22+"), "node")
        self.cfg_js_runtime.addItem(tr("QuickJS"), "quickjs")
        selected_runtime = self.config.get("JavaScriptRuntime", "auto")
        self.cfg_js_runtime.setCurrentIndex(max(0, self.cfg_js_runtime.findData(selected_runtime)))
        runtime_row.addWidget(self.cfg_js_runtime)
        perf_l.addLayout(runtime_row)
        perf_l.addWidget(make_divider())
        channel_row = QHBoxLayout()
        channel_copy = QVBoxLayout()
        channel_copy.setSpacing(2)
        channel_copy.addWidget(make_label("yt-dlp update channel", "fieldLabel"))
        channel_copy.addWidget(make_label(
            "Nightly ships same-day YouTube fixes; stable lags by weeks.",
            "fieldHint", word_wrap=True,
        ))
        channel_row.addLayout(channel_copy, 1)
        self.cfg_ytdlp_channel = QComboBox()
        self.cfg_ytdlp_channel.setAccessibleName(tr("yt-dlp update channel"))
        self.cfg_ytdlp_channel.addItem(tr("Nightly (recommended)"), "nightly")
        self.cfg_ytdlp_channel.addItem(tr("Stable"), "stable")
        selected_channel = self.config.get("YtDlpUpdateChannel", "nightly")
        self.cfg_ytdlp_channel.setCurrentIndex(max(0, self.cfg_ytdlp_channel.findData(selected_channel)))
        channel_row.addWidget(self.cfg_ytdlp_channel)
        perf_l.addLayout(channel_row)
        layout.addWidget(perf_card)

        # Appearance and language
        language_card, language_l = self._make_settings_group("Appearance and language")
        theme_row = QHBoxLayout()
        theme_row.addWidget(make_label("Theme", "fieldLabel"))
        theme_row.addStretch()
        self.cfg_theme = QComboBox()
        self.cfg_theme.setAccessibleName(tr("Theme"))
        self.cfg_theme.addItem(tr("System default"), "system")
        self.cfg_theme.addItem(tr("Dark"), "dark")
        self.cfg_theme.addItem(tr("Light"), "light")
        selected_theme = self.config.get("Theme", "system")
        self.cfg_theme.setCurrentIndex(
            max(0, self.cfg_theme.findData(selected_theme))
        )
        self.cfg_theme.setToolTip(
            tr("System default follows the operating system appearance.")
        )
        theme_row.addWidget(self.cfg_theme)
        language_l.addLayout(theme_row)
        language_row = QHBoxLayout()
        language_row.addWidget(make_label("Language", "fieldLabel"))
        language_row.addStretch()
        self.cfg_language = QComboBox()
        self.cfg_language.setAccessibleName(tr("Companion language"))
        self.cfg_language.addItem(tr("System default"), "system")
        language_labels = {"de": "Deutsch", "en": "English"}
        for value in ADVERTISED_LOCALES:
            self.cfg_language.addItem(language_labels.get(value, value), value)
        selected_language = self.config.get("Language", "system")
        self.cfg_language.setCurrentIndex(
            max(0, self.cfg_language.findData(selected_language))
        )
        self.cfg_language.setToolTip(
            tr(
                "Language changes apply the next time Astra Downloader starts."
            )
        )
        language_row.addWidget(self.cfg_language)
        language_l.addLayout(language_row)
        language_l.addWidget(make_label(
            "Language changes apply after restarting Astra Downloader.",
            "fieldHint", word_wrap=True,
        ))
        layout.addWidget(language_card)

        # Window and tray
        beh_card, beh_l = self._make_settings_group("Window and tray")
        self.cfg_closetotray = QCheckBox(tr("Close to the system tray"))
        self.cfg_closetotray.setChecked(self.config.get("CloseToTray", True))
        self.cfg_startmin = QCheckBox(tr("Start minimized to the tray"))
        self.cfg_startmin.setChecked(self.config.get("StartMinimized", False))
        self.cfg_notify = QCheckBox(tr("Notify when a download finishes (while minimized)"))
        self.cfg_notify.setChecked(self.config.get("NotifyOnComplete", True))
        self.cfg_clipboard = QCheckBox(tr("Stage copied video links for review"))
        self.cfg_clipboard.setChecked(self.config.get("ClipboardLinkGrabber", False))
        self.cfg_clipboard.setToolTip(
            tr(
                "Watch clipboard changes for video links from any supported site. "
                "Matching links fill the Quick download field but are never "
                "downloaded until you confirm."
            )
        )
        self.cfg_clipboard.setAccessibleDescription(
            tr(
                "Off by default. Clipboard content that does not look like a video "
                "link is ignored, and a matching link is staged without starting a "
                "download."
            )
        )
        for w in [
            self.cfg_closetotray, self.cfg_startmin, self.cfg_notify,
        ]:
            beh_l.addWidget(w)
        layout.addWidget(beh_card)

        # Clipboard staging fills the Quick download field; it is a download
        # behaviour, not something the tray does.
        clip_card, clip_l = self._make_settings_group("Clipboard")
        clip_l.addWidget(self.cfg_clipboard)
        layout.addWidget(clip_card)

        # Tools — v1.2.0 downloader-maintenance actions
        tools_card, tools_l = self._make_settings_group("Maintenance")
        self.cfg_autoupdate = QCheckBox(tr("Keep yt-dlp up to date automatically"))
        self.cfg_autoupdate.setChecked(self.config.get("AutoUpdateYtDlp", True))
        # The real cadence: throttled to once per 12 hours, checked when the
        # server starts and again whenever the download queue goes idle (the
        # race-free moment to swap the binary).
        self.cfg_autoupdate.setToolTip(tr(
            "Checks at most once every 12 hours, when the server starts and "
            "when the download queue goes idle."
        ))
        tools_l.addWidget(self.cfg_autoupdate)
        tools_l.addWidget(make_label("Installed tools", "fieldLabel"))
        self.tools_status = make_label("Checking installed tools…", "fieldHint", word_wrap=True, status=True)
        self.tools_status.setAccessibleName(tr("Installed tools status"))
        tools_l.addWidget(self.tools_status)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        self.btn_check_updates = self._make_tool_button(
            "Check for yt-dlp updates",
        )
        self.btn_check_updates.setToolTip(
            tr("Check for a yt-dlp update. Active downloads must finish first.")
        )
        self.btn_check_updates.clicked.connect(self._force_ytdlp_update)
        tools_row.addWidget(self.btn_check_updates)
        btn_reinstall_ffmpeg = self._make_tool_button(
            "Reinstall ffmpeg", "danger",
        )
        # _reinstall_ffmpeg stages and verifies a fresh copy first; nothing is
        # deleted unless the replacement verifies.
        btn_reinstall_ffmpeg.setToolTip(tr(
            "Download a fresh ffmpeg and verify its checksum. The installed copy "
            "stays in place until the replacement verifies."
        ))
        btn_reinstall_ffmpeg.clicked.connect(self._reinstall_ffmpeg)
        tools_row.addWidget(btn_reinstall_ffmpeg)
        tools_row.addStretch()
        tools_l.addLayout(tools_row)
        tools_l.addWidget(make_divider())
        tools_l.addWidget(make_label("Version pins", "fieldLabel"))
        tools_l.addWidget(make_label(
            "An update keeps downloads working and can also take away "
            "something that was working, such as a hardware encoder. Pin a "
            "tool to hold it at the version installed now. Roll back puts the "
            "previous copy back and pins there.",
            "fieldHint", word_wrap=True,
        ))
        # Deliberately not named cfg_*: the settings reload gate treats every
        # cfg_ widget as a form field belonging to _SETTINGS_FORM_FIELDS, and
        # these are live state with their own buttons, not a saved form.
        self.managed_pin_rows = {}
        for name in self._value('MANAGED_BINARY_NAMES'):
            pin_row = QHBoxLayout()
            pin_row.setSpacing(8)
            title = make_label(name, "fieldLabel")
            title.setMinimumWidth(72)
            pin_row.addWidget(title)
            installed = make_label("", "fieldHint")
            installed.setMinimumWidth(150)
            pin_row.addWidget(installed, 1)
            field = QLineEdit()
            field.setPlaceholderText(tr("Not pinned"))
            field.setAccessibleName(
                tr_format("Pinned version for {tool}", tool=name)
            )
            field.setMaximumWidth(200)
            pin_row.addWidget(field)
            pin_button = self._make_tool_button("Pin", "ghost", name)
            pin_button.clicked.connect(
                lambda _checked=False, tool=name: self._apply_managed_binary_pin(tool)
            )
            pin_row.addWidget(pin_button)
            rollback_button = self._make_tool_button("Roll back", "ghost", name)
            rollback_button.clicked.connect(
                lambda _checked=False, tool=name: self._roll_back_managed_binary(tool)
            )
            rollback_button.setEnabled(False)
            pin_row.addWidget(rollback_button)
            self.managed_pin_rows[name] = {
                "installed": installed,
                "field": field,
                "pin": pin_button,
                "rollback": rollback_button,
            }
            tools_l.addLayout(pin_row)
        self.managed_pin_status = make_label("", "fieldHint", word_wrap=True, status=True)
        self.managed_pin_status.setAccessibleName(tr("Version pin result"))
        tools_l.addWidget(self.managed_pin_status)
        transfer_card, transfer_l = self._make_settings_group("Import and export")
        transfer_l.addWidget(make_label(
            "Move this install to another machine, or recover from a config "
            "you cannot open. The bundle carries settings and subscriptions. "
            "Stored sign-ins are listed by site but never exported. "
            "Cookies stay on this machine.",
            "fieldHint", word_wrap=True,
        ))
        bundle_row = QHBoxLayout()
        bundle_row.setSpacing(8)
        self.btn_export_settings = self._make_tool_button("Export settings")
        self.btn_export_settings.setToolTip(tr(
            "Write settings and subscriptions to a JSON bundle."
        ))
        self.btn_export_settings.clicked.connect(self._export_settings_bundle)
        bundle_row.addWidget(self.btn_export_settings)
        self.btn_import_settings = self._make_tool_button("Import settings")
        self.btn_import_settings.setToolTip(tr(
            "Read a bundle written by Export settings and apply it."
        ))
        self.btn_import_settings.clicked.connect(self._import_settings_bundle)
        bundle_row.addWidget(self.btn_import_settings)
        self.btn_undo_settings_import = self._make_tool_button(
            "Undo import", "ghost"
        )
        self.btn_undo_settings_import.setToolTip(tr(
            "Restore settings and subscriptions changed by the last import."
        ))
        self.btn_undo_settings_import.clicked.connect(self._undo_settings_import)
        self._set_settings_filter_hidden(self.btn_undo_settings_import, True)
        bundle_row.addWidget(self.btn_undo_settings_import)
        bundle_row.addStretch()
        transfer_l.addLayout(bundle_row)
        layout.addWidget(tools_card)
        layout.addWidget(transfer_card)

        save_bar = QFrame()
        save_bar.setProperty("class", "settingsSaveBar")
        save_row = QHBoxLayout(save_bar)
        save_row.setContentsMargins(38, 12, 30, 12)
        save_row.setSpacing(8)
        self.settings_status = make_label("", "settingsStatus", status=True)
        self.settings_status.setAccessibleName(tr("Settings status"))
        save_row.addWidget(self.settings_status, 1)
        btn_save = self._make_tool_button("Save changes", "primary")
        btn_save.clicked.connect(self._save_settings)
        self.btn_save = btn_save
        save_row.addWidget(btn_save)
        self.btn_restore_defaults = self._make_tool_button(
            "Restore defaults", "ghost"
        )
        self.btn_restore_defaults.setToolTip(tr(
            "Restore the editable settings to their shipped defaults."
        ))
        self.btn_restore_defaults.clicked.connect(self._restore_default_settings)
        save_row.addWidget(self.btn_restore_defaults)
        self.btn_undo_restore_defaults = self._make_tool_button(
            "Undo defaults", "ghost"
        )
        self.btn_undo_restore_defaults.setToolTip(tr(
            "Restore the settings from before Restore defaults was used."
        ))
        self.btn_undo_restore_defaults.clicked.connect(
            self._undo_restore_defaults
        )
        self._set_settings_filter_hidden(self.btn_undo_restore_defaults, True)
        save_row.addWidget(self.btn_undo_restore_defaults)
        layout.addStretch()
        root_layout.addWidget(save_bar)

        for signal in self._settings_change_signals():
            signal.connect(self._mark_settings_dirty)
        self._filter_settings("")

        self.tabs.addTab(root, tr("Settings"))
