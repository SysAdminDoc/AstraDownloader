# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

- [ ] P0 — AD-01 — Publish v2.7.0, with both artifacts, from a rebuilt binary
  Why: `gh release list` returns only `v2.0.0`; seven versions of fixes reach nobody, the in-app updater and the Astra Deck installer link both resolve to that build, and `v2.0.0` ships no `AstraDownloader-onedir.zip` — so the antivirus fallback the README documents has never existed.
  Evidence: `gh release list`; `check:versions` failure text; RESEARCH.md "Delivery and licence"; cobalt / Motrix / kannagi0303 all died in this exact state.
  Touches: `astra_downloader/build.py`, `scripts/stage-companion-release.js`, `scripts/check-versions.js`, CHANGELOG.md
  Acceptance: `build/companion-build-metadata.json` reports `2.7.0` (it currently reports 2.6.0); the release carries `AstraDownloader.exe`, `AstraDownloader-onedir.zip` and both `.sha256` sidecars; `npm run check:versions` exits 0.
  Note: `Roadmap_Blocked.md` files this as blocked on the PyQt distribution decision. AD-08 removes that dependency; if AD-08 is deferred, AD-01 stays blocked and the blocked entry stands.
  Complexity: S

- [ ] P0 — AD-05 — Cap concurrent subscription scans
  Why: `request_scan` starts a bare thread per subscription with no total cap. `_scan_ids` dedupes per id only and `SUBSCRIPTION_MAX_RECORDS = 100`, so clicking "Scan now" down the list — or `POST /subscriptions/<id>/scan` at its 30/60 s allowance — can hold 100 threads each spawning yt-dlp. Every sibling path is gated (`_formats_gate = Semaphore(2)`, `_transcription_gate = BoundedSemaphore(1)`, `MAX_CONCURRENT = 3`).
  Evidence: `astra_downloader/subscriptions.py:1153-1173`; `download.py:3421-3425`; `routes.py:1238-1258`.
  Touches: `astra_downloader/subscriptions.py`
  Acceptance: a bounded semaphore caps in-flight scans; a test requesting 20 scans proves at most N yt-dlp spawns are concurrent and none are dropped.
  Complexity: S

- [ ] P0 — AD-06 — Make status messages carry a visible tone
  Why: `_set_quick_download_status` sets `setProperty("state", …)` and calls `repolish()`, but `STYLESHEET` has no `QLabel[class="fieldHint"][state=…]` rule — only a flat `color: #8d97a4`. "Download queue is full (200/200)" therefore renders identically to "Clip ranges apply to a single link." Four more status labels set the same dead property. In a product whose thesis is diagnosis, the diagnosis is invisible.
  Evidence: `astra_downloader/gui.py:2400-2404`; `astra_downloader.py:4017` vs the working `tone` rules at `:3997-4035`; `build/companion-ui-smoke/downloads-queue-full.png`; `subscription_status`, `history_page_status`, `site_login_status`, `first_run_status`.
  Touches: `astra_downloader/astra_downloader.py` (STYLESHEET), `gui.py`, `gui_download_page.py`, `gui_history_page.py`, `gui_site_logins_page.py`, `gui_subscriptions_page.py`
  Acceptance: one convention survives (`tone`); success/warning/error each render a distinct colour on all five status labels; a test asserts every `setProperty` tone/state value used has a matching stylesheet rule, so the next unmatched value fails the suite.
  Complexity: M

- [ ] P0 — AD-07 — Invoke Windows system binaries by absolute path, with timeouts
  Why: `icacls`, `powershell` and `schtasks` are passed as bare argv[0]. `CreateProcess` searches the current working directory ahead of `%PATH%`, and the two `icacls` calls are the ones applying the restrictive ACL to the cookie jar — a shadowed `icacls` degrades that hardening silently. Three of the calls also pass no `timeout=`, unlike every other `subprocess.run` in the tree.
  Evidence: `astra_downloader/download.py:867, 887`; `astra_downloader.py:2936, 3685, 3723, 4819, 4924`; missing timeouts at `:3684, :3722, :4819`.
  Touches: `astra_downloader/download.py`, `astra_downloader/astra_downloader.py`
  Acceptance: all six resolve through `%SystemRoot%\System32\…`; every `subprocess.run` in the tree passes `timeout=`; a test pins the resolved paths.
  Complexity: S

