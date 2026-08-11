# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Actionable Items

- [ ] P2 — Build a light theme, including the surfaces that are already mixed
  Why: The product is dark-first by design, but nothing verifies what happens
  under a light Windows theme, and several surfaces already render light against
  the dark window today.
  Evidence: no theme key exists among the 72 `DEFAULT_CONFIG` keys and
  `STYLESHEET` is applied unconditionally at `astra_downloader.py:4643`, so this
  is "build a light theme", not "audit the existing one". Three details from
  earlier passes still hold, re-verified 2026-08-09: (a) `DwmSetWindowAttribute`
  / `DWMWA_USE_IMMERSIVE_DARK_MODE` appear **0 times** in the repo, so a Light
  system renders a white title bar over the `#0a0d12` body right now; (b)
  `make_line_icon` (`gui.py:189-204`) bakes stroke `#aab2bd` into a raster
  `QPixmap`, so every nav, tool and empty-state glyph is a pre-rendered dark
  bitmap — a light theme re-renders icons, it does not swap CSS; (c) the pinned
  Qt 6.11 exposes `QStyleHints.colorScheme()`, `setColorScheme()` and
  `colorSchemeChanged`, so following the system scheme is first-party API, and
  setting it also fixes the **8** native `QFileDialog` call sites (`gui.py:571`,
  2644, 3400, 5987, 6016, 6151, 7032, 7305) that follow the OS palette. Qt 6.10
  gave `windows11`/`fusion` automatic high-contrast support that a fully custom
  stylesheet forfeits — decide that deliberately.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`,
  `astra_downloader/config.py`, `scripts/render-companion-gui.py`
  Acceptance: a theme setting follows the system scheme by default; the title
  bar matches the body in both schemes; icons re-render per scheme; the render
  harness gains a theme axis.
  Complexity: L

- [ ] P0 — Show the subscription store's error instead of "you have none"
  Why: A user with an unreadable store is told their subscriptions do not exist
  and invited to re-add them — the opposite of this project's stated invariant
  that a failure names its cause and offers the fix.
  Evidence: `gui.py:2907` sets `Could not read subscriptions: {error}`; 44 lines
  later `gui.py:2952` unconditionally overwrites it with
  `0 configured · 0 archived · 0 queued`, and `:2957` renders the "No scheduled
  subscriptions" empty state. Reproduced with a store whose `snapshot()` raises.
  No test covers it. The same shape exists on Sign-ins: with `store is None`
  (`gui.py:3181`) the page renders "No stored sign-ins" with no message at all.
  Touches: `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: an unreadable subscription or sign-in store renders a distinct
  error state with a recovery action (open diagnostics / reveal the file) and
  never the empty state; tests drive a raising store for both pages.
  Complexity: S

- [ ] P0 — Keep proxy credentials out of the settings bundle, and name what an import changes
  Why: The bundle is designed to be shared between machines, and it currently
  carries credentials out and widens a filesystem write allow-list on the way in,
  behind a confirmation that reports only a count.
  Evidence: `BUNDLE_EXCLUDED_SETTINGS` (`config.py:1254-1264`) omits `Proxy`,
  `GeoVerificationProxy`, `SourceAddress`, `Xff` and `SiteProfiles`, and
  `normalize_proxy` (`:413-422`) returns the string verbatim, so
  `http://user:pass@host:3128` round-trips. The docstring at `:1276` excludes
  cookies precisely because "a bundle is … the kind of file that gets emailed
  around". On import, `ExtraOutputRoots` — which extends `allowed_output_roots`
  (`:1170-1180`), the allow-list gating where the loopback API may write — is
  applied with no GUI surface anywhere, and `gui.py:6077` reports only
  `Imported N changed settings`; the key names from `describe_bundle_changes`
  go to the log panel on a different page.
  Touches: `astra_downloader/config.py`, `astra_downloader/gui.py`
  Acceptance: credential-bearing and allow-list settings are excluded from export
  and ignored on import (or surfaced for explicit per-key confirmation); the
  import result names the settings it changed on the Settings page; tests pin the
  exclusion set against `DEFAULT_CONFIG` so a new key cannot be added silently.
  Complexity: M

