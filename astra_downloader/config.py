"""Configuration boundary for Astra Downloader.

Exports still owned by the legacy composition module resolve on first access.
Importing this boundary itself is dependency-light and never imports GUI/server
frameworks, which lets config tooling and tests run without PyQt or Flask.
"""

import os
import ctypes
import ipaddress
import json
import math
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

try:
    from ._compat import make_legacy_resolver
except ImportError:  # Flat source-path compatibility.
    from _compat import make_legacy_resolver

try:
    from .companion_ports import PORT_FALLBACKS, SERVER_PORT
except ImportError:  # Flat source-path compatibility.
    from companion_ports import PORT_FALLBACKS, SERVER_PORT


__all__ = (
    "APP_NAME", "APP_VERSION", "SERVICE_ID", "SERVICE_API_VERSION",
    "SERVER_PORT", "PORT_FALLBACKS", "MAX_CONCURRENT", "MAX_QUEUED_TOTAL",
    "DEFAULT_CONFIG", "INSTALL_DIR", "CONFIG_PATH", "HISTORY_PATH",
    "default_download_path",
    "CORS_MAX_AGE_SECONDS", "RATE_LIMIT_DOWNLOAD_MAX",
    "RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS", "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES", "HELPER_DOWNLOAD_MAX_BYTES", "sanitize_config",
    "normalize_url", "normalize_output_dir", "normalize_download_section",
    "normalize_playlist_items",
    "media_url_block_reason", "is_supported_media_url",
    "describe_media_url_block", "looks_like_media_link",
    "MEDIA_URL_BLOCK_MESSAGES", "MEDIA_HOST_HINTS",
    "validate_download_request_body",
    "allowed_output_roots", "clean_text", "clean_path_text", "coerce_bool",
    "clamp_int", "normalize_rate_limit", "normalize_proxy",
    "normalize_force_ip_version", "normalize_source_address", "normalize_xff",
    "normalize_site_profile_domain", "normalize_site_profiles",
    "validate_site_profiles", "SITE_PROFILE_OVERRIDE_KEYS",
    "output_template_preview", "WINDOWS_MAX_PATH",
    "normalize_sublangs",
    "normalize_sponsorblock_categories", "SPONSORBLOCK_CATEGORIES", "normalize_impersonate_target",
    "normalize_subtitle_mode", "normalize_subtitle_format",
    "SUBTITLE_MODES", "SUBTITLE_FORMATS", "JAVASCRIPT_RUNTIME_CHOICES",
    "build_settings_bundle", "read_settings_bundle", "describe_bundle_changes",
    "SETTINGS_BUNDLE_SCHEMA", "SETTINGS_BUNDLE_VERSION", "BUNDLE_EXCLUDED_SETTINGS",
    "write_persistent_log", "get_recent_log_entries", "log_crash",
    "atomic_write_json", "download_file_atomic", "load_json_file",
    "backup_corrupt_file", "sanitize_history_entries", "query_history_entries",
    "quarantined_state_files", "restore_quarantined_file",
    "record_quarantined_file", "forget_quarantined_file",
    "verify_file_sha256", "fetch_expected_sha256", "cleanup_stale_cookie_jars",
    "write_cookies_netscape", "RateLimiter", "Config", "History",
    "DOWNLOAD_REQUEST_ALLOWED_FIELDS", "DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS",
    "ConfigStore", "HistoryStore",
)