- [ ] P0 — AD-47 — Give Chrome/Edge users a way to register the native-messaging host
  Why: the Astra Deck download handoff is dead on every Chromium browser. `LegacyHealthTokenEcho` defaults false, so `/health` no longer echoes a token and reports `nativeChannelRequired: true`; the extension's `MediaDLManager._checkImpl` then `continue`s past every companion port and `check()` never returns a token, so the download button cannot hand off at all. The only way in is `NativeChromeExtensionIds`, which defaults to `""` and has **no GUI field anywhere** — `grep NativeChromeExtensionIds astra_downloader/gui*.py` is empty, and it is in `BUNDLE_EXCLUDED_SETTINGS` so a settings import cannot carry it either. Firefox is unaffected because its Gecko ID (`ytkit@sysadmindoc.github.io`) is fixed and registered by default. This inverts the rollout order `docs/native-messaging-token-bootstrap.md` prescribes: gate 3 says flip the legacy default off *after* packaged Chrome/Firefox validation (gate 2), and gates 1–2 are still open.
  Evidence: measured 2026-08-14 on a clean machine. `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.astra.deck.downloader` and the Edge key are both absent while the Mozilla key is present; live `/health` on 9751 returns `legacyTokenEcho: false`, `nativeChannelRequired: true`, no `token`. The mechanism itself is sound — registering a throwaway ID wrote both registry pointers plus `native-hosts/com.astra.deck.downloader.chrome.json` with `allowed_origins: ["chrome-extension://<id>/"]`, and the host answered a `chrome-extension://…` launch with a valid token. Only the ID input is missing. Everything downstream of the token is fine: an authenticated `/download` → `/status` round trip with the extension's exact payload and `X-Auth-Token` header completed and wrote an 18 MB MP4.
  Touches: `astra_downloader/gui_extension_page.py` (ID field on the Extension page), `astra_downloader/gui.py` (save/reload + re-register on change), `astra_downloader/astra_downloader.py` (`register_native_messaging_hosts` already validates via `parse_native_extension_ids`), `scripts/build-companion-translations.py`, `scripts/render-companion-gui.py` (capture scenario)
  Acceptance: a Chrome/Edge extension ID can be entered and cleared in the GUI; saving writes `NativeChromeExtensionIds`, re-runs registration, and the Chrome + Edge registry pointers and manifest appear with exactly that origin; clearing it revokes them; an invalid ID is rejected in the UI rather than reaching `allowed_origins`; a test drives the round trip.
  Complexity: M

### P1

- [ ] P1 — AD-08 — Migrate PyQt6 → PySide6 6.11.1
  Why: PyQt6 is GPL-3.0-only, `LICENSE` is MIT, and the shipped one-file exe is a combined work — the two `decision: unresolved` component entries blocking `npm run check` are that contradiction. PySide6 is LGPL, which lets the app's own code stay MIT. This converts the blocker described in `Roadmap_Blocked.md` from a legal decision into a mechanical refactor.
  Evidence: measured surface — 90 `from PyQt6` imports over 21 files, 17 `pyqtSignal`, 4 submodules, and **0** each of `pyqtSlot`, `pyqtProperty`, `sip`, `QVariant`, `loadUi`, `QtWebEngine`, `QtMultimedia`, `QtSvg`, `QtNetwork`. YTSage (4,465★) and dsymbol/yt-dlp-gui both run this stack on PySide6.
  Touches: all `astra_downloader/gui*.py`, `astra_downloader.py`, `build.py`, `requirements.txt`, `constraints-release.txt`, `license-policy.json`, `pytest.ini` (`qt_api`), `scripts/render-companion-gui.py`
  Acceptance: 964 tests and all 54 render captures pass on PySide6; `license-policy.json` has no unresolved *component* entry; the onedir zip is documented as the LGPL relinking artifact; the exe size delta is recorded.
  Note: this supersedes the "needs the PyQt distribution decision" framing in `Roadmap_Blocked.md` — the decision is still the maintainer's, but one of the two options is now a costed engineering task rather than a legal review. Update or retire that blocked entry when this lands.
  Complexity: L

