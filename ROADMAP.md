# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## v2.15.2 marketing delivery

The README opens with one evergreen share card and keeps release numbers in text and badges. The usage guide and build guide separate verified product behavior from site-dependent claims. A dated concept archive retains the original source and every review capture. The package review runs offscreen in a new disposable profile. Existing feature work below remains open.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

### P2


- [ ] P2 | AD-77 | Turn the format probe into a truthful pre-download summary
  Why: The probe already returns title, duration, formats, and approximate sizes, but the GUI shows only maximum height and deliberately hides every lookup error.
  Evidence: astra_downloader/download.py summarize_ytdlp_formats; astra_downloader/gui.py _apply_format_probe; Parabolic 2026.4 preview work; ytDownloader issue 406.
  Touches: astra_downloader/download.py, astra_downloader/gui.py, astra_downloader/gui_download_page.py, astra_downloader/test_gui.py, translation catalogues.
  Acceptance: A successful single-link probe shows sanitized title, duration, maximum resolution, and an approximate size for the selected output when known. A failed probe leaves Add to queue available but shows a bounded warning with the relevant health or sign-in next step. Editing the URL, entering a batch, or receiving a stale generation clears the summary. The card wraps at 900x620, has an accessible name, and passes German and RTL fixtures.
  Complexity: M


- [ ] P2 | AD-79 | Honor Windows contrast themes at runtime
  Why: Astra's authored QSS follows light or dark only and can override the system colors that Windows contrast themes and Qt 6.10+ provide.
  Evidence: astra_downloader/astra_downloader.py apply_application_theme; QAccessibilityHints contrastPreference; Microsoft Windows contrast-theme guidance; existing AD-63 and AD-67 accessibility work.
  Touches: astra_downloader/astra_downloader.py, astra_downloader/gui.py, astra_downloader/gui_support.py, scripts/render-companion-gui.py, astra_downloader/test_gui.py.
  Acceptance: Starting in or switching to a Windows contrast theme changes Astra without restart through QAccessibilityHints. The contrast path uses native system colors or a dedicated token set that the normal QSS does not override. Major pages, dialogs, focus, selection, disabled controls, and status tones remain distinguishable in an isolated Windows accessibility run and a deterministic test fixture.
  Complexity: M


- [ ] P2 | AD-83 | Add explicit audio-language selection
  Why: Active Seal, Parabolic, and YTDLnis reports show that automatic format ranking can select the wrong dub or ignore a requested audio track, while Astra only applies a soft generic lang sort.
  Evidence: yt-dlp format-selection documentation; Seal issue 2592; Parabolic issues 1901 and 1938; YTDLnis issue 946; astra_downloader/download.py build_format_sort_args.
  Touches: astra_downloader/download.py, astra_downloader/routes.py, astra_downloader/gui_download_page.py, astra_downloader/gui.py, astra_downloader/subscriptions.py, queue and settings schemas, tests.
  Acceptance: Format discovery returns bounded available audio-language codes and an original-language marker. Quick downloads offer Automatic, Original, and discovered languages; the strict API, profiles, subscriptions, queue persistence, and settings bundles carry the same field. An explicit choice compiles to a tested yt-dlp selection rule, a missing choice falls back with a visible explanation, and History records the requested language plus the resolved language when yt-dlp reports it.
  Complexity: L


- [ ] P2 | AD-94 | Name the transcription model and let its size be chosen
  Why: Local subtitle generation is pinned to ggml-tiny-q5_1, the least accurate build whisper.cpp ships, and no string in the interface says so. The eleven English transcription strings say only "the bundled multilingual Whisper model", so a user who enables the option and gets poor captions cannot tell whether the feature is broken or the model is small, and cannot trade disk for accuracy.
  Evidence: astra_downloader/astra_downloader.py:519 WHISPER_MODEL_NAME = 'ggml-tiny-q5_1.bin' with its pinned revision and SHA-256 at :529-535; the transcription strings in astra_downloader/translations/astra_downloader_en.ts; MANAGED_BINARY_PIN_NAMES already carries a whisper entry.
  Touches: astra_downloader/astra_downloader.py, astra_downloader/config.py, astra_downloader/health.py, astra_downloader/gui_settings_page.py, astra_downloader/download.py, astra_downloader/test_health.py, translation catalogues.
  Acceptance: The Settings row and the readiness row name the model and its on-disk size. A model choice covering at least tiny and one larger quantized build is offered, each pinned by repository revision, filename and SHA-256 the same way the current one is, with the download deferred until the choice is saved and setup is run. Switching models verifies the new file before the old one is removed, a failed fetch leaves the previous model usable, and the readiness probe reports which model is present rather than a bare ready.
  Complexity: M


### P3


- [ ] P3 | AD-71 | Areas the 2026-08-22 audit did not reach
  Why: recorded so the next pass starts where this one stopped rather than re-covering it. Not audited: the PyInstaller build pipeline beyond running it; the native messaging host registration; the Windows shell integration (jump list, `RegisterApplicationRestart`, Recycle Bin delete) beyond reading it, since driving it needs a real desktop session; the whisper transcription path; the SponsorBlock and NFO writers; and the browser extension, which is a separate repository. The GUI was exercised offscreen through `npm run smoke:gui` and the Qt test suite, never driven interactively, so nothing here rests on watching a real window.
  Where: `astra_downloader/build.py`, the native-host block in `astra_downloader/astra_downloader.py`, the taskbar and jump-list block in `astra_downloader/gui.py`, the transcription block in `astra_downloader/download.py`.

- [ ] P3 | AD-84 | Add durable one-time queue scheduling
  Why: IDM, FDM, SnapDownloader, and Downie all expose one-time scheduling, while Astra schedules subscriptions and live retries but cannot defer an ordinary queued job across a restart.
  Evidence: IDM Scheduler documentation; FDM and SnapDownloader feature pages; Downie release notes; astra_downloader/download.py durable queue and host-backoff timer. AD-64 must land first.
  Touches: astra_downloader/download.py, astra_downloader/routes.py, astra_downloader/gui.py, astra_downloader/gui_download_page.py, queue schema and migration tests.
  Acceptance: A queue item can carry notBeforeUtc from the GUI or strict API. Future items display Scheduled and do not block later runnable work. One cancellable wake timer reevaluates wall-clock time, overdue work starts after restart or resume, pause and cancel remain authoritative, and the UI states that Astra does not wake a sleeping PC.
  Complexity: M


- [ ] P3 | AD-126 | Three PowerShell-spawning tests time out on a saturated machine
  Why: test_delayed_install_dir_removal_actually_deletes_the_directory, test_a_shortcut_carries_the_taskbar_identity and test_windows_update_helper_contains_verified_backup_and_rollback_contract each wait 30 seconds on a powershell.exe child. On 2026-10-06, with two other test runs sharing the machine, all three raised subprocess.TimeoutExpired inside `npm run check` (suite time 290 s against a 41 s quiet baseline), then passed when rerun alone. Same family as AD-125 and AD-112: the clock decides the result.
  Evidence: build/check-batch1b.log from 2026-10-06; astra_downloader/test_build.py UninstallCleanupTests, astra_downloader/test_gui.py WindowsShellIntegrationTests, astra_downloader/test_routes.py CompanionUpdateEndpointTests.
  Touches: those three tests, and the helpers they call if a readiness signal is needed.
  Acceptance: None of the three fails because PowerShell started slowly. Each either waits on the outcome it checks (the folder gone, the .lnk written, the parse result) with a give-up bound that only matters when the outcome never happens, or runs the PowerShell step once per session behind a fixture. A run of the full suite alongside a second full suite passes them.
  Complexity: S