- [ ] P1 — Make the license gate run the inspection it exists for
  Why: The gate that is supposed to enforce the license policy only asserts that
  the SBOM is non-empty, so 37 real policy issues ship green.
  Evidence: `scripts/check-companion-inventory.js:16-26` calls
  `buildCompanionInventory` and throws only when `components`/`dependencies` are
  empty. `inspectCompanionInventory`
  (`scripts/companion-license-inventory.js:371-436`) — unresolved SPDX,
  `decision !== 'approved'`, missing approval evidence, missing obligations,
  moving `latest` download URLs, unresolved download SHA-256 — is referenced only
  from `tests/companion-license-inventory.test.js`. Run against the real staged
  build it reports 37 issues, including PyQt6/PyQt6-Qt6 `decision=unresolved`,
  yt-dlp and Deno on moving `latest` targets, and an unresolved ffmpeg SHA-256.
  It also filters on an `astra:companion:inventory` tag that
  `resolvedPythonComponent` never sets, exempting 9 of 38 components. Note the
  irony worth resolving together: the rule it never runs forbids moving `latest`
  URLs, and the companion updater itself uses `releases/latest`.
  Touches: `scripts/check-companion-inventory.js`,
  `scripts/companion-license-inventory.js`, `astra_downloader/license-policy.json`
  Acceptance: `npm run check` fails on today's inventory; every component is in
  scope; each of the 37 issues is either resolved in the policy or fails the
  build; a test proves the gate fails on a planted unresolved component.
  Complexity: M

- [ ] P1 — Preflight the volume the download actually writes to, and sweep staging on every terminal state
  Why: The disk check passes while the system drive fills, and every non-complete
  download leaks a full-size staging directory that nothing ever removes.
  Evidence: staging defaults to `INSTALL_DIR/download-temp/<id>`
  (`download.py:3655-3679`, `KeepIntermediateFiles` defaults False at
  `config.py:219`) and is passed as `--paths temp:` (`download.py:3910`), but the
  only preflight is `check_download_disk_space(output_dir, estimate)`
  (`gui.py:2491-2498`). With `DownloadPath` on D: and `INSTALL_DIR` on C:, a 40 GB
  job passes and fills C:; the final `temp:`→`home:` move is then cross-volume,
  so it is a copy, not a rename. `_sweep_download_intermediates` is called only
  when `dl.status == "complete"` (`download.py:4432`), with no startup sweep, no
  age policy and no cap.
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: the preflight checks both the staging and output volumes and names
  which one is short; staging is swept on cancel and failure and on startup for
  ids no longer in the queue; a test covers a cancelled download leaving nothing
  behind.
  Complexity: M