- [ ] P1 — AD-09 — Resolve the three runtime-helper licence entries as part of staging
  Why: `yt-dlp`, `ffmpeg` and `deno` account for the remaining 16 of 18 licence-inventory issues, and every one is "moving `latest` target, exact version and digest unresolved" — which a real release run can resolve mechanically. Cross-reference `Roadmap_Blocked.md`, which correctly notes FFmpeg-Builds is the asymmetric case (its dated release ships a differently-named archive with a different digest).
  Evidence: `npm run check` output, 18 issues; `astra_downloader/license-policy.json`; `Roadmap_Blocked.md` §"Make `npm run check` pass".
  Touches: `scripts/stage-companion-release.js`, `scripts/companion-license-inventory.js`, `astra_downloader/license-policy.json`
  Acceptance: staging writes the resolved version + digest actually downloaded for each helper into the policy; the inspection accepts a publisher-verified rolling alias only when a resolved digest accompanies it; `check:companion-inventory` exits 0.
  Complexity: M

- [ ] P1 — AD-10 — Announce status changes to assistive technology
  Why: `QAccessible` appears zero times in the tree. `setAccessibleName` is used well (125 calls), but changing a label's text fires no accessibility event, so a screen-reader user who presses Download and is rejected gets silence. WCAG 2.2 SC 4.1.3 Status Messages (AA).
  Evidence: repo-wide grep for `QAccessible`/`updateAccessibility` returns nothing; the five status labels listed in AD-06.
  Touches: `astra_downloader/gui_support.py`, `gui.py`
  Acceptance: a helper raises `QAccessible.Event.Alert` (or `NameChanged`) whenever a status label's text changes; every status setter routes through it; a test asserts the event fires.
  Complexity: S

- [ ] P1 — AD-11 — Stop the subscription scan from fsyncing the whole archive per candidate
  Why: `reserve_archive` then `mark_archive_queued`/`release_archive` each run `_save_locked` → `atomic_write_json` → `os.fsync` on the entire document (up to 20,000 archive records) while holding `SubscriptionStore._lock` — ~100–150 full serialize+fsync cycles for one `--playlist-end 50` scan, on the same lock the Qt main thread and `/health` take. The 3.88 ms/call figure in `CLAUDE.md` was measured without a concurrent scan.
  Evidence: `astra_downloader/subscriptions.py:1238-1298`, `:782-828`, `:504-519`; `config.py:1808-1831`; `SUBSCRIPTION_MAX_ARCHIVE_ENTRIES = 20_000` at `subscriptions.py:53`.
  Touches: `astra_downloader/subscriptions.py`
  Acceptance: one scan performs O(1) persists, not O(candidates); a test counts `atomic_write_json` calls across a 50-candidate scan and asserts the bound; crash-safety of the reservation is preserved (a killed scan must not leak reserved keys).
  Complexity: M

- [ ] P1 — AD-12 — Stop deep-copying the archive on the Qt main thread
  Why: `_history_query` calls `archive_entries()`, which `json`-roundtrips up to 20,000 records under the store lock. `subscriptions.py:941-949` documents this exact trap and ships `archive_entry(key)` as the fix; the GUI caller was never converted. The same function also re-reads and re-sanitises the whole history file per invocation.
  Evidence: `astra_downloader/gui.py:4230-4240`; `subscriptions.py:937-949`, `:1059`; `config.py:2451-2453`.
  Touches: `astra_downloader/gui.py`, `astra_downloader/subscriptions.py`
  Acceptance: the history view reads only the archive records it displays; a test with 20,000 archive entries asserts no full copy occurs on the query path.
  Complexity: M