_OWNED_EXPORTS = {
    "clean_text", "clean_path_text", "coerce_bool", "clamp_int",
    "normalize_rate_limit", "normalize_proxy",
    "normalize_force_ip_version", "normalize_source_address", "normalize_xff",
    "normalize_site_profile_domain", "normalize_site_profiles",
    "validate_site_profiles", "SITE_PROFILE_OVERRIDE_KEYS",
    "output_template_preview", "WINDOWS_MAX_PATH",
    "normalize_sublangs",
    "normalize_sponsorblock_categories", "SPONSORBLOCK_CATEGORIES",
    "normalize_subtitle_mode", "normalize_subtitle_format",
    "SUBTITLE_MODES", "SUBTITLE_FORMATS", "JAVASCRIPT_RUNTIME_CHOICES",
    "build_settings_bundle", "read_settings_bundle", "describe_bundle_changes",
    "SETTINGS_BUNDLE_SCHEMA", "SETTINGS_BUNDLE_VERSION", "BUNDLE_EXCLUDED_SETTINGS",
    "bound_output_template_fields",
    "normalize_output_template",
    "normalize_url", "normalize_download_section", "normalize_playlist_items",
    "media_url_block_reason", "is_supported_media_url",
    "describe_media_url_block", "looks_like_media_link",
    "MEDIA_URL_BLOCK_MESSAGES", "MEDIA_HOST_HINTS",
    "validate_download_request_body",
    "normalize_output_dir", "allowed_output_roots",
    "DEFAULT_CONFIG", "sanitize_config",
    "default_download_path",
    "ConfigStore", "HistoryStore", "atomic_write_json", "load_json_file",
    "backup_corrupt_file", "sanitize_history_entries",
    "quarantined_state_files", "restore_quarantined_file",
    "record_quarantined_file", "forget_quarantined_file",
    "DOWNLOAD_REQUEST_ALLOWED_FIELDS", "DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_TEXT_FIELD = 500
_MAX_PATH_FIELD = 2048
MAX_LOCAL_JSON_BYTES = 16 * 1024 * 1024
DOWNLOAD_REQUEST_ALLOWED_FIELDS = frozenset({
    "url", "audioOnly", "format", "quality", "outputDir", "title",
    "referer", "cookies", "section", "playlistItems", "videoPassword",
})
_MAX_VIDEO_PASSWORD_BYTES = 4096
DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS = frozenset({
    "args", "argv", "flags", "extraArgs", "extractorArgs",
    "postprocessorArgs", "postprocessor_args", "externalDownloaderArgs",
    "ytDlpArgs", "ytdlpArgs", "yt_dlp_args",
})


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


# The JavaScript runtimes a user may store. "auto" walks the rest in
# yt-dlp's own priority order; the probe half lives in health.py and a test
# pins the two vocabularies together.
JAVASCRIPT_RUNTIME_CHOICES = frozenset({"auto", "deno", "node", "quickjs"})

# The soft format preferences a user can express. This is the schema half:
# the mapping from these tokens to yt-dlp `--format-sort` fields lives in
# download.py, which owns argv, and a test pins the two vocabularies together
# so neither can gain a value the other does not know.
FORMAT_SORT_VIDEO_CODECS = frozenset({"auto", "h264", "vp9", "av1"})
FORMAT_SORT_AUDIO_CODECS = frozenset({"auto", "aac", "opus"})
FORMAT_SORT_FRAME_RATES = (0, 30, 60)


def _known_folder_path_windows():
    """Return the user's Windows Videos folder, or ``None`` on failure."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

        folder_id = GUID(
            0x18989B1D,
            0x99B5,
            0x455B,
            (wintypes.BYTE * 8)(0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDD, 0xFC),
        )
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree.restype = None
        path_ptr = ctypes.c_wchar_p()
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)
        )
        try:
            if result != 0 or not path_ptr.value:
                return None
            return Path(path_ptr.value)
        finally:
            ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def default_download_path():
    """Return the user's Videos folder without rewriting saved settings."""
    return str(_known_folder_path_windows() or (Path.home() / "Videos"))


DEFAULT_CONFIG = {
    "DownloadPath": default_download_path(),
    "AudioDownloadPath": "",
    "ServerPort": SERVER_PORT,
    "ServerToken": "",
    "LegacyHealthTokenEcho": _env_bool("ASTRA_LEGACY_HEALTH_TOKEN_ECHO", False),
    "LegacyHealthTokenOrigins": os.environ.get("ASTRA_LEGACY_HEALTH_TOKEN_ORIGINS", ""),
    "EmbedMetadata": True,
    "EmbedThumbnail": True,
    "EmbedChapters": True,
    "EmbedSubs": False,
    # Local Whisper transcription is opt-in. When enabled, a successful
    # media download with no subtitle track is followed by an SRT sidecar.
    "GenerateSubtitles": False,
    # Archive sidecars and chapter/live capture are opt-in. They write beside
    # the finished media and deliberately do not alter the existing embed
    # switches above.
    "WriteInfoJson": False,
    "WriteDescription": False,
    "WriteThumbnail": False,
    "SplitChapters": False,
    "LiveFromStart": False,
    "WaitForVideoSeconds": 0,
    # Downloads stage .part / .f### / .ytdl files in a private per-download
    # directory and sweep it after success. Turn this on to stage them beside
    # the output and keep them when diagnosing a merge problem.
    "KeepIntermediateFiles": False,
    # Verify a chosen format is actually downloadable before committing to it.
    # Off by default: it costs an extra request per candidate format.
    "VerifyFormats": False,
    # Soft codec and frame-rate preferences, compiled into --format-sort. The
    # container choice is a hard constraint and still wins: MP4 forces H.264
    # + AAC so an editor imports the result without transcoding. These order
    # what is left. "auto" leaves yt-dlp's own ordering alone.
    "VideoCodecPreference": "auto",
    "AudioCodecPreference": "auto",
    # Preferred frame rate, as a target rather than a cap: 60 puts 60fps
    # first and falls back rather than failing. 0 expresses no preference.
    "PreferredFrameRate": 0,
    # Bounds for a playlist or channel download. A pasted playlist otherwise
    # queues every item it contains. These apply only to a run that walks a
    # playlist — a single video is never filtered by them. 0 and "" disable
    # each independently.
    #
    # Deliberately NOT --download-archive: the archive-key mechanism in
    # subscriptions.py is this project's answer to "already seen", and a
    # second one would make a re-download report "already downloaded".
    "PlaylistMaxItems": 0,
    # An absolute YYYYMMDD, or a yt-dlp relative date like "today-30days".
    "PlaylistDateAfter": "",
    "PlaylistMinDurationSeconds": 0,
    "PlaylistMaxDurationSeconds": 0,
    # Browser TLS/HTTP fingerprint to imitate, from the targets the installed
    # yt-dlp reports. Empty is off. The standard remedy for a Cloudflare or
    # fingerprint 403 — but it can itself provoke a 429 on some sites, so it
    # is opt-in rather than a default.
    "ImpersonateTarget": "",
    # Below this rate yt-dlp assumes the CDN is throttling and re-extracts the
    # video rather than crawling to the stall watchdog. Empty disables it.
    "ThrottledRate": "",
    # 0 leaves yt-dlp's own defaults in place for both of these.
    "SocketTimeoutSeconds": 0,
    "ExtractorRetries": 0,
    # Request pacing. A bandwidth cap does not stop a 429; spacing the
    # requests does. 0 disables each independently.
    "SleepIntervalSeconds": 0,
    "MaxSleepIntervalSeconds": 0,
    "SleepRequestsSeconds": 0,
    # Randomise host backoffs and the yt-dlp sleep range by this percentage.
    # Zero keeps the historical fixed pacing behaviour.
    "PacingJitterPercent": 0,
    "SubLangs": "en",
    # Creator-written captions, the machine transcript, or the former with the
    # latter as fallback (which is what this app has always done).
    "SubtitleMode": "prefer-manual",
    # Normalise every fetched track to one format. Empty keeps the site's.
    "SubtitleFormat": "",
    "SponsorBlock": False,
    "SponsorBlockAction": "remove",
    # Which SponsorBlock categories to act on. Empty means every category,
    # which is what the app used to send unconditionally — enabling it to skip
    # sponsors also stripped intros, outros and self-promo.
    "SponsorBlockCategories": "sponsor,selfpromo,interaction",
    "ConcurrentFragments": 4,
    # How many downloads run at once (was the hardcoded MAX_CONCURRENT=3).
    "MaxConcurrentDownloads": 3,
    # yt-dlp --retries / --fragment-retries. 10 matches yt-dlp's own default,
    # so the shipped value preserves current behavior while letting users on
    # flaky networks raise it.
    "DownloadRetries": 10,
    # "auto" walks deno, then node, then the QuickJS build the app can fetch
    # for itself, which is yt-dlp's own priority order.
    "JavaScriptRuntime": "auto",
    "AutoUpdateYtDlp": True,
    # yt-dlp release channel the self-updater tracks. Nightly is yt-dlp's own
    # recommendation for regular users: the monthly stable channel lags YouTube
    # breakage by weeks, while nightly ships same-day extractor fixes.
    "YtDlpUpdateChannel": "nightly",
    "RateLimit": "",
    "Proxy": "",
    # Network-path workarounds are opt-in. A whole-session proxy remains the
    # broad control; these target dual-stack routing and geo verification only
    # when a site or network actually needs them.
    "ForceIPVersion": "",
    "SourceAddress": "",
    "Xff": "",
    "GeoVerificationProxy": "",
    # Named per-domain defaults. Secrets deliberately do not belong here:
    # cookies and credentials remain in SiteLoginStore, scoped by site.
    "SiteProfiles": [],
    "Language": "system",
    "StartMinimized": False,
    "CloseToTray": True,
    "NotifyOnComplete": True,
    # Window state is local to this machine. It is deliberately excluded from
    # settings bundles below: a geometry valid on one monitor layout should
    # never strand the window off-screen on another machine.
    "WindowGeometry": "",
    "WindowMaximized": False,
    "LastPage": "Download",
    # New installs confirm the destination once from the Download page. The
    # launcher flips this to false only when it creates the first config, so
    # older installs that predate the marker are not shown onboarding again.
    "FirstRunComplete": True,
    # Privacy-sensitive clipboard monitoring is opt-in. Matching links are
    # staged in the GUI and never enqueued without an explicit user action.
    "ClipboardLinkGrabber": False,
    "LastYtDlpUpdateCheck": "",
    "LastYtDlpUpdateAttempt": "",
    "LastYtDlpUpdateFailure": "",
    "ExtraOutputRoots": [],
    "LastFfmpegCheck": "",
    "MaxFileSizeMB": 0,
    # yt-dlp output template (filename + optional subdirs), relative to the
    # download root. Empty = the built-in default. Validated against a field
    # allowlist so a template can never drive the output path with arbitrary
    # fields/traversal (CVE-2024-38519 posture).
    "OutputTemplate": "",
    "WindowsFilenames": True,
    "NativeChromeExtensionIds": os.environ.get("ASTRA_NATIVE_CHROME_EXTENSION_IDS", ""),
    "NativeFirefoxExtensionIds": os.environ.get(
        "ASTRA_NATIVE_FIREFOX_EXTENSION_IDS",
        "ytkit@sysadmindoc.github.io",
    ),
}


def clean_text(value, default="", max_len=_MAX_TEXT_FIELD):
    if value is None:
        return default
    cleaned = _CONTROL_CHARS_RE.sub("", str(value)).strip()
    return cleaned[:max_len].rstrip() if len(cleaned) > max_len else cleaned


def clean_path_text(value):
    return clean_text(value, "", _MAX_PATH_FIELD)


def _normalize_long_text(value, default="", max_len=_MAX_TEXT_FIELD):
    if value is None:
        return default, False
    cleaned = _CONTROL_CHARS_RE.sub("", str(value)).strip()
    return (cleaned, True) if len(cleaned) > max_len else (cleaned, False)


def coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_rate_limit(value):
    cleaned = clean_text(value, "", 32).upper()
    return cleaned if re.fullmatch(r"\d+[KMG]?", cleaned) else ""


def normalize_playlist_date(value):
    """Accept an absolute YYYYMMDD or a yt-dlp relative date, else nothing.

    This lands in a subprocess argument, so the grammar is allow-listed
    rather than sanitised: an unparseable value would make yt-dlp reject the
    whole download instead of the one setting the user got wrong.
    """
    cleaned = clean_text(value, "", 32).lower().replace(" ", "")
    if re.fullmatch(r"\d{8}", cleaned):
        return cleaned
    if re.fullmatch(
        r"(now|today)[-+]\d{1,4}(microsecond|second|minute|hour|day|week|month|year)s?",
        cleaned,
    ):
        return cleaned
    return ""


def normalize_impersonate_target(value):
    """Accept a `Client-Version` target shape, else nothing.

    Shape only — this module never runs yt-dlp, so it cannot know which
    targets the installed binary actually has. The argv builder gates on the
    probed list, because yt-dlp aborts the whole download with an unhandled
    exception when given a target it does not support.
    """
    cleaned = clean_text(value, "", 40)
    return cleaned if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*-[0-9][A-Za-z0-9.]*", cleaned) else ""


def normalize_proxy(value):
    cleaned = clean_text(value, "", 512)
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return ""
    schemes = {"http", "https", "socks", "socks4", "socks4a", "socks5", "socks5h"}
    return cleaned if parsed.scheme.lower() in schemes and parsed.netloc else ""


def normalize_force_ip_version(value):
    cleaned = clean_text(value, "", 8).lower()
    return cleaned if cleaned in {"", "ipv4", "ipv6"} else ""


def normalize_source_address(value):
    """Accept one literal local address for yt-dlp's source bind option."""
    cleaned = clean_text(value, "", 64)
    if not cleaned:
        return ""
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return ""


def normalize_xff(value):
    """Accept yt-dlp's safe X-Forwarded-For geo selector vocabulary."""
    cleaned = clean_text(value, "", 64)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in {"default", "never"}:
        return lowered
    if re.fullmatch(r"[a-zA-Z]{2}", cleaned):
        return cleaned.upper()
    try:
        return str(ipaddress.ip_network(cleaned, strict=False))
    except ValueError:
        return ""


SITE_PROFILE_OVERRIDE_KEYS = (
    "ImpersonateTarget", "Proxy", "RateLimit", "ThrottledRate",
    "ForceIPVersion", "SourceAddress", "Xff", "GeoVerificationProxy",
    "SocketTimeoutSeconds", "ExtractorRetries", "SleepIntervalSeconds",
    "MaxSleepIntervalSeconds", "PacingJitterPercent", "SleepRequestsSeconds",
)
_SITE_PROFILE_MAX = 32
_SITE_PROFILE_NAME_MAX = 80
_SITE_PROFILE_DOMAIN_MAX = 253
_SITE_PROFILE_DOWNLOAD_TYPES = frozenset({"", "video", "audio", "subtitles"})
_SITE_PROFILE_VIDEO_FORMATS = frozenset({"", "mp4", "mkv", "webm"})
_SITE_PROFILE_AUDIO_FORMATS = frozenset({"", "mp3", "m4a", "opus", "flac", "wav"})
_SITE_PROFILE_QUALITY = frozenset({"", "best", "2160", "1440", "1080", "720", "480"})


def normalize_site_profile_domain(value):
    """Return a safe hostname root for a named site profile.

    Profiles only select settings for a URL that is already accepted by the
    public-media policy. Keeping the field to a hostname root prevents a
    profile from smuggling a path or credentials into matching logic and
    makes subdomain matching deterministic.
    """
    raw = clean_text(value, "", _SITE_PROFILE_DOMAIN_MAX)
    if not raw:
        return ""
    try:
        if "://" in raw:
            parsed = urlparse(raw)
            if parsed.scheme.lower() not in {"http", "https"}:
                return ""
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return ""
            if parsed.path not in {"", "/"}:
                return ""
            host = parsed.hostname or ""
        else:
            if any(character in raw for character in "/?#@"):
                return ""
            host = raw
        host = host.strip().strip(".").lower()
    except (TypeError, ValueError):
        return ""
    if host.startswith("www."):
        host = host[4:]
    if not host or len(host) > _SITE_PROFILE_DOMAIN_MAX:
        return ""
    labels = host.split(".")
    if len(labels) < 2 or any(
        not label or len(label) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in labels
    ):
        return ""
    if len(labels[-1]) < 2:
        return ""
    return host


def _site_profile_value(item, key, default=None):
    wanted = key.casefold()
    for candidate, value in item.items():
        if str(candidate).casefold() == wanted:
            return value
    return default


def _site_profile_choice(item, key, allowed, index):
    raw = _site_profile_value(item, key, "")
    cleaned = clean_text(raw, "", 32).lower()
    if cleaned not in allowed and cleaned:
        return None, f"Site profile {index} has an invalid {key}."
    return cleaned, None


def _site_profile_int(item, key, maximum, index):
    raw = _site_profile_value(item, key, 0)
    if raw in (None, ""):
        return 0, None
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None, f"Site profile {index} has an invalid {key}."
    return max(0, min(maximum, parsed)), None


def validate_site_profiles(value):
    """Validate and normalize the editable named-profile document.

    The GUI uses the error text to keep malformed JSON or a bad profile from
    being silently discarded. The config loader calls ``normalize_site_profiles``
    below, which fails closed for hand-edited or legacy state files.
    """
    if value in (None, ""):
        raw_profiles = []
    elif isinstance(value, str):
        text = value.strip()
        if len(text.encode("utf-8", errors="replace")) > 64 * 1024:
            return None, "Site profiles are too large. Keep them under 64 KB."
        try:
            raw_profiles = json.loads(text) if text else []
        except (TypeError, ValueError):
            return None, "Site profiles must be valid JSON."
    else:
        raw_profiles = value
    if not isinstance(raw_profiles, list):
        return None, "Site profiles must be a JSON array."
    if len(raw_profiles) > _SITE_PROFILE_MAX:
        return None, f"Use at most {_SITE_PROFILE_MAX} site profiles."

    profiles = []
    names = set()
    for index, item in enumerate(raw_profiles, 1):
        if not isinstance(item, dict):
            return None, f"Site profile {index} must be a JSON object."
        name = clean_text(_site_profile_value(item, "Name"), "", _SITE_PROFILE_NAME_MAX)
        domain = normalize_site_profile_domain(_site_profile_value(item, "Domain"))
        if not name:
            return None, f"Site profile {index} needs a name."
        if not domain:
            return None, f"Site profile {index} needs a valid domain such as youtube.com."
        if name.casefold() in names:
            return None, f"Site profile names must be unique: {name}."
        names.add(name.casefold())
        entry = {"Name": name, "Domain": domain}

        for key, allowed in (
            ("DownloadType", _SITE_PROFILE_DOWNLOAD_TYPES),
            ("VideoFormat", _SITE_PROFILE_VIDEO_FORMATS),
            ("AudioFormat", _SITE_PROFILE_AUDIO_FORMATS),
            ("Quality", _SITE_PROFILE_QUALITY),
        ):
            normalized, error = _site_profile_choice(item, key, allowed, index)
            if error:
                return None, error
            if normalized:
                entry[key] = normalized

        for key, normalizer in (
            ("ImpersonateTarget", normalize_impersonate_target),
            ("Proxy", normalize_proxy),
            ("RateLimit", normalize_rate_limit),
            ("ThrottledRate", normalize_rate_limit),
            ("ForceIPVersion", normalize_force_ip_version),
            ("SourceAddress", normalize_source_address),
            ("Xff", normalize_xff),
            ("GeoVerificationProxy", normalize_proxy),
        ):
            raw = _site_profile_value(item, key, "")
            normalized = normalizer(raw)
            if clean_text(raw, "", 512) and not normalized:
                return None, f"Site profile {index} has an invalid {key}."
            if normalized:
                entry[key] = normalized

        for key, maximum in (
            ("SocketTimeoutSeconds", 300),
            ("ExtractorRetries", 20),
            ("SleepIntervalSeconds", 600),
            ("MaxSleepIntervalSeconds", 600),
            ("PacingJitterPercent", 100),
            ("SleepRequestsSeconds", 60),
        ):
            normalized, error = _site_profile_int(item, key, maximum, index)
            if error:
                return None, error
            if normalized:
                entry[key] = normalized
        if (
            entry.get("MaxSleepIntervalSeconds", 0)
            and entry.get("MaxSleepIntervalSeconds", 0)
            < entry.get("SleepIntervalSeconds", 0)
        ):
            entry["MaxSleepIntervalSeconds"] = entry["SleepIntervalSeconds"]
        profiles.append(entry)
    return profiles, None


def normalize_site_profiles(value):
    """Fail closed when loading named profiles from local or imported state."""
    profiles, _error = validate_site_profiles(value)
    return profiles if profiles is not None else []


def normalize_sublangs(value):
    cleaned = clean_text(value, "en", 80)
    cleaned = re.sub(r"[^a-zA-Z0-9,\-]", "", cleaned)
    return cleaned or "en"


# Which subtitle tracks to ask for.
#
# Measured against the installed yt-dlp on 2026-08-06 with a fixture carrying
# a manual EN track, an auto EN track and an auto ES track: passing
# --write-subs and --write-auto-subs together does NOT fetch both English
# tracks. yt-dlp merges them per language and the manual one wins, so "both"
# already means prefer-manual-else-auto. What was missing is the ability to
# ask for one kind only — a viewer who wants nothing but human-written
# captions, or one who specifically wants the machine transcript.
SUBTITLE_MODES = ("prefer-manual", "manual", "auto")

# --convert-subs targets. Empty leaves the site's own format alone.
SUBTITLE_FORMATS = ("", "srt", "vtt", "ass", "lrc")


def normalize_subtitle_mode(value):
    cleaned = clean_text(value, "", 20).lower()
    return cleaned if cleaned in SUBTITLE_MODES else "prefer-manual"


def normalize_subtitle_format(value):
    cleaned = clean_text(value, "", 8).lower()
    return cleaned if cleaned in SUBTITLE_FORMATS else ""


# yt-dlp's SponsorBlock category names. An unknown name is dropped rather than
# passed through: these reach a subprocess argument.
SPONSORBLOCK_CATEGORIES = (
    "sponsor", "intro", "outro", "selfpromo", "preview", "filler",
    "interaction", "music_offtopic", "poi_highlight", "chapter",
)


def normalize_sponsorblock_categories(value):
    """Return a comma-joined subset of the known SponsorBlock categories.

    An empty result means "all", which is what the app used to send
    unconditionally — enabling SponsorBlock to skip sponsors also removed
    intros, outros and self-promo with no way to say otherwise.
    """
    if isinstance(value, (list, tuple, set)):
        raw = ",".join(str(item) for item in value)
    else:
        raw = clean_text(value, "", 240)
    if raw.strip().lower() == "all":
        return ""
    known = []
    for name in raw.split(","):
        name = re.sub(r"[^a-z_]", "", name.strip().lower())
        if name in SPONSORBLOCK_CATEGORIES and name not in known:
            known.append(name)
    return ",".join(known)


_SAFE_OUTPUT_FIELDS = frozenset({
    "title", "id", "ext", "uploader", "uploader_id", "channel", "channel_id",
    "upload_date", "release_date", "playlist_title", "playlist", "playlist_index",
    "resolution", "height", "width", "fps", "format_id", "autonumber", "epoch",
    "duration_string", "season_number", "episode_number", "view_count", "like_count",
})
_OUTPUT_FIELD_RE = re.compile(r"%\((\w+)")
# Free-text fields whose expansion is attacker/uploader controlled in length.
# Everything else in the allowlist expands to a short id, number, or date.
_LONG_TEXT_OUTPUT_FIELDS = frozenset({
    "title", "uploader", "uploader_id", "channel", "channel_id",
    "playlist_title", "playlist",
})
_OUTPUT_TOKEN_RE = re.compile(r"%\((\w+)\)(0?\d+)?(?:\.(\d+))?([sdBjlqDSU])")
# Total bytes the free-text parts of a rendered template may consume. Windows
# MAX_PATH is 260, so a template must leave room for the download root, the
# separators, and the extension.
_OUTPUT_TEXT_BUDGET = 200
_OUTPUT_TEXT_FLOOR = 40


def bound_output_template_fields(template):
    """Cap every free-text expansion in an already-validated template.

    The built-in templates bound their fields (`%(title).200B`); a custom
    `%(uploader)s/%(title)s.%(ext)s` did not, so a 200+ character title under a
    deep DownloadPath rendered past MAX_PATH and failed with an opaque file
    error. Unbounded text fields gain a byte bound and over-generous explicit
    bounds are clamped, with the budget split across the fields the template
    actually uses. Idempotent: re-normalizing a saved template is a no-op.
    """
    # `%%` is a literal percent, so `%%(title)s` is literal text and must not
    # be rewritten. Split it out and rewrite only real expansion segments.
    segments = template.split("%%")
    tokens = [
        match
        for segment in segments
        for match in _OUTPUT_TOKEN_RE.finditer(segment)
        if match.group(1) in _LONG_TEXT_OUTPUT_FIELDS
    ]
    if not tokens:
        return template
    budget = max(_OUTPUT_TEXT_FLOOR, _OUTPUT_TEXT_BUDGET // len(tokens))

    def rewrite(match):
        field, pad, precision, conversion = match.groups()
        if field not in _LONG_TEXT_OUTPUT_FIELDS or conversion not in ("s", "B"):
            return match.group(0)
        limit = min(int(precision), budget) if precision else budget
        # An unbounded `%(field)s` becomes the byte-bounded form the built-in
        # templates use; an explicit `.Ns` keeps character semantics.
        conversion = "B" if precision is None else conversion
        return f"%({field}){pad or ''}.{limit}{conversion}"

    return "%%".join(_OUTPUT_TOKEN_RE.sub(rewrite, segment) for segment in segments)


def normalize_output_template(value):
    """Return a safe yt-dlp output template (relative to the download root) or
    "" when empty/invalid. Rejects absolute paths, `..` traversal, unsafe
    characters, and any field outside the allowlist; requires `%(ext)s` so the
    extension is always preserved. This keeps a user-supplied template from
    driving the output path with arbitrary fields (CVE-2024-38519 posture)."""
    tpl = clean_text(value, "", 300).strip()
    if not tpl:
        return ""
    norm = tpl.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9 %()._\-/\[\]]+", norm):
        return ""
    if "%(ext)s" not in norm:
        return ""
    fields = _OUTPUT_FIELD_RE.findall(norm)
    if not fields or any(f not in _SAFE_OUTPUT_FIELDS for f in fields):
        return ""
    # Printf-syntax check: after removing literal %% and every well-formed
    # %(field)[pad][.prec]conv token, no stray % may remain. Without this an
    # unclosed "%(title" or a lone "50%" passed the charset/field checks and
    # then failed EVERY download at yt-dlp startup with an opaque
    # "Invalid output template" error.
    stripped = re.sub(r"%\(\w+\)(?:0?\d+)?(?:\.\d+)?[sdBjlqDSU]", "", norm.replace("%%", ""))
    if "%" in stripped:
        return ""
    return bound_output_template_fields(norm)


WINDOWS_MAX_PATH = 260
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})
_OUTPUT_TEMPLATE_PREVIEW_DEFAULT = "%(title).200B.%(ext)s"
_OUTPUT_TEMPLATE_PREVIEW_VALUES = {
    "title": "Example video",
    "id": "abc123",
    "ext": "mp4",
    "uploader": "Astra channel",
    "uploader_id": "astra",
    "channel": "Astra channel",
    "channel_id": "astra",
    "upload_date": "20260809",
    "release_date": "20260809",
    "playlist_title": "Example playlist",
    "playlist": "Example playlist",
    "playlist_index": "1",
    "resolution": "1920x1080",
    "height": "1080",
    "width": "1920",
    "fps": "30",
    "format_id": "137",
    "autonumber": "1",
    "epoch": "1786300000",
    "duration_string": "12:34",
    "season_number": "1",
    "episode_number": "1",
    "view_count": "1234",
    "like_count": "123",
}


