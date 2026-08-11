"""Import-safe download domain model and policy boundary."""

import getpass
import glob
import ipaddress
import json
import logging
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


_LOGGER = logging.getLogger(__name__)

try:
    from ._compat import make_legacy_resolver
except ImportError:  # Flat source-path compatibility.
    from _compat import make_legacy_resolver

try:
    from .config import default_download_path, SITE_PROFILE_OVERRIDE_KEYS
except ImportError:  # Flat source-path compatibility.
    from config import default_download_path, SITE_PROFILE_OVERRIDE_KEYS


__all__ = (
    "Download", "DownloadManager", "DownloadManagerCore", "build_video_format_args",
    "YTDLPActivityRegistry",
    "terminate_process_tree", "is_playlist_url", "write_cookies_netscape",
    "cleanup_stale_cookie_jars", "DOWNLOAD_ACTIVE_STATES",
    "DOWNLOAD_RUNNING_STATES", "DOWNLOAD_PENDING_STATES",
    "DOWNLOAD_TERMINAL_STATES", "DOWNLOAD_RETRYABLE_ERROR_CODES",
    "DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES",
    "DOWNLOAD_QUEUE_PATH", "MAX_CONCURRENT", "MAX_QUEUED_TOTAL",
    "HOST_BACKOFF_BASE_SECONDS", "HOST_BACKOFF_MAX_SECONDS",
    "HOST_BACKOFF_MAX_ENTRIES", "parse_retry_after_seconds",
    "build_impersonate_args",
    "build_network_workaround_args",
    "build_subtitle_args", "build_local_subtitle_args",
    "build_whisper_audio_args", "build_whisper_transcription_args",
    "local_subtitle_output_path", "local_subtitle_sidecar_exists",
    "should_generate_local_subtitles", "subtitle_language_for_transcription",
    "escape_ffmpeg_filter_value",
    "RESUME_ROLLBACK_FIELDS", "RETRY_ROLLBACK_FIELDS",
    "snapshot_download_fields", "restore_download_fields",
    "DOWNLOAD_STALL_TIMEOUT_SECONDS", "DOWNLOAD_WATCHDOG_POLL_SECONDS",
    "download_error_payload", "classify_download_failure",
    "apply_download_failure_classification", "DOWNLOAD_FAILURE_RECOVERY",
    "estimate_download_bytes", "check_download_disk_space",
    "po_provider_nudge_advice", "PO_PROVIDER_NUDGE_CODES", "PO_PROVIDER_NUDGE",
    "summarize_ytdlp_formats", "summarize_ytdlp_playlist",
    "ALLOWED_COOKIE_DOMAINS", "build_subprocess_env",
    "DownloadQueueStore", "DOWNLOAD_QUEUE_SCHEMA_VERSION",
    "PLAYLIST_PREVIEW_LIMIT",
    "SiteLoginStore", "site_login_key", "registrable_domain",
    "select_site_profile",
    "cookie_domain_in_site", "parse_netscape_cookies",
    "build_browser_cookie_args", "describe_browser_cookie_failure",
    "describe_browser_cookie_readiness", "build_site_login_credential_args",
    "SITE_LOGIN_BROWSERS", "MAX_SITE_LOGINS", "MAX_SITE_LOGIN_COOKIES",
    "MAX_SITE_LOGIN_TEXT_BYTES",
    "MAX_SITE_LOGIN_USERNAME_BYTES", "MAX_SITE_LOGIN_PASSWORD_BYTES",
    "SITE_LOGIN_DIRNAME", "SITE_LOGIN_INDEX_NAME",
    "SITE_LOGIN_CREDENTIAL_SUFFIX", "SITE_LOGIN_UNSUPPORTED_CREDENTIAL_SITES",
    "SITE_LOGIN_TEST_TIMEOUT_SECONDS",
    "default_download_path",
)

MAX_CONCURRENT = 3
MAX_QUEUED_TOTAL = 200
HOST_BACKOFF_BASE_SECONDS = 60
HOST_BACKOFF_MAX_SECONDS = 30 * 60
HOST_BACKOFF_MAX_ENTRIES = 64
DOWNLOAD_STALL_TIMEOUT_SECONDS = 1800
DOWNLOAD_WATCHDOG_POLL_SECONDS = 15
DOWNLOAD_QUEUE_SCHEMA_VERSION = 1
DOWNLOAD_INTERMEDIATE_DIRNAME = 'download-temp'
PLAYLIST_PREVIEW_LIMIT = 200
DOWNLOAD_RUNNING_STATES = {
    'queued', 'downloading', 'merging', 'extracting', 'trimming', 'transcribing',
}
DOWNLOAD_PENDING_STATES = {'pending', 'paused', 'needs-auth'}
DOWNLOAD_ACTIVE_STATES = DOWNLOAD_RUNNING_STATES | DOWNLOAD_PENDING_STATES
# 'skipped' = yt-dlp exited 0 without writing media (size cap, no downloadable
# media on the page). Terminal like the rest; the extension's download panel
# has rendered this status since v3.20.7.
DOWNLOAD_TERMINAL_STATES = {'complete', 'failed', 'cancelled', 'skipped'}
DOWNLOAD_RETRYABLE_ERROR_CODES = {
    # Transient by definition: the limit expires on its own.
    'rate-limited',
    'network-unreachable',
    'po-provider-stale',
    'po-token-required',
    'cookie-jar-failed',
    'worker-start-failed',
    'transcription-model-missing',
    'transcription-failed',
}
DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES = frozenset({
    'transcription-model-missing',
    'transcription-runtime-missing',
    'transcription-failed',
})

DOWNLOAD_DISK_SPACE_RESERVE_BYTES = 32 * 1024 * 1024


def _stored_schema_version(value):
    """Parse a JSON schema marker without treating booleans as integers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    return None

DOWNLOAD_FAILURE_RECOVERY = {
    'po-token-required': {
        'error': (
            'YouTube requires a proof-of-origin token for this video, and the '
            'plugin-free client chain cannot supply one.'
        ),
        'advice': (
            'Retry with a stored site sign-in, or try again later if YouTube '
            'makes a token-exempt format available.'
        ),
        'next_action': 'sign-in-and-retry',
    },
    'po-provider-stale': {
        'error': (
            'The YouTube proof-of-origin token path is unavailable for this '
            'video.'
        ),
        'advice': (
            'The plugin-based provider path is disabled. Retry with a stored '
            'site sign-in or later.'
        ),
        'next_action': 'sign-in-and-retry',
    },
    'sabr-limited': {
        'error': (
            'This video only exposes SABR-limited formats that this yt-dlp '
            'path cannot download yet.'
        ),
        'advice': (
            'Clip ranges, the bandwidth cap and concurrent fragments do not '
            'apply to SABR streams and were ignored. Update yt-dlp when SABR '
            'support lands, or retry after YouTube exposes standard formats.'
        ),
        'next_action': 'update-ytdlp-or-retry-later',
    },
    'deno-runtime-missing': {
        'error': (
            'yt-dlp needs the Deno JavaScript runtime to solve recent YouTube '
            'signature challenges.'
        ),
        'advice': 'Install Deno with winget install DenoLand.Deno, then restart Astra Downloader.',
        'next_action': 'install-deno',
    },
    'deno-runtime-unsupported': {
        'error': (
            'The installed Deno runtime is too old for this yt-dlp build to '
            'solve recent YouTube signature challenges.'
        ),
        'advice': 'Upgrade Deno to 2.3.0 or newer with winget upgrade DenoLand.Deno, then retry.',
        'next_action': 'upgrade-deno',
    },
    'js-runtime-missing': {
        'error': 'yt-dlp needs a configured JavaScript runtime for YouTube challenges.',
        'advice': 'Provision Deno, or install Node 22+ and select it in companion settings.',
        'next_action': 'configure-javascript-runtime',
    },
    'js-runtime-unverified': {
        'error': 'Astra Downloader could not verify the configured JavaScript runtime.',
        'advice': 'Repair or replace the selected runtime, then retry.',
        'next_action': 'repair-javascript-runtime',
    },
    'js-runtime-unsupported': {
        'error': "The configured JavaScript runtime is below yt-dlp's supported floor.",
        'advice': 'Upgrade to Deno 2.3+ or Node 22+, then retry.',
        'next_action': 'upgrade-javascript-runtime',
    },
    'ejs-runtime-not-ready': {
        'error': 'The configured runtime could not execute the yt-dlp EJS capability probe.',
        'advice': 'Repair or replace the selected JavaScript runtime, then retry.',
        'next_action': 'repair-javascript-runtime',
    },
    'sign-in-required': {
        'error': (
            'Sign in to confirm YouTube access. Grant browser cookies or open '
            'the video while signed in, then retry.'
        ),
        'advice': 'Sign in to YouTube in this browser and allow Astra Deck to attach YouTube cookies.',
        'next_action': 'sign-in-and-retry',
    },
    'ffmpeg-missing-or-stale': {
        'error': 'ffmpeg is missing, stale, or failed during merge/extract.',
        'advice': 'Open Astra Downloader and refresh ffmpeg before retrying.',
        'next_action': 'refresh-ffmpeg',
    },
    'network-unreachable': {
        'error': 'Astra Downloader could not reach the site or a required provider.',
        'advice': 'Check the network, VPN, firewall, and provider process, then retry.',
        'next_action': 'check-network-and-retry',
    },
    'cookie-jar-failed': {
        'error': 'Astra Downloader could not create a protected YouTube cookie jar.',
        'advice': 'Retry from Astra Deck so fresh cookies can be supplied.',
        'next_action': 'sign-in-and-retry',
    },
    'blocked-by-site': {
        'error': 'The site refused the request (HTTP 403).',
        'advice': (
            'Set a browser to imitate in Settings — this is the usual remedy '
            'for a Cloudflare or TLS-fingerprint block. A stored sign-in for '
            'the site also helps. If a dual-stack route is returning the 403, '
            'try `--force-ipv4` in Settings.'
        ),
        'next_action': 'impersonate-and-retry',
    },
    'geo-restricted': {
        'error': 'The site says this media is unavailable in your region.',
        'advice': (
            'Set `--xff` to a two-letter country code or CIDR block in Settings '
            'for geo verification. If that path is still blocked, add a '
            '`--geo-verification-proxy` there, then retry.'
        ),
        'next_action': 'configure-geo-and-retry',
    },
    'rate-limited': {
        'error': 'The site refused further requests for now (HTTP 429).',
        'advice': (
            'This site is paused for the rest of its retry window. Raise the '
            'request pacing in Settings — a bandwidth cap does not help here — '
            'then retry. Other sites can continue downloading.'
        ),
        'next_action': 'slow-down-and-retry',
    },
    'insufficient-disk-space': {
        'error': 'There is not enough free disk space for this download.',
        'advice': 'Free space on the destination drive, then retry the download.',
        'next_action': 'free-disk-space-and-retry',
    },
    'transcription-model-missing': {
        'error': 'The local transcription model is missing or damaged.',
        'advice': (
            'Run setup with local subtitle generation enabled, then retry subtitle '
            'generation on this completed media.'
        ),
        'next_action': 'run-setup-and-retry-subtitles',
    },
    'transcription-runtime-missing': {
        'error': 'The local transcription runtime is missing or cannot produce SRT output.',
        'advice': (
            'Run setup with local subtitle generation enabled, then retry subtitle '
            'generation on this completed media.'
        ),
        'next_action': 'run-setup-and-retry-subtitles',
    },
    'transcription-failed': {
        'error': 'Local subtitle generation failed after the media downloaded.',
        'advice': (
            'Check the local transcription readiness rows, then retry subtitles '
            'without downloading the media again.'
        ),
        'next_action': 'retry-subtitles',
    },
}

ALLOWED_COOKIE_DOMAINS = frozenset({
    ".youtube.com", "youtube.com", ".www.youtube.com", "www.youtube.com",
    ".m.youtube.com", "m.youtube.com", ".music.youtube.com", "music.youtube.com",
    ".youtube-nocookie.com", "youtube-nocookie.com",
    ".www.youtube-nocookie.com", "www.youtube-nocookie.com",
    ".youtu.be", "youtu.be", ".google.com", "google.com",
    ".accounts.google.com", "accounts.google.com",
})
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
_SUBPROCESS_ENV_ALLOWLIST = (
    'PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'COMSPEC',
    'TEMP', 'TMP', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
    'PROGRAMDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'WINDIR',
    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS',
    'LANG', 'LC_ALL', 'LC_CTYPE',
)


def _sanitize_cookie_field(value, max_len=4096):
    if value is None:
        return ""
    value = _CONTROL_CHARS_RE.sub("", str(value))
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()[:max_len]


def _is_allowed_cookie_domain(domain):
    if not domain:
        return False
    domain = domain.lower().strip()
    return domain in ALLOWED_COOKIE_DOMAINS or any(
        domain.endswith(allowed)
        for allowed in ALLOWED_COOKIE_DOMAINS
        if allowed.startswith('.')
    )


def _log_warning(logger, message):
    """Report a recoverable companion failure without masking the original path."""
    text = f"WARNING: {message}"
    try:
        if logger:
            logger(text)
        else:
            _LOGGER.warning(text)
    except Exception:
        # reason: diagnostic logging must never turn best-effort cleanup into a failure
        _LOGGER.warning(text)


def _windows_cookie_identity():
    user = os.environ.get('USERNAME') or getpass.getuser()
    domain = os.environ.get('USERDOMAIN')
    if domain and user and '\\' not in user:
        return f'{domain}\\{user}'
    return user


def _apply_cookie_jar_acl(target_path):
    """Apply a fail-closed owner-only ACL before cookie bytes are written."""
    target_path = Path(target_path)
    if os.name != 'nt':
        os.chmod(target_path, 0o600)
        if target_path.stat().st_mode & 0o077:
            raise PermissionError('cookie jar is not owner-only')
        return

    identity = _windows_cookie_identity()
    if not identity:
        raise PermissionError('Windows account identity is unavailable')
    try:
        result = subprocess.run(
            [
                'icacls', str(target_path),
                '/inheritance:r',
                '/grant:r', f'{identity}:F',
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PermissionError(f'icacls could not protect cookie jar: {error}') from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip()
        raise PermissionError(f'icacls rejected cookie jar ACL: {detail or result.returncode}')

    # /inheritance:r must remove every inherited ACE. A second readback keeps
    # the security guarantee observable and prevents silently proceeding when
    # a policy or localized account lookup leaves a broad inherited grant.
    try:
        verify = subprocess.run(
            ['icacls', str(target_path)],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PermissionError(f'icacls ACL verification failed: {error}') from error
    acl_text = f'{verify.stdout or ""}\n{verify.stderr or ""}'
    if verify.returncode != 0 or '(I)' in acl_text:
        raise PermissionError('cookie jar ACL still contains inherited permissions')


def write_cookies_netscape(cookies, target_path, *, logger=None, domain_filter=None):
    """Persist allowlisted browser cookies as an atomic protected jar.

    `domain_filter` decides which cookie domains may be written. It defaults to
    the YouTube/Google allowlist used by the extension's per-download jars; the
    site-login store passes a filter scoped to the one site the jar belongs to,
    so a stored login can never widen into a general cookie dump.
    """
    if not isinstance(cookies, list) or not cookies:
        return None

    allow_domain = domain_filter or _is_allowed_cookie_domain
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Netscape HTTP Cookie File",
        "# Auto-generated by Astra Downloader — do not edit",
        "",
    ]
    for entry in cookies:
        if not isinstance(entry, dict):
            continue
        name = _sanitize_cookie_field(entry.get("name"), 256)
        domain = _sanitize_cookie_field(entry.get("domain"), 256)
        if not name or not allow_domain(domain):
            continue
        try:
            raw_expiry = entry.get("expirationDate")
            expiry = int(float(raw_expiry)) if raw_expiry not in (None, "") else 0
            expiry = max(0, expiry)
        except Exception:  # noqa: BLE001
            expiry = 0
        lines.append(
            f"{'#HttpOnly_' if entry.get('httpOnly') else ''}{domain}\t"
            f"{'TRUE' if domain.startswith('.') else 'FALSE'}\t"
            f"{_sanitize_cookie_field(entry.get('path'), 512) or '/'}\t"
            f"{'TRUE' if entry.get('secure') else 'FALSE'}\t{expiry}\t{name}\t"
            f"{_sanitize_cookie_field(entry.get('value'), 4096)}"
        )
    if len(lines) == 3:
        return None

    temporary = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = None
    try:
        # Create an empty file with restrictive mode first. Windows ignores
        # POSIX mode bits for ACL enforcement, so icacls runs before the first
        # cookie byte is written and the ACL travels with the atomic rename.
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        _apply_cookie_jar_acl(temporary)
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target_path)
        return str(target_path)
    except Exception as error:
        if logger:
            logger(f"Cookie jar write failed: {error}")
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                # reason: the descriptor is already unusable while unwinding a failed jar write
                pass
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            # reason: the temporary jar may already have been removed by the failed operation
            pass
        return None


def _write_protected_bytes(data, target_path, *, logger=None):
    """Atomically replace an owner-only file without exposing its contents."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        _apply_cookie_jar_acl(temporary)
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target_path)
        return True
    except Exception:
        # Do not include the exception or path in the log: a mocked writer or
        # OS error is allowed to contain a credential or a user name.
        if logger:
            logger("Site-login credential write failed.")
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                # reason: the descriptor is already unusable while unwinding a failed secret write
                pass
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            # reason: the temporary secret file may already have been removed by the failed operation
            pass
        return False


# ── Site logins ───────────────────────────────────────────────────────────
# Sites with sign-in (X, Instagram, Facebook, members-only Vimeo, adult and
# paywalled sites, plus YouTube when no fresh extension cookies are available)
# serve media only to a signed-in session. The extension's cookie bridge is
# page-scoped, so the companion keeps its own store — one protected Netscape
# jar per site, imported once, attached automatically to downloads for that
# site and to nothing else.
#
# Import sources, in order of reliability on Windows:
#   1. A cookies.txt file or pasted text exported from the browser.
#   2. Extension-shaped cookie records posted to /site-logins.
#   3. yt-dlp's own browser reader (`--cookies-from-browser`), which works for
#      Firefox but fails on Chrome 127+ / Edge because app-bound encryption
#      blocks DPAPI (yt-dlp issue #10927) — the failure is reported verbatim so
#      the user is told to use source 1 instead of being left guessing.

SITE_LOGIN_DIRNAME = 'site-logins'
SITE_LOGIN_INDEX_NAME = 'index.json'
SITE_LOGIN_SCHEMA_VERSION = 1
MAX_SITE_LOGINS = 50
MAX_SITE_LOGIN_COOKIES = 400
MAX_SITE_LOGIN_TEXT_BYTES = 1024 * 1024
SITE_LOGIN_TEST_TIMEOUT_SECONDS = 30
SITE_LOGIN_CREDENTIAL_SUFFIX = '.auth'
MAX_SITE_LOGIN_USERNAME_BYTES = 512
MAX_SITE_LOGIN_PASSWORD_BYTES = 4096
SITE_LOGIN_UNSUPPORTED_CREDENTIAL_SITES = frozenset({'reddit.com', 'linkedin.com'})
SITE_LOGIN_BROWSERS = (
    'brave', 'chrome', 'chromium', 'edge', 'firefox', 'opera', 'safari',
    'vivaldi', 'whale',
)
CHROMIUM_SITE_LOGIN_BROWSERS = frozenset({
    'brave', 'chrome', 'chromium', 'edge', 'opera', 'vivaldi', 'whale',
})
# Two-label public suffixes common enough to matter when deciding what "the
# same site" means. Not a full PSL — a wrong answer here only makes the store
# key more or less specific, never more permissive than the host itself.
_MULTI_LABEL_SUFFIXES = frozenset({
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'me.uk', 'net.uk', 'sch.uk',
    'com.au', 'net.au', 'org.au', 'edu.au', 'gov.au', 'co.nz', 'net.nz',
    'org.nz', 'co.jp', 'ne.jp', 'or.jp', 'ac.jp', 'go.jp', 'com.br',
    'net.br', 'org.br', 'com.cn', 'net.cn', 'org.cn', 'com.mx', 'com.ar',
    'com.tr', 'com.tw', 'com.hk', 'com.sg', 'com.my', 'com.ph', 'co.in',
    'co.kr', 'co.za', 'com.pl', 'com.ua', 'co.il', 'com.co', 'com.pe',
})
_SITE_KEY_RE = re.compile(r'[^a-z0-9.\-]')
_SITE_LOGIN_UNDO_TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')


def registrable_domain(host):
    """Return the "same site" key for a host: `www.reddit.com` -> `reddit.com`.

    Falls back to the host itself when it is already minimal or unparseable.
    """
    host = str(host or '').strip().strip('.').lower()
    if not host:
        return ''
    labels = [label for label in host.split('.') if label]
    if len(labels) < 3:
        return '.'.join(labels)
    if '.'.join(labels[-2:]) in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return '.'.join(labels[-3:])
    return '.'.join(labels[-2:])


def site_login_key(value):
    """Normalize a URL or hostname into a filesystem-safe store key."""
    raw = str(value or '').strip()
    if not raw:
        return ''
    if '://' in raw:
        try:
            raw = urlparse(raw).hostname or ''
        except ValueError:
            return ''
    else:
        raw = raw.split('/', 1)[0].split(':', 1)[0]
    key = registrable_domain(raw)
    key = _SITE_KEY_RE.sub('', key)
    return key.strip('.')[:120]


def select_site_profile(url, profiles, profile_name=None):
    """Return the named profile for a URL, or the longest matching domain.

    ``None`` means automatic matching, while an empty string is the explicit
    one-off choice to disable profiles for this download. A named selection is
    allowed to cross its stored domain so a user can deliberately reuse a
    profile once; it remains a settings profile, never a credential store.
    """
    records = profiles if isinstance(profiles, (list, tuple)) else ()
    if profile_name == "":
        return None
    if profile_name is not None:
        wanted = str(profile_name).strip().casefold()
        if not wanted:
            return None
        return next(
            (
                dict(profile) for profile in records
                if isinstance(profile, dict)
                and str(profile.get("Name") or "").strip().casefold() == wanted
            ),
            None,
        )
    try:
        host = (urlparse(str(url or "")).hostname or "").strip().rstrip(".").lower()
    except ValueError:
        host = ""
    if not host:
        return None
    matches = [
        profile for profile in records
        if isinstance(profile, dict)
        and (
            host == str(profile.get("Domain") or "").strip().lower()
            or host.endswith("." + str(profile.get("Domain") or "").strip().lower())
        )
    ]
    if not matches:
        return None
    return dict(max(matches, key=lambda profile: len(str(profile.get("Domain") or ""))))


class _ProfileConfigOverlay:
    """A read-only config view with non-empty profile overrides applied."""

    def __init__(self, base, profile):
        self._base = base
        self._profile = profile if isinstance(profile, dict) else {}

    def get(self, key, default=None):
        if key in SITE_PROFILE_OVERRIDE_KEYS:
            value = self._profile.get(key)
            if value not in (None, "", 0):
                return value
        return self._base.get(key, default)


def cookie_domain_in_site(cookie_domain, site_key):
    """True when a cookie's domain belongs to the site the jar was stored for.

    This is the guard that keeps a stored login site-scoped: an imported
    cookies.txt full of every site the browser knows is reduced to the one site
    being signed in to, both when it is written and when it is used.
    """
    domain = str(cookie_domain or '').strip().lstrip('.').lower().rstrip('.')
    site = str(site_key or '').strip().lower()
    if not domain or not site:
        return False
    return domain == site or domain.endswith('.' + site)


def parse_netscape_cookies(text, *, limit=MAX_SITE_LOGIN_COOKIES):
    """Parse Netscape cookies.txt content into extension-shaped records.

    Returns records in the same shape the extension posts (`name`, `value`,
    `domain`, `path`, `secure`, `httpOnly`, `expirationDate`) so both import
    paths converge on one writer, one sanitizer, and one ACL.
    """
    records = []
    for raw_line in str(text or '').splitlines():
        if len(records) >= limit:
            break
        line = raw_line.rstrip('\n').rstrip('\r')
        http_only = False
        if line.startswith('#HttpOnly_'):
            http_only = True
            line = line[len('#HttpOnly_'):]
        elif line.lstrip().startswith('#') or not line.strip():
            continue
        fields = line.split('\t')
        if len(fields) < 7:
            # Some exporters emit space-padded columns; accept those too.
            fields = line.split()
            if len(fields) < 7:
                continue
            fields = fields[:6] + [' '.join(fields[6:])]
        domain, _include_sub, path, secure, expiry, name, value = fields[:7]
        if not domain or not name:
            continue
        try:
            expiration = max(0, int(float(expiry)))
        except (TypeError, ValueError, OverflowError):
            expiration = 0
        records.append({
            'name': name,
            'value': value,
            'domain': domain,
            'path': path or '/',
            'secure': str(secure).strip().upper() == 'TRUE',
            'httpOnly': http_only,
            'expirationDate': expiration,
        })
    return records