- [ ] P1 — AD-13 — Widen the catch-reason gate beyond pass-only handlers
  Why: `check-python-catch-reasons.js:42` requires `all(isinstance(statement, ast.Pass) …)`, so any handler that swallows via `return None` / `return ''` / `continue` is never examined. 65 broad handlers currently swallow with no log, no re-raise and no reason (`download.py` 26, `gui.py` 20, `astra_downloader.py` 10, `health.py` 4, `routes.py` 3, `subscriptions.py` 2). CLAUDE.md documents a shipped bug from exactly this class.
  Evidence: `scripts/check-python-catch-reasons.js:38-50`; `CLAUDE.md` §2026-08-06 "A bare `except` around a probe hid a name error".
  Touches: `scripts/check-python-catch-reasons.js`, `tests/python-catch-reason-gate.test.js`, and the annotated handlers
  Acceptance: the gate covers any handler whose body neither logs nor re-raises; the 65 sites are annotated or narrowed; `check:catch-reasons` exits 0.
  Complexity: M

- [ ] P1 — AD-15 — Restore the rationale that `HARDENING.md` was supposed to hold
  Why: two accepted-risk decisions cite a file that does not exist — the SSRF residual (a public DNS name pointed at a private address) and the outputDir allowlist design. The code is correct; the justification is unrecoverable, which is how an accepted risk quietly becomes an unexamined one.
  Evidence: `astra_downloader/config.py:1198`; `astra_downloader/download.py:4309`; no `HARDENING*` file exists anywhere in the tree.
  Touches: `docs/`, `SECURITY.md`, `astra_downloader/config.py`, `astra_downloader/download.py`
  Acceptance: both rationales live in a file that exists (or inline), the comments point at it, and a test asserts every doc path referenced from source resolves.
  Complexity: S

- [ ] P1 — AD-16 — Give every tool button a distinct icon
  Why: `make_line_icon` matches on keyword and falls through to one three-lines-and-dots default, which 15 of 48 tool buttons hit — including *Remove*, *Restore*, *Restore defaults*, *Undo remove*, *Undo import*, *Undo defaults*, *Dismiss*, *Scan now*, *Add subscription*, *Test*, *Import settings*, *Import cookies.txt*. A destructive action and its undo are visually identical. The **Subscriptions** and **Settings** nav entries collide too.
  Evidence: `astra_downloader/gui_support.py:169-275` (the `else` branch at `:267`); `gui.py:1064`, `:1519`; visible in `settings-dirty.png`, `subscriptions-populated.png`, `dashboard-german.png`.
  Touches: `astra_downloader/gui_support.py`
  Acceptance: no two distinct button labels resolve to the same glyph; a test enumerates every `_make_tool_button` label and asserts a unique branch is taken (the fallback is reserved for genuinely unnamed icons).
  Complexity: M

- [ ] P1 — AD-17 — Stop the language picker offering locales that are 0.6 % translated
  Why: eleven locales are advertised; German is 783/783 and the other nine are **5/783** — five nav strings and nothing else. `check:translations` passes because it counts *declared* keys, and the generator writes a missing entry out as its own English source. Selecting Japanese today produces an English UI with a Japanese sidebar.
  Evidence: `py -3.12 scripts/build-companion-translations.py` coverage output, measured 2026-08-14; `astra_downloader/i18n.py` `ADVERTISED_LOCALES`; `Roadmap_Blocked.md` §"Translate the nine incomplete locales".
  Touches: `astra_downloader/i18n.py`, `astra_downloader/gui_settings_page.py`, `scripts/check-companion-translations.py`
  Acceptance: a locale below a stated coverage threshold is either withheld or labelled "partial" in the picker; the threshold is enforced by the gate so a regressing catalogue fails the suite.
  Complexity: S

