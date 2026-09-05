# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

- [ ] P0 | AD-113 | An existing Scoop install loses everything on the first update to the data layout
  Why: AD-102 changed the persist array to a single data directory. scoop update extracts the new version and links only what the new manifest names, so config.json, history.json, download-queue.json, subscriptions.json and site-logins are not linked into the new app directory, portable_state_dir finds no legacy marker at the root and returns the empty data junction, and the real files are stranded in the old version directory the app never looks at. site-logins used to be the one entry that survived, because it was a junctioned directory, so for stored sign-ins this is a strict regression rather than a wash. The legacy-marker fallback only rescues a hand-unzipped folder, where the files are physically still beside the executable; it cannot rescue a Scoop install, which is the only population the change exists for.
  Evidence: packaging/scoop/astra-downloader.json persist; astra_downloader/astra_downloader.py portable_state_dir and _LEGACY_PORTABLE_STATE_MARKERS; the AD-102 measurement recording that site-logins survived under the previous list.
  Touches: astra_downloader/astra_downloader.py, packaging/scoop/astra-downloader.json, tests/scoop-manifest.test.js, astra_downloader/test_build.py.
  Acceptance: A first launch that finds legacy state beside the executable and an empty data directory moves that state into data once, and reports what it moved. The move is atomic per file and leaves the original in place if any part fails, so an interrupted migration never loses a queue or a sign-in. A launch with no legacy state, a launch already migrated, and a launch with both present are each covered by a test.
  Complexity: M

### P1

### P2



- [ ] P2 | AD-122 | The Settings proxy hint prints a detected proxy verbatim
  Why: the resolved-address preview renders the value parse_wininet_proxy_server returned, and normalize_proxy preserves userinfo, so a WinINET ProxyServer entry carrying credentials is shown in full on the Settings page. Not persisted and visible only to the user who configured it, which is why it is here rather than above, but it contradicts the rule AD-101 established that a proxy is named by scheme, host and port only.
  Evidence: astra_downloader/gui.py the Windows-reports proxy hint; astra_downloader/config.py normalize_proxy preserving userinfo; astra_downloader/config.py redact_proxy_url.
  Touches: astra_downloader/gui.py, astra_downloader/test_gui.py.
  Acceptance: Every place that shows a proxy to a user routes through redact_proxy_url. A test scans the GUI for a proxy value rendered without it.
  Complexity: S

- [ ] P2 | AD-123 | The extension shows a green yt-dlp pill on a below-floor build
  Why: Astra Deck's health normalizer whitelists thirteen keys and preflight is not among them, and its yt-dlp pill is rendered unconditionally ok while the ffmpeg and JavaScript-runtime pills tone on state. A user driving downloads from the extension on a yt-dlp below the security floor sees no signal at all, so the AD-108 clause about reporting it whatever the auto-update setting holds only for the desktop window.
  Evidence: the health normalizer key whitelist and the unconditional yt-dlp pill in the Astra-Deck repository download-ui feature; astra_downloader/health.py emitting securityFloor and belowSecurityFloor on the ytdlp-freshness check.
  Touches: the Astra-Deck repository, and astra_downloader/routes.py only if the health payload needs a narrower field for it.
  Acceptance: The extension tones its yt-dlp pill from the same check the desktop preflight uses and names the floor when the installed build is below it. Requires a change in the Astra-Deck repository, so it ships there and is verified against a running Astra Downloader reporting a below-floor version.
  Complexity: M

- [ ] P2 | AD-124 | preflight blocking is not a usable signal
  Why: ffmpeg-capabilities lands in blocking on ordinary working installs, so preflight status reads blocked for many users and nothing consumes it. Confirmed 2026-09-05: with a below-floor yt-dlp the health route reported status blocked and blocking naming both ytdlp-freshness and ffmpeg-capabilities, while POST /download accepted the request and start_download ran. That is the correct behaviour today, since a security floor should not silently stop a queue, but it means anything that later starts honouring blocking would refuse work on healthy installs.
  Evidence: astra_downloader/health.py assembling blocking and the blocked summary; astra_downloader/routes.py never calling evaluate_preflight_checks outside the health closure; the /health and POST /download responses captured on 2026-09-05.
  Touches: astra_downloader/health.py, astra_downloader/test_health.py.
  Acceptance: Either ffmpeg-capabilities stops reporting error on an install that can actually download, or blocking is renamed and documented as advisory so no future consumer reads it as a gate. Whichever is chosen, a test pins the meaning.
  Complexity: M