def _render_output_template_preview(template):
    def replace(match):
        field, _pad, precision, _conversion = match.groups()
        value = str(_OUTPUT_TEMPLATE_PREVIEW_VALUES.get(field, field))
        if precision:
            value = value[:int(precision)]
        return value

    # A doubled percent is a literal percent in a yt-dlp template.
    return _OUTPUT_TOKEN_RE.sub(replace, template.replace("%%", "%"))


def _windows_reserved_output_component(component):
    stem = str(component or "").rstrip(" .").split(".", 1)[0].upper()
    return stem if stem in _WINDOWS_RESERVED_NAMES else ""


def output_template_preview(template, output_dir="", *, max_path=WINDOWS_MAX_PATH):
    """Render a safe example and report Windows path hazards before saving."""
    raw = clean_text(template, "", 300)
    if raw:
        normalized = normalize_output_template(raw)
        if not normalized:
            return {
                "valid": False, "normalized": "", "relative": "", "path": "",
                "length": 0, "max_path": int(max_path),
                "reserved": (), "too_long": False,
            }
    else:
        normalized = _OUTPUT_TEMPLATE_PREVIEW_DEFAULT
    relative = _render_output_template_preview(normalized).replace("/", "\\")
    root = clean_path_text(output_dir) or "C:\\Videos"
    path = root.rstrip("\\/") + "\\" + relative
    reserved = []
    for component in relative.split("\\"):
        name = _windows_reserved_output_component(component)
        if name and name not in reserved:
            reserved.append(name)
    length = len(path)
    return {
        "valid": True,
        "normalized": normalized,
        "relative": relative,
        "path": path,
        "length": length,
        "max_path": int(max_path),
        "reserved": tuple(reserved),
        "too_long": length > int(max_path),
    }


