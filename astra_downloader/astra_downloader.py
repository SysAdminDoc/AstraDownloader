#!/usr/bin/env python3
"""
Astra Downloader — Desktop GUI + HTTP API server for Astra Deck.
Manages yt-dlp downloads with a PyQt6 GUI, system tray, and REST API on port 9751.

First run auto-downloads yt-dlp + ffmpeg. No separate installer needed.
"""

import sys, os, json, time, re, uuid, subprocess, threading, socket, shutil, traceback, hmac, hashlib, struct, math, stat
import queue
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

# The pinned yt-dlp (2026.7.4) requires Python 3.11; on 3.10 the install of
# requirements.txt fails before this guard would ever run, so the guard has to
# agree with the pin or it explains nothing. Packaged builds carry their own
# interpreter and build.py already restricts them to 3.11 and 3.12.
_MIN_PYTHON = (3, 11)
if sys.version_info < _MIN_PYTHON:
    sys.stderr.write(
        f"[Astra Downloader] Python {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}+ "
        f"required (you're on "
        f"{sys.version_info.major}.{sys.version_info.minor}). yt-dlp "
        f"raised its minimum to Python 3.11 in release 2026.07.04.\n"
    )
    sys.exit(1)

# Source imports are deliberately side-effect free: dependency installation is
# an explicit virtual-environment setup step, never an import-time mutation.
REQUIREMENTS_PATH = Path(__file__).with_name("requirements.txt")


def source_dependency_error(error):
    missing = getattr(error, "name", None) or type(error).__name__
    return (
        f"Astra Downloader source dependencies are missing or unusable ({missing}). "
        "The application will not install packages during import. Create a virtual "
        "environment with `py -3.12 -m venv .venv`, then run "
        f"`.\\.venv\\Scripts\\python.exe -m pip install --require-virtualenv -r \"{REQUIREMENTS_PATH}\"`."
    )


try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QTabWidget, QScrollArea, QFrame, QCheckBox, QLineEdit,
        QFileDialog, QSystemTrayIcon, QMenu, QProgressBar, QTextEdit,
        QSpinBox, QComboBox, QGraphicsOpacityEffect, QStyle, QDialog,
        QDialogButtonBox
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QSize, QPropertyAnimation, QEasingCurve
    from PyQt6.QtGui import QIcon, QFont, QTextCursor
    import requests as http_requests
except ImportError as exc:
    raise ImportError(source_dependency_error(exc)) from exc

try:
    from .routes import (
        RateLimiter, _ServerAdapter, _build_wsgi_server,
        create_api as _owned_create_api,
    )
    from .config import (
        DEFAULT_CONFIG, CONFIG_SCHEMA_VERSION, ConfigStore, DOWNLOAD_REQUEST_ALLOWED_FIELDS,
        DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS,
        HISTORY_RETENTION_DEFAULT, HISTORY_RETENTION_MIN, HISTORY_RETENTION_MAX,
        HistoryStore, PORT_FALLBACKS, SERVER_PORT,
        default_download_path,
        allowed_output_roots, atomic_write_json, backup_corrupt_file, clamp_int,
        MEDIA_HOST_HINTS, MEDIA_URL_BLOCK_MESSAGES,
        clean_path_text, clean_text, coerce_bool, describe_media_url_block,
        is_supported_media_url, load_json_file, looks_like_media_link,
        media_url_block_reason,
        normalize_download_section, normalize_playlist_items, normalize_output_dir,
        normalize_output_template, normalize_proxy,
        output_template_preview,
        normalize_force_ip_version, normalize_source_address, normalize_xff,
        validate_site_profiles,
        normalize_rate_limit, normalize_sponsorblock_categories,
        normalize_playlist_date,
        normalize_impersonate_target,
        normalize_sublangs, normalize_subtitle_format, normalize_subtitle_mode,
        SUBTITLE_MODES, SUBTITLE_FORMATS, JAVASCRIPT_RUNTIME_CHOICES,
        build_settings_bundle, read_settings_bundle, describe_bundle_changes,
        SETTINGS_BUNDLE_SCHEMA, SETTINGS_BUNDLE_VERSION, BUNDLE_EXCLUDED_SETTINGS,
        normalize_url, sanitize_config,
        SPONSORBLOCK_CATEGORIES,
        FORMAT_SORT_VIDEO_CODECS, FORMAT_SORT_AUDIO_CODECS,
        FORMAT_SORT_FRAME_RATES,
        lookup_history_url, query_history_entries, sanitize_history_entries,
        quarantined_state_files, restore_quarantined_file,
        validate_download_request_body,
    )
    from .download import (
        ALLOWED_COOKIE_DOMAINS, DOWNLOAD_ACTIVE_STATES, DOWNLOAD_FAILURE_RECOVERY,
        DOWNLOAD_PENDING_STATES, DOWNLOAD_RETRYABLE_ERROR_CODES,
        DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES,
        DOWNLOAD_RUNNING_STATES, DOWNLOAD_STALL_TIMEOUT_SECONDS,
        DOWNLOAD_INTERMEDIATE_DIRNAME,
        DOWNLOAD_TERMINAL_STATES, DOWNLOAD_WATCHDOG_POLL_SECONDS,
        DOWNLOAD_QUEUE_SCHEMA_VERSION, MAX_CONCURRENT, MAX_QUEUED_TOTAL,
        HOST_BACKOFF_BASE_SECONDS, HOST_BACKOFF_MAX_SECONDS,
        HOST_BACKOFF_MAX_ENTRIES, parse_retry_after_seconds,
        MAX_SITE_LOGIN_COOKIES, MAX_SITE_LOGIN_TEXT_BYTES, MAX_SITE_LOGINS,
        PLAYLIST_PREVIEW_LIMIT,
        SITE_LOGIN_BROWSERS, SITE_LOGIN_DIRNAME, SITE_LOGIN_INDEX_NAME,
        SITE_LOGIN_TEST_TIMEOUT_SECONDS,
        SiteLoginStore,
        build_browser_cookie_args,
        cookie_domain_in_site, describe_browser_cookie_failure,
        describe_browser_cookie_readiness,
        parse_netscape_cookies, registrable_domain, site_login_key,
        select_site_profile,
        Download, DownloadManagerCore,
        DownloadQueueStore, YTDLPActivityRegistry,
        PO_PROVIDER_NUDGE, PO_PROVIDER_NUDGE_CODES, po_provider_nudge_advice,
        apply_download_failure_classification, build_video_format_args,
        build_format_sort_args,
        check_download_disk_space, estimate_download_bytes,
        RESUME_ROLLBACK_FIELDS, RETRY_ROLLBACK_FIELDS,
        snapshot_download_fields, restore_download_fields,
        build_playlist_bound_args,
        build_impersonate_args,
        build_network_workaround_args,
        build_subtitle_args,
        build_local_subtitle_args, local_subtitle_output_path,
        build_whisper_audio_args, build_whisper_transcription_args,
        local_subtitle_sidecar_exists, should_generate_local_subtitles,
        subtitle_language_for_transcription, escape_ffmpeg_filter_value,
        build_media_server_nfo, build_tvshow_nfo, build_season_nfo,
        write_media_server_nfo, write_media_server_sidecars,
        NFO_MAX_TEXT_CHARS,
        parse_whisper_progress, TRANSCRIPTION_WAV_BYTES_PER_SECOND,
        TRANSCRIPTION_FALLBACK_DURATION_SECONDS, estimate_transcription_wav_bytes,
        SUBTITLE_WRITE_FLAGS, SUBTITLE_CONVERT_FORMATS, SUBTITLE_WRITTEN_RE,
        FORMAT_SORT_VIDEO_FIELDS, FORMAT_SORT_AUDIO_FIELDS,
        build_subprocess_env as _owned_build_subprocess_env,
        classify_download_failure, summarize_ytdlp_formats, summarize_ytdlp_playlist,
        cleanup_stale_cookie_jars as _owned_cleanup_stale_cookie_jars,
        download_error_payload, is_playlist_url,
        QUALITY_LADDER, probed_video_heights, quality_choices_for_heights,
        SABR_LIMITED_NOTICE, describe_sabr_voided_options, sabr_only_formats,
        terminate_process_tree as _owned_terminate_process_tree,
        write_cookies_netscape as _owned_write_cookies_netscape,
    )
    from .health import (
        DENO_MIN_VERSION, NODE_MIN_VERSION,
        QUICKJS_MIN_VERSION, JS_RUNTIMES,
        ExecutableVersionProbe, FfmpegCapabilitiesProbe,
        ImpersonateTargetsProbe, parse_impersonate_targets,
        YTDLP_EXTERNAL_RUNTIME_CUTOFF,
        _compare_semver, _parse_ytdlp_release_date, evaluate_sabr_support,
        _run_captured as _owned_run_captured,
        build_javascript_runtime_args, build_youtube_extractor_args,
        evaluate_javascript_runtime as _owned_evaluate_javascript_runtime,
        is_youtube_url,
        MANAGED_BINARY_ANTIVIRUS_ADVICE, MANAGED_BINARY_MIN_BYTES,
        managed_binary_state, managed_binary_usable,
        javascript_runtime_supported as _owned_javascript_runtime_supported,
        parse_ffmpeg_major, parse_ffmpeg_snapshot_date, parse_ffmpeg_version_output,
        parse_javascript_runtime_version as _owned_parse_javascript_runtime_version,
        parse_ytdlp_version_output,
        probe_whisper_runtime,
        probe_javascript_execution as _owned_probe_javascript_execution,
        ytdlp_needs_external_runtime, missing_ffmpeg_filters,
        REQUIRED_FFMPEG_FILTERS, evaluate_preflight_checks,
    )
    from .i18n import (
        SUPPORTED_LOCALES, install_companion_translator,
        normalize_companion_locale,
    )
    from .subscriptions import (
        SUBSCRIPTION_MAX_INTERVAL_MINUTES,
        SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS,
        SUBSCRIPTION_RETRY_BASE_SECONDS,
        SUBSCRIPTION_MIN_INTERVAL_MINUTES,
        SUBSCRIPTION_SCHEMA_VERSION,
        SubscriptionManager,
        SubscriptionStore,
        normalize_subscription_candidate,
        subscription_archive_key,
    )
    from .gui import (
        FolderPickerService as _OwnedFolderPickerService,
        MainWindowCore,
        ReadinessProbe as _OwnedReadinessProbe,
        SetupWorkerCore,
        download_status_tone, format_duration, human_status, make_card,
        make_divider, make_empty_state, make_label, make_line_icon,
        make_section_label, make_stat, make_status_badge, refresh_line_icons,
        set_gui_theme, set_line_icon, repolish,
    )
except ImportError:  # Direct script / flat source-path compatibility.
    from routes import (
        RateLimiter, _ServerAdapter, _build_wsgi_server,
        create_api as _owned_create_api,
    )
    from config import (
        DEFAULT_CONFIG, CONFIG_SCHEMA_VERSION, ConfigStore, DOWNLOAD_REQUEST_ALLOWED_FIELDS,
        DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS,
        HISTORY_RETENTION_DEFAULT, HISTORY_RETENTION_MIN, HISTORY_RETENTION_MAX,
        HistoryStore, PORT_FALLBACKS, SERVER_PORT,
        default_download_path,
        allowed_output_roots, atomic_write_json, backup_corrupt_file, clamp_int,
        MEDIA_HOST_HINTS, MEDIA_URL_BLOCK_MESSAGES,
        clean_path_text, clean_text, coerce_bool, describe_media_url_block,
        is_supported_media_url, load_json_file, looks_like_media_link,
        media_url_block_reason,
        normalize_download_section, normalize_playlist_items, normalize_output_dir,
        normalize_output_template, normalize_proxy,
        output_template_preview,
        normalize_force_ip_version, normalize_source_address, normalize_xff,
        validate_site_profiles,
        normalize_rate_limit, normalize_sponsorblock_categories,
        normalize_playlist_date,
        normalize_impersonate_target,
        normalize_sublangs, normalize_subtitle_format, normalize_subtitle_mode,
        SUBTITLE_MODES, SUBTITLE_FORMATS, JAVASCRIPT_RUNTIME_CHOICES,
        build_settings_bundle, read_settings_bundle, describe_bundle_changes,
        SETTINGS_BUNDLE_SCHEMA, SETTINGS_BUNDLE_VERSION, BUNDLE_EXCLUDED_SETTINGS,
        normalize_url, sanitize_config,
        SPONSORBLOCK_CATEGORIES,
        FORMAT_SORT_VIDEO_CODECS, FORMAT_SORT_AUDIO_CODECS,
        FORMAT_SORT_FRAME_RATES,
        lookup_history_url, query_history_entries, sanitize_history_entries,
        quarantined_state_files, restore_quarantined_file,
        validate_download_request_body,
    )
    from download import (
        ALLOWED_COOKIE_DOMAINS, DOWNLOAD_ACTIVE_STATES, DOWNLOAD_FAILURE_RECOVERY,
        DOWNLOAD_PENDING_STATES, DOWNLOAD_RETRYABLE_ERROR_CODES,
        DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES,
        DOWNLOAD_RUNNING_STATES, DOWNLOAD_STALL_TIMEOUT_SECONDS,
        DOWNLOAD_INTERMEDIATE_DIRNAME,
        DOWNLOAD_TERMINAL_STATES, DOWNLOAD_WATCHDOG_POLL_SECONDS,
        DOWNLOAD_QUEUE_SCHEMA_VERSION, MAX_CONCURRENT, MAX_QUEUED_TOTAL,
        HOST_BACKOFF_BASE_SECONDS, HOST_BACKOFF_MAX_SECONDS,
        HOST_BACKOFF_MAX_ENTRIES, parse_retry_after_seconds,
        MAX_SITE_LOGIN_COOKIES, MAX_SITE_LOGIN_TEXT_BYTES, MAX_SITE_LOGINS,
        PLAYLIST_PREVIEW_LIMIT,
        SITE_LOGIN_BROWSERS, SITE_LOGIN_DIRNAME, SITE_LOGIN_INDEX_NAME,
        SITE_LOGIN_TEST_TIMEOUT_SECONDS,
        SiteLoginStore,
        build_browser_cookie_args,
        cookie_domain_in_site, describe_browser_cookie_failure,
        describe_browser_cookie_readiness,
        parse_netscape_cookies, registrable_domain, site_login_key,
        select_site_profile,
        Download, DownloadManagerCore,
        DownloadQueueStore, YTDLPActivityRegistry,
        PO_PROVIDER_NUDGE, PO_PROVIDER_NUDGE_CODES, po_provider_nudge_advice,
        apply_download_failure_classification, build_video_format_args,
        build_format_sort_args,
        check_download_disk_space, estimate_download_bytes,
        RESUME_ROLLBACK_FIELDS, RETRY_ROLLBACK_FIELDS,
        snapshot_download_fields, restore_download_fields,
        build_playlist_bound_args,
        build_impersonate_args,
        build_network_workaround_args,
        build_subtitle_args,
        build_local_subtitle_args, local_subtitle_output_path,
        build_whisper_audio_args, build_whisper_transcription_args,
        local_subtitle_sidecar_exists, should_generate_local_subtitles,
        subtitle_language_for_transcription, escape_ffmpeg_filter_value,
        build_media_server_nfo, build_tvshow_nfo, build_season_nfo,
        write_media_server_nfo, write_media_server_sidecars,
        NFO_MAX_TEXT_CHARS,
        parse_whisper_progress, TRANSCRIPTION_WAV_BYTES_PER_SECOND,
        TRANSCRIPTION_FALLBACK_DURATION_SECONDS, estimate_transcription_wav_bytes,
        SUBTITLE_WRITE_FLAGS, SUBTITLE_CONVERT_FORMATS, SUBTITLE_WRITTEN_RE,
        FORMAT_SORT_VIDEO_FIELDS, FORMAT_SORT_AUDIO_FIELDS,
        build_subprocess_env as _owned_build_subprocess_env,
        classify_download_failure, summarize_ytdlp_formats, summarize_ytdlp_playlist,
        cleanup_stale_cookie_jars as _owned_cleanup_stale_cookie_jars,
        download_error_payload, is_playlist_url,
        QUALITY_LADDER, probed_video_heights, quality_choices_for_heights,
        SABR_LIMITED_NOTICE, describe_sabr_voided_options, sabr_only_formats,
        terminate_process_tree as _owned_terminate_process_tree,
        write_cookies_netscape as _owned_write_cookies_netscape,
    )
    from health import (
        DENO_MIN_VERSION, NODE_MIN_VERSION,
        QUICKJS_MIN_VERSION, JS_RUNTIMES,
        ExecutableVersionProbe, FfmpegCapabilitiesProbe,
        ImpersonateTargetsProbe, parse_impersonate_targets,
        YTDLP_EXTERNAL_RUNTIME_CUTOFF,
        _compare_semver, _parse_ytdlp_release_date, evaluate_sabr_support,
        _run_captured as _owned_run_captured,
        build_javascript_runtime_args, build_youtube_extractor_args,
        evaluate_javascript_runtime as _owned_evaluate_javascript_runtime,
        is_youtube_url,
        MANAGED_BINARY_ANTIVIRUS_ADVICE, MANAGED_BINARY_MIN_BYTES,
        managed_binary_state, managed_binary_usable,
        javascript_runtime_supported as _owned_javascript_runtime_supported,
        parse_ffmpeg_major, parse_ffmpeg_snapshot_date, parse_ffmpeg_version_output,
        parse_javascript_runtime_version as _owned_parse_javascript_runtime_version,
        parse_ytdlp_version_output,
        probe_whisper_runtime,
        probe_javascript_execution as _owned_probe_javascript_execution,
        ytdlp_needs_external_runtime, missing_ffmpeg_filters,
        REQUIRED_FFMPEG_FILTERS, evaluate_preflight_checks,
    )
    from i18n import (
        SUPPORTED_LOCALES, install_companion_translator,
        normalize_companion_locale,
    )
    from subscriptions import (
        SUBSCRIPTION_MAX_INTERVAL_MINUTES,
        SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS,
        SUBSCRIPTION_RETRY_BASE_SECONDS,
        SUBSCRIPTION_MIN_INTERVAL_MINUTES,
        SUBSCRIPTION_SCHEMA_VERSION,
        SubscriptionManager,
        SubscriptionStore,
        normalize_subscription_candidate,
        subscription_archive_key,
    )
    from gui import (
        FolderPickerService as _OwnedFolderPickerService,
        MainWindowCore,
        ReadinessProbe as _OwnedReadinessProbe,
        SetupWorkerCore,
        download_status_tone, format_duration, human_status, make_card,
        make_divider, make_empty_state, make_label, make_line_icon,
        make_section_label, make_stat, make_status_badge, refresh_line_icons,
        set_gui_theme, set_line_icon, repolish,
    )

# ══════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════
APP_NAME = "Astra Downloader"
APP_VERSION = "2.6.0"
PORTABLE_MARKER_NAME = ".astradownloader-portable"
INSTANCE_CONTROL_PORT_DEFAULT = 9752
INSTANCE_LOCK_PORT_DEFAULT = 9753


def default_install_dir(localappdata=None):
    """Return the per-user install/state root used by packaged launches."""
    base = localappdata
    if base is None:
        base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = Path.home() / "AppData" / "Local"
    return Path(base) / "AstraDownloader"


def _launch_executable_path(executable=None):
    if executable is not None:
        return Path(executable).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def portable_marker_path(executable=None):
    return _launch_executable_path(executable).parent / PORTABLE_MARKER_NAME


