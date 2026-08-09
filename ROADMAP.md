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

- [ ] P2 — Translate the strings the extractor cannot see
  Why: `Duration`, `Format` and `Quality` are the History list's column headers and render in English in every locale, because they are written with `setText()` at runtime rather than built through `tr()`. The same shape hides an unknown number of other strings: readiness values ("Checking", "Fallback"), and the composed status lines ("0 of 0 filtered · 0 retained", "Every 60 min · next scan ...").
  Evidence: measured 2026-08-06 by rendering the German locale and dumping every visible QLabel per page — the three column headers came back English against a 219/219 German catalogue. `scripts/extract_companion_strings.py` reads the syntax tree, so a literal that never appears as an argument to a translating call is invisible to it by construction.
  Touches: `astra_downloader/gui.py`, `scripts/extract_companion_strings.py`
  Acceptance: the runtime-assigned labels are built through `tr()` so the extractor finds them; the composed status lines take their word order from a translated template rather than concatenation; the German scenario asserts one of them.
  Complexity: M

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

## Research-Driven Additions — v2.5.0 pass (2026-08-06)

A second pass, run against shipped v2.5.0. It covered the four surfaces the
"Unaudited" section above admits were never audited — the self-update
transaction, the native-messaging bootstrap, the build/release gates and the
subscription scheduler — plus the GUI's UX and i18n surface, and measured the
app against the yt-dlp 2026.08.04 and ffmpeg N-123918 binaries it actually
provisions. Every item traces to a finding in `RESEARCH.md`.

Notes on existing items above — read these before starting them:

- *Light-theme behaviour* — three additions. (a) The non-client frame is never
  themed: `DwmSetWindowAttribute` / `DWMWA_USE_IMMERSIVE_DARK_MODE` appears
  nowhere in the repo, so a Light-mode system already renders a white title bar
  over the `#0a0d12` body **today**. (b) `make_line_icon` bakes stroke
  `#aab2bd` into a raster `QPixmap` (`gui.py:196`), so every nav, tool and
  empty-state glyph is a pre-rendered dark bitmap — a light theme re-renders
  icons, it does not swap CSS. (c) The pinned Qt 6.11 already exposes
  `QStyleHints.colorScheme()`, `setColorScheme()`, `colorSchemeChanged` and the
  `windows11` widget style (probed on this machine 2026-08-06), so following
  the system scheme is first-party API, and setting it also fixes the seven
  native `QFileDialog` surfaces. Qt 6.10 additionally gave `windows11`/`fusion`
  automatic high-contrast support, which a fully custom stylesheet forfeits —
  worth deciding deliberately. `scripts/render-companion-gui.py` has no theme
  axis; its 23 scenarios roughly double.
- *Package for winget* — the open question is answered. `InstallerType:
  portable` is current in the live 1.12.0 manifest schema, and the signing
  requirement applies to MSIX only. The existence proof is yt-dlp's own
  manifest: portable, unsigned GitHub-release exes, with
  `Dependencies.PackageDependencies: [DenoLand.Deno, yt-dlp.FFmpeg]` — copy
  that shape. Two further constraints: winget applies Mark-of-the-Web via
  `IAttachmentExecute` and silently halts unsigned `.exe` *installer* types, so
  portable is the only viable route; and Scoop's main bucket excludes GUI apps
  outright, so that channel needs a self-hosted bucket using `persist` to keep
  settings across upgrades. The real blocker is inside this repo:
  `ensure_installed_executable` (`astra_downloader.py:2590-2619`) copies the
  running exe into `%LOCALAPPDATA%` on every frozen launch, so a
  winget-managed copy forks into a second install that `winget uninstall`
  cannot remove. Fix that first — it is also a P0 below.
- *Give `subscriptions.py` a real test surface* — the scheduler defects filed
  below are what that missing coverage is hiding; the lifecycle tests should
  assert against them specifically.
- *Close the highest-risk test gaps* — add `ensure_installed_executable`,
  `read_last_installed_update_sha256` and `reserve_archive`'s status gate; each
  is a P0/P1 below whose current coverage asserts shape, not outcome.
- *Site profiles selected by URL pattern* — still the genuine leapfrog. Checked
  again 2026-08-06 against the field's fastest-growing new entrant (Youwee,
  1,378 stars since 2026-01-18): it has a plugin store and workflow
  automation but no per-site rules either. YTPTube's "cookie override via
  conditions" (v2.6.2) is the closest prior art and is worth reading before
  designing this.

### P0

