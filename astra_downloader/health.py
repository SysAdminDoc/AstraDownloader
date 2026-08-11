"""Import-safe runtime health policy and compatibility boundary."""

import re
import subprocess
import threading
import time
from datetime import datetime
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
    "probe_po_token_provider", "reset_po_token_provider_cache",
    "probe_deno_runtime",
    "QUICKJS_MIN_VERSION", "JS_RUNTIMES",
    "probe_javascript_runtime", "build_javascript_runtime_args",
    "reset_deno_runtime_cache", "provision_deno", "_parse_ytdlp_release_date",
    "ytdlp_needs_external_runtime", "YTDLP_EXTERNAL_RUNTIME_CUTOFF",
    "DENO_MIN_VERSION", "NODE_MIN_VERSION", "parse_ffmpeg_major",
    "parse_ffmpeg_snapshot_date", "probe_whisper_runtime",
    "check_ffmpeg_capabilities", "reset_ffmpeg_capabilities_cache",
    "build_youtube_extractor_args", "is_youtube_url", "should_check_ytdlp_update",
    "maybe_auto_update_ytdlp", "_run_ytdlp_self_update",
    "read_update_recovery_status", "atomic_copy_verified",
    "parse_companion_version_source", "fetch_latest_companion_version",
    "validate_companion_update_binary", "probe_companion_update_binary",
    "read_last_installed_update_sha256", "record_last_installed_update_sha256",
    "schedule_companion_update_restart", "schedule_companion_process_exit",
    "_compare_semver", "evaluate_sabr_support", "SABR_NATIVE_MIN_VERSION",
    "ExecutableVersionProbe", "parse_ytdlp_version_output",
    "parse_ffmpeg_version_output",
    "FfmpegCapabilitiesProbe",
    "parse_javascript_runtime_version", "javascript_runtime_supported",
    "probe_javascript_execution", "evaluate_javascript_runtime",
)

YTDLP_EXTERNAL_RUNTIME_CUTOFF = (2026, 4, 1)
DENO_MIN_VERSION = "2.3.0"
NODE_MIN_VERSION = "22.0.0"
# QuickJS is the smallest runtime yt-dlp accepts and the one this app can
# provision without asking the user to install anything: a 2 MB executable
# against Deno's 40 MB archive. The floor is the version the app pins and
# ships, because that is the only one this project has verified end-to-end —
# a test keeps the two in step.
QUICKJS_MIN_VERSION = "0.16.1"

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
        # Spawning yt-dlp outside the lock, as the other probes here do.
        targets = parse_impersonate_targets(
            self._runner([str(path), "--list-impersonate-targets"])
        )
        with self._lock:
            self._value = targets
            self._checked_at = self._clock()
            return list(self._value)

    def reset(self):
        with self._lock:
            self._value = None
            self._checked_at = 0.0


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
    args = ['--extractor-args', 'youtube:formats=duplicate']
    # The default web/mweb clients need GVS proof-of-origin tokens and
    # otherwise return SABR-only formats or HTTP 403. Use only the client
    # chain this plugin-free build has verified as token-exempt: bare `web` is
    # SABR-only without a GVS token, while android_vr is erratic and rides
    # last. yt-dlp merges this with formats=duplicate for a deterministic path.
    args += [
        '--extractor-args',
        'youtube:player_client=visionos,tv,web_embedded,android_vr',
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
                                quickjs_min=QUICKJS_MIN_VERSION):
    minimum = _runtime_minimum(runtime, deno_min, node_min, quickjs_min)
    try:
        output = runner([str(path), '--version'], timeout=timeout)
        version = parse_javascript_runtime_version(runtime, output)
    except Exception:
        return {
            'runtime': runtime, 'version': None, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
            'reason': 'runtime-probe-failed',
        }
    if not version:
        return {
            'runtime': runtime, 'version': None, 'path': path, 'source': source,
            'supported': False, 'ejsReady': False, 'minVersion': minimum,
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
            'reason': 'runtime-version-unsupported',
        }
    try:
        ejs_ready = probe_javascript_execution(
            runtime, path, runner=runner, marker=marker, timeout=timeout
        )
    except Exception:
        ejs_ready = False
    return {
        'runtime': runtime, 'version': version, 'path': path, 'source': source,
        'supported': True, 'ejsReady': ejs_ready, 'minVersion': minimum,
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
        self._condition = threading.Condition()

    @staticmethod
    def _resolve(value):
        return value() if callable(value) else value

    def get(self, force=False):
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
        # The executable probe can take several seconds on a cold cache. The
        # condition is released while it runs, so callers can wait on the
        # in-flight marker without blocking reset/prime operations.
        try:
            try:
                value = self._parser(self._runner([str(path), *self._args]))
            except Exception:
                # Health is advisory. A timeout, AV block, or parser failure
                # is a negative result and must still receive the TTL.
                value = None
        finally:
            with self._condition:
                self._value = value
                self._has_value = True
                self._checked_at = self._clock()
                self._in_flight = False
                self._condition.notify_all()
        return value

    def reset(self):
        with self._condition:
            self._value = None
            self._has_value = False
            self._checked_at = 0.0

    def prime(self, value, checked_at=None):
        """Publish a version already verified by an update transaction."""
        with self._condition:
            self._value = value
            self._has_value = True
            self._checked_at = self._clock() if checked_at is None else float(checked_at)


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
        # The version getter can invoke an executable probe. Keep that I/O
        # outside the capabilities-cache lock so concurrent health calls do
        # not wait for a cold ffmpeg subprocess.
        raw = self._version_getter()
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


_OWNED_EXPORTS = {
    "YTDLP_EXTERNAL_RUNTIME_CUTOFF", "DENO_MIN_VERSION", "NODE_MIN_VERSION",
    "is_youtube_url", "_compare_semver", "_parse_ytdlp_release_date",
    "evaluate_sabr_support", "SABR_NATIVE_MIN_VERSION",
    "ytdlp_needs_external_runtime", "build_javascript_runtime_args",
    "build_youtube_extractor_args", "parse_ffmpeg_major",
    "parse_ffmpeg_snapshot_date",
    "_run_captured", "ExecutableVersionProbe", "parse_ytdlp_version_output",
    "parse_impersonate_targets", "ImpersonateTargetsProbe",
    "IMPERSONATE_TARGET_RE",
    "parse_ffmpeg_version_output",
    "probe_whisper_runtime",
    "FfmpegCapabilitiesProbe",
    "parse_javascript_runtime_version", "javascript_runtime_supported",
    "probe_javascript_execution", "evaluate_javascript_runtime",
}
_resolve_legacy = make_legacy_resolver(
    name for name in __all__ if name not in _OWNED_EXPORTS
)


def __getattr__(name):
    return _resolve_legacy(name)


def __dir__():
    return sorted((*globals(), *__all__))