- [ ] P2 — AD-62 — A rejected link's reason is translated around, not translated
  Why: `describe_rejected_links` wraps `{reason}` in a translated frame, but the reason itself comes from the URL policy untranslated. A German build shows a German sentence containing an English clause.
  Where: `astra_downloader/gui_support.py` `describe_rejected_links`; the reasons originate in `astra_downloader/config.py` `normalize_url` and its callers.

- [ ] P2 — AD-63 — Tray notifications raise no accessibility event
  Why: every status label in the app announces itself through `StatusLabel.setText` / `announce_status`. The five `QSystemTrayIcon.showMessage` balloons bypass that path entirely, so a completion or a failure that fires while the window is minimised is announced to nobody. That is exactly when the balloon is the only report.
  Where: `astra_downloader/gui.py`, the five `showMessage` call sites; `astra_downloader/gui_support.py` `announce_status`.

- [ ] P2 — AD-64 — `_arm_host_backoff_wakeup` decides on liveness it does not hold
  Why: the timer is created under the lock and started outside it, so `current.is_alive()` is False for a timer another thread has installed but not yet started. Two threads can each install and start one; the loser is unreachable by `cancel_all` and fires anyway. The observed cost is a redundant daemon timer rather than a missed wakeup, which is why it is here and not above, but the check-then-act is real.
  Where: `astra_downloader/download.py` `_arm_host_backoff_wakeup`.

- [ ] P2 — AD-65 — `_persist_stop` is set by nothing
  Why: the queue writer thread has a stop event that is never signalled anywhere in the tree. Retirement relies entirely on the two-second idle timeout, and `cancel_all` does not stop the writer. Either wire the event into shutdown or delete it; as written it reads like a shutdown path that exists.
  Where: `astra_downloader/download.py` (`_persist_stop`, and the writer loop that reads it).

- [ ] P2 | AD-77 | Turn the format probe into a truthful pre-download summary
  Why: The probe already returns title, duration, formats, and approximate sizes, but the GUI shows only maximum height and deliberately hides every lookup error.
  Evidence: astra_downloader/download.py summarize_ytdlp_formats; astra_downloader/gui.py _apply_format_probe; Parabolic 2026.4 preview work; ytDownloader issue 406.
  Touches: astra_downloader/download.py, astra_downloader/gui.py, astra_downloader/gui_download_page.py, astra_downloader/test_gui.py, translation catalogues.
  Acceptance: A successful single-link probe shows sanitized title, duration, maximum resolution, and an approximate size for the selected output when known. A failed probe leaves Add to queue available but shows a bounded warning with the relevant health or sign-in next step. Editing the URL, entering a batch, or receiving a stale generation clears the summary. The card wraps at 900x620, has an accessible name, and passes German and RTL fixtures.
  Complexity: M

- [ ] P2 | AD-78 | Add deterministic subscription filters with a dry-run preview
  Why: MeTube and Pinchflat let archive users exclude unwanted source items before queue or seen-state mutation, while Astra can only accept every normalized candidate.
  Evidence: MeTube Subscriptions documentation; Pinchflat FAQ; astra_downloader/subscriptions.py normalize_subscription_candidate, sanitize_subscription_delivery, and scan_subscription.
  Touches: astra_downloader/subscriptions.py, astra_downloader/routes.py, astra_downloader/gui_subscriptions_page.py, astra_downloader/gui.py, astra_downloader/test_subscriptions.py, astra_downloader/test_routes.py.
  Acceptance: Subscription schema 3 supports includeTitleRegex, excludeTitleRegex, and uploadedAfter. One pure evaluator returns matched or skipped plus a reason and runs before archive reservation. A Preview scan shows both groups without changing queue, reservations, nextScanAt, or archive state. Invalid regexes are rejected on save, and the same fixture produces identical decisions in preview, manual scan, and scheduler scan.
  Complexity: M