- [ ] P0 — Give a failed download somewhere to live
  Why: A download that fails leaves no trace anywhere in the product after five minutes. Nothing can answer "what failed overnight?", which is the question a queue-based downloader exists to answer.
  Evidence: measured 2026-08-06. `history.add` is called only inside `if dl.status == "complete":` (`download.py:3087-3091`), so failures never reach history. `cleanup_old` deletes any terminal download 5 minutes after it finishes (`download.py:3835-3842`), driven by the 60 s timer at `gui.py:1177-1179`. The Download page shows `recent[:8]` (`gui.py:3935`). A non-retryable failure gets `action = "none"` (`gui.py:3701-3713`) and the context menu is gated on `recent and dl.status == "complete"` (`gui.py:3790-3798`), so it offers no retry, no copy-link and no copy-error. The same root cause makes the History status filter inert: it offers only "All statuses" and "Complete" (`gui.py:2058-2061`) while `query_history_entries` defaults a missing status to `"complete"` (`config.py:1227`), so both selections return identical rows.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`, `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: terminal downloads of every status reach history carrying `errorCode` and error text; the status filter offers the statuses that now exist and changes the result set; a failed row exposes retry (when retryable), copy link and copy error; the 5-minute eviction no longer destroys the only record of a failure.
  Complexity: M

- [ ] P0 — Route the self-relocating exe copy through the verified-update transaction
  Why: One path writes the managed `AstraDownloader.exe` with no digest check, no version comparison, no backup and no rollback — so running an older release from Downloads silently downgrades the install, and a short write leaves a successfully-replaced corrupt binary. It is also the blocker for winget packaging.
  Evidence: `ensure_installed_executable` (`astra_downloader.py:2590-2619`) does `shutil.copy2` into a temp then `os.replace`, on every frozen launch from any other path, reached from `ensure_system_integrations` (`:4156`) **before** the single-instance guard (`:4162`). The repo already owns the correct primitive: `atomic_copy_verified` (`:770-799`) hashes the source, copies, fsyncs, re-hashes, then replaces — and its docstring exists precisely because "a normal `copy2` can leave a truncated destination". `COMPANION_ROLLBACK_FILENAME` is never touched here.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: the copy goes through `atomic_copy_verified`; an older running exe does not overwrite a newer managed one without an explicit user action; a failed copy leaves the previous managed exe intact; the test asserts the file on disk, not the call shape.
  Complexity: S

- [ ] P0 — Produce the SHA-256 sidecar the updater and the README both depend on
  Why: Self-update fails closed when `AstraDownloader.exe.sha256` is missing from a release, and nothing in this repository generates it. Any release shipped without a hand-made sidecar breaks updating for every installed client, and the README tells users to verify against a file the build does not emit.
  Evidence: `COMPANION_UPDATE_SHA256_URL` (`astra_downloader.py:344`) is the only reference to that filename in the source, and it is a read. `fetch_expected_sha256` returns `None` on any non-200 (`:997`), producing `error_code: 'sha256-sidecar-missing'` (`:2379`). `build.py` writes the digest only *inside* `build/companion-build-metadata.json` (`:283`). `scripts/stage-companion-release.js:117` instructs the operator to run `npm run release:manifest -- --require-companion`, which does not exist in `package.json` (nor does `build:userscript`, referenced at `:69`). `CLAUDE.md:35` and `README.md:74` both assert the sidecar exists. On this machine the sidecar in the live install does not match the exe beside it (`f70869c1…` vs `5f6db0e3…`) — what a hand-maintained file looks like once it drifts.
  Touches: `astra_downloader/build.py`, `scripts/stage-companion-release.js`, `package.json`, `astra_downloader/test_build.py`
  Acceptance: `py -3.12 astra_downloader/build.py` writes `AstraDownloader.exe.sha256` beside the exe from the bytes it just produced; the staging script verifies the pair and fails when they disagree; the instruction naming a non-existent npm script is corrected.
  Complexity: S

### P1

- [ ] P1 — Give the format probe the same identity the download gets
  Why: The quality picker probes a link and narrows the ladder to what it reports, but the probe runs logged-out, un-impersonated and un-proxied — so on exactly the links those features exist for, the picker states a ceiling the real download does not have, and disables the clip fields against a format table the download would never see.
  Evidence: `build_impersonate_args` appears once in the module, on the download path (`download.py:2739`); `--proxy` once, at `:2684`; `--cookies` at `:2697`. `_list_formats_gated` (`download.py:3424-3435`) and `_preview_playlist_gated` (`:3568-3582`) build argv with the extractor and JS-runtime args only. `_apply_format_probe` treats a successful probe as truth — it narrows the ladder (`gui.py:5164-5170`), asserts "This link tops out at {height}p" (`:5171-5174`) and drives `_apply_sabr_limits` (`:5163`). A probe *failure* is correctly ignored (`:5158-5161`); the damage comes from a probe that succeeds with a restricted answer.
  Touches: `astra_downloader/download.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: the format probe, the playlist preview and the subscription scan carry the stored sign-in for the target site, the configured impersonation target and the configured proxy, under the same `_cookie_jar_matches_target` scoping the download uses; a test asserts the probe argv for a signed-in domain.
  Complexity: M

- [ ] P1 — Stop hardcoding the YouTube client chain
  Why: The token-exempt fallback names a 2026-era client list that yt-dlp has since moved past, so the app now overrides its own dependency's better default and cannot benefit from an extractor fix without a code change.
  Evidence: `build_youtube_extractor_args` emits the literal `youtube:player_client=tv,web_embedded,android_vr` (`health.py:303`). Measured against the provisioned nightly (2026.08.04.234419) on 2026-08-06: with no `player_client` override the extractor resolved via **`visionos` then `android_vr`** and selected `401+251` with no JS challenge at all; with Astra's hardcoded chain it fetched the tv client config and player, ran a Deno JS challenge, emitted the SABR-only skip warning, and selected the same `401+251`. `visionos` does not appear anywhere in `astra_downloader/`. Upstream, `web_safari` was replaced by `web` across the YouTube defaults and `web_embedded` was replaced by `tv_downgraded` as the age-restricted fallback (yt-dlp PR #17261, which closed eight `web_safari` breakage issues at once).
  Touches: `astra_downloader/health.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: the no-provider path expresses a *subtraction from* yt-dlp's default (the `default,-<client>` syntax) rather than a fixed list, or at minimum adds `visionos` at the head; a test pins the emitted argv and a comment records the date the chain was last measured, so the next drift is visible.
  Complexity: S

