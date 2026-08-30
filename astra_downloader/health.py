"""Import-safe runtime health policy and compatibility boundary."""

import email.utils
import hashlib
import hmac
import os
import re
import subprocess
import threading
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from ._compat import make_legacy_resolver
except ImportError:  # Flat source-path compatibility.
    from _compat import make_legacy_resolver


__all__ = (
    "get_ytdlp_version", "get_ffmpeg_version", "_run_captured",
    "parse_impersonate_targets", "ImpersonateTargetsProbe",
    "IMPERSONATE_TARGET_RE",
    "parse_extractor_list", "ExtractorListProbe",
    "EXTRACTOR_LIST_TIMEOUT_SECONDS",
    "probe_po_token_provider", "reset_po_token_provider_cache",
    "probe_deno_runtime",
    "QUICKJS_MIN_VERSION", "JS_RUNTIMES",
    "probe_javascript_runtime", "build_javascript_runtime_args",
    "reset_deno_runtime_cache", "provision_deno", "_parse_ytdlp_release_date",
    "ytdlp_needs_external_runtime", "YTDLP_EXTERNAL_RUNTIME_CUTOFF",
    "DENO_MIN_VERSION", "DENO_SECURITY_MIN_VERSION", "NODE_MIN_VERSION", "parse_ffmpeg_major",
    "parse_ffmpeg_snapshot_date", "probe_whisper_runtime",
    "check_ffmpeg_capabilities", "reset_ffmpeg_capabilities_cache",
    "build_youtube_extractor_args", "is_youtube_url", "should_check_ytdlp_update",
    "maybe_auto_update_ytdlp", "_run_ytdlp_self_update",
    "read_update_recovery_status", "atomic_copy_verified",
    "DownloadedExecutableIntegrityError", "verify_adjacent_release_sidecar",
    "parse_companion_version_source", "fetch_latest_companion_version",
    "validate_companion_update_binary", "probe_companion_update_binary",
    "read_last_installed_update_sha256", "record_last_installed_update_sha256",
    "schedule_companion_update_restart", "schedule_companion_process_exit",
    "_compare_semver", "evaluate_sabr_support", "SABR_NATIVE_MIN_VERSION",
    "ExecutableVersionProbe", "parse_ytdlp_version_output",
    "parse_ffmpeg_version_output",
    "FfmpegCapabilitiesProbe",
    "parse_javascript_runtime_version", "javascript_runtime_supported",
    "javascript_runtime_security_supported",
    "probe_javascript_execution", "evaluate_javascript_runtime",
    "REQUIRED_FFMPEG_FILTERS", "missing_ffmpeg_filters",
    "YTDLP_STALE_AFTER_DAYS", "evaluate_preflight_checks",
    "probe_output_folder", "probe_state_location",
    "parse_http_date_epoch", "measure_system_clock_offset",
    "SYSTEM_CLOCK_WARN_SECONDS", "SYSTEM_CLOCK_ERROR_SECONDS",
    "SITE_LONG_TERM_REFUSAL_SECONDS",
    "MANAGED_BINARY_NAMES", "MANAGED_BINARY_SECURITY_FLOORS",
    "evaluate_managed_binary_pin", "filter_managed_binary_pins",
    "managed_binary_pin",
)

YTDLP_EXTERNAL_RUNTIME_CUTOFF = (2026, 4, 1)
DENO_MIN_VERSION = "2.3.0"
# Deno's functional floor is set by yt-dlp's EJS support. Keep the security
# floor separate so an installed runtime that still works is refreshed when it
# falls behind a known-fixed release.
DENO_SECURITY_MIN_VERSION = "2.8.1"
NODE_MIN_VERSION = "22.0.0"
# QuickJS is the smallest runtime yt-dlp accepts and the one this app can
# provision without asking the user to install anything: a 2 MB executable
# against Deno's 40 MB archive. The floor is the version the app pins and
# ships, because that is the only one this project has verified end-to-end —
# a test keeps the two in step.
QUICKJS_MIN_VERSION = "0.16.1"

# The local transcription path normalises input audio through this filter.
# Keep the pre-flight requirement deliberately small: the rest of the media
# path delegates format selection to yt-dlp and does not need a filter audit.
REQUIRED_FFMPEG_FILTERS = ("aformat",)
YTDLP_STALE_AFTER_DAYS = 30
RELEASE_SIDECAR_MAX_BYTES = 4096


class DownloadedExecutableIntegrityError(RuntimeError):
    """A present release sidecar does not authenticate the running image."""

    code = "download-integrity-check-failed"


def _release_integrity_error(detail):
    return DownloadedExecutableIntegrityError(
        f"Astra Downloader download integrity check failed "
        f"({DownloadedExecutableIntegrityError.code}): {detail} "
        "Delete the executable and its SHA-256 file, then download both again."
    )


def verify_adjacent_release_sidecar(
    executable, *, max_sidecar_bytes=RELEASE_SIDECAR_MAX_BYTES,
):
    """Verify ``<executable>.sha256`` when that release file is present.

    Release downloads carry a small sha256sum-style manifest. Source runs,
    managed installs, and extracted one-folder builds normally have no such
    sibling, so absence deliberately preserves their existing startup path.
    A present sidecar fails closed when it is unreadable, malformed, names a
    different file, or disagrees with the running image.
    """
    executable = Path(executable)
    sidecar = executable.with_name(executable.name + ".sha256")
    try:
        sidecar_size = sidecar.stat().st_size
    except FileNotFoundError:
        return False
    except OSError as error:
        raise _release_integrity_error(
            f"the adjacent sidecar could not be inspected ({error})."
        ) from error
    limit = max(1, int(max_sidecar_bytes))
    if sidecar_size <= 0 or sidecar_size > limit:
        raise _release_integrity_error("the adjacent sidecar has an invalid size.")
    try:
        with sidecar.open("rb") as stream:
            payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise _release_integrity_error(
                "the adjacent sidecar grew beyond the allowed size."
            )
        text = payload.decode("ascii").strip()
    except (OSError, UnicodeError) as error:
        raise _release_integrity_error(
            f"the adjacent sidecar could not be read ({error})."
        ) from error
    match = re.fullmatch(r"([0-9A-Fa-f]{64})[ \t]+\*?([^\r\n]+)", text)
    if not match or Path(match.group(2).strip()).name.casefold() != executable.name.casefold():
        raise _release_integrity_error(
            "the adjacent sidecar is malformed or names a different file."
        )
    try:
        digest = hashlib.sha256()
        with executable.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise _release_integrity_error(
            f"the running executable could not be hashed ({error})."
        ) from error
    expected = match.group(1).lower()
    actual = digest.hexdigest().lower()
    if not hmac.compare_digest(expected, actual):
        raise _release_integrity_error(
            f"the sidecar expected {expected[:12]} but the executable is "
            f"{actual[:12]}."
        )
    return True

# The runtimes yt-dlp accepts that this app knows how to probe and select.
# yt-dlp also lists `bun`; it is absent here because nothing provisions it and
# an unprobed name would be offered without evidence it works.
JS_RUNTIMES = ('deno', 'node', 'quickjs')
_JS_RUNTIME_FLOOR_ORDER = ('deno', 'node', 'quickjs')


def _runtime_minimum(runtime, deno_min, node_min, quickjs_min):
    return dict(zip(
        _JS_RUNTIME_FLOOR_ORDER, (deno_min, node_min, quickjs_min)
    )).get(runtime, deno_min)