- [ ] P1 — Give the companion updater a backoff, a rate limit, and a startup sweep
  Why: Each call re-downloads ~47 MB before it can discover it was unnecessary,
  nothing bounds the repeat rate, the scratch files are never cleaned, and a
  failed schedule leaves a status marker stuck for the session.
  Evidence: `POST /update` (`routes.py:1175-1209`) has no `RateLimiter` where six
  sibling routes do, and `d36bb69`'s backoff covers only the yt-dlp path
  (`should_check_ytdlp_update`, `astra_downloader.py:1793-1805`); the download at
  `:2620` precedes the digest-skew guard at `:2689`. The same anonymous
  `api.github.com` endpoint the updater polls has a 60/hour ceiling — the bug
  ytdlp-interface #360 reports. Scratch files up to
  `HELPER_DOWNLOAD_MAX_BYTES` = 500 MB land in `INSTALL_DIR` (`:929`, `:2618`,
  `:2298`, `:2333`) and only `remove_portable_state` ever removes any, and its
  `.AstraDownloader.` prefix test misses the double-dot `..AstraDownloader.update.
  ….download` temp. `activation-pending` is written at `:2732` **before**
  `schedule_companion_update_restart` at `:2737`, and the `except` at `:2759`
  never rewrites it, so `/health` reports it forever and
  `read_last_installed_update_sha256` returns `None`, disabling the skew guard;
  the staleness test at `:1707` diffs naive local wall-clock, so a backwards
  clock step keeps it fresh permanently.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/routes.py`
  While in here: `os.replace` is not a durable rename on Windows — CPython calls
  `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING)` with no `MOVEFILE_WRITE_THROUGH`,
  so the rename is atomic for visibility but unflushed. That is the right default
  for the 14 rebuildable-state sites, but the self-update stage
  (`astra_downloader.py:1967`) and the durable-state write (`:2480`) are the two
  that carry state worth not losing.
  Acceptance: `/update` is rate-limited and backs off after failure; the version
  check precedes the download; a failed schedule records a terminal state; a
  startup sweep removes orphaned update scratch files including the double-dot
  form; staleness uses a monotonic or UTC comparison; the two durability-
  sensitive replaces flush.
  Complexity: M

- [ ] P1 — Make subscription scans visible to the "is yt-dlp busy" guard
  Why: The auto-updater replaces a running executable and blames itself, and a
  self-update can orphan a scan whose cookie jar then survives on disk.
  Evidence: `active_count()` (`download.py:4738-4740`) returns
  `len(self._running_ids)`, and `probe_subscription_uploads`
  (`astra_downloader.py:611+`) spawns `yt-dlp.exe` from the scheduler thread
  without registering. So `maybe_auto_update_ytdlp` (`:2087`) sees "idle",
  `os.replace(stage_path, YTDLP_PATH)` (`:1967`) fails against the locked image,
  and `mark_ytdlp_update_attempt(succeeded=False)` burns the backoff while
  reporting "the active copy was retained". Separately,
  `schedule_companion_process_exit` calls `os._exit(0)` (`:2541`), skipping the
  probe's `identity_cleanup()` (`:652-654`) and leaving
  `.cookies.probe.<hex>.txt` — exported site sign-in cookies — which
  `cleanup_stale_cookie_jars` then skips because it ignores files younger than
  300 s (`download.py:1326`).
  Touches: `astra_downloader/download.py`,
  `astra_downloader/astra_downloader.py`, `astra_downloader/subscriptions.py`
  Acceptance: any spawned yt-dlp registers in one shared activity view; the
  updater refuses to swap while one is live; a startup sweep removes probe cookie
  jars regardless of age; tests cover the scan-active case.
  Complexity: M

- [ ] P1 — Make every setting signal "Unsaved changes"
  Why: 19 of 68 controls change silently, so edits are discarded with no feedback
  at any point, and the test that is supposed to guard this asserts source text.
  Evidence: the dirty-signal list at `gui.py:4728-4739` is hand-maintained and
  has drifted from `_SETTINGS_FORM_FIELDS` (`gui.py:5762-5821`). Measured by
  toggling each widget on the live window: `cfg_site_profiles`,
  `cfg_windows_filenames`, `cfg_keep_intermediates`, `cfg_write_info`,
  `cfg_write_description`, `cfg_write_thumbnail`, `cfg_split_chapters`,
  `cfg_live_from_start`, `cfg_wait_for_video` and all 10 SponsorBlock category
  checkboxes (`gui.py:4106-4131`) produce no status change. The only guard,
  `test_astra_downloader.py:1491`, asserts that the string
  `self._show_settings_status("Unsaved changes", "warning")` appears in the
  source — it passes regardless of wiring.
  Touches: `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: the dirty signal is derived from the form-field registry rather
  than a parallel list; a test toggles every registered control and asserts the
  status changes, so a new setting cannot be added without it.
  Complexity: M

- [ ] P1 — Stop the settings search from un-hiding deliberately hidden widgets
  Why: An "Undo import" button is visible from app start, before any import
  exists, and clicking it reports that there is nothing to undo.
  Evidence: `_build_settings` ends with `self._filter_settings("")`
  (`gui.py:4740`); with an empty query `_filter_settings` (`:1551-1572`) marks
  every item as matching and `_set_settings_item_visible` calls
  `setVisible(True)` down the subtree, undoing `btn_undo_settings_import.hide()`
  (`:4661`) and `cfg_port_session_hint.setVisible(False)` (`:3710`). Measured:
  the other three undo buttons are correctly hidden, this one is not, and the
  bug recurs after every search-then-clear cycle.
  Touches: `astra_downloader/gui.py`
  Acceptance: filtering never overrides a widget's own hidden state; a test
  asserts the undo button is hidden at construction and after clearing a search.
  Complexity: S

- [ ] P1 — Let a site profile satisfy a retry precondition
  Why: A profile that supplies exactly the workaround a refusal asks for cannot
  unblock the retry, so the user is told to set something in Settings that they
  already set in the profile.
  Evidence: `recovery_precondition` (`download.py:5306-5331`) reads
  `self.config` for `ForceIPVersion`, `ImpersonateTarget` and
  `build_network_workaround_args`, while `_effective_config_for_url`
  (`:2608-2616`) exists and is used at `:4002` and `:5015`; `dl` is in scope.
  `_check_site_login` (`:4949`) has the same scoping. A profile with
  `Xff: "DE"` therefore leaves a `geo-restricted` download permanently
  un-retryable even though the download itself would send `--xff DE`.
  Touches: `astra_downloader/download.py`
  Acceptance: preconditions are evaluated against the URL's effective config; a
  test covers a profile-supplied `Xff` unblocking a geo refusal.
  Complexity: S