- [ ] P1 — Stop the yt-dlp updater retrying on every idle queue
  Why: The 12-hour throttle marker is written only on success, so a persistently failing update — blocked proxy, AV write-lock — re-runs after every single download, forever.
  Evidence: `mark_ytdlp_update_check` has exactly two call sites (`astra_downloader.py:1702`, `:1756`), both on success paths. Every failure return in `_run_ytdlp_self_update` skips it: `active-version-unverified` (`:1628`), `staging-failed` (`:1637`), `update-timeout` (`:1665`), `update-launch-failed` (`:1672`), `update-command-failed` (`:1686`), `staged-version-unverified` (`:1695`). `should_check_ytdlp_update` (`:1573`) therefore stays true and `maybe_refresh_ytdlp` fires on every drain to idle (`download.py:3390`). Each attempt runs `atomic_copy_verified` over the ~16 MB binary (three passes) plus a 120 s-timeout subprocess.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: a failed update also records an attempt, with a shorter backoff than the success interval rather than none; a test asserts a second attempt is refused immediately after a failure.
  Complexity: S

- [ ] P1 — Bound the retries a subscription spends on a candidate it cannot download
  Why: An archive entry that reaches `failed` is not in the set that blocks re-reservation, and nothing counts attempts or backs off. One members-only or geo-blocked video in a watched channel makes the app spawn the same doomed yt-dlp job every 5 minutes, unattended, for as long as the subscription exists — the realistic outcome is rate-limiting from the extractor host.
  Evidence: `reserve_archive` refuses only `{"reserved", "queued", "complete"}` (`subscriptions.py:534`), while both failure paths write `"failed"` (`release_archive` `:563-570`, `mark_download`/`handle_download_completed` `:832-859`, `:882-888`). `SUBSCRIPTION_MIN_INTERVAL_MINUTES = 5` (`:38`) and the scheduler runs unattended (`:758-766`). No `attempts` field exists on an archive entry anywhere in the module. Retrying a *transient* failure is the intended behaviour — the defect is the missing cap, not the retry.
  Touches: `astra_downloader/subscriptions.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: an archive entry counts attempts and applies increasing backoff; after a bounded number it stops re-enqueueing and the subscription row names the item that gave up and why; a manual rescan clears the count.
  Complexity: M

- [ ] P1 — Make the ffmpeg version floor apply to the build the bootstrap installs
  Why: The exact `8.1.2` floor was added as a security control and cannot fire against any install this app produces — the bootstrap fetches a master snapshot, and snapshot builds are deliberately exempt. `SECURITY.md` invites reports about a known-vulnerable pin while the check is structurally unable to detect one.
  Evidence: `FFMPEG_URL` is `.../yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip` (`astra_downloader.py:312`), which always reports `N-<build>-g<commit>-<date>`. `parse_ffmpeg_major` matches `n?(\d+)\.` (`health.py:307-317`) and returns `None` for that shape by design (`health.py:560-562`), so `check()` short-circuits to `majorVersion: None, current: None` before `_FFMPEG_MIN_VERSION` (`astra_downloader.py:1460`) is consulted. Measured on this machine 2026-08-06: the provisioned binary reports `N-123918-gf7ca6f7481-20260411`, and `ffmpeg -decoders | grep magicyuv` returns the decoder — the detection command from CVE-2026-8461, one of the CVEs FFmpeg 8.1.2 fixes.
  Touches: `astra_downloader/health.py`, `astra_downloader/astra_downloader.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: a snapshot build is compared on the build date embedded in its version string against a dated floor, so a provisioned ffmpeg older than that floor is reported stale and re-fetched; the readiness row states which of the two comparisons it made.
  Complexity: S

