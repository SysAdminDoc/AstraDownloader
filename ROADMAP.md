# Roadmap

Actionable items only — work a coding agent can pick up and implement without
external dependencies. Completed items are deleted; shipped work lives in git
history and `CHANGELOG.md`.

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
- *Light-theme behaviour* — no theme key exists in `DEFAULT_CONFIG`, so the
  work is "build a light theme", not "audit the existing one".
- *Subscriptions unaudited* — corroborated from the other direction:
  `subscriptions.py` is 866 lines behind a single test class.

### P1

### P2

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

- [ ] P2 — Windows shell integration: AppUserModelID, taskbar progress, notification actions
  Why: Without an explicit AppUserModelID an unpackaged exe has unreliable taskbar-pinning identity and toast attribution; download progress is invisible unless the window is open; and completion notifications cannot be clicked to reach the file.
  Evidence: no `SetCurrentProcessExplicitAppUserModelID` anywhere in `astra_downloader/`; progress exists only in-window (`gui.py:2933`); `QSystemTrayIcon.messageClicked` is never connected, only `activated` (`gui.py:1059`); `_show_download_location` opens the parent folder with `os.startfile` rather than selecting the file (`gui.py:3349-3361`).
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`
  Acceptance: An AppUserModelID is set before the first window is created; the taskbar button shows aggregate queue progress; clicking a completion notification reveals the file with `explorer /select,`; a right-click menu on a finished card offers play, reveal, copy URL and re-download.
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

- [ ] P3 — Package for winget and offer a portable mode
  Why: Every comparable project ships through a package manager, and the install location is hardcoded with no portable option.
  Evidence: `INSTALL_DIR` is unconditionally `%LOCALAPPDATA%\AstraDownloader` (`astra_downloader.py:244`) with no portable flag; the CLI exposes only `--background`, `--uninstall`, `--update-health-check` and `--visual-smoke`, while winget requires a silent-install path. ytDownloader, Open Video Downloader, NeoDLP and media-downloader all ship winget manifests.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/build.py`, `README.md`
  Acceptance: A silent install path exists and is documented; a portable mode keeps all state beside the executable; a winget manifest is published. Resolve the open question in `RESEARCH.md` about one-folder versus single-file packaging before choosing the installer shape.
  Complexity: L