YOUTUBE_HOSTS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')


def is_youtube_url(url):
    """Return whether a URL points at a supported YouTube property.

    The host is parsed, never string-matched. This predicate decides which
    cookie jar is handed to a yt-dlp process on a `--cookies` write path, so a
    pattern that can be satisfied by a query string or fragment —
    `https://evil.com?x=.youtube.com/` — hands the YouTube jar to an
    attacker-chosen host. `urlparse().hostname` also strips userinfo, so
    `https://youtube.com@evil.com/` resolves to `evil.com` as it must.
    """
    try:
        parsed = urlparse(str(url or '').strip())
        host = (parsed.hostname or '').lower().rstrip('.')
    except ValueError:
        return False
    if parsed.scheme.lower() not in ('http', 'https') or not host:
        return False
    return any(host == known or host.endswith('.' + known) for known in YOUTUBE_HOSTS)


def _compare_semver(a, b):
    """Compare numeric release segments while conservatively ignoring suffixes."""
    def parts(value):
        if not isinstance(value, str):
            return []
        result = []
        for chunk in value.strip().lstrip('nvV').split('.'):
            digits = ''
            for character in chunk:
                if not character.isdigit():
                    break
                digits += character
            if not digits:
                break
            result.append(int(digits))
            if digits != chunk:
                break
        return result

    left, right = parts(a), parts(b)
    length = max(len(left), len(right))
    left += [0] * (length - len(left))
    right += [0] * (length - len(right))
    return -1 if left < right else 1 if left > right else 0


# Auto-updating the managed binaries is survival — a yt-dlp more than a few
# weeks old stops working on YouTube — but it also silently breaks things that
# were working, and the user has no way to stop it. GDownloader#54 is the
# canonical case: an auto-update removed the nvenc encoder the user relied on.
# A pin freezes one binary; a rollback puts the retained previous copy back
# and pins to it.
MANAGED_BINARY_NAMES = ("yt-dlp", "ffmpeg", "deno", "quickjs", "whisper")

# Only the binaries with a *declared* security floor can refuse a pin, and
# these are the declarations that already exist. yt-dlp and whisper have no
# version floor in this project, so a pin there is accepted — inventing one
# to make the refusal path uniform would be a number nobody measured.
MANAGED_BINARY_SECURITY_FLOORS = {
    "deno": DENO_SECURITY_MIN_VERSION,
    "quickjs": QUICKJS_MIN_VERSION,
}

# yt-dlp ships `2026.08.19`, FFmpeg `8.1.2` and snapshot builds
# `N-125875-g0a1b2c3`, Deno `2.8.1`. One shape covers all of them without
# admitting a path, a flag, or an argument.
MANAGED_BINARY_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")


def evaluate_managed_binary_pin(name, version, floors=None,
                                snapshot_floors=None):
    """Decide whether one managed binary may be pinned to one version.

    Returns the decision rather than raising, because both callers — the
    Settings form and the local API — have to name the reason back to the
    user. An empty version is always allowed: it is how a pin is cleared.

    A master snapshot such as `N-126229-gf101fce22d-20260820` carries no
    semver at all, so where a snapshot floor is declared the embedded build
    date is what the pin is measured against. Without that, pinning the
    ffmpeg the app just installed would be refused as "below 8.1.2".
    """
    name = str(name or "").strip().lower()
    version = str(version or "").strip()
    floors = MANAGED_BINARY_SECURITY_FLOORS if floors is None else floors
    snapshot_floors = snapshot_floors or {}
    if name not in MANAGED_BINARY_NAMES:
        return {
            "ok": False, "name": name, "version": version, "floor": "",
            "reason": "unknown-managed-binary",
            "message": f"{name or 'That tool'} is not a managed binary.",
        }
    if not version:
        return {
            "ok": True, "name": name, "version": "", "floor": "",
            "reason": "", "message": f"{name} follows the published release again.",
        }
    if not MANAGED_BINARY_VERSION_RE.fullmatch(version):
        return {
            "ok": False, "name": name, "version": version, "floor": "",
            "reason": "pin-version-unreadable",
            "message": f"{version!r} is not a version {name} publishes.",
        }
    floor = str(floors.get(name, "") or "")
    if floor:
        snapshot_floor = str(snapshot_floors.get(name, "") or "")
        snapshot_date = (
            parse_ffmpeg_snapshot_date(version) if snapshot_floor else None
        )
        if snapshot_date is not None:
            below = snapshot_date < snapshot_floor
            named_floor = snapshot_floor
        elif not _numeric_release_parts(version):
            return {
                "ok": False, "name": name, "version": version, "floor": floor,
                "reason": "pin-version-unreadable",
                "message": f"{version!r} is not a version {name} publishes.",
            }
        else:
            below = _compare_semver(version, floor) < 0
            named_floor = floor
        if below:
            return {
                "ok": False, "name": name, "version": version,
                "floor": named_floor,
                "reason": "pin-below-security-floor",
                "message": (
                    f"{name} {version} is below the {named_floor} security "
                    f"floor and cannot be pinned. Pin {named_floor} or later."
                ),
            }
    return {
        "ok": True, "name": name, "version": version, "floor": floor,
        "reason": "", "message": f"{name} is pinned to {version}.",
    }


def _numeric_release_parts(value):
    """True when `_compare_semver` can read a release number out of `value`."""
    for chunk in str(value or "").strip().lstrip("nvV").split("."):
        if chunk[:1].isdigit():
            return True
        break
    return False


def filter_managed_binary_pins(raw, floors=None, snapshot_floors=None):
    """Keep only the pins that would be accepted if they were set today.

    A floor can rise between releases, which would otherwise leave a stored
    pin quietly holding a binary below it. Dropping the pin on load is the
    behaviour that fails safe: the binary goes back to the published release.
    """
    pins = {}
    if not isinstance(raw, dict):
        return pins
    for name in MANAGED_BINARY_NAMES:
        decision = evaluate_managed_binary_pin(
            name, raw.get(name), floors=floors, snapshot_floors=snapshot_floors,
        )
        if decision["ok"] and decision["version"]:
            pins[name] = decision["version"]
    return pins


def managed_binary_pin(pins, name):
    """Return the version one binary is pinned to, or ''."""
    if not isinstance(pins, dict):
        return ""
    return str(pins.get(str(name or "").strip().lower(), "") or "").strip()


# The yt-dlp release that first ships the native SABR downloader (PR #13515).
# Until it merges upstream, no version can download SABR-only streams, so SABR
# support is reported as "limited" for every installed version. When it lands,
# set this to that version string and evaluate_sabr_support flips to "supported"
# automatically for capable installs — no other change needed.
SABR_NATIVE_MIN_VERSION = None


def evaluate_sabr_support(ytdlp_version):
    """Real SABR capability of the installed yt-dlp: 'supported' only when the
    installed version can download SABR-only streams (native SABR downloader),
    else 'limited'. Replaces a hardcoded constant so the health/readiness pill
    reflects the actual binary instead of always claiming 'limited'."""
    if not SABR_NATIVE_MIN_VERSION or not ytdlp_version:
        return "limited"
    return "supported" if _compare_semver(str(ytdlp_version), SABR_NATIVE_MIN_VERSION) >= 0 else "limited"