- [ ] P1 — Make the native-messaging allowlist revocable, and keep it out of settings bundles
  Why: Clearing the configured extension IDs revokes nothing, and the same setting rides in an exported bundle — so an imported bundle can name an attacker's extension ID and hand it the ServerToken, which is full control of the local download API.
  Evidence: `register_native_messaging_hosts` returns early when both ID lists are empty (`astra_downloader.py:2913-2915`) and writes only under `if chrome_ids:` / `if firefox_ids:` (`:2918-2933`) — there is no delete path, so the manifest and its `HKCU\...\NativeMessagingHosts\...` pointer survive; removal happens only in `run_uninstall` (`:3502-3503`). The host serves `get-token` to an allowed extension (`:4026-4034`). `BUNDLE_EXCLUDED_SETTINGS` (`config.py:829-833`) excludes `ServerToken` and `LegacyHealthTokenOrigins` with a written rationale, but not `NativeChromeExtensionIds`, which also feeds `legacy_health_token_origin_allowlist` (`astra_downloader.py:2883`).
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/config.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: clearing or narrowing the ID list deletes the corresponding manifest and registry value on the next launch; both native-extension-ID settings join `BUNDLE_EXCLUDED_SETTINGS` and an import reports that they were not carried.
  Complexity: S

- [ ] P1 — Stop probing yt-dlp synchronously before the first frame
  Why: The window blocks on a yt-dlp subprocess during construction — the exact thing this file documents itself as deliberately deferring in two other places.
  Evidence: `_build_settings` calls `probe_impersonate_targets()` inline at `gui.py:3179`, and `_build_settings` runs from `__init__` at `gui.py:1137`. The probe shells out with a 20 s timeout (`astra_downloader.py:1076-1080`). Measured 2026-08-06: `yt-dlp --list-impersonate-targets` takes 1.7–1.9 s warm, so every cold launch shows a blank window for that long, bounded at 20 s if the binary is being scanned or is damaged. Contrast the comments at `gui.py:1201-1208` ("Let the first window frame render before probing external tools") and `gui.py:1655-1659` ("never probe yt-dlp --version synchronously here").
  Touches: `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: the impersonation combo is built with the configured value plus a pending marker and populated from the existing deferred readiness worker; a test asserts no yt-dlp spawn occurs during window construction.
  Complexity: S

### P2

- [ ] P2 — Back off per host, not per download
  Why: The taxonomy already classifies HTTP 429, but recovery is per-download and unquantified — so a rate-limited site keeps its downloads cycling through the same limit while the rest of the queue waits behind them, and the advice is prose rather than a wait.
  Evidence: retries are per-`Download` (`DownloadRetries` → `--retries`/`--fragment-retries`, `download.py:2611-2612`) and `DOWNLOAD_FAILURE_RECOVERY` carries `error`/`advice`/`next_action` strings with no duration field (`download.py:78-183`). Nothing keys any state by host. The model to copy is JDownloader, whose plugins raise a temporarily-unavailable status carrying an explicit wait duration and disable that host after N failures rather than stalling the queue; TubeArchivist's companion pattern is a randomised ±50% jitter on its request sleep, because a fixed sleep is itself a fingerprint (the app currently offers a fixed `--sleep-interval` plus an optional max, `download.py:2673-2681`).
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: a 429 or throttle failure records a retry-after per registrable domain; other hosts keep downloading; the card shows a countdown rather than a static message; the existing pacing settings gain a jitter option.
  Complexity: M

- [ ] P2 — Let a stored sign-in be tested
  Why: A cookie jar's only feedback is a download failing hours later, and the app already knows enough to check it directly. This is the answer to the most common failure class in the whole field.
  Evidence: the Sign-ins page shows site, source, count and expiry (`gui.py:2364-2426`) and nothing exercises a jar. `describe_browser_cookie_failure` (`download.py:789-796`) already explains Chrome/Edge 127+ App-Bound Encryption *after* an import fails, but nothing validates a jar that imported cleanly and has since been invalidated server-side. Cookie diagnosis — not cookie import — is the recurring complaint across Parabolic (#1755, #1835, #1753) and ytDownloader (#433). TubeArchivist's answer is a Validate button whose check is concrete and falsifiable: can yt-dlp reach a private, sign-in-only resource. yt-dlp 2026.07 also reworked the Instagram extractor to detect invalidated cookies specifically, which is a new classifiable failure.
  Touches: `astra_downloader/gui.py`, `astra_downloader/download.py`
  Acceptance: each sign-in row has a Test action that runs a bounded, metadata-only yt-dlp probe against a sign-in-gated URL for that site and reports pass/fail in plain language on the page; a jar that fails is marked in the list, not silently kept.
  Complexity: M

- [ ] P2 — Translate the strings that never reach `gui.py`
  Why: The text a user reads at the moment they need help is the one category that never translates. Different mechanism from the existing "strings the extractor cannot see" item — those are runtime `setText` calls *inside* `gui.py`; these live in modules the extractor does not read at all, and they include every failure explanation and every screen-reader label.
  Evidence: `scripts/extract_companion_strings.py:32-34` scans `astra_downloader/gui.py` only. `DOWNLOAD_FAILURE_RECOVERY` is 14 codes × `error`/`advice`/`next_action` as plain literals in `download.py:78-183`, rendered raw at `gui.py:3780-3783` and `:3880-3885`; `SABR_LIMITED_NOTICE` (`download.py:1186-1189`) and `MANAGED_BINARY_ANTIVIRUS_ADVICE` (`health.py:143-146`) have the same shape. Counted in `gui.py` on 2026-08-06: 30 `setToolTip` calls of which 1 is wrapped in `tr()`, and 88 `setAccessibleName` calls of which 2 are — so every screen-reader label is English in 10 of the 11 advertised locales.
  Touches: `astra_downloader/download.py`, `astra_downloader/health.py`, `astra_downloader/gui.py`, `scripts/extract_companion_strings.py`
  Acceptance: the extractor reads every module owning user-facing text; failure explanations, tooltips and accessible names are translatable and present in the catalogues; `npm run check` fails when one is added without reaching them.
  Complexity: M

- [ ] P2 — Repair the subscription store's recovery invariants
  Why: Three separate ways a subscription silently stops working, all in the unattended subsystem, all invisible because `enabled` stays true and `lastError` stays empty.
  Evidence: (a) `nextScanAt` is accepted verbatim with no upper clamp — `_finite_timestamp` rejects only non-finite and `<= 0` (`subscriptions.py:108-115`, `:316-318`) — so one wall-clock skew during `begin_scan`/`finish_scan` writes a far-future value and `due_subscriptions` (`:476-483`) never returns it again; the scheduler uses `time.time()` throughout with no monotonic fallback. (b) Load-time `_sanitize_archive` sorts by `updatedAt` alone (`:357-358`) while runtime `_trim_archive_locked` sorts by `(status_priority, updatedAt)` (`:664-676`), so a restart at the 20,000 bound can evict live `queued` entries; `reconcile_downloads` then skips them (`:613-614`) and the next scan re-downloads what is already on disk. (c) `activation-pending` is terminal — `_write_update_state` sets it before `schedule_companion_update_restart` (`astra_downloader.py:2479-2483`), nothing clears it, and `/health` serves it (`routes.py:390`); `log_update_recovery_status` (`:4153`) only logs.
  Touches: `astra_downloader/subscriptions.py`, `astra_downloader/astra_downloader.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: `nextScanAt` is clamped to `now + intervalMinutes*60` on load; load-time trimming uses the runtime status-priority ordering; a stale `activation-pending` older than the update timeout is reconciled at startup and stops being reported as pending.
  Complexity: M