- [ ] P2 | AD-79 | Honor Windows contrast themes at runtime
  Why: Astra's authored QSS follows light or dark only and can override the system colors that Windows contrast themes and Qt 6.10+ provide.
  Evidence: astra_downloader/astra_downloader.py apply_application_theme; QAccessibilityHints contrastPreference; Microsoft Windows contrast-theme guidance; existing AD-63 and AD-67 accessibility work.
  Touches: astra_downloader/astra_downloader.py, astra_downloader/gui.py, astra_downloader/gui_support.py, scripts/render-companion-gui.py, astra_downloader/test_gui.py.
  Acceptance: Starting in or switching to a Windows contrast theme changes Astra without restart through QAccessibilityHints. The contrast path uses native system colors or a dedicated token set that the normal QSS does not override. Major pages, dialogs, focus, selection, disabled controls, and status tones remain distinguishable in an isolated Windows accessibility run and a deterministic test fixture.
  Complexity: M

- [ ] P2 | AD-80 | Declare a reproducible Python test toolchain
  Why: pytest.ini requires xdist and configures pytest-qt and pytest-asyncio, but the repository declares only runtime dependencies and the README gives no clean-environment install command.
  Evidence: pytest.ini, README.md Tests and gates, astra_downloader/requirements.txt, Python Packaging Dependency Groups specification.
  Touches: pyproject.toml, pytest.ini, README.md, scripts/run-checks.js, dependency-audit tests.
  Acceptance: A PEP 735 test group declares compatible versions of pytest, pytest-xdist, pytest-qt, and pytest-asyncio. In a new CPython 3.13 virtual environment, the documented install command collects the full suite without plugin errors, runs every test, and npm run check passes. A gate fails if pytest.ini references an undeclared plugin, and README.md refreshes its count from collect-only.
  Complexity: S

- [ ] P2 | AD-81 | Mark missing History files without deleting their records
  Why: Ordinary History always offers Show for any stored filename, while the subscription archive already distinguishes deletion from an unavailable drive.
  Evidence: astra_downloader/gui.py _refresh_history and _open_subscription_archive; Downie Preferences history-cleanup behavior.
  Touches: astra_downloader/gui.py, astra_downloader/config.py history projections, astra_downloader/test_gui.py.
  Acceptance: Only the visible History page is checked off the GUI thread. FileNotFoundError marks a row Missing and disables or relabels Show; other OSError results show Unavailable and do not claim deletion. The stored row, search, and export remain intact, and a later refresh restores Show when the file returns.
  Complexity: M

- [ ] P2 | AD-83 | Add explicit audio-language selection
  Why: Active Seal, Parabolic, and YTDLnis reports show that automatic format ranking can select the wrong dub or ignore a requested audio track, while Astra only applies a soft generic lang sort.
  Evidence: yt-dlp format-selection documentation; Seal issue 2592; Parabolic issues 1901 and 1938; YTDLnis issue 946; astra_downloader/download.py build_format_sort_args.
  Touches: astra_downloader/download.py, astra_downloader/routes.py, astra_downloader/gui_download_page.py, astra_downloader/gui.py, astra_downloader/subscriptions.py, queue and settings schemas, tests.
  Acceptance: Format discovery returns bounded available audio-language codes and an original-language marker. Quick downloads offer Automatic, Original, and discovered languages; the strict API, profiles, subscriptions, queue persistence, and settings bundles carry the same field. An explicit choice compiles to a tested yt-dlp selection rule, a missing choice falls back with a visible explanation, and History records the requested language plus the resolved language when yt-dlp reports it.
  Complexity: L