def missing_ffmpeg_filters(output, required=REQUIRED_FFMPEG_FILTERS):
    """Return required FFmpeg filters absent from ``-filters`` output.

    FFmpeg prints a three-character capability flag followed by the filter
    name. Parse only that stable table shape so banners, build metadata, and
    arbitrary stderr text cannot accidentally count as a filter.
    """
    available = set()
    for line in str(output or "").splitlines():
        fields = line.strip().split()
        if len(fields) < 2 or not re.fullmatch(r"[TSC.]{3}", fields[0]):
            continue
        name = fields[1].strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            available.add(name)
    return [name for name in required if str(name) not in available]


# Radarr's 33 named health checks are the field's best-tested list of
# environment problems that present as download problems. Four of them map
# onto failure classes this program has already met: state living where an
# update overwrites it, an output folder that is gone or read-only, a site
# refusing for an extended period rather than one download failing, and a
# clock far enough out to break TLS validation and cookie expiry.
#
# Every probe below is I/O the caller owns; `evaluate_preflight_checks` stays
# pure and never learns a path.
SYSTEM_CLOCK_WARN_SECONDS = 5 * 60
SYSTEM_CLOCK_ERROR_SECONDS = 24 * 60 * 60
SITE_LONG_TERM_REFUSAL_SECONDS = 60 * 60


def probe_output_folder(path):
    """Report whether the configured download folder accepts a write now.

    `.exists()` is not the question. A folder on a disconnected network or
    removable drive, and one whose ACLs were tightened after it was chosen,
    both fail at the first download with a yt-dlp error that names neither
    cause. The probe writes a zero-byte file and removes it.
    """
    text = str(path or '').strip()
    if not text:
        return {'configured': False, 'exists': False, 'writable': False}
    target = Path(text)
    try:
        exists = target.is_dir()
    except OSError:
        # reason: an unreachable UNC path raises rather than returning False
        exists = False
    if not exists:
        return {'configured': True, 'exists': False, 'writable': False}
    probe = target / f'.astra-write-probe-{os.getpid()}'
    try:
        with open(probe, 'wb'):
            pass
    except OSError:
        return {'configured': True, 'exists': True, 'writable': False}
    finally:
        try:
            probe.unlink()
        except OSError:
            # reason: the probe file never existed, or something else removed it
            pass
    return {'configured': True, 'exists': True, 'writable': True}


def _protected_program_roots():
    roots = []
    for name in ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432'):
        value = str(os.environ.get(name, '') or '').strip()
        if value:
            roots.append(value)
    return roots


def probe_state_location(state_dir, *, portable=False, protected_roots=None):
    """Report whether settings, queue and history survive the next update.

    A portable copy keeps its state beside the executable, so replacing that
    folder with a newer build takes the config, queue and history with it.
    A copy unpacked under Program Files has the second half of the problem:
    the writes need elevation, and without it Windows either refuses them or
    redirects them somewhere the next launch will not look.
    """
    roots = _protected_program_roots() if protected_roots is None else list(protected_roots)
    target = Path(str(state_dir or '.'))
    protected = any(_path_is_inside(target, root) for root in roots if str(root or '').strip())
    try:
        exists = target.is_dir()
    except OSError:
        exists = False
    writable = False
    if exists:
        probe = target / f'.astra-state-probe-{os.getpid()}'
        try:
            with open(probe, 'wb'):
                pass
            writable = True
        except OSError:
            writable = False
        finally:
            try:
                probe.unlink()
            except OSError:
                # reason: the probe file never existed, or something else removed it
                pass
    return {
        'portable': bool(portable),
        'exists': exists,
        'writable': writable,
        'protected': protected,
    }