def normalize_url(value):
    url, too_long = _normalize_long_text(value, "", 4096)
    if too_long:
        return None, "URL is too long to download safely."
    if not url or any(character.isspace() for character in url):
        return None, "Enter a valid http or https URL."
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, "Enter a valid http or https URL."
    return url, None


# ── Media source policy ───────────────────────────────────────────────────
# Astra Downloader accepts any public http(s) media URL yt-dlp can extract
# (YouTube, Reddit, X/Twitter, TikTok, Vimeo, Twitch clips, …). Until v1.8.0
# the HTTP boundary enforced a YouTube-only host allowlist; that allowlist was
# never about YouTube, it was the SSRF control — yt-dlp fetches, follows, and
# retries whatever URL it is handed, so a caller holding the loopback token
# could otherwise aim it (and any attached cookie jar) at LAN services or the
# cloud-metadata endpoint. Widening the capability therefore replaces the
# allowlist with an explicit private-network denylist rather than removing the
# check. Cookie jars, PO tokens, and the JS-runtime gate stay YouTube-scoped.
MEDIA_URL_BLOCK_MESSAGES = {
    "invalid-url": "Enter a valid http or https URL.",
    "credentials-in-url": (
        "URLs that embed a username or password are not accepted. "
        "Paste the plain video link instead."
    ),
    "private-host": (
        "That address is on a private, loopback, or link-local network. "
        "Astra Downloader only downloads from public sites."
    ),
    "non-public-host": (
        "That host is not a public internet address. "
        "Paste a normal video link such as https://www.reddit.com/r/…"
    ),
}
# Hostname forms that never belong to a public media site. `.internal` also
# covers metadata.google.internal; 169.254.169.254 is caught as link-local.
_BLOCKED_MEDIA_HOSTS = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
})
_BLOCKED_MEDIA_HOST_SUFFIXES = (
    ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home.arpa",
)
# Hosts a paste-anything clipboard grabber should stage without being asked
# twice. Purely a UX hint — it never gates a download.
MEDIA_HOST_HINTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com", "reddit.com", "redd.it",
    "twitter.com", "x.com", "t.co", "tiktok.com", "vimeo.com", "twitch.tv",
    "dailymotion.com", "dai.ly", "streamable.com", "bilibili.com",
    "soundcloud.com", "facebook.com", "fb.watch", "instagram.com",
    "bsky.app", "rumble.com", "odysee.com", "kick.com", "nicovideo.jp",
    "vk.com", "ok.ru", "pscp.tv", "periscope.tv", "imgur.com", "gfycat.com",
    "9gag.com", "newgrounds.com", "archive.org", "ted.com", "coub.com",
    "bitchute.com", "peertube.tv", "loom.com", "vidyard.com", "wistia.com",
)
_MEDIA_PATH_HINTS = (
    "/watch", "/video", "/videos", "/v/", "/embed/", "/clip", "/clips/",
    "/shorts/", "/reel", "/status/", "/comments/", "/playlist", "/episode",
    "/media/", "/stream", "/live/",
)
_MEDIA_EXTENSION_HINTS = (
    ".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi", ".flv", ".m3u8", ".mpd",
    ".ts", ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac",
)