- [ ] P1 — Make portable uninstall remove the state it claims to remove
  Why: It prints "Portable Astra Downloader state was removed" while leaving live
  session cookies on what is typically a removable medium.
  Evidence: `remove_portable_state` (`astra_downloader.py:3798-3839`) deletes
  only paths in a hand-written `known_paths` set. Not listed, therefore
  preserved: `site-logins/` (`SiteLoginStore`, `download.py:490`) — confirmed on
  this machine as `site-logins/index.json` plus a Netscape jar of live session
  cookies — `download-temp/`, transient `.cookies.*.txt` jars, rotated
  `server.log.1`/`crash.log.1`, and `*.corrupt-*` quarantine copies. This is the
  gate-that-enumerates-what-it-guards shape the repo has been bitten by before.
  Touches: `astra_downloader/astra_downloader.py`
  Acceptance: the sweep is derived from the set of app-owned paths rather than a
  literal list, or asserts completeness against it; a test plants a sign-in jar
  and a staging folder and proves both are gone.
  Complexity: S

- [ ] P1 — Tune the whisper invocation, and label the live-wait setting correctly
  Why: The shipped `queue=3` is simultaneously the slowest and the lowest-quality
  setting available, and a live-stream setting says the opposite of what it does.
  Evidence (measured on a 104.47 s speech sample, `tiny-q5_1`, `use_gpu=0`, this
  machine): `queue=3` → 13.75 s, 29 of 38 cues overlap the previous cue, 2 cues
  span >20 s; `queue=10` → 9.99 s, 7 overlapping; `queue=20` → **6.72 s**, 3
  overlapping, none runaway; `queue=30` → 8.40 s, 1 overlapping. `max_len=42`
  works on the same binary and is the standard readability knob. Real-time factor
  at `queue=20` is 0.064, so a one-hour video costs roughly 4 minutes of CPU —
  the number the earlier roadmap left open. Do **not** set `use_gpu=1`: it logs
  `Unsupported GPU: NVIDIA GeForce RTX 4070 SUPER` and runs 2.3× slower (17.50 s
  vs 7.62 s). Separately, `--wait-for-video` is documented by the shipped yt-dlp
  as "the minimum number of seconds (or range) to wait **between retries**", not
  a cap, while `gui.py:3968-3980`/`4072-4081` present it as "Wait for live video,
  0 disables waiting" with a seconds suffix; the resulting forever-wait never
  trips the 1800 s stall watchdog because the `[wait]` lines keep resetting
  activity, so it holds a concurrency slot until restart.
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`
  Finally, renumber the produced SRT: FFmpeg's filter prints
  `WhisperContext.index`, which is never initialised to 1
  (`libavfilter/af_whisper.c`), so **every cue list starts at 0** — observed in
  every sample generated here. FFmpeg and VLC both ignore the counter entirely,
  but stricter validators and some web players key on 1-based numbering, and a
  one-pass renumber on the sidecar is cheaper than arguing with upstream.
  Acceptance: `queue` and `max_len` are set from measured defaults (and exposed
  if a setting is warranted); the emitted SRT is 1-based; the live-wait control
  is relabelled as a retry interval and a bounded overall wait is enforced or the
  slot is released.
  Complexity: S

- [ ] P1 — Bound transcription cost and watch the process
  Why: Nothing limits how long transcription runs, how much CPU it takes, or how
  many run at once, and the stall watchdog is watching a process that has already
  exited.
  Evidence: `_run_local_subtitles` (`download.py:3681-3827`) spawns with only
  `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` — no priority class, no thread
  cap — and neither the stdout loop nor `proc.wait()` has a timeout. The stall
  watchdog closure binds `watched_proc=proc`, the yt-dlp process
  (`download.py:4114`). `MaxConcurrentDownloads` clamps to 10
  (`config.py:1440`), so up to ten CPU-saturating whisper processes can run on an
  interactive desktop. Progress is reported as a fixed 1-99% because "the filter
  does not expose the input duration"; it does not need to — the media duration
  is already known and `out_time_ms` tracks media position exactly (verified:
  final value 104469438 for a 104.469 s input). Note that key is **microseconds**
  despite its name.
  Touches: `astra_downloader/download.py`
  Acceptance: transcription runs below normal priority with a bounded overall
  timeout and its own watchdog; concurrent transcriptions are capped
  independently of download concurrency; progress shows real percent.
  Complexity: M

- [ ] P1 — Give the control borders a visible boundary
  Why: The prior pass measured this and it is unchanged; 28 controls currently
  have effectively no edge until hover or focus.
  Evidence: measured against the real `#0a0d12` background from `STYLESHEET`:
  `QPushButton` border `#343d49` = **1.77:1** (WCAG 1.4.11 floor is 3:1);
  `[secondary]` `#3a4451` = 1.97; `:disabled` `#232a33` = 1.34;
  `QCheckBox::indicator` `#485362` = 2.49; and `[class="ghost"]`
  (`astra_downloader.py:3380`, 28 uses in `gui.py`) sets
  `border-color: transparent` over a `#11161d` fill = **1.07:1**. `#516072`
  measures 3.03:1 against the same background. Text contrast and the focus ring
  already pass and need no change.
  Touches: `astra_downloader/astra_downloader.py`
  Acceptance: every non-text control boundary measures ≥3:1 against its own
  background, verified by a test that parses `STYLESHEET` rather than assuming
  the background.
  Complexity: S