def _path_is_inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def parse_http_date_epoch(value):
    """Return the epoch seconds an RFC 7231 `Date` header names, or None."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return None


def measure_system_clock_offset(date_header, local_epoch=None):
    """Compare this machine's clock against a server's `Date` header.

    Positive means the local clock runs ahead. The header arrives on requests
    the app already makes, so this costs nothing extra, and it is the only
    reference available to a program with no NTP client of its own.
    """
    server_epoch = parse_http_date_epoch(date_header)
    if server_epoch is None:
        return None
    now = time.time() if local_epoch is None else float(local_epoch)
    return {'measured': True, 'offsetSeconds': now - server_epoch}


def _preflight_now_date(value):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            # reason: malformed injected test/adapter time falls back to today
            pass
    return date.today()


def _preflight_check(check_id, name, status, action, message, **details):
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "action": action,
        "message": str(message or "")[:240],
        "details": details,
    }


def evaluate_preflight_checks(*, ytdlp_version=None, ffmpeg_capabilities=None,
                              javascript_runtime=None, sign_in_entries=None,
                              github_api_budget=None, po_token_provider=None,
                              output_folder=None, state_location=None,
                              site_refusals=None, system_clock=None,
                              now=None):
    """Classify known download prerequisites without performing I/O.

    Callers own the slow probes and pass their bounded results here. The
    returned IDs and actions are stable API values; ``details`` contains only
    counts, versions, and booleans, never paths, site names, tokens, or cookie
    contents. ``warning`` and ``unknown`` conditions are actionable but do
    not block a download; ``error`` identifies a prerequisite that is known
    to be unusable.
    """
    today = _preflight_now_date(now)
    checks = []

    release_date = _parse_ytdlp_release_date(ytdlp_version)
    if release_date is None:
        checks.append(_preflight_check(
            "ytdlp-freshness", "yt-dlp freshness", "error", "refresh-ytdlp",
            "yt-dlp is missing or its release date could not be verified.",
            version=str(ytdlp_version or ""),
            maxAgeDays=YTDLP_STALE_AFTER_DAYS,
        ))
    else:
        try:
            release = date(*release_date)
            age_days = max(0, (today - release).days)
        except ValueError:
            age_days = YTDLP_STALE_AFTER_DAYS + 1
        stale = age_days > YTDLP_STALE_AFTER_DAYS
        checks.append(_preflight_check(
            "ytdlp-freshness", "yt-dlp freshness",
            "warning" if stale else "ok", "refresh-ytdlp",
            (
                f"Installed yt-dlp is {age_days} days old; refresh it before "
                "starting a download."
                if stale else "Installed yt-dlp is within the freshness window."
            ),
            version=str(ytdlp_version), ageDays=age_days,
            maxAgeDays=YTDLP_STALE_AFTER_DAYS,
        ))

    runtime = javascript_runtime if isinstance(javascript_runtime, dict) else {}
    if not runtime.get("ytdlpNeedsRuntime"):
        checks.append(_preflight_check(
            "javascript-runtime", "JavaScript runtime", "not-applicable",
            "provision-runtime",
            "The installed yt-dlp does not require an external JavaScript runtime.",
        ))
    elif runtime.get("supported") is True and runtime.get("ejsReady") is True:
        checks.append(_preflight_check(
            "javascript-runtime", "JavaScript runtime", "ok",
            "provision-runtime", "A supported JavaScript runtime passed its execution check.",
            runtime=str(runtime.get("runtime") or ""),
            version=str(runtime.get("version") or ""),
        ))
    else:
        runtime_reason = str(runtime.get("reason") or "runtime-not-ready")
        runtime_label = str(runtime.get("runtime") or "JavaScript runtime").title()
        runtime_version = str(runtime.get("version") or "unknown")
        if runtime_reason == "runtime-version-below-security-floor":
            runtime_message = (
                f"{runtime_label} {runtime_version} is below the security floor "
                f"{runtime.get('securityMinVersion') or 'required'}; update it before downloading."
            )
        elif runtime_reason == "runtime-version-unsupported":
            runtime_message = (
                f"{runtime_label} {runtime_version} is below the runtime floor "
                f"{runtime.get('minVersion') or 'required'}; update it before downloading."
            )
        else:
            runtime_message = (
                "yt-dlp needs a supported JavaScript runtime, but it is missing or not ready."
            )
        checks.append(_preflight_check(
            "javascript-runtime", "JavaScript runtime", "error",
            "provision-runtime",
            runtime_message,
            runtime=str(runtime.get("runtime") or ""),
            reason=runtime_reason,
            minVersion=str(runtime.get("minVersion") or ""),
            securityMinVersion=str(runtime.get("securityMinVersion") or ""),
        ))

    ffmpeg = ffmpeg_capabilities if isinstance(ffmpeg_capabilities, dict) else {}
    missing_filters = [
        str(value) for value in (ffmpeg.get("missingFilters") or [])
        if str(value)
    ]
    filter_checked = ffmpeg.get("filterCheck") is True
    if missing_filters:
        checks.append(_preflight_check(
            "ffmpeg-capabilities", "FFmpeg security and filters", "error",
            "refresh-ffmpeg",
            "FFmpeg is missing a filter required by local transcription.",
            missingFilters=missing_filters,
        ))
    elif ffmpeg.get("current") is False:
        checks.append(_preflight_check(
            "ffmpeg-capabilities", "FFmpeg security and filters", "error",
            "refresh-ffmpeg",
            str(ffmpeg.get("message") or "FFmpeg is below the verified security floor."),
            current=False,
            majorVersion=ffmpeg.get("majorVersion"),
        ))
    elif ffmpeg.get("current") is True and filter_checked:
        checks.append(_preflight_check(
            "ffmpeg-capabilities", "FFmpeg security and filters", "ok",
            "refresh-ffmpeg", "FFmpeg meets the security floor and filter requirements.",
            current=True,
        ))
    else:
        checks.append(_preflight_check(
            "ffmpeg-capabilities", "FFmpeg security and filters", "unknown",
            "refresh-ffmpeg",
            "FFmpeg security or filter capability could not be verified yet.",
            current=ffmpeg.get("current"),
            filterChecked=filter_checked,
        ))

    entries = sign_in_entries if isinstance(sign_in_entries, (list, tuple)) else []
    expired_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            cookie_count = max(0, int(entry.get("cookies") or 0))
        except (TypeError, ValueError, OverflowError):
            cookie_count = 0
        if (
            entry.get("expired") is True and cookie_count > 0
            and (entry.get("stored") is not False)
        ):
            expired_count += 1
    if expired_count:
        checks.append(_preflight_check(
            "sign-in-expiry", "Stored sign-in expiry", "warning",
            "refresh-sign-in",
            f"{expired_count} stored sign-in session(s) have expired cookies.",
            expiredCount=expired_count,
        ))
    elif entries:
        checks.append(_preflight_check(
            "sign-in-expiry", "Stored sign-in expiry", "ok", "refresh-sign-in",
            "Stored sign-in sessions have no expired cookie jars.", expiredCount=0,
        ))
    else:
        checks.append(_preflight_check(
            "sign-in-expiry", "Stored sign-in expiry", "not-applicable",
            "refresh-sign-in", "No stored sign-in cookie jars need checking.",
            expiredCount=0,
        ))

    budget = github_api_budget if isinstance(github_api_budget, dict) else {}
    raw_remaining = budget.get("remaining")
    try:
        remaining = max(0, int(raw_remaining)) if raw_remaining is not None else None
    except (TypeError, ValueError, OverflowError):
        remaining = None
    if remaining is None:
        checks.append(_preflight_check(
            "github-api-budget", "Anonymous GitHub API budget", "unknown",
            "retry-github",
            "The anonymous GitHub API budget has not been measured yet.",
        ))
    elif remaining == 0:
        checks.append(_preflight_check(
            "github-api-budget", "Anonymous GitHub API budget", "error",
            "retry-github",
            "The anonymous GitHub API budget is exhausted; retry after reset.",
            remaining=0, resetAt=budget.get("resetAt"),
        ))
    else:
        checks.append(_preflight_check(
            "github-api-budget", "Anonymous GitHub API budget",
            "warning" if remaining <= 5 else "ok", "retry-github",
            (
                f"Only {remaining} anonymous GitHub API request(s) remain."
                if remaining <= 5 else "The anonymous GitHub API budget is available."
            ),
            remaining=remaining, limit=budget.get("limit"),
            resetAt=budget.get("resetAt"),
        ))

    if po_token_provider is None:
        checks.append(_preflight_check(
            "po-token-provider", "Proof-of-origin token provider", "not-applicable",
            "use-sign-in",
            "The plugin-free client chain does not require a token provider.",
        ))
    elif isinstance(po_token_provider, dict) and po_token_provider.get("ok"):
        provider_stale = bool(po_token_provider.get("stale"))
        checks.append(_preflight_check(
            "po-token-provider", "Proof-of-origin token provider",
            "warning" if provider_stale else "ok", "use-sign-in",
            "The proof-of-origin token provider is stale." if provider_stale
            else "The proof-of-origin token provider is ready.",
            stale=provider_stale,
        ))
    else:
        checks.append(_preflight_check(
            "po-token-provider", "Proof-of-origin token provider", "warning",
            "use-sign-in",
            "The proof-of-origin token provider cannot mint a session-bound token; use a site sign-in or retry later.",
        ))

    folder = output_folder if isinstance(output_folder, dict) else None
    if folder is None:
        checks.append(_preflight_check(
            "output-folder", "Download folder", "unknown", "choose-output-folder",
            "The download folder has not been checked yet.",
        ))
    elif not folder.get("configured"):
        checks.append(_preflight_check(
            "output-folder", "Download folder", "error", "choose-output-folder",
            "No download folder is set; choose one before starting a download.",
            configured=False,
        ))
    elif not folder.get("exists"):
        checks.append(_preflight_check(
            "output-folder", "Download folder", "error", "choose-output-folder",
            "The download folder is missing, or the drive holding it is not connected.",
            configured=True, exists=False,
        ))
    elif not folder.get("writable"):
        checks.append(_preflight_check(
            "output-folder", "Download folder", "error", "choose-output-folder",
            "The download folder exists but will not accept a write; choose another one.",
            configured=True, exists=True, writable=False,
        ))
    else:
        checks.append(_preflight_check(
            "output-folder", "Download folder", "ok", "choose-output-folder",
            "The download folder exists and accepts a write.",
            configured=True, exists=True, writable=True,
        ))

    location = state_location if isinstance(state_location, dict) else None
    if location is None:
        checks.append(_preflight_check(
            "state-location", "Settings and queue storage", "unknown",
            "review-state-location",
            "Where settings, queue and history live has not been checked yet.",
        ))
    elif location.get("writable") is not True:
        checks.append(_preflight_check(
            "state-location", "Settings and queue storage", "error",
            "review-state-location",
            "Settings, queue and history cannot be written; nothing this session "
            "changes will survive a restart.",
            writable=False, portable=bool(location.get("portable")),
            protected=bool(location.get("protected")),
        ))
    elif location.get("protected"):
        checks.append(_preflight_check(
            "state-location", "Settings and queue storage", "warning",
            "review-state-location",
            "This copy stores its settings under a protected program folder, "
            "where Windows may redirect or refuse the writes.",
            writable=True, protected=True,
            portable=bool(location.get("portable")),
        ))
    elif location.get("portable"):
        checks.append(_preflight_check(
            "state-location", "Settings and queue storage", "warning",
            "review-state-location",
            "Settings, queue and history live beside the program, so replacing "
            "this folder with a newer build erases them. Copy them first.",
            writable=True, portable=True, protected=False,
        ))
    else:
        checks.append(_preflight_check(
            "state-location", "Settings and queue storage", "ok",
            "review-state-location",
            "Settings, queue and history live outside the program folder and an "
            "update leaves them alone.",
            writable=True, portable=False, protected=False,
        ))

    refusals = site_refusals if isinstance(site_refusals, (list, tuple)) else None
    if refusals is None:
        checks.append(_preflight_check(
            "site-availability", "Site availability", "not-applicable",
            "review-site-refusals",
            "Repeated site refusals have not been checked yet.",
        ))
    else:
        open_count = 0
        longest = 0.0
        for entry in refusals:
            if not isinstance(entry, dict):
                continue
            open_count += 1
            try:
                longest = max(longest, float(entry.get("openForSeconds") or 0.0))
            except (TypeError, ValueError, OverflowError):
                # reason: a malformed streak still counts as one refusing site
                pass
        long_term = longest >= SITE_LONG_TERM_REFUSAL_SECONDS
        if not open_count:
            checks.append(_preflight_check(
                "site-availability", "Site availability", "not-applicable",
                "review-site-refusals",
                "No site is refusing downloads.", refusingSites=0,
            ))
        else:
            checks.append(_preflight_check(
                "site-availability", "Site availability", "warning",
                "review-site-refusals",
                (
                    f"{open_count} site(s) have refused every attempt for over "
                    f"{int(longest // 3600)} hour(s); a sign-in or a long pause is "
                    "more use than another retry."
                    if long_term else
                    f"{open_count} site(s) refused repeatedly, so downloads to them are paused."
                ),
                refusingSites=open_count,
                longestStreakSeconds=int(longest),
                longTerm=long_term,
            ))

    clock = system_clock if isinstance(system_clock, dict) else None
    if clock is None or clock.get("measured") is not True:
        # Not "unknown": the reading rides along on responses the app already
        # makes, so before the first one there is nothing the user could do
        # about it and nothing to draw their attention to.
        checks.append(_preflight_check(
            "system-clock", "System clock", "not-applicable", "sync-system-clock",
            "No server response has arrived yet to compare this machine's clock against.",
        ))
    else:
        try:
            offset = float(clock.get("offsetSeconds") or 0.0)
        except (TypeError, ValueError, OverflowError):
            offset = 0.0
        drift = abs(offset)
        if drift >= SYSTEM_CLOCK_ERROR_SECONDS:
            checks.append(_preflight_check(
                "system-clock", "System clock", "error", "sync-system-clock",
                f"This machine's clock is {int(drift // 3600)} hour(s) out, which "
                "breaks certificate validation and expires cookies early.",
                offsetSeconds=int(offset),
            ))
        elif drift >= SYSTEM_CLOCK_WARN_SECONDS:
            checks.append(_preflight_check(
                "system-clock", "System clock", "warning", "sync-system-clock",
                f"This machine's clock is {int(drift // 60)} minute(s) out; stored "
                "sign-ins may look expired before they are.",
                offsetSeconds=int(offset),
            ))
        else:
            checks.append(_preflight_check(
                "system-clock", "System clock", "ok", "sync-system-clock",
                "This machine's clock agrees with the server it was compared against.",
                offsetSeconds=int(offset),
            ))

    blocking = [item["id"] for item in checks if item["status"] == "error"]
    attention = [
        item["id"] for item in checks
        if item["status"] in {"warning", "unknown"}
    ]
    return {
        "status": "blocked" if blocking else "attention" if attention else "ready",
        "blocking": blocking,
        "attention": attention,
        "checks": checks,
    }


# Antivirus removing a managed binary is the single largest support burden
# for downloaders of this shape. Removal is easy to see; the damaging case is
# a quarantine that leaves a zero-byte or truncated stub behind, because that
# satisfies every `.exists()` gate and the app carries on with a tool it
# cannot run. Both real binaries are tens of megabytes, so anything under a
# megabyte is broken regardless of how it got that way.
MANAGED_BINARY_MIN_BYTES = 1024 * 1024

MANAGED_BINARY_ANTIVIRUS_ADVICE = (
    "Antivirus software may have removed or truncated it. Add an exclusion "
    "for {path} and let setup fetch it again."
)


def managed_binary_state(path, minimum_bytes=MANAGED_BINARY_MIN_BYTES):
    """Classify a managed helper binary as 'ok', 'missing' or 'damaged'.

    'damaged' is the case worth naming separately: the file is present, so
    every existence check passes, but it is too small to be the real thing.
    """
    if not path:
        return 'missing'
    try:
        candidate = Path(path)
        if not candidate.is_file():
            return 'missing'
        size = candidate.stat().st_size
    except OSError:
        # An unreadable file is not a usable one, and re-fetching is the same
        # remedy as for a missing one.
        return 'damaged'
    return 'ok' if size >= max(0, int(minimum_bytes or 0)) else 'damaged'


def managed_binary_usable(path, minimum_bytes=MANAGED_BINARY_MIN_BYTES):
    """Whether a managed helper binary is present and plausibly whole."""
    return managed_binary_state(path, minimum_bytes) == 'ok'


# yt-dlp aborts the whole download with an unhandled exception when handed an
# impersonate target it does not have — verified against the installed binary:
# `--impersonate NotAReal-1` exits with YoutubeDLError, not a warning. So the
# offer is built from what the binary reports, and the argv is gated on it.
IMPERSONATE_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[0-9][A-Za-z0-9.]*$")


def parse_impersonate_targets(output):
    """Read `--list-impersonate-targets` output into a list of client names.

    The table is `Client  OS  Source`, preceded by an `[info]` line and a
    dashed rule. Only the first column is a target; the rest is provenance.
    """
    targets = []
    for line in str(output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("[") or set(stripped) <= {"-"}:
            continue
        first = stripped.split()[0]
        if first.lower() == "client" or not IMPERSONATE_TARGET_RE.match(first):
            continue
        if first not in targets:
            targets.append(first)
    return targets


class ImpersonateTargetsProbe:
    """Thread-safe TTL cache over `yt-dlp --list-impersonate-targets`."""

    def __init__(self, *, path, runner, clock=time.time, ttl_seconds=3600):
        self._path = path
        self._runner = runner
        self._clock = clock
        self._ttl_seconds = max(0, float(ttl_seconds))
        self._value = None
        self._checked_at = 0.0
        # See ExecutableVersionProbe: the subprocess runs with the lock
        # released, so a probe started before a binary swap must not publish
        # its answer after one.
        self._generation = 0
        self._lock = threading.Lock()

    @staticmethod
    def _resolve(value):
        return value() if callable(value) else value

    def get(self, force=False):
        path = Path(self._resolve(self._path))
        if not path.exists():
            return []
        with self._lock:
            now = self._clock()
            if (
                not force
                and self._value is not None
                and (now - self._checked_at) < self._ttl_seconds
            ):
                return list(self._value)
            generation = self._generation
        # Spawning yt-dlp outside the lock, as the other probes here do.
        for _attempt in range(_PROBE_RESTART_LIMIT):
            targets = parse_impersonate_targets(
                self._runner([str(path), "--list-impersonate-targets"])
            )
            with self._lock:
                if generation == self._generation:
                    break
                # reset() ran while this was out, which is what a binary swap
                # does. Answering [] would read as "this build can imitate
                # nothing", so ask the binary that is actually installed.
                generation = self._generation
        with self._lock:
            self._value = targets
            self._checked_at = self._clock()
            return list(self._value)

    def reset(self):
        with self._lock:
            self._value = None
            self._checked_at = 0.0
            self._generation += 1


# Listing every extractor is not a fast call: the pinned build reports over
# 1,700 of them, and the process has to import the whole extractor package to
# do it. The Sites page therefore renders the curated registry immediately and
# merges this in when it arrives, rather than blocking on it.
EXTRACTOR_LIST_TIMEOUT_SECONDS = 60

# A broken extractor is still listed, with a marker. Surfacing that is the
# honest thing to do: "supported" and "supported and currently working" are
# different claims, and a site that yt-dlp itself has flagged is exactly the
# one a user is about to file a bug about.
_EXTRACTOR_BROKEN_MARKER = "(CURRENTLY BROKEN)"


def parse_extractor_list(output):
    """Read `yt-dlp --list-extractors` output into `(name, working)` pairs.

    One extractor per line. yt-dlp appends a marker to the ones it knows are
    broken, and prefixes progress chatter with `[`, which is dropped. The
    generic fallbacks are dropped too: `generic` matching a page is not the
    same as a site being supported, and listing them invites the reading that
    every site on the web is covered.
    """
    seen = set()
    extractors = []
    for line in str(output or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("["):
            continue
        working = _EXTRACTOR_BROKEN_MARKER not in stripped
        name = stripped.replace(_EXTRACTOR_BROKEN_MARKER, "").strip()
        if not name or name.lower() in {"generic", "default"}:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        extractors.append((name, working))
    return extractors


class ExtractorListProbe:
    """Thread-safe TTL cache over `yt-dlp --list-extractors`.

    Same shape as `ImpersonateTargetsProbe`, including the generation guard: a
    probe started before a binary swap must not publish an answer describing
    the binary that is no longer installed.
    """

    def __init__(self, *, path, runner, clock=time.time, ttl_seconds=6 * 3600):
        self._path = path
        self._runner = runner
        self._clock = clock
        self._ttl_seconds = max(0, float(ttl_seconds))
        self._value = None
        self._checked_at = 0.0
        self._generation = 0
        self._lock = threading.Lock()

    @staticmethod
    def _resolve(value):
        return value() if callable(value) else value

    def get(self, force=False):
        path = Path(self._resolve(self._path))
        if not path.exists():
            return []
        with self._lock:
            now = self._clock()
            if (
                not force
                and self._value is not None
                and (now - self._checked_at) < self._ttl_seconds
            ):
                return list(self._value)
            generation = self._generation
        extractors = []
        for _attempt in range(_PROBE_RESTART_LIMIT):
            extractors = parse_extractor_list(
                self._runner([str(path), "--list-extractors"])
            )
            with self._lock:
                if generation == self._generation:
                    break
                generation = self._generation
        with self._lock:
            self._value = extractors
            self._checked_at = self._clock()
            return list(self._value)

    def reset(self):
        with self._lock:
            self._value = None
            self._checked_at = 0.0
            self._generation += 1


def _parse_ytdlp_release_date(version_string):
    """Parse a yt-dlp date release into a comparable date tuple."""
    if not isinstance(version_string, str):
        return None
    match = re.match(r'(\d{4})\.(\d{1,2})\.(\d{1,2})', version_string.strip())
    if not match:
        return None
    try:
        year, month, day = (int(match.group(index)) for index in range(1, 4))
    except (TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return year, month, day


def ytdlp_needs_external_runtime(version_string, cutoff=YTDLP_EXTERNAL_RUNTIME_CUTOFF):
    """Return whether a yt-dlp release is new enough to require an external runtime."""
    parsed = _parse_ytdlp_release_date(version_string)
    return parsed is not None and parsed >= cutoff


def build_javascript_runtime_args(readiness):
    """Return explicit yt-dlp runtime selection for a verified capability probe."""
    if not isinstance(readiness, dict):
        return []
    if readiness.get('supported') is not True or readiness.get('ejsReady') is not True:
        return []
    runtime = readiness.get('runtime')
    path = readiness.get('path')
    if runtime not in JS_RUNTIMES or not path:
        return []
    return ['--no-js-runtimes', '--js-runtimes', f'{runtime}:{path}']


def build_youtube_extractor_args(url, po_token_provider=None,
                                 default_provider_port=None):
    """Build the plugin-free YouTube extractor arguments.

    The companion deliberately runs yt-dlp with ``--no-plugin-dirs``. Keep
    that security boundary honest by never emitting the bgutil plugin
    namespace, even when a stale process happens to answer on its port. The
    token-exempt client chain is therefore deterministic for downloads,
    format probes, and playlist probes alike. The provider parameters remain
    accepted for source compatibility with older callers.
    """
    if not is_youtube_url(url):
        return []
    args = [
        '--extractor-args', 'youtube:formats=duplicate',
        '--extractor-args', 'youtube:skip=translated_subs',
        '--extractor-args', 'youtube-ejs:jitless=true',
    ]
    # The default web/mweb clients need GVS proof-of-origin tokens and
    # otherwise return SABR-only formats or HTTP 403. Use only the client
    # chain this plugin-free build has verified as token-exempt: bare `web` is
    # SABR-only without a GVS token. yt-dlp 2026.08.19 dropped android_vr
    # (client 1.65.10 403s every format), so it is not in this chain.
    args += [
        '--extractor-args',
        'youtube:player_client=visionos,tv,web_embedded',
    ]
    return args


def parse_ffmpeg_major(version_string):
    """Extract the numeric major from a canonical ffmpeg release string.

    Accepts an optional lowercase ``n`` tag prefix (BtbN-style release builds
    report ``n8.1.2-...``); capital ``N-<commit>`` master snapshots stay
    unmatched on purpose — they have no comparable release number.
    """
    if not version_string:
        return None
    match = re.match(r'n?(\d+)\.', str(version_string))
    return int(match.group(1)) if match else None


def parse_ffmpeg_snapshot_date(version_string):
    """Return the ISO build date embedded in an FFmpeg master snapshot.

    The BtbN master archive reports versions such as
    N-123918-gf7ca6f7481-20260411. The date is the only comparable freshness
    signal for that build family; malformed or undated snapshots remain
    unknown rather than being guessed current or stale.
    """
    match = re.search(r'(?<!\d)(20\d{6})(?!\d)', str(version_string or ''))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), '%Y%m%d').date().isoformat()
    except ValueError:
        return None


def parse_javascript_runtime_version(runtime, output):
    if not output:
        return None
    first_line = output.strip().splitlines()[0] if output.strip() else ''
    match = re.search(r'(\d+\.\d+\.\d+)', first_line)
    if match:
        return match.group(1)
    return first_line[:32] if runtime == 'deno' and first_line else None


def javascript_runtime_supported(runtime, version, *, deno_min=DENO_MIN_VERSION,
                                 node_min=NODE_MIN_VERSION,
                                 quickjs_min=QUICKJS_MIN_VERSION):
    if runtime not in JS_RUNTIMES:
        return False
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version.strip()):
        return False
    minimum = _runtime_minimum(runtime, deno_min, node_min, quickjs_min)
    return _compare_semver(version, minimum) >= 0


def javascript_runtime_security_supported(
    runtime, version, *, deno_security_min=DENO_SECURITY_MIN_VERSION,
):
    """Return whether a runtime meets this app's security floor."""
    if runtime != 'deno':
        return True
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version.strip()):
        return False
    return _compare_semver(version, deno_security_min) >= 0


