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

- **Per-download destination.** `DownloadPath` / `AudioDownloadPath` are
  global settings and `/pick-folder` already opens a native picker. The paste
  box should be able to override the destination for one download without
  changing the default.

- **Drag and drop onto the window.** A downloader should accept a dropped
  link or a dropped text file of links. `_start_quick_download` already takes
  a whitespace-separated batch, so this is a `dragEnterEvent` /
  `dropEvent` pair on the Download page plus the existing batch path.

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
- *Per-download destination* — corroborated; Stacher and YTPTube both ship
  per-item destinations and 4K Video Downloader paywalls the related URL-list
  import/export.
- *Drag and drop* — corroborated as table-stakes (Tartube, media-downloader).
- *Light-theme behaviour* — no theme key exists in `DEFAULT_CONFIG`, so the
  work is "build a light theme", not "audit the existing one".
- *Subscriptions unaudited* — corroborated from the other direction:
  `subscriptions.py` is 866 lines behind a single test class.

### P1

- [ ] P1 — Tell the user when a state file was quarantined, and offer restore
  Why: A corrupt `config.json` silently regenerates the server token — breaking extension pairing — and reverts every setting; a corrupt `download-queue.json` is indistinguishable from an empty one and discards all pending work, while a mere schema mismatch is properly surfaced.
  Evidence: `config.py:734-748` renames to `<name>.corrupt-<timestamp>` with no notification; `download.py:1226-1230` and `1384-1400` treat an empty dict as a valid empty queue; `config.py:654-655` regenerates the token.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: Quarantining a file raises a persistent, dismissible in-app notice naming the file and its backup path, with a one-click restore that swaps the backup back and reloads; corrupt and empty queue files are distinguished.
  Complexity: M

- [ ] P1 — Authenticate the local instance-control socket
  Why: Any local process can send `shutdown` to `127.0.0.1:9752` and force-close the app mid-download, or `start` to bring up the API; `SO_REUSEADDR` additionally lets another process steal the listener on Windows.
  Evidence: `gui.py:3867-3894` — no token and no peer check, in contrast with the HTTP surface's `hmac.compare_digest` bearer auth (`routes.py:260-262`).
  Touches: `astra_downloader/gui.py`, `astra_downloader/astra_downloader.py` (uninstall handshake at line 3192), `astra_downloader/test_astra_downloader.py`
  Acceptance: Control commands carry the session token and are rejected without it; `SO_REUSEADDR` is removed or replaced with `SO_EXCLUSIVEADDRUSE` so a second binder fails rather than hijacking; the uninstall handshake still works.
  Complexity: M

- [ ] P1 — Stop `/health` disclosing the subscription list to unauthenticated callers
  Why: `/health` deliberately auth-gates `recentErrors` with a comment explaining the threat model, then returns every subscribed channel URL and title two lines later to any local caller.
  Evidence: `routes.py:408` against `routes.py:410-412`; `snapshot()` reaches `subscriptions.py:698` and `370-372`.
  Touches: `astra_downloader/routes.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: `subscriptions` is present only when `check_auth()` passes, matching the sibling field; an unauthenticated `/health` still returns the identity and version fields the extension needs for discovery.
  Complexity: S

- [ ] P1 — Raise the source-run Python floor to 3.11
  Why: `requirements.txt` pins `yt-dlp==2026.7.4`, whose release raised the minimum Python to 3.11, but the module-load guard still admits 3.10 — so a 3.10 checkout fails at dependency resolution instead of at the guard that exists to explain it.
  Evidence: `astra_downloader.py:16-17` (`_MIN_PYTHON = (3, 10)`, with a comment citing the older 3.9 drop); yt-dlp 2026.07.04 release notes. `build.py:43` already restricts release builds to 3.11 and 3.12.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/requirements.txt`, `README.md`
  Acceptance: `_MIN_PYTHON` is `(3, 11)`, its comment cites the current reason, and the README's source-run instructions agree.
  Complexity: S