def _path_is_within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def portable_mode_requested(argv=None, *, executable=None, install_dir=None,
                            frozen=None):
    """Return whether this launch must keep application state beside itself.

    A packaged one-folder distribution carries ``PORTABLE_MARKER_NAME`` beside
    its executable. The marker is ignored inside the managed install root so a
    copied or unpacked install cannot accidentally switch another install to a
    portable state root. ``--portable`` remains an explicit override for a
    one-file copy; ``--install`` is the corresponding installed-mode override.
    Source runs retain their historical AppData default unless explicitly
    requested portable.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    normalized_args = {str(arg).strip().lower() for arg in args}
    if "--install" in normalized_args:
        return False
    if any(str(arg).strip().lower() == "--portable" for arg in args):
        return True
    if str(os.environ.get("ASTRA_PORTABLE", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return False
    executable_path = _launch_executable_path(executable)
    managed_root = Path(install_dir or default_install_dir()).resolve()
    return (
        not _path_is_within(executable_path.parent, managed_root)
        and portable_marker_path(executable_path).is_file()
    )


def runtime_state_dir(portable=None):
    """Choose the state root without letting a portable launch touch AppData."""
    if portable is None:
        portable = PORTABLE_MODE
    if portable:
        return _launch_executable_path().parent
    return default_install_dir()


def instance_ports_for_root(root, installed_root=None):
    """Return deterministic control/lock ports isolated by the state root."""
    resolved = Path(root).resolve()
    managed_root = Path(installed_root or default_install_dir()).resolve()
    if resolved == managed_root:
        return INSTANCE_CONTROL_PORT_DEFAULT, INSTANCE_LOCK_PORT_DEFAULT
    digest = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).digest()
    base = 20000 + (int.from_bytes(digest[:4], "big") % 20000)
    if base % 2:
        base += 1
    return base, base + 1


def instance_namespace_for_root(root=None):
    """Return the stable suffix used by the per-root instance mutex."""
    resolved = Path(root or INSTALL_DIR).resolve()
    managed_root = Path(default_install_dir()).resolve()
    if resolved == managed_root:
        return "installed"
    return hashlib.sha256(
        os.path.normcase(str(resolved)).encode("utf-8")
    ).hexdigest()[:16]


PORTABLE_MODE = portable_mode_requested()
SERVICE_ID = "astra-downloader"
# SERVICE_API_VERSION is the wire-schema version. 1.2.0 adds /health fields
# (ytDlpVersion, ffmpegVersion, rateLimit); 1.4.0 adds the compatibility
# /health.poTokenProvider field; 1.5.0 adds
# /health.denoRuntime for the external JS runtime that yt-dlp >= 2026.04
# requires on YouTube extractions. Older clients ignore unknown keys, so
# the major version stays at 2 (additive, backward-compatible).
SERVICE_API_VERSION = 2
INSTANCE_CONTROL_HOST = '127.0.0.1'
DIAGNOSTIC_LOG_ENTRY_LIMIT = 30
DIAGNOSTIC_TEXT_LIMIT = 600
# Stall watchdog for the download subprocess. `for line in proc.stdout` blocks
# forever if yt-dlp wedges on a dead socket — there is no other timeout on the
# download path, so a hung process permanently consumes one of MAX_CONCURRENT
# slots and leaks an OS process. A download making any progress streams output
# constantly (resetting the timer), so only a genuinely wedged process — zero
# output for this long — is killed. Deliberately generous so a slow ffmpeg merge
# of a large file (which can be silent for minutes) is never false-killed.
INSTALL_DIR = runtime_state_dir()
INSTANCE_CONTROL_PORT, INSTANCE_LOCK_PORT = instance_ports_for_root(INSTALL_DIR)
CONFIG_PATH = INSTALL_DIR / 'config.json'
HISTORY_PATH = INSTALL_DIR / 'history.json'
DOWNLOAD_QUEUE_PATH = INSTALL_DIR / 'download-queue.json'
SUBSCRIPTIONS_PATH = INSTALL_DIR / 'subscriptions.json'
LOG_PATH = INSTALL_DIR / 'server.log'
CRASH_LOG_PATH = INSTALL_DIR / 'crash.log'
YTDLP_PATH = INSTALL_DIR / 'yt-dlp.exe'
FFMPEG_PATH = INSTALL_DIR / 'ffmpeg.exe'
WHISPER_MODEL_NAME = 'ggml-tiny-q5_1.bin'
WHISPER_MODEL_PATH = INSTALL_DIR / WHISPER_MODEL_NAME
# The multilingual tiny quantized model keeps the opt-in feature practical
# on CPU-only machines while covering languages beyond English. The size floor
# is intentionally much higher than the helper-executable floor: a truncated
# model can look present and fail only after a user waits for transcription.
WHISPER_MODEL_MIN_BYTES = 16 * 1024 * 1024
# Hugging Face's ``main`` branch is mutable. Pin the model to the reviewed
# repository revision so the digest and the bytes fetched by setup cannot
# silently drift between releases.
WHISPER_MODEL_REVISION = '5359861c739e955e79d9a303bcbc70fb988958b1'
WHISPER_MODEL_URL = (
    'https://huggingface.co/ggerganov/whisper.cpp/resolve/'
    f'{WHISPER_MODEL_REVISION}/'
    f'{WHISPER_MODEL_NAME}?download=true'
)
WHISPER_MODEL_SHA256 = (
    '818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7'
)
# FFmpeg-Builds removed its Whisper filter from the security-floor archive.
# Keep the media tool on that floor and provision the small, CPU-only
# whisper.cpp CLI separately instead. The release asset is pinned by both tag
# and digest; the archive contains the CLI and its colocated DLLs.
WHISPER_BIN_VERSION = '1.9.1'
WHISPER_BIN_DIR = INSTALL_DIR / 'whisper'
WHISPER_BIN_PATH = WHISPER_BIN_DIR / 'whisper-cli.exe'
WHISPER_BIN_MIN_BYTES = 128 * 1024
WHISPER_BIN_URL = (
    'https://github.com/ggml-org/whisper.cpp/releases/download/'
    f'v{WHISPER_BIN_VERSION}/whisper-bin-x64.zip'
)
WHISPER_BIN_SHA256 = (
    '7d8be46ecd31828e1eb7a2ecdd0d6b314feafd82163038ab6092594b0a063539'
)
ICON_PATH = INSTALL_DIR / 'AstraDownloader.ico'
# Scheduled subscriptions keep their archive in the schema-checked
# subscriptions.json document. Normal downloads still always re-run.

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
DENO_DIR = INSTALL_DIR / 'deno'
DENO_PATH = DENO_DIR / 'deno.exe'
NATIVE_HOST_DIR = INSTALL_DIR / 'native-hosts'
DEFAULT_FIREFOX_EXTENSION_IDS = ("ytkit@sysadmindoc.github.io",)
# Chromium-family browsers all read a Chrome-style ``allowed_origins`` host
# manifest, but each browser has its own per-user HKCU registry root.
CHROMIUM_NATIVE_MESSAGING_REGISTRY_ROOTS = (
    'Software\\Google\\Chrome\\NativeMessagingHosts',
    'Software\\Microsoft\\Edge\\NativeMessagingHosts',
    'Software\\BraveSoftware\\Brave-Browser\\NativeMessagingHosts',
    'Software\\Vivaldi\\NativeMessagingHosts',
    'Software\\Opera Software\\Opera Stable\\NativeMessagingHosts',
    'Software\\Chromium\\NativeMessagingHosts',
)
FIREFOX_NATIVE_MESSAGING_REGISTRY_ROOT = (
    'Software\\Mozilla\\NativeMessagingHosts'
)
# Chrome extension IDs are hashes encoded in exactly 32 characters from a-p.
# Gecko IDs are commonly email-shaped, but may also be generated opaque IDs;
# reject separators, control characters, and URL-like values without imposing
# Chrome's alphabet on Firefox.
CHROME_EXTENSION_ID_RE = re.compile(r'^[a-p]{32}$')
FIREFOX_EXTENSION_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._%+@-]{0,127}$')
DENO_ZIP_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
DENO_SHA256_URL = DENO_ZIP_URL + ".sha256sum"
DENO_SHA256_ASSET = Path(urlparse(DENO_ZIP_URL).path).name
# QuickJS, the fallback runtime. yt-dlp accepts deno, node, quickjs and bun;
# quickjs is by far the smallest, which is what makes it the one this app can
# fetch on its own rather than telling the user to go and install something.
#
# Pinned to an exact release with the digest in source rather than fetched
# from a sidecar: quickjs-ng publishes no checksum asset, and a digest that
# ships with the code cannot be moved by whoever controls the release.
# Verified 2026-08-06 against yt-dlp 2026.08.04 — a real YouTube download
# completes with quickjs as the only enabled runtime.
QUICKJS_VERSION = "0.16.1"
QUICKJS_DIR = INSTALL_DIR / 'quickjs'
QUICKJS_PATH = QUICKJS_DIR / 'qjs.exe'
QUICKJS_EXE_URL = (
    "https://github.com/quickjs-ng/quickjs/releases/download/"
    f"v{QUICKJS_VERSION}/qjs-windows-x86_64.exe"
)
QUICKJS_SHA256 = "55a1b69cd4fdb6b0d3f8fdd910d0e89519f5330e408462084140c7b3b964fdae"
ICON_URL = "https://raw.githubusercontent.com/SysAdminDoc/AstraDownloader/main/AstraDownloader.ico"
# The published Release is the only thing an update can actually install, so it
# is also what decides whether one is available. Reading `main` meant a version
# bump with no published release drove the update logic (branch trust).
COMPANION_UPDATE_RELEASE_API_URL = "https://api.github.com/repos/SysAdminDoc/AstraDownloader/releases/latest"
COMPANION_UPDATE_VERSION_URL_TEMPLATE = "https://raw.githubusercontent.com/SysAdminDoc/AstraDownloader/{tag}/astra_downloader/astra_downloader.py"
COMPANION_UPDATE_EXE_URL = "https://github.com/SysAdminDoc/AstraDownloader/releases/latest/download/AstraDownloader.exe"
COMPANION_UPDATE_SHA256_URL = "https://github.com/SysAdminDoc/AstraDownloader/releases/latest/download/AstraDownloader.exe.sha256"
# The release check already talks to GitHub anonymously. Keep the most recent
# rate-limit headers so the readiness panel can name an exhausted API budget
# without adding another network request to every /health poll.
_GITHUB_API_BUDGET_LOCK = threading.Lock()
_GITHUB_API_BUDGET = {
    'remaining': None,
    'limit': None,
    'resetAt': None,
    'source': 'not-observed',
}
COMPANION_UPDATE_TIMEOUT_SECONDS = 120
COMPANION_UPDATE_MIN_BYTES = 1024
COMPANION_VERSION_SOURCE_MAX_BYTES = 256 * 1024
YTDLP_ROLLBACK_FILENAME = '.yt-dlp.last-known-good.exe'
COMPANION_ROLLBACK_FILENAME = '.AstraDownloader.last-known-good.exe'
# Hard ceiling for any single helper download (companion exe, yt-dlp, ffmpeg
# zip, icon). The largest legitimate asset (the ffmpeg archive) is well under
# 200 MB; a misbehaving CDN, truncating proxy, or endless redirect body must
# not be able to fill the disk before the SHA-256 check ever runs.
HELPER_DOWNLOAD_MAX_BYTES = 500 * 1024 * 1024  # 500 MB
# Checksum sidecars should contain only a small text manifest.  Bound these
# separately from binary downloads so a compromised mirror cannot make the
# process allocate an arbitrarily large response before verification begins.
CHECKSUM_SIDECAR_MAX_BYTES = 64 * 1024  # 64 KiB


# v1.2.0: rate-limit for /download. Token-bucket sliding window — tuned so a
# legitimate user spamming the download button hits MAX_CONCURRENT long before
# this kicks in, but a compromised extension can't queue 10k /download calls
# in a burst.
RATE_LIMIT_DOWNLOAD_MAX = 30
RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS = 60
RATE_LIMIT_PICKFOLDER_MAX = 5
RATE_LIMIT_PICKFOLDER_WINDOW_SECONDS = 60
# Health is read-only, but it still runs executable capability probes. Keep a
# small polling budget so a local client cannot turn a cold cache into a probe
# storm while normal extension polling remains comfortably below the ceiling.
RATE_LIMIT_HEALTH_MAX = 30
RATE_LIMIT_HEALTH_WINDOW_SECONDS = 60
# Companion release checks hit both GitHub's API and a raw source endpoint.
# Keep a small legitimate retry allowance while preventing a broken release
# from turning one impatient click into a repeated multi-megabyte download.
RATE_LIMIT_UPDATE_MAX = 3
RATE_LIMIT_UPDATE_WINDOW_SECONDS = 60
COMPANION_UPDATE_FAILURE_BACKOFF_SECONDS = 300
# Scheduled scans only need the newest bounded window. The archive store is
# the authority for dedupe; this cap keeps one slow channel from monopolizing
# a waitress worker or filling the local state document.
SUBSCRIPTION_PROBE_LIMIT = 50
SUBSCRIPTION_PROBE_TIMEOUT_SECONDS = 60
# v1.2.0: CORS preflight cache horizon — keeps browsers from re-asking OPTIONS
# for every POST /download during a multi-video session.
CORS_MAX_AGE_SECONDS = 600
# v1.5.1 / RESEARCH_FEATURE_PLAN EI12: bounds on the HTTP surface so the
# Flask process can't be OOM'd by either side of an oversized payload.
#
# Incoming: 1 MB caps the body of POST /download / /config / /pick-folder.
# Real payloads are <2 KB (a yt-dlp URL + flags); 1 MB is a generous
# defensive margin that still blocks "POST a 1 GB blob" memory blowups.
# Flask honours this via app.config['MAX_CONTENT_LENGTH'] and emits 413
# itself before any handler sees the body.
#
# Outgoing: 10 MB caps the jsonify'd payload from cors_response. /history
# already caps to 500 entries (each ~500 bytes), /health is small,
# /config is bounded — but a future endpoint that streams logs or
# format-listings could blow past. cors_response checks the serialised
# body length and swaps oversized payloads for a 413 error response so
# the wire never carries the bloated content.
MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
# v1.2.0: upstream publishes per-release checksum sidecars. Executable helper
# downloads must fail closed when their sidecar is missing or malformed; using
# an unverified yt-dlp/ffmpeg binary is worse than a blocked first-run setup.
YTDLP_SHA256_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"
YTDLP_SHA256_ASSET = "yt-dlp.exe"
FFMPEG_SHA256_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/checksums.sha256"
FFMPEG_SHA256_ASSET = Path(urlparse(FFMPEG_URL).path).name
# v1.2.0: stamp we write under HKCU so shortcut/protocol/task/uninstall
# registration is skipped on subsequent launches at the same version.
INTEGRATIONS_STAMP_KEY = r'Software\Classes\AstraDownloader'
INTEGRATIONS_STAMP_VALUE = 'IntegrationsVersion'

# v1.4.0 (N1): the old bgutil-ytdlp-pot-provider integration is retained only
# as a compatibility-shaped health field. yt-dlp is always launched with
# --no-plugin-dirs, so no external plugin can affect a download. The actual
# path is the verified token-exempt client chain in health.py; advertising a
# reachable bgutil process as usable would be misleading.
PO_TOKEN_PROVIDER_PROBE_TIMEOUT = 1.0

# yt-dlp >= 2026.04 ships an `external n/sig solver` for YouTube
# (upstream PR #14157). Without an installed JavaScript runtime — Deno is
# the documented option — the `web` and `web_safari` clients return empty
# format lists on a growing share of videos. The /health endpoint surfaces
# Deno presence so the downloadHealthPanel can render a "Deno: missing"
# pill when the bundled yt-dlp.exe is recent enough to need it but Deno
# is absent from the system PATH.
#
# Cutoff is the first nightly that flipped the dep from optional to
# load-bearing — pinned conservatively at 2026.04.01 so newer-than-cutoff
# yt-dlps are flagged; older ones (the in-field-stable pre-Deno line)
# don't false-positive on a misconfigured PATH.
DENO_RUNTIME_PROBE_TIMEOUT = 1.5
_DENO_RUNTIME_CACHE_TTL_SECONDS = 60
JS_RUNTIME_CAPABILITY_MARKER = "ASTRA_EJS_RUNTIME_OK"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
MAX_TEXT_FIELD = 500
MAX_PATH_FIELD = 2048
LOG_MAX_BYTES = 1024 * 1024
_LOG_LOCK = threading.Lock()
# One source: the ring has to hold at least what a diagnostics bundle claims
# to include, or the bundle quietly ships fewer entries than it advertises.
_LOG_RING_MAX = DIAGNOSTIC_LOG_ENTRY_LIMIT
_log_ring = __import__('collections').deque(maxlen=_LOG_RING_MAX)
YTDLP_FORBIDDEN_LINK_FLAGS = frozenset({
    # Shortcut files written from remote metadata — CVE-2026-55404.
    '--write-link',
    '--write-url-link',
    '--write-desktop-link',
    '--write-webloc-link',
    # Command execution driven by extractor output — GHSA-69qj-pvh9-c5wg.
    '--exec',
    '--exec-before-download',
    # Credential files and credential-producing commands —
    # GHSA-g3gw-q23r-pgqm.
    '--netrc',
    '--netrc-cmd',
    '--netrc-location',
    # Handing the transfer to an external downloader. Astra Downloader never
    # offers one, and 2026 brought code-execution advisories against two of
    # the common choices (CVE-2026-50574, CVE-2026-50019).
    '--downloader',
    '--external-downloader',
    '--downloader-args',
    '--external-downloader-args',
})


# Applied to every yt-dlp spawn, not to any single builder.
#
# --ignore-config stops configuration *files*; yt-dlp's plugin directories are
# a separate mechanism with their own defaults, so without --no-plugin-dirs
# arbitrary Python under %APPDATA%\yt-dlp\plugins is imported — and executed —
# inside the process this program spawns. Verified 2026-08-06: a marker plugin
# ran under exactly the flags used here, and the debug line read
# "Plugin directories: <path>"; with --no-plugin-dirs it reads
# "none (disabled)". Refusing --exec and the external downloaders at this same
# boundary while leaving that path open would be decorative.
#
# --no-remote-components is belt-and-braces: official builds, which is what
# this program downloads and manages, do not fetch remote components anyway.
#
# Both options require a current yt-dlp. That is already this program's floor:
# requirements.txt pins 2026.7.4 and YouTube extraction needs a build newer
# than YTDLP_EXTERNAL_RUNTIME_CUTOFF regardless.
YTDLP_HARDENING_FLAGS = ('--no-plugin-dirs', '--no-remote-components')


def validate_ytdlp_spawn_args(args):
    """Fail closed if an out-of-policy flag reaches the process boundary.

    Request fields and persisted settings are allowlisted earlier, but this
    final guard also catches future builder regressions and yt-dlp's accepted
    long-option abbreviations. Everything in the denylist either creates files
    or runs commands from remote metadata, or hands the transfer to a process
    this program does not control; each entry names its advisory above.

    This is also where the hardening flags are added, so a yt-dlp invocation
    added later cannot forget them.
    """
    safe_args = list(args)
    for raw_arg in safe_args[1:]:
        if not isinstance(raw_arg, str):
            continue
        option = raw_arg.strip().split('=', 1)[0].casefold()
        if option.startswith('--') and any(
                forbidden.startswith(option) for forbidden in YTDLP_FORBIDDEN_LINK_FLAGS):
            raise ValueError(f'Refusing unsafe yt-dlp flag: {option}')
    missing = [flag for flag in YTDLP_HARDENING_FLAGS if flag not in safe_args]
    return safe_args[:1] + missing + safe_args[1:]


_YTDLP_ACTIVITY = YTDLPActivityRegistry()


def spawn_ytdlp(args, **kwargs):
    """Launch yt-dlp only after applying final process-boundary policy."""
    token = _YTDLP_ACTIVITY.reserve()
    try:
        process = subprocess.Popen(validate_ytdlp_spawn_args(args), **kwargs)
    except Exception:
        _YTDLP_ACTIVITY.release(token)
        raise
    if callable(getattr(process, 'poll', None)):
        _YTDLP_ACTIVITY.attach(token, process)
    else:
        # Test doubles and unusual launch adapters without poll() cannot be
        # observed safely; do not leave a permanent busy marker behind.
        _YTDLP_ACTIVITY.release(token)
    return process


def probe_subscription_uploads(
    url,
    timeout=SUBSCRIPTION_PROBE_TIMEOUT_SECONDS,
    configured_runtime='auto',
    identity_builder=None,
):
    """Read a bounded flat upload listing without downloading media."""
    normalized, error = normalize_url(url)
    if error or not normalized or not is_youtube_url(normalized):
        return [], "Subscriptions must use a YouTube channel or playlist URL."
    args = [
        str(YTDLP_PATH), '--ignore-config', '--no-colors', '--no-warnings',
        '--flat-playlist', '--dump-single-json', '--skip-download',
        '--playlist-end', str(SUBSCRIPTION_PROBE_LIMIT),
    ]
    args += build_youtube_extractor_args(normalized)
    args += build_javascript_runtime_args(
        probe_javascript_runtime(configured_runtime=configured_runtime)
    )
    identity_cleanup = None
    if identity_builder is not None:
        try:
            identity_args, identity_cleanup = identity_builder(normalized)
            args += identity_args
        except Exception as exc:  # noqa: BLE001
            return [], f"Could not prepare the subscription identity: {exc}"
    args.append(normalized)
    try:
        proc = spawn_ytdlp(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=CREATE_NO_WINDOW,
            env=_build_subprocess_env(),
        )
    except Exception as exc:  # noqa: BLE001
        if identity_cleanup:
            identity_cleanup()
        return [], f"Could not start yt-dlp: {exc}"
    try:
        output, error_output = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            terminate_process_tree(proc)
        except Exception as error:
            write_persistent_log(
                f"WARNING: subscription probe termination failed: {error}"
            )
        return [], "Timed out while scanning the subscription."
    finally:
        if identity_cleanup:
            identity_cleanup()
        _YTDLP_ACTIVITY.release_process(proc)
    if proc.returncode != 0:
        lines = [line.strip() for line in (error_output or '').splitlines() if line.strip()]
        return [], (lines[-1] if lines else "yt-dlp could not scan the subscription.")[:240]
    try:
        info = json.loads(output or '{}')
    except (TypeError, ValueError):
        return [], "Could not parse yt-dlp output while scanning the subscription."
    if not isinstance(info, dict):
        return [], "yt-dlp returned an invalid subscription listing."
    entries = info.get('entries')
    if not isinstance(entries, list):
        entries = [info] if info.get('id') or info.get('url') else []
    return entries[:SUBSCRIPTION_PROBE_LIMIT], None


def spawn_media_process(args, **kwargs):
    """Launch a server-built media helper command without accepting client flags."""
    return subprocess.Popen(list(args), **kwargs)


def write_persistent_log(message, path=None):
    """Best-effort disk log for diagnostics when the windowed exe has no console.

    ``path`` binds LOG_PATH late so the test suite can redirect the module
    global to a temp file — unit runs used to interleave fabricated failure
    lines ("updater exploded", "disk full") into the REAL
    %LOCALAPPDATA%/AstraDownloader/server.log, poisoning support reads."""
    try:
        path = Path(LOG_PATH if path is None else path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _LOG_LOCK:
            if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
                backup = path.with_suffix(path.suffix + ".1")
                try:
                    if backup.exists():
                        backup.unlink()
                    path.replace(backup)
                except Exception:
                    # reason: log rotation is optional and the active log remains usable
                    pass
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f"{ts} {message}\n")
            _log_ring.append({'ts': ts, 'msg': message[:MAX_TEXT_FIELD]})
    except Exception:
        # reason: persistent diagnostics are best-effort and must never mask application work
        pass


def seed_log_ring(path=None):
    """Restore the bounded in-memory log view from the persisted log tail."""
    try:
        target = Path(LOG_PATH if path is None else path)
        if not target.is_file():
            return 0
        with open(target, 'rb') as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - LOG_MAX_BYTES), os.SEEK_SET)
            raw = stream.read()
        lines = raw.decode('utf-8', errors='replace').splitlines()
        entries = []
        for line in lines[-_LOG_RING_MAX:]:
            match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s(.*)$', line)
            if match:
                timestamp, message = match.groups()
            else:
                timestamp, message = '', line
            if message:
                entries.append({'ts': timestamp, 'msg': message[:MAX_TEXT_FIELD]})
        with _LOG_LOCK:
            _log_ring.clear()
            _log_ring.extend(entries)
        return len(entries)
    except Exception:
        # reason: a corrupt or locked historical log must not prevent startup
        return 0


def get_recent_log_entries():
    with _LOG_LOCK:
        return list(_log_ring)


def redact_diagnostic_text(value, secrets=None):
    """Return bounded support text without paths, URLs, or secret-shaped values."""
    text = str(value or '')[:DIAGNOSTIC_TEXT_LIMIT]
    for secret in secrets or ():
        secret = str(secret or '')
        if secret:
            text = text.replace(secret, '[redacted secret]')

    replacements = (
        (str(INSTALL_DIR), '%LOCALAPPDATA%\\AstraDownloader'),
        (str(Path.home()), '%USERPROFILE%'),
    )
    for raw, replacement in replacements:
        if raw:
            text = re.sub(re.escape(raw), lambda _match: replacement, text, flags=re.IGNORECASE)

    # Support bundles do not need user/video URLs. Removing the whole value also
    # avoids leaking query tokens, video IDs, channel handles, and local callback
    # parameters while retaining the surrounding failure message.
    text = re.sub(r'https?://[^\s\]\[(){}<>"\']+', '[redacted URL]', text, flags=re.IGNORECASE)
    # Any remaining absolute Windows path is private even when it lives outside
    # the default install/home roots. Stop at common log delimiters.
    text = re.sub(r'(?<![A-Za-z0-9_])[A-Za-z]:\\[^\r\n\t,;]+', '[redacted path]', text)
    text = re.sub(
        r'(?i)\b(authorization|bearer|cookie|set-cookie|token|api[-_ ]?key)\b\s*[:=]?\s*[^\s,;]+',
        lambda match: f"{match.group(1)}=[redacted]",
        text,
    )
    # Long opaque hex/base64url values cover server tokens, API keys, cookie
    # fragments, request IDs, and download UUIDs. Keep short hashes/versions.
    text = re.sub(r'(?i)\b[a-f0-9]{24,}\b', '[redacted identifier]', text)
    text = re.sub(r'\b[A-Za-z0-9_-]{32,}\b', '[redacted identifier]', text)
    return text


def build_diagnostics_bundle(server_running=False, endpoint='', active_downloads=0,
                             completed_downloads=0, recent_logs=None, secrets=None):
    """Build the allowlisted, redacted diagnostics payload shown before copy."""
    safe_logs = []
    for entry in list(recent_logs or [])[-DIAGNOSTIC_LOG_ENTRY_LIMIT:]:
        if not isinstance(entry, dict):
            continue
        message = redact_diagnostic_text(entry.get('msg', ''), secrets=secrets)
        if not message:
            continue
        safe_logs.append({
            'timestamp': clean_text(entry.get('ts'), '', 32),
            'message': message,
        })
    return {
        'schemaVersion': 1,
        'application': {
            'name': APP_NAME,
            'version': APP_VERSION,
        },
        'service': {
            'state': 'running' if server_running else 'stopped',
            'endpoint': clean_text(endpoint, '', 128),
            'activeDownloads': max(0, int(active_downloads or 0)),
            'completedThisSession': max(0, int(completed_downloads or 0)),
        },
        'dependencies': {
            'ytDlpInstalled': managed_binary_usable(YTDLP_PATH),
            'ffmpegInstalled': managed_binary_usable(FFMPEG_PATH),
            'denoInstalled': DENO_PATH.exists() or bool(shutil.which('deno')),
        },
        'recentLog': safe_logs,
    }


def log_crash(context="Unhandled exception"):
    try:
        write_persistent_log(f"{context}\n{traceback.format_exc()}", CRASH_LOG_PATH)
    except Exception:
        # reason: crash logging must not replace the original unhandled exception
        pass


def report_fatal_error(context="Fatal startup error"):
    """Tell the user a windowed build died, then leave a non-zero exit code.

    A packaged build has no console. Without this, a startup failure means
    double-clicking the icon does nothing at all, forever, with the only
    evidence in a log file the user has no reason to know exists.
    """
    log_crash(context)
    message = (
        f"{APP_NAME} could not start.\n\n{context}\n\n"
        f"Details were written to:\n{CRASH_LOG_PATH}"
    )
    if sys.platform == 'win32':
        try:
            import ctypes

            # MB_OK | MB_ICONERROR | MB_SETFOREGROUND
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10 | 0x10000)
        except Exception:
            # reason: the crash log is already written; a failed dialog must
            # not replace the original error
            pass
    else:
        sys.stderr.write(message + "\n")


def install_unhandled_exception_hooks(notify=None):
    """Route exceptions that escape a slot to the crash log and the user.

    Qt calls slots from C++, so an exception raised inside one unwinds into
    the event loop and, since Qt 6, aborts the process. Without a hook there
    is no traceback anywhere — not even in the log.
    """
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_traceback)
            return
        try:
            write_persistent_log(
                "Unhandled exception\n"
                + "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
                CRASH_LOG_PATH,
            )
        except Exception:
            # reason: reporting must never replace the exception being reported
            pass
        if callable(notify):
            try:
                notify(f"{exc_type.__name__}: {exc_value}")
            except Exception:
                # reason: the in-app notice is best effort
                pass
        previous(exc_type, exc_value, exc_traceback)

    sys.excepthook = hook
    # PyQt routes slot exceptions through sys.excepthook only when this is
    # left alone; assigning it explicitly keeps the behaviour if a future
    # PyQt release changes the default.
    threading.excepthook = lambda args: hook(
        args.exc_type, args.exc_value, args.exc_traceback
    )
    return hook


def _durable_replace(source, destination):
    """Replace a file and flush the rename when it carries update state."""
    source = Path(source)
    destination = Path(destination)
    if os.name == 'nt':
        import ctypes
        move_file_ex = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file_ex.restype = ctypes.c_bool
        flags = 0x00000001 | 0x00000008  # MOVEFILE_REPLACE_EXISTING | WRITE_THROUGH
        if not move_file_ex(str(source), str(destination), flags):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    os.replace(source, destination)
    try:
        directory_fd = os.open(str(destination.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def atomic_copy_verified(source, destination):
    """Copy one file through a sibling temporary and verify byte identity.

    Update recovery depends on the backup remaining usable after a crash.  A
    normal ``copy2`` can leave a truncated destination, so copy, fsync, hash,
    and only then atomically replace the retained backup.
    """
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_digest = _compute_sha256(source)
    if not source_digest:
        raise RuntimeError(f'Could not verify source file {source.name}.')
    tmp = destination.with_name(f'.{destination.name}.{uuid.uuid4().hex}.tmp')
    try:
        with open(source, 'rb') as src, open(tmp, 'wb') as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        copied_digest = _compute_sha256(tmp)
        if copied_digest != source_digest:
            raise RuntimeError(f'Backup verification failed for {source.name}.')
        os.replace(tmp, destination)
        return source_digest
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            # reason: atomic-copy scratch cleanup is best-effort after replacement or failure
            pass


def download_file_atomic(url, path, timeout=60, chunk_size=65536, progress_cb=None,
                         max_bytes=HELPER_DOWNLOAD_MAX_BYTES):
    """Download with atomic replacement.

    progress_cb(downloaded_bytes, total_bytes_or_None) is fired roughly each
    chunk when supplied. It MUST be cheap and thread-safe — the caller is
    responsible for marshaling back to Qt.

    max_bytes caps the stream (audit fix): the byte count is checked while
    streaming so a server that lies about (or omits) content-length cannot
    fill the disk; on breach the partial temp file is removed and a
    RuntimeError raised before any SHA-256 verification would run.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.download")
    try:
        with http_requests.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = None
            try:
                total = int(r.headers.get('content-length', '') or 0) or None
            except (TypeError, ValueError):
                total = None
            if max_bytes and total and total > max_bytes:
                raise RuntimeError(
                    f"Download too large: server advertises {total} bytes "
                    f"(limit {max_bytes})"
                )
            downloaded = 0
            last_cb = 0.0
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if max_bytes and downloaded > max_bytes:
                            raise RuntimeError(
                                f"Download exceeded the {max_bytes} byte limit; aborted"
                            )
                        if progress_cb is not None:
                            now = time.monotonic()
                            # Throttle to ~10 Hz so very fast downloads don't
                            # flood the Qt event loop with progress signals.
                            if now - last_cb > 0.1:
                                last_cb = now
                                try:
                                    progress_cb(downloaded, total)
                                except Exception:
                                    # reason: progress reporting must never
                                    # abort a successful download.
                                    pass
                f.flush()
                os.fsync(f.fileno())
            if progress_cb is not None:
                try:
                    progress_cb(downloaded, total)
                except Exception:
                    # reason: the final progress notification is advisory after bytes are durable
                    pass
        if tmp.stat().st_size <= 0:
            raise RuntimeError("Downloaded file was empty")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            # reason: atomic-download scratch cleanup is best-effort after replacement or failure
            pass


def copy_stream_limited(source, destination, max_bytes, chunk_size=1024 * 1024):
    """Copy a binary stream while enforcing a hard byte ceiling."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    copied = 0
    while True:
        # Read at most one byte beyond the remaining allowance so an
        # over-limit stream is detected without buffering an oversized chunk.
        chunk = source.read(min(chunk_size, max_bytes - copied + 1))
        if not chunk:
            return copied
        copied += len(chunk)
        if copied > max_bytes:
            raise RuntimeError(f"Extracted file exceeded the {max_bytes} byte limit")
        destination.write(chunk)


def extract_archive_executable_atomic(archive_path, destination, executable_name,
                                      max_bytes=HELPER_DOWNLOAD_MAX_BYTES):
    """Extract one exact executable basename through an atomic temporary.

    Release archives are verified by their callers before this function runs,
    but their expanded size and member layout remain untrusted.  Requiring one
    exact basename prevents suffix lookalikes and ambiguity; checking both the
    declared and streamed sizes prevents compressed archive expansion from
    filling the disk.
    """
    import zipfile

    archive_path = Path(archive_path)
    destination = Path(destination)
    expected_name = str(executable_name).casefold()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.extract")
    try:
        with zipfile.ZipFile(archive_path) as zf:
            candidates = []
            for info in zf.infolist():
                normalized = info.filename.replace('\\', '/').rstrip('/')
                basename = normalized.rsplit('/', 1)[-1].casefold()
                if not info.is_dir() and basename == expected_name:
                    candidates.append(info)
            if not candidates:
                raise RuntimeError(f"{executable_name} was not found in the downloaded archive")
            if len(candidates) != 1:
                raise RuntimeError(
                    f"Downloaded archive contains multiple {executable_name} entries"
                )
            member = candidates[0]
            if member.file_size <= 0:
                raise RuntimeError(f"{executable_name} in archive was empty")
            if member.file_size > max_bytes:
                raise RuntimeError(
                    f"{executable_name} expands to {member.file_size} bytes "
                    f"(limit {max_bytes})"
                )
            with zf.open(member) as src, open(tmp, 'wb') as dst:
                copied = copy_stream_limited(src, dst, max_bytes=max_bytes)
                dst.flush()
                os.fsync(dst.fileno())
            if copied <= 0:
                raise RuntimeError(f"{executable_name} in archive was empty")
        os.replace(tmp, destination)
        return destination
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            # reason: archive scratch cleanup is best-effort after replacement or failure
            pass


def extract_archive_directory_atomic(archive_path, destination,
                                     executable_name,
                                     max_bytes=HELPER_DOWNLOAD_MAX_BYTES):
    """Install a verified runtime archive while retaining its sibling DLLs.

    ``extract_archive_executable_atomic`` is intentionally limited to one
    file, which is right for ffmpeg and Deno. whisper.cpp ships a CLI beside
    several DLLs, so extract the one directory containing the named CLI. The
    archive is still treated as untrusted: traversal, absolute names,
    symlinks, ambiguous executables, and expanded-size abuse are rejected
    before the live runtime directory is replaced.
    """
    import zipfile

    archive_path = Path(archive_path)
    destination = Path(destination)
    expected_name = str(executable_name).casefold()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_root = destination.parent / f'.{destination.name}.{uuid.uuid4().hex}.extract'
    backup = destination.parent / f'.{destination.name}.{uuid.uuid4().hex}.old'
    candidates = []
    expanded = 0
    moved_old = False
    try:
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                raw_name = str(info.filename or '').replace('\\', '/')
                if (
                    not raw_name or raw_name.startswith('/')
                    or re.match(r'^[A-Za-z]:', raw_name)
                ):
                    raise RuntimeError('Downloaded runtime archive contained an absolute path')
                parts = tuple(part for part in raw_name.split('/') if part not in ('', '.'))
                if not parts or '..' in parts:
                    raise RuntimeError('Downloaded runtime archive contained a traversal path')
                target = tmp_root.joinpath(*parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                mode = (int(info.external_attr) >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise RuntimeError('Downloaded runtime archive contained a symlink')
                if info.file_size <= 0:
                    raise RuntimeError(f'Runtime archive member {raw_name} was empty')
                member_size = int(info.file_size)
                if expanded + member_size > max_bytes:
                    raise RuntimeError(
                        f'Runtime archive expands beyond the {max_bytes} byte limit'
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, open(target, 'wb') as stream:
                    copied = copy_stream_limited(
                        source, stream, max_bytes=max_bytes - expanded
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                if copied != member_size:
                    raise RuntimeError(f'Runtime archive member {raw_name} was truncated')
                expanded += member_size
                if target.name.casefold() == expected_name:
                    candidates.append(target)
        if len(candidates) != 1:
            raise RuntimeError(
                f'Downloaded runtime archive must contain exactly one {executable_name}'
            )
        source_dir = candidates[0].parent
        if destination.exists():
            os.replace(destination, backup)
            moved_old = True
        os.replace(source_dir, destination)
        if moved_old:
            shutil.rmtree(backup, ignore_errors=True)
            moved_old = False
        return destination / executable_name
    except Exception:
        if moved_old and not destination.exists() and backup.exists():
            try:
                os.replace(backup, destination)
                moved_old = False
            except OSError:
                # reason: recovery is best-effort; the old verified runtime
                # is preferable to leaving a half-extracted directory
                pass
        raise
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        if not moved_old:
            shutil.rmtree(backup, ignore_errors=True)


# ── v1.2.0 helpers: SHA-256 verification, path confinement, rate limiting ──
def _compute_sha256(path, chunk_size=65536):
    """Return lowercase hex SHA-256 of a file's contents, or None on error."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                h.update(chunk)
        return h.hexdigest().lower()
    except Exception as e:
        write_persistent_log(f"SHA-256 compute failed for {path}: {e}")
        return None