def probe_javascript_execution(runtime, executable, *, runner, marker,
                               timeout=1.5):
    if runtime == 'deno':
        args = [str(executable), 'eval', '--no-config', f"console.log('{marker}')"]
    elif runtime == 'node':
        args = [
            str(executable), '--input-type=commonjs', '-e',
            f"process.stdout.write('{marker}')",
        ]
    elif runtime == 'quickjs':
        # Verified against the shipped build: `qjs -e` evaluates and prints.
        args = [str(executable), '-e', f"console.log('{marker}')"]
    else:
        return False
    return marker in runner(args, timeout=timeout)


def evaluate_javascript_runtime(runtime, path, source, *, runner, marker,
                                timeout=1.5, deno_min=DENO_MIN_VERSION,
                                node_min=NODE_MIN_VERSION,
                                deno_security_min=DENO_SECURITY_MIN_VERSION,
                                quickjs_min=QUICKJS_MIN_VERSION):
    minimum = _runtime_minimum(runtime, deno_min, node_min, quickjs_min)
    security_minimum = deno_security_min if runtime == 'deno' else None
    try:
        output = runner([str(path), '--version'], timeout=timeout)
    except Exception:
        # reason: the returned probe already reports runtime-probe-failed, which is what the readiness row renders
        return {
            'runtime': runtime, 'version': None, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
            'securityMinVersion': security_minimum,
            'reason': 'runtime-probe-failed',
        }
    version = parse_javascript_runtime_version(runtime, output)
    if not version:
        return {
            'runtime': runtime, 'version': None, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
            'securityMinVersion': security_minimum,
            'reason': 'runtime-version-unparseable',
        }
    supported = javascript_runtime_supported(
        runtime, version, deno_min=deno_min, node_min=node_min,
        quickjs_min=quickjs_min,
    )
    if not supported:
        return {
            'runtime': runtime, 'version': version, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
            'securityMinVersion': security_minimum,
            'reason': 'runtime-version-unsupported',
        }
    if not javascript_runtime_security_supported(
        runtime, version, deno_security_min=deno_security_min,
    ):
        return {
            'runtime': runtime, 'version': version, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
            'securityMinVersion': security_minimum,
            'reason': 'runtime-version-below-security-floor',
        }
    try:
        ejs_ready = probe_javascript_execution(
            runtime, path, runner=runner, marker=marker, timeout=timeout
        )
    except Exception:
        # reason: an unusable challenge solver is a negative readiness answer; the runtime row above names what to repair
        ejs_ready = False
    return {
        'runtime': runtime, 'version': version, 'path': path, 'source': source,
        'supported': True, 'ejsReady': ejs_ready, 'minVersion': minimum,
        'securityMinVersion': security_minimum,
        'reason': 'ready' if ejs_ready else 'runtime-execution-failed',
    }