- [ ] P2 — Make the gates able to fail
  Why: Three checks can report success without having checked anything, which is worse than not having them — the dependency audit in particular is a control `SECURITY.md` leans on.
  Evidence: (a) `scripts/audit-python-deps.js:136` defaults `dependencies` to `[]` on any shape mismatch and `:188` derives `status` purely from `actionableFindings.length`, so an empty or renamed pip-audit result reports `pass` having audited zero packages; `tool.exitCode` is recorded at `:194` and never compared, which also defeats the `--strict` flag passed at `:250`. (b) `buildCompanionInventory`/`inspectCompanionInventory` (`scripts/companion-license-inventory.js:267-434`) have exactly one consumer — `tests/companion-license-inventory.test.js`, on synthetic fixtures; no npm script runs them against a real staged artifact, and `:268-269` returns an empty inventory rather than erroring when the exe is absent. (c) `scripts/yt-dlp-smoke.py` runs `sys.executable -m yt_dlp`, exercising the pip pin `yt-dlp==2026.7.4`, while `YtDlpUpdateChannel` defaults to `nightly` (`config.py:209`) and the provisioned binary here is 2026.08.04.234419 — the gate proves a version no user runs. (d) `requirements.txt` carries reasoned floors for Flask, Werkzeug, Jinja2, requests and waitress but none for `urllib3`, which is transitive through requests and carries two 2026 High advisories (CVE-2026-44431/44432, cross-origin header forwarding on proxied redirects and a decompression-bomb bypass); the release graph pins 2.7.0 but a source install can resolve lower.
  Touches: `scripts/audit-python-deps.js`, `scripts/companion-license-inventory.js`, `scripts/yt-dlp-smoke.py`, `astra_downloader/requirements.txt`, `package.json`
  Acceptance: the audit asserts every requirement line appears in the result and fails on a zero-dependency report or a non-zero tool exit; the license inventory runs against a real staged artifact and errors on a missing one; the smoke gate can target the provisioned `yt-dlp.exe`; `urllib3` gains a reasoned floor.
  Complexity: M

- [ ] P2 — Give the user a way to read and send the log
  Why: Diagnostics collected after a restart contain nothing from the session that broke, there is no path from the UI to the log file, and the only export is a clipboard copy.
  Evidence: the log pane is one `QTextEdit` on the Browser extension page, capped at 300 blocks and reset to "Ready." on Clear (`gui.py:1530-1539`, `:5280-5281`). `LOG_PATH`/`CRASH_LOG_PATH` (`astra_downloader.py:303-304`) have no UI path — `_open_folder` (`gui.py:5294-5302`) falls back to `INSTALL_DIR` only when `DownloadPath` is empty, which never happens because it defaults to `~/Videos` (`config.py:129`). The diagnostics dialog (`gui.py:5237-5278`) copies to clipboard only, and its payload is `get_recent_log_entries()` — a `deque(maxlen=30)` (`astra_downloader.py:452-453`) never rehydrated from `server.log` at startup. There is no severity concept: `write_persistent_log` takes a bare message (`:595-618`) and no `LogLevel` key exists.
  Touches: `astra_downloader/gui.py`, `astra_downloader/astra_downloader.py`
  Acceptance: "Save diagnostics" writes the payload to a file the user chooses; the log pane offers "Reveal log file"; the ring is seeded from the tail of `server.log` at startup so a post-restart report is not empty.
  Complexity: S