def _media_url_host(url):
    """Return the bare lowercase host of a URL (no port, no brackets, no dot)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None, None
    host = parsed.hostname  # already strips userinfo, port, and [] on IPv6
    if not host:
        return None, parsed
    return host.strip().rstrip(".").lower(), parsed


def _ip_is_public(address):
    """Reject every non-globally-routable literal, including IPv4-mapped v6."""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    sixtofour = getattr(address, "sixtofour", None)
    if sixtofour is not None:
        address = sixtofour
    return not (
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_multicast or address.is_reserved or address.is_unspecified
    )


def media_url_block_reason(url):
    """Return why a URL must not be handed to yt-dlp, or None when it is fine.

    Deliberately literal-only: no DNS resolution happens here, because a name
    that resolves privately at validation time can resolve publicly a
    millisecond later (and vice versa). The residual — a public DNS name
    pointed at a private address — is documented in HARDENING.md.
    """
    normalized, error = normalize_url(url)
    if error or not normalized:
        return "invalid-url"
    host, parsed = _media_url_host(normalized)
    if not host:
        return "invalid-url"
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        return "credentials-in-url"
    try:
        return None if _ip_is_public(ipaddress.ip_address(host)) else "private-host"
    except ValueError:
        # reason: not an IP literal — the hostname rules below decide
        pass
    if host in _BLOCKED_MEDIA_HOSTS or host.endswith(_BLOCKED_MEDIA_HOST_SUFFIXES):
        return "private-host"
    labels = host.split(".")
    if len(labels) < 2 or not all(labels):
        # Single-label names are intranet hosts ("nas", "router", "localhost").
        return "private-host"
    tld = labels[-1]
    # A public suffix is alphabetic (or punycode). Requiring that rejects the
    # obfuscated loopback literals urlparse does not recognise as IPs —
    # "127.1", "0x7f.0.0.1", "2130706433" — without touching real domains,
    # including internationalized ones.
    if not (tld.isalpha() or (tld.startswith("xn--") and len(tld) > 4)):
        return "non-public-host"
    return None


def is_supported_media_url(url):
    """True when yt-dlp may be pointed at this URL."""
    return media_url_block_reason(url) is None


def describe_media_url_block(reason):
    """Map a block reason onto user-facing copy."""
    return MEDIA_URL_BLOCK_MESSAGES.get(
        reason, MEDIA_URL_BLOCK_MESSAGES["invalid-url"]
    )


def looks_like_media_link(url):
    """UX-only heuristic for the clipboard grabber: does this copied link look
    like something worth staging? Never used to allow or deny a download —
    `is_supported_media_url` owns that decision."""
    if not is_supported_media_url(url):
        return False
    host, parsed = _media_url_host(url)
    if not host:
        return False
    if any(host == hint or host.endswith("." + hint) for hint in MEDIA_HOST_HINTS):
        return True
    path = (parsed.path or "").lower()
    if any(marker in path for marker in _MEDIA_PATH_HINTS):
        return True
    return path.endswith(_MEDIA_EXTENSION_HINTS)


def _parse_section_timestamp(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        parts = raw.split(":")
        if len(parts) > 3:
            return None
        try:
            values = [float(part) for part in parts]
        except (TypeError, ValueError, OverflowError):
            return None
        if any(part < 0 for part in values):
            return None
        if len(values) > 1 and any(part >= 60 for part in values[1:]):
            return None
        seconds = sum(
            part * (60 ** (len(values) - index - 1))
            for index, part in enumerate(values)
        )
    else:
        return None
    if not math.isfinite(seconds) or seconds < 0 or seconds > 86400:
        return None
    return round(seconds, 3)


def normalize_download_section(value):
    """Normalize an accurate re-cut range expressed as seconds or HH:MM:SS."""
    if value in (None, ""):
        return None, None
    if not isinstance(value, dict):
        return None, "Section must contain start and end timestamps."
    unknown = sorted(str(key) for key in value if str(key) not in {"start", "end"})
    if unknown:
        return None, "Unsupported section field(s): {}.".format(", ".join(unknown))
    start = _parse_section_timestamp(value.get("start"))
    end = _parse_section_timestamp(value.get("end"))
    if start is None or end is None:
        return None, "Section start and end must be timestamps between 0:00 and 24:00:00."
    if end <= start:
        return None, "Section end must be later than its start."
    if end - start < 0.1:
        return None, "Section must be at least 0.1 seconds long."
    return {"start": start, "end": end}, None


def normalize_playlist_items(value):
    """Return a bounded, deduplicated list of positive yt-dlp playlist indexes."""
    if value in (None, ""):
        return None, None
    if not isinstance(value, (list, tuple)):
        return None, "Playlist items must be an array of item numbers."
    if not value:
        return None, "Select at least one playlist item."
    if len(value) > 200:
        return None, "Select no more than 200 playlist items at once."
    items = []
    seen = set()
    for raw in value:
        if isinstance(raw, bool):
            return None, "Playlist item numbers must be positive integers."
        if isinstance(raw, int):
            item = raw
        elif isinstance(raw, str) and re.fullmatch(r"\d+", raw.strip()):
            item = int(raw.strip())
        else:
            return None, "Playlist item numbers must be positive integers."
        if item < 1 or item > 100000:
            return None, "Playlist item numbers must be between 1 and 100000."
        if item not in seen:
            items.append(item)
            seen.add(item)
    if not items:
        return None, "Select at least one playlist item."
    return sorted(items), None


def validate_download_request_body(body):
    """Reject unreviewed client fields before any queue or process side effect."""
    if not isinstance(body, dict) or not body.get("url"):
        return None, "Missing download URL.", None
    keys = {str(key) for key in body}
    forbidden = sorted(keys & DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS)
    if forbidden:
        return (
            None,
            "Client-supplied yt-dlp flags are not allowed. The companion builds yt-dlp arguments server-side.",
            "unsupported-ytdlp-flags",
        )
    unknown = sorted(keys - DOWNLOAD_REQUEST_ALLOWED_FIELDS)
    if unknown:
        return (
            None,
            "Unsupported /download field(s): {}.".format(", ".join(unknown)),
            "unsupported-download-fields",
        )
    if "format" in body and not isinstance(body["format"], str):
        return None, "Download format must be a string.", "invalid-download-format"
    if "quality" in body and not isinstance(body["quality"], str):
        return None, "Download quality must be a string.", "invalid-download-quality"
    if "videoPassword" in body:
        video_password = body["videoPassword"]
        if not isinstance(video_password, str):
            return None, "Video password must be a string.", "invalid-video-password"
        try:
            password_bytes = len(video_password.encode("utf-8"))
        except UnicodeError:
            password_bytes = _MAX_VIDEO_PASSWORD_BYTES + 1
        if "\x00" in video_password or (
            video_password and password_bytes > _MAX_VIDEO_PASSWORD_BYTES
        ):
            return (
                None,
                "Video password must be between 1 and 4096 UTF-8 bytes.",
                "invalid-video-password",
            )
    if "section" in body:
        section, section_error = normalize_download_section(body.get("section"))
        if section_error:
            return None, section_error, "invalid-download-section"
        body = dict(body)
        body["section"] = section
    if "playlistItems" in body:
        playlist_items, items_error = normalize_playlist_items(body.get("playlistItems"))
        if items_error:
            return None, items_error, "invalid-playlist-items"
        body = dict(body)
        body["playlistItems"] = playlist_items
    return body, None, None


def allowed_output_roots(config):
    """Return unique, resolved directories that downloads may target."""
    raw_roots = []
    for key in ("DownloadPath", "AudioDownloadPath"):
        value = config.get(key, "") if config else ""
        if value:
            raw_roots.append(value)
    extra = (config.get("ExtraOutputRoots", []) if config else []) or []
    if isinstance(extra, list):
        raw_roots.extend(str(value) for value in extra if isinstance(value, str) and value)

    resolved = []
    seen = set()
    for raw in raw_roots:
        try:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                continue
            candidate = path.resolve()
        except (OSError, RuntimeError):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    return resolved


def normalize_output_dir(value, default_dir=None, allowed_roots=None):
    """Validate, confine, create, and return an absolute output directory."""
    raw, too_long = _normalize_long_text(value, "", _MAX_PATH_FIELD)
    if too_long:
        return None, "Output folder path is too long."
    if not raw:
        raw, too_long = _normalize_long_text(default_dir, "", _MAX_PATH_FIELD)
        if too_long:
            return None, "Default output folder path is too long."
    if not raw:
        raw = default_download_path()
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            return None, "Choose an absolute output folder."
        if allowed_roots:
            try:
                resolved = path.resolve()
            except (OSError, RuntimeError):
                return None, "Output folder path could not be resolved."
            if not any(_is_path_under(resolved, root) for root in allowed_roots):
                return None, "Output folder is outside the configured download locations."
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            return None, "Output path is not a folder."
        return str(path), None
    except (OSError, RuntimeError) as error:
        return None, f"Cannot use output folder: {error}"


def _is_path_under(child, root):
    try:
        child.resolve().relative_to(root)
        return True
    except (ValueError, OSError, RuntimeError):
        return False


# ---------------------------------------------------------------------------
# Settings bundle: moving an install to another machine, and getting a
# corrupted config back without hand-editing JSON.

SETTINGS_BUNDLE_SCHEMA = "astra-downloader-settings"
SETTINGS_BUNDLE_VERSION = 1

# Settings deliberately left out of an exported bundle.
#
# ServerToken is the shared secret the browser extension authenticates with.
# Carrying it into a bundle would put a working credential in a file users
# email to themselves, and copying one machine's token to another lets either
# drive the other's queue. The importing install keeps its own.
#
# The legacy health-token settings are read from environment variables at
# startup, so exporting them would write a value the target machine is about
# to overwrite anyway — an import that appears to do nothing is worse than
# one that does not claim to.
BUNDLE_EXCLUDED_SETTINGS = frozenset({
    "ServerToken",
    "LegacyHealthTokenEcho",
    "LegacyHealthTokenOrigins",
    "NativeChromeExtensionIds",
    "NativeFirefoxExtensionIds",
    "WindowGeometry",
    "WindowMaximized",
    "LastPage",
    "FirstRunComplete",
})

# Subscription fields that describe one machine's scan history rather than
# the subscription itself. A bundle carries what to watch and how often, not
# when this particular install last looked.
_BUNDLE_SUBSCRIPTION_FIELDS = (
    "id", "url", "title", "intervalMinutes", "enabled",
)


def build_settings_bundle(config, subscriptions=(), site_logins=(), *,
                          app_version="", now=None):
    """Build the portable bundle: settings, subscriptions, sign-in names.

    Sign-ins are named but never carried. `SiteLoginStore` states that cookie
    values never leave the jar files, and a bundle is precisely the kind of
    file that gets emailed around, so the export records which sites had a
    sign-in and leaves the user to add them again on the other machine. That
    is also why there is no opt-in to include them: an option to break that
    rule is still a way to break it.
    """
    read = getattr(config, "get", None)
    settings = {}
    if callable(read):
        for key in sorted(DEFAULT_CONFIG):
            if key in BUNDLE_EXCLUDED_SETTINGS:
                continue
            settings[key] = read(key, DEFAULT_CONFIG[key])
    exported_subscriptions = []
    for record in subscriptions or ():
        if not isinstance(record, dict):
            continue
        exported_subscriptions.append(
            {field: record.get(field) for field in _BUNDLE_SUBSCRIPTION_FIELDS
             if field in record}
        )
    names = []
    for entry in site_logins or ():
        site = entry.get("site") if isinstance(entry, dict) else entry
        site = clean_text(site, "", 253)
        if site and site not in names:
            names.append(site)
    return {
        "schema": SETTINGS_BUNDLE_SCHEMA,
        "schemaVersion": SETTINGS_BUNDLE_VERSION,
        "appVersion": str(app_version or ""),
        "exportedAt": float(now if now is not None else 0.0),
        "settings": settings,
        "subscriptions": exported_subscriptions,
        "excludedSettings": sorted(BUNDLE_EXCLUDED_SETTINGS),
        # Names only — see the docstring.
        "siteLoginSites": names,
    }


def read_settings_bundle(payload):
    """Validate a bundle. Returns (bundle, error); never both.

    Fails closed on anything that is not recognisably one of ours: an import
    overwrites every setting, so guessing at a malformed file is how a user
    ends up with a config they cannot explain.
    """
    if not isinstance(payload, dict):
        return None, "That file is not an Astra Downloader settings bundle."
    if payload.get("schema") != SETTINGS_BUNDLE_SCHEMA:
        return None, "That file is not an Astra Downloader settings bundle."
    try:
        version = int(payload.get("schemaVersion"))
    except (TypeError, ValueError):
        return None, "That bundle does not declare a version."
    if version > SETTINGS_BUNDLE_VERSION:
        return None, (
            f"That bundle was written by a newer version (format {version}; "
            f"this build reads {SETTINGS_BUNDLE_VERSION}). Update Astra "
            "Downloader and try again."
        )
    raw_settings = payload.get("settings")
    if not isinstance(raw_settings, dict):
        return None, "That bundle has no settings in it."
    # Everything goes through the same normaliser the live config uses, so a
    # hand-edited bundle cannot introduce a value the app would not accept
    # from its own config file.
    merged = {key: value for key, value in raw_settings.items()
              if key in DEFAULT_CONFIG and key not in BUNDLE_EXCLUDED_SETTINGS}
    settings = sanitize_config(merged)
    for key in BUNDLE_EXCLUDED_SETTINGS:
        settings.pop(key, None)
    subscriptions = []
    for record in (payload.get("subscriptions") or []):
        if not isinstance(record, dict):
            continue
        url, url_error = normalize_url(record.get("url"))
        if url_error or not url:
            continue
        subscriptions.append({
            "url": url,
            "title": clean_text(record.get("title"), "", 300),
            "intervalMinutes": clamp_int(record.get("intervalMinutes"), 60, 1, 40320),
            "enabled": coerce_bool(record.get("enabled"), True),
        })
    sites = []
    for site in (payload.get("siteLoginSites") or []):
        site = clean_text(site, "", 253)
        if site and site not in sites:
            sites.append(site)
    return {
        "schemaVersion": version,
        "appVersion": clean_text(payload.get("appVersion"), "", 40),
        "settings": settings,
        "subscriptions": subscriptions,
        "excludedSettings": sorted(BUNDLE_EXCLUDED_SETTINGS),
        "siteLoginSites": sites,
    }, None


def describe_bundle_changes(current, bundle):
    """Say what importing this bundle would actually change.

    An import that reports "done" tells the user nothing about whether it did
    what they wanted; this is what the confirmation says instead.
    """
    read = getattr(current, "get", None)
    changed = []
    if callable(read):
        for key in sorted(bundle.get("settings") or {}):
            incoming = bundle["settings"][key]
            if read(key, DEFAULT_CONFIG.get(key)) != incoming:
                changed.append(key)
    return {
        "settings": changed,
        "subscriptions": len(bundle.get("subscriptions") or []),
        "excludedSettings": list(
            bundle.get("excludedSettings") or sorted(BUNDLE_EXCLUDED_SETTINGS)
        ),
        "siteLoginSites": list(bundle.get("siteLoginSites") or []),
    }


def sanitize_config(raw):
    """Return the bounded, schema-known companion configuration."""
    source = raw if isinstance(raw, dict) else {}
    data = {
        key: source.get(key, value)
        for key, value in DEFAULT_CONFIG.items()
    }
    data["DownloadPath"] = clean_path_text(data.get("DownloadPath")) or DEFAULT_CONFIG["DownloadPath"]
    data["AudioDownloadPath"] = clean_path_text(data.get("AudioDownloadPath"))
    data["ServerPort"] = clamp_int(data.get("ServerPort"), SERVER_PORT, 1024, 65535)
    token = clean_text(data.get("ServerToken"), "", 128)
    data["ServerToken"] = token if re.fullmatch(r"[A-Za-z0-9_\-]{16,128}", token) else uuid.uuid4().hex
    for key in (
        "EmbedMetadata", "EmbedThumbnail", "EmbedChapters", "EmbedSubs",
        "GenerateSubtitles",
        "WriteInfoJson", "WriteDescription", "WriteThumbnail",
        "SplitChapters", "LiveFromStart",
        "WindowsFilenames",
        "KeepIntermediateFiles", "VerifyFormats",
        "SponsorBlock", "AutoUpdateYtDlp", "StartMinimized", "CloseToTray",
        "NotifyOnComplete", "ClipboardLinkGrabber", "WindowMaximized",
        "FirstRunComplete", "LegacyHealthTokenEcho",
    ):
        data[key] = coerce_bool(data.get(key), DEFAULT_CONFIG[key])
    data["WindowGeometry"] = clean_text(data.get("WindowGeometry"), "", 8192)
    page = clean_text(data.get("LastPage"), "Download", 80)
    data["LastPage"] = page if page in {
        "Download", "History", "Sign-ins", "Subscriptions",
        "Browser extension", "Settings",
    } else "Download"
    data["SubLangs"] = normalize_sublangs(data.get("SubLangs"))
    data["SubtitleMode"] = normalize_subtitle_mode(data.get("SubtitleMode"))
    data["SubtitleFormat"] = normalize_subtitle_format(data.get("SubtitleFormat"))
    data["SponsorBlockAction"] = "mark" if data.get("SponsorBlockAction") == "mark" else "remove"
    data["SponsorBlockCategories"] = normalize_sponsorblock_categories(
        data.get("SponsorBlockCategories")
    )
    data["ConcurrentFragments"] = clamp_int(data.get("ConcurrentFragments"), 4, 1, 32)
    data["MaxConcurrentDownloads"] = clamp_int(data.get("MaxConcurrentDownloads"), 3, 1, 10)
    data["DownloadRetries"] = clamp_int(data.get("DownloadRetries"), 10, 0, 50)
    runtime = clean_text(data.get("JavaScriptRuntime"), "auto", 16).lower()
    data["JavaScriptRuntime"] = runtime if runtime in JAVASCRIPT_RUNTIME_CHOICES else "auto"
    channel = clean_text(data.get("YtDlpUpdateChannel"), "nightly", 16).lower()
    data["YtDlpUpdateChannel"] = channel if channel in {"stable", "nightly"} else "nightly"
    data["RateLimit"] = normalize_rate_limit(data.get("RateLimit"))
    data["ThrottledRate"] = normalize_rate_limit(data.get("ThrottledRate"))
    data["SocketTimeoutSeconds"] = clamp_int(data.get("SocketTimeoutSeconds"), 0, 0, 300)
    data["ExtractorRetries"] = clamp_int(data.get("ExtractorRetries"), 0, 0, 20)
    video_codec = clean_text(data.get("VideoCodecPreference"), "auto", 16).lower()
    data["VideoCodecPreference"] = (
        video_codec if video_codec in FORMAT_SORT_VIDEO_CODECS else "auto"
    )
    audio_codec = clean_text(data.get("AudioCodecPreference"), "auto", 16).lower()
    data["AudioCodecPreference"] = (
        audio_codec if audio_codec in FORMAT_SORT_AUDIO_CODECS else "auto"
    )
    frame_rate = clamp_int(data.get("PreferredFrameRate"), 0, 0, 120)
    data["PreferredFrameRate"] = (
        frame_rate if frame_rate in FORMAT_SORT_FRAME_RATES else 0
    )
    data["PlaylistMaxItems"] = clamp_int(data.get("PlaylistMaxItems"), 0, 0, 1000)
    data["PlaylistDateAfter"] = normalize_playlist_date(data.get("PlaylistDateAfter"))
    data["PlaylistMinDurationSeconds"] = clamp_int(
        data.get("PlaylistMinDurationSeconds"), 0, 0, 86400)
    data["PlaylistMaxDurationSeconds"] = clamp_int(
        data.get("PlaylistMaxDurationSeconds"), 0, 0, 86400)
    # A maximum below the minimum matches nothing at all, which reads as a
    # broken download rather than a filter the user got wrong.
    if data["PlaylistMaxDurationSeconds"] and (
            data["PlaylistMaxDurationSeconds"] < data["PlaylistMinDurationSeconds"]):
        data["PlaylistMaxDurationSeconds"] = data["PlaylistMinDurationSeconds"]
    data["SleepIntervalSeconds"] = clamp_int(data.get("SleepIntervalSeconds"), 0, 0, 600)
    data["MaxSleepIntervalSeconds"] = clamp_int(data.get("MaxSleepIntervalSeconds"), 0, 0, 600)
    # yt-dlp rejects a maximum below the minimum, so the pair is normalised
    # here rather than at the argv, where it would fail the whole download.
    if data["MaxSleepIntervalSeconds"] and (
            data["MaxSleepIntervalSeconds"] < data["SleepIntervalSeconds"]):
        data["MaxSleepIntervalSeconds"] = data["SleepIntervalSeconds"]
    data["SleepRequestsSeconds"] = clamp_int(data.get("SleepRequestsSeconds"), 0, 0, 60)
    data["WaitForVideoSeconds"] = clamp_int(
        data.get("WaitForVideoSeconds"), 0, 0, 3600
    )
    data["PacingJitterPercent"] = clamp_int(
        data.get("PacingJitterPercent"), 0, 0, 100
    )
    data["ImpersonateTarget"] = normalize_impersonate_target(data.get("ImpersonateTarget"))
    data["Proxy"] = normalize_proxy(data.get("Proxy"))
    data["ForceIPVersion"] = normalize_force_ip_version(data.get("ForceIPVersion"))
    data["SourceAddress"] = normalize_source_address(data.get("SourceAddress"))
    data["Xff"] = normalize_xff(data.get("Xff"))
    data["GeoVerificationProxy"] = normalize_proxy(data.get("GeoVerificationProxy"))
    data["SiteProfiles"] = normalize_site_profiles(data.get("SiteProfiles"))
    language = clean_text(data.get("Language"), "system", 16).replace("-", "_")
    allowed_languages = {
        "system", "ar", "de", "en", "es", "fr", "it", "ja", "ko",
        "pt_BR", "ru", "zh_CN",
    }
    data["Language"] = language if language in allowed_languages else "system"
    data["LastYtDlpUpdateCheck"] = clean_text(data.get("LastYtDlpUpdateCheck"), "", 40)
    data["LastYtDlpUpdateAttempt"] = clean_text(data.get("LastYtDlpUpdateAttempt"), "", 40)
    data["LastYtDlpUpdateFailure"] = clean_text(data.get("LastYtDlpUpdateFailure"), "", 40)
    data["LastFfmpegCheck"] = clean_text(data.get("LastFfmpegCheck"), "", 40)
    data["MaxFileSizeMB"] = clamp_int(data.get("MaxFileSizeMB"), 0, 0, 102400)
    data["OutputTemplate"] = normalize_output_template(data.get("OutputTemplate"))
    data["NativeChromeExtensionIds"] = clean_text(data.get("NativeChromeExtensionIds"), "", 2048)
    data["NativeFirefoxExtensionIds"] = clean_text(data.get("NativeFirefoxExtensionIds"), "", 2048)
    data["LegacyHealthTokenOrigins"] = clean_text(data.get("LegacyHealthTokenOrigins"), "", 2048)
    extra = data.get("ExtraOutputRoots")
    if not isinstance(extra, list):
        extra = []
    data["ExtraOutputRoots"] = [
        cleaned
        for item in extra[:16]
        if isinstance(item, str) and (cleaned := clean_path_text(item))
    ]
    return data


def atomic_write_json(path, data):
    """Durably replace a JSON document without exposing partial contents."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            # reason: JSON scratch cleanup is best-effort after replacement or failure
            pass