def _run_captured(args, timeout=5, *, runner=None, creationflags=0):
    """Capture a diagnostic subprocess without raising into health endpoints."""
    runner = subprocess.run if runner is None else runner
    try:
        result = runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        return (result.stdout or '') + (result.stderr or '')
    except Exception:
        # reason: a version probe that cannot run has no output, and every caller already treats empty text as unknown
        return ''


def parse_ytdlp_version_output(output):
    first = output.strip().splitlines()[0] if output and output.strip() else ''
    return first[:32] or None


def parse_ffmpeg_version_output(output):
    first = output.splitlines()[0] if output else ''
    match = re.search(r'ffmpeg version (\S+)', first)
    return (match.group(1) if match else '')[:64] or None


def probe_whisper_runtime(path, minimum_bytes=MANAGED_BINARY_MIN_BYTES,
                          *, runner=None):
    """Verify that the managed whisper.cpp CLI can provide SRT output.

    A present executable is not enough: an incomplete extraction can leave
    the CLI on disk while its DLLs are missing, and a generic helper binary
    can satisfy a size check without implementing the capability we need.
    ``whisper-cli --help`` is deliberately parsed instead of trusting its
    exit code, just as the ffmpeg capability probe must parse filter output.
    """
    path = Path(path)
    state = managed_binary_state(path, minimum_bytes)
    result = {
        'state': state,
        'usable': False,
        'path': str(path),
        'reason': 'missing' if state == 'missing' else 'damaged',
    }
    if state != 'ok':
        return result
    output = _run_captured(
        [str(path), '--help'],
        timeout=5,
        runner=runner,
    )
    # The CLI writes help to stderr. _run_captured combines both streams, but
    # check for the actual SRT switch rather than merely a successful process.
    if re.search(r'(?m)--output-srt\b', output or ''):
        result.update({'usable': True, 'reason': 'ready'})
    else:
        result['reason'] = 'capability-missing'
    return result


