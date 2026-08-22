# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

### P2

- [ ] P2 — AD-25 — Turn subscriptions into an archive manager
  Why: the page is one row per subscription with Scan now / Remove and an aggregate "10 archived · 2 queued". There is no per-subscription output folder, format, quality or naming template, no view of what was archived, no way to unmark an item, and no upgrade rule. This is the densest unmet need in the market: pinchflat#408 (17), #139 (15), #805 (11) and yt-dlp#953 (17) are 60 combined reactions on one problem nobody has solved.
  Evidence: `build/companion-ui-smoke/subscriptions-populated.png`; `astra_downloader/gui_subscriptions_page.py` (109 lines); RESEARCH.md "Market signal"; ytdl-sub `keep_max_files`; Radarr `DecisionEngine/Specifications` upgrade specification.
  Touches: `astra_downloader/subscriptions.py`, `gui_subscriptions_page.py`, `gui.py`, `routes.py`, `config.py`
  Acceptance: a subscription carries its own destination, format, quality and template; an archive view lists captured items with an "allow re-download" action; a re-scan fetches only when the available format is a strict upgrade over what is on disk; schema migration covers existing records.
  Complexity: XL

- [ ] P2 — AD-40 — Detect archived items the source has since deleted
  Why: an archive whose upstream entry disappears silently rots. Tartube's "Missing Videos" folder is the only implementation in the field, and pinchflat#805 (11 reactions) asks for the inverse guarantee — do not re-download what the user deleted locally. Both need the same reconciliation between the archive and the last scan.
  Evidence: Tartube README §6.25; pinchflat#805; `astra_downloader/subscriptions.py` archive keys.
  Touches: `astra_downloader/subscriptions.py`, `gui_subscriptions_page.py`, `gui_history_page.py`
  Acceptance: a scan that no longer sees a previously-archived item marks it, without deleting anything; a locally-deleted file is not silently re-fetched; both states are visible and reversible. Depends on AD-25.
  Complexity: M

### P3

- [ ] P3 — AD-46 — Also persist the queue outside the manager lock
  Why: `_persist_locked` runs `atomic_write_json` → `os.fsync` under `DownloadManagerCore._lock` from ~15 call sites, and the Qt main thread takes that same lock every 500 ms via `update_timer` → `_update_ui`. On a slow or BitLocker-throttled disk this is a visible stall that nothing measures. Same shape as AD-11, lower frequency.
  Evidence: `astra_downloader/download.py:3706-3715`, called from `:3696, :3902, :4402, :5649`; `gui.py:1166-1168`, `:4148`.
  Touches: `astra_downloader/download.py`
  Acceptance: the serialize+fsync happens outside the lock (snapshot under the lock, write after); a test asserts the lock is not held across the write.
  Complexity: M