- [ ] P1 — AD-18 — Put the queue above the fold on the Download page
  Why: `downloads-active-pending.png` is a scenario *with* active and pending downloads and shows none of them at 1120×760. The page stacks first-run panel → paste box → password → four option rows → four hint lines → setup status → readiness grid → pre-flight panel → notices → divider → toolbar → queue. The design invariant is "downloader first"; the download you just started is last, and the pre-flight panel is fully expanded even when every check passes.
  Evidence: `astra_downloader/gui_download_page.py:114-445`; `build/companion-ui-smoke/downloads-active-pending.png`, `downloads-queue-full.png`.
  Touches: `astra_downloader/gui_download_page.py`, `scripts/render-companion-gui.py`, `DownloaderFirstLayoutTests`
  Acceptance: with one active download, the queue's first row is visible at 1120×760 without scrolling; the readiness strip and pre-flight panel collapse to a one-line summary when nothing is wrong and expand on a failing check; `DownloaderFirstLayoutTests` pins the new order.
  Complexity: M

- [ ] P1 — AD-19 — Raise the HTTP dependency floors and pin certifi
  Why: `werkzeug>=3.1.6` misses 3.1.7's `parse_list_header` quoting fix, `Transfer-Encoding` set parsing and host character validation, and 3.1.8's `Request.host` returning `""` on an invalid header — all on the HTTP surface this app exposes. `requests>=2.33.0` is two releases behind 2.34.2. `certifi` is transitive, which means the CA bundle version is whatever the resolver picked.
  Evidence: Werkzeug changelog (3.1.7 2026-03-23, 3.1.8 2026-04-02); `astra_downloader/requirements.txt`, `constraints-release.txt`.
  Touches: `astra_downloader/requirements.txt`, `astra_downloader/constraints-release.txt`, `build/pylock.toml`
  Acceptance: floors are `werkzeug>=3.1.8`, `requests>=2.34.2`, `certifi>=2026.7.22` declared explicitly; `npm run audit:python` and the suite stay green.
  Complexity: S

- [ ] P1 — AD-20 — Move the build interpreter to Python 3.13.15
  Why: python.org shipped no Windows installer after **3.12.10 (2025-04-08)**; 3.12.11/12/13 are source-only and the devguide marks 3.12 `security` ("no more binaries are released"). The build interpreter is frozen ~16 months behind CPython security fixes. PyQt6, PySide6, PyInstaller 6.22 and yt-dlp all ship the identical `cp310-abi3-win_amd64` wheels on 3.13.
  Evidence: https://www.python.org/downloads/release/python-31213/; https://devguide.python.org/versions/.
  Touches: `astra_downloader/build.py`, `constraints-release.txt`, `package.json` scripts, README, CLAUDE.md
  Acceptance: the release build runs on 3.13.15; 964 tests and 54 render captures pass; the 3.11 source floor is unchanged; every `py -3.12` reference in scripts and docs is updated together.
  Complexity: M

- [ ] P1 — AD-21 — Decide the argv-credential question and write it down
  Why: `build_site_login_credential_args` emits `--username`/`--password`/`--video-password`, which are visible in `Win32_Process.CommandLine` to any process running as the same user and are captured by command-line-recording EDR. The store is ACL'd and redacted everywhere else. `SECURITY.md`'s accepted-properties list does not mention it. Open across five passes.
  Evidence: `astra_downloader/download.py` `build_site_login_credential_args`; `SECURITY.md` §Scope Notes (absent).
  Touches: `astra_downloader/download.py`, `SECURITY.md`, `docs/`
  Acceptance: either `--password -` on stdin (with the netrc family still denied) or an explicit accepted-property entry in `SECURITY.md` naming command-line visibility, pinned by test either way.
  Complexity: M