# How many times a probe re-reads after a reset landed mid-flight. One
# rollback is one bump, so a single restart is the real case; the bound is
# here so a caller cannot be held by a stream of them.
_PROBE_RESTART_LIMIT = 3


class ExecutableVersionProbe:
    """Thread-safe TTL cache for an injected executable version command."""

    def __init__(self, *, path, args, parser, runner, clock=time.time, ttl_seconds=3600):
        self._path = path
        self._args = tuple(args)
        self._parser = parser
        self._runner = runner
        self._clock = clock
        self._ttl_seconds = max(0, float(ttl_seconds))
        self._value = None
        self._has_value = False
        self._checked_at = 0.0
        self._in_flight = False
        # Bumped by reset() and prime(). The I/O below runs with the condition
        # released, so a probe that started before a binary was swapped could
        # land afterwards and republish the old version for a whole TTL. It
        # compares this on the way back in and drops its answer if the world
        # moved.
        self._generation = 0
        self._condition = threading.Condition()

    @staticmethod
    def _resolve(value):
        return value() if callable(value) else value

    def get(self, force=False, attempt=0):
        path = Path(self._resolve(self._path))
        if not path.exists():
            return None
        with self._condition:
            now = self._clock()
            if (
                not force
                and self._has_value
                and (now - self._checked_at) < self._ttl_seconds
            ):
                return self._value
            if self._in_flight:
                # A cold /health request must not turn one blocked executable
                # into N subprocesses. Wait for the owner and use its result,
                # including a cached None, even when this caller requested a
                # forced refresh.
                while self._in_flight:
                    self._condition.wait()
                if self._has_value:
                    return self._value
            self._in_flight = True
            generation = self._generation
        # The executable probe can take several seconds on a cold cache. The
        # condition is released while it runs, so callers can wait on the
        # in-flight marker without blocking reset/prime operations.
        try:
            try:
                value = self._parser(self._runner([str(path), *self._args]))
            except Exception:
                # Health is advisory. A timeout, AV block, or parser failure
                # is a negative result and must still receive the TTL.
                # reason: health is advisory, so a timeout, AV block or parser failure is a negative result that still takes the TTL
                value = None
        finally:
            with self._condition:
                stale = generation != self._generation
                if not stale:
                    self._value = value
                    self._has_value = True
                    self._checked_at = self._clock()
                elif self._has_value:
                    # prime() ran while this was out: it carries a version an
                    # update transaction already verified, so it wins.
                    value = self._value
                # Read under the condition; deciding to re-probe on a value
                # someone can be changing is how this class got here.
                reprobe = stale and not self._has_value
                self._in_flight = False
                self._condition.notify_all()
        if reprobe:
            # reset() ran while this was out, and left nothing behind.
            # Answering None would report the executable as unreadable, so
            # read the one that is installed now.
            if attempt + 1 < _PROBE_RESTART_LIMIT:
                return self.get(force=True, attempt=attempt + 1)
        return value

    def reset(self):
        with self._condition:
            self._value = None
            self._has_value = False
            self._checked_at = 0.0
            self._generation += 1

    def prime(self, value, checked_at=None):
        """Publish a version already verified by an update transaction."""
        with self._condition:
            self._value = value
            self._has_value = True
            self._checked_at = self._clock() if checked_at is None else float(checked_at)
            self._generation += 1


