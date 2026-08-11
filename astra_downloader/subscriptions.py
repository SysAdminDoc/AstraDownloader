"""Durable scheduled subscription ingestion for the Astra Downloader.

The companion deliberately keeps subscription state separate from the normal
download history.  A subscription document contains the schedule and a
bounded archive of video keys, while the download queue carries the small
amount of linkage needed to reconcile a scan with a restart.  Ordinary
downloads never consult this store and remain re-downloadable.
"""

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
    "SUBSCRIPTION_SCHEMA_VERSION",
    "SUBSCRIPTION_MIN_INTERVAL_MINUTES",
    "SUBSCRIPTION_MAX_INTERVAL_MINUTES",
    "SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS",
    "SUBSCRIPTION_RETRY_BASE_SECONDS",
    "SUBSCRIPTION_MAX_RECORDS",
    "SUBSCRIPTION_MAX_ARCHIVE_ENTRIES",
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


SUBSCRIPTION_SCHEMA_VERSION = 1
SUBSCRIPTION_MIN_INTERVAL_MINUTES = 5
SUBSCRIPTION_MAX_INTERVAL_MINUTES = 7 * 24 * 60
SUBSCRIPTION_MAX_ARCHIVE_ATTEMPTS = 3
SUBSCRIPTION_RETRY_BASE_SECONDS = SUBSCRIPTION_MIN_INTERVAL_MINUTES * 60
SUBSCRIPTION_MAX_RECORDS = 100
SUBSCRIPTION_MAX_ARCHIVE_ENTRIES = 20_000
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
        }

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

    def _save_locked(self):
        if not self._compatible:
            return False
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

    def add_subscription(self, url, *, interval_minutes=60, enabled=True, title="", now=None):
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
            }
            self._data["subscriptions"].append(record)
            if not self._save_locked():
                self._data["subscriptions"].pop()
                return None, self._save_failure_message()
            return _copy(record), None

    def update_subscription(self, sub_id, *, url=None, interval_minutes=None,
                            enabled=None, title=None, now=None):
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
            record["nextScanAt"] = now + record["intervalMinutes"] * 60
            record["updatedAt"] = now
            if not self._save_locked():
                record.clear()
                record.update(before)
                return False
            return True

    def reserve_archive(self, key, candidate, subscription_id, now=None):
        """Claim an archive key.

        Failed claims are retried with a bounded, increasing delay. Once the
        attempt budget is spent, the scheduler gets a distinct outcome so it
        can name the candidate and its last failure instead of silently
        re-enqueueing it forever.
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
                if existing.get("status") in {"reserved", "queued", "complete"}:
                    return RESERVE_ALREADY_PRESENT
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

    def mark_download(self, download_id, status, error="", now=None):
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

    def archive_entries(self):
        with self._lock:
            return _copy(self._data["archive"])

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
        logger=None,
        activity_registry=None,
        clock=time.time,
        tick_seconds=15,
    ):
        self.store = store
        self._probe = probe
        self._enqueue = enqueue
        self._status_reader = status_reader or (lambda _download_id: "failed")
        self._logger = logger or (lambda _message: None)
        self._activity_registry = activity_registry
        self._clock = clock
        self._tick_seconds = max(1.0, float(tick_seconds))
        self._lock = threading.RLock()
        self._scan_ids = set()
        self._stop = threading.Event()
        self._thread = None

    def list_subscriptions(self):
        return self.store.list_subscriptions()

    def archive_entries(self):
        """Return the durable archive for unified history lookup."""
        return self.store.archive_entries()

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

    def add_subscription(self, url, interval_minutes=60, enabled=True, title=""):
        return self.store.add_subscription(
            url,
            interval_minutes=interval_minutes,
            enabled=enabled,
            title=title,
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
        allowed = {"url", "interval_minutes", "enabled", "title"}
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

    def scan_subscription(self, sub_id, *, now=None, manual=False, _claimed=False):
        sub_id = str(sub_id)
        if not _claimed:
            with self._lock:
                if sub_id in self._scan_ids:
                    return {"id": sub_id, "queued": 0, "skipped": 0, "scanning": True}
                self._scan_ids.add(sub_id)
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

            candidates = []
            for entry in entries if isinstance(entries, (list, tuple)) else []:
                candidate = normalize_subscription_candidate(
                    entry,
                    normalize_url=self.store._normalize_url,
                    is_youtube_url=self.store._is_youtube_url,
                    clean_text=self.store._clean_text,
                )
                if candidate:
                    candidates.append(candidate)

            queued = 0
            skipped = 0
            errors = []
            for candidate in candidates:
                if self._stop.is_set():
                    break
                key = subscription_archive_key(candidate)
                reserved = self.store.reserve_archive(key, candidate, sub_id, now=now)
                if reserved == RESERVE_ALREADY_PRESENT:
                    skipped += 1
                    continue
                if reserved == RESERVE_RETRY_BACKOFF:
                    skipped += 1
                    continue
                if reserved == RESERVE_RETRY_EXHAUSTED:
                    skipped += 1
                    entry = self.store.archive_entries().get(key, {})
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
                if self._stop.is_set():
                    self.store.release_archive(
                        key,
                        "Scheduled scan stopped before queueing this item.",
                        now=now,
                    )
                    break
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

            # Identical failures repeat once per candidate; the user needs
            # the cause, not the count.
            unique_errors = list(dict.fromkeys(errors))
            error = "; ".join(unique_errors[:3])
            finished = self.store.finish_scan(
                sub_id,
                queued=queued,
                skipped=skipped,
                error=error,
                now=now,
            )
            if not finished and not error:
                error = self._persistence_message()
            return {
                "id": sub_id,
                "queued": queued,
                "skipped": skipped,
                "error": error,
            }
        finally:
            if activity_token is not None:
                try:
                    self._activity_registry.end_activity(activity_token)
                except Exception as error:  # noqa: BLE001
                    self._logger(f"Could not release subscription activity: {error}")
            with self._lock:
                self._scan_ids.discard(sub_id)

    def handle_download_completed(self, download_id):
        status = self._status_reader(download_id)
        return self.store.mark_download(
            download_id,
            status,
            error="Scheduled download failed." if status != "complete" else "",
        )

    def reconcile_downloads(self, downloads):
        return self.store.reconcile_downloads(downloads)