class SiteLoginStore:
    """Durable, per-site cookies or credentials for signed-in downloads.

    Cookie and password values never leave their protected files:
    `entries()` reports metadata only, which is what the GUI, the API, and
    the diagnostics bundle are allowed to see.
    """

    def __init__(self, root, *, logger=None, clock=time.time,
                 reader=None, writer=None):
        self.root = Path(root) / SITE_LOGIN_DIRNAME
        self.index_path = self.root / SITE_LOGIN_INDEX_NAME
        self._logger = logger
        self._clock = clock
        self._reader = reader
        self._writer = writer
        self._lock = threading.RLock()
        # Undo backups contain session or password values, so they are
        # session-only and never survive a new store instance. A crash
        # therefore cannot leave an unlisted live sign-in in the protected
        # directory indefinitely.
        self._cleanup_undo_backups()

    # -- storage -----------------------------------------------------------
    def _log(self, message):
        if self._logger:
            try:
                self._logger(message)
            except Exception:
                # reason: store bookkeeping must never fail a download
                pass

    def _ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            _apply_cookie_jar_acl(self.root)
        except Exception as error:
            self._log(f"WARNING: site-login directory ACL failed: {error}")

    def _load_index(self):
        if self._reader is not None:
            raw = self._reader(self.index_path, {})
        else:
            try:
                raw = json.loads(self.index_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raw = {}
        if not isinstance(raw, dict):
            return {}
        entries = raw.get('sites')
        if not isinstance(entries, dict):
            return {}
        return {
            str(key): value for key, value in entries.items()
            if isinstance(value, dict)
        }

    def _save_index(self, entries):
        payload = {
            'schemaVersion': SITE_LOGIN_SCHEMA_VERSION,
            'sites': entries,
        }
        if self._writer is not None:
            # Injected writers signal failure by raising (atomic_write_json
            # returns None on success), which is the same contract
            # DownloadQueueStore.save relies on.
            try:
                self._writer(self.index_path, payload)
                return True
            except Exception as error:  # noqa: BLE001
                self._log(f"WARNING: site-login index save failed: {error}")
                return False
        try:
            self._ensure_root()
            self.index_path.write_text(
                json.dumps(payload, indent=2), encoding='utf-8'
            )
            return True
        except OSError as error:
            self._log(f"WARNING: site-login index save failed: {error}")
            return False

    def _jar_path(self, key):
        return self.root / f"{key}.txt"

    def _credential_path(self, key):
        return self.root / f"{key}{SITE_LOGIN_CREDENTIAL_SUFFIX}"

    def _undo_path(self, token):
        if not _SITE_LOGIN_UNDO_TOKEN_RE.fullmatch(str(token or "")):
            return None
        return self.root / f".undo-{token}.txt"

    def _credential_undo_path(self, token):
        if not _SITE_LOGIN_UNDO_TOKEN_RE.fullmatch(str(token or "")):
            return None
        return self.root / f".undo-{token}{SITE_LOGIN_CREDENTIAL_SUFFIX}"

    def _cleanup_undo_backups(self):
        try:
            if not self.root.exists():
                return
            for path in tuple(self.root.glob(".undo-*.txt")) + tuple(
                self.root.glob(f".undo-*{SITE_LOGIN_CREDENTIAL_SUFFIX}")
            ):
                try:
                    path.unlink()
                except OSError as error:
                    self._log(f"WARNING: stale site-login undo cleanup failed: {error}")
        except OSError as error:
            self._log(f"WARNING: site-login undo scan failed: {error}")

    @staticmethod
    def _undo_record(record):
        """Keep only non-secret index metadata in an undo token."""
        record = record if isinstance(record, dict) else {}

        def nonnegative_int(value):
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError, OverflowError):
                return 0

        return {
            'label': str(record.get('label') or '')[:120],
            'source': str(record.get('source') or 'import')[:60],
            'cookies': nonnegative_int(record.get('cookies')),
            'importedAt': nonnegative_int(record.get('importedAt')),
            'earliestExpiry': nonnegative_int(record.get('earliestExpiry')),
        }

    # -- reads -------------------------------------------------------------
    def entries(self):
        """Return metadata for every stored login. Never returns secrets."""
        with self._lock:
            index = self._load_index()
        result = []
        now = self._clock()
        for key, record in sorted(index.items()):
            expiry = record.get('earliestExpiry') or 0
            try:
                expiry = int(expiry)
            except (TypeError, ValueError):
                expiry = 0
            jar_stored = self._jar_path(key).exists()
            credentialed = self._credential_path(key).exists()
            result.append({
                'site': key,
                'label': str(record.get('label') or key)[:120],
                'source': str(record.get('source') or 'import')[:60],
                'cookies': int(record.get('cookies') or 0),
                'importedAt': int(record.get('importedAt') or 0),
                'earliestExpiry': expiry,
                'expired': bool(expiry and expiry <= now),
                'credentialed': credentialed,
                'stored': jar_stored or credentialed,
            })
        return result

    def has_login_for(self, url):
        return bool(self.site_key_for_url(url))

    def site_key_for_url(self, url):
        """Return the stored site key that covers a URL, or '' when none does."""
        key = site_login_key(url)
        if not key:
            return ''
        with self._lock:
            index = self._load_index()
        if key in index and (
            self._jar_path(key).exists() or self._credential_path(key).exists()
        ):
            return key
        return ''

    @staticmethod
    def _valid_credential_value(value, max_bytes):
        if not isinstance(value, str) or not value or '\x00' in value:
            return False
        try:
            return len(value.encode('utf-8')) <= max_bytes
        except UnicodeError:
            return False

    def credentials_for_url(self, url):
        """Return one site's credentials for internal argv construction only."""
        key = site_login_key(url)
        if not key:
            return None
        with self._lock:
            index = self._load_index()
            path = self._credential_path(key)
            if key not in index or not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError, UnicodeError):
                self._log(f"WARNING: stored site sign-in credentials for {key} are unreadable.")
                return None
        if not isinstance(payload, dict) or payload.get('schemaVersion') != 1:
            self._log(f"WARNING: stored site sign-in credentials for {key} are invalid.")
            return None
        username = payload.get('username')
        password = payload.get('password')
        if not self._valid_credential_value(username, MAX_SITE_LOGIN_USERNAME_BYTES):
            self._log(f"WARNING: stored site sign-in username for {key} is invalid.")
            return None
        if not self._valid_credential_value(password, MAX_SITE_LOGIN_PASSWORD_BYTES):
            self._log(f"WARNING: stored site sign-in password for {key} is invalid.")
            return None
        return {'username': username, 'password': password}

    # -- writes ------------------------------------------------------------
    def save_cookies(self, site, cookies, *, source='import', label=None):
        """Filter cookie records to one site and persist a protected jar."""
        key = site_login_key(site)
        if not key:
            return None, 'Enter the site address you signed in to, such as x.com.'
        if not isinstance(cookies, list) or not cookies:
            return None, 'No cookies were found to import.'
        scoped = [
            entry for entry in cookies[:MAX_SITE_LOGIN_COOKIES]
            if isinstance(entry, dict)
            and cookie_domain_in_site(entry.get('domain'), key)
        ]
        if not scoped:
            return None, (
                f'None of those cookies belong to {key}. Sign in to the site '
                'first, then export or share its cookies.'
            )
        with self._lock:
            index = self._load_index()
            if key not in index and len(index) >= MAX_SITE_LOGINS:
                return None, (
                    f'Site sign-in limit reached ({MAX_SITE_LOGINS}). '
                    'Remove one before adding another.'
                )
            self._ensure_root()
            written = write_cookies_netscape(
                scoped,
                self._jar_path(key),
                logger=self._logger,
                domain_filter=lambda domain: cookie_domain_in_site(domain, key),
            )
            if not written:
                return None, 'Astra Downloader could not store the cookies safely.'
            expiries = [
                int(entry.get('expirationDate') or 0) for entry in scoped
                if int(entry.get('expirationDate') or 0) > 0
            ]
            index[key] = {
                'label': str(label or key)[:120],
                'source': str(source)[:60],
                'cookies': len(scoped),
                'importedAt': int(self._clock()),
                'earliestExpiry': min(expiries) if expiries else 0,
            }
            if not self._save_index(index):
                # The jar is already on disk at this point. An unrecorded jar is
                # invisible to entries() — no row, so no Remove button — while
                # still holding a live session, so it must not survive a failed
                # index write.
                try:
                    self._jar_path(key).unlink(missing_ok=True)
                except OSError as error:
                    self._log(f"WARNING: orphaned site-login jar cleanup failed: {error}")
                return None, (
                    'Astra Downloader stored the cookies but could not record '
                    'the sign-in, so it was rolled back. Check disk space and '
                    'permissions, then try again.'
                )
        self._log(
            f"Stored a site sign-in for {key} ({len(scoped)} cookies, source={source})"
        )
        return {
            'site': key,
            'cookies': len(scoped),
            'skipped': max(0, len(cookies) - len(scoped)),
        }, None

    def save_credentials(self, site, username, password, *, source='credentials', label=None):
        """Persist one site's username/password without putting either in metadata."""
        key = site_login_key(site)
        if not key:
            return None, 'Enter the site address you sign in to, such as vimeo.com.'
        if key in SITE_LOGIN_UNSUPPORTED_CREDENTIAL_SITES:
            return None, (
                f'yt-dlp no longer supports username/password sign-in for {key}. '
                'Use an exported cookies.txt file instead.'
            )
        if not self._valid_credential_value(username, MAX_SITE_LOGIN_USERNAME_BYTES):
            return None, 'Enter a username up to 512 UTF-8 bytes.'
        if not self._valid_credential_value(password, MAX_SITE_LOGIN_PASSWORD_BYTES):
            return None, 'Enter a password up to 4096 UTF-8 bytes.'
        payload = json.dumps(
            {'schemaVersion': 1, 'username': username, 'password': password},
            ensure_ascii=False,
            separators=(',', ':'),
        ).encode('utf-8')
        with self._lock:
            index = self._load_index()
            if key not in index and len(index) >= MAX_SITE_LOGINS:
                return None, (
                    f'Site sign-in limit reached ({MAX_SITE_LOGINS}). '
                    'Remove one before adding another.'
                )
            self._ensure_root()
            credential_path = self._credential_path(key)
            previous = None
            if credential_path.exists():
                try:
                    previous = credential_path.read_bytes()
                except OSError:
                    return None, (
                        'Astra Downloader could not read the existing sign-in safely. '
                        'Check permissions, then try again.'
                    )
            if not _write_protected_bytes(
                payload, credential_path, logger=self._logger
            ):
                return None, 'Astra Downloader could not store the sign-in safely.'
            record = dict(index.get(key) or {})
            record.update({
                'label': str(label or record.get('label') or key)[:120],
                'source': str(source)[:60],
                'cookies': max(0, int(record.get('cookies') or 0)),
                'importedAt': int(self._clock()),
                'earliestExpiry': max(0, int(record.get('earliestExpiry') or 0)),
                'authMethod': 'credentials',
            })
            index[key] = record
            if not self._save_index(index):
                if previous is None:
                    try:
                        credential_path.unlink(missing_ok=True)
                    except OSError as error:
                        self._log(
                            f'WARNING: orphaned site-login credential cleanup failed: {error}'
                        )
                elif not _write_protected_bytes(
                    previous, credential_path, logger=self._logger
                ):
                    self._log('WARNING: site-login credential rollback failed.')
                return None, (
                    'Astra Downloader stored the sign-in but could not record it, '
                    'so it was rolled back. Check disk space and permissions, then retry.'
                )
        self._log(f'Stored username/password sign-in for {key}')
        return {'site': key, 'credentialed': True}, None

    def import_netscape_text(self, site, text, *, source='cookies.txt', label=None):
        """Import a cookies.txt export, keeping only the target site's cookies."""
        if not isinstance(text, str) or not text.strip():
            return None, 'The cookie file is empty.'
        if len(text.encode('utf-8', 'ignore')) > MAX_SITE_LOGIN_TEXT_BYTES:
            return None, 'That cookie file is too large to be a browser export.'
        records = parse_netscape_cookies(text)
        if not records:
            return None, (
                'No cookies were found. Export the file in Netscape '
                'cookies.txt format, not JSON.'
            )
        return self.save_cookies(site, records, source=source, label=label)

    def remove(self, site):
        key = site_login_key(site)
        if not key:
            return False
        with self._lock:
            index = self._load_index()
            existed = key in index
            index.pop(key, None)
            self._save_index(index)
            for path, label in (
                (self._jar_path(key), 'jar'),
                (self._credential_path(key), 'credential'),
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as error:
                    self._log(f"WARNING: site-login {label} delete failed: {error}")
                    return False
        if existed:
            self._log(f"Removed the stored site sign-in for {key}")
        return existed

    def remove_with_undo(self, site):
        """Remove one sign-in while keeping a protected, session-only undo.

        Cookie and credential bytes stay in the store's protected directory. The returned
        token contains only the site name and non-secret index metadata, so a
        GUI undo action never has to hold or serialize cookie values.
        """
        key = site_login_key(site)
        if not key:
            return None, 'Enter a valid site address.'
        with self._lock:
            index = self._load_index()
            record = index.get(key)
            if not isinstance(record, dict):
                return None, 'That stored sign-in no longer exists.'
            undo_record = self._undo_record(record)
            self._ensure_root()
            jar = self._jar_path(key)
            credential_path = self._credential_path(key)
            token = uuid.uuid4().hex
            backup = self._undo_path(token)
            credential_backup = self._credential_undo_path(token)
            has_jar = jar.exists()
            has_credentials = credential_path.exists()
            try:
                if has_jar:
                    jar.replace(backup)
                if has_credentials:
                    credential_path.replace(credential_backup)
                updated = dict(index)
                updated.pop(key, None)
                if not self._save_index(updated):
                    if has_jar:
                        backup.replace(jar)
                    if has_credentials:
                        credential_backup.replace(credential_path)
                    return None, (
                        'Could not remove the sign-in safely. The stored session '
                        'was kept; check disk space and permissions, then retry.'
                    )
            except OSError as error:
                if has_jar and backup.exists() and not jar.exists():
                    try:
                        backup.replace(jar)
                    except OSError as rollback_error:
                        self._log(
                            f"WARNING: site-login undo rollback failed: {rollback_error}"
                        )
                if has_credentials and credential_backup.exists() and not credential_path.exists():
                    try:
                        credential_backup.replace(credential_path)
                    except OSError as rollback_error:
                        self._log(
                            f"WARNING: site-login credential undo rollback failed: {rollback_error}"
                        )
                self._log(f"WARNING: site-login removal failed: {error}")
                return None, 'Could not remove the stored sign-in safely.'
        self._log(f"Removed the stored site sign-in for {key}")
        return {
            'site': key,
            'token': token,
            'hasJar': has_jar,
            'hasCredentials': has_credentials,
            'record': undo_record,
        }, None

    def restore_removed(self, undo):
        """Restore the sign-in represented by a prior ``remove_with_undo``."""
        if not isinstance(undo, dict):
            return False, 'There is no sign-in removal to undo.'
        key = site_login_key(undo.get('site'))
        token = str(undo.get('token') or '')
        backup = self._undo_path(token)
        credential_backup = self._credential_undo_path(token)
        record = undo.get('record')
        if (
            not key or backup is None or credential_backup is None
            or not isinstance(record, dict)
        ):
            return False, 'That sign-in undo snapshot is invalid.'
        has_jar = bool(undo.get('hasJar'))
        has_credentials = bool(undo.get('hasCredentials'))
        with self._lock:
            index = self._load_index()
            if key in index:
                return False, 'That site already has a stored sign-in.'
            jar = self._jar_path(key)
            credential_path = self._credential_path(key)
            if not has_jar and jar.exists():
                return False, 'A file already exists for that site; the undo was not applied.'
            if not has_credentials and credential_path.exists():
                return False, 'A file already exists for that site; the undo was not applied.'
            if has_jar and not backup.exists():
                return False, 'The sign-in undo snapshot is no longer on disk.'
            if has_credentials and not credential_backup.exists():
                return False, 'The sign-in undo snapshot is no longer on disk.'
            try:
                if has_jar:
                    backup.replace(jar)
                if has_credentials:
                    credential_backup.replace(credential_path)
                updated = dict(index)
                updated[key] = self._undo_record(record)
                if not self._save_index(updated):
                    if has_jar:
                        jar.replace(backup)
                    if has_credentials:
                        credential_path.replace(credential_backup)
                    return False, (
                        'Could not restore the sign-in. The undo snapshot is still '
                        'available; check disk space and permissions, then retry.'
                    )
            except OSError as error:
                if has_jar and jar.exists() and not backup.exists():
                    try:
                        jar.replace(backup)
                    except OSError as rollback_error:
                        self._log(
                            f"WARNING: site-login restore rollback failed: {rollback_error}"
                        )
                if has_credentials and credential_path.exists() and not credential_backup.exists():
                    try:
                        credential_path.replace(credential_backup)
                    except OSError as rollback_error:
                        self._log(
                            f"WARNING: site-login credential restore rollback failed: {rollback_error}"
                        )
                self._log(f"WARNING: site-login restore failed: {error}")
                return False, 'Could not restore the stored sign-in safely.'
        self._log(f"Restored the stored site sign-in for {key}")
        return True, None

    def discard_removed(self, undo):
        """Drop a superseded session-only undo backup."""
        if not isinstance(undo, dict):
            return False
        backup = self._undo_path(undo.get('token'))
        credential_backup = self._credential_undo_path(undo.get('token'))
        if backup is None or credential_backup is None:
            return False
        try:
            backup.unlink(missing_ok=True)
            credential_backup.unlink(missing_ok=True)
            return True
        except OSError as error:
            self._log(f"WARNING: site-login undo cleanup failed: {error}")
            return False

    def export_jar_for_site(self, url, target_path):
        """Export the per-download jar and report which site it belongs to.

        Returns `(path, site_key)` so a caller does not have to look the key up
        again — `site_key_for_url` re-reads the index from disk on every call,
        and the scheduler needs both values for each queued download.
        """
        key = self.site_key_for_url(url)
        if not key:
            return None, ''
        return self._export_jar_for_key(key, target_path), key

    def export_jar_for(self, url, target_path):
        """Write a per-download copy of the stored jar, or None when unusable.

        A copy is used rather than the stored file itself because `--cookies`
        is also a write path: yt-dlp saves the jar back when it exits, so two
        concurrent downloads for one site would race on the stored file, and a
        redirect through a CDN would append foreign domains to it.
        """
        key = self.site_key_for_url(url)
        if not key:
            return None
        return self._export_jar_for_key(key, target_path)

    def _export_jar_for_key(self, key, target_path):
        if not self._jar_path(key).exists():
            return None
        try:
            text = self._jar_path(key).read_text(encoding='utf-8')
        except OSError as error:
            self._log(f"WARNING: stored site sign-in for {key} is unreadable: {error}")
            return None
        records = parse_netscape_cookies(text)
        now = self._clock()
        fresh = [
            record for record in records
            if cookie_domain_in_site(record.get('domain'), key)
            and (not record.get('expirationDate')
                 or int(record.get('expirationDate') or 0) > now)
        ]
        if not fresh:
            self._log(
                f"Stored site sign-in for {key} has no unexpired cookies; "
                "sign in again to refresh it."
            )
            return None
        return write_cookies_netscape(
            fresh,
            target_path,
            logger=self._logger,
            domain_filter=lambda domain: cookie_domain_in_site(domain, key),
        )


def build_browser_cookie_args(browser, profile=None):
    """Return the yt-dlp argument pair for reading a browser's cookie store."""
    name = str(browser or '').strip().lower()
    if name not in SITE_LOGIN_BROWSERS:
        return []
    target = name
    profile = str(profile or '').strip()
    if profile:
        # yt-dlp accepts BROWSER[:PROFILE]; ':' and '+' are its own separators
        # and must not arrive from a profile name.
        if any(character in profile for character in ':+"'):
            return []
        target = f"{name}:{profile}"
    return ['--cookies-from-browser', target]


def describe_browser_cookie_readiness(browser):
    """Return a preflight warning for browsers yt-dlp often cannot decrypt."""
    name = str(browser or '').strip().lower()
    if name in CHROMIUM_SITE_LOGIN_BROWSERS:
        return 'likely unreadable on Windows 127+; export cookies.txt instead'
    return ''


def build_site_login_credential_args(credentials):
    """Build yt-dlp login flags from an internal, already protected record."""
    if not isinstance(credentials, dict):
        return []
    username = credentials.get('username')
    password = credentials.get('password')
    if not SiteLoginStore._valid_credential_value(
        username, MAX_SITE_LOGIN_USERNAME_BYTES
    ) or not SiteLoginStore._valid_credential_value(
        password, MAX_SITE_LOGIN_PASSWORD_BYTES
    ):
        return []
    return ['--username', username, '--password', password]


def describe_browser_cookie_failure(output):
    """Explain a failed browser cookie read in the user's terms."""
    text = str(output or '').lower()
    if 'dpapi' in text or 'app-bound' in text or 'app bound' in text:
        return (
            'Chrome and Edge 127+ encrypt their cookie store so no outside '
            'program can read it. Export a cookies.txt file from the browser '
            'and import that instead.'
        )
    if 'could not find' in text and 'cookies' in text:
        return (
            'That browser profile has no cookie database. Pick the profile you '
            'actually browse with.'
        )
    if 'unsupported browser' in text:
        return 'That browser is not one yt-dlp can read cookies from.'
    if 'permission denied' in text or 'being used by another process' in text:
        return (
            'The browser is holding its cookie database open. Close the '
            'browser and try again, or import a cookies.txt export.'
        )
    return ''


def cleanup_stale_cookie_jars(install_dir, older_than_seconds=300, *, clock=time.time):
    """Remove crash-orphaned cookie jars, including fresh probe artifacts."""
    try:
        now = clock()
        for entry in Path(install_dir).glob('.cookies.*.txt'):
            try:
                fresh_probe = entry.name.startswith(('.cookies.probe.', '.cookies.import.'))
                if fresh_probe or now - entry.stat().st_mtime > older_than_seconds:
                    entry.unlink()
            except OSError:
                # reason: a concurrent cleanup or antivirus scan may own the stale file
                pass
    except OSError:
        # reason: a missing or inaccessible install directory has no stale jars to sweep
        pass


class YTDLPActivityRegistry:
    """Shared, conservative view of every live or reserved yt-dlp activity."""

    def __init__(self):
        self._lock = threading.Lock()
        self._activities = {}

    def reserve(self):
        token = object()
        with self._lock:
            self._activities[token] = None
        return token

    def attach(self, token, process):
        with self._lock:
            if token in self._activities:
                self._activities[token] = process

    def release(self, token):
        with self._lock:
            self._activities.pop(token, None)

    def release_process(self, process):
        """Release every registration belonging to a completed process."""
        if process is None:
            return
        with self._lock:
            for token, registered in list(self._activities.items()):
                if registered is process:
                    self._activities.pop(token, None)

    def begin_activity(self):
        return self.reserve()

    def end_activity(self, token):
        self.release(token)

    def active_count(self):
        with self._lock:
            for token, process in list(self._activities.items()):
                if process is None:
                    continue
                poll = getattr(process, 'poll', None)
                if not callable(poll):
                    self._activities.pop(token, None)
                    continue
                try:
                    finished = poll() is not None
                except Exception:
                    # An indeterminate process must keep the updater blocked.
                    finished = False
                if finished:
                    self._activities.pop(token, None)
            return len(self._activities)


def build_subprocess_env(deno_path, deno_dir=None, *, environ=None):
    """Build the allowlisted environment used for untrusted media subprocesses."""
    environ = os.environ if environ is None else environ
    env = {key: environ[key] for key in _SUBPROCESS_ENV_ALLOWLIST if key in environ}
    deno_path = Path(deno_path)
    if deno_path.exists():
        directory = Path(deno_dir) if deno_dir is not None else deno_path.parent
        env['PATH'] = str(directory) + os.pathsep + env.get('PATH', '')
    return env


def terminate_process_tree(proc, timeout=3, *, platform=None, runner=None,
                           creationflags=0, timeout_error=None, logger=None):
    """Terminate a media subprocess and its children without orphaning ffmpeg."""
    if not proc or proc.poll() is not None:
        return
    platform = sys.platform if platform is None else platform
    runner = subprocess.run if runner is None else runner
    timeout_error = subprocess.TimeoutExpired if timeout_error is None else timeout_error
    if platform == 'win32':
        try:
            runner(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                capture_output=True,
                creationflags=creationflags,
                timeout=5,
            )
            try:
                proc.wait(timeout=timeout)
            except Exception as error:
                _log_warning(logger, f"taskkill completed but process wait failed: {error}")
            return
        except Exception as error:
            _log_warning(logger, f"Windows taskkill failed: {error}")
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
            return
        except Exception as error:
            _log_warning(logger, f"process terminate fallback failed: {error}")
        try:
            proc.kill()
        except Exception as error:
            _log_warning(logger, f"process kill fallback failed: {error}")
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        return
    except timeout_error:
        _log_warning(logger, "process terminate timed out; trying kill fallback")
    except Exception as error:
        _log_warning(logger, f"process terminate failed: {error}")
    try:
        proc.kill()
    except Exception as error:
        _log_warning(logger, f"process kill fallback failed: {error}")


# Path segments that mean "this URL is a collection, not one video" on the
# non-YouTube sites yt-dlp supports (SoundCloud sets, Bandcamp/Vimeo albums,
# PeerTube playlists, podcast series…). Matched as whole segments, not
# substrings: `/video/playlist-of-hits` is one video whose slug happens to
# contain the word, and treating it as a playlist sent it into a folder named
# after a missing field. Deliberately narrow — anything unmatched is a single
# item downloaded with --no-playlist, so pasting a profile or subreddit link
# can never queue a hundred videos.
_PLAYLIST_PATH_SEGMENTS = frozenset({
    'playlist', 'playlists', 'sets', 'album', 'albums',
    'series', 'collection', 'collections',
})
_PLAYLIST_QUERY_KEYS = ('list', 'playlist', 'album', 'set')


def is_playlist_url(url):
    try:
        parsed = urlparse(url)
        params = {}
        for part in parsed.query.split('&'):
            if '=' in part:
                key, value = part.split('=', 1)
                params.setdefault(key.lower(), []).append(value)
        has_list = bool(params.get('list', [''])[0])
        has_video = bool(params.get('v', [''])[0])
        if has_list:
            # A YouTube watch URL carrying &list= stays a single video; that
            # has been the contract since v1.2 and the extension relies on it.
            return not has_video
        segments = [segment for segment in (parsed.path or '').lower().split('/') if segment]
        if any(segment in _PLAYLIST_PATH_SEGMENTS for segment in segments):
            return True
        return any(
            bool(params.get(key, [''])[0]) for key in _PLAYLIST_QUERY_KEYS
        )
    except Exception:
        return False


# The argv half of the format-preference vocabulary declared in config.py.
# A user token maps to one yt-dlp `--format-sort` field.
FORMAT_SORT_VIDEO_FIELDS = {
    'h264': 'vcodec:h264',
    'vp9': 'vcodec:vp9',
    'av1': 'vcodec:av01',
}
FORMAT_SORT_AUDIO_FIELDS = {
    'aac': 'acodec:aac',
    'opus': 'acodec:opus',
}


def build_format_sort_args(config):
    """Compile soft codec and frame-rate preferences into `--format-sort`.

    yt-dlp puts the fields it is given *ahead* of its own defaults, so naming
    `vcodec` alone would rank a 360p H.264 stream above a 1080p VP9 one. `res`
    is therefore always first: resolution stays the primary axis, which is
    what the quality picker expresses, and these preferences break the ties
    beneath it.

    The container remains a hard constraint handled by `build_video_format_args`
    — MP4 still forces H.264 and AAC so an editor imports the result without
    transcoding. These only order what that leaves open.
    """
    # Every caller passes something with `.get` — a plain dict from the tests
    # and a ConfigStore in the app; neither is required to be the other.
    read = getattr(config, 'get', None)
    if not callable(read):
        return []
    fields = []
    video = str(read('VideoCodecPreference') or 'auto').strip().lower()
    if video in FORMAT_SORT_VIDEO_FIELDS:
        fields.append(FORMAT_SORT_VIDEO_FIELDS[video])
    audio = str(read('AudioCodecPreference') or 'auto').strip().lower()
    if audio in FORMAT_SORT_AUDIO_FIELDS:
        fields.append(FORMAT_SORT_AUDIO_FIELDS[audio])
    try:
        frame_rate = int(read('PreferredFrameRate') or 0)
    except (TypeError, ValueError, OverflowError):
        frame_rate = 0
    if frame_rate > 0:
        # `~` is "closest to", so an unavailable 60fps falls back to what
        # exists rather than failing the format selection outright.
        fields.append(f'fps~{frame_rate}')
    if not fields:
        return []
    return ['--format-sort', ','.join(['res'] + fields)]


def build_impersonate_args(config, available_targets):
    """Compile the impersonation target, gated on what the binary really has.

    Verified against the installed yt-dlp: an unknown target does not warn,
    it raises YoutubeDLError and the download dies. So a configured value
    that the binary does not report is dropped rather than passed through —
    a stale setting must not break every download.
    """
    read = getattr(config, 'get', None)
    if not callable(read):
        return []
    target = str(read('ImpersonateTarget') or '').strip()
    if not target:
        return []
    known = {str(item) for item in (available_targets or ())}
    if target not in known:
        return []
    return ['--impersonate', target]


def build_network_workaround_args(config):
    """Compile the opt-in IP and geo workarounds, dropping unsafe values.

    Config values are normally sanitized before they reach a manager, but
    this builder is also used by probes and direct callers. Validate again at
    the subprocess boundary so a stale or hand-built config cannot inject an
    arbitrary yt-dlp argument.
    """
    read = getattr(config, 'get', None)
    if not callable(read):
        return []

    args = []
    force_ip = str(read('ForceIPVersion') or '').strip().lower()
    if force_ip == 'ipv4':
        args.append('--force-ipv4')
    elif force_ip == 'ipv6':
        args.append('--force-ipv6')

    source = str(read('SourceAddress') or '').strip()
    try:
        source = str(ipaddress.ip_address(source)) if source else ''
    except ValueError:
        source = ''
    if source:
        args += ['--source-address', source]

    xff = str(read('Xff') or '').strip()
    lowered_xff = xff.lower()
    if lowered_xff in {'default', 'never'}:
        xff = lowered_xff
    elif re.fullmatch(r'[A-Za-z]{2}', xff):
        xff = xff.upper()
    else:
        try:
            xff = str(ipaddress.ip_network(xff, strict=False)) if xff else ''
        except ValueError:
            xff = ''
    if xff:
        args += ['--xff', xff]

    geo_proxy = str(read('GeoVerificationProxy') or '').strip()
    try:
        parsed = urlparse(geo_proxy)
        schemes = {'http', 'https', 'socks', 'socks4', 'socks4a', 'socks5', 'socks5h'}
        valid_proxy = (
            bool(geo_proxy) and len(geo_proxy) <= 512
            and parsed.scheme.lower() in schemes and bool(parsed.netloc)
        )
    except ValueError:
        valid_proxy = False
    if valid_proxy:
        args += ['--geo-verification-proxy', geo_proxy]
    return args


# The argv half of the subtitle vocabulary declared in config.py. A user
# token maps to the yt-dlp flags that fetch that kind of track; a test pins
# the two vocabularies together so neither can gain a value the other does
# not know.
SUBTITLE_WRITE_FLAGS = {
    'prefer-manual': ('--write-subs', '--write-auto-subs'),
    'manual': ('--write-subs',),
    'auto': ('--write-auto-subs',),
}
SUBTITLE_CONVERT_FORMATS = frozenset({'srt', 'vtt', 'ass', 'lrc'})

# yt-dlp names each subtitle it writes on stdout. A subtitles-only run passes
# `--skip-download`, and the `after_move:` print hook the app normally learns
# the output path from does not fire without a media file — measured against
# the installed binary — so this line is the only report of what landed.
SUBTITLE_WRITTEN_RE = re.compile(
    r'^\[info\]\s+Writing video subtitles to:\s*(.+?)\s*$'
)


def build_subtitle_args(config, subtitles_only=False):
    """Compile the subtitle request: which tracks, which languages, what format.

    Measured against the installed yt-dlp on 2026-08-06 with a fixture holding
    a manual EN track, an auto EN track and an auto ES track:

        --write-subs --write-auto-subs  ->  en = MANUAL, es = auto
        --write-subs                    ->  en = MANUAL  (es absent)
        --write-auto-subs               ->  en = auto,   es = auto

    So yt-dlp merges the two catalogues per language with the creator's track
    winning; sending both never yielded two English files. `prefer-manual` is
    therefore the long-standing behaviour under a name, and the new capability
    is asking for exactly one kind — a viewer who wants only human-written
    captions, or only the machine transcript.

    A subtitles-only job fetches subtitles whether or not the embed switch is
    on, since embedding is the one thing it cannot do.
    """
    read = getattr(config, 'get', None)
    if not callable(read):
        return []
    embed = bool(read('EmbedSubs'))
    if not (embed or subtitles_only):
        return []
    mode = str(read('SubtitleMode') or '').strip().lower()
    if mode not in SUBTITLE_WRITE_FLAGS:
        mode = 'prefer-manual'
    args = []
    # Embedding needs a container to embed into, so it is meaningless for a
    # subtitles-only run and yt-dlp would warn about it on every job.
    if embed and not subtitles_only:
        args.append('--embed-subs')
    args += list(SUBTITLE_WRITE_FLAGS[mode])
    langs = re.sub(r'[^a-zA-Z0-9,\-]', '', str(read('SubLangs') or 'en')) or 'en'
    args += ['--sub-langs', langs]
    fmt = str(read('SubtitleFormat') or '').strip().lower()
    if fmt and fmt in SUBTITLE_CONVERT_FORMATS:
        args += ['--convert-subs', fmt]
    return args


def escape_ffmpeg_filter_value(value):
    """Escape a local path for an ffmpeg filter option.

    The process is spawned with an argv list, so shell quoting is neither
    needed nor wanted. The whisper filter still uses ``:`` as its option
    separator, though, which makes a Windows drive letter special. Convert
    separators to forward slashes and escape the filter punctuation twice.
    ffmpeg parses the filtergraph once before the option parser sees the
    value, so one backslash is consumed too early on Windows.
    """
    text = str(value or '').replace('\\', '/')
    for character in (':', ',', '[', ']', ';', "'"):
        text = text.replace(character, '\\\\' + character)
    return text


def local_subtitle_output_path(media_path):
    """Return the deterministic SRT sidecar path for one finished media file."""
    path = Path(media_path)
    if path.suffix:
        return path.with_suffix('.srt')
    return path.with_name(path.name + '.srt')


def local_subtitle_sidecar_exists(media_path):
    """Whether yt-dlp or an earlier transcription already wrote a sidecar."""
    path = Path(media_path)
    try:
        siblings = path.parent.iterdir()
    except OSError:
        return False
    stem = path.stem.casefold()
    formats = {'.srt', '.vtt', '.ass', '.lrc'}
    for candidate in siblings:
        try:
            if not candidate.is_file() or candidate.suffix.casefold() not in formats:
                continue
            name = candidate.name.casefold()
        except OSError:
            continue
        if name == f'{stem}{candidate.suffix.casefold()}' or name.startswith(f'{stem}.'):
            return True
    return False


def subtitle_language_for_transcription(config):
    """Choose the first configured language Whisper should transcribe."""
    read = getattr(config, 'get', None)
    raw = read('SubLangs') if callable(read) else ''
    for candidate in str(raw or '').split(','):
        code = candidate.strip().lower().replace('_', '-')
        if not code:
            continue
        # Whisper's filter accepts ISO language codes, not yt-dlp's regional
        # subtitle variants. The base code is the useful, deterministic
        # interpretation for values such as ``zh-Hans``.
        base = code.split('-', 1)[0]
        if re.fullmatch(r'[a-z]{2,3}', base):
            return base
    return 'auto'


def build_local_subtitle_args(ffmpeg_path, media_path, model_path,
                              output_path, language='auto'):
    """Build the server-owned ffmpeg Whisper command for one SRT sidecar."""
    model = escape_ffmpeg_filter_value(model_path)
    destination = escape_ffmpeg_filter_value(output_path)
    language = str(language or 'auto').strip().lower()
    if not re.fullmatch(r'[a-z]{2,3}', language):
        language = 'auto'
    filter_graph = (
        'aformat=sample_rates=16000:channel_layouts=mono,'
        f'whisper=model={model}:language={language}:queue=3:use_gpu=0:'
        f'destination={destination}:format=srt'
    )
    return [
        str(ffmpeg_path), '-hide_banner', '-nostdin', '-y',
        '-i', str(media_path), '-vn', '-af', filter_graph,
        '-progress', 'pipe:1', '-nostats', '-f', 'null', '-',
    ]


def build_whisper_audio_args(ffmpeg_path, media_path, output_path):
    """Extract the 16 kHz mono PCM WAV accepted by whisper.cpp."""
    return [
        str(ffmpeg_path), '-hide_banner', '-nostdin', '-y',
        '-i', str(media_path), '-vn', '-ac', '1', '-ar', '16000',
        '-c:a', 'pcm_s16le', str(output_path),
        '-progress', 'pipe:1', '-nostats',
    ]


def build_whisper_transcription_args(whisper_path, model_path, audio_path,
                                     output_base, language='auto',
                                     threads=4, max_len=42):
    """Build a deterministic whisper.cpp SRT invocation."""
    language = str(language or 'auto').strip().lower()
    if not re.fullmatch(r'[a-z]{2,3}', language) and language != 'auto':
        language = 'auto'
    try:
        threads = max(1, min(32, int(threads)))
    except (TypeError, ValueError, OverflowError):
        threads = 4
    try:
        max_len = max(0, min(200, int(max_len)))
    except (TypeError, ValueError, OverflowError):
        max_len = 42
    return [
        str(whisper_path), '-m', str(model_path), '-f', str(audio_path),
        '-l', language, '-t', str(threads), '-ml', str(max_len),
        '-osrt', '-of', str(output_base), '-ng',
    ]


def should_generate_local_subtitles(config, download):
    """Gate local transcription to opt-in video jobs with no subtitle track."""
    read = getattr(config, 'get', None)
    if not callable(read) or not bool(read('GenerateSubtitles')):
        return False
    if bool(getattr(download, 'audio_only', False)) or bool(
        getattr(download, 'subtitles_only', False)
    ):
        return False
    if bool(getattr(download, 'subtitle_written', False)):
        return False
    filename = str(getattr(download, 'filename', '') or '').strip()
    if not filename:
        return False
    media = Path(filename)
    try:
        if not media.is_file():
            return False
    except OSError:
        return False
    return not local_subtitle_sidecar_exists(media)


def build_playlist_bound_args(config):
    """Compile the bounds that keep a pasted playlist from queueing all of it.

    Verified against the installed binary on a real channel: `--max-downloads`
    stops the walk at the cap, and `--dateafter` and a `duration` match-filter
    each exclude items that fail them.

    `--download-archive` is deliberately absent and must stay absent — the
    archive-key mechanism in `subscriptions.py` is this project's answer to
    "already seen", and a second one makes a deliberate re-download report
    "already downloaded" and do nothing.
    """
    read = getattr(config, 'get', None)
    if not callable(read):
        return []

    def _int(key):
        try:
            return max(0, int(read(key) or 0))
        except (TypeError, ValueError, OverflowError):
            return 0

    args = []
    max_items = _int('PlaylistMaxItems')
    if max_items > 0:
        args += ['--max-downloads', str(max_items)]
    date_after = str(read('PlaylistDateAfter') or '').strip()
    if date_after:
        args += ['--dateafter', date_after]
    minimum = _int('PlaylistMinDurationSeconds')
    maximum = _int('PlaylistMaxDurationSeconds')
    clauses = []
    if minimum > 0:
        clauses.append(f'duration>={minimum}')
    if maximum > 0 and maximum >= minimum:
        clauses.append(f'duration<={maximum}')
    if clauses:
        # `& ` is yt-dlp's conjunction; a single filter string keeps the two
        # bounds one expression so neither can be dropped independently.
        args += ['--match-filters', ' & '.join(clauses)]
    return args


def build_video_format_args(container, quality):
    """Return editor-compatible yt-dlp format selection arguments."""
    height_filter = '' if quality == 'best' else f'[height<={quality}]'
    if container == 'mp4':
        v_pref, a_pref = '[vcodec^=avc1]', '[ext=m4a]'
    elif container == 'webm':
        v_pref, a_pref = '[vcodec^=vp9]', '[ext=webm]'
    else:
        v_pref = a_pref = ''

    if v_pref or a_pref:
        selector = (
            f'bestvideo{height_filter}{v_pref}+bestaudio{a_pref}/'
            f'bestvideo{height_filter}{v_pref}+bestaudio/'
            f'bestvideo{height_filter}+bestaudio{a_pref}/'
            f'bestvideo{height_filter}+bestaudio/'
            f'best{height_filter}{v_pref}/'
            f'best{height_filter}/best'
        )
    else:
        selector = f'bestvideo{height_filter}+bestaudio/best{height_filter}/best'
    return ['-f', selector, '--merge-output-format', container]


def download_error_payload(error_code, error=None, advice=None):
    meta = DOWNLOAD_FAILURE_RECOVERY.get(error_code, {})
    return {
        'error': error or meta.get('error') or 'Download failed.',
        'code': error_code,
        'error_code': error_code,
        'advice': advice or meta.get('advice') or 'Retry after checking Astra Downloader diagnostics.',
        'next_action': meta.get('next_action', 'retry'),
    }


def _format_byte_count(value):
    value = max(0.0, float(value or 0))
    units = ('B', 'KiB', 'MiB', 'GiB', 'TiB')
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024 or candidate == units[-1]:
            break
        value /= 1024
    return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'


def estimate_download_bytes(summary, *, audio_only=False, quality='best'):
    """Estimate a conservative media size from a format-probe summary.

    yt-dlp may select one muxed format or a separate video/audio pair. The
    larger of those two estimates is used so the preflight cannot promise a
    download that only fits when the extractor chooses the smaller path.
    Zero-sized or missing estimates are ignored; an unknown size returns 0
    and leaves the normal download path available.
    """
    if not isinstance(summary, dict):
        return 0
    formats = []
    for entry in summary.get('formats') or []:
        if not isinstance(entry, dict):
            continue
        try:
            size = int(entry.get('filesize') or 0)
        except (TypeError, ValueError, OverflowError):
            size = 0
        if size > 0:
            formats.append((entry, size))
    if not formats:
        return 0
    if audio_only:
        return max(
            size for entry, size in formats if entry.get('has_audio')
        ) if any(entry.get('has_audio') for entry, _size in formats) else 0

    eligible_video = []
    cap = None
    if str(quality or 'best') != 'best':
        try:
            cap = int(quality)
        except (TypeError, ValueError, OverflowError):
            cap = None
    for entry, size in formats:
        if not entry.get('has_video'):
            continue
        if cap is not None:
            try:
                height = int(entry.get('height') or 0)
            except (TypeError, ValueError, OverflowError):
                height = 0
            if height > cap:
                continue
        eligible_video.append((entry, size))
    if not eligible_video:
        return 0
    muxed = max(
        (size for entry, size in eligible_video if entry.get('has_audio')),
        default=0,
    )
    audio_sizes = [
        size for entry, size in formats
        if entry.get('has_audio') and not entry.get('has_video')
    ]
    separate = max(
        (size for entry, size in eligible_video if not entry.get('has_audio')),
        default=0,
    )
    if separate and audio_sizes:
        separate += max(audio_sizes)
    return max(muxed, separate)


def _check_one_download_volume(path, required, reserve, label):
    """Check one volume and identify the path that will consume its space."""
    target = Path(path or '.').expanduser()
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        free = int(shutil.disk_usage(str(target)).free)
    except (OSError, ValueError) as exc:
        return download_error_payload(
            'insufficient-disk-space',
            error=(
                f'Could not check free disk space on the {label} volume '
                f'before downloading: {exc}'
            ),
        )
    needed = required + reserve
    if free >= needed:
        return None
    return download_error_payload(
        'insufficient-disk-space',
        error=(
            f'Not enough free disk space on the {label} volume: the estimate '
            f'is {_format_byte_count(required)}, only {_format_byte_count(free)} '
            f'is free, and the download is short by '
            f'{_format_byte_count(needed - free)}.'
        ),
    )


def check_download_disk_space(
    path, required_bytes, *, reserve_bytes=DOWNLOAD_DISK_SPACE_RESERVE_BYTES,
    staging_path=None,
):
    """Check the output volume and, when supplied, the staging volume.

    The nearest existing ancestor is used so a not-yet-created folder is
    checked on the same volume. ``yt-dlp`` writes the estimate once to its
    private staging path and then moves it to the output path, so both volumes
    must have room. Disk-usage failures are fail-closed: an unknown free-space
    value must not turn a preflight into a false pass.
    """
    try:
        required = max(0, int(required_bytes or 0))
        reserve = max(0, int(reserve_bytes or 0))
    except (TypeError, ValueError, OverflowError):
        return download_error_payload(
            'insufficient-disk-space',
            error='Could not determine the download size before starting it.',
        )
    if required <= 0:
        return None
    checks = [('output', path)]
    if staging_path is not None:
        checks.append(('staging', staging_path))
    failures = [
        failure for label, target in checks
        if (failure := _check_one_download_volume(target, required, reserve, label))
    ]
    if not failures:
        return None
    if len(failures) == 1:
        return failures[0]
    return download_error_payload(
        'insufficient-disk-space',
        error=' '.join(failure['error'] for failure in failures),
    )


def summarize_ytdlp_formats(info):
    """Reduce a yt-dlp `-J` info dict to a concise, UI-ready format list:
    real available formats with id/ext/resolution/codec/size/audio-video flags.
    Storyboard (mhtml) and empty (no vcodec+acodec) entries are dropped."""
    if not isinstance(info, dict):
        return {'id': '', 'title': '', 'duration': 0, 'formats': []}
    out = []
    for f in (info.get('formats') or []):
        if not isinstance(f, dict) or f.get('format_id') is None:
            continue
        vcodec = f.get('vcodec') or 'none'
        acodec = f.get('acodec') or 'none'
        if f.get('ext') == 'mhtml' or (vcodec == 'none' and acodec == 'none'):
            continue
        out.append({
            'format_id': str(f.get('format_id')),
            'ext': f.get('ext') or '',
            'height': int(f.get('height') or 0),
            'width': int(f.get('width') or 0),
            'fps': f.get('fps') or 0,
            'vcodec': vcodec,
            'acodec': acodec,
            'has_video': vcodec != 'none',
            'has_audio': acodec != 'none',
            'filesize': int(f.get('filesize') or f.get('filesize_approx') or 0),
            'tbr': f.get('tbr') or 0,
            'format_note': (f.get('format_note') or '')[:80],
            # Carried so a SABR-only URL can be recognised before a run
            # starts, rather than after the options it voids are ignored.
            'protocol': (f.get('protocol') or '')[:32],
        })
    return {
        'id': str(info.get('id') or ''),
        'title': (info.get('title') or '')[:300],
        'duration': info.get('duration') or 0,
        'formats': out,
    }


# The quality picker's fixed ladder, highest first. A probe narrows it; it is
# never widened, so a probe that reports nothing leaves the offer untouched.
QUALITY_LADDER = ('2160', '1440', '1080', '720', '480')

# yt-dlp cannot apply --download-sections, --limit-rate or -N to a SABR
# stream (PR #13515). When a URL serves nothing else those options are void,
# and the failure taxonomy exists precisely to stop that going unexplained.
SABR_VOIDED_OPTIONS = (
    'clip ranges', 'the bandwidth cap', 'concurrent fragments',
)
SABR_LIMITED_NOTICE = (
    'This link only offers SABR streams. {options} do not apply to them and '
    'will be ignored.'
)


def describe_sabr_voided_options(options=SABR_VOIDED_OPTIONS):
    """Render the voided-option list as a sentence fragment."""
    items = [str(option) for option in options if str(option or '').strip()]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    return ', '.join(items[:-1]) + ' and ' + items[-1]


def sabr_only_formats(summary):
    """Whether every video format a probe found is a SABR stream.

    A URL that serves anything else is not limited — the non-SABR format is
    what gets downloaded — so this is deliberately all-or-nothing rather than
    a warning on the first SABR entry.
    """
    if not isinstance(summary, dict):
        return False
    video = [
        entry for entry in (summary.get('formats') or [])
        if isinstance(entry, dict) and entry.get('has_video')
    ]
    if not video:
        return False
    return all(
        'sabr' in str(entry.get('protocol') or '').lower() for entry in video
    )


def probed_video_heights(summary):
    """Distinct video heights a `list_formats` summary actually offers."""
    if not isinstance(summary, dict):
        return []
    heights = set()
    for entry in (summary.get('formats') or []):
        if not isinstance(entry, dict) or not entry.get('has_video'):
            continue
        try:
            height = int(entry.get('height') or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if height > 0:
            heights.add(height)
    return sorted(heights, reverse=True)


def quality_choices_for_heights(heights, ladder=QUALITY_LADDER):
    """Reduce the quality ladder to the rungs a probed URL can actually serve.

    A rung survives when the URL has something at or below it, so the cap it
    expresses is reachable. A video that tops out beneath the lowest rung —
    a 240p upload against a ladder starting at 480p — keeps no rungs at all:
    every one of them would name a resolution the link cannot serve, and
    'Best' is the only honest offer. An empty or unusable probe returns the
    whole ladder, so the picker never claims to know less than it did before.
    """
    usable = []
    for value in heights or []:
        try:
            usable.append(int(value))
        except (TypeError, ValueError, OverflowError):
            continue
    usable = [height for height in usable if height > 0]
    if not usable:
        return list(ladder)
    tallest = max(usable)
    return [rung for rung in ladder if int(rung) <= tallest]


def summarize_ytdlp_playlist(info, limit=PLAYLIST_PREVIEW_LIMIT):
    """Reduce a flat-playlist probe to a bounded, UI-safe preview."""
    if not isinstance(info, dict):
        return {
            'id': '', 'title': '', 'channel': '', 'total': 0,
            'truncated': False, 'items': [],
        }
    limit = max(1, min(PLAYLIST_PREVIEW_LIMIT, int(limit or PLAYLIST_PREVIEW_LIMIT)))
    raw_entries = info.get('entries') or []
    items = []
    for position, entry in enumerate(raw_entries[:limit], start=1):
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get('playlist_index') or position)
        except (TypeError, ValueError, OverflowError):
            index = position
        try:
            duration = max(0, int(float(entry.get('duration') or 0)))
        except (TypeError, ValueError, OverflowError):
            duration = 0
        items.append({
            'index': max(1, index),
            'id': str(entry.get('id') or '')[:120],
            'title': str(entry.get('title') or '(untitled)')[:300],
            'channel': str(
                entry.get('channel') or entry.get('uploader') or ''
            )[:200],
            'duration': duration,
            'availability': str(entry.get('availability') or '')[:40],
        })
    try:
        declared_total = max(0, int(info.get('playlist_count') or 0))
    except (TypeError, ValueError, OverflowError):
        declared_total = 0
    observed_total = len(raw_entries)
    total = max(declared_total, observed_total)
    return {
        'id': str(info.get('id') or '')[:120],
        'title': str(info.get('title') or '(untitled playlist)')[:300],
        'channel': str(info.get('channel') or info.get('uploader') or '')[:200],
        'total': total,
        'truncated': total > limit or observed_total > limit,
        'limit': limit,
        'items': items,
    }


def _redact_download_secrets(value, download):
    """Remove auth values before error text can reach history or diagnostics."""
    secrets = []
    credentials = getattr(download, '_credentials', None)
    if isinstance(credentials, dict):
        secrets.extend((credentials.get('username'), credentials.get('password')))
    secrets.append(getattr(download, '_video_password', ''))
    if isinstance(value, list):
        return [_redact_download_secrets(item, download) for item in value]
    text = str(value or '')
    for secret in secrets:
        if isinstance(secret, str) and secret:
            text = text.replace(secret, '[redacted]')
    return text


def _is_benign_failure_noise(line):
    """True for yt-dlp output lines that must never be surfaced as the failure
    reason. These are informational/warning/progress lines that routinely
    appear in the tail of a failed run and would otherwise masquerade as the
    cause (most notoriously the "your yt-dlp version is older than 90 days"
    nag and the "PO Token which was not provided" web-formats warning)."""
    low = str(line or '').strip().lower()
    if not low:
        return True
    if low.startswith('warning:'):
        return True
    if 'is older than' in low and 'yt-dlp' in low:
        return True
    if low.startswith('[download]') or low.startswith('[youtube]'):
        return True
    if low.startswith('mdlp'):  # our own progress prefix
        return True
    return False


_RETRY_AFTER_RE = re.compile(
    r'\bretry(?:[- ]after| in)\s*(?:[:=]\s*)?'
    r'(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)?',
    re.IGNORECASE,
)


def parse_retry_after_seconds(lines):
    """Extract a bounded Retry-After-style wait from yt-dlp output."""
    if isinstance(lines, str):
        text = lines
    else:
        text = '\n'.join(str(line or '') for line in (lines or []))
    for match in _RETRY_AFTER_RE.finditer(text):
        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            continue
        unit = str(match.group(2) or '').lower()
        if unit.startswith('hour') or unit.startswith('hr'):
            value *= 3600
        elif unit.startswith('minute') or unit.startswith('min'):
            value *= 60
        value = max(1, min(HOST_BACKOFF_MAX_SECONDS, math.ceil(value)))
        return int(value)
    return None


def classify_download_failure(message='', lines=None):
    # Two-pass: classify the definitive final error message first, and only
    # consult the output tail when the message alone is unrecognized. Without
    # this, a benign "PO Token which was not provided" WARNING anywhere in
    # the last 30 lines outranked the real cause (ffmpeg failure, connection
    # reset, disk full) carried by the message itself.
    primary = _classify_failure_text(str(message or '').lower())
    if primary:
        return primary
    text_parts = [str(message or '')]
    if lines:
        text_parts.extend(str(line or '') for line in lines)
    return _classify_failure_text(' '.join(text_parts).lower())


def _classify_failure_text(text):
    if not text.strip():
        return None
    if (
        'deno' in text
        and ('javascript runtime' in text or 'signature' in text or 'n/sig' in text
             or 'not found' in text or 'requires' in text)
    ):
        if any(marker in text for marker in ('stale', 'outdated', 'unsupported', 'too old', 'below')):
            return 'deno-runtime-unsupported'
        return 'deno-runtime-missing'
    if any(marker in text for marker in ('po token', 'po-token', 'potoken', 'po_token', 'bgutil')):
        if any(marker in text for marker in (
            'stale', 'expired', 'outdated', 'provider failed', 'failed to issue',
            'failed to fetch', 'unreachable', 'connection refused', 'invalid response',
        )):
            return 'po-provider-stale'
        return 'po-token-required'
    if any(marker in text for marker in (
        'sign in to confirm', 'please sign in', 'login required', 'not logged in',
        'confirm you are not a bot', 'cookies are required', 'use cookies',
        'authentication required',
        # The token-exempt client chain surfaces the age gate as a bare
        # LOGIN_REQUIRED/UNPLAYABLE playability status rather than prose.
        'login_required', 'age-restricted', 'age restricted',
        'inappropriate for some users', 'members-only', 'members only',
    )):
        return 'sign-in-required'
    if 'unplayable' in text:
        return 'sign-in-required'
    if 'ffmpeg' in text and any(marker in text for marker in (
        'not found', 'not installed', 'no such file', 'exited with code',
        'version', 'stale', 'unable to execute', 'failed',
    )):
        return 'ffmpeg-missing-or-stale'
    if any(marker in text for marker in (
        'sabr', 'no video formats', 'requested format is not available',
        'no formats available', 'only images are available',
    )):
        return 'sabr-limited'
    # Checked before the generic network bucket: a 429 is not a broken
    # connection and its fix is pacing, not retrying harder.
    if any(marker in text for marker in (
        'http error 429', 'too many requests', 'rate-limited', 'rate limited',
        'rate limit exceeded', 'throttled', 'throttling', 'slow down', 'slowdown',
    )):
        return 'rate-limited'
    if any(marker in text for marker in (
        'not available in your country', 'not available in your region',
        'not available in this region', 'geo-restricted', 'geo restricted',
        'geoblocked', 'geographical restriction', 'country restriction',
        'outside your region', 'available only in your',
        'available only for viewers in', 'only available in your',
    )):
        return 'geo-restricted'
    # Before the network bucket: a 403 is a refusal, not a broken connection,
    # and "check your firewall" is wrong advice for it.
    if any(marker in text for marker in (
        'http error 403', 'forbidden', 'cloudflare', 'blocked by',
    )):
        return 'blocked-by-site'
    if any(marker in text for marker in (
        'network is unreachable', 'failed to establish a new connection',
        'connection refused', 'connection reset', 'connection timed out',
        'timed out', 'temporary failure in name resolution', 'name or service not known',
        'dns', 'unable to download webpage', 'http error 502', 'http error 503',
        'http error 504',
    )):
        return 'network-unreachable'
    return None


# The old provider nudge is retained as a compatibility export, but there is
# no provider branch to recommend: plugin loading is disabled and every run
# uses the token-exempt client chain.
PO_PROVIDER_NUDGE_CODES = frozenset()
PO_PROVIDER_NUDGE = (
    'This install uses the plugin-free token-exempt YouTube client chain; '
    'age-gated or members-only videos may still require sign-in.'
)


def po_provider_nudge_advice(advice, error_code, provider_running):
    """Append the provider nudge when it is the missing piece."""
    if provider_running or error_code not in PO_PROVIDER_NUDGE_CODES:
        return advice
    advice = str(advice or '').strip()
    if 'pot-provider' in advice.lower() and 'no po-token provider is running' in advice.lower():
        return advice
    return f'{advice} {PO_PROVIDER_NUDGE}'.strip()


def apply_download_failure_classification(
    download, error_code, error=None, advice=None, provider_running=None,
):
    if not error_code:
        return
    payload = download_error_payload(error_code, error=error, advice=advice)
    download.error_code = payload['error_code']
    download.error_advice = po_provider_nudge_advice(
        payload['advice'], payload['error_code'], provider_running,
    ) if provider_running is not None else payload['advice']
    download.error_action = payload['next_action']
    download.error = payload['error']


class Download:
    def __init__(self, dl_id, url, audio_only=False, fmt=None, quality='best',
                 output_dir=None, title=None, referer=None, cookies_file=None,
                 requires_auth=False, created_at=None, queue_order=0, section=None,
                 playlist_items=None, subscription_id=None, archive_key=None,
                 subtitles_only=False, clock=None, profile_name=None):
        self._clock = clock or time.time
        self.id = dl_id
        self.url = url
        self.audio_only = audio_only
        self.format = fmt or ('mp3' if audio_only else 'mp4')
        self.quality = quality
        self.output_dir = output_dir
        self.title = title or "Unknown"
        self.referer = referer
        self.section = dict(section) if isinstance(section, dict) else None
        self.playlist_items = list(playlist_items) if playlist_items else None
        # A subtitles-only job skips the media entirely. It is a property of
        # the request, not of the settings, so two queued items can differ.
        self.subtitles_only = bool(subtitles_only)
        # Subscription linkage is metadata only.  Normal downloads leave both
        # fields empty, so the regular re-download behavior is unchanged.
        self.subscription_id = subscription_id
        self.archive_key = archive_key
        # None = automatic URL matching; an empty string is the explicit
        # one-off choice to bypass profiles for this queued item.
        self.profile_name = profile_name
        self.cookies_file = cookies_file
        # Which site the jar at `cookies_file` was built for: 'youtube' for the
        # extension's bridge, or a stored site-login key. A jar is only ever
        # passed to yt-dlp for the site it belongs to, so a caller cannot post
        # one site's URL with another site's cookies and have them sent.
        self.cookies_scope = ""
        self.requires_auth = bool(requires_auth)
        self._cookies = None
        # Credentials and one-off video passwords are deliberately ephemeral.
        # The durable queue serializes only request metadata, never secrets.
        self._credentials = None
        self._video_password = ""
        # yt-dlp's --force-overwrites includes --no-continue, so it must only be
        # sent on a run that is *meant* to start over. A retry, a resume, or a
        # download recovered after a restart is exactly the case where a `.part`
        # file may already hold most of the media — sending it there restarts a
        # 4 GB file from zero. Set on the paths that continue existing work.
        self.resume_partial = False
        # A subtitle-only retry keeps the completed media path and is durable so
        # a restart cannot silently turn it into a full media download.
        self.subtitle_retry = False
        self.status = "pending"
        self.progress = 0.0
        self.speed = ""
        self.eta = ""
        self.filename = ""
        # Set when yt-dlp reports a creator or auto-generated track. This is
        # separate from the sidecar check because --embed-subs can consume the
        # temporary subtitle file before the local-transcription stage runs.
        self.subtitle_written = False
        self.error = ""
        self.error_code = ""
        self.error_advice = ""
        self.error_action = ""
        self.start_time = float(created_at if created_at is not None else self._clock())
        self.queue_order = max(0, int(queue_order or 0))
        self.finished_time = None
        self.process = None

    def mark_terminal(self):
        if self.status in DOWNLOAD_TERMINAL_STATES and self.finished_time is None:
            self.finished_time = self._clock()

    def to_dict(self):
        payload = {
            "id": self.id, "url": self.url, "title": self.title,
            "status": self.status, "progress": round(self.progress, 1),
            "speed": self.speed, "eta": self.eta, "filename": self.filename,
            "error": self.error, "audioOnly": self.audio_only,
            "format": self.format, "quality": self.quality,
            "requiresAuth": self.requires_auth,
            "retryable": bool(
                (self.status == 'failed'
                 and self.error_code in DOWNLOAD_RETRYABLE_ERROR_CODES)
                or (self.status == 'complete'
                    and self.error_code in DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES)
            ),
        }
        if self.error_code:
            payload["error_code"] = self.error_code
            payload["advice"] = self.error_advice
            payload["next_action"] = self.error_action
        if self.section:
            payload["section"] = dict(self.section)
        if self.playlist_items:
            payload["playlistItems"] = list(self.playlist_items)
        if self.subscription_id:
            payload["subscriptionId"] = self.subscription_id
        if self.subtitles_only:
            payload["subtitlesOnly"] = True
        if self.profile_name is not None:
            payload["profileName"] = self.profile_name
        return payload


# Fields a rejected queue mutation has to put back.
#
# These were positional tuples, and the two lists drifted: retry()'s
# needs-auth rollback packed 15 fields and unpacked 14, so a failed queue
# write raised `ValueError: too many values to unpack` *instead of* rolling
# back, leaving the download stranded in needs-auth with its order bumped.
# Naming the fields makes the snapshot and the restore the same list by
# construction, so they cannot disagree again.
RESUME_ROLLBACK_FIELDS = (
    'status', 'error', 'error_code', 'error_advice', 'error_action',
    'requires_auth', '_cookies', 'resume_partial',
)
RETRY_ROLLBACK_FIELDS = (
    'status', 'progress', 'speed', 'eta', 'filename',
    'error', 'error_code', 'error_advice', 'error_action',
    'finished_time', 'start_time', 'queue_order',
    'requires_auth', '_cookies', 'resume_partial', 'subtitle_retry',
)
# start_download() reuses an existing needs-auth record rather than queueing a
# duplicate, so it overwrites the whole request and must be able to put the
# previous one back. This was the last positional tuple of the three.
AUTH_RECOVERY_ROLLBACK_FIELDS = (
    'audio_only', 'format', 'quality', 'output_dir',
    'title', 'referer', 'section', 'playlist_items', 'subtitles_only',
    'subscription_id', 'archive_key', 'requires_auth', 'status',
    'error', 'error_code', 'error_advice', 'error_action',
    '_credentials', '_video_password', 'profile_name',
)


def snapshot_download_fields(download, fields):
    """Capture the named attributes so a failed persist can undo the change."""
    return {name: getattr(download, name) for name in fields}


def restore_download_fields(download, snapshot):
    """Put a `snapshot_download_fields` result back onto the download."""
    for name, value in snapshot.items():
        setattr(download, name, value)


class DownloadQueueStore:
    """Schema-checked durable queue storage with injected JSON collaborators."""

    def __init__(self, *, path, reader, writer, logger, clean_text,
                 clean_path_text, schema_version=1, max_records=MAX_QUEUED_TOTAL):
        self.path = Path(path)
        self._reader = reader
        self._writer = writer
        self._logger = logger
        self._clean_text = clean_text
        self._clean_path_text = clean_path_text
        self.schema_version = int(schema_version)
        self.max_records = max(1, int(max_records))
        self.incompatibility_error = ""

    def load(self):
        raw = self._reader(self.path, {})
        if not isinstance(raw, dict):
            return {}, True
        stored_version = _stored_schema_version(raw.get('schemaVersion'))
        if raw and stored_version is not None and stored_version > self.schema_version:
            self.incompatibility_error = (
                "The pending queue was created by a newer, incompatible Astra "
                f"Downloader version (schema {stored_version}; this build reads "
                f"{self.schema_version}). Update Astra Downloader before "
                "resuming it."
            )
            self._logger(self.incompatibility_error)
            return raw, False
        if raw and (stored_version is None or stored_version < self.schema_version):
            previous = (
                str(stored_version) if stored_version is not None else "missing or invalid"
            )
            self._logger(
                f"Migrating download queue schema {previous} to "
                f"{self.schema_version} on the next save."
            )
        self.incompatibility_error = ""
        return raw, True

    def serialize(self, downloads, intake_paused=False):
        unfinished = sorted(
            (download for download in downloads if download.status in DOWNLOAD_ACTIVE_STATES),
            key=lambda download: (download.queue_order, download.start_time, download.id),
        )[:self.max_records]
        records = [{
            'id': self._clean_text(download.id, '', 120),
            'url': download.url,
            'title': self._clean_text(download.title, 'Unknown', 500) or 'Unknown',
            'audioOnly': bool(download.audio_only),
            'format': download.format,
            'quality': download.quality,
            'outputDir': self._clean_path_text(download.output_dir),
            'referer': download.referer,
            'requiresAuth': bool(download.requires_auth),
            **({'section': dict(download.section)} if download.section else {}),
            **({'playlistItems': list(download.playlist_items)}
               if download.playlist_items else {}),
            **({'subscriptionId': download.subscription_id}
               if download.subscription_id else {}),
            **({'archiveKey': download.archive_key}
               if download.archive_key else {}),
            **({'subtitlesOnly': True} if download.subtitles_only else {}),
            **({'subtitleRetry': True} if getattr(download, 'subtitle_retry', False) else {}),
            **({'profileName': getattr(download, 'profile_name', None)}
               if getattr(download, 'profile_name', None) is not None else {}),
            'createdAt': float(download.start_time),
            'order': int(download.queue_order),
        } for download in unfinished]
        return {
            'schemaVersion': self.schema_version,
            'intakePaused': bool(intake_paused),
            'downloads': records,
        }

    def save(self, downloads, intake_paused=False):
        try:
            self._writer(self.path, self.serialize(downloads, intake_paused))
            return True
        except Exception as error:
            self._logger(f"Download queue save failed: {error}")
            return False


_REQUIRED_MANAGER_DEPENDENCIES = frozenset({
    'CREATE_NEW_PROCESS_GROUP',
    'CREATE_NO_WINDOW',
    'FFMPEG_PATH',
    'INSTALL_DIR',
    'WHISPER_BIN_MIN_BYTES',
    'WHISPER_BIN_PATH',
    'WHISPER_MODEL_MIN_BYTES',
    'WHISPER_MODEL_PATH',
    'YTDLP_PATH',
    '_build_subprocess_env',
    'allowed_output_roots',
    'atomic_write_json',
    'build_javascript_runtime_args',
    'build_youtube_extractor_args',
    'clamp_int',
    'clean_path_text',
    'clean_text',
    'cleanup_stale_cookie_jars',
    'coerce_bool',
    'is_supported_media_url',
    'is_youtube_url',
    'load_json_file',
    'managed_binary_state',
    'normalize_output_dir',
    'normalize_sponsorblock_categories',
    'normalize_download_section',
    'normalize_playlist_items',
    'normalize_url',
    'probe_javascript_runtime',
    'probe_impersonate_targets',
    'probe_whisper_runtime',
    'normalize_impersonate_target',
    'quarantined_state_files',
    'spawn_media_process',
    'spawn_ytdlp',
    'terminate_process_tree',
    'write_persistent_log',
})


class DownloadManagerCore:
    ALLOWED_VIDEO_FMT = {'mp4', 'mkv', 'webm'}
    ALLOWED_AUDIO_FMT = {'mp3', 'm4a', 'opus', 'flac', 'wav'}
    ALLOWED_QUALITY = {'best', '2160', '1440', '1080', '720', '480'}
    FORMATS_PROBE_LIMIT = 2
    FORMATS_BUSY_MESSAGE = (
        'Astra Downloader is already looking up formats for other videos. '
        'Try again in a moment.'
    )
    PLAYLIST_BUSY_MESSAGE = (
        'Astra Downloader is already previewing media for other requests. '
        'Try again in a moment.'
    )

    def __init__(self, config, history, queue_path=None, *, dependencies, progress_updated, download_completed):
        missing = sorted(set(_REQUIRED_MANAGER_DEPENDENCIES) - set(dependencies))
        if missing:
            raise ValueError("Missing download manager dependencies: " + ", ".join(missing))
        self._dependencies = dict(dependencies)
        self.progress_updated = progress_updated
        self.download_completed = download_completed
        self.config = config
        self.history = history
        self.downloads = {}
        self._next_id = 0
        self._next_order = 0
        self._lock = threading.Lock()
        self._running_ids = set()
        # A rate limit belongs to the site's registrable domain, not to one
        # queue record. The map is session-only: a restart restores the queue
        # but never silently carries a stale server-imposed wait forward.
        self._host_backoffs = {}
        self._host_backoff_timer = None
        self._host_backoff_timer_due = 0.0
        # Bound concurrent `yt-dlp -J` format probes: each one holds a
        # waitress worker thread for up to 60s, and the pool only has 8 —
        # unbounded probes could starve /health, /status and /download.
        self._formats_gate = threading.Semaphore(self.FORMATS_PROBE_LIMIT)
        self._queue_path = Path(queue_path) if queue_path else None
        self._queue_store = (
            DownloadQueueStore(
                path=self._queue_path,
                reader=lambda path, fallback: self._dependencies['load_json_file'](path, fallback),
                writer=lambda path, data: self._dependencies['atomic_write_json'](path, data),
                logger=lambda message: self._dependencies['write_persistent_log'](message),
                clean_text=lambda *args, **kwargs: self._dependencies['clean_text'](*args, **kwargs),
                clean_path_text=lambda *args, **kwargs: self._dependencies['clean_path_text'](*args, **kwargs),
                schema_version=DOWNLOAD_QUEUE_SCHEMA_VERSION,
                max_records=MAX_QUEUED_TOTAL,
            )
            if self._queue_path is not None else None
        )
        # Signed-in downloads for every supported site. Rooted in the install
        # dir alongside the transient per-download jars so one sweep and one
        # ACL policy cover both.
        self.site_logins = SiteLoginStore(
            self._dependencies['INSTALL_DIR'](),
            logger=lambda message: self._dependencies['write_persistent_log'](message),
            # Same durability contract as the queue, config, history and
            # subscription stores: a torn index write fails closed and would
            # otherwise drop every stored sign-in at once.
            reader=lambda path, fallback: self._dependencies['load_json_file'](path, fallback),
            writer=lambda path, data: self._dependencies['atomic_write_json'](path, data),
        )
        self._persistence_error = ""
        # A completed download whose history entry could not be written. The
        # file is on disk and the download is genuinely complete, so the run
        # must not be failed — but silence here means the user's record of it
        # simply does not exist, which is how a full disk presents.
        self._history_error = ""
        # (requirement, url, requires_auth) -> (checked_at, (satisfied, message))
        self._precondition_cache = {}
        self._precondition_cache_lock = threading.Lock()
        # Slow JavaScript and browser-fingerprint probes are owned by the
        # background readiness worker. Keep only their immutable result here;
        # recovery checks must never turn a GUI refresh into a subprocess.
        self._readiness_lock = threading.Lock()
        self._readiness_snapshot = {
            'configuredRuntime': None,
            'runtime': None,
            'impersonateTargets': None,
            'updatedAt': 0.0,
            'error': '',
        }
        self._persistence_compatible = True
        self.intake_paused = False
        self._closing = False
        self.total_completed = 0
        # v1.2.0: sweep any cookie jars left by a previous crash before any
        # new download starts. Session cookies shouldn't outlive the process
        # that needed them.
        self._dependencies['cleanup_stale_cookie_jars']()
        self._restore_pending_queue()
        self._sweep_orphaned_download_intermediates()

    def update_readiness_snapshot(self, payload):
        """Publish probe results produced by the background readiness worker.

        The GUI receives the same payload for display, but it is deliberately
        not the owner of this update: the worker calls this method before its
        Qt signal crosses into the GUI thread. A malformed payload is treated
        as unavailable rather than allowing a stale positive result to linger.
        """
        payload = payload if isinstance(payload, dict) else {}
        runtime = payload.get('runtime')
        if not isinstance(runtime, dict):
            runtime = None
        raw_targets = payload.get('impersonateTargets')
        targets = None
        if isinstance(raw_targets, (list, tuple)):
            values = []
            for target in raw_targets:
                target = str(target or '').strip()
                if target and target not in values:
                    values.append(target)
            targets = tuple(values)
        configured_runtime = payload.get('configuredRuntime')
        if configured_runtime is not None:
            configured_runtime = str(configured_runtime).strip().lower() or None
        error = str(payload.get('error') or '')[:240]
        with self._readiness_lock:
            self._readiness_snapshot = {
                'configuredRuntime': configured_runtime,
                'runtime': dict(runtime) if runtime is not None else None,
                'impersonateTargets': targets,
                'updatedAt': time.time(),
                'error': error,
            }
        with self._precondition_cache_lock:
            self._precondition_cache.clear()

    def _effective_config_for_url(self, url, profile_name=None):
        """Return global settings overlaid with the URL's site profile."""
        profile = select_site_profile(
            url, self.config.get('SiteProfiles', []), profile_name
        )
        return (
            _ProfileConfigOverlay(self.config, profile)
            if profile else self.config
        )

    def _restore_pending_queue(self):
        """Restore unfinished work without starting it or restoring secrets.

        A crash can leave both running and pending records in the durable
        queue. Every record is intentionally converted to an explicit recovery
        state: unauthenticated work becomes ``paused`` and work that previously
        used browser cookies becomes ``needs-auth``. This prevents duplicate
        downloads from silently starting after an application restart.
        """
        if self._queue_store is None:
            return
        raw, compatible = self._queue_store.load()
        # An empty dict is what a corrupt file and an empty queue both look
        # like from here. The quarantine the read just performed is the only
        # thing that tells them apart, and discarding pending work in silence
        # is not the same event as starting with nothing.
        quarantined = {
            entry['path']
            for entry in self._dependencies['quarantined_state_files']()
        }
        if str(self._queue_store.path) in quarantined:
            self._persistence_error = (
                'The pending download queue could not be read and was set aside. '
                'Any downloads waiting in it were not restored.'
            )
        if not compatible:
            self._persistence_compatible = False
            self._persistence_error = (
                self._queue_store.incompatibility_error
                or 'The pending queue was created by an incompatible Astra Downloader version.'
            )
            self._dependencies['write_persistent_log'](
                'Download queue schema is incompatible; preserving the file without changes.'
            )
            return
        persisted_pause = self._dependencies['coerce_bool'](
            raw.get('intakePaused'), False
        )
        records = raw.get('downloads', [])
        if not isinstance(records, list):
            self.intake_paused = persisted_pause
            return

        restored = []
        seen_ids = set()
        allowed_roots = self._dependencies['allowed_output_roots'](self.config)
        for index, item in enumerate(records[:MAX_QUEUED_TOTAL]):
            if not isinstance(item, dict):
                continue
            url, err = self._dependencies['normalize_url'](item.get('url'))
            if err or not self._dependencies['is_supported_media_url'](url):
                continue
            output_dir = self._dependencies['clean_path_text'](item.get('outputDir'))
            try:
                if not output_dir or not Path(output_dir).expanduser().is_absolute():
                    continue
                resolved_output = Path(output_dir).expanduser().resolve()
                if not allowed_roots or not any(
                    resolved_output == root or resolved_output.is_relative_to(root)
                    for root in allowed_roots
                ):
                    continue
                output_dir = str(resolved_output)
            except (OSError, RuntimeError, ValueError):
                continue
            audio_only = self._dependencies['coerce_bool'](item.get('audioOnly'), False)
            if audio_only:
                raw_format = item.get('format')
                fmt = raw_format if isinstance(raw_format, str) and raw_format in self.ALLOWED_AUDIO_FMT else 'mp3'
            else:
                raw_format = item.get('format')
                fmt = raw_format if isinstance(raw_format, str) and raw_format in self.ALLOWED_VIDEO_FMT else 'mp4'
            raw_quality = item.get('quality')
            quality = raw_quality if isinstance(raw_quality, str) and raw_quality in self.ALLOWED_QUALITY else 'best'
            section, section_error = self._dependencies['normalize_download_section'](
                item.get('section')
            )
            if section_error:
                section = None
            playlist_items, playlist_error = self._dependencies['normalize_playlist_items'](
                item.get('playlistItems')
            )
            if playlist_error:
                playlist_items = None
            referer, _ = self._dependencies['normalize_url'](item.get('referer')) if item.get('referer') else (None, None)
            subscription_id = self._dependencies['clean_text'](item.get('subscriptionId'), '', 120) or None
            archive_key = self._dependencies['clean_text'](item.get('archiveKey'), '', 430) or None
            raw_profile_name = item.get('profileName')
            if raw_profile_name is None:
                profile_name = None
            else:
                profile_name = self._dependencies['clean_text'](
                    raw_profile_name, '', 80
                )
                if profile_name and not select_site_profile(
                    url, self.config.get('SiteProfiles', []), profile_name
                ):
                    # A profile deleted since the queue was written falls
                    # back to the current automatic match rather than
                    # stranding the recovered download.
                    profile_name = None
            dl_id = self._dependencies['clean_text'](item.get('id'), '', 120)
            if not dl_id or dl_id in seen_ids:
                self._next_id += 1
                dl_id = f"dl_{self._next_id}_{uuid.uuid4().hex[:6]}"
            seen_ids.add(dl_id)
            requires_auth = self._dependencies['coerce_bool'](item.get('requiresAuth'), False)
            self._next_order += 1
            try:
                created_at = float(item.get('createdAt') or time.time())
            except (TypeError, ValueError, OverflowError):
                created_at = time.time()
            if not math.isfinite(created_at) or created_at <= 0:
                created_at = time.time()
            dl = Download(
                dl_id,
                url,
                audio_only=audio_only,
                fmt=fmt,
                quality=quality,
                output_dir=output_dir,
                title=self._dependencies['clean_text'](item.get('title'), None, 500) or None,
                referer=referer,
                requires_auth=requires_auth,
                created_at=created_at,
                queue_order=self._next_order,
                section=section,
                playlist_items=playlist_items,
                subscription_id=subscription_id,
                archive_key=archive_key,
                subtitles_only=self._dependencies['coerce_bool'](
                    item.get('subtitlesOnly'), False
                ),
                profile_name=profile_name,
            )
            dl.subtitle_retry = self._dependencies['coerce_bool'](
                item.get('subtitleRetry'), False
            )
            dl.status = 'needs-auth' if requires_auth else 'paused'
            dl.error = (
                'Fresh sign-in is required before this recovered download can run.'
                if requires_auth else
                'Recovered after restart. Resume the queue when you are ready.'
            )
            # This download was interrupted mid-flight, so whatever yt-dlp had
            # already written is still on disk. Continue from it.
            dl.resume_partial = True
            restored.append(dl)

        if not restored:
            self.intake_paused = persisted_pause
            return
        with self._lock:
            for dl in restored:
                self.downloads[dl.id] = dl
            self.intake_paused = True
            # Normalize any legacy/running statuses on disk immediately. The
            # persisted form contains metadata only; cookie values and jar
            # paths are deliberately absent from _serialize_queue_locked().
            self._persist_locked()

    def _serialize_queue_locked(self):
        if self._queue_store is None:
            return {
                'schemaVersion': DOWNLOAD_QUEUE_SCHEMA_VERSION,
                'intakePaused': bool(self.intake_paused),
                'downloads': [],
            }
        return self._queue_store.serialize(self.downloads.values(), self.intake_paused)

    def _persist_locked(self):
        if self._queue_store is None or self._closing:
            return True
        if not self._persistence_compatible:
            return False
        if self._queue_store.save(self.downloads.values(), self.intake_paused):
            self._persistence_error = ''
            return True
        self._persistence_error = 'Could not save the pending download queue.'
        return False

    def _capacity_locked(self):
        running = len(self._running_ids)
        pending = sum(
            1 for dl in self.downloads.values()
            if dl.status in DOWNLOAD_PENDING_STATES
        )
        total = running + pending
        return {
            'running': running,
            'runningLimit': self._max_concurrent(),
            'pending': pending,
            'total': total,
            'totalLimit': MAX_QUEUED_TOTAL,
            'available': max(0, MAX_QUEUED_TOTAL - total),
            'intakePaused': bool(self.intake_paused),
        }

    def capacity(self):
        with self._lock:
            return self._capacity_locked()

    def _ordered_pending_locked(self):
        return sorted(
            (
                dl for dl in self.downloads.values()
                if dl.status in DOWNLOAD_PENDING_STATES
            ),
            key=lambda dl: (dl.queue_order, dl.start_time, dl.id),
        )

    def _auth_recovery_locked(self, url, cookies):
        if not cookies:
            return None
        return next((
            dl for dl in self._ordered_pending_locked()
            if dl.status == 'needs-auth' and dl.url == url
        ), None)

    def _launch_workers(self, downloads):
        for dl in downloads:
            with self._lock:
                if dl.status != 'queued':
                    # cancel() can land between _schedule() marking this item
                    # queued and this launch loop. The item is already
                    # terminal, and no worker thread will run its finally
                    # block, so release the reserved slot here.
                    self._running_ids.discard(dl.id)
                    dl._cookies = None
                    dl._credentials = None
                    dl._video_password = ""
                    skip_launch = True
                else:
                    skip_launch = False
                    subtitle_retry = bool(getattr(dl, 'subtitle_retry', False))
                    cookies = None if subtitle_retry else dl._cookies
                    dl._cookies = None
            if skip_launch:
                self._sweep_download_intermediates(dl)
                continue
            # A stored site sign-in stands in for the extension's cookie
            # bridge on every site the extension cannot reach. Request-supplied
            # cookies still win: they are fresher than anything on disk.
            site_login_used = False
            if not subtitle_retry and not cookies:
                jar_path = self._dependencies['INSTALL_DIR']() / f".cookies.{dl.id}.txt"
                # One lookup, not two: the stored site-login jar is the
                # fallback identity for every target, including YouTube
                # subscription downloads. Fresh extension cookies still win.
                exported, scope = self.site_logins.export_jar_for_site(dl.url, jar_path)
                if exported:
                    dl.cookies_file = exported
                    dl.cookies_scope = scope
                    site_login_used = True
                elif not dl._credentials:
                    # A stored username/password is the second identity
                    # source. Cookies win when both exist because yt-dlp can
                    # refresh a session jar, while credentials remain an
                    # explicit fallback for browsers it cannot read.
                    dl._credentials = self.site_logins.credentials_for_url(dl.url)
                    site_login_used = bool(dl._credentials)
            if not subtitle_retry and cookies:
                jar_path = self._dependencies['INSTALL_DIR']() / f".cookies.{dl.id}.txt"
                dl.cookies_file = write_cookies_netscape(
                    cookies, jar_path,
                    logger=self._dependencies['write_persistent_log'],
                )
                dl.cookies_scope = 'youtube' if dl.cookies_file else ''
            if not subtitle_retry and (cookies or site_login_used):
                cancelled_during_prep = False
                with self._lock:
                    if dl.status != 'queued':
                        # Cancelled while the jar was being written. cancel()
                        # could not unlink a jar it didn't know about yet, so
                        # clean it up here and release the slot.
                        self._running_ids.discard(dl.id)
                        jar = dl.cookies_file
                        dl.cookies_file = None
                        dl._credentials = None
                        dl._video_password = ""
                        if jar:
                            try:
                                Path(jar).unlink(missing_ok=True)
                            except Exception:
                                # reason: cancellation cleanup races with the jar writer and is idempotent
                                pass
                        cancelled_during_prep = True
                if cancelled_during_prep:
                    self._sweep_download_intermediates(dl)
                    continue
                # Only a requested cookie jar is mandatory. A stored site
                # sign-in that cannot be exported (none saved, all expired) is
                # not a failure — the download proceeds signed-out and, if the
                # site refuses, classify_download_failure raises
                # `sign-in-required` with the advice that names this store.
                if cookies and not dl.cookies_file:
                    with self._lock:
                        self._running_ids.discard(dl.id)
                        dl.status = 'failed'
                        apply_download_failure_classification(dl, 'cookie-jar-failed')
                        dl.mark_terminal()
                        self._persist_locked()
                    self._sweep_download_intermediates(dl)
                    self.progress_updated.emit()
                    self.download_completed.emit(dl.id)
                    continue
            try:
                thread = threading.Thread(
                    target=self._worker_entry,
                    args=(dl,),
                    daemon=True,
                )
                thread.start()
            except Exception as exc:
                with self._lock:
                    self._running_ids.discard(dl.id)
                    dl.status = 'failed'
                    dl.error = 'Could not start the download worker. Retry the download.'
                    dl.error_code = 'worker-start-failed'
                    dl.mark_terminal()
                    if dl.cookies_file:
                        try:
                            Path(dl.cookies_file).unlink(missing_ok=True)
                        except Exception:
                            # reason: the worker failed before cleanup and the jar may already be gone
                            pass
                        dl.cookies_file = None
                    dl._credentials = None
                    dl._video_password = ""
                    self._persist_locked()
                self._dependencies['write_persistent_log'](f"Download worker {dl.id} failed to start: {exc}")
                self._sweep_download_intermediates(dl)
                self.progress_updated.emit()
                self.download_completed.emit(dl.id)
        # A worker preparation failure frees a slot synchronously.
        if downloads and not self._closing:
            self._schedule()

    def _worker_entry(self, dl):
        escaped = False
        try:
            self._run_download(dl)
        except Exception as exc:
            # _run_download is defensive, but keep the scheduler correct if a
            # future implementation lets an exception escape its boundary.
            if dl.status not in DOWNLOAD_TERMINAL_STATES:
                dl.status = 'failed'
                dl.error = 'Unexpected download worker failure. Check Astra Downloader logs.'
                dl.mark_terminal()
            escaped = True
            self._dependencies['write_persistent_log'](
                f"Download worker {dl.id} escaped unexpectedly: "
                f"{_redact_download_secrets(exc, dl)}"
            )
        finally:
            with self._lock:
                self._running_ids.discard(dl.id)
                # Never keep a password in the live queue after the process
                # that needed it has finished.
                dl._credentials = None
                dl._video_password = ""
                if dl.status in DOWNLOAD_RUNNING_STATES:
                    dl.status = 'failed'
                    dl.error = 'Download worker stopped before reporting a result.'
                    dl.mark_terminal()
                terminal_cleanup = escaped and dl.status in DOWNLOAD_TERMINAL_STATES
                self._persist_locked()
            if terminal_cleanup:
                self._sweep_download_intermediates(dl)
            if not self._closing:
                self._schedule()
                # Queue drained to idle: this is the race-free window to
                # actually apply a yt-dlp update that was deferred while
                # downloads were running. No yt-dlp.exe is in flight, so the
                # staged binary can be swapped in without a file-in-use race.
                if self.active_count() == 0:
                    self.maybe_refresh_ytdlp('queue-idle')

    @staticmethod
    def _host_backoff_key(url):
        """Return the registrable domain used to isolate throttled hosts."""
        try:
            host = (urlparse(str(url or '')).hostname or '').strip().lower()
        except ValueError:
            host = ''
        if not host:
            return ''
        # `registrable_domain` is intentionally small and is not an IP parser;
        # keep public IPs and IPv6 literals intact rather than collapsing an
        # address into the last two labels.
        if ':' in host or re.fullmatch(r'\d+(?:\.\d+){3}', host):
            return host
        return registrable_domain(host)

    def _host_backoff_remaining_locked(self, url):
        key = self._host_backoff_key(url)
        if not key:
            return 0.0
        state = self._host_backoffs.get(key)
        if not state:
            return 0.0
        remaining = float(state.get('until', 0.0)) - time.monotonic()
        if remaining <= 0:
            self._host_backoffs.pop(key, None)
            return 0.0
        return remaining

    def host_backoff_remaining(self, url):
        """Return the live host pause in seconds for a queue item's URL."""
        with self._lock:
            return self._host_backoff_remaining_locked(url)

    def _pacing_jitter_multiplier(self):
        try:
            percentage = int(self.config.get('PacingJitterPercent', 0) or 0)
        except (TypeError, ValueError, OverflowError):
            percentage = 0
        percentage = max(0, min(100, percentage))
        if not percentage:
            return 1.0
        spread = percentage / 100.0
        return random.uniform(max(0.0, 1.0 - spread), 1.0 + spread)

    def _record_host_backoff(self, url, retry_after_seconds=None):
        """Pause one registrable domain after a classified throttle failure."""
        key = self._host_backoff_key(url)
        if not key:
            return 0.0
        now = time.monotonic()
        try:
            explicit = float(retry_after_seconds)
        except (TypeError, ValueError, OverflowError):
            explicit = 0.0
        explicit = (
            max(1.0, min(float(HOST_BACKOFF_MAX_SECONDS), explicit))
            if explicit > 0 else None
        )
        with self._lock:
            previous = self._host_backoffs.get(key)
            previous_until = float(previous.get('until', 0.0)) if previous else 0.0
            active = previous_until > now
            failures = int(previous.get('failures', 0) or 0) + 1 if active else 1
            if explicit is not None:
                retry_after = explicit
            else:
                exponent = min(10, max(0, failures - 1))
                retry_after = min(
                    float(HOST_BACKOFF_MAX_SECONDS),
                    float(HOST_BACKOFF_BASE_SECONDS) * (2 ** exponent),
                )
            delay = max(1.0, retry_after * self._pacing_jitter_multiplier())
            until = max(previous_until if active else 0.0, now + delay)
            self._host_backoffs[key] = {
                'until': until,
                'retry_after': retry_after,
                'failures': failures,
            }
            # The map is bounded even if a long-running session encounters a
            # large number of unrelated hosts. Expired entries are cheaper to
            # discard now than to make every scheduler pass carry them.
            for old_key, state in tuple(self._host_backoffs.items()):
                if float(state.get('until', 0.0)) <= now:
                    self._host_backoffs.pop(old_key, None)
            if len(self._host_backoffs) > HOST_BACKOFF_MAX_ENTRIES:
                oldest = sorted(
                    self._host_backoffs.items(),
                    key=lambda item: float(item[1].get('until', 0.0)),
                )
                for old_key, _state in oldest[:-HOST_BACKOFF_MAX_ENTRIES]:
                    self._host_backoffs.pop(old_key, None)
            remaining = max(0.0, until - now)
        self._dependencies['write_persistent_log'](
            f"Host backoff for {key}: retry after {math.ceil(retry_after)}s "
            f"(scheduled {math.ceil(remaining)}s, failure {failures})"
        )
        self._arm_host_backoff_wakeup(remaining)
        return remaining

    def _arm_host_backoff_wakeup(self, delay):
        """Wake the scheduler at the earliest blocked-host expiry."""
        try:
            delay = max(0.05, float(delay))
        except (TypeError, ValueError, OverflowError):
            return
        deadline = time.monotonic() + delay
        previous = None
        with self._lock:
            if self._closing:
                return
            current = self._host_backoff_timer
            if current is not None and current.is_alive():
                if self._host_backoff_timer_due <= deadline + 0.05:
                    return
                previous = current
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(delay, self._wake_host_backoff)
            timer.daemon = True
            self._host_backoff_timer = timer
            self._host_backoff_timer_due = deadline
        try:
            timer.start()
        except RuntimeError:
            with self._lock:
                if self._host_backoff_timer is timer:
                    self._host_backoff_timer = None
                    self._host_backoff_timer_due = 0.0

    def _wake_host_backoff(self):
        current = threading.current_thread()
        with self._lock:
            if self._host_backoff_timer is not current:
                return
            self._host_backoff_timer = None
            self._host_backoff_timer_due = 0.0
            closing = self._closing
        if not closing:
            self._schedule()

    def _max_concurrent(self):
        """Configured simultaneous-download limit, clamped. Defaults to the
        historical MAX_CONCURRENT (3) when unset."""
        try:
            return self._dependencies['clamp_int'](
                self.config.get('MaxConcurrentDownloads', MAX_CONCURRENT),
                MAX_CONCURRENT, 1, 10,
            )
        except Exception:  # noqa: BLE001
            return MAX_CONCURRENT

    def _schedule(self):
        to_start = []
        wake_delay = None
        with self._lock:
            if self._closing or self.intake_paused:
                return
            available = max(0, self._max_concurrent() - len(self._running_ids))
            if available <= 0:
                return
            # Do not slice before checking the host pause: a throttled item
            # at the head of the queue must not hide work for another site.
            for dl in self._ordered_pending_locked():
                if dl.status != 'pending':
                    continue
                remaining = self._host_backoff_remaining_locked(dl.url)
                if remaining > 0:
                    wake_delay = remaining if wake_delay is None else min(wake_delay, remaining)
                    continue
                dl.status = 'queued'
                self._running_ids.add(dl.id)
                to_start.append(dl)
                if len(to_start) >= available:
                    break
        if wake_delay is not None:
            self._arm_host_backoff_wakeup(wake_delay)
        if to_start:
            self.progress_updated.emit()
            self._launch_workers(to_start)

    def _reclaim_terminal_records_locked(self, required_slots=1):
        """Free only terminal records when the bounded queue needs capacity."""
        overflow = len(self.downloads) + max(0, required_slots) - MAX_QUEUED_TOTAL
        if overflow <= 0:
            return 0
        terminal = sorted(
            (
                (getattr(download, 'finished_time', None) or download.start_time, dl_id)
                for dl_id, download in self.downloads.items()
                if download.status in DOWNLOAD_TERMINAL_STATES
            ),
            key=lambda item: item[0],
        )
        removed = 0
        for _finished_at, dl_id in terminal[:overflow]:
            del self.downloads[dl_id]
            removed += 1
        return removed

    def start_download(self, url, audio_only=False, fmt=None, quality=None,
                       output_dir=None, title=None, referer=None, cookies=None,
                       section=None, playlist_items=None, subscription_id=None,
                       archive_key=None, subtitles_only=False, video_password=None,
                       profile_name=None):
        url, err = self._dependencies['normalize_url'](url)
        if err:
            return None, err
        # Every entry point lands here — HTTP routes, the GUI quick-download
        # box, the clipboard grabber, and the subscription scheduler — so the
        # private-network denylist is enforced once, at the queue boundary,
        # instead of once per caller.
        if not self._dependencies['is_supported_media_url'](url):
            return None, (
                'That address is on a private, loopback, or link-local network. '
                'Astra Downloader only downloads from public sites.'
            )
        if profile_name is not None:
            profile_name = self._dependencies['clean_text'](profile_name, '', 80)
            if profile_name and not select_site_profile(
                url, self.config.get('SiteProfiles', []), profile_name
            ):
                return None, f"Unknown site profile: {profile_name}."
        selected_profile = select_site_profile(
            url, self.config.get('SiteProfiles', []), profile_name
        )
        audio_only = self._dependencies['coerce_bool'](audio_only, False)
        section, section_error = self._dependencies['normalize_download_section'](section)
        if section_error:
            return None, section_error
        playlist_items, playlist_error = self._dependencies['normalize_playlist_items'](
            playlist_items
        )
        if playlist_error:
            return None, playlist_error
        playlist_request = is_playlist_url(url)
        if playlist_items and not playlist_request:
            return None, "Playlist item selection requires a playlist URL."
        if section and playlist_request:
            return None, "Clip ranges are available for single-video downloads only."
        if video_password is None:
            video_password = ""
        elif not isinstance(video_password, str):
            return None, "Video password must be text."
        elif video_password and not SiteLoginStore._valid_credential_value(
            video_password, MAX_SITE_LOGIN_PASSWORD_BYTES
        ):
            return None, "Video password must be between 1 and 4096 UTF-8 bytes."
        if video_password and playlist_request:
            return None, "Video passwords are available for single-link downloads only."

        # No update trigger here: firing before the download was enqueued let
        # the updater pass its active_count()==0 idle gate and then race the
        # yt-dlp.exe this very download spawns milliseconds later — the
        # binary swap hit file-in-use, failed, and re-downloaded the whole
        # release at the next window. The server-start hook plus the
        # queue-idle hook in _worker_entry (fires after every drain,
        # including failures) cover staleness without a race.

        with self._lock:
            self._reclaim_terminal_records_locked()
            auth_recovery = self._auth_recovery_locked(url, cookies)
            if not auth_recovery and self._capacity_locked()['total'] >= MAX_QUEUED_TOTAL:
                return None, (
                    f"Download queue is full ({MAX_QUEUED_TOTAL}/{MAX_QUEUED_TOTAL}). "
                    "Cancel a pending item or wait for a running download to finish, then retry."
                )

        # Sanitize format/quality
        if selected_profile:
            if fmt is None:
                fmt = selected_profile.get(
                    'AudioFormat' if audio_only else 'VideoFormat'
                ) or None
            if quality is None:
                quality = selected_profile.get('Quality') or None
        if audio_only:
            fmt = fmt if isinstance(fmt, str) and fmt in self.ALLOWED_AUDIO_FMT else 'mp3'
        else:
            fmt = fmt if isinstance(fmt, str) and fmt in self.ALLOWED_VIDEO_FMT else 'mp4'
        quality = quality if isinstance(quality, str) and quality in self.ALLOWED_QUALITY else 'best'

        # Output directory — path-confined to the server's configured roots.
        # A compromised extension or malicious content script would otherwise
        # be able to hand us any absolute path and watch us mkdir + write
        # there. See HARDENING.md Pass 6 S2 (outputDir allowlist).
        client_supplied_output = bool(output_dir)
        if not output_dir:
            if audio_only and self.config.get("AudioDownloadPath"):
                output_dir = self.config.get("AudioDownloadPath")
            else:
                output_dir = self.config.get("DownloadPath", default_download_path())
        # Only enforce confinement when the client supplied the path. The
        # fallback defaults above are always inside the allowlist by
        # construction, and enforcing for them would create a chicken-and-egg
        # when the user is first setting DownloadPath from the Settings UI.
        roots = self._dependencies['allowed_output_roots'](self.config) if client_supplied_output else None
        output_dir, err = self._dependencies['normalize_output_dir'](
            output_dir,
            self.config.get("DownloadPath", default_download_path()),
            allowed_roots=roots,
        )
        if err:
            return None, err
        title = self._dependencies['clean_text'](title, None, 500) or None
        referer, _ = self._dependencies['normalize_url'](referer) if referer else (None, None)
        subscription_id = self._dependencies['clean_text'](subscription_id, '', 120) or None
        archive_key = self._dependencies['clean_text'](archive_key, '', 430) or None
        subtitles_only = self._dependencies['coerce_bool'](subtitles_only, False)

        with self._lock:
            # Re-check capacity under the lock. The first check released the
            # lock for URL/output normalization, so concurrent requests could
            # otherwise overfill the durable queue.
            self._reclaim_terminal_records_locked()
            auth_recovery = self._auth_recovery_locked(url, cookies)
            if not auth_recovery and self._capacity_locked()['total'] >= MAX_QUEUED_TOTAL:
                return None, (
                    f"Download queue is full ({MAX_QUEUED_TOTAL}/{MAX_QUEUED_TOTAL}). "
                    "Cancel a pending item or wait for a running download to finish, then retry."
                )
            recovery_previous = None
            if auth_recovery:
                dl = auth_recovery
                dl_id = dl.id
                recovery_previous = snapshot_download_fields(
                    dl, AUTH_RECOVERY_ROLLBACK_FIELDS
                )
                dl.audio_only = audio_only
                dl.format = fmt
                dl.quality = quality
                dl.output_dir = output_dir
                dl.title = title or dl.title
                dl.referer = referer
                dl.section = dict(section) if section else None
                dl.playlist_items = list(playlist_items) if playlist_items else None
                dl.subtitles_only = subtitles_only
                dl.subscription_id = subscription_id
                dl.archive_key = archive_key
                dl.profile_name = profile_name
                dl.requires_auth = True
                dl._cookies = list(cookies)
                dl._credentials = None
                dl._video_password = video_password
                dl.status = 'pending'
                dl.error = ''
                dl.error_code = ''
                dl.error_advice = ''
                dl.error_action = ''
            else:
                self._next_id += 1
                dl_id = f"dl_{self._next_id}_{uuid.uuid4().hex[:6]}"
                self._next_order += 1
                dl = Download(
                    dl_id,
                    url,
                    audio_only,
                    fmt,
                    quality,
                    output_dir,
                    title,
                    referer,
                    requires_auth=bool(cookies),
                    queue_order=self._next_order,
                    section=section,
                    playlist_items=playlist_items,
                    subscription_id=subscription_id,
                    archive_key=archive_key,
                    subtitles_only=subtitles_only,
                    profile_name=profile_name,
                )
                dl._cookies = list(cookies) if cookies else None
                dl._video_password = video_password
                self.downloads[dl_id] = dl
            if not self._persist_locked():
                if not auth_recovery:
                    del self.downloads[dl_id]
                else:
                    restore_download_fields(dl, recovery_previous)
                dl._cookies = None
                if not self._persistence_compatible:
                    # Disk/permission advice is wrong for a schema mismatch;
                    # surface the real cause so the user can recover.
                    return None, self._persistence_error
                return None, (
                    "Could not save the pending download queue. Check disk space and "
                    "permissions, then retry."
                )

        self._schedule()

        return dl_id, None

    def _recut_section(self, dl, env):
        """Replace a completed file with a frame-accurate ffmpeg re-cut."""
        if not dl.section:
            return True
        input_path = Path(dl.filename or "")
        try:
            input_path = input_path.resolve(strict=True)
            output_root = Path(dl.output_dir).resolve(strict=True)
            if input_path != output_root and not input_path.is_relative_to(output_root):
                raise ValueError("download output escaped its configured directory")
        except (OSError, RuntimeError, ValueError) as error:
            dl.status = "failed"
            dl.error = f"Accurate clip could not locate the downloaded file: {error}"
            return False

        start = float(dl.section["start"])
        duration = float(dl.section["end"]) - start
        temporary = input_path.with_name(
            f".{input_path.stem}.astra-section-{uuid.uuid4().hex}{input_path.suffix}"
        )
        ffmpeg = str(self._dependencies['FFMPEG_PATH']())
        args = [
            ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y',
            '-i', str(input_path), '-ss', f'{start:.3f}', '-t', f'{duration:.3f}',
            '-map_metadata', '0',
        ]
        suffix = input_path.suffix.lower()
        if dl.audio_only:
            audio_codec_args = {
                '.mp3': ['-c:a', 'libmp3lame', '-q:a', '0'],
                '.m4a': ['-c:a', 'aac', '-b:a', '256k'],
                '.opus': ['-c:a', 'libopus', '-b:a', '192k'],
                '.flac': ['-c:a', 'flac'],
                '.wav': ['-c:a', 'pcm_s16le'],
            }
            args += ['-map', '0:a:0', '-vn']
            args += audio_codec_args.get(suffix, ['-c:a', 'aac', '-b:a', '256k'])
        elif suffix == '.webm':
            args += [
                '-map', '0:v:0?', '-map', '0:a:0?', '-map', '0:s?',
                '-c:v', 'libvpx-vp9', '-crf', '24', '-b:v', '0',
                '-c:a', 'libopus', '-b:a', '192k', '-c:s', 'webvtt',
            ]
        else:
            args += [
                '-map', '0:v:0?', '-map', '0:a:0?', '-map', '0:s?',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                '-c:a', 'aac', '-b:a', '192k',
                '-c:s', 'mov_text' if suffix == '.mp4' else 'copy',
            ]
            if suffix == '.mp4':
                args += ['-movflags', '+faststart']
        args.append(str(temporary))

        dl.status = 'trimming'
        dl.speed = ''
        dl.eta = ''
        self.progress_updated.emit()
        proc = None
        try:
            proc = self._dependencies['spawn_media_process'](
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=(
                    self._dependencies['CREATE_NO_WINDOW']
                    | self._dependencies['CREATE_NEW_PROCESS_GROUP']
                ),
                env=env,
            )
            dl.process = proc
            output, _ = proc.communicate()
            if dl.status == 'cancelled':
                return False
            if proc.returncode != 0 or not temporary.is_file():
                detail = " ".join(str(output or "").split())[-220:]
                dl.status = 'failed'
                dl.error = (
                    "ffmpeg could not create the requested clip."
                    + (f" {detail}" if detail else "")
                )
                apply_download_failure_classification(
                    dl, 'ffmpeg-missing-or-stale', error=dl.error
                )
                return False
            os.replace(temporary, input_path)
            dl.filename = str(input_path)
            return True
        finally:
            dl.process = None
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # reason: section scratch cleanup is best-effort after ffmpeg exits
                pass
            if proc is not None and proc.poll() is None:
                try:
                    self._dependencies['terminate_process_tree'](proc)
                except Exception as error:
                    self._dependencies['write_persistent_log'](
                        f"WARNING: section ffmpeg termination failed: {error}"
                    )

    def _converted_subtitle_path(self, written_path):
        """Map a written subtitle to what `--convert-subs` renamed it to.

        yt-dlp announces the track it downloaded and only then converts it,
        and the `[SubtitlesConvertor]` line does not name a destination —
        measured against the installed binary. The conversion is a pure
        extension swap on the same stem, so derive it; if the derived file is
        not there, the announced one is still the honest answer.
        """
        fmt = str(self.config.get('SubtitleFormat') or '').strip().lower()
        if not fmt or fmt not in SUBTITLE_CONVERT_FORMATS:
            return written_path
        try:
            converted = Path(written_path).with_suffix(f'.{fmt}')
        except (TypeError, ValueError, OSError):
            return written_path
        return str(converted) if converted.exists() else written_path

    def _consume_ytdlp_output(self, dl, proc, activity):
        """Parse one yt-dlp process's stdout into `dl`'s live progress state.

        Both the first attempt and the cookie-less live retry run this parser.
        The retry used to carry a cloned copy with no test coverage, and it had
        already drifted from this one — a late output line could resurrect a
        cancelled download into "merging".

        Returns `(last_lines, last_error)` for failure classification.
        """
        last_lines = []
        last_error = None
        for line in proc.stdout:
            activity['at'] = time.monotonic()
            line = line.strip()
            if not line:
                continue
            last_lines.append(line)
            if len(last_lines) > 30:
                last_lines = last_lines[-30:]
            if 'ERROR' in line.upper():
                last_error = line

            # Preferred structured progress (JSON - robust to yt-dlp format
            # changes). Falls through to the legacy MDLP regex only if JSON
            # parsing fails.
            if line.startswith('MDLP_JSON '):
                try:
                    payload = json.loads(line[len('MDLP_JSON '):])
                    total = payload.get('total_bytes') or payload.get('total_bytes_estimate') or 0
                    downloaded_bytes = payload.get('downloaded_bytes') or 0
                    if isinstance(total, (int, float)) and total > 0:
                        dl.progress = max(0.0, min(100.0, (downloaded_bytes / total) * 100.0))
                    spd = (payload.get('_speed_str') or '').strip()
                    eta = (payload.get('_eta_str') or '').strip()
                    if spd and spd not in ('NA', 'Unknown'):
                        dl.speed = spd
                    if eta and eta not in ('NA', 'Unknown'):
                        dl.eta = eta
                    self.progress_updated.emit()
                    continue
                except Exception:
                    # reason: yt-dlp occasionally emits a malformed JSON line on
                    # extractor exit. Fall through to MDLP.
                    pass
            if line.startswith('MDLP_FILEPATH '):
                try:
                    filepath = json.loads(line[len('MDLP_FILEPATH '):])
                    if isinstance(filepath, str) and filepath:
                        dl.filename = filepath
                        continue
                except Exception:
                    # reason: malformed path payload; keep parsing the stream
                    pass

            # A subtitles-only run passes --skip-download, and the after_move
            # print hook above never fires without a media file, so the card
            # would finish with nothing to reveal. This line is also how the
            # local-transcription stage knows that --embed-subs already found
            # a track, even if yt-dlp removes the temporary sidecar afterward.
            written = SUBTITLE_WRITTEN_RE.match(line)
            if written:
                dl.subtitle_written = True
                if getattr(dl, 'subtitles_only', False):
                    dl.filename = self._converted_subtitle_path(written.group(1))
                continue

            # Structured progress (MDLP prefix, legacy fallback)
            m = re.match(r'^MDLP\s+(\d+\.?\d*)%?\s+(\S+)\s+(\S+)', line)
            if m:
                dl.progress = float(m.group(1))
                spd, eta = m.group(2), m.group(3)
                if spd not in ('NA', 'Unknown'):
                    dl.speed = spd
                if eta not in ('NA', 'Unknown'):
                    dl.eta = eta
                self.progress_updated.emit()
                continue

            # Legacy progress
            m = re.match(r'\[download\]\s+(\d+\.?\d*)%', line)
            if m:
                dl.progress = float(m.group(1))
                m2 = re.search(r'at\s+(\S+)\s+ETA\s+(\S+)', line)
                if m2:
                    dl.speed = m2.group(1)
                    dl.eta = m2.group(2)
                self.progress_updated.emit()
                continue

            # Request pacing makes yt-dlp sit idle on purpose. Without this the
            # row keeps its last speed and reads as hung rather than waiting.
            m = re.search(r'Sleeping\s+([\d.]+)\s+second', line, re.IGNORECASE)
            if m:
                try:
                    seconds = max(0, int(round(float(m.group(1)))))
                except (TypeError, ValueError):
                    seconds = 0
                dl.speed = f"waiting {seconds}s"
                dl.eta = ""
                self.progress_updated.emit()
                continue

            # Status changes
            if dl.status == 'cancelled':
                pass  # never resurrect a cancelled item from output lines
            elif '[Merger]' in line or 'Merging formats' in line:
                dl.status = "merging"
                self.progress_updated.emit()
            elif '[ExtractAudio]' in line or '[extract]' in line:
                dl.status = "extracting"
                self.progress_updated.emit()

            # Filename detection
            m = re.search(r'\[Merger\] Merging formats into "(.+)"', line)
            if m:
                dl.filename = m.group(1)
            else:
                m = re.search(r'\[download\] Destination: (.+)', line)
                if m:
                    dl.filename = m.group(1)
        return last_lines, last_error

    def _cookie_jar_matches_target(self, dl):
        """True when the jar on this download belongs to the site being asked
        for. Falls back to the YouTube check when a jar predates scope
        tracking (a queue recovered from an older companion)."""
        scope = getattr(dl, 'cookies_scope', '') or ''
        is_youtube = self._dependencies['is_youtube_url'](dl.url)
        if not scope:
            return is_youtube
        if scope == 'youtube':
            return is_youtube
        return scope == site_login_key(dl.url)

    def _empty_result_reason(self, dl):
        """Return why a zero-exit run produced no media, or None when it did.

        `dl.filename` is set from yt-dlp's own Destination/Merger/after_move
        output, so an empty value means nothing was written. A value that no
        longer exists on disk means a post-processor consumed the file and its
        replacement was never announced — treated as a real result rather than
        a skip, to avoid a false alarm on unusual post-processor chains.
        """
        if dl.filename:
            return None
        max_filesize = 0
        try:
            max_filesize = int(self.config.get("MaxFileSizeMB", 0) or 0)
        except (TypeError, ValueError):
            max_filesize = 0
        if max_filesize > 0:
            return (
                "Nothing was downloaded: every available format is larger than "
                f"the {max_filesize} MB size limit. Raise or clear Max file "
                "size in Settings, then retry."
            )
        return (
            "Nothing was downloaded: this link produced no media file. It may "
            "be a page without a downloadable video, or the site may serve it "
            "only to signed-in viewers."
        )

    def _download_intermediate_dir(self, dl):
        """Return the stable, app-owned staging directory for one download.

        The directory is derived from the queue id rather than a random temp
        name so a recovered queue item finds the same ``.part`` files after a
        restart. Queue ids normally already use the safe ``dl_*`` form, but
        restored state is untrusted, so sanitize it and add a deterministic
        suffix whenever it changes.
        """
        install_dir = Path(self._dependencies['INSTALL_DIR']()).resolve()
        root = (install_dir / DOWNLOAD_INTERMEDIATE_DIRNAME).resolve()
        raw_id = str(getattr(dl, 'id', '') or 'download')
        safe_id = re.sub(r'[^A-Za-z0-9._-]+', '_', raw_id)[:80]
        if not safe_id:
            safe_id = 'download'
        if safe_id != raw_id:
            suffix = uuid.uuid5(uuid.NAMESPACE_URL, raw_id).hex[:12]
            safe_id = f'{safe_id.rstrip("._-") or "download"}-{suffix}'
        candidate = (root / safe_id).resolve()
        if candidate.parent != root:
            # A pre-existing junction/symlink must never turn cleanup into a
            # recursive delete outside the app-owned staging root.
            suffix = uuid.uuid5(uuid.NAMESPACE_URL, raw_id).hex[:12]
            candidate = root / f'download-{suffix}'
        return candidate

    def _mark_transcription_failure(self, dl, error_code, error):
        """Keep the downloaded media complete when its optional sidecar fails."""
        if dl.status == 'cancelled':
            return
        dl.status = 'complete'
        apply_download_failure_classification(dl, error_code, error=error)

    def _run_local_subtitles(self, dl, effective_config):
        """Transcribe a successful video into an atomic SRT sidecar.

        FFmpeg only prepares the PCM input. The transcription capability is
        the pinned whisper.cpp sidecar, so an ffmpeg update cannot silently
        remove the feature. A sidecar failure annotates the completed media;
        it never turns a successful download into a failed full re-download.
        """
        if not should_generate_local_subtitles(effective_config, dl):
            return True

        model_path = Path(self._dependencies['WHISPER_MODEL_PATH']())
        model_state = self._dependencies['managed_binary_state'](
            model_path, self._dependencies['WHISPER_MODEL_MIN_BYTES']()
        )
        if model_state != 'ok':
            self._mark_transcription_failure(
                dl,
                'transcription-model-missing',
                'Local subtitle generation needs the Whisper model, but the '
                'model is missing or damaged.',
            )
            return False

        whisper_path = Path(self._dependencies['WHISPER_BIN_PATH']())
        runtime = self._dependencies['probe_whisper_runtime'](
            whisper_path, self._dependencies['WHISPER_BIN_MIN_BYTES']()
        )
        if not runtime.get('usable'):
            self._mark_transcription_failure(
                dl,
                'transcription-runtime-missing',
                'Local subtitle generation needs the whisper.cpp runtime, but '
                'it is missing or cannot provide SRT output.',
            )
            return False

        media_path = Path(dl.filename)
        output_path = local_subtitle_output_path(media_path)
        token = uuid.uuid4().hex
        temporary_audio = output_path.with_name(f'.{output_path.name}.{token}.wav')
        temporary_base = output_path.with_name(f'.{output_path.name}.{token}')
        temporary_srt = Path(f'{temporary_base}.srt')
        language = subtitle_language_for_transcription(effective_config)
        ffmpeg_args = build_whisper_audio_args(
            self._dependencies['FFMPEG_PATH'](), media_path, temporary_audio,
        )
        whisper_args = build_whisper_transcription_args(
            whisper_path, model_path, temporary_audio, temporary_base,
            language=language,
        )
        dl.status = 'transcribing'
        dl.speed = 'local transcription'
        dl.eta = ''
        dl.progress = min(99.0, max(0.0, float(dl.progress or 0.0)))
        self.progress_updated.emit()
        output_lines = []

        def run_process(args):
            proc = self._dependencies['spawn_media_process'](
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=(
                    self._dependencies['CREATE_NO_WINDOW']
                    | self._dependencies['CREATE_NEW_PROCESS_GROUP']
                ),
                env=self._dependencies['_build_subprocess_env'](),
            )
            dl.process = proc
            try:
                with self._lock:
                    cancelled_pre_spawn = dl.status == 'cancelled'
                if cancelled_pre_spawn:
                    self._dependencies['terminate_process_tree'](proc)
                for raw_line in getattr(proc, 'stdout', ()):
                    line = str(raw_line or '').strip()
                    if not line:
                        continue
                    output_lines.append(line)
                    if len(output_lines) > 40:
                        del output_lines[:-40]
                    if line.startswith('out_time_ms='):
                        dl.progress = max(1.0, min(99.0, float(dl.progress or 0.0)))
                        self.progress_updated.emit()
                proc.wait()
                return proc.returncode
            finally:
                dl.process = None
                try:
                    if getattr(proc, 'stdout', None) is not None:
                        proc.stdout.close()
                except Exception:
                    # reason: cleanup must not replace a completed transcription
                    pass
                if proc.poll() is None:
                    try:
                        self._dependencies['terminate_process_tree'](proc)
                    except Exception as error:
                        self._dependencies['write_persistent_log'](
                            f'WARNING: local subtitle termination failed: {error}'
                        )

        try:
            if run_process(ffmpeg_args) != 0:
                if dl.status == 'cancelled':
                    return False
                detail = ' '.join(
                    line for line in output_lines
                    if 'error' in line.lower() or 'failed' in line.lower()
                )[-240:]
                self._mark_transcription_failure(
                    dl,
                    'transcription-failed',
                    'ffmpeg could not prepare audio for local subtitles.' + (
                        f' {detail}' if detail else ''
                    ),
                )
                return False
            if dl.status == 'cancelled':
                return False
            dl.progress = max(50.0, min(80.0, float(dl.progress or 0.0)))
            self.progress_updated.emit()
            if run_process(whisper_args) != 0:
                if dl.status == 'cancelled':
                    return False
                detail = ' '.join(
                    line for line in output_lines
                    if 'error' in line.lower() or 'failed' in line.lower()
                )[-240:]
                self._mark_transcription_failure(
                    dl,
                    'transcription-failed',
                    'whisper.cpp could not generate local subtitles.' + (
                        f' {detail}' if detail else ''
                    ),
                )
                return False
            if dl.status == 'cancelled':
                return False
            if temporary_srt.is_file() and temporary_srt.stat().st_size > 0:
                os.replace(temporary_srt, output_path)
                dl.status = 'complete'
                dl.progress = 100.0
                dl.speed = ''
                dl.eta = ''
                dl.error = ''
                dl.error_code = ''
                dl.error_advice = ''
                dl.error_action = ''
                self.progress_updated.emit()
                return True
            self._mark_transcription_failure(
                dl,
                'transcription-failed',
                'whisper.cpp completed without producing an SRT sidecar.',
            )
            return False
        except FileNotFoundError:
            if dl.status != 'cancelled':
                self._mark_transcription_failure(
                    dl,
                    'transcription-runtime-missing',
                    'The local transcription runtime is unavailable. Run setup first.',
                )
            return False
        except Exception as error:
            if dl.status != 'cancelled':
                self._mark_transcription_failure(
                    dl,
                    'transcription-failed',
                    'Unexpected local subtitle error. Check Astra Downloader logs.',
                )
                self._dependencies['write_persistent_log'](
                    f'Local subtitles for {dl.id} failed: '
                    f'{_redact_download_secrets(error, dl)}'
                )
            return False
        finally:
            for path in (temporary_audio, temporary_srt):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # reason: a locked partial transcript is safe to retry later
                    pass

    def _record_terminal_download(self, dl):
        """Persist history and emit completion after any terminal worker path."""
        dl.mark_terminal()
        if dl.status in DOWNLOAD_TERMINAL_STATES:
            self._sweep_download_intermediates(dl)
        if dl.status == "complete":
            self.total_completed += 1
        # History is the durable record of every terminal outcome, not just a
        # successful file write. The queue intentionally evicts old terminal
        # objects, so omitting failures here made an overnight failure vanish
        # with no way to explain or retry it later.
        duration = int(time.time() - dl.start_time)
        recorded = self.history.add({
            "id": dl.id, "url": dl.url, "title": dl.title,
            "filename": dl.filename, "format": dl.format,
            "quality": dl.quality, "audioOnly": dl.audio_only,
            "section": dict(dl.section) if dl.section else None,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": duration,
            "status": dl.status,
            "errorCode": dl.error_code,
            "error": dl.error,
        })
        with self._lock:
            if recorded:
                self._history_error = ""
            else:
                self._history_error = (
                    "The last download finished but could not be added to "
                    "History. Check free disk space and folder permissions."
                )
        if not recorded:
            self._dependencies['write_persistent_log'](
                f"Download {dl.id} reached {dl.status} but its history entry "
                "could not be saved."
            )

        self.progress_updated.emit()
        self.download_completed.emit(dl.id)

    def _run_download(self, dl):
        with self._lock:
            if dl.status != 'queued':
                # cancel() can land between _schedule() releasing the lock and
                # this worker thread's first statement. The item is already
                # terminal (cancel() persisted it and unlinked its cookie jar),
                # so reviving it would run a download the user just cancelled.
                # _worker_entry's finally block releases the slot and
                # re-schedules; nothing else to tear down here.
                return
            dl.status = "downloading"
        self.progress_updated.emit()

        effective_config = self._effective_config_for_url(
            dl.url, getattr(dl, 'profile_name', None)
        )

        if getattr(dl, 'subtitle_retry', False):
            try:
                self._run_local_subtitles(dl, effective_config)
            except Exception as error:
                if dl.status != 'cancelled':
                    self._mark_transcription_failure(
                        dl,
                        'transcription-failed',
                        'Unexpected local subtitle error. Check Astra Downloader logs.',
                    )
                    self._dependencies['write_persistent_log'](
                        f'Subtitle-only retry for {dl.id} failed: '
                        f'{_redact_download_secrets(error, dl)}'
                    )
            finally:
                dl.subtitle_retry = False
            self._record_terminal_download(dl)
            return

        ytdlp = str(self._dependencies['YTDLP_PATH']())
        ffmpeg_dir = str(self._dependencies['FFMPEG_PATH']().parent)
        is_playlist = is_playlist_url(dl.url)

        # Output template. A user-configured template (already validated by
        # config.normalize_output_template — allowlisted fields, no traversal,
        # keeps %(ext)s) is always relative to the download root and, when set,
        # governs both single and playlist layout. It must stay relative: yt-dlp
        # ignores --paths when -o receives an absolute template.
        custom_tpl = str(effective_config.get("OutputTemplate", "") or "")
        if custom_tpl:
            out_tpl = custom_tpl
        elif is_playlist:
            # yt-dlp substitutes the literal string "NA" for a field it cannot
            # resolve, so a collection with no title used to create a folder
            # called NA and every such download piled into it. The alternation
            # falls back to the playlist id and then to a plain word.
            out_tpl = (
                "%(playlist_title,playlist_id|Playlist).200B/"
                "%(title).200B.%(ext)s"
            )
        else:
            out_tpl = "%(title).200B.%(ext)s"

        # yt-dlp downloads to temp: first and moves only the finished output
        # under home:. KeepIntermediateFiles is deliberately also the
        # diagnosis switch: it puts temp: beside the output and skips cleanup.
        keep_intermediates = bool(effective_config.get("KeepIntermediateFiles", False))
        intermediate_dir = (
            Path(dl.output_dir)
            if keep_intermediates else self._download_intermediate_dir(dl)
        )

        # Build args. v1.2.0: emit progress as JSON alongside the legacy MDLP
        # line so we can parse robustly when yt-dlp tweaks its human-readable
        # format. We keep the legacy line as a fallback.
        args = [ytdlp, '--ignore-config', '--newline', '--progress', '--no-colors',
                '--trim-filenames', '180',
                '--replace-in-metadata', 'title,playlist_title',
                '[\":<>|*?/\\\\]', '_',
                '--ffmpeg-location', ffmpeg_dir,
                '--paths', f'home:{dl.output_dir}',
                '--paths', f'temp:{intermediate_dir}',
                '-o', out_tpl,
                '--progress-template',
                'download:MDLP %(progress._percent_str)s %(progress._speed_str)s %(progress._eta_str)s',
                '--progress-template',
                'download:MDLP_JSON %(progress)j',
                '--print', 'after_move:MDLP_FILEPATH %(filepath)j']
        if effective_config.get("WindowsFilenames", True):
            args.append('--windows-filenames')

        frags = self._dependencies['clamp_int'](effective_config.get("ConcurrentFragments", 4), 4, 1, 32)
        args += ['--concurrent-fragments', str(frags)]
        retries = self._dependencies['clamp_int'](effective_config.get("DownloadRetries", 10), 10, 0, 50)
        args += ['--retries', str(retries), '--fragment-retries', str(retries)]
        subtitles_only = bool(getattr(dl, 'subtitles_only', False))
        # Every embed writes into the media container, and a subtitles-only
        # run never produces one. Passing them would ask ffmpeg to postprocess
        # a file that was deliberately not downloaded.
        if not subtitles_only:
            if effective_config.get("EmbedMetadata"):
                args.append('--embed-metadata')
            if effective_config.get("EmbedThumbnail"):
                args.append('--embed-thumbnail')
            if effective_config.get("EmbedChapters"):
                args.append('--embed-chapters')
        if effective_config.get("WriteInfoJson"):
            args.append('--write-info-json')
        if effective_config.get("WriteDescription"):
            args.append('--write-description')
        if effective_config.get("WriteThumbnail"):
            args.append('--write-thumbnail')
        if effective_config.get("SplitChapters"):
            args.append('--split-chapters')
        if effective_config.get("LiveFromStart"):
            args.append('--live-from-start')
        wait_for_video = self._dependencies['clamp_int'](
            effective_config.get("WaitForVideoSeconds", 0), 0, 0, 3600
        )
        if wait_for_video > 0:
            args += ['--wait-for-video', str(wait_for_video)]
        args += build_subtitle_args(effective_config, subtitles_only=subtitles_only)
        if subtitles_only:
            args.append('--skip-download')
        # SponsorBlock has YouTube-only segment data; passing it for any other
        # site only produces a warning line that later competes with the real
        # failure reason in the output tail.
        if effective_config.get("SponsorBlock") and self._dependencies['is_youtube_url'](dl.url):
            action = 'mark' if effective_config.get("SponsorBlockAction") == 'mark' else 'remove'
            # Empty means every category, which is what this used to send
            # unconditionally — asking it to skip sponsors also stripped
            # intros, outros and self-promo.
            categories = self._dependencies['normalize_sponsorblock_categories'](
                effective_config.get("SponsorBlockCategories", "")
            )
            args += [f'--sponsorblock-{action}', categories or 'all']
        # v1.3.0: --force-overwrites lets the user re-download the same URL
        # repeatedly. Without it, yt-dlp refuses to overwrite an existing
        # output file and prints "[download] Title.mp4 has already been
        # downloaded" — same UX failure mode as the now-removed
        # --download-archive feature.
        #
        # It also includes --no-continue, which is why it is not unconditional:
        # on a retry, a resume, or a download recovered after a restart there
        # may be a `.part` file worth continuing from, and discarding it means
        # re-fetching everything already on disk.
        if not getattr(dl, 'resume_partial', False):
            args.append('--force-overwrites')
        rate = str(effective_config.get("RateLimit", "")).strip().upper()
        if rate and re.match(r'^\d+[KMG]?$', rate):
            args += ['--limit-rate', rate]
        # A CDN that throttles to a trickle otherwise runs until the stall
        # watchdog kills it; yt-dlp can notice and re-extract instead.
        throttled = str(effective_config.get("ThrottledRate", "")).strip().upper()
        if throttled and re.match(r'^\d+[KMG]?$', throttled):
            args += ['--throttled-rate', throttled]
        socket_timeout = int(effective_config.get("SocketTimeoutSeconds", 0) or 0)
        if socket_timeout > 0:
            args += ['--socket-timeout', str(socket_timeout)]
        # Distinct from --retries, which covers the transfer: this covers the
        # extractor giving up before a transfer ever starts.
        extractor_retries = int(effective_config.get("ExtractorRetries", 0) or 0)
        if extractor_retries > 0:
            args += ['--extractor-retries', str(extractor_retries)]
        # Costs a request per candidate format, so it is opt-in. A format that
        # fails verification classifies through the existing taxonomy.
        if effective_config.get("VerifyFormats"):
            args.append('--check-formats')
        # Pacing. --limit-rate caps bandwidth, which does nothing about a
        # per-request rate limit; spacing the requests is the actual lever.
        sleep_interval = int(effective_config.get("SleepIntervalSeconds", 0) or 0)
        max_sleep = int(effective_config.get("MaxSleepIntervalSeconds", 0) or 0)
        try:
            pacing_jitter = max(0, min(100, int(
                effective_config.get("PacingJitterPercent", 0) or 0
            )))
        except (TypeError, ValueError, OverflowError):
            pacing_jitter = 0
        if sleep_interval > 0:
            args += ['--sleep-interval', str(sleep_interval)]
            jitter_max = math.ceil(
                sleep_interval * (1 + pacing_jitter / 100.0)
            ) if pacing_jitter else 0
            effective_max_sleep = max(max_sleep, jitter_max)
            if effective_max_sleep >= sleep_interval:
                args += ['--max-sleep-interval', str(effective_max_sleep)]
        sleep_requests = int(effective_config.get("SleepRequestsSeconds", 0) or 0)
        if sleep_requests > 0:
            if pacing_jitter:
                sleep_requests = max(
                    1, round(sleep_requests * self._pacing_jitter_multiplier())
                )
            args += ['--sleep-requests', str(sleep_requests)]
        proxy = effective_config.get("Proxy", "")
        if proxy and re.match(r'^(socks(?:4a?|5h?)?|https?)://', proxy):
            args += ['--proxy', proxy]
        args += build_network_workaround_args(effective_config)
        max_filesize = int(effective_config.get("MaxFileSizeMB", 0) or 0)
        if max_filesize > 0:
            args += ['--max-filesize', f'{max_filesize}M']
        if dl.referer:
            args += ['--referer', dl.referer]
        # Two jars can reach this point, each scoped to one site: the
        # extension's YouTube bridge (ALLOWED_COOKIE_DOMAINS) and a stored site
        # sign-in (one registrable domain, enforced by SiteLoginStore).
        # `--cookies` is also a write path, so a jar is attached only for the
        # site it was built for — a request that pairs one site's URL with
        # another site's cookies sends nothing.
        if dl.cookies_file and self._cookie_jar_matches_target(dl):
            args += ['--cookies', dl.cookies_file]
        else:
            args += build_site_login_credential_args(
                getattr(dl, '_credentials', None)
            )
        if getattr(dl, '_video_password', '') and not is_playlist:
            args += ['--video-password', dl._video_password]
        if is_playlist:
            args.append('--yes-playlist')
            if dl.playlist_items:
                args += ['--playlist-items', ','.join(str(item) for item in dl.playlist_items)]
            # Bounds belong to the run that walks a playlist; a single video
            # is never filtered by them.
            args += build_playlist_bound_args(effective_config)
        elif not self._dependencies['is_youtube_url'](dl.url):
            # Single-item intent on a non-YouTube URL. Without this, pasting a
            # channel/profile/subreddit link makes yt-dlp walk the whole
            # collection. YouTube keeps its historical default (a watch URL
            # carrying &list= is handled by the extension) so this cannot
            # change any behaviour the extension already depends on.
            args.append('--no-playlist')

        # Format selection
        if dl.audio_only:
            args += ['-f', 'bestaudio', '--extract-audio',
                     '--audio-format', dl.format, '--audio-quality', '0']
        else:
            args += build_video_format_args(dl.format, dl.quality)
        args += build_format_sort_args(effective_config)

        # yt-dlp is spawned with --no-plugin-dirs. The extractor builder must
        # therefore always use the plugin-free token-exempt client chain; a
        # local process on the old bgutil port cannot change this argv.
        args += self._dependencies['build_youtube_extractor_args'](dl.url)
        runtime = self._dependencies['probe_javascript_runtime'](
            configured_runtime=effective_config.get('JavaScriptRuntime', 'auto')
        )
        args += self._dependencies['build_javascript_runtime_args'](runtime)
        configured_target = str(
            effective_config.get('ImpersonateTarget', '') or ''
        ).strip()
        available_targets = (
            self._dependencies['probe_impersonate_targets']()
            if configured_target else []
        )
        args += build_impersonate_args(effective_config, available_targets)

        args.append(dl.url)

        # Watchdog sentinels declared before the try so the finally can stop the
        # thread even if Popen() raises before the watchdog is created.
        stop_watchdog = None
        watchdog_thread = None
        watchdog_killed = {'value': None}
        last_lines = []
        last_error = None
        try:
            env = self._dependencies['_build_subprocess_env']()
            proc = self._dependencies['spawn_ytdlp'](
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
                creationflags=self._dependencies['CREATE_NO_WINDOW'] | self._dependencies['CREATE_NEW_PROCESS_GROUP'],
                env=env,
            )
            dl.process = proc
            with self._lock:
                cancelled_pre_spawn = dl.status == 'cancelled'
            if cancelled_pre_spawn:
                # cancel() landed in the pre-spawn arg-building window: it saw
                # process None and armed no terminate thread, so kill the tree
                # we just spawned ourselves.
                try:
                    self._dependencies['terminate_process_tree'](proc)
                except Exception as error:
                    # reason: best-effort kill; process may already be gone
                    self._dependencies['write_persistent_log'](
                        f"WARNING: pre-spawn process termination failed: {error}"
                    )
            # Stall watchdog (see DOWNLOAD_STALL_TIMEOUT_SECONDS): kill a wedged
            # yt-dlp/ffmpeg tree that produces no output for too long so it can't
            # block a worker thread / hold a concurrency slot forever.
            activity = {'at': time.monotonic()}
            stop_watchdog = threading.Event()

            # Bind the stop event and process into the closure via default args.
            # The retry path (below) rebinds `stop_watchdog` and `proc`; without
            # this binding a still-running original watchdog would re-read those
            # names and start polling the retry's event/process, becoming a
            # duplicate watchdog that can cross-kill or mis-attribute a stall.
            def _stall_watchdog(ev=stop_watchdog, watched_proc=proc):
                while not ev.wait(DOWNLOAD_WATCHDOG_POLL_SECONDS):
                    if dl.status == 'cancelled':
                        if watched_proc.poll() is None:
                            watchdog_killed['value'] = 'cancelled'
                            try:
                                self._dependencies['terminate_process_tree'](watched_proc)
                            except Exception as error:
                                # reason: best-effort kill; process may already be gone
                                self._dependencies['write_persistent_log'](
                                    f"WARNING: cancelled-download watchdog termination failed: {error}"
                                )
                        return
                    if (time.monotonic() - activity['at']) > DOWNLOAD_STALL_TIMEOUT_SECONDS:
                        watchdog_killed['value'] = 'stall'
                        try:
                            self._dependencies['terminate_process_tree'](watched_proc)
                        except Exception as error:
                            # reason: best-effort kill; process may already be gone
                            self._dependencies['write_persistent_log'](
                                f"WARNING: stalled-download watchdog termination failed: {error}"
                            )
                        return

            watchdog_thread = threading.Thread(
                target=_stall_watchdog, name='download-stall-watchdog', daemon=True
            )
            watchdog_thread.start()

            last_lines, last_error = self._consume_ytdlp_output(dl, proc, activity)
            last_lines = _redact_download_secrets(last_lines, dl)
            last_error = _redact_download_secrets(last_error, dl)

            proc.wait()

            if dl.status != "complete":
                if dl.status == "cancelled":
                    dl.error = dl.error or "Cancelled by user."
                elif watchdog_killed['value'] == 'stall':
                    dl.status = "failed"
                    dl.error = (
                        "Download stalled (no progress for "
                        f"{DOWNLOAD_STALL_TIMEOUT_SECONDS // 60} minutes) and was stopped."
                    )
                    apply_download_failure_classification(
                        dl, 'network-unreachable', error=dl.error
                    )
                elif proc.returncode == 0:
                    # yt-dlp exits 0 when it deliberately downloads nothing —
                    # most often because --max-filesize rejected every format
                    # (a 300 MB archive.org item under a 25 MB cap), or the
                    # extractor produced no media. Reporting "complete" with no
                    # file on disk reads exactly like a broken downloader, so
                    # surface it as `skipped` with the reason instead.
                    skip_reason = self._empty_result_reason(dl)
                    if skip_reason:
                        dl.status = "skipped"
                        dl.progress = 0
                        dl.error = skip_reason
                    else:
                        dl.status = "complete"
                        dl.progress = 100
                else:
                    dl.status = "failed"
                    # Audit pass: truncate the last ERROR line like the
                    # fallback branch already does. yt-dlp ERROR lines can
                    # carry a full Python traceback; an untruncated value used
                    # to round-trip through /status to the extension popup and
                    # blow past the JSON payload UI budget.
                    if last_error:
                        dl.error = last_error[-240:]
                    else:
                        # No real `ERROR:` line. yt-dlp still emits benign
                        # WARNING noise (e.g. "Your yt-dlp version … is older
                        # than 90 days", "PO Token which was not provided",
                        # progress residue) that must NEVER be surfaced as the
                        # failure reason — doing so masks the true cause and
                        # reads as "the downloader is broken" when it merely
                        # exited. Drop that noise before falling back.
                        meaningful = [
                            ln for ln in last_lines
                            if ln and not _is_benign_failure_noise(ln)
                        ]
                        if meaningful:
                            dl.error = " ".join(meaningful)[-240:]
                        else:
                            dl.error = (
                                f"yt-dlp exited with code {proc.returncode} "
                                "without reporting a specific error. The video "
                                "may be unavailable, private, region-locked, or "
                                "require sign-in."
                            )
                    # Attach an actionable classification (error_code / advice /
                    # next_action) so the extension can render recovery guidance
                    # instead of raw yt-dlp text. Preserves the message above.
                    _failure_code = classify_download_failure(
                        last_error or dl.error, last_lines
                    )
                    if _failure_code:
                        apply_download_failure_classification(
                            dl, _failure_code, error=dl.error,
                        )
                    combined = " ".join(last_lines).lower()
                    if 'live event has ended' in combined and dl.cookies_file:
                        self._dependencies['write_persistent_log'](
                            f"Download {dl.id}: 'live event has ended' with cookies — "
                            "retrying without cookies"
                        )
                        retry_args = [a for i, a in enumerate(args)
                                      if a != '--cookies' and (i == 0 or args[i - 1] != '--cookies')]
                        dl.status = "downloading"
                        dl.error = ""
                        dl.error_code = ""
                        dl.error_advice = ""
                        dl.error_action = ""
                        dl.progress = 0
                        self.progress_updated.emit()
                        if stop_watchdog is not None:
                            stop_watchdog.set()
                        # Join the original watchdog before rebinding so it can't
                        # linger and poll the retry's process/event.
                        if watchdog_thread is not None:
                            watchdog_thread.join(timeout=DOWNLOAD_WATCHDOG_POLL_SECONDS + 1)
                        # The first process reached EOF, but Popen keeps the
                        # TextIOWrapper open until it is explicitly closed (or
                        # garbage-collected). Close it before rebinding `proc`
                        # so repeated cookie-less retries cannot leak one pipe
                        # handle per attempt.
                        previous_stdout = getattr(proc, 'stdout', None)
                        try:
                            if previous_stdout is not None:
                                previous_stdout.close()
                        except Exception:
                            # reason: test doubles and already-closed streams
                            # may not expose a conventional close operation
                            pass
                        self._release_ytdlp_activity(proc)
                        activity['at'] = time.monotonic()
                        stop_watchdog = threading.Event()
                        proc = self._dependencies['spawn_ytdlp'](
                            retry_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', bufsize=1,
                            creationflags=self._dependencies['CREATE_NO_WINDOW'] | self._dependencies['CREATE_NEW_PROCESS_GROUP'],
                            env=env,
                        )
                        dl.process = proc
                        with self._lock:
                            cancelled_pre_spawn = dl.status == 'cancelled'
                        if cancelled_pre_spawn:
                            # cancel() can land after the first process exits
                            # but before this cookie-less retry is spawned. It
                            # saw the exited process and therefore armed no
                            # terminate thread; kill the retry tree here before
                            # it can download or write output.
                            try:
                                self._dependencies['terminate_process_tree'](proc)
                            except Exception as error:
                                # reason: best-effort kill; process may already be gone
                                self._dependencies['write_persistent_log'](
                                    f"WARNING: cancelled retry termination failed: {error}"
                                )

                        def _retry_watchdog(ev=stop_watchdog, watched_proc=proc):
                            while not ev.wait(DOWNLOAD_WATCHDOG_POLL_SECONDS):
                                if dl.status == 'cancelled':
                                    if watched_proc.poll() is None:
                                        watchdog_killed['value'] = 'cancelled'
                                        try:
                                            self._dependencies['terminate_process_tree'](watched_proc)
                                        except Exception as error:
                                            # reason: best-effort kill; process may already be gone
                                            self._dependencies['write_persistent_log'](
                                                f"WARNING: retry watchdog cancellation termination failed: {error}"
                                            )
                                    return
                                if (time.monotonic() - activity['at']) > DOWNLOAD_STALL_TIMEOUT_SECONDS:
                                    watchdog_killed['value'] = 'stall'
                                    try:
                                        self._dependencies['terminate_process_tree'](watched_proc)
                                    except Exception as error:
                                        self._dependencies['write_persistent_log'](
                                            f"WARNING: retry watchdog stall termination failed: {error}"
                                        )
                                    return

                        watchdog_thread = threading.Thread(
                            target=_retry_watchdog, name='download-stall-watchdog-retry', daemon=True
                        )
                        watchdog_thread.start()

                        last_lines, last_error = self._consume_ytdlp_output(dl, proc, activity)
                        last_lines = _redact_download_secrets(last_lines, dl)
                        last_error = _redact_download_secrets(last_error, dl)

                        proc.wait()
                        if dl.status == 'cancelled':
                            dl.error = dl.error or "Cancelled by user."
                        elif watchdog_killed['value'] == 'stall':
                            dl.status = "failed"
                            dl.error = (
                                "Download stalled (no progress for "
                                f"{DOWNLOAD_STALL_TIMEOUT_SECONDS // 60} minutes) and was stopped."
                            )
                            apply_download_failure_classification(
                                dl, 'network-unreachable', error=dl.error
                            )
                        elif proc.returncode == 0:
                            skip_reason = self._empty_result_reason(dl)
                            if skip_reason:
                                dl.status = "skipped"
                                dl.progress = 0
                                dl.error = skip_reason
                            else:
                                dl.status = "complete"
                                dl.progress = 100
                        else:
                            dl.status = "failed"
                            if last_error:
                                dl.error = last_error[-240:]
                            elif last_lines:
                                dl.error = " ".join(last_lines)[-240:]
                            else:
                                dl.error = "Unknown error"
                            apply_download_failure_classification(
                                dl,
                                classify_download_failure(dl.error, last_lines),
                            )
                    elif 'live event has ended' in combined:
                        dl.error = (
                            "YouTube reports this live stream has ended. "
                            "The VOD archive may still be processing — "
                            "try again in a few minutes."
                        )
                    elif ('sabr' in combined or 'no video formats' in combined
                            or 'requested format is not available' in combined):
                        apply_download_failure_classification(
                            dl, 'sabr-limited',
                        )
                    else:
                        apply_download_failure_classification(
                            dl,
                            classify_download_failure(dl.error, last_lines),
                        )
            if dl.status == "complete" and dl.section:
                if stop_watchdog is not None:
                    stop_watchdog.set()
                try:
                    if getattr(proc, 'stdout', None) is not None:
                        proc.stdout.close()
                except Exception:
                    # reason: test doubles and already-closed streams are safe to ignore during teardown
                    pass
                if self._recut_section(dl, env):
                    dl.status = "complete"
                    dl.progress = 100
            if dl.status == 'complete':
                self._run_local_subtitles(dl, effective_config)

        except FileNotFoundError:
            if dl.status != "cancelled":
                dl.status = "failed"
                dl.error = "yt-dlp not found. Run setup first."
        except Exception as e:
            if dl.status != "cancelled":
                dl.status = "failed"
                dl.error = "Unexpected download error. Check Astra Downloader logs for details."
                self._dependencies['write_persistent_log'](
                    f"Download {dl.id} failed unexpectedly: "
                    f"{_redact_download_secrets(e, dl)}"
                )
        finally:
            # Signal the watchdog to stop; it's a daemon thread that wakes from
            # its wait() the moment the event is set and exits on its own. We do
            # NOT join() it here — joining adds latency between status becoming
            # terminal (which unblocks observers/tests) and the post-finally
            # history write, which can let an observer see "complete" before the
            # history entry exists.
            if stop_watchdog is not None:
                stop_watchdog.set()
            # Audit fix: if we got here via the generic except (e.g. an
            # unexpected error inside the output-parsing loop), yt-dlp and any
            # ffmpeg child may still be running — without this they'd be
            # orphaned (holding a MAX_CONCURRENT slot's process alive and
            # keeping the cookie jar in use while we unlink it below). The
            # normal-completion and cancelled paths are unaffected:
            # terminate_process_tree() returns immediately when the process
            # has already exited, and the cancel() thread's own kill is
            # idempotent with this one.
            orphan = dl.process
            if orphan is not None and orphan.poll() is None:
                try:
                    self._dependencies['terminate_process_tree'](orphan)
                except Exception as error:
                    # reason: best-effort kill; never mask the original error
                    self._dependencies['write_persistent_log'](
                        f"WARNING: orphaned process termination failed: {error}"
                    )
            # Popen does not close PIPE-backed TextIOWrapper objects merely
            # because wait() reached EOF. Explicit closure prevents descriptor
            # leaks in the long-running GUI after each completed, failed, or
            # cancelled download.
            process_stdout = getattr(orphan, 'stdout', None)
            try:
                if process_stdout is not None:
                    process_stdout.close()
            except Exception:
                # reason: cleanup must never replace the download result
                pass
            self._release_ytdlp_activity(orphan)
            dl.process = None
            # Cookie jar holds session credentials — purge it as soon as the
            # download process exits so it never outlives the one request that
            # needed it.
            if dl.cookies_file:
                try:
                    Path(dl.cookies_file).unlink(missing_ok=True)
                except Exception:
                    # reason: cookie cleanup is idempotent after worker failure or cancellation
                    pass
                dl.cookies_file = None
        if dl.error_code == 'rate-limited':
            self._record_host_backoff(
                dl.url, parse_retry_after_seconds(last_lines)
            )

        self._record_terminal_download(dl)

    def pause_intake(self):
        with self._lock:
            if self.intake_paused:
                return True
            self.intake_paused = True
            if self._persist_locked():
                return True
            self.intake_paused = False
            return False

    def resume_intake(self):
        with self._lock:
            restored = []
            self.intake_paused = False
            for dl in self.downloads.values():
                if dl.status == 'paused':
                    restored.append((dl, dl.error))
                    dl.status = 'pending'
                    dl.error = ''
            if not self._persist_locked():
                self.intake_paused = True
                for dl, error in restored:
                    dl.status = 'paused'
                    dl.error = error
                return False
        self.progress_updated.emit()
        self._schedule()
        return True

    def persist_intake_flag(self, paused):
        """Persist ``intakePaused`` as *paused* without changing the live flag.

        Used by the companion self-update immediately before the process
        exits: intake must stay paused in this process so nothing can spawn
        yt-dlp during the exit window, but the relaunched companion should
        restore the user's pre-update setting.
        """
        with self._lock:
            previous = self.intake_paused
            self.intake_paused = bool(paused)
            ok = self._persist_locked()
            self.intake_paused = previous
            return ok

    def resume_download(self, dl_id, cookies=None):
        with self._lock:
            dl = self.downloads.get(dl_id)
            if not dl:
                return False, 'Download no longer exists in the queue.'
            if dl_id in self._running_ids:
                # The worker that owns this id has not run its finally block
                # yet. Flipping the item back to pending now would let
                # _schedule() start a second worker whose slot registration
                # the first worker's teardown then discards.
                return False, 'Download is still finalizing — retry in a moment.'
            if dl.status not in DOWNLOAD_PENDING_STATES:
                return False, 'Only pending or recovered downloads can be resumed.'
            if dl.status == 'needs-auth' and not cookies:
                return False, (
                    'Fresh YouTube cookies are required. Retry from Astra Deck so the '
                    'browser can authorize this download.'
                )
            previous = snapshot_download_fields(dl, RESUME_ROLLBACK_FIELDS)
            if cookies:
                dl.requires_auth = True
                dl._cookies = list(cookies)
            dl.status = 'pending'
            dl.error = ''
            dl.error_code = ''
            dl.error_advice = ''
            dl.error_action = ''
            dl.resume_partial = True
            if not self._persist_locked():
                restore_download_fields(dl, previous)
                return False, self._persistence_error
        self.progress_updated.emit()
        self._schedule()
        return True, None

    def retry(self, dl_id, cookies=None):
        # Recovery checks may consult a cached readiness snapshot, but keeping
        # this preflight outside the queue lock makes that contract explicit
        # and prevents a future check from reintroducing lock contention.
        while True:
            with self._lock:
                dl = self.downloads.get(dl_id)
                if not dl:
                    return False, 'Download no longer exists in the queue.'
                if dl_id in self._running_ids:
                    # A worker can stamp a retryable failure milliseconds before
                    # its finally block discards the id from _running_ids. A
                    # retry accepted in that gap starts a second worker, then
                    # the first worker's teardown discards the second worker's
                    # slot and marks the retrying download failed.
                    return False, 'Download is still finalizing — retry in a moment.'
                # `skipped` is retryable by definition: nothing was written,
                # and the fix (raise the size limit, sign in, pick another
                # link) is a setting change followed by exactly this action.
                subtitle_retry = (
                    dl.status == 'complete'
                    and dl.error_code in DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES
                )
                if dl.status not in ('failed', 'skipped') and not subtitle_retry:
                    return False, 'Only failed or skipped downloads can be retried.'
                needs_recovery = (
                    dl.status == 'failed'
                    and dl.error_code not in DOWNLOAD_RETRYABLE_ERROR_CODES
                )
                recovery_signature = (
                    dl.error_code, dl.url, bool(dl.requires_auth)
                ) if needs_recovery else None

            recovery_answer = None
            if needs_recovery:
                # The object is revalidated under the lock below. This first
                # pass only reads immutable recovery inputs and is intentionally
                # outside the manager lock.
                recovery_answer = self.recovery_precondition(dl)
                if not recovery_answer[0]:
                    return False, recovery_answer[1]

            with self._lock:
                dl = self.downloads.get(dl_id)
                if not dl:
                    return False, 'Download no longer exists in the queue.'
                if dl_id in self._running_ids:
                    return False, 'Download is still finalizing — retry in a moment.'
                subtitle_retry = (
                    dl.status == 'complete'
                    and dl.error_code in DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES
                )
                if dl.status not in ('failed', 'skipped') and not subtitle_retry:
                    return False, 'Only failed or skipped downloads can be retried.'
                if dl.status == 'failed' and dl.error_code not in DOWNLOAD_RETRYABLE_ERROR_CODES:
                    current_signature = (
                        dl.error_code, dl.url, bool(dl.requires_auth)
                    )
                    if current_signature != recovery_signature:
                        # The record changed while the cached precondition was
                        # being read. Re-evaluate the new failure outside the
                        # lock instead of accepting a stale answer.
                        continue
                    if recovery_answer is None or not recovery_answer[0]:
                        return False, (
                            recovery_answer[1]
                            if recovery_answer is not None else
                            'This failure needs its recovery action before it can be retried.'
                        )
                result = self._retry_locked(dl, cookies, subtitle_retry)
            if result[0]:
                self.progress_updated.emit()
                self._schedule()
            return result

    def _retry_locked(self, dl, cookies, subtitle_retry):
        """Apply a validated retry while ``self._lock`` is held."""
        if dl.status == 'failed' and dl.error_code == 'rate-limited':
            remaining = self._host_backoff_remaining_locked(dl.url)
            if remaining > 0:
                return False, (
                    'This site is still rate-limited; retry in '
                    f'{math.ceil(remaining)} seconds.'
                )
        if self._capacity_locked()['total'] >= MAX_QUEUED_TOTAL:
            return False, (
                f"Download queue is full ({MAX_QUEUED_TOTAL}/{MAX_QUEUED_TOTAL}). "
                "Cancel a pending item or wait for a running download to finish, then retry."
            )
        previous = snapshot_download_fields(dl, RETRY_ROLLBACK_FIELDS)
        if subtitle_retry:
            try:
                media_path = Path(dl.filename).resolve(strict=True)
                output_root = Path(dl.output_dir).resolve(strict=True)
                if media_path != output_root and not media_path.is_relative_to(output_root):
                    raise ValueError
            except (OSError, RuntimeError, ValueError):
                return False, 'The completed media file is no longer available for subtitle retry.'
            dl.status = 'pending'
            dl.progress = 0.0
            dl.speed = ''
            dl.eta = ''
            dl.error = ''
            dl.error_code = ''
            dl.error_advice = ''
            dl.error_action = ''
            dl.finished_time = None
            dl.start_time = time.time()
            dl.resume_partial = False
            dl.subtitle_retry = True
            self._next_order += 1
            dl.queue_order = self._next_order
            if not self._persist_locked():
                restore_download_fields(dl, previous)
                return False, self._persistence_error
            # The completed media remains in place. This job deliberately
            # bypasses cookie preparation and yt-dlp in _run_download.
        elif dl.requires_auth and not cookies:
            dl.status = 'needs-auth'
            dl.error = (
                'Fresh YouTube authentication is required before this download can retry.'
            )
            dl.error_code = ''
            dl.error_advice = ''
            dl.error_action = 'sign-in-and-retry'
            dl.finished_time = None
            self._next_order += 1
            dl.queue_order = self._next_order
            if not self._persist_locked():
                restore_download_fields(dl, previous)
                return False, self._persistence_error
            return False, (
                'Fresh YouTube cookies are required. Retry from Astra Deck so the '
                'browser can authorize this download.'
            )
        if not subtitle_retry and cookies:
            dl.requires_auth = True
            dl._cookies = list(cookies)
        if not subtitle_retry:
            dl.status = 'pending'
            dl.progress = 0.0
            dl.speed = ''
            dl.eta = ''
            dl.filename = ''
            dl.error = ''
            dl.error_code = ''
            dl.error_advice = ''
            dl.error_action = ''
            dl.finished_time = None
            dl.start_time = time.time()
            # A retry continues whatever the failed attempt left on disk.
            dl.resume_partial = True
            self._next_order += 1
            dl.queue_order = self._next_order
            if not self._persist_locked():
                restore_download_fields(dl, previous)
                return False, self._persistence_error
        return True, None

    def move_pending(self, dl_id, position):
        with self._lock:
            ok, error = self._move_pending_locked(dl_id, position)
        if ok:
            self.progress_updated.emit()
        return ok, error

    def _move_pending_locked(self, dl_id, position):
        """Reorder one pending download. The caller must hold the lock.

        Split out so `move_pending_by` can derive an index and apply the move
        under a single acquisition. It used to release the lock between the
        two, so a download finishing in the gap left the absolute position
        meaning something other than the ordering it was derived from.
        """
        pending = self._ordered_pending_locked()
        current = next((index for index, dl in enumerate(pending) if dl.id == dl_id), None)
        if current is None:
            return False, 'Only pending downloads can be reordered.'
        if isinstance(position, bool):
            return False, 'Queue position must be an integer.'
        if isinstance(position, int):
            target = position
        elif isinstance(position, str) and re.fullmatch(r'-?\d+', position.strip()):
            target = int(position.strip())
        else:
            return False, 'Queue position must be an integer.'
        target = max(0, min(target, len(pending) - 1))
        if target == current:
            return True, None
        previous_orders = {dl.id: dl.queue_order for dl in pending}
        item = pending.pop(current)
        pending.insert(target, item)
        for index, dl in enumerate(pending, start=1):
            dl.queue_order = index
        self._next_order = max(self._next_order, len(pending))
        if not self._persist_locked():
            for dl in pending:
                dl.queue_order = previous_orders[dl.id]
            return False, self._persistence_error
        return True, None

    def move_pending_by(self, dl_id, offset):
        with self._lock:
            pending = self._ordered_pending_locked()
            current = next((index for index, dl in enumerate(pending) if dl.id == dl_id), None)
            if current is None:
                return False, 'Only pending downloads can be reordered.'
            ok, error = self._move_pending_locked(dl_id, current + int(offset))
        if ok:
            self.progress_updated.emit()
        return ok, error

    def cancel(self, dl_id):
        with self._lock:
            dl = self.downloads.get(dl_id)
            if not dl or dl.status in DOWNLOAD_TERMINAL_STATES:
                return False
            dl.status = "cancelled"
            dl.error = "Cancelled by user."
            dl._cookies = None
            if dl.cookies_file and dl.process is None:
                try:
                    Path(dl.cookies_file).unlink(missing_ok=True)
                except Exception:
                    # reason: cancellation cleanup races with worker teardown and is idempotent
                    pass
                dl.cookies_file = None
            dl.mark_terminal()
            proc = dl.process
            was_running = dl_id in self._running_ids
            self._persist_locked()
        if proc and proc.poll() is None:
            def terminate():
                try:
                    self._dependencies['terminate_process_tree'](proc)
                except Exception as error:
                    self._dependencies['write_persistent_log'](
                        f"WARNING: cancelled-download termination failed: {error}"
                    )
            threading.Thread(target=terminate, daemon=True).start()
        if not was_running:
            # No worker will reach _record_terminal_download for a queued or
            # pending item cancelled before launch.
            self._sweep_download_intermediates(dl)
        self.progress_updated.emit()
        if not was_running:
            self._schedule()
        return True

    def cancel_all(self):
        to_sweep = []
        with self._lock:
            # Keep the last durable unfinished snapshot intact. A new process
            # will restore those records paused/needs-auth rather than silently
            # starting them or losing user intent.
            self._closing = True
            backoff_timer = self._host_backoff_timer
            self._host_backoff_timer = None
            self._host_backoff_timer_due = 0.0
            active = [d for d in self.downloads.values() if d.status in DOWNLOAD_ACTIVE_STATES]
        if backoff_timer is not None:
            backoff_timer.cancel()
        for dl in active:
            dl.status = "cancelled"
            dl.error = "Cancelled (app shutdown)."
            dl._cookies = None
            dl.mark_terminal()
            proc = dl.process
            if proc is None and dl.id not in self._running_ids:
                to_sweep.append(dl)
            if proc and proc.poll() is None:
                try:
                    self._dependencies['terminate_process_tree'](proc)
                except Exception as e:
                    self._dependencies['write_persistent_log'](
                        f"WARNING: cancel_all termination failed: {e}"
                    )
        for dl in to_sweep:
            self._sweep_download_intermediates(dl)

    def active_count(self):
        with self._lock:
            queued_activity = len(self._running_ids)
        activity_counter = self._dependencies.get('ytdlp_activity_count')
        if not callable(activity_counter):
            return queued_activity
        try:
            process_activity = max(0, int(activity_counter() or 0))
        except Exception:  # noqa: BLE001
            # An unknown activity state must fail closed for updater guards.
            process_activity = queued_activity + 1
        return max(queued_activity, process_activity)

    def _release_ytdlp_activity(self, process):
        """Drop a registry reservation once a yt-dlp call has ended."""
        release = self._dependencies.get('release_ytdlp_activity')
        if not callable(release) or process is None:
            return
        try:
            release(process)
        except Exception as error:  # noqa: BLE001
            self._dependencies['write_persistent_log'](
                f"WARNING: yt-dlp activity cleanup failed: {error}"
            )

    def maybe_refresh_ytdlp(self, reason):
        """Open the throttled, race-safe yt-dlp auto-update window from the
        download path.

        Called when the queue drains to idle — the moment no yt-dlp.exe is in
        flight. The updater it delegates to is throttled (one check per interval),
        stages a *sibling* copy, verifies ``--version``, keeps a byte-verified
        rollback, and only atomically swaps the live binary when no download is
        running — so an in-flight download is never blocked or corrupted. This
        is what keeps yt-dlp current WITHOUT shipping a new extension or
        companion build: fresh yt-dlp releases land automatically the next time
        the user downloads, or the moment the queue goes idle. Best-effort and
        fully swallowed — an update hiccup must never fail a download."""
        hook = self._dependencies.get('maybe_auto_update_ytdlp')
        if hook is None:
            return
        try:
            hook(self.config, self.active_count)
        except Exception as exc:  # noqa: BLE001
            try:
                self._dependencies['write_persistent_log'](
                    f"yt-dlp auto-update trigger ({reason}) failed: {exc}"
                )
            except Exception:
                # reason: logging must not turn an update hiccup into a crash
                pass

    def list_formats(self, url, timeout=60):
        """Return `(summary, error)` of the real available formats for a single
        media URL via `yt-dlp -J`, run under the same extractor + JS-runtime
        conditions as an actual download so the listing matches what would be
        downloaded."""
        url, err = self._dependencies['normalize_url'](url)
        if err:
            return None, err
        if not self._dependencies['is_supported_media_url'](url):
            return None, (
                'Astra Downloader only lists formats for public media URLs.'
            )
        if not self._formats_gate.acquire(blocking=False):
            return None, self.FORMATS_BUSY_MESSAGE
        try:
            return self._list_formats_gated(url, timeout)
        finally:
            self._formats_gate.release()

    def _list_formats_gated(self, url, timeout):
        ytdlp = str(self._dependencies['YTDLP_PATH']())
        args = [ytdlp, '--ignore-config', '--no-colors', '--no-warnings',
                '--no-playlist', '-J', '--skip-download']
        args += self._dependencies['build_youtube_extractor_args'](url)
        runtime = self._dependencies['probe_javascript_runtime'](
            configured_runtime=self.config.get('JavaScriptRuntime', 'auto')
        )
        args += self._dependencies['build_javascript_runtime_args'](runtime)
        identity_args, identity_cleanup = self._build_probe_identity_args(url)
        args += identity_args
        args.append(url)
        try:
            env = self._dependencies['_build_subprocess_env']()
            proc = self._dependencies['spawn_ytdlp'](
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                creationflags=self._dependencies['CREATE_NO_WINDOW'],
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            identity_cleanup()
            return None, f'Could not start yt-dlp: {exc}'
        try:
            out, errout = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                self._dependencies['terminate_process_tree'](proc)
            except Exception as error:
                # reason: best-effort kill; process may already be gone
                self._dependencies['write_persistent_log'](
                    f"WARNING: format-probe termination failed: {error}"
                )
            return None, 'Timed out while listing formats.'
        finally:
            identity_cleanup()
            self._release_ytdlp_activity(proc)
        if proc.returncode != 0:
            tail = [ln.strip() for ln in (errout or '').splitlines() if ln.strip()]
            msg = next((ln for ln in reversed(tail) if not _is_benign_failure_noise(ln)), '')
            return None, (msg or 'yt-dlp could not list formats.')[:240]
        try:
            info = json.loads(out)
        except Exception:  # noqa: BLE001
            return None, 'Could not parse yt-dlp output while listing formats.'
        return summarize_ytdlp_formats(info), None

    def import_site_login_from_browser(self, site, browser, profile=None,
                                       timeout=90):
        """Read one site's cookies out of an installed browser via yt-dlp.

        yt-dlp writes the loaded jar to `--cookies` even when the URL itself
        cannot be extracted, so this needs no downloadable page — the site
        address alone is enough. The extracted jar is filtered to the target
        site before anything is stored.
        """
        key = site_login_key(site)
        if not key:
            return None, 'Enter the site address you signed in to, such as x.com.'
        browser_args = build_browser_cookie_args(browser, profile)
        if not browser_args:
            return None, (
                'Choose one of the supported browsers: '
                + ', '.join(SITE_LOGIN_BROWSERS) + '.'
            )
        install_dir = Path(self._dependencies['INSTALL_DIR']())
        staging = install_dir / f".cookies.import.{uuid.uuid4().hex}.txt"
        args = [
            str(self._dependencies['YTDLP_PATH']()), '--ignore-config',
            '--no-colors', '--skip-download', '--simulate', '--no-playlist',
        ]
        args += browser_args
        args += ['--cookies', str(staging), f'https://{key}/']
        try:
            proc = self._dependencies['spawn_ytdlp'](
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                creationflags=self._dependencies['CREATE_NO_WINDOW'],
                env=self._dependencies['_build_subprocess_env'](),
            )
        except Exception as exc:  # noqa: BLE001
            return None, f'Could not start yt-dlp: {exc}'
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                self._dependencies['terminate_process_tree'](proc)
            except Exception as error:
                # reason: best-effort kill; the reader may already have exited
                self._dependencies['write_persistent_log'](
                    f"WARNING: cookie import termination failed: {error}"
                )
            self._unlink_quietly(staging)
            return None, 'Timed out while reading cookies from the browser.'
        try:
            try:
                text = staging.read_text(encoding='utf-8')
            except OSError:
                text = ''
            explained = describe_browser_cookie_failure(output)
            if explained:
                return None, explained
            if not text.strip():
                return None, (
                    'The browser returned no cookies. Sign in to the site in '
                    'that browser and profile first.'
                )
            result, error = self.site_logins.import_netscape_text(
                key, text, source=f'browser:{str(browser).strip().lower()}'
            )
            if error and 'None of those cookies belong to' in error:
                return None, (
                    f'That browser profile holds no cookies for {key}. Sign in '
                    'to the site there, or export a cookies.txt file instead.'
                )
            return result, error
        finally:
            # The staging jar holds every cookie the browser exposed — far more
            # than the one site being stored. It never outlives this call.
            self._release_ytdlp_activity(proc)
            self._unlink_quietly(staging)

    def test_site_login(self, site, timeout=SITE_LOGIN_TEST_TIMEOUT_SECONDS):
        """Verify one stored cookie or credential sign-in with a bounded probe."""
        key = site_login_key(site)
        if not key:
            return None, 'Enter a valid site address before testing its sign-in.'
        try:
            timeout = min(float(timeout), float(SITE_LOGIN_TEST_TIMEOUT_SECONDS))
        except (TypeError, ValueError):
            timeout = float(SITE_LOGIN_TEST_TIMEOUT_SECONDS)
        timeout = max(1.0, timeout)
        install_dir = Path(self._dependencies['INSTALL_DIR']())
        staging = install_dir / f".cookies.test.{uuid.uuid4().hex}.txt"
        try:
            try:
                jar_path, stored_key = self.site_logins.export_jar_for_site(
                    f'https://{key}/', staging
                )
            except Exception as exc:  # noqa: BLE001
                return None, f'Could not prepare the sign-in test: {exc}'
            credentials = None
            if not jar_path or stored_key != key:
                credentials = self.site_logins.credentials_for_url(f'https://{key}/')
            if (not jar_path or stored_key != key) and not credentials:
                return None, (
                    f'No usable stored sign-in was found for {key}. '
                    'Import the cookies again, then test it.'
                )
            probe = Download('__site-login-test__', f'https://{key}/')
            probe._credentials = credentials
            auth_args = (
                ['--cookies', str(jar_path)] if jar_path and stored_key == key
                else build_site_login_credential_args(credentials)
            )
            args = [
                str(self._dependencies['YTDLP_PATH']()), '--ignore-config',
                '--no-colors', '--no-warnings', '--skip-download', '--simulate',
                '--dump-single-json', '--no-playlist', '--socket-timeout', '10',
                '--retries', '1', '--fragment-retries', '1',
                '--extractor-retries', '1', *auth_args,
                *build_network_workaround_args(self.config),
                f'https://{key}/',
            ]
            try:
                proc = self._dependencies['spawn_ytdlp'](
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=self._dependencies['CREATE_NO_WINDOW'],
                    env=self._dependencies['_build_subprocess_env'](),
                )
            except Exception as exc:  # noqa: BLE001
                return None, f'Could not start the sign-in test: {exc}'
            try:
                _output, error_output = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    self._dependencies['terminate_process_tree'](proc)
                except Exception as error:
                    # reason: best-effort kill; the test is already bounded
                    self._dependencies['write_persistent_log'](
                        f'WARNING: sign-in test termination failed: {error}'
                    )
                return None, f'Sign-in test timed out for {key}.'
            finally:
                self._release_ytdlp_activity(proc)
            if proc.returncode != 0:
                lines = [
                    line.strip() for line in (error_output or '').splitlines()
                    if line.strip()
                ]
                detail = lines[-1] if lines else 'yt-dlp rejected the stored session.'
                detail = _redact_download_secrets(detail, probe)
                return None, f'Sign-in test failed for {key}: {detail[:200]}'
            return {
                'site': key,
                'ok': True,
                'message': f'yt-dlp reached {key} with the stored sign-in.',
            }, None
        finally:
            self._unlink_quietly(staging)

    def _unlink_quietly(self, path):
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as error:
            self._dependencies['write_persistent_log'](
                f"WARNING: temporary cookie file cleanup failed: {error}"
            )

    def _build_probe_identity_args(self, url):
        """Build the auth, proxy and browser-fingerprint args for a probe.

        A probe is a real yt-dlp invocation, so it must see the same identity
        as the eventual download. Stored cookies are exported to a transient
        jar because yt-dlp may update ``--cookies`` on exit; the cleanup
        callback keeps that copy out of the install directory after the probe.
        The temporary ``Download`` object deliberately reuses the download
        path's cookie-scope predicate rather than duplicating its rules.
        """
        args = []
        effective_config = self._effective_config_for_url(url)
        proxy = effective_config.get("Proxy", "")
        if proxy and re.match(r'^(socks(?:4a?|5h?)?|https?)://', proxy):
            args += ['--proxy', proxy]
        args += build_network_workaround_args(effective_config)

        probe = Download("__probe__", url)
        jar_path = Path(self._dependencies['INSTALL_DIR']()) / (
            f".cookies.probe.{uuid.uuid4().hex}.txt"
        )
        try:
            exported, scope = self.site_logins.export_jar_for_site(url, jar_path)
        except Exception as error:  # noqa: BLE001
            self._dependencies['write_persistent_log'](
                f"WARNING: probe sign-in export failed: {error}"
            )
            exported, scope = None, ""
        if exported:
            probe.cookies_file = exported
            probe.cookies_scope = scope

        cookie_path = probe.cookies_file
        if cookie_path and self._cookie_jar_matches_target(probe):
            args += ['--cookies', cookie_path]
        else:
            cookie_path = None
            probe._credentials = self.site_logins.credentials_for_url(url)
            args += build_site_login_credential_args(probe._credentials)

        configured_target = str(
            effective_config.get('ImpersonateTarget', '') or ''
        ).strip()
        available_targets = (
            self._dependencies['probe_impersonate_targets']()
            if configured_target else []
        )
        args += build_impersonate_args(effective_config, available_targets)

        def cleanup():
            if cookie_path:
                self._unlink_quietly(cookie_path)
            elif exported:
                self._unlink_quietly(exported)

        return args, cleanup

    def preview_playlist(self, url, timeout=60):
        """Return a bounded flat-playlist preview without downloading media."""
        url, err = self._dependencies['normalize_url'](url)
        if err:
            return None, err
        if not self._dependencies['is_supported_media_url'](url):
            return None, 'Enter a public playlist URL.'
        if not is_playlist_url(url):
            return None, 'Enter a playlist URL.'
        if not self._formats_gate.acquire(blocking=False):
            return None, self.PLAYLIST_BUSY_MESSAGE
        try:
            return self._preview_playlist_gated(url, timeout)
        finally:
            self._formats_gate.release()

    def _preview_playlist_gated(self, url, timeout):
        ytdlp = str(self._dependencies['YTDLP_PATH']())
        args = [
            ytdlp, '--ignore-config', '--no-colors', '--no-warnings',
            '--flat-playlist', '--dump-single-json', '--skip-download',
            '--playlist-end', str(PLAYLIST_PREVIEW_LIMIT + 1),
        ]
        args += self._dependencies['build_youtube_extractor_args'](url)
        runtime = self._dependencies['probe_javascript_runtime'](
            configured_runtime=self.config.get('JavaScriptRuntime', 'auto')
        )
        args += self._dependencies['build_javascript_runtime_args'](runtime)
        identity_args, identity_cleanup = self._build_probe_identity_args(url)
        args += identity_args
        args.append(url)
        try:
            proc = self._dependencies['spawn_ytdlp'](
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=self._dependencies['CREATE_NO_WINDOW'],
                env=self._dependencies['_build_subprocess_env'](),
            )
        except Exception as exc:  # noqa: BLE001
            identity_cleanup()
            return None, f'Could not start yt-dlp: {exc}'
        try:
            out, errout = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                self._dependencies['terminate_process_tree'](proc)
            except Exception as error:
                self._dependencies['write_persistent_log'](
                    f"WARNING: playlist-probe termination failed: {error}"
                )
            return None, 'Timed out while previewing the playlist.'
        finally:
            identity_cleanup()
            self._release_ytdlp_activity(proc)
        if proc.returncode != 0:
            tail = [line.strip() for line in (errout or '').splitlines() if line.strip()]
            message = next(
                (line for line in reversed(tail) if not _is_benign_failure_noise(line)),
                '',
            )
            return None, (message or 'yt-dlp could not preview the playlist.')[:240]
        try:
            info = json.loads(out)
        except Exception:  # noqa: BLE001
            return None, 'Could not parse yt-dlp output while previewing the playlist.'
        return summarize_ytdlp_playlist(info), None

    def exists(self, dl_id):
        """True while the download id is still tracked in the active queue."""
        with self._lock:
            return dl_id in self.downloads

    def status_of(self, dl_id, default=None):
        """Return the download's status string, or ``default`` when unknown."""
        with self._lock:
            dl = self.downloads.get(dl_id)
            return dl.status if dl else default

    def snapshot_of(self, dl_id):
        """Return a ``to_dict()`` snapshot taken under the manager lock, or None."""
        with self._lock:
            dl = self.downloads.get(dl_id)
            return dl.to_dict() if dl else None

    def pending_count(self):
        with self._lock:
            return sum(1 for d in self.downloads.values()
                       if d.status in DOWNLOAD_PENDING_STATES)

    def snapshot(self):
        with self._lock:
            return sorted(
                self.downloads.values(),
                key=lambda dl: (dl.queue_order, dl.start_time, dl.id),
            )

    def queue_payload(self):
        with self._lock:
            pending = self._ordered_pending_locked()
            pending_positions = {dl.id: index for index, dl in enumerate(pending)}
            ordered = sorted(
                self.downloads.values(),
                key=lambda item: (item.queue_order, item.start_time, item.id)
            )
            # Take the durable queue snapshot and capacity under the lock, but
            # resolve recovery actions after releasing it. A GUI/API refresh
            # must never hold the manager lock while evaluating a precondition.
            payloads = [(dl, dl.to_dict()) for dl in ordered]
            capacity = self._capacity_locked()
            persistence_error = self._persistence_error or None
            history_error = self._history_error or None
        items = []
        for dl, payload in payloads:
            # Download.to_dict answers this from the code alone; only the
            # manager can see whether the recovery action has been done.
            payload['retryable'] = self.is_retryable(dl)
            if dl.id in pending_positions:
                payload['queuePosition'] = pending_positions[dl.id]
            items.append(payload)
        return {
            'downloads': items,
            'count': len(items),
            'capacity': capacity,
            'persistenceError': persistence_error,
            'historyError': history_error,
        }

    def _sweep_orphaned_download_intermediates(self):
        """Remove staging directories whose ids are no longer in the queue.

        A process killed during a transfer cannot reach the terminal cleanup
        below. On the next startup, retain only directories for records that
        were durably restored; everything else is app-owned scratch. Resolved
        path checks keep a junction or symlink from turning cleanup into a
        recursive delete outside the staging root.
        """
        if self.config.get("KeepIntermediateFiles", False):
            return
        try:
            root = (
                Path(self._dependencies['INSTALL_DIR']())
                / DOWNLOAD_INTERMEDIATE_DIRNAME
            ).resolve()
            if not root.is_dir():
                return
            protected = {
                self._download_intermediate_dir(download).resolve()
                for download in self.downloads.values()
            }
            for candidate in root.iterdir():
                try:
                    if candidate.is_symlink():
                        # Do not follow reparse points or links during a
                        # startup sweep; a human can remove an ambiguous link
                        # after reviewing the log.
                        continue
                    resolved = candidate.resolve()
                    if resolved.parent != root or resolved in protected:
                        continue
                    if not candidate.is_dir():
                        continue
                    shutil.rmtree(candidate)
                    self._dependencies['write_persistent_log'](
                        f"Removed orphaned download staging directory: {candidate}"
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    # reason: orphan cleanup is best effort and must not keep
                    # the downloader from starting after a locked stale job
                    self._dependencies['write_persistent_log'](
                        f"WARNING: could not remove orphaned download staging "
                        f"directory {candidate}: {error}"
                    )
        except (OSError, RuntimeError, ValueError) as error:
            # reason: the staging root may not exist or may be unavailable
            self._dependencies['write_persistent_log'](
                f"WARNING: could not scan download staging directories: {error}"
            )

    def _sweep_download_intermediates(self, dl):
        """Remove one download's staging and legacy intermediate files.

        New runs stage those files in a stable, per-download directory under
        the app install root. Every terminal state sweeps that directory unless
        the user explicitly enabled ``KeepIntermediateFiles`` for diagnosis.
        The legacy destination sweep stays in place for intermediates created
        by older versions of the app.
        """
        if self.config.get("KeepIntermediateFiles", False):
            return
        staging = self._download_intermediate_dir(dl)
        try:
            if staging.is_dir():
                shutil.rmtree(staging)
                self._dependencies['write_persistent_log'](
                    f"Download {dl.id}: removed its intermediate staging directory."
                )
        except OSError:
            # reason: staging cleanup is best effort; the finished file is the result
            pass
        final = str(dl.filename or '').strip()
        if not final:
            return
        try:
            final_path = Path(final)
            folder = final_path.parent
            if not folder.is_dir():
                return
            stem = final_path.stem
            # `Title.mp4` -> `Title.mp4.part`, `Title.mp4.ytdl`, `Title.f137.mp4`
            patterns = (
                f"{glob.escape(final_path.name)}.part",
                f"{glob.escape(final_path.name)}.part-Frag*",
                f"{glob.escape(final_path.name)}.ytdl",
                f"{glob.escape(stem)}.f[0-9]*.*",
            )
            removed = 0
            for pattern in patterns:
                for candidate in folder.glob(pattern):
                    if candidate == final_path or not candidate.is_file():
                        continue
                    try:
                        candidate.unlink()
                        removed += 1
                    except OSError:
                        # reason: a leftover we cannot delete is not a download
                        # failure; the file the user asked for is already there
                        pass
            if removed:
                self._dependencies['write_persistent_log'](
                    f"Download {dl.id}: removed {removed} intermediate file(s)."
                )
        except OSError:
            # reason: sweeping is cleanup, never part of the download result
            pass

    # Failure codes whose fix is an action the user performs outside the queue.
    # They are not in DOWNLOAD_RETRYABLE_ERROR_CODES because retrying before the
    # action is done just reproduces the failure — but once it *is* done the
    # download is perfectly retryable, and nothing used to re-check.
    _RECOVERABLE_PRECONDITIONS = {
        'js-runtime-missing': 'runtime',
        'js-runtime-unsupported': 'runtime',
        'js-runtime-unverified': 'runtime',
        'ejs-runtime-not-ready': 'runtime',
        'deno-runtime-missing': 'runtime',
        'deno-runtime-unsupported': 'runtime',
        'ffmpeg-missing-or-stale': 'ffmpeg',
        'sign-in-required': 'sign-in',
        'blocked-by-site': 'impersonate',
        'geo-restricted': 'geo',
    }

    # The GUI asks this for every failed card on every refresh, and the
    # sign-in branch reads the site-login index off disk. Two seconds is short
    # enough that Retry appears almost immediately after the user installs a
    # runtime, and long enough that a queue of failed cards cannot turn a
    # 500 ms UI tick into a burst of index reads.
    _PRECONDITION_TTL_SECONDS = 2.0

    def recovery_precondition(self, dl):
        """Whether the thing this failure was waiting for has been done.

        Returns (satisfied, still_missing_message). A code with no known
        precondition is reported as unsatisfied so behaviour cannot loosen by
        accident when a new failure code is added.
        """
        requirement = self._RECOVERABLE_PRECONDITIONS.get(dl.error_code)
        if requirement is None:
            return False, 'This failure needs its recovery action before it can be retried.'
        cache_key = (requirement, dl.url if requirement == 'sign-in' else '',
                     bool(dl.requires_auth))
        now = time.time()
        with self._precondition_cache_lock:
            cached = self._precondition_cache.get(cache_key)
        if cached is not None and now - cached[0] < self._PRECONDITION_TTL_SECONDS:
            return cached[1]
        answer = self._evaluate_recovery_precondition(dl, requirement)
        with self._precondition_cache_lock:
            self._precondition_cache[cache_key] = (now, answer)
        return answer

    def _evaluate_recovery_precondition(self, dl, requirement):
        if requirement == 'runtime':
            with self._readiness_lock:
                readiness = dict(self._readiness_snapshot)
            configured_runtime = str(
                self.config.get('JavaScriptRuntime', 'auto') or 'auto'
            ).strip().lower()
            if (
                not readiness.get('updatedAt')
                or (
                    readiness.get('configuredRuntime')
                    and readiness.get('configuredRuntime') != configured_runtime
                )
                or not isinstance(readiness.get('runtime'), dict)
            ):
                return False, (
                    'The JavaScript runtime is still being checked. Try again '
                    'in a moment.'
                )
            runtime = readiness['runtime']
            if runtime.get('supported') is True and runtime.get('ejsReady') is True:
                return True, None
            return False, (
                'A supported JavaScript runtime is still not ready. Install or '
                'repair Deno or Node, then retry.'
            )
        if requirement == 'ffmpeg':
            try:
                ffmpeg = Path(self._dependencies['FFMPEG_PATH']())
                ready = ffmpeg.exists() and ffmpeg.stat().st_size > 0
            except OSError:
                ready = False
            if ready:
                return True, None
            return False, 'FFmpeg is still missing. Refresh it from Settings, then retry.'
        if requirement == 'impersonate':
            if str(self.config.get('ForceIPVersion', '') or '').strip().lower() == 'ipv4':
                return True, None
            target = self._dependencies['normalize_impersonate_target'](
                self.config.get('ImpersonateTarget', '')
            )
            if not target:
                return False, (
                    'Choose a browser to imitate in Settings — the usual remedy '
                    'for this refusal — then retry.'
                )
            with self._readiness_lock:
                available = self._readiness_snapshot.get('impersonateTargets')
            if available is None:
                return False, (
                    'Browser capability information is still being checked. '
                    'Try again in a moment.'
                )
            if target and target in set(available):
                return True, None
            return False, (
                f'The installed yt-dlp cannot imitate {target}. Choose a '
                'different browser in Settings, then retry.'
            )
        if requirement == 'geo':
            workaround_args = build_network_workaround_args(self.config)
            if '--xff' in workaround_args or '--geo-verification-proxy' in workaround_args:
                return True, None
            return False, (
                'Set a country code or CIDR block for `--xff`, or a geo '
                'verification proxy, in Settings, then retry.'
            )
        if requirement == 'sign-in':
            if dl.requires_auth:
                # The extension's YouTube bridge supplies cookies per attempt;
                # `retry(cookies=...)` is the path for that, not this one.
                return False, (
                    'Fresh sign-in is required. Retry from Astra Deck so the '
                    'browser can authorize this download.'
                )
            if self.site_logins.has_login_for(dl.url):
                return True, None
            return False, (
                'No stored sign-in covers this site yet. Add one on the '
                'Sign-ins page, then retry.'
            )
        return False, 'This failure needs its recovery action before it can be retried.'

    def is_retryable(self, dl):
        """Whether Retry would be accepted for this download right now."""
        if dl.status == 'skipped':
            return True
        if (
            dl.status == 'complete'
            and dl.error_code in DOWNLOAD_SUBTITLE_RETRYABLE_ERROR_CODES
        ):
            return True
        if dl.status != 'failed':
            return False
        if dl.error_code in DOWNLOAD_RETRYABLE_ERROR_CODES:
            return True
        return self.recovery_precondition(dl)[0]

    def persistence_notice(self):
        """The durability problem the user most needs to know about, if any.

        Every persistence caller but one already reports its failure through a
        return value the caller checks. The history write after a terminal
        outcome cannot: the download really did finish, so there is nothing to
        fail and no return path to check it. This is where that failure becomes
        visible.
        """
        with self._lock:
            return self._persistence_error or self._history_error or ''

    def cleanup_old(self):
        cutoff = time.time() - 300  # 5 min
        with self._lock:
            to_remove = [k for k, d in self.downloads.items()
                         if d.status in DOWNLOAD_TERMINAL_STATES
                         and (getattr(d, 'finished_time', None) or d.start_time) < cutoff]
            for k in to_remove:
                del self.downloads[k]


DownloadManager = DownloadManagerCore


_OWNED_EXPORTS = {
    "Download", "build_video_format_args", "is_playlist_url",
    "build_network_workaround_args",
    "download_error_payload", "classify_download_failure",
    "apply_download_failure_classification", "DOWNLOAD_FAILURE_RECOVERY",
    "po_provider_nudge_advice", "PO_PROVIDER_NUDGE_CODES", "PO_PROVIDER_NUDGE",
    "summarize_ytdlp_formats", "summarize_ytdlp_playlist",
    "DOWNLOAD_ACTIVE_STATES", "DOWNLOAD_RUNNING_STATES",
    "DOWNLOAD_PENDING_STATES", "DOWNLOAD_TERMINAL_STATES",
    "DOWNLOAD_RETRYABLE_ERROR_CODES", "MAX_CONCURRENT", "MAX_QUEUED_TOTAL",
    "DOWNLOAD_STALL_TIMEOUT_SECONDS", "DOWNLOAD_WATCHDOG_POLL_SECONDS",
    "write_cookies_netscape", "cleanup_stale_cookie_jars",
    "terminate_process_tree", "build_subprocess_env", "ALLOWED_COOKIE_DOMAINS",
    "DownloadQueueStore", "DownloadManager", "DownloadManagerCore",
    "DOWNLOAD_QUEUE_SCHEMA_VERSION", "PLAYLIST_PREVIEW_LIMIT",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