class FfmpegCapabilitiesProbe:
    """Cached ffmpeg support-floor assessment over an injected version source."""

    def __init__(self, *, version_getter, clock=time.time, minimum_major=7,
                 minimum_version=None, minimum_snapshot_date=None,
                 ttl_seconds=3600):
        self._version_getter = version_getter
        self._clock = clock
        self._minimum_major = max(0, int(minimum_major))
        # Optional exact semver floor (e.g. "8.1.2"). Only applied when the
        # reported version parses to a numeric release; master/snapshot builds
        # ("N-119847-g…") use the embedded build date when a dated floor is
        # configured.
        self._minimum_version = str(minimum_version).strip() if minimum_version else None
        self._minimum_snapshot_date = (
            str(minimum_snapshot_date).strip() if minimum_snapshot_date else None
        )
        self._ttl_seconds = max(0, float(ttl_seconds))
        self._value = None
        self._checked_at = 0.0
        # See ExecutableVersionProbe.
        self._generation = 0
        self._lock = threading.Lock()

    def check(self, force=False):
        with self._lock:
            now = self._clock()
            if (
                not force
                and self._value is not None
                and (now - self._checked_at) < self._ttl_seconds
            ):
                return dict(self._value)
            generation = self._generation
        # The version getter can invoke an executable probe. Keep that I/O
        # outside the capabilities-cache lock so concurrent health calls do
        # not wait for a cold ffmpeg subprocess.
        for _attempt in range(_PROBE_RESTART_LIMIT):
            raw = self._version_getter()
            with self._lock:
                if generation == self._generation:
                    break
                # reset() ran while the version getter was out, which is what
                # a rollback does. The answer in hand describes the ffmpeg
                # that was just replaced, so read the new one instead of
                # caching it for a whole TTL.
                generation = self._generation
        with self._lock:
            now = self._clock()
            major = parse_ffmpeg_major(raw)
            if major is None:
                snapshot_date = parse_ffmpeg_snapshot_date(raw)
                if self._minimum_snapshot_date and snapshot_date:
                    current = snapshot_date >= self._minimum_snapshot_date
                    if current:
                        message = (
                            f'ffmpeg snapshot build date {snapshot_date} meets the '
                            f'{self._minimum_snapshot_date}+ dated floor'
                        )
                    else:
                        message = (
                            f'ffmpeg snapshot build date {snapshot_date} is below the '
                            f'{self._minimum_snapshot_date} dated floor '
                            '(known-vulnerable); re-download via the bundled bootstrap'
                        )
                    result = {
                        'majorVersion': None,
                        'buildDate': snapshot_date,
                        'comparison': 'snapshot-date',
                        'current': current,
                        'message': message,
                    }
                else:
                    result = {
                        'majorVersion': None,
                        'buildDate': snapshot_date,
                        'comparison': 'unknown',
                        'current': None,
                        'message': 'ffmpeg version not detected (first-run bootstrap or undated snapshot build)',
                    }
            elif self._minimum_version:
                # A numeric major means a tagged release, so compare the full
                # reported version against the exact floor. _compare_semver
                # ignores the build suffix (e.g. "-full_build-www.gyan.dev").
                current = _compare_semver(str(raw), self._minimum_version) >= 0
                if current:
                    message = f'ffmpeg {raw} meets the {self._minimum_version}+ floor'
                else:
                    message = (
                        f'ffmpeg {raw} is below the {self._minimum_version}+ floor '
                        '(known-vulnerable); re-download via the bundled bootstrap'
                    )
                result = {
                    'majorVersion': major,
                    'buildDate': None,
                    'comparison': 'release-version',
                    'current': current,
                    'message': message,
                }
            else:
                current = major >= self._minimum_major
                if current:
                    message = f'ffmpeg {major}.x meets the {self._minimum_major}+ floor'
                else:
                    message = (
                        f'ffmpeg {major}.x is below the {self._minimum_major}+ floor; '
                        'consider re-downloading via the bundled bootstrap'
                    )
                result = {
                    'majorVersion': major,
                    'buildDate': None,
                    'comparison': 'release-major',
                    'current': current,
                    'message': message,
                }
            self._value = result
            self._checked_at = now
            return dict(result)

    def reset(self):
        with self._lock:
            self._value = None
            self._checked_at = 0.0
            self._generation += 1


_OWNED_EXPORTS = {
    "YTDLP_EXTERNAL_RUNTIME_CUTOFF", "DENO_MIN_VERSION", "DENO_SECURITY_MIN_VERSION",
    "NODE_MIN_VERSION",
    "is_youtube_url", "_compare_semver", "_parse_ytdlp_release_date",
    "evaluate_sabr_support", "SABR_NATIVE_MIN_VERSION",
    "ytdlp_needs_external_runtime", "build_javascript_runtime_args",
    "build_youtube_extractor_args", "parse_ffmpeg_major",
    "parse_ffmpeg_snapshot_date",
    "_run_captured", "ExecutableVersionProbe", "parse_ytdlp_version_output",
    "parse_impersonate_targets", "ImpersonateTargetsProbe",
    "IMPERSONATE_TARGET_RE",
    "parse_extractor_list", "ExtractorListProbe",
    "EXTRACTOR_LIST_TIMEOUT_SECONDS",
    "parse_ffmpeg_version_output",
    "probe_whisper_runtime",
    "FfmpegCapabilitiesProbe",
    "parse_javascript_runtime_version", "javascript_runtime_supported",
    "javascript_runtime_security_supported",
    "probe_javascript_execution", "evaluate_javascript_runtime",
    "REQUIRED_FFMPEG_FILTERS", "YTDLP_STALE_AFTER_DAYS",
    "missing_ffmpeg_filters", "evaluate_preflight_checks",
    "DownloadedExecutableIntegrityError", "verify_adjacent_release_sidecar",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
