# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

- [ ] P1 | AD-89 | Stop the Scoop package from discarding user state on update
  Why: packaging/scoop/astra-downloader.json sets "persist": [] and installs the one-folder zip, which carries .astradownloader-portable, so runtime_state_dir() puts config.json, history.json, download-queue.json, subscriptions.json, site-logins/, server.log and the managed yt-dlp/ffmpeg/deno/quickjs/whisper trees inside scoop\apps\astra-downloader\<version>\. Scoop links only persist entries out of the versioned directory, so an update starts from an empty state root, loses stored sign-ins and re-provisions the whole managed binary set. The manifest is also in no bucket and README.md never mentions Scoop, so today it reaches nobody.
  Evidence: packaging/scoop/astra-downloader.json; astra_downloader/astra_downloader.py:372 PORTABLE_MARKER_NAME, runtime_state_dir, and the INSTALL_DIR paths at :511-593; astra_downloader/build.py:233 writing the marker into the zip; https://github.com/ScoopInstaller/Scoop/wiki/Persistent-data. Open question 1 in RESEARCH.md decides between persisting the portable layout and switching Scoop to the managed install.
  Touches: packaging/scoop/astra-downloader.json, README.md, scripts/check-versions.js or a new manifest gate, tests/documentation-facts.test.js.
  Acceptance: Whichever layout is chosen, an install followed by a version bump followed by scoop update and scoop cleanup leaves settings, history, queue, subscriptions and stored sign-ins readable, and does not re-download the managed binaries. A gate fails when a state path named in astra_downloader.py has no counterpart in the manifest's persist list under the portable layout. README.md documents the Scoop install command actually supported.
  Complexity: M

- [ ] P1 | AD-76 | Notify hidden users when a download fails
  Why: _notify_completed_downloads handles complete and skipped jobs only, so an overnight failure is silent until the user reopens the window.
  Evidence: astra_downloader/gui.py _notify_completed_downloads; durable failure recording in astra_downloader/download.py _record_history; the YT-DLP Studio README advertises both finish and failure alerts. AD-63 remains the accessibility half of this work.
  Touches: astra_downloader/config.py, astra_downloader/gui.py, astra_downloader/gui_settings_page.py, astra_downloader/gui_support.py, astra_downloader/test_gui.py, translation catalogues.
  Acceptance: A separate NotifyOnFailure setting defaults on and migrates independently from NotifyOnComplete. A terminal failed job produces one warning notification when the window is hidden or minimized, never when the failed card is visible. Its text names the bounded failure reason, activation restores the window and focuses that card, a retry can create a new terminal notification, and the event also uses the accessible announcement path from AD-63.
  Complexity: M

### P2

- [ ] P2 — AD-72 — The GUI smoke names dialogs by their window title, and nothing pins the two together
  Why: `capture_modal_dialog` matches `dialog.windowTitle()` against a literal in the render script. Renaming a dialog title in `gui.py` therefore breaks a gate in a file nobody editing the GUI would think to open, and the failure this pass hit was silent for eight minutes before it was even visible as a stall. The raise-inside-the-timer hang is fixed, but the coupling is still a literal in one file matching a literal in another. Either read the expected title from the module under test, or add a unit test that asserts the two agree.
  Where: `scripts/render-companion-gui.py` `capture_modal_dialog` and its five callers; the `setWindowTitle` calls in `astra_downloader/gui.py`.

- [ ] P2 — AD-60 — A site profile's download type is stored and never applied outside the paste box
  Why: `sanitize_site_profiles` validates and stores `DownloadType`, and `start_download` applies a profile's `VideoFormat`, `AudioFormat` and `Quality` but not its `DownloadType`. The only consumer is the GUI paste box. An API or subscription download for a profiled domain therefore ignores the audio-only or subtitles-only preference the user set for that site. Decide whether the field is a paste-box default (rename it, or say so in the setting's help text) or a profile rule, then make one true.
  Where: `astra_downloader/config.py` (`DownloadType` in the profile schema), `astra_downloader/download.py` `start_download`, `astra_downloader/gui.py` `_sync_quick_download_profile`.

- [ ] P2 — AD-61 — Six error toasts splice raw exception text and name no next step
  Why: `Could not read stored sign-ins: {error}`, `Could not read that file: {error}` (twice), `Could not write the bundle: {error}`, `Could not read that bundle: {error}`, `Could not export download history: {error}`, plus `{label}: {error}` paired with a bare "Test failed". Their siblings all end in a concrete action ("check disk permissions and retry"). These end in a Python exception string, unbounded in length, with no suggestion of what to do.
  Where: `astra_downloader/gui.py`, the seven `tr_format` sites listed above.

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

- [ ] P2 | AD-82 | Make the server-log empty state follow server state
  Why: The extension page can show Server online, Running, and Stop server while the empty log card simultaneously says to start the API and offers Start server.
  Evidence: build/companion-ui-smoke/dashboard-online.png; astra_downloader/gui_extension_page.py log_empty_state; astra_downloader/gui.py _restore_log_view and _set_server_running.
  Touches: astra_downloader/gui_extension_page.py, astra_downloader/gui.py, astra_downloader/test_gui.py, scripts/render-companion-gui.py.
  Acceptance: Running with no log lines shows No events yet without a Start action. Stopped with no lines offers Start server. State changes, clear-log, and restored persisted entries keep the correct variant, and both states are pinned by GUI tests plus the online smoke capture.
  Complexity: S

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