- [ ] P2 — Remember the window, and let the destructive actions be taken back
  Why: A desktop app that reopens at 1120×760 on the Download page every launch reads as unfinished, and four irreversible actions have neither the confirmation this project bans nor the undo it prescribes instead.
  Evidence: `setMinimumSize(900, 620)` + `resize(1120, 760)` unconditionally at `gui.py:1009-1010`; no `saveGeometry`/`restoreGeometry`/`QSettings` anywhere in the app modules; `_nav_click("Download")` hardcoded at `gui.py:1139`. Without undo or confirmation: remove sign-in (`gui.py:4538-4547`, deletes the jar), remove subscription (`:2587-2596`), import a settings bundle (`self.config.update(bundle["settings"])` at `:4322`, with `describe_bundle_changes` computed at `:4320` but reported only at `:4346-4354` — after the write), and `closeEvent` → `dl_manager.cancel_all()` (`:5504`), which with `CloseToTray` off kills every in-flight download with no indication any were running. History clear is the one that does it right (`gui.py:2040-2044`, `:4498-4517`), though its snapshot is session-only.
  Touches: `astra_downloader/gui.py`, `astra_downloader/config.py`
  Acceptance: window geometry, maximised state and last page persist; sign-in and subscription removal gain the same undo affordance history clear has; a settings import writes a restorable snapshot first; closing with downloads running says how many will be cancelled before doing it.
  Complexity: M

- [ ] P2 — Make the Settings page navigable
  Why: 66 interactive controls in one 811-line method, with no search, no reset, and the most-wanted setting filed under the wrong heading.
  Evidence: `_build_settings` is `gui.py:2598-3408`; 44 named `cfg_*` controls plus 10 SponsorBlock category boxes (`:2843-2856`) and 12 subtitle-language boxes (`:2789-2800`), with Performance alone holding 16 (`:2956-3229`). No filter field on the page, and no `Reset`/`Restore default` anywhere in `gui.py` — `DEFAULT_CONFIG` is read only as an import fallback (`:4217`), so a user who breaks `OutputTemplate` has no way back. `cfg_language` sits in the "Tray behavior" group (`:3234-3236`) with its restart requirement only in a tooltip (`:3257-3259`); Export/Import settings sit under "Maintenance" (`:3331-3346`).
  Touches: `astra_downloader/gui.py`
  Acceptance: a filter box narrows to matching controls and their group; every control has a per-field revert, or the page has a restore-defaults action that reports what changed; Language and Export/Import move to groups that name them.
  Complexity: M

- [ ] P2 — Resolve the download folder from the Windows known folder
  Why: `~/Videos` is assumed rather than resolved, so a user who has moved or redirected their Videos folder gets a stray directory beside their profile instead of their real one.
  Evidence: `str(Path.home() / "Videos")` is hardcoded at `config.py:129` and `:783`, `download.py:2177` and `:2185`, `gui.py:497` and `:2669`. No `SHGetKnownFolderPath`, `FOLDERID_Videos` or `KnownFolder` call appears anywhere in the repo.
  Touches: `astra_downloader/config.py`, `astra_downloader/astra_downloader.py`
  Acceptance: the default resolves `FOLDERID_Videos` and falls back to `~/Videos` only when the call fails; an existing configured path is never rewritten.
  Complexity: S