def backup_corrupt_file(path, timestamp=None):
    """Move malformed state aside for support and recovery."""
    path = Path(path)
    if not path.exists():
        return None
    if timestamp is None:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.corrupt-{timestamp}")
    try:
        path.replace(backup)
        return backup
    except OSError:
        return None


_QUARANTINE_LOCK = threading.Lock()
_quarantined_state_files = []


def record_quarantined_file(path, backup):
    """Remember that a state file was set aside, so someone can be told.

    Quarantine is silent by design at the read site — the caller gets its
    fallback and carries on. But a config.json set aside here regenerates the
    server token, which breaks extension pairing, and a queue set aside here
    is indistinguishable from an empty one. The original bytes are still on
    disk beside the replacement; this is the record that says so.
    """
    entry = {'path': str(path), 'backup': str(backup)}
    with _QUARANTINE_LOCK:
        if entry not in _quarantined_state_files:
            _quarantined_state_files.append(entry)
    return entry


def quarantined_state_files():
    with _QUARANTINE_LOCK:
        return [dict(entry) for entry in _quarantined_state_files]


def forget_quarantined_file(backup):
    backup = str(backup)
    with _QUARANTINE_LOCK:
        remaining = [e for e in _quarantined_state_files if e['backup'] != backup]
        removed = len(remaining) != len(_quarantined_state_files)
        _quarantined_state_files[:] = remaining
    return removed


