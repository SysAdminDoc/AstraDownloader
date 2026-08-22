# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

### P2

### P3

- [ ] P3 — AD-46 — Also persist the queue outside the manager lock
  Why: `_persist_locked` runs `atomic_write_json` → `os.fsync` under `DownloadManagerCore._lock` from ~15 call sites, and the Qt main thread takes that same lock every 500 ms via `update_timer` → `_update_ui`. On a slow or BitLocker-throttled disk this is a visible stall that nothing measures. Same shape as AD-11, lower frequency.
  Evidence: `astra_downloader/download.py:3706-3715`, called from `:3696, :3902, :4402, :5649`; `gui.py:1166-1168`, `:4148`.
  Touches: `astra_downloader/download.py`
  Acceptance: the serialize+fsync happens outside the lock (snapshot under the lock, write after); a test asserts the lock is not held across the write.
  Complexity: M