- [ ] P1 — Fix the minimum-size layout the harness already captures
  Why: The app's own documented minimum window size renders overlapping,
  truncated controls, and the harness photographs it every run without asserting
  anything about it.
  Evidence: `build/companion-ui-smoke/reflow-900x620-hidpi-large-font.png`
  inspected at full resolution: the Download options row (`gui.py:2044-2105`)
  shows the profile combo painting outside its box, `Vi` for Video, `M` for MP4,
  `Be` for Best, `Save t` for Save to, no drop-down arrows, and the clip-range
  hint vertically clipped; measured widths are 170px for the profile combo and
  55px for the other four. This is the documented "a QLabel will not shrink below
  its text" class, re-introduced when the v2.6.0 profile combo joined the row.
  The scenario asserts only `window.size()` and `output.width()`
  (`render-companion-gui.py:601`, `:626`).
  Touches: `astra_downloader/gui.py`, `scripts/render-companion-gui.py`
  Acceptance: the row wraps or elides with all labels legible at 900x620 with a
  large font; the scenario asserts something about the row rather than the image
  size.
  Complexity: M

- [ ] P1 — Make undo durable, or say that it is not
  Why: Every undo in the app dies with the process and nothing tells the user, in
  a product whose stated convention is undo instead of confirmation.
  Evidence: clear-history (`gui.py:6297`/`6316`), remove-sign-in (`:3443`/`:3473`),
  remove-subscription (`:3612`/`:3645`) and bundle-import (`:6014`/`:6099`) all
  keep their snapshot in memory only; `History.clear()` (`config.py:1859`) writes
  `[]` straight over the file with no on-disk backup, and the confirmation text
  says only "Downloaded files were not removed". `_restore_default_settings`
  (`gui.py:5872`) overwrites 57 keys plus the SponsorBlock categories and can
  restart the server with **no undo at all**.
  For anything that removes a *file*, the shell already offers durable undo:
  `IFileOperation::DeleteItem` with `FOFX_RECYCLEONDELETE | FOFX_ADDUNDORECORD`
  sends it to the Recycle Bin and registers a shell undo record, no snapshot
  needed. Pass `FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT` and a NULL owner
  window or the shell shows its own confirmation dialog, which this project bans.
  Touches: `astra_downloader/gui.py`, `astra_downloader/config.py`,
  `astra_downloader/astra_downloader.py`
  Acceptance: destructive actions write a recoverable snapshot beside the data
  (as sign-in removal already does) so undo survives a restart, or the
  confirmation states the undo window explicitly; file removals go to the
  Recycle Bin; Restore defaults gains an undo.
  Complexity: M

- [ ] P2 — Decide what the language picker is allowed to advertise
  Why: Eleven locales are offered and nine render as English, which is a worse
  experience than offering two, and the gap has more than doubled.
  Evidence: `py -3.12 scripts/build-companion-translations.py` on 2026-08-09:
  `de` 564/564, and `ar, es, fr, it, ja, ko, pt_BR, ru, zh_CN` all **5/564**.
  The catalogue grew 219 → 564 strings since the last pass, so
  `Roadmap_Blocked.md`'s "214 strings per locale" is now 559. All eleven are
  advertised via `SUPPORTED_LOCALES` (`i18n.py:10-23`) and selectable at
  `gui.py:4527-4560`; Arabic at 5/564 means the RTL scenario ships mirrored
  chrome around entirely English copy. The coverage gate checks declaration only,
  by design, so `npm run check` is green at 0.9%.
  Touches: `astra_downloader/i18n.py`, `astra_downloader/gui.py`,
  `scripts/check-companion-translations.py`, `Roadmap_Blocked.md`
  Acceptance: the picker lists only locales above a stated coverage threshold (or
  marks the others as partial), and the gate enforces that threshold rather than
  mere declaration.
  Complexity: S