def _parse_sha256_sums(body, target_asset=None):
    """Parse a SHA256SUMS-style document.

    Supports two formats:
      <hex>  <filename>
      <hex> *<filename>
      <hex>
    Returns the hex digest for target_asset, or the single digest if the file
    contains exactly one entry with no filename and no asset selector was
    supplied.
    """
    if not body:
        return None
    body = body.strip()
    if not body:
        return None
    # Single-line "<hex>" sidecar (some ffmpeg-builds assets ship this form).
    # A bare digest cannot prove which asset it belongs to, so it is only
    # safe when the caller has no asset selector to enforce.
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) == 1 and re.fullmatch(r'[0-9A-Fa-f]{64}', lines[0]):
        return None if target_asset else lines[0].lower()
    for line in lines:
        # Tolerate "<hex>  <name>" and "<hex> *<name>" variants.
        m = re.match(r'^([0-9A-Fa-f]{64})\s+\*?(.+)$', line)
        if not m:
            continue
        digest, name = m.group(1).lower(), m.group(2).strip()
        if target_asset and Path(name).name != target_asset:
            continue
        return digest
    return None


def fetch_expected_sha256(sidecar_url, target_asset=None, timeout=15):
    """Best-effort checksum fetch. Returns None when the sidecar is missing,
    malformed, or the request fails — caller decides whether to hard-fail."""
    try:
        with http_requests.get(sidecar_url, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                return None
            try:
                advertised = int(r.headers.get('content-length', '') or 0)
            except (TypeError, ValueError):
                advertised = 0
            if advertised > CHECKSUM_SIDECAR_MAX_BYTES:
                return None
            body = bytearray()
            for chunk in r.iter_content(4096):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > CHECKSUM_SIDECAR_MAX_BYTES:
                    return None
            text = body.decode('utf-8', errors='replace')
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if (
                target_asset
                and len(lines) == 1
                and re.fullmatch(r'[0-9A-Fa-f]{64}', lines[0])
            ):
                # A URL-specific .sha256/.sha256sum sidecar can identify its
                # payload by filename; a generic manifest cannot.
                sidecar_name = Path(urlparse(sidecar_url).path).name
                for suffix in ('.sha256sum', '.sha256', '.sha256.txt'):
                    if sidecar_name.endswith(suffix):
                        sidecar_name = sidecar_name[:-len(suffix)]
                        break
                if sidecar_name != target_asset:
                    return None
                return lines[0].lower()
            return _parse_sha256_sums(text, target_asset=target_asset)
    except Exception:
        return None


def verify_file_sha256(path, expected_hex):
    """Raise RuntimeError on mismatch, return True on success, False when
    expected_hex is missing so callers can decide whether to fail closed."""
    if not expected_hex:
        return False
    expected = expected_hex.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        return False
    actual = _compute_sha256(path)
    if actual is None:
        raise RuntimeError(f"Could not hash {path} for integrity verification")
    if actual != expected:
        raise RuntimeError(
            f"SHA-256 mismatch for {Path(path).name}: "
            f"expected {expected[:12]}…, got {actual[:12]}…. "
            "Delete the downloaded file and retry setup."
        )
    return True


def download_verified_file_atomic(url, path, expected_hex, **download_kwargs):
    """Download, verify, and activate a managed file transactionally.

    ``download_file_atomic`` makes a complete download durable, but its
    destination is still live before a caller can perform integrity checks.
    Managed binaries therefore download into a fresh sibling staging path;
    only a successful digest check can replace the installed file.  If the
    fetch or verification fails, an existing installed file is untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.verified')
    try:
        download_file_atomic(url, staged, **download_kwargs)
        if not verify_file_sha256(staged, expected_hex):
            raise RuntimeError(
                f"Could not verify downloaded file {path.name}; refusing to install it."
            )
        _durable_replace(staged, path)
        return path
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            # reason: failed staging cleanup may race with antivirus
            pass


def cleanup_stale_cookie_jars(older_than_seconds=300):
    return _owned_cleanup_stale_cookie_jars(
        INSTALL_DIR,
        older_than_seconds=older_than_seconds,
        clock=time.time,
    )


def _run_captured(args, timeout=5):
    return _owned_run_captured(
        args,
        timeout=timeout,
        runner=subprocess.run,
        creationflags=CREATE_NO_WINDOW,
    )


_ytdlp_version_probe = ExecutableVersionProbe(
    path=lambda: YTDLP_PATH,
    args=('--version',),
    parser=parse_ytdlp_version_output,
    runner=lambda args: _run_captured(args),
    clock=lambda: time.time(),
)
_ffmpeg_version_probe = ExecutableVersionProbe(
    path=lambda: FFMPEG_PATH,
    args=('-version',),
    parser=parse_ffmpeg_version_output,
    runner=lambda args: _run_captured(args),
    clock=lambda: time.time(),
)


def get_ytdlp_version(force=False):
    return _ytdlp_version_probe.get(force=force)


_impersonate_targets_probe = ImpersonateTargetsProbe(
    path=lambda: YTDLP_PATH,
    runner=lambda args: _run_captured(args, timeout=20),
    clock=lambda: time.time(),
)


def probe_impersonate_targets(force=False):
    """Browser fingerprints the installed yt-dlp can actually imitate."""
    return _impersonate_targets_probe.get(force=force)


def reset_impersonate_targets_cache():
    _impersonate_targets_probe.reset()


def probe_po_token_provider(force=False, timeout=PO_TOKEN_PROVIDER_PROBE_TIMEOUT):
    """Return no usable provider while yt-dlp plugin loading is disabled."""
    return None


def reset_po_token_provider_cache():
    # Kept as a no-op for callers that reset all readiness probes between
    # tests or after a setup run. There is no network probe to cache anymore.
    return None


# Deno (or other external JS runtime) presence probe + cutoff
# evaluation for the bundled yt-dlp.exe.
_deno_runtime_cache = {'value': None, 'checked_at': 0.0}
_DENO_RUNTIME_CACHE_LOCK = threading.Lock()


class DenoProvisionError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


_last_deno_provision_error = {'code': None, 'message': ''}


def _set_deno_provision_error(code=None, message=''):
    _last_deno_provision_error['code'] = code
    _last_deno_provision_error['message'] = str(message or '')


def get_last_deno_provision_error():
    return dict(_last_deno_provision_error)


def _parse_deno_version(output):
    return _owned_parse_javascript_runtime_version('deno', output)


def _is_deno_version_supported(version):
    return _owned_javascript_runtime_supported(
        'deno', version, deno_min=DENO_MIN_VERSION, node_min=NODE_MIN_VERSION
    )


def _probe_deno_binary_version(deno_path):
    output = _run_captured([str(deno_path), '--version'], timeout=DENO_RUNTIME_PROBE_TIMEOUT)
    return _parse_deno_version(output)


def _parse_javascript_runtime_version(runtime, output):
    return _owned_parse_javascript_runtime_version(runtime, output)


def _javascript_runtime_supported(runtime, version):
    return _owned_javascript_runtime_supported(
        runtime, version, deno_min=DENO_MIN_VERSION, node_min=NODE_MIN_VERSION
    )


def _probe_javascript_execution(runtime, executable):
    return _owned_probe_javascript_execution(
        runtime,
        executable,
        runner=lambda args, timeout: _run_captured(args, timeout=timeout),
        marker=JS_RUNTIME_CAPABILITY_MARKER,
        timeout=DENO_RUNTIME_PROBE_TIMEOUT,
    )


def _javascript_runtime_candidates(configured_runtime):
    candidates = []
    if configured_runtime in {'auto', 'deno'}:
        if DENO_PATH.exists():
            candidates.append(('deno', str(DENO_PATH), 'bundled'))
        system_deno = shutil.which('deno')
        if system_deno and all(path != system_deno for _runtime, path, _source in candidates):
            candidates.append(('deno', system_deno, 'system'))
    if configured_runtime in {'auto', 'node'}:
        system_node = shutil.which('node')
        if system_node:
            candidates.append(('node', system_node, 'system'))
    if configured_runtime in {'auto', 'quickjs'}:
        # Last, matching yt-dlp's own priority (deno > node > quickjs). Only
        # the copy this app provisioned is offered: it is pinned to a digest
        # and verified end-to-end, which nothing on PATH is.
        if managed_binary_usable(QUICKJS_PATH):
            candidates.append(('quickjs', str(QUICKJS_PATH), 'bundled'))
    return candidates


def _evaluate_javascript_runtime(runtime, path, source):
    return _owned_evaluate_javascript_runtime(
        runtime,
        path,
        source,
        runner=lambda args, timeout: _run_captured(args, timeout=timeout),
        marker=JS_RUNTIME_CAPABILITY_MARKER,
        timeout=DENO_RUNTIME_PROBE_TIMEOUT,
        deno_min=DENO_MIN_VERSION,
        node_min=NODE_MIN_VERSION,
    )


def provision_deno():
    """Download Deno into DENO_DIR if not already present.

    Returns the path to the provisioned deno.exe, or None on failure.
    Follows the same atomic-download pattern as yt-dlp and ffmpeg.
    """
    _set_deno_provision_error()
    if DENO_PATH.exists():
        version = _probe_deno_binary_version(DENO_PATH)
        if _is_deno_version_supported(version):
            return str(DENO_PATH)
        write_persistent_log(
            f"Bundled Deno {version or 'unknown'} is below required {DENO_MIN_VERSION}; refreshing"
        )
    DENO_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = DENO_DIR / f'.deno.{uuid.uuid4().hex}.zip'
    try:
        expected_hash = fetch_expected_sha256(DENO_SHA256_URL, target_asset=DENO_SHA256_ASSET)
        if not expected_hash:
            raise DenoProvisionError(
                'deno-sha256-sidecar-missing',
                'Deno checksum sidecar was missing or malformed; refusing to extract an unverified runtime.',
            )
        with http_requests.get(DENO_ZIP_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_bytes = 0
            with open(tmp_zip, 'wb') as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)
                        if total_bytes > HELPER_DOWNLOAD_MAX_BYTES:
                            raise RuntimeError('Deno archive exceeded size limit')
                f.flush()
                os.fsync(f.fileno())
        if tmp_zip.stat().st_size <= 0:
            raise RuntimeError('Downloaded Deno archive was empty')
        try:
            verify_file_sha256(tmp_zip, expected_hash)
        except RuntimeError as e:
            try:
                tmp_zip.unlink(missing_ok=True)
            except OSError:
                # reason: failed archive cleanup may race with antivirus or another recovery pass
                pass
            raise DenoProvisionError('deno-sha256-verification-failed', str(e))
        extract_archive_executable_atomic(
            tmp_zip, DENO_PATH, 'deno.exe', max_bytes=HELPER_DOWNLOAD_MAX_BYTES,
        )
        installed_version = _probe_deno_binary_version(DENO_PATH)
        if not _is_deno_version_supported(installed_version):
            try:
                DENO_PATH.unlink(missing_ok=True)
            except OSError:
                # reason: invalid provisioned runtime cleanup is best-effort before reporting failure
                pass
            raise DenoProvisionError(
                'deno-runtime-unsupported',
                (
                    f"Provisioned Deno {installed_version or 'unknown'} is below "
                    f"the required {DENO_MIN_VERSION} runtime floor."
                ),
            )
        reset_deno_runtime_cache()
        return str(DENO_PATH)
    except DenoProvisionError as e:
        _set_deno_provision_error(e.code, str(e))
        write_persistent_log(f"Deno provisioning failed: {e}")
        return None
    except Exception as e:
        _set_deno_provision_error('deno-provision-failed', str(e))
        write_persistent_log(f"Deno provisioning failed: {e}")
        return None
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            # reason: temporary runtime archive cleanup is best-effort during every exit path
            pass


def provision_quickjs():
    """Fetch the pinned QuickJS build into QUICKJS_DIR if it is not there.

    Returns the path to a verified qjs.exe, or None. This is the runtime the
    app can obtain on its own: a 2 MB executable against Deno's 40 MB
    archive, so it is what "YouTube works without installing anything" rests
    on. Deno stays the preferred runtime when it is present.

    Unlike Deno's, the expected digest is pinned in source rather than read
    from a published sidecar — quickjs-ng ships no checksum asset, and a
    digest that travels with the code is not something the release host can
    change. The consequence is that bumping QUICKJS_VERSION requires bumping
    QUICKJS_SHA256 in the same commit; a test refuses a mismatched pair.
    """
    if managed_binary_usable(QUICKJS_PATH):
        version = _probe_quickjs_binary_version(QUICKJS_PATH)
        if version and _compare_semver(version, QUICKJS_MIN_VERSION) >= 0:
            return str(QUICKJS_PATH)
        write_persistent_log(
            f"Provisioned QuickJS {version or 'unknown'} is below required "
            f"{QUICKJS_MIN_VERSION}; refreshing"
        )
    QUICKJS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        download_verified_file_atomic(
            QUICKJS_EXE_URL, QUICKJS_PATH, QUICKJS_SHA256,
            timeout=120, max_bytes=HELPER_DOWNLOAD_MAX_BYTES,
        )
    except Exception as error:
        write_persistent_log(f"QuickJS provisioning failed: {error}")
        return None
    reset_deno_runtime_cache()
    return str(QUICKJS_PATH)


def provision_whisper_model(progress_cb=None):
    """Fetch and verify the pinned local Whisper model when requested."""
    state = managed_binary_state(WHISPER_MODEL_PATH, WHISPER_MODEL_MIN_BYTES)
    if state == 'ok':
        try:
            verify_file_sha256(WHISPER_MODEL_PATH, WHISPER_MODEL_SHA256)
            return str(WHISPER_MODEL_PATH)
        except RuntimeError as error:
            write_persistent_log(f'Whisper model checksum failed; refreshing: {error}')
            try:
                WHISPER_MODEL_PATH.unlink(missing_ok=True)
            except OSError:
                # reason: a quarantined or locked model will be replaced if
                # the next fetch can acquire the destination
                pass

    space_failure = check_download_disk_space(
        INSTALL_DIR, WHISPER_MODEL_MIN_BYTES,
    )
    if space_failure:
        write_persistent_log(
            'Whisper model provisioning skipped: '
            f"{space_failure.get('error', 'insufficient disk space')}"
        )
        return None
    try:
        download_verified_file_atomic(
            WHISPER_MODEL_URL,
            WHISPER_MODEL_PATH,
            WHISPER_MODEL_SHA256,
            timeout=120,
            chunk_size=65536,
            progress_cb=progress_cb,
            max_bytes=HELPER_DOWNLOAD_MAX_BYTES,
        )
        if managed_binary_state(
            WHISPER_MODEL_PATH, WHISPER_MODEL_MIN_BYTES
        ) != 'ok':
            raise RuntimeError('Downloaded Whisper model was smaller than expected.')
        return str(WHISPER_MODEL_PATH)
    except Exception as error:
        write_persistent_log(f'Whisper model provisioning failed: {error}')
        return None


def provision_whisper_runtime(progress_cb=None):
    """Fetch the pinned whisper.cpp CLI and its runtime DLLs atomically."""
    current = probe_whisper_runtime(
        WHISPER_BIN_PATH, WHISPER_BIN_MIN_BYTES,
    )
    if current.get('usable'):
        return str(WHISPER_BIN_PATH)

    space_failure = check_download_disk_space(INSTALL_DIR, HELPER_DOWNLOAD_MAX_BYTES)
    if space_failure:
        write_persistent_log(
            'Whisper runtime provisioning skipped: '
            f"{space_failure.get('error', 'insufficient disk space')}"
        )
        return None

    tmp_zip = INSTALL_DIR / f'.whisper.{uuid.uuid4().hex}.zip'
    installed = False
    try:
        download_file_atomic(
            WHISPER_BIN_URL,
            tmp_zip,
            timeout=120,
            chunk_size=65536,
            progress_cb=progress_cb,
            max_bytes=HELPER_DOWNLOAD_MAX_BYTES,
        )
        verify_file_sha256(tmp_zip, WHISPER_BIN_SHA256)
        extracted = extract_archive_directory_atomic(
            tmp_zip,
            WHISPER_BIN_DIR,
            'whisper-cli.exe',
            max_bytes=HELPER_DOWNLOAD_MAX_BYTES,
        )
        installed = True
        result = probe_whisper_runtime(extracted, WHISPER_BIN_MIN_BYTES)
        if not result.get('usable'):
            raise RuntimeError(
                'Downloaded whisper.cpp runtime did not expose its SRT capability.'
            )
        return str(extracted)
    except Exception as error:
        if installed:
            shutil.rmtree(WHISPER_BIN_DIR, ignore_errors=True)
        write_persistent_log(f'Whisper runtime provisioning failed: {error}')
        return None
    finally:
        try:
            tmp_zip.unlink(missing_ok=True)
        except OSError:
            # reason: cleanup is best-effort after a verified extraction
            pass


def _probe_quickjs_binary_version(path):
    try:
        output = _run_captured(
            [str(path), '--version'], timeout=DENO_RUNTIME_PROBE_TIMEOUT
        )
    except Exception:
        # reason: an unrunnable binary is treated as an unusable one by the
        # caller, which re-fetches rather than reporting a version
        return None
    return _parse_javascript_runtime_version('quickjs', output)


def probe_deno_runtime(force=False, configured_runtime='auto'):
    """Probe the configured yt-dlp JavaScript runtime capability.

    The historical function name remains for wire compatibility. The result
    now distinguishes version support from actual JavaScript execution and can
    select Node 22+ when configured. Unknown and exception states fail closed.
    """
    preference = str(configured_runtime or 'auto').strip().lower()
    if preference not in {'auto', 'deno', 'node', 'quickjs'}:
        preference = 'auto'
    with _DENO_RUNTIME_CACHE_LOCK:
        cache = _deno_runtime_cache
        now = time.time()
        if (not force
                and cache.get('preference') == preference
                and (now - cache['checked_at']) < _DENO_RUNTIME_CACHE_TTL_SECONDS):
            return cache['value']
    # Runtime discovery includes yt-dlp and up to two subprocess probes per
    # candidate. Keep all of that work outside the cache lock so a cold or
    # stalled runtime cannot serialize health, readiness, and download calls.
    ytdlp_version = get_ytdlp_version()
    parsed_ytdlp_version = _parse_ytdlp_release_date(ytdlp_version or '')
    # A present binary whose version cannot be verified is not evidence of
    # the pre-runtime line. Treat it as runtime-required; first-run remains
    # quiet because there is no binary yet.
    needs_runtime = (
        ytdlp_needs_external_runtime(ytdlp_version or '')
        if parsed_ytdlp_version is not None
        else YTDLP_PATH.exists()
    )
    evaluated = [
        _evaluate_javascript_runtime(runtime, path, source)
        for runtime, path, source in _javascript_runtime_candidates(preference)
    ]
    selected = next((item for item in evaluated if item['ejsReady']), None)
    if selected is None and evaluated:
        selected = evaluated[0]
    if selected is None:
        selected = {
            'runtime': preference if preference != 'auto' else None,
            'version': None,
            'path': None,
            'source': None,
            'supported': False,
            'ejsReady': False,
            'minVersion': {
                'node': NODE_MIN_VERSION, 'quickjs': QUICKJS_MIN_VERSION,
            }.get(preference, DENO_MIN_VERSION),
            'reason': 'runtime-not-installed',
        }

    installed = selected['path'] is not None
    ready = selected['supported'] and selected['ejsReady']
    runtime_label = (selected.get('runtime') or 'JavaScript runtime').title()
    advice = ''
    if needs_runtime and selected['reason'] == 'runtime-not-installed':
        advice = (
            'No configured JavaScript runtime was found. Select Auto or Deno and click '
            'Provision Deno, or select Node after installing Node 22 or newer.'
        )
    elif needs_runtime and selected['reason'] == 'runtime-version-unsupported':
        advice = (
            f"{runtime_label} {selected.get('version') or 'unknown'} is below the required "
            f"{selected['minVersion']} runtime floor. Update it, then retry."
        )
    elif needs_runtime and selected['reason'] in {'runtime-version-unparseable', 'runtime-probe-failed'}:
        advice = (
            f"Astra Downloader could not verify the configured {runtime_label} version. "
            'Repair or replace the runtime, then retry.'
        )
    elif needs_runtime and not ready:
        advice = (
            f"{runtime_label} reported a supported version but failed the JavaScript "
            'execution probe required by yt-dlp EJS. Repair or replace it, then retry.'
        )
    result = {
        **selected,
        'installed': installed,
        'stale': bool(installed and not ready),
        'configuredRuntime': preference,
        'canProvisionDeno': preference in {'auto', 'deno'},
        'ytdlpNeedsRuntime': needs_runtime,
        'advice': advice,
    }
    with _DENO_RUNTIME_CACHE_LOCK:
        cache = _deno_runtime_cache
        cache['value'] = result
        cache['checked_at'] = time.time()
        cache['preference'] = preference
        return result


probe_javascript_runtime = probe_deno_runtime


def reset_deno_runtime_cache():
    """Test hook + manual recheck path — clears the cached probe result."""
    with _DENO_RUNTIME_CACHE_LOCK:
        _deno_runtime_cache['value'] = None
        _deno_runtime_cache['checked_at'] = 0.0
        _deno_runtime_cache['preference'] = None


def get_ffmpeg_version(force=False):
    return _ffmpeg_version_probe.get(force=force)


# v1.4.0 (NX10): ffmpeg 8.0 dropped OpenSSL <=1.1.0; 8.1.1 removed the
# legacy HLS protocol handler (HLS is still supported via the demuxer
# path that yt-dlp typically uses, but the old `hls://` URL form is
# gone). Both releases also flipped TLS peer-cert verification ON by
# default. We don't read ffmpeg's capabilities directly anywhere — yt-dlp
# handles invocation — but we can audit ffmpeg's reported major version
# at bootstrap and warn if it's stale. The check runs once per Astra
# Downloader launch (cached) and the result lands on /health.
_FFMPEG_MIN_MAJOR = 8  # ffmpeg 8.x is current as of 2026.
# Exact security floor. FFmpeg 8.1.2 fixes the MagicYUV decoder RCE
# (CVE-2026-8461, CVSS 8.8); 8.0/8.0.1 carry the RV60 OOB-read cluster. A
# stale ffmpeg on PATH that reports a tagged version below this is flagged on
# /health. Master snapshots use their embedded build date against the dated
# security floor below.
_FFMPEG_MIN_VERSION = "8.1.2"
# Master snapshots have no semver, so compare their embedded build date to
# the release date of the exact security floor. A snapshot from before this
# date is re-fetched through the same verified bootstrap as a stale release.
_FFMPEG_MIN_SNAPSHOT_DATE = "2026-06-17"
_ffmpeg_capabilities_probe = FfmpegCapabilitiesProbe(
    version_getter=lambda: get_ffmpeg_version(),
    clock=lambda: time.time(),
    minimum_major=_FFMPEG_MIN_MAJOR,
    minimum_version=_FFMPEG_MIN_VERSION,
    minimum_snapshot_date=_FFMPEG_MIN_SNAPSHOT_DATE,
    ttl_seconds=3600,
)


def check_ffmpeg_capabilities(force=False):
    return _ffmpeg_capabilities_probe.check(force=force)


_ffmpeg_filter_probe_lock = threading.Lock()
_ffmpeg_filter_probe_value = None
_ffmpeg_filter_probe_checked_at = 0.0
_FFMPEG_FILTER_PROBE_TTL_SECONDS = 3600


def probe_ffmpeg_filters(force=False):
    """Check the small filter surface used by local transcription.

    A missing executable is reported as unchecked rather than as a false
    positive. The subprocess is only started for the managed executable and
    the result is cached so readiness and /health cannot create a probe storm.
    """
    global _ffmpeg_filter_probe_value, _ffmpeg_filter_probe_checked_at
    path = Path(FFMPEG_PATH)
    if not path.is_file():
        return {
            'filterCheck': False,
            'missingFilters': [],
            'filterReason': 'ffmpeg-not-installed',
        }
    with _ffmpeg_filter_probe_lock:
        now = time.time()
        if (
            not force and _ffmpeg_filter_probe_value is not None
            and now - _ffmpeg_filter_probe_checked_at < _FFMPEG_FILTER_PROBE_TTL_SECONDS
        ):
            return dict(_ffmpeg_filter_probe_value)
    output = _run_captured(
        [str(path), '-hide_banner', '-filters'], timeout=5,
    )
    if not output:
        result = {
            'filterCheck': False,
            'missingFilters': [],
            'filterReason': 'filter-probe-failed',
        }
    else:
        result = {
            'filterCheck': True,
            'missingFilters': missing_ffmpeg_filters(output),
            'filterReason': 'ready',
        }
    with _ffmpeg_filter_probe_lock:
        _ffmpeg_filter_probe_value = dict(result)
        _ffmpeg_filter_probe_checked_at = time.time()
    return result


def get_preflight_ffmpeg_capabilities(force=False):
    """Return the cached security-floor result plus filter capability data."""
    result = dict(check_ffmpeg_capabilities(force=force) or {})
    result.update(probe_ffmpeg_filters(force=force))
    return result


def reset_ffmpeg_capabilities_cache():
    global _ffmpeg_filter_probe_value, _ffmpeg_filter_probe_checked_at
    _ffmpeg_capabilities_probe.reset()
    with _ffmpeg_filter_probe_lock:
        _ffmpeg_filter_probe_value = None
        _ffmpeg_filter_probe_checked_at = 0.0


# ── v1.2.0: throttled yt-dlp auto-update helpers ──
# v1.5.4: 24h -> 12h. The check now fires on the download path (initiation +
# queue-idle), not just at the rare server restart, so a shorter throttle keeps
# yt-dlp fresh — important when YouTube breaks older builds and yt-dlp ships a
# same-day fix — while still bounding GitHub release checks to at most twice a
# day per user.
_YTDLP_UPDATE_INTERVAL_HOURS = 12
_YTDLP_UPDATE_FAILURE_BACKOFF_HOURS = 1
_YTDLP_UPDATE_LOCK = threading.Lock()
_COMPANION_UPDATE_LOCK = threading.Lock()


def _ytdlp_update_state_path():
    return INSTALL_DIR / 'yt-dlp-update-state.json'


def _companion_update_state_path():
    return INSTALL_DIR / 'companion-update-state.json'


_UPDATE_SCRATCH_PREFIXES = (
    '.AstraDownloader.update.',
    '..AstraDownloader.update.',
    '.AstraDownloader.apply-update.',
    '.yt-dlp.update.',
    '..yt-dlp.update.',
)


def cleanup_update_scratch_files():
    """Remove update artifacts left behind by a killed updater process."""
    root = Path(INSTALL_DIR)
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    removed = 0
    for child in children:
        if not any(child.name.startswith(prefix) for prefix in _UPDATE_SCRATCH_PREFIXES):
            continue
        try:
            if child.is_symlink() or not child.is_file():
                continue
            child.unlink(missing_ok=True)
            removed += 1
        except OSError as error:
            write_persistent_log(f'Could not remove stale update scratch {child}: {error}')
    if removed:
        write_persistent_log(f'Removed {removed} stale update scratch file(s) at startup.')
    return removed


def _read_update_state(path):
    data = load_json_file(path, {})
    return data if isinstance(data, dict) else {}


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _parse_update_timestamp(value):
    """Parse current UTC markers and legacy local-naive markers safely."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        stamp = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        try:
            stamp = datetime.strptime(text, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    if stamp.tzinfo is None:
        # State written before UTC markers used the machine's local wall clock.
        # Attach the local zone before comparing it with an aware UTC value.
        stamp = stamp.astimezone()
    return stamp.astimezone(timezone.utc)


def _write_update_state(path, **fields):
    state = _read_update_state(path)
    state.update(fields)
    state['updated_at'] = _utc_timestamp()
    atomic_write_json(path, state, durable=True)
    return state


def _reconcile_stale_companion_activation():
    """Turn an abandoned restart marker into a visible failed attempt."""
    path = _companion_update_state_path()
    state = _read_update_state(path)
    if state.get('status') != 'activation-pending':
        return state
    stamp = _parse_update_timestamp(state.get('updated_at'))
    stale = stamp is None or (
        datetime.now(timezone.utc) - stamp
    ).total_seconds() > COMPANION_UPDATE_TIMEOUT_SECONDS
    if not stale:
        return state
    reconciled = _write_update_state(
        path,
        status='activation-failed',
        active_version=str(state.get('active_version') or APP_VERSION)[:32],
        rollback_version=str(state.get('rollback_version') or '')[:32],
        active_sha256='',
        error_code='activation-timeout',
    )
    write_persistent_log(
        'Companion update activation was left pending past its timeout; '
        'marked the attempt failed so a later update can retry.'
    )
    return reconciled


def read_update_recovery_status():
    """Return the allowlisted, path-free updater state exposed by /health."""
    result = {}
    for wire_name, path in (
        ('ytDlp', _ytdlp_update_state_path()),
        ('companion', _companion_update_state_path()),
    ):
        state = _read_update_state(path)
        if not state:
            continue
        public = {}
        for source, target in (
            ('status', 'status'),
            ('active_version', 'activeVersion'),
            ('rollback_version', 'rollbackVersion'),
            ('error_code', 'errorCode'),
            ('updated_at', 'updatedAt'),
        ):
            value = state.get(source)
            if isinstance(value, str) and value:
                public[target] = value[:80]
        if public:
            result[wire_name] = public
    return result


def log_update_recovery_status():
    for product, state in read_update_recovery_status().items():
        write_persistent_log(
            f'Update recovery {product}: status {state.get("status", "unknown")}; '
            f'active {state.get("activeVersion", "unknown")}; '
            f'rollback {state.get("rollbackVersion", "not retained")}.'
        )


def _probe_ytdlp_binary(path, timeout=15):
    """Return a strict yt-dlp version only when the candidate can execute."""
    try:
        result = subprocess.run(
            [str(path), '--version'],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return ''
    if result.returncode != 0:
        return ''
    output = ((result.stdout or '') + (result.stderr or '')).strip()
    version = output.splitlines()[0].strip() if output else ''
    return version[:32] if re.fullmatch(r'\d{4}\.\d{1,2}\.\d{1,2}(?:[.\w+-]*)?', version) else ''


def _parse_iso_like(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def should_check_ytdlp_update(config, interval_hours=_YTDLP_UPDATE_INTERVAL_HOURS):
    if not config:
        return True
    now = datetime.now()
    failure = _parse_iso_like(config.get("LastYtDlpUpdateFailure", ""))
    if failure is not None:
        failure_age = (now - failure).total_seconds()
        if failure_age <= _YTDLP_UPDATE_FAILURE_BACKOFF_HOURS * 3600:
            return False
    success = _parse_iso_like(config.get("LastYtDlpUpdateCheck", ""))
    if success is None:
        return True
    return (now - success).total_seconds() > interval_hours * 3600


def mark_ytdlp_update_attempt(config, *, succeeded):
    """Persist a short failure backoff or the normal successful throttle."""
    if not config:
        return
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fields = {
            "LastYtDlpUpdateAttempt": stamp,
            "LastYtDlpUpdateFailure": "" if succeeded else stamp,
        }
        if succeeded:
            fields["LastYtDlpUpdateCheck"] = stamp
        if isinstance(config, dict):
            config.update(fields)
        else:
            for key, value in fields.items():
                config.set(key, value)
            config.save()
    except Exception as e:
        write_persistent_log(f"Could not persist yt-dlp update timestamp: {e}")


def mark_ytdlp_update_check(config):
    mark_ytdlp_update_attempt(config, succeeded=True)


def _run_ytdlp_self_update(config, source_tag):
    """Update a staged yt-dlp copy, then activate it with verified rollback.

    Running ``-U`` against the live executable made a valid-but-broken update
    irreversible.  The updater now mutates a sibling staging copy, verifies
    ``--version``, retains one byte-verified last-known-good copy, atomically
    activates, and restores the backup if the post-activation probe fails.
    """
    if not _YTDLP_UPDATE_LOCK.acquire(blocking=False):
        return {
            'ok': False, 'exit_code': -1, 'stdout': '', 'stderr': '',
            'error': 'A yt-dlp update is already in progress.',
            'error_code': 'update-in-progress',
            'version_before': get_ytdlp_version() or '',
            'version_after': get_ytdlp_version() or '',
            'source': source_tag,
        }

    stage_path = INSTALL_DIR / f'.yt-dlp.update.{uuid.uuid4().hex}.exe'
    backup_path = INSTALL_DIR / YTDLP_ROLLBACK_FILENAME
    version_before = _probe_ytdlp_binary(YTDLP_PATH)
    base = {
        'exit_code': -1,
        'stdout': '',
        'stderr': '',
        'version_before': version_before,
        'version_after': version_before,
        'rollback_version': '',
        'rolled_back': False,
        'source': source_tag,
    }
    update_succeeded = False
    try:
        if not version_before:
            return {
                **base, 'ok': False,
                'error': 'The installed yt-dlp could not pass --version; update was not started.',
                'error_code': 'active-version-unverified',
            }
        try:
            atomic_copy_verified(YTDLP_PATH, stage_path)
        except Exception as exc:  # noqa: BLE001
            write_persistent_log(f'yt-dlp {source_tag} staging failed: {exc}')
            return {
                **base, 'ok': False,
                'error': 'Could not stage yt-dlp beside the active executable.',
                'error_code': 'staging-failed',
            }

        try:
            channel = str((config.get('YtDlpUpdateChannel', 'nightly') if config else 'nightly') or 'nightly').lower()
        except Exception:
            channel = 'nightly'
        if channel not in ('stable', 'nightly'):
            channel = 'nightly'
        # `--update-to <channel>@latest` both switches channel and updates,
        # replacing the old plain `-U` (which was locked to whatever channel the
        # binary shipped as — stable — and so lagged YouTube breakage).
        update_args = [str(stage_path), '--update-to', f'{channel}@latest']
        try:
            result = subprocess.run(
                update_args,
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            write_persistent_log(
                f'yt-dlp {source_tag} staged update timed out after 120 s.'
            )
            return {
                **base, 'ok': False,
                'error': 'yt-dlp -U timed out after 120 s',
                'error_code': 'update-timeout',
            }
        except Exception as exc:  # noqa: BLE001
            write_persistent_log(f'yt-dlp {source_tag} staged update error: {exc}')
            return {
                **base, 'ok': False,
                'error': 'yt-dlp -U could not be launched. Check Astra Downloader logs for details.',
                'error_code': 'update-launch-failed',
            }

        stdout = (result.stdout or '').strip()[:200]
        stderr = (result.stderr or '').strip()[:200]
        result_fields = {**base, 'exit_code': result.returncode, 'stdout': stdout, 'stderr': stderr}
        if result.returncode != 0:
            write_persistent_log(
                f'yt-dlp {source_tag} staged update failed (exit {result.returncode}): '
                f'{stderr or stdout}'
            )
            return {
                **result_fields, 'ok': False,
                'error': stderr or stdout or f'yt-dlp -U exited with code {result.returncode}',
                'error_code': 'update-command-failed',
            }

        staged_version = _probe_ytdlp_binary(stage_path)
        if not staged_version:
            write_persistent_log(f'yt-dlp {source_tag} staged binary failed --version; active copy retained.')
            return {
                **result_fields, 'ok': False,
                'error': 'Updated yt-dlp failed its staged --version check; the active copy was retained.',
                'error_code': 'staged-version-unverified',
            }

        if staged_version == version_before:
            mark_ytdlp_update_check(config)
            update_succeeded = True
            rollback_version = _probe_ytdlp_binary(backup_path) if backup_path.exists() else ''
            _write_update_state(
                _ytdlp_update_state_path(), status='current',
                active_version=version_before, rollback_version=rollback_version,
                active_sha256=_compute_sha256(YTDLP_PATH) or '', error_code='',
            )
            write_persistent_log(
                f'yt-dlp {source_tag} update checked: active {version_before}; '
                f'rollback {rollback_version or "not retained yet"}.'
            )
            return {
                **result_fields, 'ok': True, 'exit_code': 0,
                'version_after': version_before, 'rollback_version': rollback_version,
            }

        rollback_digest = atomic_copy_verified(YTDLP_PATH, backup_path)
        rollback_version = _probe_ytdlp_binary(backup_path)
        if rollback_version != version_before:
            raise RuntimeError('The retained yt-dlp backup failed its version check.')

        staged_digest = _compute_sha256(stage_path)
        if not staged_digest:
            raise RuntimeError('The staged yt-dlp update could not be hashed.')
        _durable_replace(stage_path, YTDLP_PATH)
        active_version = _probe_ytdlp_binary(YTDLP_PATH)
        active_digest = _compute_sha256(YTDLP_PATH)
        if active_version != staged_version or active_digest != staged_digest:
            atomic_copy_verified(backup_path, YTDLP_PATH)
            restored_version = _probe_ytdlp_binary(YTDLP_PATH)
            restored_digest = _compute_sha256(YTDLP_PATH)
            rollback_ok = restored_version == rollback_version and restored_digest == rollback_digest
            status = 'rolled-back' if rollback_ok else 'rollback-failed'
            error_code = 'post-update-health-failed' if rollback_ok else 'rollback-verification-failed'
            _write_update_state(
                _ytdlp_update_state_path(), status=status,
                active_version=restored_version, rollback_version=rollback_version,
                active_sha256=restored_digest or '', rollback_sha256=rollback_digest,
                error_code=error_code,
            )
            write_persistent_log(
                f'yt-dlp {source_tag} activation failed; rollback {rollback_version} '
                f'{"restored" if rollback_ok else "could not be verified"}.'
            )
            return {
                **result_fields, 'ok': False, 'version_after': restored_version,
                'rollback_version': rollback_version, 'rolled_back': rollback_ok,
                'error': (
                    f'Updated yt-dlp failed post-update health; '
                    f'{"restored " + rollback_version if rollback_ok else "automatic rollback could not be verified"}.'
                ),
                'error_code': error_code,
            }

        mark_ytdlp_update_check(config)
        update_succeeded = True
        _ytdlp_version_probe.prime(active_version)
        _write_update_state(
            _ytdlp_update_state_path(), status='active',
            active_version=active_version, rollback_version=rollback_version,
            active_sha256=active_digest, rollback_sha256=rollback_digest,
            error_code='',
        )
        write_persistent_log(
            f'yt-dlp {source_tag} update active {active_version}; '
            f'last-known-good rollback {rollback_version} retained.'
        )
        return {
            **result_fields, 'ok': True, 'exit_code': 0,
            'version_after': active_version, 'rollback_version': rollback_version,
        }
    except Exception as exc:  # noqa: BLE001
        write_persistent_log(f'yt-dlp {source_tag} recoverable update failed: {exc}')
        restored = False
        rollback_version = _probe_ytdlp_binary(backup_path) if backup_path.exists() else ''
        active_version = _probe_ytdlp_binary(YTDLP_PATH) if YTDLP_PATH.exists() else ''
        if rollback_version and active_version != version_before:
            try:
                atomic_copy_verified(backup_path, YTDLP_PATH)
                active_version = _probe_ytdlp_binary(YTDLP_PATH)
                restored = active_version == rollback_version
            except Exception as restore_exc:  # noqa: BLE001
                write_persistent_log(f'yt-dlp emergency rollback failed: {restore_exc}')
        error_code = 'safe-activation-failed' if active_version == version_before or restored else 'rollback-verification-failed'
        try:
            _write_update_state(
                _ytdlp_update_state_path(),
                status='rolled-back' if restored else ('active' if active_version == version_before else 'rollback-failed'),
                active_version=active_version, rollback_version=rollback_version,
                error_code=error_code,
            )
        except Exception as state_exc:  # noqa: BLE001
            write_persistent_log(f'Could not persist yt-dlp recovery state: {state_exc}')
        return {
            **base, 'ok': False, 'version_after': active_version,
            'rollback_version': rollback_version, 'rolled_back': restored,
            'error': (
                'Could not safely install the yt-dlp update. '
                + ('The last-known-good copy was restored.' if restored else 'The active copy was retained.')
            ),
            'error_code': error_code,
        }
    finally:
        if not update_succeeded:
            mark_ytdlp_update_attempt(config, succeeded=False)
        try:
            stage_path.unlink(missing_ok=True)
        except Exception:
            # reason: update staging cleanup is best-effort after activation or rollback
            pass
        _YTDLP_UPDATE_LOCK.release()


def maybe_auto_update_ytdlp(config, active_count_fn=None):
    """Background-run yt-dlp -U when more than a day has passed.

    Fire-and-forget in a daemon thread so startup isn't blocked. The exit code
    is logged (previously swallowed entirely).

    v4.47.0 NF26: when ``active_count_fn`` is provided and returns > 0, the
    update is deferred. yt-dlp's ``-U`` flag atomically replaces the binary,
    and on Windows the in-flight ``subprocess.Popen([YTDLP_PATH, ...])`` of
    an active download can race the replace with file-in-use errors. Callers
    in the GUI / server path pass ``dl_manager.active_count`` so the check
    consults the live queue without coupling this function to the manager
    instance.

    The check is racy by design — we accept that a download started during
    the millisecond between ``active_count_fn()`` returning 0 and ``-U``
    spawning the replacement process can still race. Mitigation in practice
    is that ``-U`` runs ahead of any user download (server-start hook), and
    a download starting in that micro-window is so unlikely we don't pay the
    cost of a hard cross-process lock.

    v4.47.0 NF18: the subprocess runner was extracted into
    ``_run_ytdlp_self_update`` so the on-demand ``/update-ytdlp`` endpoint
    can share the same logging + version-cache + throttle-marker semantics.
    """
    if not YTDLP_PATH.exists():
        return
    if not config.get("AutoUpdateYtDlp", True):
        return
    if not should_check_ytdlp_update(config):
        return
    if active_count_fn is not None:
        try:
            in_flight = int(active_count_fn() or 0)
        except Exception as e:  # noqa: BLE001
            # The update replaces an executable used by active workers.  An
            # unknown activity state is therefore unsafe; defer and retry on
            # the next scheduled check instead of failing open into a race.
            write_persistent_log(
                f"yt-dlp auto-update deferred — active-count probe failed: {e}"
            )
            return
        if in_flight > 0:
            write_persistent_log(
                f"yt-dlp auto-update deferred — {in_flight} active download(s); "
                f"next check at the configured 24h throttle."
            )
            return

    threading.Thread(
        target=lambda: _run_ytdlp_self_update(config, source_tag='auto'),
        daemon=True,
    ).start()


# ── v4.47.0 NF6: companion self-update helpers ──
def parse_companion_version_source(source_text):
    """Extract APP_VERSION from the raw astra_downloader.py source."""
    if not isinstance(source_text, str):
        return ''
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']{1,32})["\']', source_text, re.MULTILINE)
    return m.group(1).strip() if m else ''


def parse_companion_release_tag(payload):
    """Return the release tag from a GitHub release payload, or ''.

    The tag is pasted into a raw.githubusercontent URL, so it is validated
    against the repository's own tag shape rather than trusted verbatim.
    """
    if not isinstance(payload, dict):
        return ''
    tag = str(payload.get('tag_name') or '').strip()
    if payload.get('draft') or payload.get('prerelease'):
        return ''
    return tag if re.fullmatch(r'v\d+\.\d+\.\d+', tag) else ''


def _header_int(headers, name):
    try:
        value = headers.get(name)
        return int(value) if value is not None and str(value).strip() else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def observe_github_api_budget(response):
    """Record anonymous GitHub rate-limit headers without retaining a token."""
    headers = getattr(response, 'headers', {}) or {}
    remaining = _header_int(headers, 'X-RateLimit-Remaining')
    limit = _header_int(headers, 'X-RateLimit-Limit')
    reset_at = _header_int(headers, 'X-RateLimit-Reset')
    if remaining is None and limit is None and reset_at is None:
        return get_github_api_budget()
    snapshot = {
        'remaining': max(0, remaining) if remaining is not None else None,
        'limit': max(0, limit) if limit is not None else None,
        'resetAt': max(0, reset_at) if reset_at is not None else None,
        'source': 'github-api',
    }
    with _GITHUB_API_BUDGET_LOCK:
        _GITHUB_API_BUDGET.update(snapshot)
        return dict(_GITHUB_API_BUDGET)


def get_github_api_budget():
    with _GITHUB_API_BUDGET_LOCK:
        return dict(_GITHUB_API_BUDGET)


def fetch_latest_companion_release_tag(timeout=15):
    """Resolve the newest published Release tag for this repository."""
    response = http_requests.get(
        COMPANION_UPDATE_RELEASE_API_URL,
        timeout=timeout,
        headers={'Accept': 'application/vnd.github+json'},
    )
    observe_github_api_budget(response)
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError('Could not read the latest Astra Downloader release.') from exc
    tag = parse_companion_release_tag(payload)
    if not tag:
        raise RuntimeError('No published Astra Downloader release is available.')
    return tag


def fetch_latest_companion_version(timeout=15):
    """Read the companion APP_VERSION from the newest published Release.

    Sourced from the release tag, never from a branch: the update installs a
    Release asset, so a bump that has not been released must not advertise one.
    """
    tag = fetch_latest_companion_release_tag(timeout=timeout)
    with http_requests.get(
        COMPANION_UPDATE_VERSION_URL_TEMPLATE.format(tag=tag), stream=True, timeout=timeout,
    ) as response:
        response.raise_for_status()
        try:
            advertised = int(response.headers.get('content-length', '') or 0)
        except (TypeError, ValueError):
            advertised = 0
        if advertised > COMPANION_VERSION_SOURCE_MAX_BYTES:
            raise RuntimeError('Companion version source exceeded its size limit.')
        source = bytearray()
        for chunk in response.iter_content(8192):
            if not chunk:
                continue
            source.extend(chunk)
            if len(source) > COMPANION_VERSION_SOURCE_MAX_BYTES:
                raise RuntimeError('Companion version source exceeded its size limit.')
    version = parse_companion_version_source(source.decode('utf-8', errors='replace'))
    if not version:
        raise RuntimeError('Could not read APP_VERSION from the update manifest.')
    return version


def validate_companion_update_binary(path):
    """Cheap integrity sanity check before scheduling an exe replacement."""
    path = Path(path)
    if not path.exists():
        raise RuntimeError('Downloaded Astra Downloader update is missing.')
    if path.stat().st_size < COMPANION_UPDATE_MIN_BYTES:
        raise RuntimeError('Downloaded Astra Downloader update is too small to trust.')
    with open(path, 'rb') as fh:
        header = fh.read(2)
    if header != b'MZ':
        raise RuntimeError('Downloaded Astra Downloader update is not a Windows executable.')
    return True


def probe_companion_update_binary(path, expected_version, timeout=30):
    """Run the staged companion's non-GUI startup check in the background."""
    expected_version = str(expected_version or '').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', expected_version):
        return False
    try:
        result = subprocess.run(
            [str(path), '--update-health-check', str(expected_version)],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001
        write_persistent_log(f'Companion staged health check could not launch: {exc}')
        return False
    return result.returncode == 0


# Audit fix (version-skew loop): "update available" is decided by parsing
# APP_VERSION from the repo's main branch, but the artifact comes from
# releases/latest. When main is bumped before the release asset is published,
# releases/latest still serves the binary we're already running — every
# /update cycle would download the same exe, pass MZ/size/SHA validation,
# schedule a replace, restart, and report update_available again, forever.
# We persist the SHA-256 of the last update this install scheduled and refuse
# to schedule a replace whose digest matches it (or matches the running
# frozen binary). A genuinely newer release has a different digest, so it
# still installs normally.
def read_last_installed_update_sha256():
    """Lowercase hex digest of the last successfully activated update, or None."""
    data = load_json_file(_companion_update_state_path(), {})
    if not isinstance(data, dict):
        return None
    # Older state files had no status and are still valid. Once the recovery
    # helper has written a status, only an active install may suppress a retry;
    # activation and rollback failures must leave the release available again.
    status = str(data.get('status') or '').strip().lower()
    if status and status != 'active':
        return None
    value = data.get('sha256')
    if isinstance(value, str):
        value = value.strip().lower()
        if re.fullmatch(r'[0-9a-f]{64}', value):
            return value
    return None


def record_last_installed_update_sha256(digest, *, status='active'):
    """Persist an update digest with an explicit activation status.

    The detached helper changes ``activation-pending`` to ``active`` only
    after replacement and a post-activation health probe. Recording the
    verified digest before detaching keeps one state writer in the normal
    production path without making a merely scheduled update suppress a
    retry.
    """
    try:
        _write_update_state(
            _companion_update_state_path(),
            sha256=str(digest).strip().lower(),
            status=str(status or 'active').strip().lower(),
            recorded_at=_utc_timestamp(),
            app_version=APP_VERSION,
        )
    except Exception as e:  # noqa: BLE001
        write_persistent_log(f"Could not persist companion update state: {e}")


def _safe_update_paths(update_path, target_path=None):
    install_root = INSTALL_DIR.resolve()
    update = Path(update_path).resolve()
    target = Path(target_path or install_target_exe()).resolve()
    if target.name != 'AstraDownloader.exe':
        raise RuntimeError(f'Refusing to update unexpected target: {target}')
    if target.parent != install_root:
        raise RuntimeError(f'Refusing to update outside install dir: {target}')
    if update.parent != install_root or not update.name.startswith('.AstraDownloader.update.'):
        raise RuntimeError(f'Refusing to apply untrusted update path: {update}')
    return update, target


def schedule_companion_update_restart(
    update_path, target_path=None, restart_args=None, pid=None,
    expected_sha256=None, expected_version='', previous_version='',
):
    """Schedule after-exit replacement and relaunch of AstraDownloader.exe.

    The running PyInstaller executable cannot be overwritten in-place on
    Windows. A detached helper waits for this PID to exit, re-verifies the
    staged binary's SHA-256 and startup check, retains one verified backup,
    atomically replaces the managed executable, repeats the startup check, and
    restores the backup before relaunch if post-activation health fails.
    """
    update, target = _safe_update_paths(update_path, target_path)
    restart_args = list(restart_args or ['--start-server'])
    current_pid = int(pid or os.getpid())
    expected_digest = str(expected_sha256 or '').strip().lower()
    expected_version = str(expected_version or '').strip()[:32]
    previous_version = str(previous_version or '').strip()[:32]
    if not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
        raise RuntimeError('A verified SHA-256 is required to schedule the companion update.')
    version_pattern = r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?'
    if not re.fullmatch(version_pattern, expected_version) or not re.fullmatch(version_pattern, previous_version):
        raise RuntimeError('Both active and target companion versions are required for rollback.')
    backup = INSTALL_DIR / COMPANION_ROLLBACK_FILENAME
    state_path = _companion_update_state_path()
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == 'win32':
        script = INSTALL_DIR / f".AstraDownloader.apply-update.{uuid.uuid4().hex}.ps1"
        script.write_text(r'''
param(
    [int] $ProcessId,
    [string] $SourcePath,
    [string] $TargetPath,
    [string] $BackupPath,
    [string] $StatePath,
    [string] $RestartArgs,
    [string] $ExpectedSHA256,
    [string] $ExpectedVersion,
    [string] $PreviousVersion
)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class AstraDeckMoveFile {
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern bool MoveFileEx(string existingFileName, string newFileName, int flags);
}
'@
$MOVEFILE_REPLACE_EXISTING = 0x1
$MOVEFILE_WRITE_THROUGH = 0x8
$flags = $MOVEFILE_REPLACE_EXISTING -bor $MOVEFILE_WRITE_THROUGH

function Move-Replace([string] $Source, [string] $Destination) {
    $ok = [AstraDeckMoveFile]::MoveFileEx($Source, $Destination, $flags)
    if (-not $ok) {
        $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "MoveFileEx failed with Win32 error $err"
    }
}

function Copy-Verified([string] $Source, [string] $Destination) {
    $temp = "$Destination.$([Guid]::NewGuid().ToString('N')).tmp"
    Copy-Item -LiteralPath $Source -Destination $temp -Force
    $sourceHash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLower()
    $copyHash = (Get-FileHash -LiteralPath $temp -Algorithm SHA256).Hash.ToLower()
    if ($sourceHash -ne $copyHash) { throw 'Retained backup digest mismatch' }
    Move-Replace $temp $Destination
    return $sourceHash
}

function Test-Companion([string] $Path, [string] $Version) {
    $probe = Start-Process -FilePath $Path -ArgumentList @('--update-health-check', $Version) -WindowStyle Hidden -PassThru
    $probeFinished = $false
    try {
        # A very short health probe can exit between Start-Process and
        # Wait-Process. In that race Wait-Process reports "process not found"
        # even though the probe completed successfully. Read live state first
        # and re-check it after any wait failure before declaring a bad build.
        $probe.Refresh()
        if ($probe.HasExited) {
            $probeFinished = $true
        } else {
            Wait-Process -Id $probe.Id -Timeout 30 -ErrorAction Stop | Out-Null
            $probe.Refresh()
            $probeFinished = $probe.HasExited
        }
    } catch {
        try {
            $probe.Refresh()
            $probeFinished = $probe.HasExited
        } catch {
            # The process object can lose its handle after a fast exit. A
            # missing live process is still a completed probe; its ExitCode
            # remains available on the original Process object when possible.
            $probeFinished = $null -eq (Get-Process -Id $probe.Id -ErrorAction SilentlyContinue)
        }
    }
    if (-not $probeFinished) {
        try { Stop-Process -Id $probe.Id -Force -ErrorAction SilentlyContinue } catch {}
        return $false
    }
    return $probe.ExitCode -eq 0
}

function Write-RecoveryState([string] $Status, [string] $ActiveVersion, [string] $RollbackVersion, [string] $ErrorCode) {
    $state = [ordered]@{
        sha256 = if ($Status -eq 'active') { $ExpectedSHA256.ToLower() } else { '' }
        app_version = $ExpectedVersion
        status = $Status
        active_version = $ActiveVersion
        rollback_version = $RollbackVersion
        error_code = $ErrorCode
        updated_at = [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    }
    $temp = "$StatePath.$([Guid]::NewGuid().ToString('N')).tmp"
    $json = $state | ConvertTo-Json
    $encoding = New-Object Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($json + [Environment]::NewLine)
    $stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    } finally {
        $stream.Dispose()
    }
    Move-Replace $temp $StatePath
}

$activated = $false
try {
    try { Wait-Process -Id $ProcessId -Timeout 45 } catch { Start-Sleep -Seconds 2 }
    $sourceHash = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash.ToLower()
    if ($sourceHash -ne $ExpectedSHA256.ToLower()) { throw 'Staged update digest changed before activation' }
    if (-not (Test-Companion $SourcePath $ExpectedVersion)) { throw 'Staged update health check failed' }
    if (-not (Test-Path -LiteralPath $TargetPath)) { throw 'Managed companion target is missing' }
    $rollbackHash = Copy-Verified $TargetPath $BackupPath
    Move-Replace $SourcePath $TargetPath
    $activated = $true
    $targetHash = (Get-FileHash -LiteralPath $TargetPath -Algorithm SHA256).Hash.ToLower()
    if ($targetHash -ne $ExpectedSHA256.ToLower() -or -not (Test-Companion $TargetPath $ExpectedVersion)) {
        throw 'Post-update companion health check failed'
    }
    Write-RecoveryState 'active' $ExpectedVersion $PreviousVersion ''
} catch {
    if ($activated -and (Test-Path -LiteralPath $BackupPath)) {
        try {
            Copy-Verified $BackupPath $TargetPath | Out-Null
            if (-not (Test-Companion $TargetPath $PreviousVersion)) { throw 'Restored companion health check failed' }
            Write-RecoveryState 'rolled-back' $PreviousVersion $PreviousVersion 'post-update-health-failed'
        } catch {
            Write-RecoveryState 'rollback-failed' '' $PreviousVersion 'rollback-verification-failed'
        }
    } else {
        Write-RecoveryState 'activation-failed' $PreviousVersion $PreviousVersion 'staged-health-failed'
    }
} finally {
    if (Test-Path -LiteralPath $TargetPath) {
        Start-Process -FilePath $TargetPath -ArgumentList $RestartArgs -WindowStyle Hidden
    }
    Remove-Item -LiteralPath $SourcePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}
'''.lstrip(), encoding='utf-8')
        args = [
            'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(script),
            '-ProcessId', str(current_pid),
            '-SourcePath', str(update),
            '-TargetPath', str(target),
            '-BackupPath', str(backup),
            '-StatePath', str(state_path),
            '-RestartArgs', command_line(restart_args),
            '-ExpectedSHA256', expected_digest,
            '-ExpectedVersion', expected_version,
            '-PreviousVersion', previous_version,
        ]
        subprocess.Popen(args, creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
    else:
        script = INSTALL_DIR / f".AstraDownloader.apply-update.{uuid.uuid4().hex}.py"
        script.write_text('''\
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

pid = int(sys.argv[1])
source = sys.argv[2]
target = sys.argv[3]
backup = sys.argv[4]
state_path = sys.argv[5]
expected_sha256 = sys.argv[6]
expected_version = sys.argv[7]
previous_version = sys.argv[8]
restart_args = sys.argv[9:]

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest().lower()

def durable_replace(source_path, destination_path):
    os.replace(source_path, destination_path)
    try:
        directory_fd = os.open(os.path.dirname(destination_path) or '.', os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

def atomic_copy(source_path, destination_path):
    temp = destination_path + '.' + uuid.uuid4().hex + '.tmp'
    shutil.copyfile(source_path, temp)
    if digest(source_path) != digest(temp):
        raise RuntimeError('Retained backup digest mismatch')
    durable_replace(temp, destination_path)

def healthy(path, version):
    return subprocess.run(
        [path, '--update-health-check', version],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
    ).returncode == 0

def write_state(status, active_version, rollback_version, error_code):
    payload = {
        'sha256': expected_sha256 if status == 'active' else '',
        'app_version': expected_version,
        'status': status, 'active_version': active_version,
        'rollback_version': rollback_version, 'error_code': error_code,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
    }
    temp = state_path + '.' + uuid.uuid4().hex + '.tmp'
    with open(temp, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    durable_replace(temp, state_path)

deadline = time.time() + 45
while time.time() < deadline:
    try:
        os.kill(pid, 0)
    except OSError:
        break
    time.sleep(0.25)
activated = False
try:
    if digest(source) != expected_sha256.lower() or not healthy(source, expected_version):
        raise RuntimeError('Staged companion verification failed')
    atomic_copy(target, backup)
    durable_replace(source, target)
    activated = True
    if digest(target) != expected_sha256.lower() or not healthy(target, expected_version):
        raise RuntimeError('Post-update companion health check failed')
    write_state('active', expected_version, previous_version, '')
except Exception:
    if activated and os.path.exists(backup):
        try:
            atomic_copy(backup, target)
            if not healthy(target, previous_version):
                raise RuntimeError('Restored companion health check failed')
            write_state('rolled-back', previous_version, previous_version, 'post-update-health-failed')
        except Exception:
            write_state('rollback-failed', '', previous_version, 'rollback-verification-failed')
    else:
        write_state('activation-failed', previous_version, previous_version, 'staged-health-failed')
finally:
    if os.path.exists(target):
        subprocess.Popen([target] + restart_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(source)
    except OSError:
        # reason: the source may already be removed after the replacement handoff
        pass
    try:
        os.remove(__file__)
    except OSError:
        # reason: self-delete is best-effort after the updater process has detached
        pass
''', encoding='utf-8')
        subprocess.Popen([
            sys.executable, str(script), str(current_pid), str(update), str(target),
            str(backup), str(state_path), expected_digest, expected_version,
            previous_version,
        ] + restart_args)
    return {
        'scheduled': True, 'target': str(target), 'source': str(update),
        'rollback': str(backup), 'active_version': expected_version,
        'rollback_version': previous_version,
    }


def schedule_companion_process_exit(delay=0.6):
    """Exit after the HTTP response has a chance to flush."""
    def _exit_later():
        time.sleep(delay)
        write_persistent_log('Exiting for Astra Downloader self-update.')
        os._exit(0)

    threading.Thread(target=_exit_later, daemon=True, name='AstraDownloaderSelfUpdateExit').start()


def _run_companion_self_update(restart=True, dl_manager=None):
    if not _COMPANION_UPDATE_LOCK.acquire(blocking=False):
        return {
            'ok': False,
            'error': 'An Astra Downloader update is already in progress.',
            'error_code': 'update-in-progress',
            'current_version': APP_VERSION,
            'latest_version': '',
        }
    # TOCTOU guard: the /update route checks active_count() once at entry, but
    # the version fetch + exe download + SHA fetch + staged health probe below
    # can take minutes. Pause download intake for the duration so a /download
    # or /queue/resume accepted on another waitress thread cannot spawn a
    # yt-dlp tree that os._exit(0) would orphan; resume on every outcome that
    # leaves this process running.
    intake_was_paused = True
    intake_paused_here = False
    if dl_manager is not None:
        intake_was_paused = bool(getattr(dl_manager, 'intake_paused', False))
        if not intake_was_paused:
            if dl_manager.pause_intake():
                intake_paused_here = True
            else:
                write_persistent_log(
                    'Companion update: could not pause download intake; '
                    'relying on the pre-restart in-flight re-check.'
                )
    try:
        result = _run_companion_self_update_unlocked(restart=restart, dl_manager=dl_manager)
        if (intake_paused_here and restart and result.get('ok')
                and result.get('status') == 'restart_scheduled'):
            # This process is about to os._exit(0): keep the live intake pause
            # so nothing can spawn yt-dlp in the exit window, but persist the
            # user's pre-update flag so the relaunched companion doesn't come
            # up silently paused.
            intake_paused_here = False
            try:
                dl_manager.persist_intake_flag(intake_was_paused)
            except Exception as e:  # noqa: BLE001
                write_persistent_log(f"Companion update: could not persist the pre-update intake flag: {e}")
        return result
    finally:
        try:
            if intake_paused_here:
                dl_manager.resume_intake()
        finally:
            _COMPANION_UPDATE_LOCK.release()


def _run_companion_self_update_unlocked(restart=True, dl_manager=None):
    current_version = APP_VERSION
    if is_portable_mode() and is_onedir_build():
        return {
            'ok': False,
            'error': (
                'The one-folder portable build cannot replace only its executable. '
                'Download the next one-folder archive to update it.'
            ),
            'error_code': 'portable-onedir-update-unsupported',
            'current_version': current_version,
            'latest_version': '',
        }
    try:
        latest_version = fetch_latest_companion_version()
    except Exception as e:  # noqa: BLE001
        write_persistent_log(f"Companion update version check failed: {e}")
        return {
            'ok': False,
            'error': 'Could not check latest Astra Downloader version. Check Astra Downloader logs for details.',
            'error_code': 'version-check-failed',
            'current_version': current_version,
            'latest_version': '',
        }

    if _compare_semver(latest_version, current_version) <= 0:
        return {
            'ok': True,
            'update_available': False,
            'status': 'current',
            'current_version': current_version,
            'latest_version': latest_version,
        }

    update_path = INSTALL_DIR / f".AstraDownloader.update.{uuid.uuid4().hex}.exe"
    try:
        download_file_atomic(
            COMPANION_UPDATE_EXE_URL,
            update_path,
            timeout=COMPANION_UPDATE_TIMEOUT_SECONDS,
            chunk_size=65536,
        )
        validate_companion_update_binary(update_path)
        expected_hash = fetch_expected_sha256(
            COMPANION_UPDATE_SHA256_URL,
            target_asset='AstraDownloader.exe',
            timeout=15,
        )
        if not expected_hash:
            try:
                update_path.unlink(missing_ok=True)
            except Exception:
                # reason: failed update cleanup may already have been completed by recovery
                pass
            return {
                'ok': False,
                'error': 'Could not install Astra Downloader update: SHA-256 sidecar unavailable.',
                'error_code': 'sha256-sidecar-missing',
                'current_version': current_version,
                'latest_version': latest_version,
            }
        try:
            verify_file_sha256(update_path, expected_hash)
        except Exception as e:  # noqa: BLE001
            write_persistent_log(f"Companion update SHA-256 verification failed: {e}")
            try:
                update_path.unlink(missing_ok=True)
            except Exception:
                # reason: failed hash cleanup is best-effort before returning the verification error
                pass
            return {
                'ok': False,
                'error': 'Could not install Astra Downloader update: SHA-256 verification failed.',
                'error_code': 'sha256-verification-failed',
                'current_version': current_version,
                'latest_version': latest_version,
            }
        if not probe_companion_update_binary(update_path, latest_version):
            try:
                update_path.unlink(missing_ok=True)
            except Exception:
                # reason: staged health-check cleanup is best-effort before returning the failure
                pass
            return {
                'ok': False,
                'error': 'Downloaded Astra Downloader update failed its staged startup check.',
                'error_code': 'staged-health-check-failed',
                'current_version': current_version,
                'latest_version': latest_version,
            }
        # Version-skew guard (see read_last_installed_update_sha256): the
        # artifact digest equals expected_hash — verify_file_sha256 just
        # proved it — so compare that against the running frozen binary and
        # the last update this install activated. A match means the
        # releases/latest asset has not actually changed (main's APP_VERSION
        # was bumped ahead of the release), and installing it again can only
        # loop, never advance the version.
        downloaded_digest = str(expected_hash).strip().lower()
        same_as_running = False
        if is_frozen_app():
            try:
                same_as_running = _compute_sha256(current_executable_path()) == downloaded_digest
            except Exception:
                # reason: a missing or changing running binary simply cannot prove digest equality
                same_as_running = False
        if same_as_running or downloaded_digest == read_last_installed_update_sha256():
            try:
                update_path.unlink(missing_ok=True)
            except Exception:
                # reason: duplicate-release cleanup is best-effort after the digest comparison
                pass
            write_persistent_log(
                f"Companion update skipped: releases/latest asset (sha256 "
                f"{downloaded_digest[:12]}...) matches the installed binary; the "
                f"release for {latest_version} is not published yet."
            )
            return {
                'ok': True,
                'update_available': False,
                'status': 'release-pending',
                'current_version': current_version,
                'latest_version': latest_version,
            }
        # Re-check in-flight work immediately before committing to the
        # restart. The route's entry check ran minutes ago (download +
        # verification above); anything accepted since then would be
        # orphaned by schedule_companion_process_exit's os._exit(0).
        if dl_manager is not None:
            in_flight = dl_manager.active_count()
            if in_flight > 0:
                try:
                    update_path.unlink(missing_ok=True)
                except Exception:
                    # reason: in-flight update cleanup is best-effort before returning the guard error
                    pass
                write_persistent_log(
                    f"Companion update aborted: {in_flight} download(s) started "
                    f"while the update was being prepared."
                )
                return {
                    'ok': False,
                    'error': f"{in_flight} download(s) in flight — wait for them to finish, then try again. "
                             f"The companion update must restart Astra Downloader after atomically replacing the executable.",
                    'error_code': 'downloads-in-flight',
                    'inFlight': in_flight,
                    'current_version': current_version,
                    'latest_version': latest_version,
                }
        _write_update_state(
            _companion_update_state_path(), status='activation-pending',
            active_version=current_version, rollback_version=current_version,
            active_sha256='', rollback_sha256='', error_code='',
        )
        restart_args = ['--start-server']
        if is_portable_mode():
            restart_args.append('--portable')
        try:
            schedule = schedule_companion_update_restart(
                update_path, install_target_exe(), restart_args,
                expected_sha256=downloaded_digest,
                expected_version=latest_version,
                previous_version=current_version,
            )
            # The detached helper is still authoritative for the final
            # ``active`` state, but production records the verified digest
            # before it exits so an interrupted handoff is diagnosable and
            # cannot be mistaken for an already-installed release.
            record_last_installed_update_sha256(
                downloaded_digest, status='activation-pending'
            )
            if restart:
                schedule_companion_process_exit()
        except Exception as schedule_error:  # noqa: BLE001
            write_persistent_log(f"Companion update scheduling failed: {schedule_error}")
            try:
                _write_update_state(
                    _companion_update_state_path(), status='activation-failed',
                    active_version=current_version, rollback_version=current_version,
                    active_sha256='', rollback_sha256='', error_code='schedule-failed',
                )
            except Exception as state_error:  # noqa: BLE001
                write_persistent_log(
                    f"Could not persist failed companion update scheduling state: {state_error}"
                )
            try:
                update_path.unlink(missing_ok=True)
            except Exception:
                # reason: failed scheduling cleanup is best-effort after the terminal state is recorded
                pass
            return {
                'ok': False,
                'error': 'Could not schedule Astra Downloader to restart for the update.',
                'error_code': 'schedule-failed',
                'current_version': current_version,
                'latest_version': latest_version,
            }
        write_persistent_log(
            f"Companion update scheduled ({current_version} -> {latest_version}) via {update_path}"
        )
        return {
            'ok': True,
            'update_available': True,
            'status': 'restart_scheduled',
            'current_version': current_version,
            'latest_version': latest_version,
            'active_version': latest_version,
            'rollback_version': current_version,
            'restart': bool(restart),
            'target': schedule.get('target'),
        }
    except Exception as e:  # noqa: BLE001
        write_persistent_log(f"Companion update failed: {e}")
        try:
            update_path.unlink(missing_ok=True)
        except Exception:
            # reason: failed update cleanup is best-effort after the primary error is recorded
            pass
        return {
            'ok': False,
            'error': 'Could not install Astra Downloader update. Check Astra Downloader logs for details.',
            'error_code': 'install-failed',
            'current_version': current_version,
            'latest_version': latest_version,
        }


# ── v1.2.0: integrations stamp (idempotent shortcut/protocol/task registration) ──
def _get_integrations_stamp():
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTEGRATIONS_STAMP_KEY)
        try:
            value, _ = winreg.QueryValueEx(key, INTEGRATIONS_STAMP_VALUE)
            return value
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _set_integrations_stamp():
    if sys.platform != 'win32':
        return
    try:
        import winreg
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, INTEGRATIONS_STAMP_KEY, 0, winreg.KEY_WRITE)
        try:
            winreg.SetValueEx(key, INTEGRATIONS_STAMP_VALUE, 0, winreg.REG_SZ, APP_VERSION)
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        write_persistent_log(f"Could not persist integrations stamp: {e}")


def normalize_long_text(value, default="", max_len=MAX_TEXT_FIELD):
    if value is None:
        return default, False
    value = CONTROL_CHARS_RE.sub("", str(value)).strip()
    if len(value) > max_len:
        return value, True
    return value, False


def ps_single_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def write_cookies_netscape(cookies, target_path):
    return _owned_write_cookies_netscape(
        cookies,
        target_path,
        logger=write_persistent_log,
    )


def is_frozen_app():
    return bool(getattr(sys, "frozen", False))


def is_portable_mode():
    """Return whether this process must avoid per-user installation state."""
    return bool(PORTABLE_MODE)


def current_executable_path():
    if is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(__file__).resolve()


def is_onedir_build():
    """Return whether the running frozen app needs sibling files to start."""
    if not is_frozen_app():
        return False
    executable = current_executable_path()
    return (executable.parent / "_internal").is_dir()


def install_target_exe():
    if is_portable_mode():
        return current_executable_path()
    return INSTALL_DIR / "AstraDownloader.exe"


def _probe_companion_version(path, timeout=15):
    """Read a frozen companion's version without opening its GUI."""
    try:
        result = subprocess.run(
            [str(path), '--version'],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    if result.returncode != 0:
        return ''
    version_pattern = r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?'
    for line in (result.stdout or '').splitlines():
        value = line.strip()
        if re.fullmatch(version_pattern, value):
            return value
    return ''


def ensure_installed_executable(*, allow_downgrade=False):
    """Install the running frozen exe without silently replacing a newer one.

    ``allow_downgrade`` is deliberately explicit for a future repair or user
    initiated rollback path. Ordinary launches always preserve a newer managed
    binary and use the byte-verified copy primitive for replacement.
    """
    current = current_executable_path()
    if not is_frozen_app() or is_portable_mode() or is_onedir_build():
        return current

    target = install_target_exe()
    try:
        if current == target.resolve():
            return target
    except Exception:
        # reason: an unavailable target path only disables the same-file fast path
        pass

    try:
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        if target.exists() and not allow_downgrade:
            installed_version = _probe_companion_version(target)
            if installed_version and _compare_semver(installed_version, APP_VERSION) > 0:
                write_persistent_log(
                    f"Kept newer installed executable {installed_version}; "
                    f"running copy is {APP_VERSION}."
                )
                return target
        atomic_copy_verified(current, target)
        write_persistent_log(f"Installed executable updated: {target}")
        return target
    except Exception as e:
        write_persistent_log(f"Could not update installed executable from {current}: {e}")
        return current


def launch_command_parts(prefer_installed=True):
    if is_frozen_app():
        exe = ensure_installed_executable() if prefer_installed else current_executable_path()
        return str(exe), []
    return sys.executable, [str(Path(__file__).resolve())]


def command_line(parts):
    return subprocess.list2cmdline([str(p) for p in parts])


PROTOCOL_SCHEMES = ('ytdl://', 'mediadl://')


def download_url_from_protocol_argv(argv=None):
    """The URL a `ytdl://` or `mediadl://` launch is asking us to download.

    The handlers are registered as `<exe> "%1"`, so the browser hands over the
    whole link. Returns '' for a bare `ytdl://start`, which means "just bring
    the app up", and for anything the URL policy rejects.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    for arg in args:
        raw = str(arg).strip()
        lowered = raw.lower()
        for scheme in PROTOCOL_SCHEMES:
            if not lowered.startswith(scheme):
                continue
            payload = raw[len(scheme):].strip()
            if not payload or payload.strip('/').lower() == 'start':
                return ''
            payload = unquote(payload)
            if '://' not in payload:
                # A bare word is one of the legacy "just open the app" forms
                # (ytdl://start, ytdl://download), not a host.
                host = payload.lstrip('/').split('/', 1)[0].split('?', 1)[0]
                if '.' not in host:
                    return ''
                payload = 'https://' + payload.lstrip('/')
            normalized, error = normalize_url(payload)
            return '' if error else normalized
    return ''


def startup_command_from_argv(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    for arg in args:
        value = str(arg).strip().lower()
        if value in ('--start-server', '-start-server', 'start'):
            return 'start'
        if value.startswith(PROTOCOL_SCHEMES):
            url = download_url_from_protocol_argv([arg])
            # A protocol link naming a video is a request to download it; the
            # handler used to map every one of them to 'start', so clicking a
            # ytdl:// link launched the app and queued nothing.
            return f'download {url}' if url else 'start'
    return ''


def instance_control_token():
    """Shared secret for the loopback instance-control port.

    The only legitimate senders are a second copy of this program and the
    uninstaller, and both can read the config the running instance wrote. No
    other local process can, which is the point: without a secret, anything
    running as this user could send `shutdown` and kill a download in flight.
    """
    try:
        return str(Config(read_only=True).get("ServerToken") or '')
    except Exception as error:
        write_persistent_log(f"Could not read the instance control token: {error}")
        return ''


def send_instance_command(command, host=INSTANCE_CONTROL_HOST, port=INSTANCE_CONTROL_PORT,
                          attempts=5, delay=0.2, token=None):
    command = str(command or '').strip()
    if command.lower() in {'show', 'start', 'shutdown'}:
        command = command.lower()
    elif not command.lower().startswith('download '):
        # A download command carries a URL, whose case must survive.
        return False
    if token is None:
        token = instance_control_token()
    payload = (f"{token} {command}" + '\n').encode('ascii', errors='ignore')
    for attempt in range(max(1, int(attempts))):
        try:
            with socket.create_connection((host, int(port)), timeout=0.5) as conn:
                conn.sendall(payload)
            return True
        except OSError as e:
            last_err = e
            if attempt < attempts - 1:
                time.sleep(delay)
    write_persistent_log(f"Could not send instance command '{command}': {last_err}")
    return False


SHORTCUT_NAME = "Astra Downloader.lnk"
SHORTCUT_DESCRIPTION = "Astra Deck Download Server"


def start_menu_programs_dir():
    """Return the per-user Start Menu Programs folder.

    Per-user rather than all-users: the companion installs into LOCALAPPDATA
    without elevation, so an entry under ProgramData would be a shortcut the
    installing user cannot remove.
    """
    appdata = os.environ.get('APPDATA')
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def build_shortcut_command(lnk_path, target, base_args, description=SHORTCUT_DESCRIPTION):
    """Return the PowerShell that writes one .lnk via WScript.Shell."""
    ico = str(ICON_PATH) if ICON_PATH.exists() else ""
    arguments = command_line(base_args)
    workdir = str(Path(target).parent if Path(target).parent.exists() else INSTALL_DIR)
    return (
        f'$ws = New-Object -ComObject WScript.Shell; '
        f'$sc = $ws.CreateShortcut({ps_single_quote(lnk_path)}); '
        f'$sc.TargetPath = {ps_single_quote(target)}; '
        f'$sc.WorkingDirectory = {ps_single_quote(workdir)}; '
        f'$sc.Arguments = {ps_single_quote(arguments)}; '
        + (f'$sc.IconLocation = {ps_single_quote(ico)}; ' if ico else '')
        + f'$sc.Description = {ps_single_quote(description)}; '
        f'$sc.Save()'
    )


def _write_shortcut(lnk_path, target, base_args, label):
    lnk_path = Path(lnk_path)
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         build_shortcut_command(lnk_path, target, base_args)],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if not lnk_path.exists():
        write_persistent_log(f"{label} shortcut was not created at {lnk_path}")
        return False
    return True


def register_desktop_shortcut(target, base_args):
    try:
        _write_shortcut(Path.home() / "Desktop" / SHORTCUT_NAME,
                        target, base_args, "Desktop")
    except Exception as e:
        write_persistent_log(f"Shortcut registration failed: {e}")


def register_start_menu_shortcut(target, base_args):
    """Publish the companion in the Start Menu so it is searchable by name.

    The companion is otherwise reachable only from the tray, a desktop icon,
    or the logon task, so a user who closes it has no obvious way to start it
    again. Written on the same version-stamped path as the other integrations,
    which means an upgrade refreshes the target automatically.
    """
    try:
        _write_shortcut(start_menu_programs_dir() / SHORTCUT_NAME,
                        target, base_args, "Start Menu")
    except Exception as e:
        write_persistent_log(f"Start Menu registration failed: {e}")


def register_startup_task(target, base_args):
    try:
        task_cmd = command_line([target] + list(base_args) + ['-Background'])
        subprocess.run([
            'schtasks', '/Create', '/TN', 'AstraDownloader',
            '/TR', task_cmd, '/SC', 'ONLOGON', '/RL', 'LIMITED', '/F'
        ], capture_output=True, creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        write_persistent_log(f"Startup task registration failed: {e}")


def register_protocol_handlers(target, base_args):
    try:
        import winreg
        open_cmd = command_line([target] + list(base_args)) + ' "%1"'
        for proto in ('ytdl', 'mediadl'):
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, f'Software\\Classes\\{proto}', 0, winreg.KEY_WRITE)
            winreg.SetValueEx(key, '', 0, winreg.REG_SZ, f'URL:{proto} Protocol')
            winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
            winreg.CloseKey(key)
            cmd_key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, f'Software\\Classes\\{proto}\\shell\\open\\command', 0, winreg.KEY_WRITE)
            winreg.SetValueEx(cmd_key, '', 0, winreg.REG_SZ, open_cmd)
            winreg.CloseKey(cmd_key)
    except Exception as e:
        write_persistent_log(f"Protocol registration failed: {e}")


def register_uninstall_entry(target, base_args):
    try:
        import winreg
        uninstall_cmd = command_line([target] + list(base_args) + ['--uninstall'])
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AstraDownloader', 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, 'DisplayVersion', 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, 'Publisher', 0, winreg.REG_SZ, 'SysAdminDoc')
        winreg.SetValueEx(key, 'InstallLocation', 0, winreg.REG_SZ, str(INSTALL_DIR))
        if ICON_PATH.exists():
            winreg.SetValueEx(key, 'DisplayIcon', 0, winreg.REG_SZ, f'{ICON_PATH},0')
        winreg.SetValueEx(key, 'UninstallString', 0, winreg.REG_SZ, uninstall_cmd)
        winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, 'NoRepair', 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception as e:
        write_persistent_log(f"Uninstall registration failed: {e}")


def is_valid_native_extension_id(value, browser='chrome'):
    """Return whether an ID is safe for a browser native-host manifest."""
    text = str(value or '').strip()
    browser = str(browser or '').strip().lower()
    if browser == 'chrome':
        return bool(CHROME_EXTENSION_ID_RE.fullmatch(text.lower()))
    if browser == 'firefox':
        return bool(FIREFOX_EXTENSION_ID_RE.fullmatch(text))
    return bool(text and len(text) <= 128 and not any(
        ord(char) < 0x20 or char in '/\\<>' for char in text
    ))


def parse_native_extension_ids(value, fallback=(), browser=None):
    """Split, deduplicate, and optionally validate native-host IDs.

    ``browser=None`` keeps the generic parser useful for legacy origin
    settings. Registration and manifest construction always pass the target
    browser so untrusted text cannot become an ``allowed_origins`` entry.
    """
    if isinstance(value, (list, tuple)):
        raw = value
    elif isinstance(value, str):
        raw = re.split(r'[\s,;]+', value)
    else:
        raw = []
    out = []
    for item in raw:
        text = str(item or '').strip()
        if not text:
            continue
        if browser and not is_valid_native_extension_id(text, browser):
            continue
        if str(browser or '').lower() == 'chrome':
            text = text.lower()
        if text not in out:
            out.append(text)
    if out:
        return out
    for item in fallback or ():
        text = str(item or '').strip()
        if not text or (browser and not is_valid_native_extension_id(text, browser)):
            continue
        if str(browser or '').lower() == 'chrome':
            text = text.lower()
        if text not in out:
            out.append(text)
    return out


def normalize_extension_origin(origin):
    try:
        parsed = urlparse(str(origin or "").strip().rstrip("/"))
    except Exception:
        return ""
    scheme = (parsed.scheme or "").lower()
    host = (parsed.netloc or "").strip().lower()
    if scheme not in {"chrome-extension", "moz-extension"} or not host:
        return ""
    return f"{scheme}://{host}"


def parse_legacy_health_token_origins(value):
    origins = []
    for item in parse_native_extension_ids(value):
        normalized = normalize_extension_origin(item)
        if not normalized and re.fullmatch(r"[a-z]{8,64}", item.strip().lower()):
            normalized = normalize_extension_origin(f"chrome-extension://{item.strip().lower()}")
        if normalized and normalized not in origins:
            origins.append(normalized)
    return origins


def legacy_health_token_origin_allowlist(config):
    origins = []
    for chrome_id in parse_native_extension_ids(config.get("NativeChromeExtensionIds", "")):
        normalized = normalize_extension_origin(f"chrome-extension://{chrome_id.strip().lower()}")
        if normalized and normalized not in origins:
            origins.append(normalized)
    for origin in parse_legacy_health_token_origins(config.get("LegacyHealthTokenOrigins", "")):
        if origin not in origins:
            origins.append(origin)
    return frozenset(origins)


def register_native_host_registry_value(key_path, manifest_path):
    import winreg
    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
    try:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(manifest_path))
    finally:
        winreg.CloseKey(key)


def unregister_native_host_registry_value(key_path):
    """Remove a native-host registry pointer when its allowlist is cleared."""
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        # reason: revocation is idempotent when the pointer is already absent
        pass
    except OSError as error:
        write_persistent_log(
            f"Native messaging host registry cleanup failed for {key_path}: {error}"
        )


def _revoke_native_messaging_host(manifest_path, registry_key):
    try:
        Path(manifest_path).unlink(missing_ok=True)
    except OSError as error:
        write_persistent_log(
            f"Native messaging manifest cleanup failed for {manifest_path}: {error}"
        )
    unregister_native_host_registry_value(registry_key)


def register_native_messaging_hosts(target, base_args, config):
    if sys.platform != 'win32':
        return
    chrome_ids = parse_native_extension_ids(
        config.get("NativeChromeExtensionIds", ""), browser="chrome"
    )
    firefox_ids = parse_native_extension_ids(
        config.get("NativeFirefoxExtensionIds", ""), browser="firefox"
    )
    chrome_manifest = NATIVE_HOST_DIR / f"{NATIVE_HOST_NAME}.chrome.json"
    firefox_manifest = NATIVE_HOST_DIR / f"{NATIVE_HOST_NAME}.firefox.json"
    chrome_registry_keys = tuple(
        f"{root}\\{NATIVE_HOST_NAME}"
        for root in CHROMIUM_NATIVE_MESSAGING_REGISTRY_ROOTS
    )
    firefox_registry_key = (
        f"{FIREFOX_NATIVE_MESSAGING_REGISTRY_ROOT}\\{NATIVE_HOST_NAME}"
    )

    def revoke_chromium_host():
        try:
            chrome_manifest.unlink(missing_ok=True)
        except OSError as error:
            write_persistent_log(
                f"Native messaging manifest cleanup failed for {chrome_manifest}: {error}"
            )
        for registry_key in chrome_registry_keys:
            unregister_native_host_registry_value(registry_key)

    if base_args:
        write_persistent_log("Native messaging host registration skipped: source runs need an executable wrapper.")
        if not chrome_ids:
            revoke_chromium_host()
        if not firefox_ids:
            _revoke_native_messaging_host(firefox_manifest, firefox_registry_key)
        return
    if not chrome_ids and not firefox_ids:
        revoke_chromium_host()
        _revoke_native_messaging_host(firefox_manifest, firefox_registry_key)
        write_persistent_log("Native messaging host registration disabled: no extension IDs configured.")
        return
    try:
        NATIVE_HOST_DIR.mkdir(parents=True, exist_ok=True)
        if chrome_ids:
            atomic_write_json(chrome_manifest, build_native_host_manifest(target, chrome_ids, browser="chrome"))
            for registry_key in chrome_registry_keys:
                register_native_host_registry_value(registry_key, chrome_manifest)
        else:
            revoke_chromium_host()
        if firefox_ids:
            atomic_write_json(firefox_manifest, build_native_host_manifest(target, firefox_ids, browser="firefox"))
            register_native_host_registry_value(
                firefox_registry_key,
                firefox_manifest,
            )
        else:
            _revoke_native_messaging_host(firefox_manifest, firefox_registry_key)
    except Exception as e:
        write_persistent_log(f"Native messaging host registration failed: {e}")


def ensure_system_integrations(prefer_installed=True, force=False):
    """Register shortcut / startup task / protocol handlers / uninstall entry.

    v1.2.0: idempotent — writes a version stamp to HKCU after success and
    short-circuits on subsequent launches when the stamp matches APP_VERSION.
    Previously fired a PowerShell process + 3 winreg writes + schtasks on
    every launch, even when nothing had changed.
    """
    if is_portable_mode():
        # Portable copies are intentionally self-contained. Registering a
        # shortcut, protocol handler, scheduled task, or native host would
        # make an otherwise movable folder depend on this machine.
        return launch_command_parts(prefer_installed=False)
    target, base_args = launch_command_parts(prefer_installed=prefer_installed)
    if not force and _get_integrations_stamp() == APP_VERSION:
        register_native_messaging_hosts(target, base_args, Config())
        return target, base_args
    register_desktop_shortcut(target, base_args)
    register_start_menu_shortcut(target, base_args)
    register_startup_task(target, base_args)
    register_protocol_handlers(target, base_args)
    register_uninstall_entry(target, base_args)
    register_native_messaging_hosts(target, base_args, Config())
    _set_integrations_stamp()
    return target, base_args

# ── Dark theme stylesheet ──
# One visual system: a single type scale, one spacing rhythm, and separators
# in place of nested cards. Two superseded layers used to sit above this one
# and were discarded by this very assignment; they only made the live palette
# harder to find.
STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0a0d12;
    color: #f2f0ed;
    font-size: 13px;
}
QLabel { color: #f2f0ed; background: transparent; }
QLabel[class="brandFallback"] {
    background: #ff6552;
    color: #170806;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 800;
}
QLabel[class="brandTitle"] {
    color: #fff8f4;
    font-size: 12px;
    font-weight: 750;
    letter-spacing: .35px;
}
QLabel[class="brandVersion"] { color: #8d97a4; font-size: 11px; }
QLabel[class="settingsStatus"] { font-size: 12px; }
QLabel[class="settingsStatus"][tone="neutral"] { color: #9ca5b0; }
QLabel[class="settingsStatus"][tone="success"] { color: #75dcb1; }
QLabel[class="settingsStatus"][tone="warning"] { color: #edbd76; }
QLabel[class="settingsStatus"][tone="danger"] { color: #ff8d82; }
QLabel[class="title"] { font-size: 28px; font-weight: 700; color: #fbf8f5; }
QLabel[class="subtitle"] { color: #9da6b2; font-size: 13px; }
QLabel[class="muted"] { color: #8d97a4; }
QLabel[class="secondary"] { color: #c5cbd3; font-size: 13px; }
QLabel[class="section"], QLabel[class="panelTitle"] {
    color: #f1eeea;
    font-size: 14px;
    font-weight: 650;
    letter-spacing: 0;
}
QLabel[class="settingsSection"] {
    color: #b8c0ca;
    font-size: 15px;
    font-weight: 650;
}
QLabel[class="fieldLabel"] { color: #f1eeea; font-size: 13px; font-weight: 600; }
QLabel[class="fieldHint"] { color: #8d97a4; font-size: 12px; }
QLabel[class="toolbarMeta"], QLabel[class="columnLabel"], QLabel[class="tableValue"] {
    color: #aab2bd;
    font-size: 13px;
}
QLabel[class="metricLabel"] { color: #aab2bd; font-size: 13px; }
QLabel[class="metricValue"] { color: #f8f5f1; font-size: 26px; font-weight: 700; }
QLabel[class="metricValue"][tone="accent"] { color: #ff6a57; }
QLabel[class="heroTitle"] { color: #faf7f3; font-size: 18px; font-weight: 650; }
QLabel[class="emptyGlyph"] { color: #788391; font-size: 42px; font-weight: 300; }
QLabel[class="emptyTitle"] { color: #f4f1ee; font-size: 19px; font-weight: 650; }
QLabel[class="emptyBody"] { color: #98a1ad; font-size: 13px; }
QLabel[class="stateDot"] { font-size: 13px; }
QLabel[class="stateDot"][tone="success"] { color: #55d69f; }
QLabel[class="stateDot"][tone="warning"] { color: #f1b45e; }
QLabel[class="stateDot"][tone="danger"] { color: #ff7568; }
QLabel[class="stateDot"][tone="neutral"] { color: #747f8d; }
QLabel[class="stateLabel"] { font-size: 12px; font-weight: 600; }
QLabel[class="stateLabel"][tone="success"] { color: #75dcb1; }
QLabel[class="stateLabel"][tone="warning"] { color: #edbd76; }
QLabel[class="stateLabel"][tone="danger"] { color: #ff8d82; }
QLabel[class="stateLabel"][tone="info"] { color: #85bee8; }
QLabel[class="stateLabel"][tone="neutral"] { color: #9ca5b0; }
QLabel[class="readinessValue"] { color: #d9dde2; font-size: 12px; font-weight: 600; }
QLabel[class="readinessDot"] { font-size: 12px; }
QLabel[class="readinessDot"][tone="success"] { color: #55d69f; }
QLabel[class="readinessDot"][tone="warning"] { color: #f1b45e; }
QLabel[class="readinessDot"][tone="danger"] { color: #ff7568; }
QLabel[class="readinessDot"][tone="neutral"] { color: #747f8d; }
QLabel[class="badge"] { background: transparent; border: none; padding: 0; font-size: 12px; font-weight: 600; }
QLabel[class="badge"][tone="success"] { color: #75dcb1; }
QLabel[class="badge"][tone="warning"] { color: #edbd76; }
QLabel[class="badge"][tone="danger"] { color: #ff8d82; }
QLabel[class="badge"][tone="info"] { color: #85bee8; }
QLabel[class="badge"][tone="neutral"] { color: #9ca5b0; }
QLabel[class="errorCallout"] {
    color: #ffb7b0;
    background: #1c1315;
    border-left: 2px solid #b65a53;
    padding: 9px 11px;
    font-size: 12px;
}

QPushButton {
    background-color: transparent;
    color: #d8dde3;
    border: 1px solid #607080;
    border-radius: 6px;
    padding: 7px 13px;
    min-height: 36px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton:hover { background-color: #171d25; border-color: #718092; color: #fffaf6; }
QPushButton:pressed { background-color: #11161d; }
QPushButton:focus { border-color: #ff7664; }
QPushButton:disabled { color: #606a77; background: transparent; border-color: #607080; }
QPushButton[class="primary"] {
    background-color: #ff6552;
    color: #170806;
    border-color: #ff6552;
    font-weight: 700;
}
QPushButton[class="primary"]:hover { background-color: #ff7867; border-color: #ff7867; }
QPushButton[class="secondary"] { background: transparent; color: #d8dde3; border-color: #607080; }
QPushButton[class="danger"] { background: transparent; color: #ef9b93; border-color: #c9675f; }
QPushButton[class="ghost"] { background-color: #11161d; border-color: #607080; color: #aeb6c1; padding-left: 9px; padding-right: 9px; }
QPushButton[class="ghost"]:hover { background-color: #171d25; border-color: #718092; color: #f2f0ed; }
/* Keyboard focus. The bare QPushButton:focus rule above is the same
   specificity as every QPushButton[class="…"] rule, so those later rules won
   the cascade and focus rendered no pixels at all on ghost, primary,
   secondary and danger buttons. Each variant restates the ring after its own
   class rule. #ffb2a5 holds 11.3:1 against the window (#0a0d12) and 9.8:1
   against the hover fill (#171d25). The primary button is filled, so the ring
   the eye compares against is its own #ff6552 face — a light ring only reaches
   1.7:1 there, so it takes the dark #170806 (6.7:1) instead. */
QPushButton[class="ghost"]:focus { border-color: #ffb2a5; background-color: #171d25; }
QPushButton[class="primary"]:focus { border-color: #170806; }
QPushButton[class="secondary"]:focus { border-color: #ffb2a5; }
QPushButton[class="danger"]:focus { border-color: #ffb2a5; }
QPushButton[class="nav"] {
    color: #a6afba;
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 4px;
    text-align: left;
    padding: 11px 14px;
    margin: 0 12px 5px 12px;
    min-height: 42px;
    font-size: 14px;
    font-weight: 550;
}
QPushButton[class="nav"]:hover { background-color: #151a21; color: #f2f0ed; }
QPushButton[class="nav"][active="true"] {
    color: #fff8f4;
    background-color: #202630;
    border-left-color: #ff6552;
    font-weight: 650;
}
QPushButton[class="nav"]:focus { background-color: #171d25; border-left-color: #697482; }
QPushButton[class="nav"][active="true"]:focus { background-color: #242b35; border-left-color: #ff6552; }

QLineEdit, QSpinBox, QComboBox {
    background-color: #11161d;
    color: #f0eeeb;
    border: 1px solid #607080;
    border-radius: 6px;
    padding: 7px 10px;
    min-height: 36px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #ff7664; background: #151b23; }
QLineEdit[state="error"], QSpinBox[state="error"] { border-color: #c9675f; background: #1a1214; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: #687381; background: #0e1319; border-color: #607080; }
/* The paste box is the product's front door, so it is sized like one.
   An attribute selector outranks a pseudo-class in Qt's CSS2 cascade, so
   the focus state has to be restated here or the hero field would render
   no focus ring at all (the same trap the nav buttons hit). */
QLineEdit[class="heroUrl"] {
    font-size: 15px;
    min-height: 46px;
    padding: 10px 14px;
    border-color: #687381;
}
QLineEdit[class="heroUrl"]:focus { border-color: #ff7664; background: #151b23; }
QComboBox::drop-down { border: none; width: 24px; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; background: transparent; }
QCheckBox { color: #d7dce2; font-size: 13px; spacing: 10px; min-height: 26px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px; border: 1px solid #607080; background: transparent; }
QCheckBox::indicator:hover { border-color: #718092; }
QCheckBox::indicator:checked { background: #ff6552; border-color: #ff6552; }
/* A styled indicator suppresses Qt's native focus rect, so the checked and
   unchecked focus states have to draw their own. */
QCheckBox::indicator:focus { border-color: #ffb2a5; }
QCheckBox::indicator:checked:focus { border-color: #ffb2a5; background: #ff7867; }
QCheckBox:disabled { color: #687381; }

QFrame[class="sidebar"] { background-color: #080b0f; border-right: 1px solid #252c35; }
QFrame[class="card"] { background: transparent; border: none; }
QFrame[class="serverControl"], QFrame[class="readiness"] {
    background: transparent;
    border: none;
    border-radius: 0;
}
QFrame[class="readinessRow"] { background: transparent; border: none; }
QFrame[class="stat"] {
    background: transparent;
    border: none;
    border-right: 1px solid #2b333d;
    border-radius: 0;
}
QFrame[class="stat"][last="true"] { border-right: none; }
QFrame[class="empty"] { background: transparent; border: none; border-radius: 0; }
QFrame[class="settingsGroup"] {
    background: transparent;
    border: none;
    border-bottom: 1px solid #252d37;
    border-radius: 0;
}
QFrame[class="listHeader"] { background: transparent; border: none; border-bottom: 1px solid #2a323c; }
QFrame[class="historyRow"], QFrame[class="download"] {
    background: transparent;
    border: none;
    border-bottom: 1px solid #252d37;
    border-radius: 0;
}
QFrame[class="download"][state="failed"] { background: #151113; border-left: 2px solid #b65a53; }
QFrame[class="download"][state="complete"] { background: transparent; border-left: 2px solid #3f8b70; }
QFrame[class="divider"] { background: #29313b; border: none; min-height: 1px; max-height: 1px; }
QFrame[class="verticalDivider"] { background: #2b333d; border: none; min-width: 1px; max-width: 1px; }

QTextEdit {
    background-color: #0d1218;
    color: #b4bcc6;
    border: 1px solid #607080;
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
    padding: 12px;
}
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; border: none; margin: 2px; }
QScrollBar::handle:vertical { background: #394350; border-radius: 4px; min-height: 28px; }
QProgressBar { background: #151b22; border: none; border-radius: 4px; height: 6px; }
QProgressBar::chunk { background: #ff6552; border-radius: 4px; }
QTabWidget::pane { border: none; }
QTabBar { background: transparent; }
QTabBar::tab { height: 0; width: 0; }
QMenu { background: #11161d; color: #f0eeeb; border: 1px solid #607080; padding: 5px; }
QMenu::item { padding: 7px 22px 7px 10px; border-radius: 4px; }
QMenu::item:selected { background: #242b35; }
QToolTip { background: #11161d; color: #f0eeeb; border: 1px solid #607080; padding: 6px 8px; }
"""

# Qt stylesheets do not have variables. Keeping the authored dark sheet as
# the source of truth and deriving its light counterpart from a complete
# token map prevents one-off controls from quietly retaining the old dark
# surface when the user changes schemes.
_LIGHT_THEME_COLOR_REPLACEMENTS = {
    "#080b0f": "#e8edf3",
    "#0a0d12": "#f6f8fb",
    "#0d1218": "#ffffff",
    "#0e1319": "#eef2f6",
    "#11161d": "#ffffff",
    "#151113": "#fff0ee",
    "#151a21": "#e9eef4",
    "#151b22": "#e6ebf1",
    "#151b23": "#f2f5f8",
    "#170806": "#2c0d08",
    "#171d25": "#edf1f5",
    "#1a1214": "#fff1ef",
    "#1c1315": "#fff1ef",
    "#202630": "#dce5ee",
    "#242b35": "#d2dce6",
    "#252c35": "#cbd5df",
    "#252d37": "#d2dce6",
    "#29313b": "#c2ccd6",
    "#2a323c": "#cbd5df",
    "#2b333d": "#c5d0da",
    "#394350": "#718092",
    "#3f8b70": "#2f8a68",
    "#55d69f": "#087f55",
    "#606a77": "#697785",
    "#607080": "#738294",
    "#687381": "#697785",
    "#697482": "#526272",
    "#718092": "#526272",
    "#747f8d": "#5c6c7b",
    "#75dcb1": "#087f55",
    "#788391": "#5c6c7b",
    "#85bee8": "#1769aa",
    "#8d97a4": "#536273",
    "#98a1ad": "#536273",
    "#9ca5b0": "#536273",
    "#9da6b2": "#445466",
    "#a6afba": "#445466",
    "#aab2bd": "#445466",
    "#aeb6c1": "#445466",
    "#b4bcc6": "#445466",
    "#b65a53": "#a83930",
    "#b8c0ca": "#344251",
    "#c5cbd3": "#344251",
    "#c9675f": "#a83930",
    "#d7dce2": "#253343",
    "#d8dde3": "#253343",
    "#d9dde2": "#253343",
    "#edbd76": "#8a5700",
    "#ef9b93": "#a83930",
    "#f0eeeb": "#18212b",
    "#f1b45e": "#8a5700",
    "#f1eeea": "#18212b",
    "#f2f0ed": "#18212b",
    "#f4f1ee": "#18212b",
    "#f8f5f1": "#18212b",
    "#faf7f3": "#18212b",
    "#fbf8f5": "#18212b",
    "#ff6552": "#d94c3b",
    "#ff6a57": "#c43f2e",
    "#ff7568": "#b52f25",
    "#ff7664": "#a83b30",
    "#ff7867": "#e05b49",
    "#ff8d82": "#b52f25",
    "#ffb2a5": "#8f251e",
    "#ffb7b0": "#a83930",
    "#fff8f4": "#18212b",
    "#fffaf6": "#18212b",
}
LIGHT_STYLESHEET = STYLESHEET
for _dark_colour, _light_colour in _LIGHT_THEME_COLOR_REPLACEMENTS.items():
    LIGHT_STYLESHEET = LIGHT_STYLESHEET.replace(_dark_colour, _light_colour)


def stylesheet_for_theme(theme):
    """Return the authored stylesheet for an already-resolved scheme."""
    return LIGHT_STYLESHEET if str(theme or "").strip().lower() == "light" else STYLESHEET


def resolve_theme(theme="system", color_scheme=None):
    """Resolve a stored theme preference to ``light`` or ``dark``."""
    normalized = str(theme or "system").strip().lower()
    if normalized in {"light", "dark"}:
        return normalized
    if color_scheme is None:
        application = QApplication.instance()
        if application is not None:
            try:
                color_scheme = QApplication.styleHints().colorScheme()
            except Exception:
                color_scheme = None
    schemes = getattr(Qt, "ColorScheme", None)
    if schemes is not None and color_scheme == getattr(schemes, "Light", object()):
        return "light"
    return "dark"


def set_window_title_bar_theme(window, theme):
    """Ask Windows' DWM to use the same scheme as the client area."""
    if window is None or os.name != "nt":
        return False
    try:
        import ctypes

        value = ctypes.c_int(1 if str(theme).strip().lower() == "dark" else 0)
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        # Attribute 20 is the current name; 19 is used by older Windows 10
        # builds. Trying both keeps packaged installs aligned across systems.
        for attribute in (20, 19):
            result = dwm.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                return True
    except Exception:
        # The title bar is cosmetic and DWM is unavailable on non-Desktop
        # Windows hosts. The stylesheet remains the reliable fallback.
        return False
    return False


def apply_application_theme(theme="system", *, windows=None):
    """Apply a stored theme preference to the live Qt application."""
    application = QApplication.instance()
    normalized = str(theme or "system").strip().lower()
    if normalized not in {"system", "light", "dark"}:
        normalized = "system"
    if application is None:
        return resolve_theme(normalized, color_scheme=Qt.ColorScheme.Dark)

    if getattr(application, "_astra_theme_applying", False):
        return resolve_theme(normalized)
    application._astra_theme_applying = True
    application._astra_theme_setting = normalized
    try:
        hints = QApplication.styleHints()
        if not getattr(application, "_astra_system_theme_connected", False):
            signal = getattr(hints, "colorSchemeChanged", None)
            if signal is not None:
                def _system_theme_changed(*_args):
                    if getattr(application, "_astra_theme_setting", "system") == "system":
                        apply_application_theme("system")
                try:
                    signal.connect(_system_theme_changed)
                    application._astra_system_theme_connected = True
                except Exception:
                    # Older Qt builds expose no connectable color-scheme
                    # signal; startup resolution still works there.
                    # reason: the stylesheet can still resolve the initial scheme
                    pass
        set_scheme = getattr(hints, "setColorScheme", None)
        unset_scheme = getattr(hints, "unsetColorScheme", None)
        schemes = getattr(Qt, "ColorScheme", None)
        if normalized == "system":
            if callable(unset_scheme):
                unset_scheme()
        elif callable(set_scheme) and schemes is not None:
            set_scheme(getattr(schemes, normalized.capitalize()))
        resolved = resolve_theme(normalized)
        application.setStyleSheet(stylesheet_for_theme(resolved))
        set_gui_theme(resolved)
        refresh_line_icons(application)
        targets = list(windows) if windows is not None else application.topLevelWidgets()
        for window in targets:
            set_window_title_bar_theme(window, resolved)
        return resolved
    finally:
        application._astra_theme_applying = False

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
class Config(ConfigStore):
    def __init__(self, read_only=False):
        super().__init__(
            install_dir=lambda: INSTALL_DIR,
            path=lambda: CONFIG_PATH,
            sanitizer=sanitize_config,
            loader=load_json_file,
            writer=lambda path, data: atomic_write_json(path, data),
            logger=lambda message: write_persistent_log(message),
            schema_version=CONFIG_SCHEMA_VERSION,
            read_only=read_only,
        )

# ══════════════════════════════════════════════════════════════
# HISTORY
# ══════════════════════════════════════════════════════════════
class History(HistoryStore):
    def __init__(self, config=None):
        def read_limit():
            source = config.get("HistoryRetentionLimit", HISTORY_RETENTION_DEFAULT) \
                if config is not None else HISTORY_RETENTION_DEFAULT
            return clamp_int(
                source,
                HISTORY_RETENTION_DEFAULT,
                HISTORY_RETENTION_MIN,
                HISTORY_RETENTION_MAX,
            )

        super().__init__(
            path=lambda: HISTORY_PATH,
            sanitizer=sanitize_history_entries,
            loader=load_json_file,
            writer=lambda path, data: atomic_write_json(path, data),
            logger=lambda message: write_persistent_log(message),
            limit=HISTORY_RETENTION_DEFAULT,
            limit_reader=read_limit,
        )


def _build_subprocess_env():
    return _owned_build_subprocess_env(DENO_PATH, DENO_DIR, environ=os.environ)


def terminate_process_tree(proc, timeout=3):
    return _owned_terminate_process_tree(
        proc,
        timeout=timeout,
        platform=sys.platform,
        runner=subprocess.run,
        creationflags=CREATE_NO_WINDOW,
        timeout_error=subprocess.TimeoutExpired,
        logger=write_persistent_log,
    )

# ══════════════════════════════════════════════════════════════
# DOWNLOAD MANAGER
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# v1.2.2: cross-thread native folder picker
# ══════════════════════════════════════════════════════════════
# Flask handlers run on waitress worker threads; Qt widgets are
# GUI-thread only. The extension popup's "Change" button needs to
# trigger a native folder dialog so users don't have to manually
# type a Windows path. Worker threads enqueue requests; a QTimer on
# the GUI thread pumps them through QFileDialog and returns results
# via per-request response queues. 150 ms tick is invisible to the
# user (HTTP request -> dialog appears within one frame).

_folder_pick_q = queue.Queue(maxsize=1)
_folder_picker_service = None  # set in main() once QApplication exists


class FolderPickerService(_OwnedFolderPickerService):
    def __init__(self, parent=None):
        super().__init__(
            request_queue=_folder_pick_q,
            dialog_factory=lambda *args, **kwargs: QFileDialog(*args, **kwargs),
            dialog_types=lambda: QFileDialog,
            clock=lambda: time.time(),
            logger=lambda message: write_persistent_log(message),
            parent=parent,
        )


class _DownloadManagerSignals(QObject):
    progress_updated = pyqtSignal()
    download_completed = pyqtSignal(str)


class DownloadManager(DownloadManagerCore):
    def __init__(self, config, history, queue_path=None):
        self._signal_bridge = _DownloadManagerSignals()
        DownloadManagerCore.__init__(
            self, config, history, queue_path,
            dependencies={
                'CREATE_NEW_PROCESS_GROUP': CREATE_NEW_PROCESS_GROUP,
                'CREATE_NO_WINDOW': CREATE_NO_WINDOW,
                'FFMPEG_PATH': lambda: FFMPEG_PATH,
                'INSTALL_DIR': lambda: INSTALL_DIR,
                'WHISPER_BIN_MIN_BYTES': lambda: WHISPER_BIN_MIN_BYTES,
                'WHISPER_BIN_PATH': lambda: WHISPER_BIN_PATH,
                'WHISPER_MODEL_MIN_BYTES': lambda: WHISPER_MODEL_MIN_BYTES,
                'WHISPER_MODEL_PATH': lambda: WHISPER_MODEL_PATH,
                'YTDLP_PATH': lambda: YTDLP_PATH,
                '_build_subprocess_env': lambda *args, **kwargs: _build_subprocess_env(*args, **kwargs),
                'allowed_output_roots': lambda *args, **kwargs: allowed_output_roots(*args, **kwargs),
                'atomic_write_json': lambda *args, **kwargs: atomic_write_json(*args, **kwargs),
                'build_javascript_runtime_args': lambda *args, **kwargs: build_javascript_runtime_args(*args, **kwargs),
                'build_youtube_extractor_args': lambda *args, **kwargs: build_youtube_extractor_args(*args, **kwargs),
                'clamp_int': lambda *args, **kwargs: clamp_int(*args, **kwargs),
                'clean_path_text': lambda *args, **kwargs: clean_path_text(*args, **kwargs),
                'clean_text': lambda *args, **kwargs: clean_text(*args, **kwargs),
                'cleanup_stale_cookie_jars': lambda *args, **kwargs: cleanup_stale_cookie_jars(*args, **kwargs),
                'coerce_bool': lambda *args, **kwargs: coerce_bool(*args, **kwargs),
                'check_download_disk_space': lambda *args, **kwargs: check_download_disk_space(*args, **kwargs),
                'is_supported_media_url': lambda *args, **kwargs: is_supported_media_url(*args, **kwargs),
                'is_youtube_url': lambda *args, **kwargs: is_youtube_url(*args, **kwargs),
                'load_json_file': lambda *args, **kwargs: load_json_file(*args, **kwargs),
                'managed_binary_state': lambda *args, **kwargs: managed_binary_state(*args, **kwargs),
                # v1.5.4: let the download path drive the throttled, race-safe
                # yt-dlp auto-update so a long-running companion keeps yt-dlp
                # current between restarts — the download path, not just server
                # startup, now opens the update window.
                'maybe_auto_update_ytdlp': lambda *args, **kwargs: maybe_auto_update_ytdlp(*args, **kwargs),
                'normalize_output_dir': lambda *args, **kwargs: normalize_output_dir(*args, **kwargs),
                'normalize_sponsorblock_categories': lambda *args, **kwargs: normalize_sponsorblock_categories(*args, **kwargs),
                'normalize_download_section': lambda *args, **kwargs: normalize_download_section(*args, **kwargs),
                'normalize_playlist_items': lambda *args, **kwargs: normalize_playlist_items(*args, **kwargs),
                'normalize_url': lambda *args, **kwargs: normalize_url(*args, **kwargs),
                'probe_javascript_runtime': lambda *args, **kwargs: probe_javascript_runtime(*args, **kwargs),
                'probe_impersonate_targets': lambda *args, **kwargs: probe_impersonate_targets(*args, **kwargs),
                'probe_whisper_runtime': lambda *args, **kwargs: probe_whisper_runtime(*args, **kwargs),
                'normalize_impersonate_target': lambda *args, **kwargs: normalize_impersonate_target(*args, **kwargs),
                'quarantined_state_files': lambda *args, **kwargs: quarantined_state_files(*args, **kwargs),
                'spawn_ytdlp': lambda *args, **kwargs: spawn_ytdlp(*args, **kwargs),
                'ytdlp_activity_count': lambda: _YTDLP_ACTIVITY.active_count(),
                'release_ytdlp_activity': lambda process: _YTDLP_ACTIVITY.release_process(process),
                'spawn_media_process': lambda *args, **kwargs: spawn_media_process(*args, **kwargs),
                'terminate_process_tree': lambda *args, **kwargs: terminate_process_tree(*args, **kwargs),
                'write_media_server_sidecars': lambda *args, **kwargs: write_media_server_sidecars(*args, **kwargs),
                'write_persistent_log': lambda *args, **kwargs: write_persistent_log(*args, **kwargs),
            },
            progress_updated=self._signal_bridge.progress_updated,
            download_completed=self._signal_bridge.download_completed,
        )


def build_subscription_manager(config, dl_manager):
    """Compose the durable subscription scheduler from application services."""
    store = SubscriptionStore(
        path=SUBSCRIPTIONS_PATH,
        reader=lambda path, fallback: load_json_file(path, fallback),
        writer=lambda path, data: atomic_write_json(path, data),
        logger=lambda message: write_persistent_log(message),
        normalize_url=lambda value: normalize_url(value),
        is_youtube_url=lambda value: is_youtube_url(value),
        clean_text=lambda *args, **kwargs: clean_text(*args, **kwargs),
        clamp_int=lambda *args, **kwargs: clamp_int(*args, **kwargs),
        coerce_bool=lambda *args, **kwargs: coerce_bool(*args, **kwargs),
    )

    def enqueue(subscription, candidate, archive_key):
        return dl_manager.start_download(
            url=candidate['url'],
            title=candidate.get('title'),
            subscription_id=subscription['id'],
            archive_key=archive_key,
        )

    return SubscriptionManager(
        store=store,
        probe=lambda url: probe_subscription_uploads(
            url,
            configured_runtime=config.get('JavaScriptRuntime', 'auto'),
            identity_builder=dl_manager._build_probe_identity_args,
        ),
        enqueue=enqueue,
        status_reader=lambda download_id: dl_manager.status_of(download_id, default='failed'),
        logger=lambda message: write_persistent_log(message),
        activity_registry=_YTDLP_ACTIVITY,
    )


# ══════════════════════════════════════════════════════════════
# HTTP SERVER (Flask in background thread)
# ══════════════════════════════════════════════════════════════
def create_api(config, dl_manager, history, subscriptions=None):
    return _owned_create_api(config, dl_manager, history, dependencies={
        'APP_NAME': APP_NAME,
        'APP_VERSION': APP_VERSION,
        'CORS_MAX_AGE_SECONDS': CORS_MAX_AGE_SECONDS,
        'DEFAULT_CONFIG': DEFAULT_CONFIG,
        'MAX_REQUEST_BYTES': MAX_REQUEST_BYTES,
        'MAX_RESPONSE_BYTES': MAX_RESPONSE_BYTES,
        'RATE_LIMIT_DOWNLOAD_MAX': RATE_LIMIT_DOWNLOAD_MAX,
        'RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS': RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS,
        'RATE_LIMIT_PICKFOLDER_MAX': RATE_LIMIT_PICKFOLDER_MAX,
        'RATE_LIMIT_PICKFOLDER_WINDOW_SECONDS': RATE_LIMIT_PICKFOLDER_WINDOW_SECONDS,
        'RATE_LIMIT_HEALTH_MAX': RATE_LIMIT_HEALTH_MAX,
        'RATE_LIMIT_HEALTH_WINDOW_SECONDS': RATE_LIMIT_HEALTH_WINDOW_SECONDS,
        'RATE_LIMIT_UPDATE_MAX': RATE_LIMIT_UPDATE_MAX,
        'RATE_LIMIT_UPDATE_WINDOW_SECONDS': RATE_LIMIT_UPDATE_WINDOW_SECONDS,
        'COMPANION_UPDATE_FAILURE_BACKOFF_SECONDS': COMPANION_UPDATE_FAILURE_BACKOFF_SECONDS,
        'SERVER_PORT': SERVER_PORT,
        'SERVICE_API_VERSION': SERVICE_API_VERSION,
        'SERVICE_ID': SERVICE_ID,
        'YTDLP_PATH': YTDLP_PATH,
        '_folder_pick_q': _folder_pick_q,
        '_folder_picker_service': lambda: _folder_picker_service,
        '_run_companion_self_update': lambda *args, **kwargs: _run_companion_self_update(*args, **kwargs),
        '_run_ytdlp_self_update': lambda *args, **kwargs: _run_ytdlp_self_update(*args, **kwargs),
        'allowed_output_roots': lambda *args, **kwargs: allowed_output_roots(*args, **kwargs),
        'check_ffmpeg_capabilities': lambda *args, **kwargs: check_ffmpeg_capabilities(*args, **kwargs),
        'clamp_int': lambda *args, **kwargs: clamp_int(*args, **kwargs),
        'clean_text': lambda *args, **kwargs: clean_text(*args, **kwargs),
        'coerce_bool': lambda *args, **kwargs: coerce_bool(*args, **kwargs),
        'download_error_payload': lambda *args, **kwargs: download_error_payload(*args, **kwargs),
        'get_ffmpeg_version': lambda *args, **kwargs: get_ffmpeg_version(*args, **kwargs),
        'get_last_deno_provision_error': lambda *args, **kwargs: get_last_deno_provision_error(*args, **kwargs),
        'get_recent_log_entries': lambda *args, **kwargs: get_recent_log_entries(*args, **kwargs),
        'get_ytdlp_version': lambda *args, **kwargs: get_ytdlp_version(*args, **kwargs),
        'evaluate_sabr_support': lambda *args, **kwargs: evaluate_sabr_support(*args, **kwargs),
        'evaluate_preflight_checks': lambda *args, **kwargs: evaluate_preflight_checks(*args, **kwargs),
        'get_preflight_ffmpeg_capabilities': lambda *args, **kwargs: get_preflight_ffmpeg_capabilities(*args, **kwargs),
        'get_github_api_budget': lambda *args, **kwargs: get_github_api_budget(*args, **kwargs),
        'describe_media_url_block': lambda *args, **kwargs: describe_media_url_block(*args, **kwargs),
        'is_youtube_url': lambda *args, **kwargs: is_youtube_url(*args, **kwargs),
        'legacy_health_token_origin_allowlist': lambda *args, **kwargs: legacy_health_token_origin_allowlist(*args, **kwargs),
        'media_url_block_reason': lambda *args, **kwargs: media_url_block_reason(*args, **kwargs),
        'MAX_SITE_LOGIN_COOKIES': MAX_SITE_LOGIN_COOKIES,
        'normalize_extension_origin': lambda *args, **kwargs: normalize_extension_origin(*args, **kwargs),
        'normalize_url': lambda *args, **kwargs: normalize_url(*args, **kwargs),
        'probe_javascript_runtime': lambda *args, **kwargs: probe_javascript_runtime(*args, **kwargs),
        'probe_po_token_provider': lambda *args, **kwargs: probe_po_token_provider(*args, **kwargs),
        'provision_deno': lambda *args, **kwargs: provision_deno(*args, **kwargs),
        'provision_quickjs': lambda *args, **kwargs: provision_quickjs(*args, **kwargs),
        'build_reveal_command': lambda *args, **kwargs: build_reveal_command(*args, **kwargs),
        'spawn_detached': lambda *args, **kwargs: spawn_detached(*args, **kwargs),
        'summarize_taskbar_progress': lambda *args, **kwargs: summarize_taskbar_progress(*args, **kwargs),
        'TaskbarProgress': TaskbarProgress,
        'lookup_history_url': lambda *args, **kwargs: lookup_history_url(*args, **kwargs),
        'query_history_entries': lambda *args, **kwargs: query_history_entries(*args, **kwargs),
        'read_update_recovery_status': lambda *args, **kwargs: read_update_recovery_status(*args, **kwargs),
        'subscription_manager': subscriptions,
        'validate_download_request_body': lambda *args, **kwargs: validate_download_request_body(*args, **kwargs),
        'write_persistent_log': lambda *args, **kwargs: write_persistent_log(*args, **kwargs),
    })


class SetupWorker(SetupWorkerCore):
    def __init__(self, parent=None, force_ffmpeg=False, auto_update_ytdlp=True,
                 configured_runtime='auto', config=None):
        super().__init__(
            parent=parent,
            force_ffmpeg=force_ffmpeg,
            auto_update_ytdlp=auto_update_ytdlp,
            configured_runtime=configured_runtime,
            config=config,
            dependencies={
                'DEFAULT_CONFIG': lambda: DEFAULT_CONFIG,
                'FFMPEG_PATH': lambda: FFMPEG_PATH,
                'FFMPEG_SHA256_ASSET': lambda: FFMPEG_SHA256_ASSET,
                'FFMPEG_SHA256_URL': lambda: FFMPEG_SHA256_URL,
                'FFMPEG_URL': lambda: FFMPEG_URL,
                'check_ffmpeg_capabilities': lambda *args, **kwargs: check_ffmpeg_capabilities(*args, **kwargs),
                'check_download_disk_space': lambda *args, **kwargs: check_download_disk_space(*args, **kwargs),
                'HELPER_DOWNLOAD_MAX_BYTES': lambda: HELPER_DOWNLOAD_MAX_BYTES,
                'MANAGED_BINARY_ANTIVIRUS_ADVICE': lambda: MANAGED_BINARY_ANTIVIRUS_ADVICE,
                'managed_binary_state': lambda *args, **kwargs: managed_binary_state(*args, **kwargs),
                'ICON_PATH': lambda: ICON_PATH,
                'ICON_URL': lambda: ICON_URL,
                'INSTALL_DIR': lambda: INSTALL_DIR,
                'is_portable_mode': lambda: is_portable_mode(),
                'WHISPER_MODEL_MIN_BYTES': lambda: WHISPER_MODEL_MIN_BYTES,
                'WHISPER_MODEL_PATH': lambda: WHISPER_MODEL_PATH,
                'WHISPER_BIN_MIN_BYTES': lambda: WHISPER_BIN_MIN_BYTES,
                'WHISPER_BIN_PATH': lambda: WHISPER_BIN_PATH,
                'YTDLP_PATH': lambda: YTDLP_PATH,
                'YTDLP_SHA256_ASSET': lambda: YTDLP_SHA256_ASSET,
                'YTDLP_SHA256_URL': lambda: YTDLP_SHA256_URL,
                'YTDLP_URL': lambda: YTDLP_URL,
                '_set_integrations_stamp': lambda *args, **kwargs: _set_integrations_stamp(*args, **kwargs),
                'download_file_atomic': lambda *args, **kwargs: download_file_atomic(*args, **kwargs),
                'extract_archive_executable_atomic': lambda *args, **kwargs: extract_archive_executable_atomic(*args, **kwargs),
                'fetch_expected_sha256': lambda *args, **kwargs: fetch_expected_sha256(*args, **kwargs),
                'get_ytdlp_version': lambda *args, **kwargs: get_ytdlp_version(*args, **kwargs),
                'http_get': lambda *args, **kwargs: http_requests.get(*args, **kwargs),
                'launch_command_parts': lambda *args, **kwargs: launch_command_parts(*args, **kwargs),
                'log_crash': lambda *args, **kwargs: log_crash(*args, **kwargs),
                'probe_javascript_runtime': lambda *args, **kwargs: probe_javascript_runtime(*args, **kwargs),
                'provision_deno': lambda *args, **kwargs: provision_deno(*args, **kwargs),
                'provision_quickjs': lambda *args, **kwargs: provision_quickjs(*args, **kwargs),
                'provision_whisper_runtime': lambda *args, **kwargs: provision_whisper_runtime(*args, **kwargs),
                'provision_whisper_model': lambda *args, **kwargs: provision_whisper_model(*args, **kwargs),
                'probe_whisper_runtime': lambda *args, **kwargs: probe_whisper_runtime(*args, **kwargs),
                'build_reveal_command': lambda *args, **kwargs: build_reveal_command(*args, **kwargs),
                'spawn_detached': lambda *args, **kwargs: spawn_detached(*args, **kwargs),
                'summarize_taskbar_progress': lambda *args, **kwargs: summarize_taskbar_progress(*args, **kwargs),
                'build_settings_bundle': lambda *args, **kwargs: build_settings_bundle(*args, **kwargs),
                'read_settings_bundle': lambda *args, **kwargs: read_settings_bundle(*args, **kwargs),
                'describe_bundle_changes': lambda *args, **kwargs: describe_bundle_changes(*args, **kwargs),
                'TaskbarProgress': TaskbarProgress,
                'register_desktop_shortcut': lambda *args, **kwargs: register_desktop_shortcut(*args, **kwargs),
                'register_protocol_handlers': lambda *args, **kwargs: register_protocol_handlers(*args, **kwargs),
                'register_startup_task': lambda *args, **kwargs: register_startup_task(*args, **kwargs),
                'register_uninstall_entry': lambda *args, **kwargs: register_uninstall_entry(*args, **kwargs),
                'run_ytdlp_self_update': lambda *args, **kwargs: _run_ytdlp_self_update(*args, **kwargs),
                'verify_file_sha256': lambda *args, **kwargs: verify_file_sha256(*args, **kwargs),
                'write_persistent_log': lambda *args, **kwargs: write_persistent_log(*args, **kwargs),
                'ytdlp_needs_external_runtime': lambda *args, **kwargs: ytdlp_needs_external_runtime(*args, **kwargs),
            },
        )


# ══════════════════════════════════════════════════════════════
# UNINSTALL
# ══════════════════════════════════════════════════════════════
def _portable_state_paths(root=None):
    """Return the root entries owned by this portable companion instance."""
    root = Path(INSTALL_DIR if root is None else root)
    root_file_names = {
        Path(path).name for path in (
            CONFIG_PATH, HISTORY_PATH, DOWNLOAD_QUEUE_PATH, SUBSCRIPTIONS_PATH,
            LOG_PATH, CRASH_LOG_PATH, YTDLP_PATH, FFMPEG_PATH,
            WHISPER_MODEL_PATH, ICON_PATH,
        )
    }
    # One-step recovery journals live beside the state files and are owned by
    # the same portable instance. Leaving them behind can resurrect an action
    # after uninstall, and can also expose stale settings to a later install.
    root_file_names.update({
        '.config.json.undo',
        '.history.json.undo',
        '.subscriptions.json.undo',
    })
    root_dir_names = {
        Path(path).name for path in (
            WHISPER_BIN_DIR, DENO_DIR, QUICKJS_DIR, NATIVE_HOST_DIR,
        )
    }
    root_dir_names.update({
        'site-logins', 'download-temp',
    })
    exact = {root / name for name in root_file_names | root_dir_names}
    exact.update({
        root / name for name in (
            'archive.txt',
            YTDLP_ROLLBACK_FILENAME,
            COMPANION_ROLLBACK_FILENAME,
            Path(_ytdlp_update_state_path()).name,
            Path(_companion_update_state_path()).name,
        )
    })
    return exact, root_file_names


def _portable_state_child_matches(name, state_names):
    """Recognize crash leftovers for known app-owned root files."""
    name = str(name)
    if name.startswith(('.AstraDownloader.', '.yt-dlp.update.')):
        return True
    if name.startswith('.cookies.') and name.endswith('.txt'):
        return True
    if name.startswith('.whisper.') and name.endswith('.zip'):
        return True
    return any(
        name.startswith(f'{base}.corrupt-')
        or name.startswith(f'.{base}.') and name.endswith('.tmp')
        or name == f'{base}.1'
        for base in state_names
    )


def remove_portable_state():
    """Remove app-owned portable state while preserving the executable/media."""
    root = Path(INSTALL_DIR)
    try:
        current = current_executable_path().resolve()
    except (OSError, RuntimeError):
        current = None
    known_paths, state_names = _portable_state_paths(root)
    known_paths = {path.resolve() for path in known_paths}
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        try:
            resolved = child.resolve()
        except (OSError, RuntimeError):
            continue
        if current is not None and resolved == current:
            continue
        if resolved not in known_paths and not _portable_state_child_matches(
            child.name, state_names
        ):
            continue
        try:
            if child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=False)
            else:
                child.unlink(missing_ok=True)
        except OSError as error:
            write_persistent_log(f"Could not remove portable state {child}: {error}")


def run_uninstall():
    write_persistent_log("Uninstall requested; removing Astra Downloader components.")

    stop_running_companion_for_uninstall()

    if is_portable_mode():
        remove_portable_state()
        message = (
            "Portable Astra Downloader state was removed. The executable and "
            "downloaded videos were not removed."
        )
        write_persistent_log(message)
        print(message)
        sys.exit(0)

    # Remove scheduled task
    subprocess.run(['schtasks', '/Delete', '/TN', 'AstraDownloader', '/F'],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)

    # Remove registry entries
    try:
        import winreg
        for path in [
            'Software\\Classes\\ytdl',
            'Software\\Classes\\mediadl',
            'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\AstraDownloader',
            INTEGRATIONS_STAMP_KEY,
        ] + [
            f'{root}\\{NATIVE_HOST_NAME}'
            for root in (
                *CHROMIUM_NATIVE_MESSAGING_REGISTRY_ROOTS,
                FIREFOX_NATIVE_MESSAGING_REGISTRY_ROOT,
            )
        ]:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + '\\shell\\open\\command')
            except Exception:
                # reason: each uninstall key may already be absent on a partial or older install
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + '\\shell\\open')
            except Exception:
                # reason: each uninstall key may already be absent on a partial or older install
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + '\\shell')
            except Exception:
                # reason: each uninstall key may already be absent on a partial or older install
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except Exception:
                # reason: each uninstall key may already be absent on a partial or older install
                pass
    except Exception:
        # reason: uninstall continues even when registry cleanup is unavailable
        pass

    if NATIVE_HOST_DIR.exists():
        shutil.rmtree(NATIVE_HOST_DIR, ignore_errors=True)

    # Remove desktop and Start Menu shortcuts
    for lnk in (Path.home() / "Desktop" / SHORTCUT_NAME,
                start_menu_programs_dir() / SHORTCUT_NAME):
        try:
            lnk.unlink(missing_ok=True)
        except OSError as error:
            write_persistent_log(f"Could not remove {lnk}: {error}")

    # Remove install directory
    if INSTALL_DIR.exists():
        try:
            shutil.rmtree(INSTALL_DIR, ignore_errors=False)
        except Exception:
            write_persistent_log("Install directory will be removed after exit.")
            if is_frozen_app():
                spawn_delayed_install_dir_removal(INSTALL_DIR)

    message = "Astra Downloader has been uninstalled. Downloaded videos were not removed."
    write_persistent_log(message)
    print(message)
    sys.exit(0)


def stop_running_companion_for_uninstall():
    """Ask only the instance for this data root to stop before removal."""
    graceful = send_instance_command('shutdown', attempts=3, delay=0.2)
    if graceful:
        # Give closeEvent time to stop the local API and cancel owned jobs.
        time.sleep(0.75)
    return graceful


def is_safe_install_dir_for_removal(path):
    """Return True only for the app-owned install directory shape."""
    try:
        resolved = Path(path).resolve()
    except Exception:
        return False
    if not resolved.is_absolute():
        return False
    if resolved.name != "AstraDownloader":
        return False
    # Avoid ever treating a drive root / user profile root as removable.
    return len(resolved.parts) >= 3


def spawn_delayed_install_dir_removal(path=INSTALL_DIR):
    """Remove the frozen app directory after this process exits."""
    if not is_safe_install_dir_for_removal(path):
        write_persistent_log(f"Refused delayed removal for unexpected install dir: {path}")
        return False
    target = str(Path(path).resolve())
    if sys.platform == 'win32':
        # powershell -Command joins every remaining argument into the command
        # text, so $args is always empty here — the path has to be embedded in
        # the script itself. Single-quote it (doubling any literal quote) so a
        # username containing a quote or a space cannot break out.
        quoted = "'" + target.replace("'", "''") + "'"
        script = f"Start-Sleep -Seconds 2; Remove-Item -LiteralPath {quoted} -Recurse -Force"
        subprocess.Popen(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    else:
        subprocess.Popen(
            [sys.executable, '-c', 'import shutil,sys,time; time.sleep(2); shutil.rmtree(sys.argv[1], ignore_errors=True)', target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True

class ReadinessProbe(_OwnedReadinessProbe):
    def __init__(self, configured_runtime='auto', *, impersonate_targets=None,
                 whisper_model_state=None, whisper_runtime_state=None,
                 readiness_sink=None, preflight_evaluator=None,
                 ffmpeg_capabilities=None, sign_in_entries=None,
                 github_api_budget=None):
        super().__init__(
            configured_runtime,
            runtime_probe=lambda *args, **kwargs: probe_javascript_runtime(*args, **kwargs),
            provider_probe=lambda *args, **kwargs: probe_po_token_provider(*args, **kwargs),
            ytdlp_version=lambda *args, **kwargs: get_ytdlp_version(*args, **kwargs),
            ffmpeg_version=lambda *args, **kwargs: get_ffmpeg_version(*args, **kwargs),
            logger=lambda message: write_persistent_log(message),
            impersonate_targets=(
                impersonate_targets
                or (lambda: probe_impersonate_targets())
            ),
            whisper_model_state=(
                whisper_model_state
                or (lambda: managed_binary_state(
                    WHISPER_MODEL_PATH, WHISPER_MODEL_MIN_BYTES
                ))
            ),
            whisper_runtime_state=(
                whisper_runtime_state
                or (lambda: probe_whisper_runtime(
                    WHISPER_BIN_PATH, WHISPER_BIN_MIN_BYTES
                ))
            ),
            readiness_sink=readiness_sink,
            preflight_evaluator=(
                preflight_evaluator
                or (lambda **kwargs: evaluate_preflight_checks(**kwargs))
            ),
            ffmpeg_capabilities=(
                ffmpeg_capabilities
                or (lambda: get_preflight_ffmpeg_capabilities())
            ),
            sign_in_entries=sign_in_entries,
            github_api_budget=(
                github_api_budget
                or (lambda: get_github_api_budget())
            ),
        )

# ══════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════
class MainWindow(MainWindowCore):
    def __init__(self, config, dl_manager, history, start_minimized=False,
                 subscriptions=None, first_run=False):
        super().__init__(
            config,
            dl_manager,
            history,
            start_minimized=start_minimized,
            first_run=first_run,
            dependencies={
                'APP_NAME': lambda: APP_NAME,
                'APP_VERSION': lambda: APP_VERSION,
                'DEFAULT_CONFIG': lambda: DEFAULT_CONFIG,
                'HISTORY_RETENTION_DEFAULT': lambda: HISTORY_RETENTION_DEFAULT,
                'HISTORY_RETENTION_MIN': lambda: HISTORY_RETENTION_MIN,
                'HISTORY_RETENTION_MAX': lambda: HISTORY_RETENTION_MAX,
                'DOWNLOAD_PENDING_STATES': lambda: DOWNLOAD_PENDING_STATES,
                'DOWNLOAD_INTERMEDIATE_DIRNAME': lambda: DOWNLOAD_INTERMEDIATE_DIRNAME,
                'DOWNLOAD_RETRYABLE_ERROR_CODES': lambda: DOWNLOAD_RETRYABLE_ERROR_CODES,
                'DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES': lambda: DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES,
                'DOWNLOAD_RUNNING_STATES': lambda: DOWNLOAD_RUNNING_STATES,
                'DOWNLOAD_TERMINAL_STATES': lambda: DOWNLOAD_TERMINAL_STATES,
                'FFMPEG_PATH': lambda: FFMPEG_PATH,
                'ICON_PATH': lambda: ICON_PATH,
                'INSTALL_DIR': lambda: INSTALL_DIR,
                'INSTANCE_CONTROL_HOST': lambda: INSTANCE_CONTROL_HOST,
                'INSTANCE_CONTROL_PORT': lambda: INSTANCE_CONTROL_PORT,
                'LOG_PATH': lambda: LOG_PATH,
                'MAX_SITE_LOGIN_TEXT_BYTES': lambda: MAX_SITE_LOGIN_TEXT_BYTES,
                'MODULE_FILE': lambda: __file__,
                'PORT_FALLBACKS': lambda: PORT_FALLBACKS,
                'ReadinessProbe': lambda *args, **kwargs: ReadinessProbe(*args, **kwargs),
                'TaskbarProgress': TaskbarProgress,
                'build_reveal_command': lambda *args, **kwargs: build_reveal_command(*args, **kwargs),
                'spawn_detached': lambda *args, **kwargs: spawn_detached(*args, **kwargs),
                'summarize_taskbar_progress': lambda *args, **kwargs: summarize_taskbar_progress(*args, **kwargs),
                'build_settings_bundle': lambda *args, **kwargs: build_settings_bundle(*args, **kwargs),
                'read_settings_bundle': lambda *args, **kwargs: read_settings_bundle(*args, **kwargs),
                'describe_bundle_changes': lambda *args, **kwargs: describe_bundle_changes(*args, **kwargs),
                'SERVER_PORT': lambda: SERVER_PORT,
                'SetupWorker': lambda *args, **kwargs: SetupWorker(*args, **kwargs),
                'YTDLP_PATH': lambda: YTDLP_PATH,
                'WHISPER_MODEL_MIN_BYTES': lambda: WHISPER_MODEL_MIN_BYTES,
                'WHISPER_MODEL_PATH': lambda: WHISPER_MODEL_PATH,
                'WHISPER_BIN_MIN_BYTES': lambda: WHISPER_BIN_MIN_BYTES,
                'WHISPER_BIN_PATH': lambda: WHISPER_BIN_PATH,
                '_build_wsgi_server': lambda *args, **kwargs: _build_wsgi_server(*args, **kwargs),
                '_ffmpeg_version_probe': lambda: _ffmpeg_version_probe,
                '_run_ytdlp_self_update': lambda *args, **kwargs: _run_ytdlp_self_update(*args, **kwargs),
                'build_diagnostics_bundle': lambda *args, **kwargs: build_diagnostics_bundle(*args, **kwargs),
                'check_download_disk_space': lambda *args, **kwargs: check_download_disk_space(*args, **kwargs),
                'clamp_int': lambda *args, **kwargs: clamp_int(*args, **kwargs),
                'create_api': lambda config_value, manager_value, history_value: create_api(
                    config_value,
                    manager_value,
                    history_value,
                    subscriptions=subscriptions,
                ),
                'get_ffmpeg_version': lambda *args, **kwargs: get_ffmpeg_version(*args, **kwargs),
                'get_recent_log_entries': lambda *args, **kwargs: get_recent_log_entries(*args, **kwargs),
                'get_ytdlp_version': lambda *args, **kwargs: get_ytdlp_version(*args, **kwargs),
                'SITE_LOGIN_BROWSERS': lambda: SITE_LOGIN_BROWSERS,
                'describe_browser_cookie_readiness': lambda *args, **kwargs: describe_browser_cookie_readiness(*args, **kwargs),
                'QUALITY_LADDER': lambda: QUALITY_LADDER,
                'is_playlist_url': lambda *args, **kwargs: is_playlist_url(*args, **kwargs),
                'is_youtube_url': lambda *args, **kwargs: is_youtube_url(*args, **kwargs),
                'probed_video_heights': lambda *args, **kwargs: probed_video_heights(*args, **kwargs),
                'SABR_LIMITED_NOTICE': lambda: SABR_LIMITED_NOTICE,
                'describe_sabr_voided_options': lambda *args, **kwargs: describe_sabr_voided_options(*args, **kwargs),
                'estimate_download_bytes': lambda *args, **kwargs: estimate_download_bytes(*args, **kwargs),
                'sabr_only_formats': lambda *args, **kwargs: sabr_only_formats(*args, **kwargs),
                'quality_choices_for_heights': lambda *args, **kwargs: quality_choices_for_heights(*args, **kwargs),
                'looks_like_media_link': lambda *args, **kwargs: looks_like_media_link(*args, **kwargs),
                'MANAGED_BINARY_ANTIVIRUS_ADVICE': lambda: MANAGED_BINARY_ANTIVIRUS_ADVICE,
                'managed_binary_state': lambda *args, **kwargs: managed_binary_state(*args, **kwargs),
                'managed_binary_usable': lambda *args, **kwargs: managed_binary_usable(*args, **kwargs),
                'probe_whisper_runtime': lambda *args, **kwargs: probe_whisper_runtime(*args, **kwargs),
                'evaluate_sabr_support': lambda *args, **kwargs: evaluate_sabr_support(*args, **kwargs),
                'maybe_auto_update_ytdlp': lambda *args, **kwargs: maybe_auto_update_ytdlp(*args, **kwargs),
                'normalize_output_dir': lambda *args, **kwargs: normalize_output_dir(*args, **kwargs),
                'normalize_sponsorblock_categories': lambda *args, **kwargs: normalize_sponsorblock_categories(*args, **kwargs),
                'normalize_download_section': lambda *args, **kwargs: normalize_download_section(*args, **kwargs),
                'normalize_output_template': lambda *args, **kwargs: normalize_output_template(*args, **kwargs),
                'output_template_preview': lambda *args, **kwargs: output_template_preview(*args, **kwargs),
                'normalize_playlist_date': lambda *args, **kwargs: normalize_playlist_date(*args, **kwargs),
                'normalize_impersonate_target': lambda *args, **kwargs: normalize_impersonate_target(*args, **kwargs),
                'probe_impersonate_targets': lambda *args, **kwargs: probe_impersonate_targets(*args, **kwargs),
                'normalize_proxy': lambda *args, **kwargs: normalize_proxy(*args, **kwargs),
                'normalize_force_ip_version': lambda *args, **kwargs: normalize_force_ip_version(*args, **kwargs),
                'normalize_source_address': lambda *args, **kwargs: normalize_source_address(*args, **kwargs),
                'normalize_xff': lambda *args, **kwargs: normalize_xff(*args, **kwargs),
                'normalize_rate_limit': lambda *args, **kwargs: normalize_rate_limit(*args, **kwargs),
                'select_site_profile': lambda *args, **kwargs: select_site_profile(*args, **kwargs),
                'validate_site_profiles': lambda *args, **kwargs: validate_site_profiles(*args, **kwargs),
                'normalize_sponsorblock_categories': lambda *args, **kwargs: normalize_sponsorblock_categories(*args, **kwargs),
                'SPONSORBLOCK_CATEGORIES': lambda: SPONSORBLOCK_CATEGORIES,
                'normalize_sublangs': lambda *args, **kwargs: normalize_sublangs(*args, **kwargs),
                'normalize_subtitle_mode': lambda *args, **kwargs: normalize_subtitle_mode(*args, **kwargs),
                'normalize_subtitle_format': lambda *args, **kwargs: normalize_subtitle_format(*args, **kwargs),
                'normalize_url': lambda *args, **kwargs: normalize_url(*args, **kwargs),
                'quarantined_state_files': lambda *args, **kwargs: quarantined_state_files(*args, **kwargs),
                'lookup_history_url': lambda *args, **kwargs: lookup_history_url(*args, **kwargs),
                'query_history_entries': lambda *args, **kwargs: query_history_entries(*args, **kwargs),
                'reset_deno_runtime_cache': lambda *args, **kwargs: reset_deno_runtime_cache(*args, **kwargs),
                'restore_quarantined_file': lambda *args, **kwargs: restore_quarantined_file(*args, **kwargs),
                'reset_ffmpeg_capabilities_cache': lambda *args, **kwargs: reset_ffmpeg_capabilities_cache(*args, **kwargs),
                'subscription_manager': subscriptions,
                'write_persistent_log': lambda *args, **kwargs: write_persistent_log(*args, **kwargs),
                'apply_theme': lambda theme: apply_application_theme(theme),
            },
        )


# ══════════════════════════════════════════════════════════════
# SINGLE INSTANCE GUARD
# ══════════════════════════════════════════════════════════════
INSTANCE_ALREADY_RUNNING = object()


# Windows uses this string to decide which taskbar button a window belongs to
# and which application a toast is attributed to. The documented shape is
# CompanyName.ProductName[.SubProduct][.VersionInformation], deliberately
# without a version: it must stay stable across releases or an upgrade
# orphans the user's pinned shortcut.
APP_USER_MODEL_ID = "SysAdminDoc.AstraDownloader"


def set_app_user_model_id(app_id=APP_USER_MODEL_ID):
    """Claim an explicit taskbar identity. Returns whether Windows took it.

    An unpackaged executable that never calls this gets an identity derived
    from its path, so a pinned shortcut and the running process disagree and
    the taskbar shows two buttons for one app.
    """
    try:
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            str(app_id)
        )
    except Exception as error:
        # reason: a non-Windows host or a shell32 without the export leaves
        # the process on the default identity, which is cosmetic, not fatal
        write_persistent_log(f"Could not set the taskbar identity: {error}")
        return False
    # S_OK is 0; anything else is an HRESULT failure worth recording but not
    # worth refusing to start over.
    if result != 0:
        write_persistent_log(
            f"Windows refused the taskbar identity (HRESULT {result:#010x})"
        )
        return False
    return True


# Aggregate taskbar progress states, in ITaskbarList3::SetProgressState's
# own vocabulary. Named here so the pure decision — what the queue as a whole
# is doing — can be tested without a window handle or a COM apartment.
TASKBAR_PROGRESS_NONE = 0x0
TASKBAR_PROGRESS_INDETERMINATE = 0x1
TASKBAR_PROGRESS_NORMAL = 0x2
TASKBAR_PROGRESS_ERROR = 0x4
TASKBAR_PROGRESS_PAUSED = 0x8


def summarize_taskbar_progress(downloads, running_states, terminal_states):
    """Reduce the queue to one (state, completed, total) the taskbar can show.

    Windows gives a single button one bar, so several downloads have to become
    one number. Percent-of-all-work is the honest reduction: five downloads at
    20% reads as 20%, not as "one of five finished". Sizes are unknown until a
    transfer starts, so each job counts as one unit of work and contributes
    its own percentage.
    """
    active = [
        download for download in downloads
        if getattr(download, 'status', '') in running_states
    ]
    if not active:
        # Nothing is running: leave the button alone rather than showing an
        # empty bar over an idle app.
        return (TASKBAR_PROGRESS_NONE, 0, 0)
    # A download that already failed is deliberately not reflected here: the
    # error state would colour the button red for work that is still running
    # fine, and the failure is already reported on its own card.
    total = len(active) * 100
    completed = 0
    for download in active:
        try:
            progress = float(getattr(download, 'progress', 0) or 0)
        except (TypeError, ValueError):
            progress = 0.0
        completed += max(0.0, min(100.0, progress))
    # Before the first progress line lands there is nothing to show but the
    # fact that work is happening, which is what indeterminate means.
    if completed <= 0:
        return (TASKBAR_PROGRESS_INDETERMINATE, 0, total)
    return (TASKBAR_PROGRESS_NORMAL, int(completed), total)


class TaskbarProgress:
    """ITaskbarList3 progress on the main window's taskbar button.

    Qt 6 dropped QtWinExtras, which is where QWinTaskbarButton lived, so this
    talks to the COM interface directly. Every entry point is guarded: the
    taskbar is a nicety, and an app that refuses to run because a shell
    interface was unavailable would be a worse bug than a missing bar.
    """

    CLSID_TASKBAR_LIST = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
    IID_TASKBAR_LIST3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
    # ITaskbarList3 vtable slots. IUnknown takes 0-2, ITaskbarList 3-6,
    # ITaskbarList2 7, and ITaskbarList3's own methods start at 8.
    VTBL_HRINIT = 3
    VTBL_SET_PROGRESS_VALUE = 9
    VTBL_SET_PROGRESS_STATE = 10

    def __init__(self, logger=None):
        self._logger = logger or write_persistent_log
        self._taskbar = None
        self._unavailable = False
        self._last = None

    def _interface(self):
        if self._taskbar is not None or self._unavailable:
            return self._taskbar
        try:
            import ctypes

            ole32 = ctypes.oledll.ole32
            ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
            clsid = _guid_from_string(self.CLSID_TASKBAR_LIST)
            iid = _guid_from_string(self.IID_TASKBAR_LIST3)
            pointer = ctypes.c_void_p()
            ole32.CoCreateInstance(
                ctypes.byref(clsid), None, 1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(iid), ctypes.byref(pointer),
            )
            self._taskbar = pointer
            self._call(self.VTBL_HRINIT)
        except Exception as error:
            self._unavailable = True
            self._taskbar = None
            self._logger(f"Taskbar progress is unavailable: {error}")
        return self._taskbar

    def _call(self, slot, *argtypes_and_args):
        import ctypes

        pointer = self._taskbar
        if not pointer:
            return None
        vtable = ctypes.cast(
            pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        )[0]
        argtypes = [item for item in argtypes_and_args if isinstance(item, type)]
        args = [item for item in argtypes_and_args if not isinstance(item, type)]
        prototype = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, *argtypes
        )
        return prototype(vtable[slot])(pointer, *args)

    def apply(self, window_id, state, completed, total):
        """Push one (state, completed, total) onto the taskbar button."""
        import ctypes

        if not window_id:
            return False
        current = (int(window_id), state, completed, total)
        if current == self._last:
            # The UI tick runs twice a second; the shell does not need to
            # hear the same number again.
            return True
        if self._interface() is None:
            return False
        try:
            handle = ctypes.c_void_p(int(window_id))
            self._call(
                self.VTBL_SET_PROGRESS_STATE,
                ctypes.c_void_p, ctypes.c_int, handle, state,
            )
            if state == TASKBAR_PROGRESS_NORMAL:
                self._call(
                    self.VTBL_SET_PROGRESS_VALUE,
                    ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ulonglong,
                    handle, max(0, int(completed)), max(1, int(total)),
                )
        except Exception as error:
            self._unavailable = True
            self._logger(f"Taskbar progress update failed: {error}")
            return False
        self._last = current
        return True


def _guid_from_string(text):
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    ctypes.oledll.ole32.CLSIDFromString(str(text), ctypes.byref(guid))
    return guid


def spawn_detached(command):
    """Start a shell helper and stop caring about it.

    Explorer is not a subprocess this app supervises: it outlives the window
    that opened it, and waiting on it or holding its pipes would tie a UI
    click to a process the user now owns.
    """
    # `command` is a command line string for the shell helpers that need
    # exact quoting (see build_reveal_command) and a list otherwise.
    return subprocess.Popen(
        command if isinstance(command, str) else list(command),
        creationflags=CREATE_NEW_PROCESS_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def build_reveal_command(file_path):
    r"""Return the command LINE that opens Explorer with `file_path` selected.

    `os.startfile` on the parent directory opens the folder but selects
    nothing, so a user with a full Downloads folder still has to hunt for the
    file that just finished.

    This returns a string, not an argv list, and that is the whole point.
    Explorer wants `/select,` and the path in one token with the quotes
    around the PATH only. Building it as a list and letting Python quote it
    produces `"/select,C:\dir\My File.mp4"` — one quoted argument — and
    Explorer silently ignores it and opens the user's Documents folder
    instead. Measured against the real shell: the list form opened
    "Documents - File Explorer" for a path containing a space.
    """
    if not file_path:
        return None
    try:
        target = Path(file_path)
        if not target.is_file():
            return None
        resolved = target.resolve()
    except (OSError, ValueError):
        return None
    if '"' in str(resolved):
        # A quote in the path would break out of the quoting below. Nothing
        # on Windows can create such a name, but the reveal is a nicety and
        # refusing it is cheaper than reasoning about the escape.
        return None
    return f'explorer.exe /select,"{resolved}"' 


def check_single_instance(startup_command=''):
    """Prevent multiple GUI instances without relying on a TCP port."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            mutex_name = (
                "Local\\AstraDownloader.SingleInstance."
                + instance_namespace_for_root()
            )
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if not handle:
                error = ctypes.get_last_error()
                raise OSError(error, f"single-instance mutex creation failed ({error})")
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                send_instance_command(startup_command or 'show')
                return INSTANCE_ALREADY_RUNNING
            return handle
        except Exception as e:
            write_persistent_log(f"Mutex single-instance guard unavailable: {e}")
            raise

    # Cross-platform fallback for source runs outside Windows.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', INSTANCE_LOCK_PORT))
        s.listen(1)
        return s  # Keep alive
    except OSError as exc:
        try:
            s.close()
        except Exception:
            # reason: a failed bind may leave no closable socket to release
            pass
        if send_instance_command(startup_command or 'show', attempts=1):
            return INSTANCE_ALREADY_RUNNING
        raise OSError(f"single-instance lock is occupied and the existing app did not respond: {exc}") from exc

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
# ──────────────────────────────────────────────────────────────────────────
# Native-messaging token bootstrap (browser-pinned channel)
#
# Native messaging is the primary token bootstrap path: the host manifest's
# allowed_origins pins exactly which extension IDs may launch this process, and
# the browser delivers the message over a private stdio pipe no other process
# can read. The old HTTP /health echo remains behind an explicit compatibility
# switch plus extension-origin allowlist for older local installs.
#
# These functions are the testable core of that design.
# ──────────────────────────────────────────────────────────────────────────

NATIVE_HOST_NAME = "com.astra.deck.downloader"
NATIVE_MESSAGE_MAX_BYTES = 1024 * 1024  # Chrome caps host->browser at 1 MB


def read_native_message(stream):
    """Read one Chrome native message: 4-byte little-endian length + UTF-8 JSON.

    Returns the decoded object, or None at clean EOF (browser closed the pipe).
    """
    raw_len = stream.read(4)
    if not raw_len or len(raw_len) < 4:
        return None
    msg_len = struct.unpack('<I', raw_len)[0]
    if msg_len <= 0 or msg_len > NATIVE_MESSAGE_MAX_BYTES:
        raise ValueError("native message length out of range: %d" % msg_len)
    body = stream.read(msg_len)
    if len(body) < msg_len:
        raise ValueError("truncated native message")
    return json.loads(body.decode('utf-8'))


def write_native_message(stream, obj):
    """Write one Chrome native message (4-byte LE length prefix + UTF-8 JSON)."""
    body = json.dumps(obj, separators=(',', ':')).encode('utf-8')
    stream.write(struct.pack('<I', len(body)))
    stream.write(body)
    stream.flush()


def handle_native_bootstrap_request(request, token):
    """Pure handler for a parsed bootstrap request. No I/O — easy to unit test."""
    if not isinstance(request, dict):
        return {"ok": False, "error": "invalid request"}
    req_type = request.get("type")
    if req_type == "ping":
        return {"ok": True, "service": SERVICE_ID, "api": SERVICE_API_VERSION}
    if req_type == "get-token":
        if not token:
            return {"ok": False, "error": "no token configured"}
        return {
            "ok": True,
            "service": SERVICE_ID,
            "api": SERVICE_API_VERSION,
            "token": token,
        }
    return {"ok": False, "error": "unsupported request type"}


def run_native_messaging_host(token, stdin=None, stdout=None):
    """Serve bootstrap requests over stdio until the browser closes the pipe."""
    stdin = stdin if stdin is not None else getattr(sys.stdin, 'buffer', sys.stdin)
    stdout = stdout if stdout is not None else getattr(sys.stdout, 'buffer', sys.stdout)
    while True:
        request = read_native_message(stdin)
        if request is None:
            return
        write_native_message(stdout, handle_native_bootstrap_request(request, token))


def argv_requests_native_host(argv):
    """True when the browser launched us as a native-messaging host.

    Chrome passes the calling extension's origin as a positional argv
    (chrome-extension://<id>/). Firefox instead passes the registered host
    manifest path followed by the configured Gecko extension ID. The Firefox
    form is accepted only for the exact manifest we registered and only when
    that manifest explicitly allows the supplied ID, so an arbitrary path or
    normal application argument cannot enter the stdio-only path.
    """
    args = list(argv or [])
    if any(
        isinstance(a, str) and (a.startswith("chrome-extension://") or a.startswith("moz-extension://"))
        for a in args
    ):
        return True

    if len(args) < 2 or not isinstance(args[0], str) or not isinstance(args[1], str):
        return False
    manifest_path = Path(args[0])
    extension_id = args[1].strip()
    expected_path = Path(NATIVE_HOST_DIR) / f"{NATIVE_HOST_NAME}.firefox.json"
    if not extension_id or manifest_path.suffix.lower() != ".json" or manifest_path.name != expected_path.name:
        return False
    try:
        if manifest_path.resolve(strict=True) != expected_path.resolve(strict=True):
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return False
    allowed_extensions = manifest.get("allowed_extensions") if isinstance(manifest, dict) else None
    return (
        isinstance(manifest, dict)
        and manifest.get("name") == NATIVE_HOST_NAME
        and manifest.get("type") == "stdio"
        and isinstance(allowed_extensions, list)
        and extension_id in allowed_extensions
    )


def build_native_host_manifest(exe_path, extension_ids, browser="chrome"):
    """Build a browser native-messaging host manifest.

    Chrome uses `allowed_origins` with chrome-extension:// IDs. Firefox uses
    `allowed_extensions` with Gecko IDs. Both are the browser-pinned security
    boundary HTTP /health lacks.
    """
    browser = str(browser or 'chrome').strip().lower()
    ids = parse_native_extension_ids(extension_ids, browser=browser)
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "Astra Downloader token bootstrap",
        "path": str(exe_path),
        "type": "stdio",
    }
    if browser == "firefox":
        manifest["allowed_extensions"] = ids
    else:
        manifest["allowed_origins"] = ["chrome-extension://%s/" % eid for eid in ids]
    return manifest


def companion_probe_exit_code(argv):
    """Return a non-GUI probe exit code, or None for a normal application run."""
    args = list(argv or [])
    if '--version' in args:
        return 0
    if '--update-health-check' not in args:
        return None
    index = args.index('--update-health-check')
    expected = args[index + 1].strip() if index + 1 < len(args) else ''
    if not expected or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', expected):
        return 2
    return 0 if hmac.compare_digest(expected, APP_VERSION) else 3


def companion_install_exit_code(argv=None):
    """Install a frozen copy and integrations without opening the GUI."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--install" not in args:
        return None
    if "--portable" in args or is_portable_mode():
        write_persistent_log("The --install and --portable modes cannot be combined.")
        return 2
    if not is_frozen_app():
        write_persistent_log("The silent install path requires the packaged executable.")
        return 2
    if is_onedir_build():
        write_persistent_log(
            "The one-folder build is already self-contained; use the one-file executable for --install."
        )
        return 2
    target = install_target_exe().resolve()
    installed = ensure_installed_executable()
    try:
        installed_path = Path(installed).resolve()
    except (OSError, TypeError, ValueError):
        installed_path = Path(installed)
    if installed_path != target or not target.is_file():
        write_persistent_log(
            f"Silent install did not produce the managed executable at {target}."
        )
        return 1
    try:
        ensure_system_integrations(prefer_installed=True, force=True)
    except Exception as error:  # noqa: BLE001 - a CLI path must return a code
        write_persistent_log(f"Silent install integration setup failed: {error}")
        return 1
    output = getattr(sys, "stdout", None)
    if output is not None:
        output.write(f"{APP_NAME} installed to {target}\n")
        output.flush()
    return 0


def main():
    probe_exit = companion_probe_exit_code(sys.argv[1:])
    if probe_exit is not None:
        if probe_exit == 0:
            output = getattr(sys, 'stdout', None)
            if output is not None:
                output.write(APP_VERSION + '\n')
                output.flush()
            return
        raise SystemExit(probe_exit)

    install_exit = companion_install_exit_code(sys.argv[1:])
    if install_exit is not None:
        raise SystemExit(install_exit)

    # Native-messaging host mode: the browser launches us with the extension
    # origin as an argv. Serve the token bootstrap over the private stdio pipe
    # and exit — before any GUI / single-instance / Flask logic.
    if argv_requests_native_host(sys.argv[1:]):
        try:
            run_native_messaging_host(Config(read_only=True).get("ServerToken"))
        except Exception as exc:  # noqa: BLE001 - host must never crash loudly
            write_persistent_log("native messaging host error: %s" % exc)
        return

    # Handle --uninstall flag
    if '--uninstall' in sys.argv:
        run_uninstall()
        return

    visual_smoke = '--visual-smoke' in sys.argv
    startup_command = startup_command_from_argv()
    start_minimized = '-Background' in sys.argv or '--background' in sys.argv or startup_command == 'start'
    seed_log_ring()
    cleanup_update_scratch_files()
    _reconcile_stale_companion_activation()
    log_update_recovery_status()

    if is_frozen_app() and not visual_smoke and not is_portable_mode():
        ensure_system_integrations(prefer_installed=True)

    # A second launch delegates to the healthy process and exits. Never kill a
    # live companion here: it may own active yt-dlp/ffmpeg jobs. The visual-smoke
    # capture is a throwaway render that must never delegate to — or disturb — a
    # running companion, so it skips the guard entirely.
    if not visual_smoke:
        try:
            lock = check_single_instance(startup_command)
        except Exception as exc:
            write_persistent_log(f"Could not establish the single-instance guard: {exc}")
            return
        if lock is INSTANCE_ALREADY_RUNNING:
            write_persistent_log("Existing Astra Downloader instance accepted the launch request.")
            return

    # Before the first window exists, and before the tray icon is created:
    # Windows binds an unpackaged process to a taskbar identity at first
    # window creation, and without an explicit one it guesses from the
    # executable path. That guess is what makes a pinned shortcut launch a
    # second, unpinned button, and it is also the identity toasts are
    # attributed to.
    set_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Segoe UI", 9))
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Init. Capture whether this is a genuinely new state directory before
    # ConfigStore creates the initial JSON file. The first-run destination
    # checkpoint remains durable if the user closes the app before confirming.
    first_launch = not CONFIG_PATH.exists()
    config = Config()
    if first_launch and not config.update({"FirstRunComplete": False}):
        write_persistent_log(
            "Could not persist the first-run marker; onboarding will remain visible this session."
        )
    apply_application_theme(config.get("Theme", "system"))
    first_run = first_launch or not bool(
        config.get("FirstRunComplete", True)
    )
    # Retain the translator for the QApplication lifetime. Qt removes a
    # translator when its QObject wrapper is garbage-collected.
    app._astra_translator = install_companion_translator(
        app, config.get("Language", "system")
    )
    history = History(config)
    dl_manager = DownloadManager(config, history, queue_path=DOWNLOAD_QUEUE_PATH)
    subscriptions = build_subscription_manager(config, dl_manager)
    dl_manager.download_completed.connect(subscriptions.handle_download_completed)
    subscriptions.reconcile_downloads(dl_manager.snapshot())

    # v1.2.2: GUI-thread folder picker bridge for /pick-folder requests.
    # Module-scoped reference keeps the QTimer alive for the app lifetime.
    global _folder_picker_service
    _folder_picker_service = FolderPickerService()

    # The old global archive file belonged to the removed all-download lock.
    # Subscription archives now live in subscriptions.json and must survive
    # companion updates, so only the obsolete legacy file is swept.
    try:
        legacy_archive = INSTALL_DIR / 'archive.txt'
        if legacy_archive.exists():
            legacy_archive.unlink()
    except OSError:
        # reason: the obsolete archive is optional and may already be removed
        pass

    start_min = start_minimized or config.get("StartMinimized", False)
    window = MainWindow(
        config,
        dl_manager,
        history,
        start_minimized=start_min,
        subscriptions=subscriptions,
        first_run=first_run,
    )
    # The application palette is selected before construction; apply the DWM
    # title-bar attribute again now that the top-level window has a handle.
    apply_application_theme(config.get("Theme", "system"), windows=(window,))
    # An exception escaping a slot used to abort the process with nothing
    # written anywhere. Route it to the crash log and to the window's log
    # panel, which is where a user already looks when something misbehaves.
    install_unhandled_exception_hooks(
        notify=lambda text: window.log_message.emit(f"Unhandled error: {text}")
    )

    # A ytdl:// link clicked while nothing was running launches this process
    # with the URL as argv. The already-running case travels the instance
    # control socket instead; both land in enqueue_protocol_download.
    protocol_url = download_url_from_protocol_argv()
    if protocol_url and not visual_smoke:
        QTimer.singleShot(0, lambda: window.enqueue_protocol_download(protocol_url))

    # The visual-smoke path exercises the frozen UI without installing system
    # integrations, starting the local server, or bootstrapping helper tools.
    # Not `.exists()`: a quarantine stub is present but unusable, and the
    # app would otherwise start the server around a tool it cannot run.
    needs_setup = not (managed_binary_usable(YTDLP_PATH)
                       and managed_binary_usable(FFMPEG_PATH))
    if visual_smoke:
        window.show()
    elif needs_setup or first_run:
        window.show()
        if needs_setup:
            window._run_setup()
        else:
            window._start_server()
    else:
        if not start_min:
            window.show()
        window._start_server()

    sys.exit(app.exec())

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        report_fatal_error(f"Fatal startup error: {type(error).__name__}: {error}")
        sys.exit(1)