- [ ] P2 | AD-92 | Give a site profile a destination folder and a concurrency cap
  Why: validate_site_profiles accepts sixteen fields covering format, quality, impersonation, proxy, rate limits, network identity and pacing, and none of them answers "put this site's files here" or "one at a time for this site, four for everything else". Subscriptions already carry per-item folders, so the storage precedent exists; ordinary and API downloads have only the single global root and the single global concurrency number.
  Evidence: astra_downloader/config.py:672 validate_site_profiles and the field lists at :718-753; astra_downloader/download.py _max_concurrent and _effective_config_for_url; YTPTube documents presets carrying paths and global plus per-extractor concurrency limits (https://github.com/arabcoders/ytptube).
  Touches: astra_downloader/config.py, astra_downloader/download.py, astra_downloader/gui_settings_page.py, astra_downloader/gui.py, astra_downloader/routes.py, astra_downloader/test_config.py, astra_downloader/test_download.py, translation catalogues.
  Acceptance: A profile can carry DownloadFolder and MaxConcurrent. The folder is validated by the same preflight the global root uses (existence, writability, free space, Windows path length) and is rejected on save when it fails, per Open question 2 in RESEARCH.md on whether it may sit outside the download root. The scheduler counts running downloads per matched profile and does not start one past its cap while still filling the remaining global slots with other sites. Quick downloads, the strict API and subscriptions all honour both fields, and the settings bundle carries them.
  Complexity: M

- [ ] P2 | AD-93 | Widen the output-template allowlist and admit yt-dlp's fallback syntax
  Why: _SAFE_OUTPUT_FIELDS holds 26 fields with no artist, album, track, release_year, series, episode or extractor, so an extracted-audio library cannot be named the way a music library is named. The charset rule also excludes "|", so yt-dlp's `%(field|fallback)s` is unavailable and a template using %(playlist_index)s on a single video renders the literal NA into the filename.
  Evidence: astra_downloader/config.py:874 _SAFE_OUTPUT_FIELDS, :953 normalize_output_template and its charset regex; Parabolic issue 767 (advanced file naming) is among that project's most-reacted open requests.
  Touches: astra_downloader/config.py, astra_downloader/gui_settings_page.py output-path preview, astra_downloader/test_config.py, translation catalogues.
  Acceptance: The allowlist gains the music and series fields plus extractor, each classified as long-text or short so the existing _OUTPUT_TEXT_BUDGET still bounds the rendered path. The template grammar accepts one fallback per token and the printf-residue check still rejects an unclosed token, a stray percent, a path separator escape, an absolute path and traversal. The Settings preview renders a fallback correctly for both a present and an absent field, and a template that previously produced NA produces the fallback instead. A yt-dlp smoke run proves the accepted grammar is the grammar yt-dlp parses.
  Complexity: M

- [ ] P2 | AD-94 | Name the transcription model and let its size be chosen
  Why: Local subtitle generation is pinned to ggml-tiny-q5_1, the least accurate build whisper.cpp ships, and no string in the interface says so. The eleven English transcription strings say only "the bundled multilingual Whisper model", so a user who enables the option and gets poor captions cannot tell whether the feature is broken or the model is small, and cannot trade disk for accuracy.
  Evidence: astra_downloader/astra_downloader.py:519 WHISPER_MODEL_NAME = 'ggml-tiny-q5_1.bin' with its pinned revision and SHA-256 at :529-535; the transcription strings in astra_downloader/translations/astra_downloader_en.ts; MANAGED_BINARY_PIN_NAMES already carries a whisper entry.
  Touches: astra_downloader/astra_downloader.py, astra_downloader/config.py, astra_downloader/health.py, astra_downloader/gui_settings_page.py, astra_downloader/download.py, astra_downloader/test_health.py, translation catalogues.
  Acceptance: The Settings row and the readiness row name the model and its on-disk size. A model choice covering at least tiny and one larger quantized build is offered, each pinned by repository revision, filename and SHA-256 the same way the current one is, with the download deferred until the choice is saved and setup is run. Switching models verifies the new file before the old one is removed, a failed fetch leaves the previous model usable, and the readiness probe reports which model is present rather than a bare ready.
  Complexity: M

- [ ] P2 | AD-125 | The progress-coalescing test is timing-flaky under xdist
  Why: test_a_burst_of_progress_signals_causes_one_refresh intermittently fails in a parallel run and passes every time in isolation. Observed 2026-09-05 failing twice in `npm run check` runs, once with 1.14 GB free and once with 5.8 GB free, and passing twice in a row in isolation each time, so it is a Qt timer raced against an assertion rather than memory pressure. Same shape as AD-112, which covers the instance-control listener. A test that fails on load is a test nobody trusts, and this one has now cost two investigations.
  Evidence: astra_downloader/test_download.py UiRefreshCoalescingTests; astra_downloader/gui.py _request_ui_refresh and the coalescing QTimer it starts.
  Touches: astra_downloader/test_download.py, astra_downloader/gui.py if the coalescer needs a deterministic hook.
  Acceptance: The test drives the coalescing timer deterministically rather than waiting on elapsed time, so a busy machine cannot change the outcome. Running the class 20 times in a row under `-n auto` passes 20 times, and the assertion still fails when the coalescing is removed from _request_ui_refresh.
  Complexity: S

### P3

- [ ] P3 | AD-95 | Report terminal download events to a configured webhook
  Why: Completion and failure are reported only through tray balloons and the window, so a subscription archive left running overnight on a machine nobody is watching reports nothing anywhere durable. Astra already runs an HTTP stack and already builds redacted download descriptions, so the outbound half is small. This is the unattended-archivist counterpart to AD-76, which covers the interactive case.
  Evidence: astra_downloader/gui.py _notify_completed_downloads and the five QSystemTrayIcon.showMessage sites; astra_downloader/download.py _record_terminal_download and format_redacted_command_args; YTPTube ships Apprise and direct HTTP webhook notifications (https://github.com/arabcoders/ytptube).
  Touches: astra_downloader/config.py, astra_downloader/download.py, astra_downloader/gui_settings_page.py, astra_downloader/test_download.py, translation catalogues.
  Acceptance: One optional webhook URL is stored, validated by the same URL policy that governs download targets so it cannot address loopback or private ranges, and is never written to the log, diagnostics or the settings bundle if it carries credentials. Completion, failure and subscription-archive events POST a bounded JSON body carrying the same redacted fields History already exposes, never a cookie, credential, token or raw command line. Delivery is off the download thread, is attempted a bounded number of times, and a failing endpoint never delays or fails the download itself. The feature is off by default.
  Complexity: M

- [ ] P3 | AD-96 | Re-check whether a native resolver is still needed
  Why: is_native_source_url short-circuits yt-dlp entirely for Kick VODs with no fallback, which is deliberate, but nothing notices when the reason expires. check-site-registry.py re-derives extractor arguments from the installed yt-dlp; there is no equivalent for the resolvers, so if Kick restores its v1 endpoint or yt-dlp fixes kick:vod, Astra keeps using its own path indefinitely. The hardcoded Chrome/136 user agent in the same module has the same shape of problem: a frozen fingerprint in a module whose whole premise is imitating the site's own player.
  Evidence: astra_downloader/native_sources.py module docstring citing yt-dlp issue 17284, NATIVE_SOURCE_USER_AGENT at :43, is_native_source_url at :100 and resolve_native_source at :233; scripts/check-site-registry.py as the precedent for re-deriving a claim from the installed yt-dlp.
  Touches: scripts/check-site-registry.py or a new gate script, scripts/run-checks.js, astra_downloader/native_sources.py, astra_downloader/test_native_sources.py.
  Acceptance: Each resolver declares the upstream reason it exists, as an extractor name plus the issue it answers. A gate reports when the installed yt-dlp's extractor for that site changes shape from the recorded state, so the claim is re-examined rather than assumed. The user agent is derived from the same source the impersonation targets come from, or is a named constant with a recorded review date that the gate flags once it is a year old.
  Complexity: S

- [ ] P3 — AD-66 — `read_settings_bundle` and `ConfigStore` disagree about a boolean schema version
  Why: `read_settings_bundle` accepts `"schemaVersion": true` because `int(True) == 1`, while `ConfigStore._load_and_sanitize` rejects a bool for the same field on purpose. One of the two is wrong about what a version marker is.
  Where: `astra_downloader/config.py`, `read_settings_bundle` and `_load_and_sanitize`.

- [ ] P3 — AD-67 — Two interactive surfaces have no focus or selection styling
  Why: `QScrollArea` is keyboard-scrollable with `border: none` and no `:focus` rule, so a keyboard user scrolling a long list has no indication of where they are. `QComboBox QAbstractItemView` sets `selection-background-color` but the popup has no `::item` rule, so the keyboard highlight inside an open combo falls back to the platform default over a custom background. Neither is measured by the focus-ring test added this pass, because neither declares a ring to measure.
  Where: `astra_downloader/astra_downloader.py`, the `QScrollArea` and `QComboBox QAbstractItemView` rules.

- [ ] P3 — AD-68 — Three sibling spin boxes spell their units three ways
  Why: `' entries'`, `' seconds'`, `' s'`, `' MB'`, `' min'`. Two of them sit on the same Settings page. Pick one convention: spelled out, or abbreviated, not both.
  Where: `astra_downloader/gui_settings_page.py` (`setSuffix` at the retention, timeout and size fields), `astra_downloader/gui_subscriptions_page.py`.

- [ ] P3 — AD-69 — The playlist dialog calls the same thing a video and an item
  Why: "Select every video in this playlist preview" sits beside "Select playlist item {index}", and the confirm button says "Download selected" while the resulting toast says "Queued {count} items from playlist." The subscription archive has the mirror problem: "Captured subscription items" beside "The source no longer lists this video."
  Where: `astra_downloader/gui.py`, the `PlaylistStagingDialog` and `SubscriptionArchiveDialog` strings.

- [ ] P3 — AD-70 — The empty-state ETA is punctuation where every other empty state is a word
  Why: an unknown ETA renders as `--`. Everywhere else the app writes "Not set", "unknown", "Off", "No limit".
  Where: `astra_downloader/gui.py`, the download-card ETA field.

- [ ] P3 — AD-71 — Areas the 2026-08-22 audit did not reach
  Why: recorded so the next pass starts where this one stopped rather than re-covering it. Not audited: the PyInstaller build pipeline beyond running it; the native messaging host registration; the Windows shell integration (jump list, `RegisterApplicationRestart`, Recycle Bin delete) beyond reading it, since driving it needs a real desktop session; the whisper transcription path; the SponsorBlock and NFO writers; and the browser extension, which is a separate repository. The GUI was exercised offscreen through `npm run smoke:gui` and the Qt test suite, never driven interactively, so nothing here rests on watching a real window.
  Where: `astra_downloader/build.py`, the native-host block in `astra_downloader/astra_downloader.py`, the taskbar and jump-list block in `astra_downloader/gui.py`, the transcription block in `astra_downloader/download.py`.

- [ ] P3 | AD-84 | Add durable one-time queue scheduling
  Why: IDM, FDM, SnapDownloader, and Downie all expose one-time scheduling, while Astra schedules subscriptions and live retries but cannot defer an ordinary queued job across a restart.
  Evidence: IDM Scheduler documentation; FDM and SnapDownloader feature pages; Downie release notes; astra_downloader/download.py durable queue and host-backoff timer. AD-64 must land first.
  Touches: astra_downloader/download.py, astra_downloader/routes.py, astra_downloader/gui.py, astra_downloader/gui_download_page.py, queue schema and migration tests.
  Acceptance: A queue item can carry notBeforeUtc from the GUI or strict API. Future items display Scheduled and do not block later runnable work. One cancellable wake timer reevaluates wall-clock time, overdue work starts after restart or resume, pause and cancel remain authoritative, and the UI states that Astra does not wake a sleeping PC.
  Complexity: M

- [ ] P3 | AD-85 | Sign update metadata independently of release hosting
  Why: The updater obtains the EXE and SHA-256 sidecar from one GitHub release, so a compromised release account can replace both and can also serve rollback or frozen metadata.
  Evidence: astra_downloader/astra_downloader.py update flow; SECURITY.md; JDownloader's 2026-05-06 and 2026-05-07 installer incident; TUF specification and security paper.
  Touches: astra_downloader/astra_downloader.py, astra_downloader/config.py updater state, scripts/write-release-provenance.js, release documentation, Python dependencies, update tests.
  Acceptance: The application bundles a trusted TUF root and accepts targets only through signed, versioned, expiring targets, snapshot, and timestamp metadata with expected lengths and hashes. Trusted metadata persists across runs to reject rollback, freeze, and mix-and-match attacks. Tests cover expired metadata, older versions, swapped EXE and sidecar, interrupted updates, root rotation, and recovery. Documentation states that this protects installed updates but not the first installer or SmartScreen reputation.
  Complexity: XL

- [ ] P3 | AD-97 | The README count check calls a missing interpreter a hard failure
  Why: documentation-facts.test.js skips its pytest collect-count check only when spawn returns ENOENT. On Windows without CPython on PATH the `python` App Execution Alias still spawns, exits 9009 and prints the Microsoft Store notice, so `result.error` is null, `collected` stays null and the test asserts its way to a failure that says "pytest ran but reported no collected count". Observed 2026-09-04 while verifying the AD-87 SKIP path with the Python entries stripped from PATH.
  Evidence: tests/documentation-facts.test.js pythonCandidates and the ENOENT branch; the `node tests (exit 1)` line in the PATH-scrubbed `node scripts/run-checks.js` run of 2026-09-04, beside the three gates that correctly reported SKIP.
  Touches: tests/documentation-facts.test.js.
  Acceptance: A candidate interpreter that exits non-zero without producing a collected count and whose output carries the Store-alias notice is treated the same as ENOENT: the loop moves to the next candidate, and exhausting them logs the skip rather than asserting. A candidate that runs pytest and genuinely fails collection still fails the test, pinned by a fixture for each of the two cases.
  Complexity: S

- [ ] P2 | AD-98 | DenoProvisionTests point DENO_PATH at a real filesystem root
  Why: three tests set `ad.DENO_PATH = Path('/nonexistent/deno.exe')`, which on Windows resolves to `C:\nonexistent\deno.exe`. That is a writable location outside any tmpdir, so the moment a network patch misses, provision_deno performs a real download into it. Observed 2026-09-04 during AD-88: repointing the HTTP seam left one fixture patching the old name for a single run and a 97 MB Deno binary landed at `C:\nonexistent\deno.exe`, after which `test_provision_deno_returns_none_on_network_failure` and `test_probe_includes_source_field` failed on every later run because `DENO_PATH.exists()` was then true. The path was removed by hand.
  Evidence: astra_downloader/test_health.py DenoProvisionTests, the three `Path('/nonexistent/deno.exe')` assignments; astra_downloader/astra_downloader.py provision_deno, whose first branch returns early when DENO_PATH exists.
  Touches: astra_downloader/test_health.py, astra_downloader/conftest.py.
  Acceptance: No test assigns a managed-binary path outside a TemporaryDirectory it owns. A test that means "this binary is absent" points at a path inside its own tmpdir, so a missed patch writes there and is discarded with the fixture. conftest already redirects INSTALL_DIR and its derived paths; the same redirection covers DENO_PATH, QUICKJS_DIR, WHISPER_BIN_PATH and WHISPER_MODEL_PATH, and a test asserts that none of the managed paths resolve outside the redirected root during a run.
  Complexity: S

- [ ] P3 | AD-99 | npm run check collects the Python suite twice
  Why: tests/documentation-facts.test.js spawns `pytest --collect-only -q` to read the count the README states, and that runs inside the `node tests` gate while the `python suite` gate then runs the full suite, which collects again. Measured at roughly 8 s of the command's runtime on 2026-09-04. Cost, not correctness.
  Evidence: tests/documentation-facts.test.js:22-61; scripts/run-checks.js GATES.
  Touches: tests/documentation-facts.test.js, scripts/run-checks.js.
  Acceptance: The count the README states is verified once per `npm run check`. Either the python-suite gate emits the collected count for the documentation test to read, or the documentation test reads a count the suite gate wrote, and neither path lets the README go stale without a gate failing. Running `node --test tests/documentation-facts.test.js` on its own still verifies the count.
  Complexity: S

- [ ] P3 | AD-100 | The pytest gate assertion cannot tell a narrowed run from a full one
  Why: documentation-facts.test.js asserts exactly one gate's args contain `pytest` and not `--collect-only`. A gate narrowed with `-k`, `--ignore` or `--deselect` satisfies every assertion while running almost nothing, which is the same class of green-but-empty gate the Python-suite gate was added to close.
  Evidence: tests/documentation-facts.test.js, the pytest-gate test; conftest.py MIN_FULL_SUITE_EXECUTED_TESTS, which already solves this problem for a direct pytest run and is not consulted by the gate assertion.
  Touches: tests/documentation-facts.test.js.
  Acceptance: The assertion rejects a python-suite gate carrying any selection-narrowing flag (-k, -m, --ignore, --deselect, --lf, --ff, -x), naming the flag it found. A test plants each flag and confirms the assertion fails, so the check cannot pass by finding nothing.
  Complexity: S

- [ ] P3 | AD-111 | Site registry notes never reach the translation catalogues
  Why: the Sites page renders auth_note and notes through make_label, which calls tr, and a failure now renders the failure note the same way, but scripts/extract_companion_strings.py does not scan astra_downloader/sites.py. Every note is therefore a tr call whose string is in no catalogue, so it renders English in all eleven locales while the text around it is translated. Pre-existing rather than introduced by AD-105, which only made a second surface show one.
  Evidence: scripts/extract_companion_strings.py SOURCE_FILES, which lists the gui modules plus download.py and health.py but not sites.py; astra_downloader/gui_sites_page.py rendering auth_note and notes through make_label; astra_downloader/gui.py _download_recovery_text rendering the failure note through tr.
  Touches: scripts/extract_companion_strings.py, scripts/build-companion-translations.py, astra_downloader/sites.py, translation catalogues.
  Acceptance: The extractor reaches the auth_note and notes literals in the site registry, by whichever shape suits its existing runtime-literal handling, and the translation gate counts them. German carries all of them. A note added to a profile without a German entry fails the gate rather than silently rendering English.
  Complexity: M

- [ ] P2 | AD-112 | The instance-control listener test is timing-flaky
  Why: test_instance_control_listener_rejects_an_untokened_command intermittently sees the untokened `show` command arrive, failing with the received list carrying an extra 'show'. Observed 2026-09-05 failing twice in full-suite runs, once in a class-scoped run, then passing three times in a row on the same tree, and passing on a clean tree in between. It is a socket handshake raced against an assertion, not a policy defect: the token check itself is covered by the sibling assertions that pass every time. A test that fails on load is a test nobody trusts, and this one has already cost two investigations.
  Evidence: astra_downloader/test_routes.py InstanceCommandTests, the received-commands assertion; the listener under test in astra_downloader/astra_downloader.py instance control.
  Touches: astra_downloader/test_routes.py, astra_downloader/astra_downloader.py instance control listener if it needs a readiness signal.
  Acceptance: The test waits on a deterministic signal that the listener has processed the untokened command rather than on elapsed time, so a slow machine cannot change the outcome. Running the class 20 times in a row passes 20 times, and the assertion still fails when the token check is removed from the listener.
  Complexity: S