- [ ] P2 — Reach the strings the extractor cannot see
  Why: The project knows about three History column headers; it is 57 sites,
  including the entire tray menu and the only modal's title.
  Evidence: **32 bare literals** and **25 f-strings** reach user-visible setters
  and never enter a catalogue. Worst offenders, all `gui.py`: the tray menu
  `Show Astra Downloader` / `Open Downloads Folder` / `Quit Astra Downloader`
  (`:1310-1317`); `setWindowTitle("Review Diagnostics")` (`:7260`); the tray
  toast (`:7406`); the History headers `Format`/`Quality`/`Duration`/`Saved` and
  `Pending`/`Recent activity`, built by a loop-fed `make_label` (`:2786-2790`,
  `:5507-5509`) and confirmed absent from the catalogue; every filter combo's
  items (`:2862-2865`, `:3134-3137`, `:4499-4501`); `Search title or filename`
  (`:2705`); and the subscription/first-run sentences at `:3544`, `:4841`,
  `:4852`, `:4873`.
  Touches: `astra_downloader/gui.py`,
  `scripts/extract_companion_strings.py`
  Acceptance: user-visible strings are constructed so the extractor can see them
  (or the extractor learns the loop and f-string forms); the catalogue count
  rises to include them; the gate fails when a new one is added.
  Complexity: M

- [ ] P2 — Close the render harness's blind spots
  Why: The harness is the project's main UI safety net and it cannot see focus,
  scale, most locales, or several of the states this pass found broken.
  Evidence: 27 scenarios, exit 0. `select_page` calls `clearFocus()`
  (`render-companion-gui.py:192-193`), so **no capture ever contains a focus
  ring** — the exact thing fixed twice for cascade bugs. `QT_SCALE_FACTOR=2` is
  forced for every scenario (`:69`), so 1x and this machine's real 1.25x are
  never rendered. Only two window sizes and two locales (`de`, `ar`); eight
  locales never rendered and no CJK glyph-width check exists.
  `subscriptions-empty` is misnamed — it asserts `{"Astra channel"}` (`:665`) and
  the PNG shows one populated row, so the real empty state is never rendered.
  Uncovered: Sign-ins beyond one scenario, subscription error/filter-empty/
  disabled rows, History `No matching downloads` and pagination, the Download
  quarantine panel (`gui.py:2199`), paused intake, queue-full, format-probe
  in-flight, settings search active, invalid site-profiles JSON.
  Touches: `scripts/render-companion-gui.py`
  Acceptance: at least one scenario per page renders with a focused control; a 1x
  and a 1.25x scenario exist; the misnamed scenario is corrected and a genuine
  empty state added; the listed uncovered states are captured.
  Complexity: M

- [ ] P2 — Make `py -3.12 -m pytest` able to report its own result
  Why: The default invocation prints a traceback instead of a pass count while
  exiting 0, so a human or an agent reading the tail cannot tell green from red.
  Evidence: pytest's tmpdir teardown raises
  `PermissionError: [WinError 5] Access is denied: '…\pytest-of-…\pytest-current'`
  in `pytest_sessionfinish`, destroying the summary. With
  `--basetemp=<scratch>` the same suite prints `829 passed, 445 subtests passed
  in 52.61s` and exits 0. The stale `pytest-of-…` tree on this machine dates to
  2026-08-03.
  Touches: `pytest.ini`
  Acceptance: `py -3.12 -m pytest` prints its summary line with no traceback;
  `README.md`'s test count is verifiable from a run.
  Complexity: S

- [ ] P2 — Bring the winget manifest under the version gate
  Why: The gate reports that every version source agrees while the manifest
  declares an older version and points at a URL that does not resolve.
  Evidence: `scripts/check-versions.js:33-41` enumerates package.json,
  `APP_VERSION`, the README badge and the CHANGELOG heading, and omits
  `packaging/winget/manifests/s/SysAdminDoc/AstraDownloader/2.5.0/…installer.yaml`,
  which declares `PackageVersion: 2.5.0` and
  `InstallerUrl: …/download/v2.5.0/AstraDownloader.exe`. `npm run check:versions`
  prints "4 sources agree at v2.6.0". Depends on the release item above for a
  real URL and checksum. Keep the manifest at schema **1.12.0** when submitting:
  1.28.0 exists but the community-repo PR template still requires 1.12
  conformance, and the delta is only `DesiredStateConfiguration` plus
  pipeline-populated `Icons`. `InstallerType: portable` is unchanged in 2026, and
  there is still no unsigned-app attestation mechanism — `SignatureSha256` is
  MSIX-only.
  Touches: `scripts/check-versions.js`, `packaging/winget/manifests/`
  Acceptance: the manifest version and installer URL are gate-checked against
  `APP_VERSION`, and the directory is renamed on a bump.
  Complexity: S