- [ ] P1 — Make fatal startup and slot exceptions visible
  Why: For a windowed exe, a fatal startup error means double-clicking the icon does nothing at all, forever; and with no `sys.excepthook` or Qt hook, an exception inside a slot aborts the process without even a crash-log line.
  Evidence: `astra_downloader.py:3620-3626` logs and swallows; no `excepthook` exists anywhere in `astra_downloader/`.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`
  Acceptance: A fatal startup error shows a native message box naming the crash-log path and exits non-zero; `sys.excepthook` and a Qt slot hook route unhandled exceptions to `log_crash` plus a non-fatal in-app notice.
  Complexity: S

### P2

- [ ] P2 — Finish the localisation
  Why: The app advertises 11 locales but ships translations for about a tenth of its strings, so choosing German yields a mostly-English window. This is also the only feature any external user has ever requested.
  Evidence: 21 `<message>` entries per catalogue against 122 `tr()` call sites plus 85 auto-translated `make_label()` calls in `gui.py`; `i18n.py:10-22` advertises 11 locales; Astra Deck issue #1 asks for Chinese. ytDownloader (23 Crowdin languages) and Parabolic (Weblate) both outsource this work.
  Touches: `scripts/build-companion-translations.py`, `astra_downloader/translations/`, `astra_downloader/gui.py`
  Acceptance: Every string reaching `tr()` or `make_label()` is extracted into the `.ts` sources; a gate fails when an untranslated literal is added; the German scenario in `scripts/render-companion-gui.py` asserts a translated string on each of the six pages rather than only the nav rail.
  Complexity: L

- [ ] P2 — Give repeated row buttons distinguishing accessible names
  Why: A screen-reader user tabbing the History list hears "Show, Show, Show" with no way to tell which file; the same applies to Remove on Sign-ins and Subscriptions, and to every download-card action.
  Evidence: `_make_tool_button` names the button from its own text (`gui.py:1124-1132`); repeated rows at `gui.py:3279-3281`, `1984-1988`, `1830-1835` and `2880-2928`. The correct pattern already exists for status labels (`gui.py:2842-2844`).
  Touches: `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: Each per-row control's accessible name includes its target; a test renders a three-item list and asserts every accessible name is distinct.
  Complexity: S

- [ ] P2 — Keep keyboard focus when a download card is rebuilt
  Why: Focus restoration only fires when the same widget object survives, but a card is destroyed and rebuilt on every status transition — so a keyboard user on a running download's Cancel button loses focus to nowhere the moment it completes.
  Evidence: `gui.py:2999-3009` rebuilds when `_astra_structure` changes; `gui.py:3038-3043` restores only when the retained widget is identical.
  Touches: `astra_downloader/gui.py`
  Acceptance: Focus is restored by logical key (download id plus action) across a structure change; a test focuses a card action, forces a status transition, and asserts focus lands on the equivalent control or the card itself.
  Complexity: M

- [ ] P2 — Report History page failures on the History page
  Why: Clear, undo and export report failures through `_append_log`, which writes to the Server log panel on a different page, so a user who hits a permissions error on History sees nothing at all.
  Evidence: `gui.py:3293-3298`, `3309-3314`, `3179` and `3209-3211` against the log widget's home at `gui.py:1358-1367`. Every other page has a status widget.
  Touches: `astra_downloader/gui.py`
  Acceptance: History gains a status label following the existing pattern, and clear, undo and export render both success and failure on-page.
  Complexity: S