- [ ] P2 — Sign in with a username and password where cookies cannot reach
  Why: The Sign-ins page is cookies-only, and five of the seven browsers it offers are the ones that can no longer be read on Windows — so for a password-protected Vimeo link, or a site with no working cookie export, there is no path at all, even though yt-dlp has one.
  Evidence: none of `--username`, `--password`, `--video-password`, `--twofactor`, `--ap-mso` or `--client-certificate` appears anywhere in `astra_downloader/` (measured 2026-08-06 against the 276 long options the provisioned yt-dlp 2026.08.04 advertises). `SITE_LOGIN_BROWSERS` offers `brave, chrome, chromium, edge, firefox, opera, safari` (`download.py:391-392`) while `describe_browser_cookie_failure` (`:789-796`) already knows Chrome/Edge 127+ App-Bound Encryption makes five of those fail — but says so only after the attempt. Note two sites to exclude: yt-dlp removed Reddit and LinkedIn login support in 2026.07 as broken.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`, `astra_downloader/gui.py`
  Acceptance: a stored site sign-in can hold credentials as an alternative to a cookie jar, kept out of the log, the diagnostics payload, the API and the settings bundle exactly as cookie values are; `--video-password` is reachable for a single link; the browser list marks the Chromium entries as likely to fail before the user picks one.
  Complexity: M

- [ ] P2 — Download intermediates somewhere other than the destination folder
  Why: `.part` and `.f###` files are written into the user's Videos folder for the life of every download, where they are visible, get indexed, and get picked up by folder-syncing tools.
  Evidence: `--paths` never appears in `astra_downloader/`; `-o` is built as an absolute path (`download.py:2593`, `:2602`). Implementation gotcha for whoever takes this: yt-dlp's help states `--paths` "is ignored if `--output` is an absolute path", so this needs `-o` made relative and `--paths home:<dir> temp:<dir>` passed together — adding `--paths temp:` alongside the current absolute `-o` is a silent no-op. The v2.1.0 sweep (`_sweep_download_intermediates`) must keep running, because a failed run's `.part` is what `resume_partial` continues from.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`
  Acceptance: intermediates are written under a temp directory and only the finished file appears in the destination; resume across a restart still works; a setting can put them back beside the output for diagnosis.
  Complexity: M

- [ ] P2 — Refuse a download that cannot fit before starting it
  Why: Nothing checks free space anywhere, so a large download fails at the end rather than the beginning, and the ffmpeg bootstrap writes ~190 MB with no precheck either.
  Evidence: `shutil.disk_usage` appears nowhere in the repo. The storage notice added in v2.1.0 reports a write that has already failed. The format probe the app already runs for the quality picker returns per-format `filesize`/`filesize_approx`, so the estimate is in hand at the moment the user presses Download.
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: a download whose probed size exceeds free space on the destination volume is refused with a classified failure naming the shortfall; the dependency bootstrap checks space before fetching ffmpeg.
  Complexity: S

- [ ] P2 — Search and filter the Subscriptions and Sign-ins lists
  Why: History has search, status, format, date range, sort and pagination; the other two lists render every record in insertion order, up to 100 subscriptions and 50 sign-ins.
  Evidence: `_refresh_subscriptions` (`gui.py:2194-2272`) and `_refresh_site_logins` (`:2364-2426`) build rows straight from the store with no filter widget on either page — even though `_refresh_site_logins` already computes `expired`/`stored` per row (`:2397-2400`), which is the filter a user actually wants.
  Touches: `astra_downloader/gui.py`
  Acceptance: both pages carry a search box and the filters their data already supports — expired sign-ins, disabled or failing subscriptions — debounced the way History's is.
  Complexity: S

- [ ] P2 — Say when something is being fetched
  Why: Three surfaces do visible work with no indication that work is happening, one of them on the GUI thread.
  Evidence: `_start_server` (`gui.py:3511-3618`) walks the whole `PORT_FALLBACKS` list binding sockets (`:3532-3546`) and constructs the WSGI server (`:3584`) synchronously on the GUI thread, and `_update_server_ui` (`:3638`) is binary Running/Stopped with no "Starting". `_refresh_history` (`:4405-4476`) calls `history_mgr.load()` on the GUI thread then rebuilds up to 50 cards with no loading state — and no error branch, so an unreadable `history.json` renders the "No downloads yet" empty state, which reads as "you have downloaded nothing". `_scan_subscription` (`:2576-2585`) posts "queued" and returns; the row shows only `nextScanAt`. The format probe (`:5112-5146`) runs on a thread after a 700 ms debounce and silently rewrites the picker on return.
  Touches: `astra_downloader/gui.py`
  Acceptance: server start reports a starting state and does its socket work off the GUI thread; History distinguishes "empty" from "could not be read" and shows a loading state; a scanning subscription says so on its row; the picker indicates a probe in flight.
  Complexity: M

### P3

- [ ] P3 — Generate subtitles locally for a video that has none
  Why: The strongest differentiator currently available, and the plumbing is already installed. Every commercial rival paywalls AI transcription; among free tools only Youwee ships it, and it bundles a separate model stack to do so. Astra needs no new binary.
  Evidence: verified on this machine 2026-08-06. The ffmpeg the app provisions (`ffmpeg-master-latest-win64-gpl`, reporting `N-123918-gf7ca6f7481-20260411`) is configured `--enable-whisper` and exposes the `whisper` audio filter; `ffmpeg -h filter=whisper` lists `model`, `language` (default `auto`), `translate`, `format` (`text|srt|json`), `max_len`, `use_gpu` (default true) and VAD options. Run against a synthetic tone with a bogus model path it returns `whisper_init_from_file_with_params_no_state: failed to open` — whisper.cpp is linked, and only the GGML model file is missing. FFmpeg merged the filter in 8.0; models are MIT-licensed GGML files from `huggingface.co/ggerganov/whisper.cpp`. The previous pass rejected this believing the app bundled ffmpeg 7.x; that is no longer true, which is why it is filed rather than left rejected.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/config.py`, `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: a model is provisioned through the same size-floored, SHA-256-verified managed-binary path yt-dlp and ffmpeg use, with its own readiness row; a setting generates an SRT for a download whose chosen languages had no track; the run reports progress and can be cancelled; transcription never runs unasked. Measure wall-clock cost against a real 10-minute video on this hardware before picking a default model size — `use_gpu` defaults true but the shipped build has no CUDA, so CPU/Vulkan throughput is the open number.
  Complexity: L

- [ ] P3 — Publish a one-folder build beside the one-file exe
  Why: `--onefile` self-extracts at runtime, which is the behaviour Defender's heuristics score, and it is the single largest support burden for this class of program. A `--onedir` zip removes the extraction step entirely and costs one extra build target.
  Evidence: the documented mitigation ranking for PyInstaller false positives puts `--onedir` first, ahead of rebuilding the bootloader; winget's Mark-of-the-Web step via `IAttachmentExecute` also silently halts unsigned `.exe` *installer* types, which is a second reason the distributable should not be an installer. This contradicts the project's standing "single-file output" rule, so it is filed as an addition rather than a replacement: the one-file exe stays the headline download and the zip is the documented "flagged by antivirus?" fallback. Code signing remains permanently out of scope, so this and the published SHA-256 are the only levers available.
  Touches: `astra_downloader/build.py`, `scripts/stage-companion-release.js`, `README.md`
  Acceptance: `build.py` can emit a `--onedir` zip with its own SHA-256 sidecar alongside the one-file exe; the README names it as the antivirus fallback and states the tradeoff; the release staging gate verifies both artifacts.
  Complexity: M

- [ ] P3 — Stop deep-copying the whole subscription document on every archive mutation
  Why: Two full `deepcopy` passes over an up-to-20,000-entry archive plus a full JSON rewrite, per candidate, under the store lock, on the scheduler thread — so a 50-video scan does that 100+ times.
  Evidence: every mutating method takes `before = _copy(self._data)` (`subscriptions.py:103-105`, `:360-368`, `:415-419`, `:536-552`, `:654-662`) and `_save_locked` copies again for the writer. Cost is O(archive) per candidate. Note the sibling measurement already recorded in this file: `_refresh_subscriptions`' per-tick archive walk was measured at 3.88 ms and is explicitly *not* worth optimising — this is a different path and should be measured the same way, before and after.
  Touches: `astra_downloader/subscriptions.py`
  Acceptance: rollback state is captured per-entry rather than per-document; the measured cost of a 50-candidate scan at the 20,000-entry bound is recorded before and after.
  Complexity: M

- [ ] P3 — Three small correctness fixes in the update and archive paths
  Why: Each is a few lines, each produces a confusing outcome rather than a dangerous one, and none has a test.
  Evidence: (a) `_parse_sha256_sums` returns a single bare digest before consulting `target_asset` (`astra_downloader.py:977-979`), so a sidecar for a different asset is accepted and then fails verification with a mismatch rather than "wrong sidecar". (b) `subscription_archive_key` falls back to `url:<url>` and the key is cleaned at 430 chars (`subscriptions.py:181-189`, `:528`) while the URL is cleaned at 4096, so two long URLs sharing a 426-character prefix collide and the second video is treated as already archived. (c) `run_uninstall` deletes the protocol, uninstall and native-host keys but not `INTEGRATIONS_STAMP_KEY` (`astra_downloader.py:403-404`, `:3471-3477`), so an uninstall followed by a reinstall of the same version short-circuits `ensure_system_integrations` (`:2945-2947`) and silently skips the shortcuts, logon task and protocol handlers.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/subscriptions.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: each fixed with a test asserting the outcome — a mismatched sidecar is rejected as such, two long distinct URLs get distinct keys, and reinstalling the same version after an uninstall restores every integration.
  Complexity: S

- [ ] P3 — A first run that sets itself up before the user needs it
  Why: Dependency provisioning is reactive, so a fresh install shows a Download page whose readiness rows say Missing and whose paste box will fail — and the only thing that triggers setup is visiting the Browser extension page and pressing Start server, which is the page the product deliberately de-emphasises.
  Evidence: no `FirstRun`/`onboarding`/`welcome` key or symbol exists in the app modules. `_run_setup` (`gui.py:5533`) is reached only from `_start_server` when `managed_binary_usable` fails (`:3517-3521`) or from `_reinstall_ffmpeg` (`:4849`). `ensure_system_integrations` (`astra_downloader.py:4155`) runs only when frozen and is silent. The tray explainer fires on first close (`gui.py:5488-5495`), long after the icon appears. Broken dependency bootstrapping is the single most recurring complaint across the whole field — Parabolic has open "yt-dlp is not found after preview update" (#1884) and "Deno update error" (#1895) issues while its main branch has been quiet since 2026-06-29 — so doing this well is a competitive position, not only a polish item.
  Touches: `astra_downloader/gui.py`, `astra_downloader/astra_downloader.py`
  Acceptance: a first launch with missing managed binaries starts provisioning from the Download page and shows progress there; the download destination is confirmed once; the extension pairing step is reachable from the first run rather than only from the Browser extension page.
  Complexity: M