- [ ] P2 — Tie the two release artifacts together
  Why: A v2.6.0 exe can be staged and published beside a v2.5.0 fallback zip with
  every gate green, and the published SBOM can describe a build that was never
  shipped.
  Evidence: `stage-companion-release.js:235-283` binds the exe to
  `companion-build-metadata.json` by size and digest but validates the onedir zip
  only structurally, with no version or provenance comparison. `build.py` copies
  the one-file exe to the repo root at `:491`, then runs the onedir PyInstaller
  pass at `:493`, then writes metadata and the sidecar at `:497-498`, and
  `clean()` (`:366-370`) never removes the root artifacts — so any failure in
  between leaves a new exe beside the previous release's sidecar and zip.
  `write_build_metadata` reads `astra_downloader/build/AstraDownloader/
  Analysis-00.toc` (`:292`), which the onedir run (`--clean`) has already
  overwritten, while hashing the one-file exe; the `embedded`/`build` scope
  decision that drives the SBOM is therefore computed from the wrong graph. No
  metadata, SBOM or license inventory is produced for the zip at all.
  Touches: `astra_downloader/build.py`, `scripts/stage-companion-release.js`
  Acceptance: both artifacts carry build metadata naming the same version and
  build; staging fails when they disagree; the root artifacts are cleaned before
  a build; the one-file metadata is captured from the one-file analysis.
  Complexity: M

- [ ] P2 — Make History a record worth keeping
  Why: The download record is silently truncated at 500 entries, and "have I
  already got this?" is the one thing three of five commercial rivals paywall.
  Evidence: `HistoryStore` is constructed with `limit=500`
  (`astra_downloader.py:3528-3537`) and `add()` writes `data[-self._limit:]`
  (`config.py:1857`) with no notice anywhere in the UI; the subscription archive
  is a separate 20,000-entry store. 4K Video Downloader Plus, Stacher and Downie
  all paywall a library/history surface, and Open Video Downloader #784 and
  Pinchflat #408 (17 reactions, the field's highest-reacted unbuilt request) are
  the same need. `RESEARCH.md` answers the standing open question: build it as an
  upgrade to History, not a seventh page.
  Touches: `astra_downloader/config.py`, `astra_downloader/gui.py`
  Acceptance: the cap is configurable and its effect is visible, or history moves
  to a store that does not need one; History answers "do I already have this
  URL" across downloads and the subscription archive.
  Complexity: L

