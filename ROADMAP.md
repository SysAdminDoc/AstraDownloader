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
  cannot remove. Fix that before packaging.
- *Give `subscriptions.py` a real test surface* — the scheduler defects filed
  below are what that missing coverage is hiding; the lifecycle tests should
  assert against them specifically.
- *Close the highest-risk test gaps* — the relocation and update-state paths
  are now covered by outcome tests; `reserve_archive`'s status gate remains in
  the P1 work below.
- *Site profiles selected by URL pattern* — still the genuine leapfrog. Checked
  again 2026-08-06 against the field's fastest-growing new entrant (Youwee,
  1,378 stars since 2026-01-18): it has a plugin store and workflow
  automation but no per-site rules either. YTPTube's "cookie override via
  conditions" (v2.6.2) is the closest prior art and is worth reading before
  designing this.

### P1

### P2
