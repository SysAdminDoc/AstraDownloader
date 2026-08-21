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

- [ ] P2 — AD-26 — Finish the playlist staging step: per-item edits and archive flags
  Why: the selection-only staging dialog shipped 2026-08-14 (Review playlist → `PlaylistStagingDialog` → `playlist_items`), but pruning is the smaller half — JDownloader's LinkGrabber and YTDLnis both let the user edit items (format/quality/name) per item or batch-apply, and nothing yet flags entries the subscription archive already holds.
  Evidence: RESEARCH.md "Competitive Landscape" (JDownloader, YTDLnis per-item editing); `astra_downloader/gui.py` `PlaylistStagingDialog`; `subscriptions.py` archive keys.
  Touches: `astra_downloader/gui.py` (`PlaylistStagingDialog`), `download.py`, `subscriptions.py`
  Acceptance: per-item and batch-apply edits both work in the staging dialog; items already in the subscription archive are flagged; a render scenario captures the dialog.
  Complexity: M

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

- [ ] P2 — AD-32 — Extend the health-check set with the checks Radarr proves matter
  Why: the pre-flight panel checks download preconditions; Radarr's 33 named checks cover the *environment*, and three map onto known bug classes here — state living where the updater will wipe it (`AppDataLocationCheck`, the portable-mode class), a site failing for an extended period rather than one download failing (`IndexerLongTermStatusCheck`, the right shape for bot-gating), and clock skew breaking TLS and cookie expiry (`SystemTimeCheck`). Output folder missing/unwritable/on a disconnected drive is the same family.
  Evidence: https://github.com/Radarr/Radarr/tree/develop/src/NzbDrone.Core/HealthCheck/Checks; `astra_downloader/health.py`; existing per-domain refusal circuits in `download.py`.
  Touches: `astra_downloader/health.py`, `gui_download_page.py`
  Acceptance: each new check is a named class with its own remedy action, surfaced in the same panel; a test drives each into its failing state.
  Complexity: M

- [ ] P2 — AD-33 — Split the test monolith and run it in parallel
  Why: `test_astra_downloader.py` is 21,137 lines holding 951 of 964 tests, and the suite runs 964 tests + 610 subtests in 545 s serially with no `pytest-xdist`. Every change pays that.
  Evidence: measured 2026-08-14; `pytest.ini` has no parallel configuration.
  Touches: `astra_downloader/test_*.py`, `pytest.ini`, `astra_downloader/conftest.py`, `requirements.txt`
  Acceptance: tests are split by domain (download / gui / routes / subscriptions / health / config / build); `-n auto` is the default and the suite is green under it; wall-clock is recorded in CLAUDE.md.
  Complexity: L

- [ ] P2 — AD-34 — Remove the last source pins and assert a test-count floor
  Why: three `inspect.getsource` assertions survive plus one exact-source-line pin, and a previous pass recorded zero — the claim was wrong. Separately, six tests skip on "yt-dlp is not installed" and `_qapp_init_error` is a *module global*, so one `QApplication` failure disables every subsequent GUI test in the run. Nothing asserts how many tests actually executed, so a hollowed-out run reports green.
  Evidence: `test_astra_downloader.py:2472, 20004, 20099, 20402`; `:11044-11052`; skip sites at `:4153, 10762, 14550, 15118, 18978, 19356`.
  Touches: `astra_downloader/test_astra_downloader.py`, `astra_downloader/conftest.py`
  Acceptance: zero `getsource`/source-text assertions remain; a session-level check fails the run when executed-test count falls below a recorded floor, naming which group was skipped.
  Complexity: M

- [ ] P2 — AD-35 — Render History and Settings in German and Arabic RTL
  Why: 54 render scenarios exist but locale variants cover only the Download and Browser extension pages — while the fixed pixel widths live elsewhere: `label.setFixedWidth(92)` on translated column headers and `heading.setFixedWidth(142)` on translated section headings. Nothing has ever looked at those pages in a longer language.
  Evidence: `scripts/render-companion-gui.py` scenario list; `astra_downloader/gui_history_page.py:135`; `gui.py:1304, 5122`; `build/companion-ui-smoke/`.
  Touches: `scripts/render-companion-gui.py`, `astra_downloader/gui_history_page.py`, `gui.py`
  Acceptance: German and Arabic captures exist for History, Settings, Sign-ins and Subscriptions; no translated label is clipped or elided in any of them; fixed widths become minimums where a translation needs more.
  Complexity: M

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

- [ ] P2 — AD-42 — Deprioritise YouTube's AI "Super Resolution" formats
  Why: YouTube began serving AI-upscaled renditions that sort above the genuine source by resolution; yt-dlp#15433 (13 reactions, opened 2025-12-29) is open and no GUI exposes a control. An archivist wants the original, and the existing `--format-sort` builder already knows to emit `res` first.
  Evidence: yt-dlp#15433; `astra_downloader/download.py` `build_video_format_args` and the `--format-sort` ordering rule recorded in CLAUDE.md.
  Touches: `astra_downloader/download.py`, `gui_settings_page.py`
  Acceptance: a setting deprioritises upscaled renditions; verified against a `--load-info-json` fixture carrying both a native and an upscaled format. *Needs live validation of the field yt-dlp exposes for the marker on the pinned yt-dlp (2026.08.19 once AD-48 lands; 2026.7.4 until then).*
  Note (2026-08-21): 2026.08.19 release notes do not mention Super Resolution. #15433 is still open. Do not invent a format key — probe a fixture on the pinned exe.
  Complexity: S

- [ ] P2 — AD-43 — Split `create_api` by resource
  Why: it is a single 1,262-line function holding 27 routes and 54 unpacked dependencies in one closure, and it is one of the three remaining `inspect.getsource` targets (AD-34) precisely because there is no smaller unit to assert against.
  Evidence: `astra_downloader/routes.py:196`; `test_astra_downloader.py:20004`.
  Touches: `astra_downloader/routes.py`
  Acceptance: routes are grouped into per-resource registrars (downloads / queue / subscriptions / site-logins / system) taking the same dependency mapping; the `_REQUIRED_*_DEPENDENCIES` contract is unchanged; all route tests pass untouched.
  Complexity: M

### P3

- [ ] P3 — AD-46 — Also persist the queue outside the manager lock
  Why: `_persist_locked` runs `atomic_write_json` → `os.fsync` under `DownloadManagerCore._lock` from ~15 call sites, and the Qt main thread takes that same lock every 500 ms via `update_timer` → `_update_ui`. On a slow or BitLocker-throttled disk this is a visible stall that nothing measures. Same shape as AD-11, lower frequency.
  Evidence: `astra_downloader/download.py:3706-3715`, called from `:3696, :3902, :4402, :5649`; `gui.py:1166-1168`, `:4148`.
  Touches: `astra_downloader/download.py`
  Acceptance: the serialize+fsync happens outside the lock (snapshot under the lock, write after); a test asserts the lock is not held across the write.
  Complexity: M
