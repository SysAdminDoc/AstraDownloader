"""Durable scheduled subscription ingestion for the Astra Downloader.

The companion deliberately keeps subscription state separate from the normal
download history.  A subscription document contains the schedule and a
bounded archive of video keys, while the download queue carries the small
amount of linkage needed to reconcile a scan with a restart.  Ordinary
downloads never consult this store and remain re-downloadable.
"""

import contextlib
import copy
import hashlib
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

try:
    from .config import DurableUndoStore
except ImportError:  # Flat source-path compatibility.
    from config import DurableUndoStore


__all__ = (
    "SUBSCRIPTION_SCHEMA_VERSION", "SUBSCRIPTION_PROBE_LIMIT",
    "SUBSCRIPTION_VIDEO_FORMATS", "SUBSCRIPTION_AUDIO_FORMATS",
    "SUBSCRIPTION_QUALITY_CHOICES", "sanitize_subscription_delivery",
    "SUBSCRIPTION_MIN_INTERVAL_MINUTES",
    "SUBSCRIPTION_MAX_INTERVAL_MINUTES",
    "SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS",
    "SUBSCRIPTION_RETRY_BASE_SECONDS",
    "SUBSCRIPTION_MAX_RECORDS",
    "SUBSCRIPTION_MAX_ARCHIVE_ENTRIES",
    "SUBSCRIPTION_SCAN_MAX_CONCURRENT",
    "RESERVE_OK",
    "RESERVE_ALREADY_PRESENT",
    "RESERVE_RETRY_BACKOFF",
    "RESERVE_RETRY_EXHAUSTED",
    "RESERVE_SAVE_FAILED",
    "SubscriptionStore",
    "SubscriptionManager",
    "normalize_subscription_candidate",
    "subscription_archive_key",
)


# 2 adds the per-subscription delivery fields below. A version-1 file loads
# unchanged: every new field has a default that means "use the global
# setting", which is exactly what a version-1 record did.
SUBSCRIPTION_SCHEMA_VERSION = 2

# How many uploads one scan asks for. Declared here as well as in the
# composition root's probe because the scheduler has to know whether a scan
# saw the whole source or only a window of it; a test pins the two together.
SUBSCRIPTION_PROBE_LIMIT = 50

# What a subscription may override about how its videos are delivered. An
# empty value always means "fall back to the global setting", so the absence
# of an override and an override that matches the global are the same thing.
# config.py owns the same vocabulary for site profiles; a test pins the two
# together, because the modules never cross-import.
SUBSCRIPTION_VIDEO_FORMATS = frozenset({"", "mp4", "mkv", "webm"})
SUBSCRIPTION_AUDIO_FORMATS = frozenset({"", "mp3", "m4a", "opus", "flac", "wav"})
SUBSCRIPTION_QUALITY_CHOICES = frozenset({
    "", "best", "2160", "1440", "1080", "720", "480",
})
SUBSCRIPTION_MIN_INTERVAL_MINUTES = 5
SUBSCRIPTION_MAX_INTERVAL_MINUTES = 7 * 24 * 60
SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS = 3
SUBSCRIPTION_RETRY_BASE_SECONDS = SUBSCRIPTION_MIN_INTERVAL_MINUTES * 60
SUBSCRIPTION_MAX_RECORDS = 100
SUBSCRIPTION_MAX_ARCHIVE_ENTRIES = 20_000
# Every scan spawns a yt-dlp process. The per-id dedup in `_scan_ids` stops a
# double scan of one subscription, but nothing else bounded the total: at the
# 100-record cap, "Scan now" down the list (or the API's 30-per-minute
# allowance) could hold 100 concurrent threads each running yt-dlp. The
# sibling paths are all gated (`_formats_gate` at 2, transcription at 1,
# downloads at 3); scans get the formats gate's width.
SUBSCRIPTION_SCAN_MAX_CONCURRENT = 2
# reserve_archive outcomes. "already present" and "retry backoff" are ordinary
# nothing-to-do cases; "retry exhausted" is surfaced with the candidate's last
# error, while "save failed" means the archive could not be written.
RESERVE_OK = "reserved"
RESERVE_ALREADY_PRESENT = "already-present"
RESERVE_RETRY_BACKOFF = "retry-backoff"
RESERVE_RETRY_EXHAUSTED = "retry-exhausted"
RESERVE_SAVE_FAILED = "save-failed"
_TEXT_LIMIT = 500
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")
_MISSING_STATE = object()


def _default_clean_text(value, default="", max_len=_TEXT_LIMIT):
    if value is None:
        return default
    cleaned = str(value).replace("\x00", "").strip()
    return cleaned[:max_len].rstrip() if len(cleaned) > max_len else cleaned


def _default_normalize_url(value):
    raw = _default_clean_text(value, "", 4096)
    parsed = urlparse(raw)
    if not raw or any(character.isspace() for character in raw):
        return None, "Enter a valid http or https URL."
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None, "Enter a valid http or https URL."
    return raw, None


def _default_is_youtube_url(url):
    # Parsed-host comparison, matching health.is_youtube_url. A string match
    # here would accept `https://evil.com?x=.youtube.com/` as a channel URL.
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https") or not host:
        return False
    return any(host == known or host.endswith("." + known) for known in _YOUTUBE_HOSTS)


def _default_clamp_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _default_coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _copy(value):
    """Copy JSON-shaped state without exposing the store's live dictionaries."""
    return copy.deepcopy(value)