- [ ] P2 — Export and import settings, sign-ins and subscriptions
  Why: The only export is history to CSV, one-way and capped; an install cannot be migrated to another machine, and a corrupt config is unrecoverable through the UI even though the original bytes sit beside it.
  Evidence: `gui.py:3175-3212` is the sole export path. Requested repeatedly elsewhere (Open Video Downloader #630, Seal #425); 4K Video Downloader paywalls URL list import/export.
  Touches: `astra_downloader/gui.py`, `astra_downloader/config.py`, `astra_downloader/subscriptions.py`, `astra_downloader/download.py`
  Acceptance: A single versioned JSON bundle round-trips settings and subscriptions; cookie jar contents are excluded by default behind an explicit opt-in that warns, preserving the no-read-path rule; import validates the schema and reports what changed.
  Complexity: M

- [ ] P2 — Per-category SponsorBlock instead of `all`
  Why: The app sends the literal `all`, so enabling SponsorBlock to skip sponsors also removes intros, outros and self-promo with no way to choose.
  Evidence: `download.py:2202-2204`. Parabolic #1583 requests exactly this; NeoDLP, YTDLnis and YTSage all ship category pickers.
  Touches: `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: Settings exposes the yt-dlp category list with per-category mark or remove; the argv carries the selected categories; the YouTube-only scoping at `download.py:2202` is preserved.
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

- [ ] P2 — Throttle `_update_ui` and debounce the history search
  Why: `_update_ui` runs on the GUI thread for every yt-dlp progress line with no throttle on top of a 500 ms timer, and every keystroke in the history search re-reads and re-sanitises `history.json` and rebuilds up to 50 widgets.
  Evidence: `gui.py:1066-1076` wires both the timer and `progress_updated`; `download.py:2036`, `2061`, `2072`, `2080` and `2083` emit per line; `gui.py:1680-1688` wires `textChanged` straight to `_refresh_history`, which loads from disk at `gui.py:3217`.
  Touches: `astra_downloader/gui.py`
  Acceptance: UI refreshes coalesce to at most one per timer tick regardless of progress-line volume; the history search debounces by 200 to 300 ms and reuses a cached load; a test asserts the refresh count under a burst of progress signals.
  Complexity: S

- [ ] P2 — Make the `ytdl://` and `mediadl://` handlers download the URL they were given
  Why: The handlers are registered but the payload is discarded — the URL maps to the literal command `start`, so clicking such a link launches the app and never queues the video.
  Evidence: `astra_downloader.py:2483-2496` registers the handler as `<exe> "%1"`; `astra_downloader.py:2372-2380` maps any such argument to `start`; nothing parses the payload.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: `ytdl://<encoded url>` enqueues that URL through the same policy checks as the paste box, including `media_url_block_reason`, and reports the result; a bare `ytdl://start` keeps the current start-the-server behaviour.
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

- [ ] P2 — Guarantee one file per finished download
  Why: A recurring complaint about tools in this class is that a download leaves three or four files plus a folder — `.part`, `.f###`, `.ytdl` and sidecars — with no cleanup.
  Evidence: no `.part` or `.ytdl` sweep exists in `download.py`; VideoHelp thread 414206 ("there are 3/4 files and a folder when downloading, I want just 1 file"). Interacts with the `--force-overwrites` item above, which governs `.part` retention.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`
  Acceptance: Intermediates are removed on success and retained on failure for resume; a "keep intermediate files" setting exists for debugging; a test asserts the post-success directory contents for a merged download.
  Complexity: S

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

- [ ] P2 — Bound the sign-in file import before it reaches memory
  Why: The import reads an unbounded file into RAM on the GUI thread, so choosing a multi-gigabyte file freezes the window before the downstream 1 MB cap rejects it.
  Evidence: `gui.py:2069-2073` reads with no size check, against the cap in `import_netscape_text` (`download.py:662-663`); the HTTP path is bounded correctly.
  Touches: `astra_downloader/gui.py`
  Acceptance: File size is checked before reading, oversized files are rejected through the existing error surface, and the read happens off the GUI thread.
  Complexity: S

- [ ] P2 — Correct the diagnostics ring-buffer limit and the test that hides it
  Why: The bundle advertises 30 entries but the ring holds 20, and the test injects 35 synthetic entries and asserts 30 — so it passes for the wrong reason and the mismatch cannot be caught.
  Evidence: `astra_downloader.py:236` (`DIAGNOSTIC_LOG_ENTRY_LIMIT = 30`) against `astra_downloader.py:352` (`deque(maxlen=20)`); `test_astra_downloader.py:1163` and `1178`.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: The two constants derive from one source, and the test exercises the real ring rather than an injected list so it fails if they diverge again.
  Complexity: S

### P3

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