- [ ] P1 — AD-22 — Lock the two unsynchronised mutations in the download manager
  Why: `self.total_completed += 1` is a read-modify-write executed on up to `MAX_CONCURRENT` worker threads, ten lines above `self._history_error` which *is* written under the lock; and `cancel_all` writes `dl.status`, `dl.error`, `dl._cookies` and calls `mark_terminal()` after the `with self._lock:` block exits, while `_worker_entry`'s `finally` mutates the same records under it.
  Evidence: `astra_downloader/download.py:5110`, `:5127`, `:6215-6226`, `:3892-3902`.
  Touches: `astra_downloader/download.py`
  Acceptance: both mutations happen under `_lock`; a test drives concurrent completions and asserts the counter is exact.
  Complexity: S

- [ ] P1 — AD-23 — Make `SERVICE_API_VERSION` a real handshake
  Why: the version is advertised in `/health` and read nowhere — zero hits for `apiVersion`/`api_version` anywhere in the Astra Deck extension. Two independently versioned products share a gate-checked port catalogue with no compatibility check, so a breaking wire change surfaces as an unexplained extension failure.
  Evidence: `astra_downloader/astra_downloader.py:450`, `routes.py:477, 506`; grep of `~/repos/Astra-Deck/extension/`.
  Touches: `astra_downloader/routes.py`, `scripts/companion-port-catalogue.json`, and the Astra Deck repository
  Acceptance: the extension reads `api` from `/health` and shows a named "companion too old / too new" state; a minimum-supported version is declared on both sides and gate-checked like the port catalogue.
  Complexity: M

- [ ] P1 — AD-24 — Render icons at the display's device pixel ratio
  Why: `make_line_icon` builds `QPixmap(size, size)` and never calls `setDevicePixelRatio`, so at 125 % (this machine), 150 % or 200 % scaling every one of ~54 icons is an 18 px bitmap upscaled by Qt.
  Evidence: `astra_downloader/gui_support.py:169-177`; no `devicePixelRatio` call exists outside `scripts/render-companion-gui.py`.
  Touches: `astra_downloader/gui_support.py`
  Acceptance: the pixmap is allocated at `size * dpr` with `setDevicePixelRatio(dpr)`; a test at 2× asserts the backing pixmap dimensions; the existing HiDPI render capture is re-taken.
  Complexity: S

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

- [ ] P2 — AD-31 — Make the rate-limit and cookie-ban tradeoff visible
  Why: yt-dlp's wiki publishes the ceilings (~300 videos/hour guest, ~2000 signed-in, 5–10 s delays advised) and states plainly that using your account "runs the risk of it being banned". Parabolic's users file bugs against its hardcoded 14–30 s sleep because it is unexplained; pinchflat has an issue titled DO NOT USE YOUTUBE COOKIES. The whole field hides this dial and then fields the reports.
  Evidence: yt-dlp Extractors wiki; Parabolic#1832; pinchflat#291; RESEARCH.md "Market signal" items 4–5.
  Touches: `astra_downloader/gui_settings_page.py`, `gui_site_logins_page.py`, `download.py`, README
  Acceptance: the pacing settings display the published ceilings alongside the current configuration and what it implies per hour; storing a YouTube sign-in shows the ban-risk warning once, sourced and linked.
  Complexity: S

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

- [ ] P2 — AD-36 — Fix the Settings section taxonomy
  Why: a section headed **Language** contains *Theme* and *Language*; a section headed **Tray behavior** contains *Keep yt-dlp up to date automatically* and *Stage copied video links for review*. With 77 settings, the group name is the only navigation aid there is.
  Evidence: `build/companion-ui-smoke/settings-dirty.png`; `astra_downloader/gui_settings_page.py`.
  Touches: `astra_downloader/gui_settings_page.py`, `scripts/build-companion-translations.py`
  Acceptance: every setting sits under a heading that describes it; new headings are translated and the catalogues regenerated; the settings-search test still finds each setting by its own words.
  Complexity: S