def restore_quarantined_file(backup):
    """Put a quarantined file back where it came from.

    Returns the restored path, or None. The caller reloads: this only moves
    bytes, and every store in this program reads its file once at construction.
    """
    backup = str(backup)
    with _QUARANTINE_LOCK:
        entry = next(
            (e for e in _quarantined_state_files if e['backup'] == backup), None)
    if entry is None:
        return None
    source = Path(entry['backup'])
    target = Path(entry['path'])
    if not source.exists():
        forget_quarantined_file(backup)
        return None
    try:
        source.replace(target)
    except OSError:
        return None
    forget_quarantined_file(backup)
    return target


def load_json_file(path, fallback, *, backup=backup_corrupt_file,
                   max_bytes=MAX_LOCAL_JSON_BYTES):
    """Read bounded JSON state, quarantining malformed files before fallback."""
    path = Path(path)
    if not path.exists():
        return fallback
    try:
        if path.stat().st_size > max_bytes:
            saved = backup(path)
            if saved:
                record_quarantined_file(path, saved)
            return fallback
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        saved = backup(path)
        if saved:
            record_quarantined_file(path, saved)
        return fallback


def sanitize_history_entries(raw, limit=500):
    """Normalize bounded download history from local or imported state."""
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw[-max(1, int(limit)):]:
        if not isinstance(item, dict):
            continue
        section, _section_error = normalize_download_section(item.get("section"))
        entry = {
            "id": clean_text(item.get("id"), "", 120),
            "url": clean_text(item.get("url"), "", 4096),
            "title": clean_text(item.get("title"), "(untitled)", 500) or "(untitled)",
            "filename": clean_path_text(item.get("filename")),
            "format": clean_text(item.get("format"), "", 16),
            "quality": clean_text(item.get("quality"), "", 16),
            "audioOnly": coerce_bool(item.get("audioOnly"), False),
            "date": clean_text(item.get("date"), "", 40),
            "duration": max(0, clamp_int(item.get("duration"), 0, 0, 60 * 60 * 24 * 30)),
            "status": clean_text(item.get("status"), "complete", 32) or "complete",
            "errorCode": clean_text(
                item.get("errorCode") or item.get("error_code"), "", 80
            ),
            "error": clean_text(
                item.get("error") or item.get("errorText"), "", 1000
            ),
        }
        if section:
            entry["section"] = section
        entries.append(entry)
    return entries


