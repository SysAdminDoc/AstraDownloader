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

- [ ] P2 — AD-29 — Let the user pin and roll back a managed binary
  Why: auto-updating yt-dlp/ffmpeg/Deno is survival, but it also silently breaks things (GDownloader#54: an auto-update killed nvenc). Pinning is also the clean way out of the ffmpeg security-floor-vs-capability deadlock, and YTDLnis ships exactly this.
  Evidence: RESEARCH.md "Competitive Landscape" (YTDLnis component management); `Roadmap_Blocked.md` §"Make `npm run check` pass" item 2; `astra_downloader/health.py` `managed_binary_state()`.
  Touches: `astra_downloader/health.py`, `astra_downloader.py`, `gui_settings_page.py`, `config.py`
  Acceptance: each managed binary can be pinned to a chosen version and rolled back; a pin below the security floor is refused with a named reason; the pinned version and digest flow into the licence inventory (AD-09).
  Complexity: L

- [ ] P2 — AD-30 — Mint PO tokens from a sidecar the app owns
  Why: `po-token-required` is a named failure cause with advice but no remedy, because `--no-plugin-dirs` is a stated security property and bgutil's provider is plugin-only. The non-plugin route is `--extractor-args "youtube:po_token=CLIENT.CONTEXT+TOKEN"`, so the app can run the provider as a managed binary it controls, mint per-video, and pass the token on argv — keeping third-party code out of yt-dlp's process.
  Evidence: `astra_downloader/download.py:627, 3002-3008`; `SECURITY.md` §"yt-dlp is spawned with its plugin directories disabled"; yt-dlp PO Token Guide; yt-dlp#14404 (380 reactions), #15012 (226).
  Touches: `astra_downloader/health.py`, `astra_downloader.py`, `download.py`, `license-policy.json`
  Acceptance: with the sidecar running, a video that previously failed `po-token-required` succeeds; with it absent, behaviour and the named cause are unchanged; no yt-dlp plugin directory is enabled. *Needs live validation that a self-minted token is accepted on the pinned 2026.7.4.*
  Complexity: L

- [ ] P2 — AD-33 — Split the test monolith and run it in parallel
  Why: `test_astra_downloader.py` is 21,137 lines holding 951 of 964 tests, and the suite runs 964 tests + 610 subtests in 545 s serially with no `pytest-xdist`. Every change pays that.
  Evidence: measured 2026-08-14; `pytest.ini` has no parallel configuration.
  Touches: `astra_downloader/test_*.py`, `pytest.ini`, `astra_downloader/conftest.py`, `requirements.txt`
  Acceptance: tests are split by domain (download / gui / routes / subscriptions / health / config / build); `-n auto` is the default and the suite is green under it; wall-clock is recorded in CLAUDE.md.
  Complexity: L

- [ ] P2 — AD-38 — Take the cheap Windows shell integrations
  Why: one prerequisite — a stable AppUserModelID set early in `main()` plus a Start-menu `.lnk` carrying it — unlocks jump-list Tasks ("Paste and download", "Open downloads folder"), correct taskbar grouping, and recent-items. Separately `RegisterApplicationRestart` makes a Windows Update reboot resume the queue instead of silently ending it, and `IFileOperation`/`send2trash` makes a queue delete recoverable.
  Evidence: https://learn.microsoft.com/en-us/windows/win32/shell/taskbar-extensions; RESEARCH.md "Security, Privacy, and Reliability"; taskbar progress is already implemented, so the COM plumbing exists.
  Touches: `astra_downloader/astra_downloader.py`, `gui.py`
  Acceptance: the jump list shows context-free tasks that work when the app is closed; a simulated restart relaunches with `--start-server`; deleting a finished file from the queue sends it to the Recycle Bin. Toasts with action buttons stay out of scope — they need package identity.
  Complexity: M

- [ ] P2 — AD-40 — Detect archived items the source has since deleted
  Why: an archive whose upstream entry disappears silently rots. Tartube's "Missing Videos" folder is the only implementation in the field, and pinchflat#805 (11 reactions) asks for the inverse guarantee — do not re-download what the user deleted locally. Both need the same reconciliation between the archive and the last scan.
  Evidence: Tartube README §6.25; pinchflat#805; `astra_downloader/subscriptions.py` archive keys.
  Touches: `astra_downloader/subscriptions.py`, `gui_subscriptions_page.py`, `gui_history_page.py`
  Acceptance: a scan that no longer sees a previously-archived item marks it, without deleting anything; a locally-deleted file is not silently re-fetched; both states are visible and reversible. Depends on AD-25.
  Complexity: M

- [ ] P2 — AD-57 — Translate the pre-flight repair button labels
  Why: `_set_preflight_row` picks its button text from an `action_labels` dict and calls `tr(action_labels.get(...))`. The extractor only sees string *literals* inside a translating call, so a `.get()` result is invisible and none of the ten repair buttons ("Refresh yt-dlp", "Provision runtime", "Choose a folder", ...) reach any catalogue. The German window shows English buttons in an otherwise translated panel.
  Evidence: `astra_downloader/gui.py` `_set_preflight_row`; CLAUDE.md 2026-08-11 "A module-level string constant is invisible to the i18n extractor"; found while landing AD-32.
  Touches: `astra_downloader/gui.py`, `scripts/build-companion-translations.py`
  Acceptance: every repair button label is declared in all eleven catalogues, and a German render capture shows a translated button; a test fails if a new action code arrives without one.
  Complexity: S

### P3

- [ ] P3 — AD-46 — Also persist the queue outside the manager lock
  Why: `_persist_locked` runs `atomic_write_json` → `os.fsync` under `DownloadManagerCore._lock` from ~15 call sites, and the Qt main thread takes that same lock every 500 ms via `update_timer` → `_update_ui`. On a slow or BitLocker-throttled disk this is a visible stall that nothing measures. Same shape as AD-11, lower frequency.
  Evidence: `astra_downloader/download.py:3706-3715`, called from `:3696, :3902, :4402, :5649`; `gui.py:1166-1168`, `:4148`.
  Touches: `astra_downloader/download.py`
  Acceptance: the serialize+fsync happens outside the lock (snapshot under the lock, write after); a test asserts the lock is not held across the write.
  Complexity: M
