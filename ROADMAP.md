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

## Audit Findings — 2026-08-06

### Notes on existing roadmap items

- *Light-theme behaviour* (the P3 "Unaudited" bullet) — confirmed and refined, not duplicated. There is no theme key in `DEFAULT_CONFIG` and `STYLESHEET` is applied unconditionally at `astra_downloader.py:3786`, so the work is indeed "build a light theme". Add one detail the existing note misses: the app already renders mixed-theme surfaces today, because `QFileDialog` (`gui.py:1863`, 2368, 3883, 4417) and the folder-picker service use the **system** palette rather than the app stylesheet. On a light Windows theme those dialogs render light against the dark window regardless of whether a light theme is ever built, so the item should cover native dialog surfaces explicitly.
- *Give `subscriptions.py` a real test surface* (P3) — the disk-full reporting defect logged above is a concrete instance of what that missing coverage hides; the lifecycle tests that item calls for should include it.

### Measured and found clean (do not re-investigate)

These were suspected, measured, and are **not** defects. Recorded so a later pass does not spend time on them again:

- **Text contrast** — every foreground measured on real pixels passes AA: `fieldHint` 6.57:1, placeholder 4.73:1, readiness values 14.26:1, queue meta 6.57:1. Only the *non-text* borders fail (logged above).
- **Accessible names** — 0 of 32 interactive controls lack both an accessible name and a text label; the focus chain from the paste box is in visual order. The v2.1.0 a11y work holds.
- **Subscription refresh cost** — `_refresh_subscriptions` runs on the 500 ms tick and calls `archive_summary()`, which walks the whole archive. Measured at the 20,000-entry cap: 3.88 ms per call, plus 0.07 ms for the subscription deepcopy and 0.04 ms for the JSON signature. Roughly 0.8% of one core; not worth optimising.
- **`/health` unauthenticated payload** — `read_update_recovery_status` (`astra_downloader.py:1388`) allowlists five string fields and truncates each to 80 chars; no paths or digests leak. `_public_runtime_status` (`routes.py:47`) strips the runtime path. Subscriptions and `recentErrors` are already behind `check_auth()`.
- **`build_format_sort_args` on audio-only downloads** — applied unconditionally including the `-f bestaudio` branch (`download.py:2535-2540`). The leading `res` field is inert for audio formats and `vcodec` matches nothing, so it is a no-op; `acodec` preference correctly still applies. Not a defect.

### Unaudited — needs a pass

Areas this pass did not cover, listed honestly so the gap is visible:

- **The native-messaging host bootstrap** (`astra_downloader.py:2715-2810`, `read_native_message`, manifest generation and the HKCU registry writes). Read but not exercised; it needs a browser to drive.
- **The self-update transaction** (`_run_companion_self_update`, `_run_ytdlp_self_update`, the staged-rollback updater, roughly `astra_downloader.py:1480-2350`). The largest untraced surface in the repo; it replaces a running executable and deserves its own dedicated pass.
- **`scripts/audit-python-deps.js` and `scripts/companion-license-inventory.js`** (402 and 437 lines). Both gates pass; neither was read closely enough to say whether they can fail for the right reasons.
- **Playwright/browser-driven verification of the Astra Deck extension contract.** The port catalogue gate checks the two copies agree, but no test in this repository exercises a real extension against the local API.