- [ ] P2 — AD-37 — Ship a Scoop Extras manifest
  Why: Scoop imposes no signing requirement and no review judgement, and the existing onedir zip plus `.sha256` is most of a valid manifest — so it is the shortest path to an install channel that never touches the browser download path or Mark-of-the-Web. Scoop **Main** is structurally closed (its criteria require a non-GUI tool), so Extras is the target. ytDownloader (10,134★) ships Scoop, winget and Chocolatey simultaneously.
  Evidence: https://github.com/ScoopInstaller/Scoop/wiki/Criteria-for-including-apps-in-the-main-bucket; https://github.com/ScoopInstaller/Scoop/wiki/App-Manifests.
  Touches: `packaging/scoop/`, `scripts/check-versions.js`
  Acceptance: a manifest with `version`, `description`, `homepage`, `license`, `hash` and `autoupdate` validates and installs the onedir build; its version is covered by the same gate as the winget manifest. Depends on AD-01.
  Complexity: S

- [ ] P2 — AD-38 — Take the cheap Windows shell integrations
  Why: one prerequisite — a stable AppUserModelID set early in `main()` plus a Start-menu `.lnk` carrying it — unlocks jump-list Tasks ("Paste and download", "Open downloads folder"), correct taskbar grouping, and recent-items. Separately `RegisterApplicationRestart` makes a Windows Update reboot resume the queue instead of silently ending it, and `IFileOperation`/`send2trash` makes a queue delete recoverable.
  Evidence: https://learn.microsoft.com/en-us/windows/win32/shell/taskbar-extensions; RESEARCH.md "Security, Privacy, and Reliability"; taskbar progress is already implemented, so the COM plumbing exists.
  Touches: `astra_downloader/astra_downloader.py`, `gui.py`
  Acceptance: the jump list shows context-free tasks that work when the app is closed; a simulated restart relaunches with `--start-server`; deleting a finished file from the queue sends it to the Recycle Bin. Toasts with action buttons stay out of scope — they need package identity.
  Complexity: M

- [ ] P2 — AD-39 — Sync the docs to what the repository actually is
  Why: README claims 914 tests (actual 964) and describes `npm run check` as four gates (it is seven with a per-gate summary); `Roadmap_Blocked.md` claims the History column headers are untranslated, which is now stale — they are extracted and translated, and the residual risk is the fixed width (AD-35). `SECURITY.md` cites two yt-dlp CVEs and three more landed 2026-06-09.
  Evidence: measured suite output; `npm run check` summary; German catalogue contains `Duration → Dauer`; GHSA-6v4j-43gg-vj32 / GHSA-c6mh-fpjc-4pr3 / GHSA-f7j3-774f-rfhj.
  Touches: README.md, SECURITY.md, Roadmap_Blocked.md, CLAUDE.md
  Acceptance: every count and gate list in the docs matches a command that can be run; the stale translation claim is corrected in place with its date.
  Complexity: S

- [ ] P2 — AD-40 — Detect archived items the source has since deleted
  Why: an archive whose upstream entry disappears silently rots. Tartube's "Missing Videos" folder is the only implementation in the field, and pinchflat#805 (11 reactions) asks for the inverse guarantee — do not re-download what the user deleted locally. Both need the same reconciliation between the archive and the last scan.
  Evidence: Tartube README §6.25; pinchflat#805; `astra_downloader/subscriptions.py` archive keys.
  Touches: `astra_downloader/subscriptions.py`, `gui_subscriptions_page.py`, `gui_history_page.py`
  Acceptance: a scan that no longer sees a previously-archived item marks it, without deleting anything; a locally-deleted file is not silently re-fetched; both states are visible and reversible. Depends on AD-25.
  Complexity: M