- [ ] P2 — Write media-server sidecars
  Why: The audience that wants this is currently unserved and no desktop GUI in
  the field does it, so it is available as a differentiator rather than parity.
  Evidence: six open Pinchflat issues ask for NFO customisation, plain-date NFO,
  Plex API and Sonarr-style post-download moves, and that project has been paused
  since 2025-09-26 (#800, 255 reactions), stranding its users. `ytdl-sub` is the
  working reference for the Kodi/Jellyfin/Emby layout; Jellyfin documents the
  schema (`<filename>.nfo` per item, `tvshow.nfo`/`season.nfo` per folder,
  provider-id tags, local NFO wins over remote providers). **Plex now reads the
  same format natively** — the Plex NFO Agent requires PMS ≥ 1.43.1 and is
  described as compliant with the Kodi/XBMC NFO format — so one output layout is
  consumable by Kodi, Jellyfin, Emby *and* Plex with no post-processing for the
  first time. Two details that decide whether it works: `<uniqueid type="…"
  default="true">` is what keeps watch state stable across rescans, and a
  YouTube channel must be a **TV library + Plex NFO Series agent**, because the
  "Personal Media Shows" agent explicitly ignores the title portion of the
  filename. The app already writes info-JSON, description and thumbnail sidecars
  behind opt-in switches (`config.py:210-215`), and yt-dlp's `--embed-metadata`
  already maps `show`/`season_number`/`episode_id`/`episode_sort`, so a
  `--parse-metadata` mapping of channel→series gets a TV-shaped file for free.
  Touches: `astra_downloader/download.py`, `astra_downloader/config.py`,
  `astra_downloader/gui.py`
  Acceptance: an opt-in setting writes a Jellyfin/Kodi-valid `.nfo` beside the
  media using the metadata already fetched; a channel download can produce the
  folder-level files; output is validated against the documented schema in a
  test.
  Complexity: L

- [ ] P2 — Turn the failure taxonomy into a pre-flight
  Why: The app's differentiator is naming a cause after a failure; the same
  knowledge would prevent most of them, and "it broke after an update" is the
  loudest complaint class in the entire field.
  Evidence: Sonarr's Health Checks are the model — named, wiki-linked conditions
  surfaced before a job fails. Conditions this repo can already evaluate:
  yt-dlp older than N days, JS runtime missing or below floor, ffmpeg below the
  security floor or lacking a needed filter, a sign-in jar past expiry, the
  anonymous GitHub API budget exhausted (ytdlp-interface #360 is exactly that
  bug), a POT provider that cannot mint session-bound tokens. Parabolic's open
  issue list is dominated by conditions of this shape while its main branch has
  been quiet since 2026-06-29.
  Touches: `astra_downloader/health.py`, `astra_downloader/gui.py`,
  `astra_downloader/routes.py`
  Acceptance: a health panel lists named conditions with a fix action before a
  download is started; each condition has a test; `/health` exposes them.
  Complexity: L

- [ ] P2 — Close the smaller correctness and coverage gaps
  Why: Individually minor, each is a concrete wrong behaviour with a known fix.
  Evidence and scope, each verified this pass:
  (a) Six of eleven empty states have no recovery action, and the Browser
  extension log has no empty state (`gui.py:2933`, `2957`, `2964`, `3208`,
  `3217`, `3693`).
  (b) Native-messaging registry keys are written only for Chrome and Firefox
  (`astra_downloader.py:3220-3225`); Edge, Brave, Vivaldi, Opera and Chromium
  read different roots and silently never bootstrap.
  (c) `parse_native_extension_ids` (`:3124-3142`) accepts any token and
  interpolates it into `allowed_origins`, while `normalize_extension_origin`
  (`:3145-3154`) — an existing validator — is used only for the legacy HTTP
  allowlist.
  (d) The whisper model URL tracks HuggingFace's mutable `main`
  (`:369-375`); the repo head is `5359861c739e955e79d9a303bcbc70fb988958b1`,
  which `resolve/<sha>/` can pin.
  (e) `output_template_preview` (`config.py:822-865`) is a second implementation
  that expands `%%`, does not model `--windows-filenames`, measures `MAX_PATH`
  against the output dir rather than the staging prefix, and omits `CONIN$`,
  `CONOUT$`, `COM0` and `LPT0` from its reserved-name check.
  (f) The three `Browse` buttons (`gui.py:1990`, `3863`, `3874`) share one
  accessible name although `_make_tool_button` supports a `target` disambiguator.
  (g) Settings search does not index `cfg_site_profiles` because
  `_settings_search_text` (`gui.py:1479-1525`) reads `QLineEdit` only.
  (h) `record_last_installed_update_sha256` (`astra_downloader.py:2244-2254`) is
  called only from tests; production writes that field from the helper script.
  (i) `Wait-Process -Id` on an already-exited probe raises under
  `$ErrorActionPreference = 'Stop'`, so a probe that exited 0 is reported as a
  failed health check (`:2342-2356`) — needs live validation for frequency.
  (j) SponsorBlock's database and API are **CC BY-NC-SA 4.0**, which requires
  visible attribution; the app exposes the feature as a bare checkbox
  (`gui.py:4083`) and the string "SponsorBlock" appears nowhere in `README.md` or
  `SECURITY.md`. The project's blessed short form is "(Using SponsorBlock)" beside
  the option, with a link to https://sponsor.ajay.app/. Worth noting alongside it
  that this is a NonCommercial ShareAlike licence inside an MIT app.
  (k) `docs/yt-dlp-cookie-threat-model.md` is still written in pre-split terms
  ("Astra Deck moves… companion v1.8.0/v1.9.0") against an app at v2.6.0; it is
  the store-review-facing document, so the version framing matters.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/gui.py`,
  `astra_downloader/config.py`
  Acceptance: each sub-item is fixed with a test, or explicitly recorded as
  accepted in `SECURITY.md` where it is a deliberate property.
  Complexity: M

- [ ] P3 — Split `gui.py` along page boundaries
  Why: At 7,743 lines it now has measurable failure modes, not just a smell.
  Evidence: this pass found three defects whose direct cause is the file's size
  and its hand-maintained parallel lists — the dirty-signal list drifting from
  the form-field registry (19 silent settings), `_build_settings` ending with a
  filter call that un-hides deliberately hidden widgets, and a minimum-size
  layout regression when a new combo joined an existing row. The module boundary
  discipline the rest of the repo follows (`_REQUIRED_*_DEPENDENCIES` frozensets,
  no cross-imports) is the pattern to extend.
  Touches: `astra_downloader/gui.py`, `astra_downloader/astra_downloader.py`
  Acceptance: each page is its own module behind the existing dependency-
  injection contract; `npm run smoke:gui` and the suite are unchanged; a diff of
  the rendered captures before and after shows no visual change.
  Complexity: XL