def _finite_timestamp(value, default=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        return default
    return parsed


def _safe_nonnegative_int(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(0, parsed)


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


def _next_retry_at(attempts, now):
    """Return an increasing retry time for a failed archive attempt."""
    attempts = max(1, _safe_nonnegative_int(attempts, 1))
    return now + SUBSCRIPTION_RETRY_BASE_SECONDS * (2 ** (attempts - 1))


def _archive_status_priority(entry):
    status = entry.get("status") if isinstance(entry, dict) else ""
    if status in {"reserved", "queued"}:
        return 2
    if status == "complete":
        return 1
    return 0


def _safe_candidate_id(value):
    cleaned = _default_clean_text(value, "", 120)
    return cleaned if cleaned and _ID_RE.fullmatch(cleaned) else ""


def normalize_subscription_candidate(
    entry,
    *,
    normalize_url=None,
    is_youtube_url=None,
    clean_text=None,
):
    """Normalize one yt-dlp flat-playlist entry into a safe video candidate.

    Flat playlist output frequently uses a bare video ID in ``url``.  Those
    entries are converted to a canonical watch URL before they reach the
    downloader; arbitrary extractor output is never passed through as a
    download target.
    """
    normalize_url = normalize_url or _default_normalize_url
    is_youtube_url = is_youtube_url or _default_is_youtube_url
    clean_text = clean_text or _default_clean_text
    if isinstance(entry, str):
        entry = {"url": entry}
    if not isinstance(entry, dict):
        return None

    video_id = _safe_candidate_id(entry.get("id"))
    raw_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    raw_url = clean_text(raw_url, "", 4096)
    if raw_url and not raw_url.lower().startswith(("http://", "https://")) and video_id:
        raw_url = f"https://www.youtube.com/watch?v={video_id}"
    url, error = normalize_url(raw_url)
    if error or not url or not is_youtube_url(url):
        if video_id:
            url, error = normalize_url(f"https://www.youtube.com/watch?v={video_id}")
        if error or not url or not is_youtube_url(url):
            return None

    title = clean_text(entry.get("title"), "(untitled)", 500) or "(untitled)"
    channel = clean_text(
        entry.get("channel") or entry.get("uploader"), "", 200
    )
    upload_date = clean_text(
        entry.get("upload_date") or entry.get("release_date"), "", 32
    )
    return {
        "id": video_id,
        "url": url,
        "title": title,
        "channel": channel,
        "uploadDate": upload_date,
    }


def sanitize_subscription_delivery(raw, *, clean_text=None, coerce_bool=None):
    """Reduce a delivery override to the fields a subscription may carry.

    Every value is optional and an empty one means "use the global setting".
    A format that does not match the chosen kind is dropped rather than
    corrected: silently turning a requested `mp3` into `mp4` because the
    subscription is a video one would deliver something nobody asked for.
    """
    clean = clean_text or _default_clean_text
    boolean = coerce_bool or _default_coerce_bool
    raw = raw if isinstance(raw, dict) else {}
    audio_only = boolean(raw.get("audioOnly"), False)
    fmt = clean(raw.get("format"), "", 16).lower()
    allowed = SUBSCRIPTION_AUDIO_FORMATS if audio_only else SUBSCRIPTION_VIDEO_FORMATS
    if fmt not in allowed:
        fmt = ""
    quality = clean(raw.get("quality"), "", 8).lower()
    if quality not in SUBSCRIPTION_QUALITY_CHOICES:
        quality = ""
    return {
        "outputDir": clean(raw.get("outputDir"), "", 4096),
        "format": fmt,
        "quality": quality,
        "outputTemplate": clean(raw.get("outputTemplate"), "", 300),
        "audioOnly": audio_only,
        # Off by default, and it costs a metadata fetch per already-captured
        # video on every scan. That is the whole reason it is a choice: a
        # channel with 500 archived uploads would pay 500 probes an hour.
        "upgradeIfBetter": boolean(raw.get("upgradeIfBetter"), False),
    }


def subscription_archive_key(candidate):
    """Return a stable, global key for a normalized video candidate."""
    if not isinstance(candidate, dict):
        return ""
    video_id = _safe_candidate_id(candidate.get("id"))
    if video_id:
        return f"id:{video_id}"
    url = _default_clean_text(candidate.get("url"), "", 4096)
    if not url:
        return ""
    # Archive keys are bounded to 430 characters. Keep short URLs readable,
    # but hash long URL-only candidates so distinct videos cannot collide
    # after the key limit is applied.
    if len(url) > 400:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return f"url-sha256:{digest}"
    return f"url:{url}"


class _SaveBatch:
    """Handle yielded by ``SubscriptionStore.batched_saves``."""

    __slots__ = ("_state",)

    def __init__(self, state):
        self._state = state

    @property
    def failed(self):
        """True when the batch's final write did not land."""
        return bool(self._state["failed"])


class SubscriptionStore:
    """Schema-checked atomic storage for schedules and their archive."""

    def __init__(
        self,
        *,
        path,
        reader=None,
        writer=None,
        logger=None,
        normalize_url=None,
        is_youtube_url=None,
        clean_text=None,
        clamp_int=None,
        coerce_bool=None,
        schema_version=SUBSCRIPTION_SCHEMA_VERSION,
        max_records=SUBSCRIPTION_MAX_RECORDS,
        max_archive_entries=SUBSCRIPTION_MAX_ARCHIVE_ENTRIES,
        clock=time.time,
    ):
        self.path = Path(path)
        self._reader = reader or self._read_json
        self._writer = writer or self._write_json
        self._logger = logger or (lambda _message: None)
        self._normalize_url = normalize_url or _default_normalize_url
        self._is_youtube_url = is_youtube_url or _default_is_youtube_url
        self._clean_text = clean_text or _default_clean_text
        self._clamp_int = clamp_int or _default_clamp_int
        self._coerce_bool = coerce_bool or _default_coerce_bool
        self.schema_version = int(schema_version)
        self.max_records = max(1, int(max_records))
        self.max_archive_entries = max(1, int(max_archive_entries))
        self._clock = clock
        self._lock = threading.RLock()
        self._compatible = True
        self._persistence_error = ""
        # Thread-local: a batch belongs to the thread that opened it. A
        # store-wide counter would silently defer another thread's write and
        # hand it back True, so an Add subscription clicked during a scan would
        # report success with nothing on disk.
        self._save_batch = threading.local()
        self._undo = DurableUndoStore(
            path=self.path.with_name(f".{self.path.name}.undo"),
            loader=self._reader,
            writer=self._writer,
            logger=self._logger,
        )
        self._data = self._load()

    @staticmethod
    def _read_json(path, fallback):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value
        except (OSError, ValueError, TypeError):
            return fallback

    @staticmethod
    def _write_json(path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
                handle.flush()
            temporary.replace(path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # reason: subscription scratch cleanup is best-effort after replacement or failure
                pass

    def _clean(self, value, default="", max_len=_TEXT_LIMIT):
        try:
            return self._clean_text(value, default, max_len)
        except TypeError:
            return self._clean_text(value, default)

    def _load(self):
        raw = self._reader(self.path, {})
        if not isinstance(raw, dict):
            return self._empty()
        stored_version = _stored_schema_version(raw.get("schemaVersion"))
        if raw and stored_version is not None and stored_version > self.schema_version:
            self._compatible = False
            self._persistence_error = (
                "Subscription state was written by a newer, incompatible Astra "
                f"Downloader version (schema {stored_version}; this build reads "
                f"{self.schema_version}). Update Astra Downloader before editing "
                "subscriptions."
            )
            self._logger(self._persistence_error)
            self._logger(
                "Subscription state schema is incompatible; preserving the file without changes."
            )
            return self._empty()
        if raw and (stored_version is None or stored_version < self.schema_version):
            previous = (
                str(stored_version) if stored_version is not None else "missing or invalid"
            )
            self._logger(
                f"Migrating subscription state schema {previous} to "
                f"{self.schema_version}."
            )
        now = self._clock()
        subscriptions = []
        seen_ids = set()
        dropped_subscriptions = 0
        raw_subscriptions = raw.get("subscriptions", [])
        if not isinstance(raw_subscriptions, list):
            raw_subscriptions = []
        for item in raw_subscriptions:
            record = self._sanitize_subscription(item, now)
            if not record:
                dropped_subscriptions += 1
                continue
            if record["id"] in seen_ids:
                dropped_subscriptions += 1
                continue
            seen_ids.add(record["id"])
            subscriptions.append(record)
        if dropped_subscriptions:
            self._logger(
                f"Subscription state dropped {dropped_subscriptions} invalid or "
                "duplicate record(s) while loading."
            )
        if len(subscriptions) > self.max_records:
            self._logger(
                f"Subscription state contains {len(subscriptions)} records, "
                f"above the configured limit of {self.max_records}; preserving "
                "the over-limit records. New subscriptions remain blocked until "
                "records are removed."
            )
        archive = self._sanitize_archive(raw.get("archive"))
        return {
            "schemaVersion": self.schema_version,
            "subscriptions": subscriptions,
            "archive": archive,
        }

    def _empty(self):
        return {
            "schemaVersion": self.schema_version,
            "subscriptions": [],
            "archive": {},
        }

    def _sanitize_subscription(self, raw, now):
        if not isinstance(raw, dict):
            return None
        sub_id = self._clean(raw.get("id"), "", 120)
        if not sub_id or not _ID_RE.fullmatch(sub_id):
            return None
        url, error = self._normalize_url(raw.get("url"))
        if error or not url or not self._is_youtube_url(url):
            return None
        interval = self._clamp_int(
            raw.get("intervalMinutes"),
            60,
            SUBSCRIPTION_MIN_INTERVAL_MINUTES,
            SUBSCRIPTION_MAX_INTERVAL_MINUTES,
        )
        created = _finite_timestamp(raw.get("createdAt"), now) or now
        updated = _finite_timestamp(raw.get("updatedAt"), created) or created
        last_scan = _finite_timestamp(raw.get("lastScanAt"), None)
        enabled = self._coerce_bool(raw.get("enabled"), True)
        next_scan = _finite_timestamp(raw.get("nextScanAt"), None)
        if next_scan is None and enabled:
            next_scan = now
        elif enabled:
            # A clock jump or a hand-edited state file must not silently put
            # an enabled subscription beyond its next legitimate interval.
            next_scan = min(
                next_scan,
                now + interval * 60,
            )
        return {
            "id": sub_id,
            "url": url,
            "title": self._clean(raw.get("title"), "", 300),
            "intervalMinutes": interval,
            "enabled": enabled,
            "createdAt": created,
            "updatedAt": updated,
            "lastScanAt": last_scan,
            "nextScanAt": next_scan,
            "lastError": self._clean(raw.get("lastError"), "", 500),
            "lastQueued": _safe_nonnegative_int(raw.get("lastQueued")),
            "lastSkipped": _safe_nonnegative_int(raw.get("lastSkipped")),
            **sanitize_subscription_delivery(
                raw, clean_text=self._clean, coerce_bool=self._coerce_bool,
            ),
        }

    # Everything an archive entry carries beyond the schema-1 set. Written
    # verbatim by `_write_locked`, so a field missing from `_sanitize_archive`
    # is written to disk and silently dropped on the next load — which is how
    # upgrade detection and the missing-upstream flag stopped surviving a
    # restart while every in-process test still passed.
    _ARCHIVE_EXTRA_FIELDS = (
        ("deliveredHeight", "int"),
        ("upgradeTargetHeight", "int"),
        ("filePath", "path"),
        ("lastSeenAt", "time"),
        ("missingUpstream", "bool"),
    )

    def _sanitize_archive_extras(self, raw):
        extras = {}
        for name, kind in self._ARCHIVE_EXTRA_FIELDS:
            if name not in raw:
                continue
            if kind == "int":
                extras[name] = _safe_nonnegative_int(raw.get(name))
            elif kind == "path":
                extras[name] = self._clean(raw.get(name), "", 4096)
            elif kind == "time":
                extras[name] = _finite_timestamp(raw.get(name), None)
            else:
                extras[name] = self._coerce_bool(raw.get(name), False)
        return extras

    def _sanitize_archive(self, raw):
        if not isinstance(raw, dict):
            return {}
        entries = []
        for key, value in raw.items():
            key = self._clean(key, "", 430)
            if not key or not isinstance(value, dict):
                continue
            status = self._clean(value.get("status"), "failed", 16)
            if status not in {"reserved", "queued", "complete", "failed"}:
                status = "failed"
            entry = {
                "url": self._clean(value.get("url"), "", 4096),
                "title": self._clean(value.get("title"), "(untitled)", 500) or "(untitled)",
                "subscriptionId": self._clean(value.get("subscriptionId"), "", 120),
                "downloadId": self._clean(value.get("downloadId"), "", 120),
                "status": status,
                "createdAt": _finite_timestamp(value.get("createdAt"), self._clock()) or self._clock(),
                "updatedAt": _finite_timestamp(value.get("updatedAt"), self._clock()) or self._clock(),
                "completedAt": _finite_timestamp(value.get("completedAt"), None),
                "lastError": self._clean(value.get("lastError"), "", 500),
                "attempts": _safe_nonnegative_int(value.get("attempts")),
                "nextRetryAt": _finite_timestamp(value.get("nextRetryAt"), None),
                **self._sanitize_archive_extras(value),
            }
            # Migrate pre-fix URL keys through the bounded hash form while
            # the full URL is still available in the archive value.
            if key.startswith("url:") and entry["url"]:
                key = subscription_archive_key({"url": entry["url"]})
            entries.append((key, entry))
        by_key = {}
        collisions = 0
        for key, entry in entries:
            previous = by_key.get(key)
            if previous is None:
                by_key[key] = entry
                continue
            collisions += 1
            previous_rank = (
                _archive_status_priority(previous),
                previous.get("updatedAt", 0),
            )
            entry_rank = (
                _archive_status_priority(entry),
                entry.get("updatedAt", 0),
            )
            if entry_rank > previous_rank:
                by_key[key] = entry
        if collisions:
            self._logger(
                f"Subscription archive merged {collisions} duplicate key(s), "
                "keeping the highest-priority state."
            )
        entries = list(by_key.items())
        entries.sort(
            key=lambda item: (
                _archive_status_priority(item[1]),
                item[1]["updatedAt"],
            ),
            reverse=True,
        )
        if len(entries) > self.max_archive_entries:
            self._logger(
                f"Subscription archive contains {len(entries)} entries, above "
                f"the configured limit of {self.max_archive_entries}; preserving "
                "the over-limit entries until an archive mutation trims them."
            )
        return dict(entries)

    def _write_locked(self):
        try:
            # Writers consume the JSON-shaped document synchronously while the
            # store lock is held. Copying the entire archive here turns every
            # candidate mutation into another O(archive) deepcopy.
            self._writer(self.path, self._data)
            self._persistence_error = ""
            return True
        except Exception as error:  # noqa: BLE001
            self._persistence_error = (
                "Could not save subscriptions. Check disk space and permissions."
            )
            self._logger(f"Subscription state save failed: {error}")
            return False

    def _batch_state(self):
        state = getattr(self._save_batch, "state", None)
        if state is None:
            state = {"depth": 0, "pending": False, "failed": False}
            self._save_batch.state = state
        return state

    def _save_locked(self):
        if not self._compatible:
            return False
        state = self._batch_state()
        if state["depth"]:
            state["pending"] = True
            return True
        return self._write_locked()

    @contextlib.contextmanager
    def batched_saves(self):
        """Coalesce this thread's writes inside the block into one persist.

        A scan runs reserve -> enqueue -> mark_queued for every candidate, and
        each step was a full serialize plus fsync of the whole document while
        holding this lock - around 100 rewrites of an archive capped at 20,000
        records for one 50-item playlist, on the same lock the Qt main thread
        and /health take.

        The batch is thread-local. Another thread mutating the store during a
        scan still writes immediately, because it has its own caller waiting on
        a truthful answer.

        Inside the batch a mutation reports success on the strength of the
        pending write. Yields a handle whose ``failed`` attribute is set if the
        final write does not land, so the caller can report that once instead of
        reading the store-wide persistence error, which is sticky and may belong
        to someone else.
        """
        state = self._batch_state()
        state["depth"] += 1
        if state["depth"] == 1:
            state["failed"] = False
        handle = _SaveBatch(state)
        try:
            yield handle
        finally:
            state["depth"] -= 1
            if state["depth"] == 0 and state["pending"]:
                state["pending"] = False
                with self._lock:
                    if not self._write_locked():
                        state["failed"] = True

    def persistence_error(self):
        """Return the current durable-state error, if one is known."""
        with self._lock:
            return self._persistence_error

    def _save_failure_message(self):
        return (
            self._persistence_error
            or "Could not save subscriptions. Check disk space and permissions."
        )

    def _snapshot_archive_entry_locked(self, snapshots, key):
        if key in snapshots:
            return
        entry = self._data["archive"].get(key, _MISSING_STATE)
        snapshots[key] = _MISSING_STATE if entry is _MISSING_STATE else _copy(entry)

    def _restore_archive_locked(self, snapshots, removed=None):
        archive = self._data["archive"]
        for key, entry in (removed or {}).items():
            archive[key] = entry
        for key, entry in snapshots.items():
            if entry is _MISSING_STATE:
                archive.pop(key, None)
            else:
                archive[key] = entry

    def _find_locked(self, sub_id):
        return next(
            (item for item in self._data["subscriptions"] if item["id"] == sub_id),
            None,
        )

    def list_subscriptions(self):
        with self._lock:
            return _copy(self._data["subscriptions"])

    def get_subscription(self, sub_id):
        with self._lock:
            item = self._find_locked(str(sub_id))
            return _copy(item) if item else None

    def load_removal_undo(self):
        record = self._undo.get("removeSubscription")
        return _copy(record) if isinstance(record, dict) else None

    def clear_removal_undo(self):
        return self._undo.clear("removeSubscription")

    def remove_subscription_with_undo(self, sub_id):
        """Remove a subscription only after its restart-safe snapshot lands."""
        with self._lock:
            if not self._compatible:
                return None, self._save_failure_message()
            index = next(
                (
                    index for index, item in enumerate(self._data["subscriptions"])
                    if item["id"] == str(sub_id)
                ),
                None,
            )
            if index is None:
                return None, "Subscription no longer exists."
            removed = _copy(self._data["subscriptions"][index])
            if not self._undo.set("removeSubscription", removed):
                return None, (
                    "Could not prepare the subscription undo snapshot. "
                    "Nothing was removed; check disk space and permissions."
                )
            self._data["subscriptions"].pop(index)
            if not self._save_locked():
                self._data["subscriptions"].insert(index, removed)
                self._undo.clear("removeSubscription")
                return None, self._save_failure_message()
            return removed, None

    def restore_subscription(self, raw):
        """Restore one previously removed subscription record.

        The GUI keeps only this JSON-shaped record for its one-step undo. It
        is validated through the same boundary as a file load before it is
        put back, and a failed write restores the store's prior in-memory
        state.
        """
        now = _finite_timestamp(self._clock(), time.time()) or time.time()
        record = self._sanitize_subscription(raw, now)
        if not record:
            return False, "That subscription could not be restored."
        with self._lock:
            if not self._compatible:
                return False, self._save_failure_message()
            if len(self._data["subscriptions"]) >= self.max_records:
                return False, f"Subscription limit reached ({self.max_records})."
            if self._find_locked(record["id"]):
                return False, "That subscription is already present."
            if any(item["url"] == record["url"]
                   for item in self._data["subscriptions"]):
                return False, "That subscription is already configured."
            self._data["subscriptions"].append(record)
            if not self._save_locked():
                self._data["subscriptions"].pop()
                return False, self._save_failure_message()
            return _copy(record), None

    def add_subscription(self, url, *, interval_minutes=60, enabled=True,
                         title="", delivery=None, now=None):
        url, error = self._normalize_url(url)
        if error or not url or not self._is_youtube_url(url):
            return None, "Subscriptions must use a YouTube channel or playlist URL."
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            if not self._compatible:
                return None, self._save_failure_message()
            if len(self._data["subscriptions"]) >= self.max_records:
                return None, f"Subscription limit reached ({self.max_records})."
            if any(item["url"] == url for item in self._data["subscriptions"]):
                return None, "That subscription is already configured."
            interval = self._clamp_int(
                interval_minutes,
                60,
                SUBSCRIPTION_MIN_INTERVAL_MINUTES,
                SUBSCRIPTION_MAX_INTERVAL_MINUTES,
            )
            record = {
                "id": f"sub_{uuid.uuid4().hex[:16]}",
                "url": url,
                "title": self._clean(title, "", 300),
                "intervalMinutes": interval,
                "enabled": self._coerce_bool(enabled, True),
                "createdAt": now,
                "updatedAt": now,
                "lastScanAt": None,
                "nextScanAt": now,
                "lastError": "",
                "lastQueued": 0,
                "lastSkipped": 0,
                **sanitize_subscription_delivery(
                    delivery, clean_text=self._clean,
                    coerce_bool=self._coerce_bool,
                ),
            }
            self._data["subscriptions"].append(record)
            if not self._save_locked():
                self._data["subscriptions"].pop()
                return None, self._save_failure_message()
            return _copy(record), None

    def update_subscription(self, sub_id, *, url=None, interval_minutes=None,
                            enabled=None, title=None, delivery=None, now=None):
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            if not self._compatible:
                return None, self._save_failure_message()
            record = self._find_locked(str(sub_id))
            if record is None:
                return None, "Subscription no longer exists."
            before = _copy(record)
            if url is not None:
                normalized, error = self._normalize_url(url)
                if error or not normalized or not self._is_youtube_url(normalized):
                    return None, "Subscriptions must use a YouTube channel or playlist URL."
                if any(
                    item["id"] != record["id"] and item["url"] == normalized
                    for item in self._data["subscriptions"]
                ):
                    return None, "That subscription is already configured."
                record["url"] = normalized
            if interval_minutes is not None:
                record["intervalMinutes"] = self._clamp_int(
                    interval_minutes,
                    record["intervalMinutes"],
                    SUBSCRIPTION_MIN_INTERVAL_MINUTES,
                    SUBSCRIPTION_MAX_INTERVAL_MINUTES,
                )
            was_enabled = bool(record["enabled"])
            if enabled is not None:
                record["enabled"] = self._coerce_bool(enabled, was_enabled)
            if title is not None:
                record["title"] = self._clean(title, "", 300)
            if delivery is not None:
                # Sanitised as a whole rather than field by field: the format
                # a subscription may carry depends on whether it is an audio
                # one, so a partial update has to be resolved against the
                # kind it is being given, not the kind it had.
                merged = {
                    key: record.get(key) for key in
                    ("outputDir", "format", "quality", "outputTemplate",
                     "audioOnly", "upgradeIfBetter")
                }
                merged.update(
                    {key: value for key, value in dict(delivery).items()
                     if value is not None}
                )
                record.update(sanitize_subscription_delivery(
                    merged, clean_text=self._clean,
                    coerce_bool=self._coerce_bool,
                ))
            record["updatedAt"] = now
            if record["enabled"] and not was_enabled:
                record["nextScanAt"] = now
            elif not record["enabled"]:
                record["nextScanAt"] = None
            if not self._save_locked():
                record.clear()
                record.update(before)
                return None, self._save_failure_message()
            return _copy(record), None

    def remove_subscription(self, sub_id):
        with self._lock:
            if not self._compatible:
                return False, self._save_failure_message()
            index = next(
                (
                    index for index, item in enumerate(self._data["subscriptions"])
                    if item["id"] == str(sub_id)
                ),
                None,
            )
            if index is None:
                return False, "Subscription no longer exists."
            removed = self._data["subscriptions"].pop(index)
            if not self._save_locked():
                self._data["subscriptions"].insert(index, removed)
                return False, self._save_failure_message()
            return True, None

    def due_subscriptions(self, now=None):
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            return _copy([
                item for item in self._data["subscriptions"]
                if item["enabled"] and item.get("nextScanAt") is not None
                and float(item["nextScanAt"]) <= now
            ])

    def begin_scan(self, sub_id, now=None):
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            if not self._compatible:
                return None
            record = self._find_locked(str(sub_id))
            if record is None:
                return None
            before = _copy(record)
            record["lastScanAt"] = now
            record["lastError"] = ""
            record["nextScanAt"] = now + record["intervalMinutes"] * 60
            record["updatedAt"] = now
            if not self._save_locked():
                record.clear()
                record.update(before)
                return None
            return _copy(record)

    def finish_scan(self, sub_id, *, queued=0, skipped=0, error="", now=None):
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            record = self._find_locked(str(sub_id))
            if record is None:
                return False
            before = _copy(record)
            record["lastQueued"] = _safe_nonnegative_int(queued)
            record["lastSkipped"] = _safe_nonnegative_int(skipped)
            record["lastError"] = self._clean(error, "", 500)
            # Anchor the next run to when this scan began. Measuring from the
            # finish adds the scan duration to every cycle, so an hourly
            # subscription whose scan takes two minutes slips about 48 minutes
            # a day. If the anchor is missing or already in the past, fall
            # forward from now so a long outage cannot queue a backlog of
            # immediately-due scans.
            # begin_scan stamps lastScanAt and finish_scan never rewrites it,
            # so it is the start of the scan now finishing.
            started_at = _finite_timestamp(record.get("lastScanAt"), 0.0) or 0.0
            interval_seconds = record["intervalMinutes"] * 60
            due = started_at + interval_seconds if started_at else now + interval_seconds
            record["nextScanAt"] = due if due > now else now + interval_seconds
            record["updatedAt"] = now
            if not self._save_locked():
                record.clear()
                record.update(before)
                return False
            return True

    def reserve_archive(self, key, candidate, subscription_id, now=None,
                        upgrade_height=0):
        """Claim an archive key.

        Failed claims are retried with a bounded, increasing delay. Once the
        attempt budget is spent, the scheduler gets a distinct outcome so it
        can name the candidate and its last failure instead of silently
        re-enqueueing it forever.

        ``upgrade_height`` re-opens a completed claim, and only when it is
        STRICTLY greater than the height already delivered. "The same again"
        is not an upgrade, and neither is "we no longer know what we got":
        an entry with no recorded height is left alone rather than re-fetched
        on the strength of a comparison nobody can make.
        """
        key = self._clean(key, "", 430)
        if not key or not isinstance(candidate, dict):
            return RESERVE_SAVE_FAILED
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            if not self._compatible:
                return RESERVE_SAVE_FAILED
            existing = self._data["archive"].get(key)
            attempts = 0
            if existing:
                delivered = _safe_nonnegative_int(existing.get("deliveredHeight"))
                upgrade = (
                    existing.get("status") == "complete"
                    and delivered > 0
                    and _safe_nonnegative_int(upgrade_height) > delivered
                )
                if existing.get("status") in {"reserved", "queued", "complete"} \
                        and not upgrade:
                    return RESERVE_ALREADY_PRESENT
                if upgrade:
                    # An upgrade is a fresh attempt at a video that already
                    # succeeded, not a retry of a failure, so the attempt
                    # budget starts over rather than counting toward
                    # "stopped retrying".
                    attempts = 0
                else:
                    attempts = _safe_nonnegative_int(existing.get("attempts"))
                    if attempts >= SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS:
                        return RESERVE_RETRY_EXHAUSTED
                    retry_at = _finite_timestamp(existing.get("nextRetryAt"), None)
                    if retry_at is not None and now < retry_at:
                        return RESERVE_RETRY_BACKOFF
            attempts += 1
            before = {}
            self._snapshot_archive_entry_locked(before, key)
            self._data["archive"][key] = {
                "url": self._clean(candidate.get("url"), "", 4096),
                "title": self._clean(candidate.get("title"), "(untitled)", 500) or "(untitled)",
                "subscriptionId": self._clean(subscription_id, "", 120),
                "downloadId": "",
                "status": "reserved",
                "createdAt": now,
                "updatedAt": now,
                "completedAt": None,
                "lastError": "",
                "attempts": attempts,
                "nextRetryAt": None,
                # Carried across a re-reservation: an upgrade compares the
                # newly available height against what is already on disk, and
                # a fresh entry would compare it against nothing.
                "deliveredHeight": _safe_nonnegative_int(
                    (existing or {}).get("deliveredHeight")
                ),
                # What this reservation is reaching for. A completion that
                # reports no height falls back to it, so an upgrade whose
                # height yt-dlp did not print cannot re-trigger forever.
                "upgradeTargetHeight": _safe_nonnegative_int(upgrade_height),
                "filePath": self._clean((existing or {}).get("filePath"), "", 4096),
                "lastSeenAt": _finite_timestamp(
                    (existing or {}).get("lastSeenAt"), None
                ),
                # A reservation is proof the scan just saw it.
                "missingUpstream": False,
            }
            removed = self._trim_archive_locked()
            if not self._save_locked():
                self._restore_archive_locked(before, removed)
                return RESERVE_SAVE_FAILED
            return RESERVE_OK

    def mark_archive_queued(self, key, download_id, now=None):
        return self._update_archive(
            key,
            status="queued",
            downloadId=self._clean(download_id, "", 120),
            lastError="",
            now=now,
        )

    def release_archive(self, key, error="", now=None):
        return self._update_archive(
            key,
            status="failed",
            downloadId="",
            lastError=self._clean(error, "Download could not be queued.", 500),
            now=now,
        )

    def mark_download(self, download_id, status, error="", now=None,
                      delivered_height=0, file_path=""):
        download_id = self._clean(download_id, "", 120)
        if not download_id:
            return 0
        status = "complete" if status == "complete" else "failed"
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            matches = [
                (key, entry) for key, entry in self._data["archive"].items()
                if entry.get("downloadId") == download_id
            ]
            if not matches:
                return 0
            before = {}
            for key, entry in matches:
                self._snapshot_archive_entry_locked(before, key)
                entry["status"] = status
                entry["updatedAt"] = now
                entry["lastError"] = self._clean(error, "", 500)
                if status == "complete":
                    entry["completedAt"] = now
                    entry["nextRetryAt"] = None
                    height = _safe_nonnegative_int(delivered_height)
                    if not height:
                        # yt-dlp prints no height for an audio-only run, and
                        # occasionally not at all. Falling back to what the
                        # reservation was reaching for is what stops an
                        # upgrade repeating on every scan.
                        height = _safe_nonnegative_int(
                            entry.get("upgradeTargetHeight"))
                    if height:
                        entry["deliveredHeight"] = height
                    entry["upgradeTargetHeight"] = 0
                    path = self._clean(file_path, "", 4096)
                    if path:
                        entry["filePath"] = path
                    # A completed item is present again by definition.
                    entry["missingUpstream"] = False
                else:
                    entry["attempts"] = max(
                        1, _safe_nonnegative_int(entry.get("attempts"))
                    )
                    entry["nextRetryAt"] = _next_retry_at(
                        entry["attempts"], now
                    )
            if not self._save_locked():
                self._restore_archive_locked(before)
                return 0
            return len(matches)

    def reconcile_downloads(self, downloads, now=None):
        """Attach queue-restored subscription records and reopen orphan claims."""
        now = _finite_timestamp(now, self._clock()) or self._clock()
        active = {}
        for download in downloads or []:
            dl_id = self._clean(getattr(download, "id", ""), "", 120)
            key = self._clean(getattr(download, "archive_key", ""), "", 430)
            sub_id = self._clean(getattr(download, "subscription_id", ""), "", 120)
            if dl_id and key:
                active[dl_id] = (key, sub_id)
        with self._lock:
            before = {}
            changed = False
            active_keys = set()
            for dl_id, (key, sub_id) in active.items():
                entry = self._data["archive"].get(key)
                if not entry:
                    continue
                active_keys.add(key)
                if entry.get("downloadId") != dl_id or entry.get("status") != "queued":
                    self._snapshot_archive_entry_locked(before, key)
                    entry["downloadId"] = dl_id
                    entry["subscriptionId"] = sub_id or entry.get("subscriptionId", "")
                    entry["status"] = "queued"
                    entry["nextRetryAt"] = None
                    entry["updatedAt"] = now
                    changed = True
            for key, entry in self._data["archive"].items():
                if entry.get("status") in {"reserved", "queued"} and key not in active_keys:
                    self._snapshot_archive_entry_locked(before, key)
                    entry["status"] = "failed"
                    entry["downloadId"] = ""
                    entry["lastError"] = "Scheduled download was interrupted; it will retry on the next scan."
                    entry["updatedAt"] = now
                    entry["attempts"] = max(
                        1, _safe_nonnegative_int(entry.get("attempts"))
                    )
                    entry["nextRetryAt"] = _next_retry_at(
                        entry["attempts"], now
                    )
                    changed = True
            if changed and not self._save_locked():
                self._restore_archive_locked(before)
                return False
            return True

    def archive_summary(self):
        with self._lock:
            counts = {"reserved": 0, "queued": 0, "complete": 0, "failed": 0}
            for entry in self._data["archive"].values():
                status = entry.get("status")
                if status in counts:
                    counts[status] += 1
            return {"total": sum(counts.values()), **counts}

    # The scalar fields History rows and URL lookup actually read. Kept as an
    # explicit tuple so the projection below cannot silently start carrying a
    # nested payload again.
    _ARCHIVE_HISTORY_FIELDS = (
        "url", "title", "status", "lastError", "subscriptionId",
        "completedAt", "updatedAt", "createdAt",
    )
    # What the archive view shows. The same scalars plus the attempt count and
    # the download it produced, which is what "why is this one failed?" needs.
    _ARCHIVE_PAGE_FIELDS = _ARCHIVE_HISTORY_FIELDS + (
        "attempts", "downloadId", "nextRetryAt", "deliveredHeight",
        "filePath", "lastSeenAt", "missingUpstream",
    )

    def mark_scan_sightings(self, subscription_id, seen_keys, *,
                            complete_listing=False, now=None):
        """Record which archived items this scan still saw, and which it did not.

        `complete_listing` is the whole of the honesty here. The scan is
        bounded (`--playlist-end`), so an old upload legitimately falls out of
        the window as new ones arrive, and calling that a deletion would flag
        half a large channel. Only a scan that returned FEWER items than its
        own limit has demonstrably seen the entire source, and only then can
        an absent archive entry be called missing.

        Nothing is deleted. A missing entry keeps its file, its history and
        its claim; it gains a flag the user can see and clear.
        """
        subscription_id = self._clean(subscription_id, "", 120)
        now = _finite_timestamp(now, self._clock()) or self._clock()
        seen = {self._clean(key, "", 430) for key in seen_keys or ()}
        seen.discard("")
        with self._lock:
            if not self._compatible:
                return 0
            before = {}
            changed = 0
            for key, entry in self._data["archive"].items():
                if entry.get("subscriptionId") != subscription_id:
                    continue
                if key in seen:
                    if entry.get("lastSeenAt") != now or entry.get("missingUpstream"):
                        self._snapshot_archive_entry_locked(before, key)
                        entry["lastSeenAt"] = now
                        entry["missingUpstream"] = False
                        changed += 1
                    continue
                if not complete_listing:
                    continue
                # Never seen by any scan: it predates this bookkeeping, so
                # there is no "it used to be there" to compare against.
                if _finite_timestamp(entry.get("lastSeenAt"), None) is None:
                    continue
                if entry.get("missingUpstream"):
                    continue
                self._snapshot_archive_entry_locked(before, key)
                entry["missingUpstream"] = True
                entry["updatedAt"] = now
                changed += 1
            if not changed:
                return 0
            if not self._save_locked():
                self._restore_archive_locked(before)
                return 0
            return changed

    def archive_page(self, subscription_id="", *, limit=200, offset=0):
        """One subscription's captured items, newest first.

        The page exists because the archive is what a subscription actually
        produced, and until now the only view of it was the aggregate count
        on the Subscriptions page: "10 archived" with no way to see which ten
        or to change your mind about one. Bounded because the archive holds
        up to 20,000 records and the Qt thread renders this.
        """
        subscription_id = self._clean(subscription_id, "", 120)
        limit = max(1, min(1000, int(limit or 200)))
        offset = max(0, int(offset or 0))
        with self._lock:
            rows = [
                {"key": key, **{
                    field: entry.get(field)
                    for field in self._ARCHIVE_PAGE_FIELDS if field in entry
                }}
                for key, entry in self._data["archive"].items()
                if isinstance(entry, dict)
                and (not subscription_id
                     or entry.get("subscriptionId") == subscription_id)
            ]
        rows.sort(
            key=lambda row: (
                _finite_timestamp(row.get("completedAt"), 0.0) or 0.0,
                _finite_timestamp(row.get("updatedAt"), 0.0) or 0.0,
            ),
            reverse=True,
        )
        return {
            "total": len(rows),
            "offset": offset,
            "items": rows[offset:offset + limit],
        }

    def forget_archive_entry(self, key):
        """Drop one archive claim so the next scan may fetch it again.

        This is also how both flags below are cleared: an item marked missing
        upstream, or one whose file the user deleted locally, is allowed
        through again by removing the claim and nothing else.

        Deliberately not a re-download: the archive is the record of what has
        been taken, and removing the record is the whole of "let this one
        through again". The file on disk is not touched — deleting media is
        the user's business, not a side effect of changing their mind about
        an archive entry.
        """
        key = self._clean(key, "", 430)
        if not key:
            return False, "That archive entry no longer exists."
        with self._lock:
            if not self._compatible:
                return False, self._save_failure_message()
            entry = self._data["archive"].pop(key, None)
            if entry is None:
                return False, "That archive entry no longer exists."
            if entry.get("status") in {"reserved", "queued"}:
                self._data["archive"][key] = entry
                return False, (
                    "That item is being downloaded now; wait for it to finish."
                )
            if not self._save_locked():
                self._data["archive"][key] = entry
                return False, self._save_failure_message()
            return True, ""

    def archive_history_view(self):
        """Project the archive into the scalar fields History displays.

        ``archive_entries()`` deep-copies every record under the store lock —
        at the 20,000-entry cap that is a multi-megabyte copy the Qt main
        thread paid on every History refresh, while every other store
        operation (including /health) waited on the lock. Search still needs
        every row, so the win is copying eight scalars per record instead of
        the whole document.
        """
        with self._lock:
            return {
                key: {
                    field: entry.get(field)
                    for field in self._ARCHIVE_HISTORY_FIELDS
                    if field in entry
                }
                for key, entry in self._data["archive"].items()
                if isinstance(entry, dict)
            }

    def archive_entries(self):
        with self._lock:
            return _copy(self._data["archive"])

    def archive_entry(self, key):
        """Return one archive entry.

        `archive_entries()` deep-copies the whole archive under the store lock.
        Callers that want two fields of one record were paying that for every
        candidate in a scan, blocking every other store operation - including
        /health - for the duration.
        """
        with self._lock:
            return _copy(self._data["archive"].get(str(key), {}))

    def reset_archive_retries(self, subscription_id, now=None):
        """Clear failed-candidate retry state for an explicit manual rescan."""
        subscription_id = self._clean(subscription_id, "", 120)
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            changed = False
            before = {}
            for key, entry in self._data["archive"].items():
                if entry.get("subscriptionId") != subscription_id:
                    continue
                if entry.get("status") != "failed":
                    continue
                self._snapshot_archive_entry_locked(before, key)
                entry["attempts"] = 0
                entry["nextRetryAt"] = None
                entry["lastError"] = ""
                entry["updatedAt"] = now
                changed = True
            if not changed:
                return True
            if not self._save_locked():
                self._restore_archive_locked(before)
                return False
            return True

    def _update_archive(self, key, *, status, downloadId, lastError, now=None):
        key = self._clean(key, "", 430)
        now = _finite_timestamp(now, self._clock()) or self._clock()
        with self._lock:
            entry = self._data["archive"].get(key)
            if not entry:
                return False
            before = {}
            self._snapshot_archive_entry_locked(before, key)
            entry["status"] = status
            entry["downloadId"] = self._clean(downloadId, "", 120)
            entry["lastError"] = self._clean(lastError, "", 500)
            entry["updatedAt"] = now
            if status == "failed":
                entry["attempts"] = max(
                    1, _safe_nonnegative_int(entry.get("attempts"))
                )
                entry["nextRetryAt"] = _next_retry_at(entry["attempts"], now)
            else:
                entry["nextRetryAt"] = None
            if not self._save_locked():
                self._restore_archive_locked(before)
                return False
            return True

    def _trim_archive_locked(self):
        if len(self._data["archive"]) <= self.max_archive_entries:
            return {}
        ordered = sorted(
            self._data["archive"].items(),
            key=lambda item: (
                _archive_status_priority(item[1]),
                item[1].get("updatedAt", 0),
            ),
            reverse=True,
        )
        kept = dict(ordered[: self.max_archive_entries])
        removed = {
            key: entry for key, entry in self._data["archive"].items()
            if key not in kept
        }
        self._data["archive"] = kept
        self._logger(
            f"Subscription archive limit removed {len(removed)} older entry(ies) "
            f"to keep the configured maximum of {self.max_archive_entries}."
        )
        return removed


class SubscriptionManager:
    """Scheduler and scan coordinator around :class:`SubscriptionStore`."""

    def __init__(
        self,
        *,
        store,
        probe,
        enqueue,
        status_reader=None,
        height_probe=None,
        delivered_height_reader=None,
        delivered_file_reader=None,
        logger=None,
        activity_registry=None,
        clock=time.time,
        tick_seconds=15,
        probe_limit=SUBSCRIPTION_PROBE_LIMIT,
    ):
        self.store = store
        self._probe = probe
        self._enqueue = enqueue
        self._status_reader = status_reader or (lambda _download_id: "failed")
        # Both are optional. Without them a subscription that asked for
        # upgrades simply never sees one, which is the same behaviour it had
        # before upgrades existed.
        self._height_probe = height_probe
        self._delivered_height_reader = (
            delivered_height_reader or (lambda _download_id: 0)
        )
        # Where the media landed, so the archive can say when the user has
        # since deleted it. Recorded, never acted on: the file is theirs.
        self._delivered_file_reader = (
            delivered_file_reader or (lambda _download_id: "")
        )
        self._logger = logger or (lambda _message: None)
        self._activity_registry = activity_registry
        self._clock = clock
        self._tick_seconds = max(1.0, float(tick_seconds))
        # How many entries the probe asks for. A scan that comes back short
        # of this has seen the whole source; one that fills it has not.
        self._probe_limit = max(1, int(probe_limit or 1))
        self._lock = threading.RLock()
        self._scan_ids = set()
        # Bounds concurrent yt-dlp scan processes across every entry path
        # (scheduler, GUI "Scan now", API). Waiting requests hold a thread but
        # no subprocess, and none are dropped.
        self._scan_gate = threading.BoundedSemaphore(SUBSCRIPTION_SCAN_MAX_CONCURRENT)
        self._stop = threading.Event()
        self._thread = None

    def list_subscriptions(self):
        return self.store.list_subscriptions()

    def archive_entries(self):
        """Return the durable archive for unified history lookup."""
        return self.store.archive_entries()

    def archive_entry(self, key):
        """Return one archive record without copying the whole archive."""
        return self.store.archive_entry(key)

    def archive_page(self, subscription_id="", *, limit=200, offset=0):
        """One subscription's captured items, newest first."""
        return self.store.archive_page(
            subscription_id, limit=limit, offset=offset,
        )

    def forget_archive_entry(self, key):
        """Let a captured item through again on the next scan."""
        return self.store.forget_archive_entry(key)

    def archive_history_view(self):
        """Return the cheap scalar projection History merges into its rows."""
        return self.store.archive_history_view()

    def snapshot(self):
        with self._lock:
            scanning = sorted(self._scan_ids)
            running = bool(self._thread and self._thread.is_alive())
        return {
            "subscriptions": self.store.list_subscriptions(),
            "archive": self.store.archive_summary(),
            "schedulerRunning": running,
            "scanning": scanning,
        }

    def add_subscription(self, url, interval_minutes=60, enabled=True,
                         title="", delivery=None):
        return self.store.add_subscription(
            url,
            interval_minutes=interval_minutes,
            enabled=enabled,
            title=title,
            delivery=delivery,
        )

    def get_subscription(self, sub_id):
        return self.store.get_subscription(str(sub_id))

    def restore_subscription(self, record):
        return self.store.restore_subscription(record)

    def load_removal_undo(self):
        return self.store.load_removal_undo()

    def clear_removal_undo(self):
        return self.store.clear_removal_undo()

    def remove_subscription_with_undo(self, sub_id):
        return self.store.remove_subscription_with_undo(str(sub_id))

    def update_subscription(self, sub_id, **fields):
        allowed = {"url", "interval_minutes", "enabled", "title", "delivery"}
        values = {key: value for key, value in fields.items() if key in allowed}
        return self.store.update_subscription(str(sub_id), **values)

    def remove_subscription(self, sub_id):
        return self.store.remove_subscription(str(sub_id))

    def _persistence_message(self):
        return (
            self.store.persistence_error()
            or "Could not save subscriptions. Check disk space and permissions."
        )

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="AstraDownloaderSubscriptions",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self, timeout=2):
        timeout = max(0.1, float(timeout))
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                self._logger(
                    "Subscription scheduler stop timed out after "
                    f"{timeout:.1f}s; a scan is still finishing."
                )
        with self._lock:
            if self._thread is thread and (not thread or not thread.is_alive()):
                self._thread = None

    def _run(self):
        # A first pass is intentionally immediate: adding a subscription while
        # the companion is running should not wait for an entire interval.
        while not self._stop.is_set():
            try:
                self.scan_due()
            except Exception as error:  # noqa: BLE001
                self._logger(f"Subscription scheduler failed: {error}")
            self._stop.wait(self._tick_seconds)

    def scan_due(self, now=None):
        due = self.store.due_subscriptions(now)
        results = []
        for item in due:
            if self._stop.is_set():
                break
            results.append(self.scan_subscription(item["id"], now=now, manual=False))
        return results

    def request_scan(self, sub_id):
        sub_id = str(sub_id)
        if not self.store.get_subscription(sub_id):
            return None, self.store.persistence_error() or "Subscription no longer exists."
        with self._lock:
            if sub_id in self._scan_ids:
                return {"id": sub_id, "scheduled": False, "scanning": True}, None
            self._scan_ids.add(sub_id)
        threading.Thread(
            target=self._run_requested_scan,
            args=(sub_id,),
            name=f"AstraSubscriptionScan-{sub_id}",
            daemon=True,
        ).start()
        return {"id": sub_id, "scheduled": True}, None

    def _run_requested_scan(self, sub_id):
        try:
            self.scan_subscription(sub_id, manual=True, _claimed=True)
        except Exception as error:  # noqa: BLE001
            self._logger(f"Manual subscription scan failed for {sub_id}: {error}")
            with self._lock:
                self._scan_ids.discard(str(sub_id))

    def scan_now(self, sub_id, *, background=False):
        if background:
            return self.request_scan(sub_id)
        return self.scan_subscription(sub_id, manual=True)


    def _upgrade_height(self, subscription, key, candidate):
        """The height a re-fetch would actually deliver, if it beats the copy.

        Returns 0 — meaning "do not re-fetch" — unless the subscription asked
        for upgrades, the entry is a completed one with a recorded height, and
        a probe is wired up. The probe costs a metadata fetch per captured
        video per scan, which is why nothing here happens by default.

        The available height is capped by the subscription's own quality
        first. Without that, a subscription pinned to 720p against a 1080p
        channel sees 1080 > 720 on every scan and re-downloads the same 720p
        file forever.
        """
        if not subscription.get("upgradeIfBetter") or self._height_probe is None:
            return 0
        entry = self.store.archive_entry(key)
        if entry.get("status") != "complete":
            return 0
        if not _safe_nonnegative_int(entry.get("deliveredHeight")):
            return 0
        try:
            available = max(0, int(self._height_probe(candidate.get("url")) or 0))
        except Exception as error:  # noqa: BLE001
            self._logger(
                f"Could not check {candidate.get('title') or 'an upload'} for a "
                f"better version: {error}"
            )
            return 0
        cap = str(subscription.get("quality") or "").strip()
        if cap.isdigit():
            available = min(available, int(cap))
        return available

    def _reserve_candidates(self, sub_id, candidates, now, subscription=None):
        """Claim every candidate. Returns the claimed keys and the tallies."""
        subscription = subscription or {}
        claimed = []
        skipped = 0
        errors = []
        for candidate in candidates:
            if self._stop.is_set():
                break
            key = subscription_archive_key(candidate)
            reserved = self.store.reserve_archive(
                key, candidate, sub_id, now=now,
                upgrade_height=self._upgrade_height(
                    subscription, key, candidate),
            )
            if reserved in (RESERVE_ALREADY_PRESENT, RESERVE_RETRY_BACKOFF):
                skipped += 1
                continue
            if reserved == RESERVE_RETRY_EXHAUSTED:
                skipped += 1
                entry = self.store.archive_entry(key)
                attempts = max(
                    1,
                    _safe_nonnegative_int(entry.get("attempts")),
                )
                last_error = self.store._clean(entry.get("lastError"), "", 500)
                message = (
                    f"{candidate.get('title') or '(untitled)'}: stopped retrying "
                    f"after {attempts} attempts"
                )
                if last_error:
                    message += f": {last_error}"
                errors.append(message)
                continue
            if reserved != RESERVE_OK:
                errors.append(
                    self._persistence_message()
                    if reserved == RESERVE_SAVE_FAILED else
                    "Could not record the scheduled download; check disk "
                    "space and permissions."
                )
                continue
            claimed.append((key, candidate))
        return claimed, skipped, errors

    def _enqueue_claimed(self, started, claimed, now):
        """Queue each claimed candidate and mark the claim against it."""
        queued = 0
        errors = []
        for key, candidate in claimed:
            if self._stop.is_set():
                self.store.release_archive(
                    key,
                    "Scheduled scan stopped before queueing this item.",
                    now=now,
                )
                continue
            try:
                result = self._enqueue(started, candidate, key)
                if isinstance(result, tuple):
                    download_id, enqueue_error = result
                else:
                    download_id, enqueue_error = result, None
            except Exception as error:  # noqa: BLE001
                download_id, enqueue_error = None, str(error)
            if enqueue_error or not download_id:
                message = str(enqueue_error or "Download could not be queued.")[:500]
                self.store.release_archive(key, message, now=now)
                errors.append(message)
                continue
            if not self.store.mark_archive_queued(key, download_id, now=now):
                errors.append(self._persistence_message())
            queued += 1
        return queued, errors

    def _claim_candidates(self, started, sub_id, candidates, now):
        """Reserve every candidate, persist, then queue what was claimed.

        The two phases are separate on purpose. ``_enqueue`` reaches the
        download manager, which persists its own queue synchronously and
        restores it on the next launch, so a claim that is still only in memory
        when the process dies leaves a restored download with no archive entry
        behind it — ``reconcile_downloads`` finds nothing to reap and the next
        scan queues the same video again. Flushing the reservations first means
        the archive entry is on disk before anything can be enqueued against
        it, and the queueing phase then coalesces on its own.
        """
        with self.store.batched_saves() as reservation_batch:
            claimed, skipped, errors = self._reserve_candidates(
                sub_id, candidates, now, subscription=started,
            )
        if reservation_batch.failed:
            errors.append(self._persistence_message())
            return 0, skipped + len(claimed), errors

        with self.store.batched_saves() as queue_batch:
            queued, queue_errors = self._enqueue_claimed(started, claimed, now)
        errors.extend(queue_errors)
        if queue_batch.failed:
            errors.append(self._persistence_message())
        return queued, skipped, errors

    def scan_subscription(self, sub_id, *, now=None, manual=False, _claimed=False):
        sub_id = str(sub_id)
        if not _claimed:
            with self._lock:
                if sub_id in self._scan_ids:
                    return {"id": sub_id, "queued": 0, "skipped": 0, "scanning": True}
                self._scan_ids.add(sub_id)
        # Acquired after the per-id claim so a duplicate request still gets its
        # fast "scanning" answer, and released by the finally below on every
        # path, including a propagating exception.
        self._scan_gate.acquire()
        activity_token = None
        if self._activity_registry is not None:
            try:
                activity_token = self._activity_registry.begin_activity()
            except Exception as error:  # noqa: BLE001
                self._logger(f"Could not register subscription activity: {error}")
        try:
            started = self.store.begin_scan(sub_id, now=now)
            if not started:
                return {
                    "id": sub_id,
                    "queued": 0,
                    "skipped": 0,
                    "error": self.store.persistence_error()
                    or "Subscription no longer exists.",
                }
            if manual and not self.store.reset_archive_retries(sub_id, now=now):
                message = self._persistence_message()
                self.store.finish_scan(sub_id, error=message, now=now)
                return {"id": sub_id, "queued": 0, "skipped": 0, "error": message}
            try:
                probe_result = self._probe(started["url"])
                if isinstance(probe_result, tuple):
                    entries, probe_error = probe_result
                else:
                    entries, probe_error = probe_result, None
            except Exception as error:  # noqa: BLE001
                entries, probe_error = [], str(error)
            if probe_error:
                message = str(probe_error)[:500]
                self.store.finish_scan(sub_id, error=message, now=now)
                return {"id": sub_id, "queued": 0, "skipped": 0, "error": message}

            raw_entries = list(entries) if isinstance(entries, (list, tuple)) else []
            # The probe asks for one more than its limit, so "fewer than the
            # limit came back" and "the source has exactly the limit" stop
            # being the same observation. Judged on the RAW count: a single
            # unusable entry dropped below would otherwise turn a truncated
            # window into a claim that the whole source was seen.
            complete_listing = len(raw_entries) <= self._probe_limit
            candidates = []
            for entry in raw_entries[:self._probe_limit]:
                candidate = normalize_subscription_candidate(
                    entry,
                    normalize_url=self.store._normalize_url,
                    is_youtube_url=self.store._is_youtube_url,
                    clean_text=self.store._clean_text,
                )
                if candidate:
                    candidates.append(candidate)

            # Two coalesced persists for the whole candidate loop instead of
            # two per candidate; _claim_candidates explains why it is two and
            # not one.
            queued, skipped, errors = self._claim_candidates(
                started, sub_id, candidates, now,
            )


            # Identical failures repeat once per candidate; the user needs
            # the cause, not the count.
            unique_errors = list(dict.fromkeys(errors))
            error = "; ".join(unique_errors[:3])
            # An archived item the source no longer lists has been deleted
            # upstream. Only a scan that returned fewer entries than its own
            # limit has seen the whole source, so only that scan may say so.
            # Batched with finish_scan: both write the same document, and the
            # coalescing budget this scan is held to counts writes, not calls.
            with self.store.batched_saves() as finish_batch:
                self.store.mark_scan_sightings(
                    sub_id,
                    [subscription_archive_key(candidate)
                     for candidate in candidates],
                    complete_listing=complete_listing,
                    now=now,
                )
                finished = self.store.finish_scan(
                    sub_id,
                    queued=queued,
                    skipped=skipped,
                    error=error,
                    now=now,
                )
            if finish_batch.failed:
                finished = False
            if not finished and not error:
                error = self._persistence_message()
            return {
                "id": sub_id,
                "queued": queued,
                "skipped": skipped,
                "error": error,
            }
        finally:
            self._scan_gate.release()
            if activity_token is not None:
                try:
                    self._activity_registry.end_activity(activity_token)
                except Exception as error:  # noqa: BLE001
                    self._logger(f"Could not release subscription activity: {error}")
            with self._lock:
                self._scan_ids.discard(sub_id)

    def handle_download_completed(self, download_id):
        status = self._status_reader(download_id)
        try:
            delivered_height = self._delivered_height_reader(download_id)
        except Exception as error:  # noqa: BLE001
            self._logger(f"Could not read the delivered height: {error}")
            delivered_height = 0
        try:
            file_path = self._delivered_file_reader(download_id)
        except Exception as error:  # noqa: BLE001
            self._logger(f"Could not read the delivered file path: {error}")
            file_path = ""
        return self.store.mark_download(
            download_id,
            status,
            error="Scheduled download failed." if status != "complete" else "",
            delivered_height=delivered_height,
            file_path=file_path,
        )

    def reconcile_downloads(self, downloads):
        return self.store.reconcile_downloads(downloads)