- [ ] P2 — AD-41 — Shorten every path segment, not just the filename
  Why: the Windows limit is 255 *bytes* per component, and a 4-byte emoji title blows it three times faster than the character count suggests. ytdl-sub applies shortening to every folder segment and exempts only the configured output root; yt-dlp#1136 (32 reactions) names temporary files as the sneaky half of the problem.
  Evidence: ytdl-sub release 2026.06.23; yt-dlp#1136; `astra_downloader/config.py:822-865` (the existing Windows-safe name preview).
  Touches: `astra_downloader/config.py`, `download.py`
  Acceptance: channel/playlist folder names and staging paths are shortened by byte length, not character count; the existing preview reports the shortened result; a test uses a 4-byte-per-character title.
  Complexity: M

- [ ] P2 — AD-42 — Deprioritise YouTube's AI "Super Resolution" formats
  Why: YouTube began serving AI-upscaled renditions that sort above the genuine source by resolution; yt-dlp#15433 (13 reactions, opened 2025-12-29) is open and no GUI exposes a control. An archivist wants the original, and the existing `--format-sort` builder already knows to emit `res` first.
  Evidence: yt-dlp#15433; `astra_downloader/download.py` `build_video_format_args` and the `--format-sort` ordering rule recorded in CLAUDE.md.
  Touches: `astra_downloader/download.py`, `gui_settings_page.py`
  Acceptance: a setting deprioritises upscaled renditions; verified against a `--load-info-json` fixture carrying both a native and an upscaled format. *Needs live validation of the field yt-dlp exposes for the marker on the pinned 2026.7.4.*
  Complexity: S

- [ ] P2 — AD-43 — Split `create_api` by resource
  Why: it is a single 1,262-line function holding 27 routes and 54 unpacked dependencies in one closure, and it is one of the three remaining `inspect.getsource` targets (AD-34) precisely because there is no smaller unit to assert against.
  Evidence: `astra_downloader/routes.py:196`; `test_astra_downloader.py:20004`.
  Touches: `astra_downloader/routes.py`
  Acceptance: routes are grouped into per-resource registrars (downloads / queue / subscriptions / site-logins / system) taking the same dependency mapping; the `_REQUIRED_*_DEPENDENCIES` contract is unchanged; all route tests pass untouched.
  Complexity: M

### P3

- [ ] P3 — AD-44 — Reap the process after a `communicate` timeout
  Why: three timeout handlers call `terminate_process_tree(proc)` and return without a second `communicate()`/`wait()`. In practice the tree-kill closes the pipes so the reader threads exit, but the `Popen` is never waited on and the handle survives until GC.
  Evidence: `astra_downloader/download.py:6330-6339`, `:6485-6493`, `:6625-6633`.
  Touches: `astra_downloader/download.py`
  Acceptance: each handler waits on the child after terminating it, with its own bounded timeout.
  Complexity: S

- [ ] P3 — AD-45 — Take log writes off the Qt main thread
  Why: `_append_log` runs on the main thread and calls `write_persistent_log`, which does `mkdir` + `stat` + `open(..., 'a')` + write per call while holding the process-global `_LOG_LOCK` that every worker thread also contends for. The GUI log widget and the in-memory ring are already correctly bounded; the synchronous I/O is the only issue.
  Evidence: `astra_downloader/gui.py:6343`; `astra_downloader.py:849-875`.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`
  Acceptance: log writes are queued to a writer thread; ordering and the crash-log path are preserved; a test asserts the main thread does no file I/O on the log path.
  Complexity: S

- [ ] P3 — AD-46 — Also persist the queue outside the manager lock
  Why: `_persist_locked` runs `atomic_write_json` → `os.fsync` under `DownloadManagerCore._lock` from ~15 call sites, and the Qt main thread takes that same lock every 500 ms via `update_timer` → `_update_ui`. On a slow or BitLocker-throttled disk this is a visible stall that nothing measures. Same shape as AD-11, lower frequency.
  Evidence: `astra_downloader/download.py:3706-3715`, called from `:3696, :3902, :4402, :5649`; `gui.py:1166-1168`, `:4148`.
  Touches: `astra_downloader/download.py`
  Acceptance: the serialize+fsync happens outside the lock (snapshot under the lock, write after); a test asserts the lock is not held across the write.
  Complexity: M
