# Roadmap

Actionable items only — work a coding agent can pick up and implement without
external dependencies. Completed items are deleted; shipped work lives in git
history and `CHANGELOG.md`.

## P2 — Downloader-first follow-ups from the v2.0.0 split

- **Format probing before download.** `/formats` already returns the real
  format table for a URL. The GUI's quality picker is a fixed list
  (Best/2160/1440/1080/720/480) that does not know what the pasted link
  actually offers, so a user can pick 2160p on a 720p video and only learn
  the truth from the result. Probe on paste (debounced, cancellable) and
  reduce the picker to what exists.

## P3 — Unaudited — needs a pass

Carried over from the Astra Deck audit backlog: these companion areas were
never given a dedicated audit pass.

- The subscriptions surface (`astra_downloader/subscriptions.py`, 866 lines)
  and its GUI page.
- `astra_downloader/build.py` and the release staging scripts.
- The GUI's light-theme behaviour. The product is dark-first by design, but
  nothing verifies what happens under a light Windows theme.

## Research-Driven Additions

Added 2026-08-06 from the research pass recorded in `RESEARCH.md`. Every item
below traces to a finding or source there.

Notes on the items above, from the same pass:
- *Format probing before download* — confirmed as the most common gap complaint
  in this software class (MeTube #1032, ytDownloader #231) and a prerequisite
  for audio-track and codec selection. It should land together with "Sort
  formats instead of guessing quality" below.
- *Light-theme behaviour* — no theme key exists in `DEFAULT_CONFIG`, so the
  work is "build a light theme", not "audit the existing one".
- *Subscriptions unaudited* — corroborated from the other direction:
  `subscriptions.py` is 866 lines behind a single test class.

### P1

- [ ] P1 — Let a failure be retried once its recovery action has been performed
  Why: The message on a non-retryable failure says "This failure needs its recovery action before it can be retried", promising a path that does not exist — nothing re-evaluates after the user installs Deno, refreshes ffmpeg or stores a sign-in, so the only way forward is to re-paste the URL and lose the queue entry.
  Evidence: `DOWNLOAD_FAILURE_RECOVERY` classifies 13 codes; `DOWNLOAD_RETRYABLE_ERROR_CODES` (`download.py:64-70`) contains 5. The 8 excluded are precisely the user-fixable ones — `js-runtime-missing`, `js-runtime-unsupported`, `js-runtime-unverified`, `ejs-runtime-not-ready`, `deno-runtime-missing`, `deno-runtime-unsupported`, `ffmpeg-missing-or-stale`, `sign-in-required`. `retry()` refuses them at `download.py:2758`. The readiness probe already knows when a runtime became usable, and `SiteLoginStore.has_login_for` already answers the sign-in question.
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: a failure whose precondition is now satisfied becomes retryable and its card offers Retry; one whose precondition is still unmet keeps the current refusal and says what is still missing; a test fails a download with `js-runtime-missing`, reports a usable runtime, and asserts the retry is accepted.
  Complexity: M

### P2

- [ ] P2 — Make a right-to-left locale render correctly, and render one in the smoke
  Why: Arabic is advertised and flips the whole layout to RTL, but 84% of the window is still English, so an Arabic user gets mirrored chrome wrapped around left-aligned English — worse than plain English. No gate could have caught it because no RTL locale is ever rendered.
  Evidence: measured 2026-08-06 by rendering the real window under `ar` offscreen — 121 of 144 visible strings were pure ASCII. `i18n.py:62-66` sets `Qt.LayoutDirection.RightToLeft` for `ar`. `scripts/render-companion-gui.py` has 19 scenarios and no RTL one; its only locale scenario is `dashboard-german`, which asserts on the nav rail — the one surface Arabic does translate, except *Subscriptions*, which stays English. In the capture the hero Download button renders at a fraction of its LTR width with its icon against the frame edge. Details and the measurement in `RESEARCH.md` (Second Pass).
  Touches: `scripts/render-companion-gui.py`, `astra_downloader/gui.py`, `astra_downloader/translations/`
  Acceptance: an `ar` scenario joins the smoke set and captures the Download page; the hero button keeps its LTR proportions under RTL; the German rail assertion is extended to a body string on the same page so a rail-only translation can no longer pass. Pairs with "Finish the localisation" — this item is the RTL correctness half, not the bulk-translation half.
  Complexity: M

- [ ] P2 — Adopt yt-dlp's throttling and transient-failure recovery knobs
  Why: The app sets `--retries` and `--fragment-retries` and stops there, so a CDN that silently throttles to a trickle, a stalled socket, or a flaky extractor all present as the stall watchdog eventually killing a download that yt-dlp could have recovered on its own.
  Evidence: none of `--throttled-rate`, `--http-chunk-size`, `--socket-timeout`, `--extractor-retries`, `--retry-sleep` or `--file-access-retries` appears anywhere in `astra_downloader/` (verified against the full 276-option `--help` inventory, 2026-08-06). `--throttled-rate` re-extracts the video when the rate drops below a floor, which is the documented remedy for the YouTube throttling this class of tool hits most. Distinct from the pacing item above: that one is about not provoking 429s, this one is about surviving a slow or flaky transfer.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: a throttle floor, socket timeout and extractor-retry count are settings compiled into the argv with conservative defaults; the stall watchdog's timeout is documented as the backstop for when they fail; a test asserts the flags appear and that the defaults do not change existing argv expectations.
  Complexity: M

- [ ] P2 — Fetch a playlist or subscription incrementally instead of whole
  Why: A subscription scan and a playlist download both re-walk everything every time. yt-dlp has the selection primitives to stop at the first already-seen item, bound a run, and filter by date or duration; none is used, so the subscription scheduler does the most expensive possible thing on every tick.
  Evidence: the selection theme is the single largest unused group — 29 options — and none of `--break-on-existing`, `--dateafter`, `--datebefore`, `--max-downloads`, `--match-filters`, `--min-filesize` or `--lazy-playlist` appears in `astra_downloader/` (verified 2026-08-06). `--download-archive` is deliberately excluded and pinned by test, and must stay excluded — the archive-key mechanism in `subscriptions.py` is this project's answer to the same problem, so the new flags must complement it rather than reintroduce it.
  Touches: `astra_downloader/subscriptions.py`, `astra_downloader/download.py`, `astra_downloader/config.py`, `astra_downloader/gui.py`
  Acceptance: a subscription scan bounds itself by count and by date and stops early once it reaches known items, without `--download-archive`; a playlist download can be capped; the existing no-archive tests still pass.
  Complexity: M

- [ ] P2 — Verify a format is actually downloadable before committing to it
  Why: The selector picks a format from the manifest and finds out at transfer time whether it works, which is one of the ways a download fails with no useful reason attached.
  Evidence: neither `--check-formats` nor `--ignore-no-formats-error` appears in `astra_downloader/` (verified 2026-08-06). Pairs directly with "Format probing before download" and "Sort formats instead of guessing quality" — all three read the same format table, so they should share one probe rather than three.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`
  Acceptance: format verification is opt-in with its cost documented (it fetches a byte range per candidate); a failure to verify is classified into the existing taxonomy rather than surfacing as raw yt-dlp text.
  Complexity: S

- [ ] P2 — Finish the localisation
  Why: The app advertises 11 locales but ships translations for about a tenth of its strings, so choosing German yields a mostly-English window. This is also the only feature any external user has ever requested.
  Evidence: 21 `<message>` entries per catalogue against 122 `tr()` call sites plus 85 auto-translated `make_label()` calls in `gui.py`; `i18n.py:10-22` advertises 11 locales; Astra Deck issue #1 asks for Chinese. ytDownloader (23 Crowdin languages) and Parabolic (Weblate) both outsource this work.
  Touches: `scripts/build-companion-translations.py`, `astra_downloader/translations/`, `astra_downloader/gui.py`
  Acceptance: Every string reaching `tr()` or `make_label()` is extracted into the `.ts` sources; a gate fails when an untranslated literal is added; the German scenario in `scripts/render-companion-gui.py` asserts a translated string on each of the six pages rather than only the nav rail.
  Complexity: L

- [ ] P2 — Export and import settings, sign-ins and subscriptions
  Why: The only export is history to CSV, one-way and capped; an install cannot be migrated to another machine, and a corrupt config is unrecoverable through the UI even though the original bytes sit beside it.
  Evidence: `gui.py:3175-3212` is the sole export path. Requested repeatedly elsewhere (Open Video Downloader #630, Seal #425); 4K Video Downloader paywalls URL list import/export.
  Touches: `astra_downloader/gui.py`, `astra_downloader/config.py`, `astra_downloader/subscriptions.py`, `astra_downloader/download.py`
  Acceptance: A single versioned JSON bundle round-trips settings and subscriptions; cookie jar contents are excluded by default behind an explicit opt-in that warns, preserving the no-read-path rule; import validates the schema and reports what changed.
  Complexity: M

- [ ] P2 — Separate creator subtitles from auto-generated ones
  Why: The app passes `--write-subs` and `--write-auto-subs` together with a single language string, so users get both when they wanted "manual if it exists, else auto", and there is no way to fetch subtitles without the video or to normalise the format.
  Evidence: `download.py:2198` passes both unconditionally. yt-dlp #2262 is the second most-upvoted enhancement upstream; Open Video Downloader #659 asks for subtitle-only downloads; SnapDownloader sells subtitle language coverage as a paid feature.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: The user chooses manual, auto, or prefer-manual-else-auto; picks languages from a multi-select; can request `--convert-subs srt`; and can run a subtitles-only job that skips the media.
  Complexity: M

- [ ] P2 — Expose `--impersonate`
  Why: The vendored yt-dlp already ships curl_cffi with at least nine impersonation targets and nothing surfaces them, leaving the standard remedy for Cloudflare and TLS-fingerprint 403s unavailable.
  Evidence: `yt-dlp.exe --list-impersonate-targets` on the installed 2026.08.04 build returns Chrome, Safari, Edge and Tor targets (run 2026-08-06); no `impersonate` reference exists anywhere in `astra_downloader/`. Caveat to surface in the UI: impersonation can itself trigger 429 on some sites (yt-dlp #10422).
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`, `astra_downloader/health.py`
  Acceptance: A per-site impersonation target can be chosen, defaulting to off; the target list is read from `--list-impersonate-targets` rather than hardcoded; `classify_download_failure` suggests it on a 403.
  Complexity: M

- [ ] P2 — Bundle QuickJS so YouTube works without a Deno install
  Why: Installing Deno is the biggest first-run blocker for full YouTube support, and yt-dlp accepts QuickJS — roughly a 1 MB binary — through plumbing this app already has.
  Evidence: `--js-runtimes RUNTIME[:PATH]` supports deno, node, quickjs and bun (`yt-dlp.exe --help`, verified 2026-08-06); `build_javascript_runtime_args` already emits `--no-js-runtimes --js-runtimes <runtime>:<path>` but gates on `runtime not in {'deno', 'node'}` (`health.py:131`); the picker offers only Deno and Node (`gui.py:2395-2396`). yt-dlp #15012 confirms quickjs is supported but disabled by default.
  Touches: `astra_downloader/health.py`, `astra_downloader/gui.py`, `astra_downloader/build.py`, `astra_downloader/config.py`
  Acceptance: A bundled `qjs` binary is detected and used automatically when no Deno or Node is present, with a version floor enforced as for the others; the readiness row names the runtime in use; a fresh install downloads a YouTube video with no user-installed runtime.
  Complexity: M

- [ ] P2 — Sort formats instead of guessing quality
  Why: The quality picker is a fixed ladder that cannot express codec, frame-rate or HDR preference, so users cannot ask for "1080p H.264 60fps, never AV1" — the most common power-user need in this class.
  Evidence: no `--format-sort` anywhere in `astra_downloader/`; `build_video_format_args` (`download.py:897-918`) encodes preferences as a hand-built cascade. yt-dlp added `--format-sort-reset` and `--compat-options 2025` in 2026.01.29. Pairs with the existing "Format probing before download" item.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`, `astra_downloader/gui.py`
  Acceptance: Preferred codec, container, frame rate and resolution ceiling are settings that compile to `--format-sort`; the editor-safe H.264 and AAC path survives as a named preset; existing format tests still pass.
  Complexity: M

- [ ] P2 — Politeness pacing between downloads
  Why: Rate-limit remedies are currently limited to a bandwidth cap, but yt-dlp's request pacing is the actual lever against 429s, and every commercial rival sells it.
  Evidence: none of `--sleep-interval`, `--max-sleep-interval`, `--sleep-requests` or `--sleep-subtitles` appear in `astra_downloader/`; yt-dlp #13831 is a subtitle 429 report; Downie shipped configurable inter-download and inter-preparation delays in 4.12.2 and 4.12.3; SnapDownloader and StreamFab paywall scheduling and pacing.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: Configurable request and inter-download sleeps compile to the yt-dlp flags; a classified 429 offers to raise them; the queue row reads "waiting Ns" instead of appearing hung.
  Complexity: M

- [ ] P2 — Self-heal a quarantined or truncated yt-dlp or ffmpeg binary
  Why: Antivirus removing the bundled tools is the largest single support burden for OSS downloaders of this shape, and the app currently discovers it as an opaque failure rather than naming it.
  Evidence: seven Open Video Downloader issues reduce to "binaries missing or corrupted, disable your antivirus" (#390, #436, #354, #362, #534, #555, #506). `verify_file_sha256` (`astra_downloader.py:839`) already exists for the update path but is not applied as a launch-time integrity check.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/health.py`, `astra_downloader/gui.py`
  Acceptance: On launch a missing or zero-size managed binary is re-fetched automatically, and the log and readiness row say that antivirus may have removed it, naming the exclusion path.
  Complexity: M

- [ ] P2 — Windows shell integration: AppUserModelID, taskbar progress, notification actions
  Why: Without an explicit AppUserModelID an unpackaged exe has unreliable taskbar-pinning identity and toast attribution; download progress is invisible unless the window is open; and completion notifications cannot be clicked to reach the file.
  Evidence: no `SetCurrentProcessExplicitAppUserModelID` anywhere in `astra_downloader/`; progress exists only in-window (`gui.py:2933`); `QSystemTrayIcon.messageClicked` is never connected, only `activated` (`gui.py:1059`); `_show_download_location` opens the parent folder with `os.startfile` rather than selecting the file (`gui.py:3349-3361`).
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`
  Acceptance: An AppUserModelID is set before the first window is created; the taskbar button shows aggregate queue progress; clicking a completion notification reveals the file with `explorer /select,`; a right-click menu on a finished card offers play, reveal, copy URL and re-download.
  Complexity: M

- [ ] P2 — Disclose SABR-imposed limitations instead of failing mid-run
  Why: When a URL yields SABR-only formats, clip ranges, rate limits and concurrent fragments are all silently void — exactly the unexplained degradation the failure taxonomy exists to prevent.
  Evidence: yt-dlp PR #13515, still open as of 2026-07, documents that `--download-sections`, `--rate-limit` and `-N` are unsupported with SABR; `evaluate_sabr_support` and a `sabr-limited` error code already exist (`health.py`, `download.py:70-171`).
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`, `astra_downloader/health.py`
  Acceptance: When SABR is detected for a URL the affected controls are disabled with an explanation before the run starts, and the `sabr-limited` advice names which options were dropped.
  Complexity: M

### P3

- [ ] P3 — Give `subscriptions.py` a real test surface
  Why: The scheduling core is 872 lines behind a single test class, and it is the one subsystem that runs unattended — a defect there is discovered by a user whose channel silently stopped downloading.
  Evidence: measured 2026-08-06 — 25 methods are never named anywhere in `test_astra_downloader.py`, including `due_subscriptions`, `begin_scan`, `finish_scan`, `_trim_archive_locked`, `release_archive` and `handle_download_completed`, which is the entire scan lifecycle. `routes.py` shows a similar count but is a false alarm: its handlers are exercised through the Flask test client by URL rather than by name.
  Touches: `astra_downloader/test_astra_downloader.py`
  Acceptance: the scan lifecycle has tests asserting effects — a due subscription becomes not-due after `begin_scan`, an interrupted scan is recoverable, the archive trims at its bound, and a completed download updates the right subscription — each mutation-checked.
  Complexity: M

- [ ] P3 — Geo and network-path workarounds for the failures a proxy cannot fix
  Why: A geo-blocked video and an IPv6-routing failure are both common, both have one-flag remedies upstream, and neither is reachable here; the only network control offered is a whole-session proxy.
  Evidence: none of `--xff`, `--force-ipv4`, `--force-ipv6`, `--source-address` or `--geo-verification-proxy` appears in `astra_downloader/` (verified 2026-08-06). `--force-ipv4` in particular is a long-standing remedy for YouTube 403s on dual-stack hosts.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: the options are settings defaulting to off; `classify_download_failure` suggests `--force-ipv4` on the 403 shape it already recognises and `--xff` on a geo-restriction message.
  Complexity: S

- [ ] P3 — Close the highest-risk test gaps
  Why: The P0 uninstall defect shipped because the only test asserted the argv shape rather than the outcome, and several other security-relevant paths have the same shape of coverage.
  Evidence: no outcome assertions exist for `run_uninstall`, `redact_diagnostic_text`, `bound_output_template_fields`, `due_subscriptions`, `closeEvent`, `_export_history` including `sanitize_csv_cell`'s formula-injection defence (`gui.py:65-69`), `_import_site_login_from_file`, or the stall and retry watchdog closures (`download.py:2311-2333`, `2466-2487`).
  Touches: `astra_downloader/test_astra_downloader.py`
  Acceptance: Each named function has at least one test asserting its effect rather than its arguments, and each new test is mutation-checked by confirming it fails against the unfixed behaviour.
  Complexity: M

- [ ] P3 — Site profiles selected by URL pattern
  Why: This is the one feature that would put the project ahead of the field rather than level with it, and it composes with the per-site cookie store already in place: one site identity holding cookies, format preference, impersonation target, proxy and pacing.
  Evidence: only Stacher7, which is closed-source, ships URL-pattern profile auto-selection; media-downloader has URL-to-engine rules; yt-dlp #4680 ("Site based configuration") is open upstream. `SiteLoginStore` already keys by registrable domain (`download.py:396-410`).
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: A named profile can be bound to a domain and is applied automatically when a matching link is pasted, with the paste box naming the chosen profile and allowing a one-off override.
  Complexity: L

- [ ] P3 — Archive-quality output options
  Why: The archivist persona is the least served: no sidecar metadata, no chapter splitting and no live capture, all of which yt-dlp supports and competitors sell.
  Evidence: none of `--write-info-json`, `--write-description`, `--write-thumbnail`, `--split-chapters`, `--live-from-start` or `--wait-for-video` appear in `astra_downloader/`. SnapDownloader sells chapters as separate files; yt-dlp restored `--live-from-start` in 2026.03.17; "live event has ended" handling already exists at `download.py:2411`.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: Sidecar writes, chapter splitting and live-from-start are settings that compile to the corresponding flags, default off, with the existing embed options unchanged.
  Complexity: M

- [ ] P3 — Filename template builder with a Windows-safety preview
  Why: Output templates are an unassisted free-text field, and long-path and reserved-name failures are among the most reported yt-dlp problems on Windows.
  Evidence: `OutputTemplate` is validated but not assisted (`config.py:144`); `--trim-filenames 180` is applied blindly (`download.py:2176`); `--windows-filenames` is never passed. yt-dlp #1136 and #8789 are the long-filename reports; Downie added a resolution placeholder in 4.11.8.
  Touches: `astra_downloader/gui.py`, `astra_downloader/config.py`, `astra_downloader/download.py`
  Acceptance: The settings field previews a rendered example filename, flags reserved names and over-length paths before saving, and `--windows-filenames` is passed.
  Complexity: M

- [ ] P3 — Document the security positions the code already takes
  Why: Two deliberate decisions are invisible to users and to contributors, so both keep being re-litigated as missing features or reported as bugs.
  Evidence: the aria2c and external-downloader ban is enforced by test (`test_astra_downloader.py:5795`) over CVE-2026-50574 but appears nowhere in `README.md` — Open Video Downloader #49 shows it will be requested. The unsigned build is permanent project policy, and HN 47588658 shows SmartScreen friction is universal for this software class, so it needs an explanation plus the existing SHA-256 sidecar, not a signing plan.
  Touches: `README.md`, `SECURITY.md`
  Acceptance: The README states why no external downloader is offered and why the build is unsigned, with the checksum verification steps; `SECURITY.md` lists both as accepted properties rather than open risks.
  Complexity: S

- [ ] P3 — Package for winget and offer a portable mode
  Why: Every comparable project ships through a package manager, and the install location is hardcoded with no portable option.
  Evidence: `INSTALL_DIR` is unconditionally `%LOCALAPPDATA%\AstraDownloader` (`astra_downloader.py:244`) with no portable flag; the CLI exposes only `--background`, `--uninstall`, `--update-health-check` and `--visual-smoke`, while winget requires a silent-install path. ytDownloader, Open Video Downloader, NeoDLP and media-downloader all ship winget manifests.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/build.py`, `README.md`
  Acceptance: A silent install path exists and is documented; a portable mode keeps all state beside the executable; a winget manifest is published. Resolve the open question in `RESEARCH.md` about one-folder versus single-file packaging before choosing the installer shape.
  Complexity: L