def query_history_entries(entries, *, query="", status="", fmt="",
                          date_from="", date_to="", sort="newest",
                          offset=0, limit=50):
    """Filter, sort, and page a bounded sanitized history collection."""
    query = str(query or "").strip().casefold()
    status = str(status or "").strip().casefold()
    fmt = str(fmt or "").strip().casefold()
    date_from = str(date_from or "").strip()
    date_to = str(date_to or "").strip()
    sort = "oldest" if sort == "oldest" else "newest"
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError, OverflowError):
        offset = 0
    try:
        limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError, OverflowError):
        limit = 50

    indexed = []
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict):
            continue
        entry_status = str(entry.get("status") or "complete").strip().casefold()
        entry_format = str(entry.get("format") or "").strip().casefold()
        entry_date = str(
            entry.get("date") or entry.get("completedAt") or entry.get("timestamp") or ""
        )[:10]
        haystack = "\n".join((
            str(entry.get("title") or ""),
            str(entry.get("filename") or ""),
        )).casefold()
        if query and query not in haystack:
            continue
        if status and status != "all" and entry_status != status:
            continue
        if fmt and fmt != "all" and entry_format != fmt:
            continue
        if date_from and (not entry_date or entry_date < date_from):
            continue
        if date_to and (not entry_date or entry_date > date_to):
            continue
        indexed.append((entry_date, index, entry))

    indexed.sort(
        key=lambda item: (item[0], item[1]),
        reverse=sort == "newest",
    )
    filtered_total = len(indexed)
    page = [item[2] for item in indexed[offset:offset + limit]]
    return {
        "history": page,
        "count": len(page),
        "total": len(entries) if isinstance(entries, list) else 0,
        "filteredTotal": filtered_total,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + len(page) < filtered_total,
        "sort": sort,
    }


class ConfigStore:
    """Transactional config persistence with explicit filesystem dependencies."""

    def __init__(self, *, install_dir, path, sanitizer, loader, writer, logger,
                 read_only=False):
        self._install_dir = install_dir
        self._path = path
        self._sanitizer = sanitizer
        self._loader = loader
        self._writer = writer
        self._logger = logger
        self._read_only = bool(read_only)
        self._lock = threading.RLock()
        # Session-only overrides (e.g. a fallback ServerPort after a bind
        # conflict): visible through get()/data so the running process uses
        # them, but never serialized — save()/update() persist _data only.
        self._session_overrides = {}
        self._resolve(self._install_dir).mkdir(parents=True, exist_ok=True)
        self._data = self._sanitizer(self._loader(self._resolve(self._path), {}))
        self._persisted_data = dict(self._data)
        if not self._read_only:
            self.save()

    @staticmethod
    def _resolve(value):
        return value() if callable(value) else value

    def get(self, key, default=None):
        with self._lock:
            if key in self._session_overrides:
                return self._session_overrides[key]
            return self._data.get(key, default)

    def reload(self):
        """Re-read the file from disk, discarding in-memory state.

        Used after a quarantined config is restored: the store read its file
        once, at construction, and by then the replacement had already been
        written with a fresh server token.
        """
        with self._lock:
            self._data = self._sanitizer(self._loader(self._resolve(self._path), {}))
            self._persisted_data = dict(self._data)
            self._session_overrides.clear()
            return True

    def get_persisted(self, key, default=None):
        """The durable value, ignoring any session-only override."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._data[key] = value

    def set_session(self, key, value):
        """Override a key for this process lifetime without persisting it."""
        with self._lock:
            self._session_overrides[key] = value

    def update(self, mapping):
        with self._lock:
            if self._read_only:
                return False
            candidate = dict(self._data)
            candidate.update(mapping)
            saved = self._save_candidate_unlocked(candidate)
            if saved:
                # An explicit write re-asserts these keys; a session override
                # must not keep shadowing the user's new value.
                for key in mapping:
                    self._session_overrides.pop(key, None)
            return saved

    def save(self):
        with self._lock:
            if self._read_only:
                return False
            return self._save_candidate_unlocked(self._data)

    def _save_candidate_unlocked(self, candidate):
        candidate = self._sanitizer(candidate)
        try:
            self._writer(self._resolve(self._path), candidate)
        except Exception as error:
            self._data = dict(self._persisted_data)
            self._logger(f"Config save failed: {error}")
            return False
        self._data = candidate
        self._persisted_data = dict(candidate)
        return True

    @property
    def data(self):
        with self._lock:
            merged = dict(self._data)
            merged.update(self._session_overrides)
            return merged


class HistoryStore:
    """Bounded history persistence with explicit serialization dependencies."""

    def __init__(self, *, path, sanitizer, loader, writer, logger, limit=500):
        self._path = path
        self._sanitizer = sanitizer
        self._loader = loader
        self._writer = writer
        self._logger = logger
        self._limit = max(1, int(limit))
        self._lock = threading.Lock()
        if not self._resolve_path().exists():
            self._write([])

    def _resolve_path(self):
        return self._path() if callable(self._path) else self._path

    def load(self):
        with self._lock:
            return self._sanitizer(self._loader(self._resolve_path(), []))

    def add(self, entry):
        with self._lock:
            data = self._sanitizer(self._loader(self._resolve_path(), []))
            data.append(entry)
            return self._write_unlocked(data[-self._limit:])

    def clear(self):
        with self._lock:
            return self._write_unlocked([])

    def replace(self, entries):
        with self._lock:
            return self._write_unlocked(entries)

    def _write(self, data):
        with self._lock:
            return self._write_unlocked(data)

    def _write_unlocked(self, data):
        try:
            self._writer(self._resolve_path(), self._sanitizer(data))
            return True
        except Exception as error:
            self._logger(f"History save failed: {error}")
            return False


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
