# Changelog

All notable changes to Astra Downloader are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases before 2.0.0 were made from the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) repository, where this
program lived as a companion service. That history is preserved in this
repository's git log.

## [Unreleased] - 2026-08-10

### Fixed

- **Interactive control boundaries now meet the non-text contrast floor.**
  Resting, disabled, hover, input, menu, text-edit, ghost-button, and
  checkbox boundaries are declared against their actual stylesheet fills.
- **Local transcription uses a verified whisper.cpp sidecar.** Setup now fetches
  the pinned CLI and sibling DLLs, probes the SRT capability, and reports a
  missing runtime before a job starts; successful media stays complete when
  subtitle generation fails, with a retry that regenerates only the SRT.
- **Windows subtitle filter paths are escaped at both parser levels.** The
  legacy FFmpeg argument builder now emits the doubled escaping required for
  drive letters and filter punctuation.
- **Portable mode follows the executable layout.** The one-folder archive
  carries a marker, installed copies remain rooted in `%LOCALAPPDATA%`,
  one-folder builds refuse unsafe self-relocation, and portable instance
  control plus uninstall cleanup are isolated to their own data root.
- **YouTube downloads no longer route through the unusable bgutil branch.**
  Plugin loading stays disabled, every extraction uses the verified
  token-exempt client chain, and `/health` no longer claims that a reachable
  external provider can affect downloads.
- **Keyboard traversal now leaves hidden navigation and the Site-profiles
  editor.** The page stack no longer traps focus in its hidden tab bar, and
  Tab in the JSON editor advances through Settings without changing its text.
- **Settings bundles keep machine-local network state local.** Proxy
  credentials, site profiles, network identity and extra output roots are
  excluded on export and ignored on import; the Settings status now lists the
  names of fields it changed.
- **Every editable setting now reports unsaved changes.** Dirty-state wiring is
  derived from the settings form registry, including all SponsorBlock category
  checkboxes, so newly registered controls cannot silently discard edits.
- **Settings search preserves deliberate visibility.** Clearing a search no
  longer resurrects the unavailable import-undo action or a hidden session
  fallback hint.
- **Retry checks now honor site profiles.** Geo and browser-refusal recovery
  uses the URL's effective profile settings, so a profile-provided workaround
  can actually unlock Retry.
- **Portable uninstall now sweeps the full app state surface.** Stored sign-ins,
  download staging, rotated logs, quarantine copies, cookie probes, legacy
  archive data, and interrupted update/setup artifacts are removed while the
  executable, marker, and downloaded media remain.
- **Live-event waiting is now bounded.** The Settings control describes
  yt-dlp's value as a retry interval, while a never-started event is stopped
  after the overall wait window and can be retried without holding a worker
  slot indefinitely.
- **Local transcription is bounded and low priority.** whisper.cpp runs under
  an independent single-job gate with a shared timeout, an exact-child
  watchdog, below-normal process priority, and real `-pp` progress; a timeout
  leaves the downloaded media complete and subtitle retryable.
- **The companion license gate now enforces its inspection.** Release-scoped
  components are checked for resolved licenses, policy decisions, obligations,
  pinned runtime downloads and artifact linkage; unresolved inventory fails the
  gate and is covered by a planted-component regression test.
- **Download staging is now volume-aware and self-cleaning.** Known-size
  preflight names a short output or staging volume; failed and cancelled jobs
  remove private scratch data, and startup removes orphaned staging IDs while
  preserving recovered queue work.
- **Companion updates are throttled and recoverable.** The `/update` endpoint
  now rate-limits and backs off after failures, startup removes orphaned update
  artifacts, failed scheduling records a terminal state, and update markers
  use UTC plus durable replacement semantics.
- **Subscription probes now participate in yt-dlp activity tracking.** The
  updater sees live scans and other yt-dlp probes through the shared activity
  view, and startup removes fresh probe/import cookie jars left by an abrupt
  exit.
- **Config recovery now handles non-finite JSON numbers safely.** Invalid
  numeric settings fall back to bounded defaults, malformed bundles return a
  validation error, and documents rejected by sanitization are quarantined
  before a clean config is saved.
- **Managed binaries install only after verification.** yt-dlp, QuickJS and
  the Whisper model now download into disposable sibling paths, verify there,
  and replace the active binary only after the checksum passes.
- **Config files are forward-compatible and versioned.** A schema marker is
  written to `config.json`, and settings from newer builds survive an older
  build's load/save cycle with a visible recovery log entry.
- **Health checks are bounded and coalesced.** Failed executable probes now
  honor their TTL, concurrent cold requests share one probe, and `/health`
  has its own burst limit with `Retry-After` guidance.
- **Recovery checks no longer probe from the GUI or queue lock.** Runtime and
  browser-impersonation results are published by the background readiness
  worker, while retry/status refreshes consume the cached snapshot.
- **Legacy health-token echo requires an extension origin.** Compatibility
  responses no longer reveal the bearer token to origin-less local callers;
  only normalized origins in the configured allowlist can receive it.
- **Restored server credentials take effect immediately.** API authentication
  and legacy health-token settings are read from the live config on each
  request, so restoring `config.json` no longer requires a process restart.
- **Subscription state no longer loses over-limit history on load.** Extra
  records are preserved and reported, archive-key migrations keep the
  highest-priority collision, and deliberate archive trimming is logged.
- **Subscription and pending-queue schemas migrate forward safely.** Missing
  and older schema markers are normalized on the next save, while newer files
  stay untouched and report the required Astra Downloader version instead of
  masquerading as a disk-space failure.
- **API failures keep the JSON contract.** Oversized requests and unexpected
  handler errors now carry the same CORS, cache, and security headers as normal
  responses, are logged for recovery, and subscription persistence failures
  return a retryable 503 with a distinct code.
- **Cookie-less live retries reset their failure state.** A successful retry no
  longer leaves stale rate-limit advice or host backoff behind, and a retry
  that exits cleanly without writing media is reported as `skipped`.
- **Failed sign-in removal is now non-destructive.** If the site-login index
  cannot be rewritten, the stored credentials and index entry remain available
  instead of being silently split apart.
- **Subscription scans now stop and coalesce cleanly.** Shutdown interrupts
  candidate intake, timed-out scheduler joins are logged, concurrent manual
  requests share one scan, scan-thread exceptions are recorded, and the scan
  endpoint has a bounded retry window.

## [2.6.0] - 2026-08-09

### Added

- **Local subtitles fill the missing-track gap.** An opt-in, checksum-pinned
  multilingual Whisper model is provisioned during setup, and successful video
  downloads with no subtitle track can now produce a cancellable SRT sidecar.
- **The release build has an antivirus fallback.** It now emits a normal
  one-folder zip with its own SHA-256 sidecar alongside the one-file executable.
- **Subscription archive scans avoid document-sized rollback copies.** Failed
  mutations now restore only touched entries. On this Windows 11 / CPython
  3.12.10 machine, a 50-candidate scan against 20,000 archive entries fell
  from a 20.66 s median before the change to 3.20 s after it (103 JSON writes
  in each run).
- **First launch is guided from the Download page.** Missing managed tools
  provision there, the video destination is confirmed once, and the welcome
  panel links directly to browser-extension pairing.

## [2.5.0] - 2026-08-06

### Added

- **Metadata probes use the download identity.** Format lookups, playlist
  previews and subscription scans now carry the configured proxy, browser
  impersonation and the target site's stored sign-in. Probe cookie jars are
  scoped by the same site check as downloads and removed after the probe.
- **Subscription retries are bounded.** Failed candidates now back off with
  increasing delays, stop after three attempts with the title and last error
  shown on the subscription row, and get a fresh budget when the user starts
  a manual rescan.
- **Subscription and update state recover safely.** Future scan times are
  clamped, load-time archive trimming keeps live claims, and an abandoned
  companion activation is marked failed after its timeout so it can be retried.
- **Translation catalogues track every companion UI string.** The checked-in
  source catalogues now cover all 448 extracted strings across all 11 locales,
  including download and health recovery guidance, tooltips and accessibility
  labels; the translation gate fails when generated keys drift from the code.
- **Update and archive keys reject ambiguity.** Checksum sidecars must identify
  the requested asset, long URL-only subscription keys use a bounded digest,
  and uninstall clears the integration stamp so a same-version reinstall
  restores its registrations.
- **Downloads follow the Windows Videos known folder.** Redirected Videos
  locations are used for new defaults, with `~/Videos` retained as the
  fail-safe fallback; existing saved paths remain untouched.
- **Diagnostics survive restarts and can leave the app safely.** The persisted
  log tail seeds the in-memory view, the diagnostics dialog can save its
  redacted JSON payload, and the log header can reveal the server log file.
- **Subscriptions and sign-ins are searchable.** Both lists now debounce text
  search and expose their useful state filters, including disabled/failing
  subscriptions and expired or missing cookie jars.
- **Stored sign-ins can be tested.** Each sign-in row now runs a bounded,
  metadata-only yt-dlp probe against its own site, cleans the temporary jar,
  and leaves a plain-language pass/fail marker on the page.
- **Known download sizes are checked before transfer.** A format probe now
  estimates muxed or split media size and refuses a quick download when the
  destination volume cannot hold it; setup applies the same fail-closed check
  before fetching the ffmpeg archive.
- **Background work says what it is doing.** Server startup now prepares ports
  off the GUI thread and reports a starting state, history distinguishes an
  unreadable store from an empty one, subscription rows show active scans, and
  format probing tells the user when it is looking up available formats.
- **Window state and destructive actions are recoverable.** The companion
  restores its last page, geometry and maximised state; sign-in, subscription
  and settings-bundle changes have one-step undo; and closing reports how many
  active downloads it is about to cancel.
- **Settings are easier to navigate and recover.** Search now narrows the
  form to matching controls and groups, Language and Import and export have
  dedicated sections, and one action restores editable settings to their
  shipped defaults while reporting what changed.
- **Site sign-ins can use credentials when cookies cannot.** Username/password
  sign-ins are stored in protected per-site files, never returned through the
  API or diagnostics surfaces, and are used as a cookie fallback for yt-dlp;
  the download page also exposes a one-link video password. Chromium browser
  readers are marked as likely unreadable on Windows 127+ before import.
- **Intermediate files stay out of the destination.** yt-dlp now stages partial
  and merge files in a stable per-download folder, cleans it after success, and
  reuses it after a restart so failed downloads can resume. The existing
  "Keep intermediate files" setting stages them beside the output for diagnosis.
- **Network-path workarounds are opt-in.** Settings can force an IP family, bind
  a source address, supply a geo X-Forwarded-For value, or use a verification-
  only proxy; 403 and geo-restriction failures now name the matching remedy.
- **Site profiles are URL-aware.** Named domain profiles can set output format,
  quality, impersonation, proxy and request pacing defaults; matching happens
  when a link is pasted, with an explicit one-off profile or no-profile choice.
- **Archive output is opt-in.** Settings can write info JSON, descriptions and
  thumbnails beside media, split chapters into files, start live streams from
  the beginning, or wait a bounded interval for a scheduled live event.
- **Filename templates explain their risks.** Settings renders an example,
  rejects reserved Windows names and overlong rendered paths, and enables
  yt-dlp's Windows filename sanitization.
- **Portable and scripted distribution paths exist.** `--portable` keeps
  application state and managed helpers beside the executable without machine
  integrations; `--install` performs the normal per-user install without
  opening the GUI, and a validated winget manifest is checked in.
- **Throttle recovery is scoped to the host.** HTTP 429 and throttle failures
  pause only the registrable domain that returned them, honour a bounded
  Retry-After hint with optional jitter, keep other sites moving, and show the
  remaining wait directly on the download card.
- **Stall failures keep their cause.** A wedged download or cookie-less retry
  now preserves the specific stall message alongside its network recovery code.

- **Choose which subtitles you get.** Subtitle tracks come from two
  catalogues — the ones a creator wrote and the machine transcript — and the
  app always asked for both. You can now ask for creator subtitles only, the
  auto-generated ones only, or the creator's with auto-generated as a fallback
  (which is what it has always done). Measured against the installed yt-dlp:
  sending both flags never produced two files for one language, so the old
  behaviour was already the fallback preference and what was actually missing
  was the ability to exclude a kind.
- **Subtitles as a download type.** Pick Subtitles beside Video and Audio to
  fetch the tracks without the media. The format and quality pickers are
  disabled for it, since neither describes a subtitle, and the page states
  which languages and format the job will use.
- **Normalise subtitles to one format.** SRT, WebVTT, ASS or LRC, or leave the
  site's own format alone.
- **Pick subtitle languages from a list.** Twelve common languages have
  checkboxes; the field beside them still accepts any code yt-dlp knows, and a
  code with no checkbox is never dropped when you untick another.

- **A JavaScript runtime the app can fetch for itself.** YouTube needs one,
  and until now the only one setup could obtain was Deno — a 40 MB archive
  whose download is the part of setup most likely to fail, leaving the install
  with no runtime and every YouTube download broken. QuickJS is 2 MB, yt-dlp
  accepts it, and it is now the automatic fallback. Verified end to end
  against yt-dlp 2026.08.04: a real YouTube download completes with QuickJS
  as the only enabled runtime. Deno stays the first choice when it is
  available, matching yt-dlp's own priority; QuickJS is also selectable
  outright in Settings.

- **The German translation is actually complete, and the rest are measured.**
  The catalogue's source list was a hand-written tuple of 21 strings against a
  window that shows 219, and nothing connected the two — so every string added
  after the tuple was written never reached a translator, while the
  catalogues reported themselves finished. The strings are now extracted from
  the GUI's syntax tree, `npm run check` fails when one reaches the UI without
  reaching the catalogues, and German is complete at 219/219 with the render
  scenario asserting translated copy on all six pages rather than the
  navigation rail alone. The nine remaining locales still declare only their
  five navigation strings; that gap is now visible and reported per locale
  instead of hidden.
- **Export and import settings.** A single versioned JSON bundle carries
  settings and subscriptions, so an install can be moved to another machine
  and a config you cannot open can be restored without hand-editing JSON. The
  import validates the file, refuses one written by a newer version, puts
  every value through the same normaliser the live config uses, and then
  reports which settings actually changed.

  Stored sign-ins are listed by site but never exported. Cookie values do not
  leave their jar files — that is the store's stated contract — so the bundle
  names the sites you will need to sign in to again rather than carrying the
  sessions. There is deliberately no option to include them. The local API
  token is left out for the same reason: it is a working credential, and a
  bundle is the kind of file people email to themselves.
- **Progress on the taskbar button.** A download runs for minutes and the
  window is usually not what the user is looking at, so the queue's overall
  progress now shows on the taskbar. Several downloads reduce to percent of
  all the work rather than a count of finished ones. Qt 6 dropped
  QtWinExtras, so this talks to the shell's own interface; where that is
  unavailable there is simply no bar.
- **A completion notification can be clicked.** Clicking it raises the window
  and shows the finished file.
- **Right-click a finished download** to play it, show it in the folder, copy
  its link, or stage it for downloading again.

### Changed

- **"Show" now selects the file rather than opening its folder.** In a busy
  Downloads folder the old behaviour still left the user hunting for what had
  just finished.
- **The app claims an explicit taskbar identity.** Without one Windows guesses
  from the executable path, which is what makes a pinned shortcut open a
  second, separate taskbar button, and it is also the identity notifications
  are attributed to.
- The "Embed subtitles" checkbox is now "Download subtitles", which is what it
  does — it fetches sidecar tracks as well as embedding them.

### Fixed

- **A subtitles-only download reports the file it wrote.** yt-dlp's
  after-move hook does not fire when the media is skipped, so such a job would
  have finished with nothing to reveal in the folder; the written-subtitle
  line is now read instead, and a converted track is named by its new
  extension.
- **An imported setting is no longer undone by the next Save.** The settings
  form is redrawn from the stored config after an import; without that it
  would still be showing the pre-import values, and saving would write them
  straight back over the import.
- **Tests no longer depend on what is installed on the machine running them.**
  `INSTALL_DIR` was redirected for the test run but the runtime paths derived
  from it were not, so a check asserting "no JavaScript runtime is available"
  passed only on a machine that happened to have none.
- **The last positional rollback tuple is gone.** `start_download` reuses a
  waiting-for-sign-in record rather than queueing a duplicate, and restored
  the previous request from a sixteen-field tuple — the same shape as the
  retry defect fixed in 2.4.0. It now names its fields.
- **A failed companion activation no longer pins update checks.** The
  suppression digest is written only after the detached helper verifies an
  active install, so activation and rollback failures can offer the release
  again.
- **Failed downloads now have a durable history.** Every terminal outcome
  carries its status, error code and explanation into History; the status
  filter lists those outcomes, and terminal queue rows offer retry, link and
  error actions where applicable.
- **A forked launch cannot silently downgrade the managed app.** Frozen
  executable relocation now uses byte-verified atomic copying, preserves a
  newer installed binary, and leaves the previous target intact on failure.
- **Release builds now emit `AstraDownloader.exe.sha256`.** The staging lane
  validates the source sidecar against the opened EXE and rechecks the staged
  pair, with no hand-maintained checksum or nonexistent release command.
- **The no-provider YouTube fallback now starts with `visionos`.** The client
  chain is pinned to the 2026-08-08 measurement while keeping the fallback
  explicit for the next yt-dlp extractor drift check.
- **The ffmpeg security floor now covers provisioned snapshots.** Undated
  snapshots remain unknown, while a dated master build is compared against
  the 2026-06-17 floor and an older build is re-fetched through verified setup.
- **Failed yt-dlp updates now back off.** A failed attempt is persisted and
  suppressed for one hour, while successful checks retain the normal 12-hour
  interval.
- **Native-messaging access is revocable and machine-local.** Clearing an
  extension allowlist removes its manifest and registry pointer, and settings
  bundles explicitly report that both native-extension lists are not carried.
- **The impersonation picker no longer blocks first paint.** It starts with
  the saved value and a pending marker, then fills from the deferred readiness
  worker after yt-dlp has been probed off the GUI thread.
- **The no-provider YouTube fallback now starts with `visionos`.** The client
  chain is pinned to the 2026-08-08 measurement while keeping the fallback
  explicit for the next yt-dlp extractor drift check.

## [2.4.0] - 2026-08-06

### Fixed

- **A retry that cannot be saved is put back, not left half-done.** The
  rollback in the sign-in branch of a retry packed fifteen fields and
  restored fourteen, so when the queue write failed the rollback itself
  raised — nothing was restored, the error escaped into the API and the
  window, and the download was stranded waiting for a sign-in with none of it
  written to disk. The lists could disagree because they were positional;
  every rollback now names its fields.
- **A `ytdl://` link works when the app is already open.** The link handler
  built the right command and the window knew how to receive it, but the
  listener in between only recognised three fixed words and dropped anything
  carrying a URL. Clicking such a link with the app running opened nothing and
  queued nothing; it only ever worked from a cold start.
- **Resume on a paused download resumes that download.** It called the
  queue-wide resume, so recovering one item started every paused one.
- **A subscription says when it cannot write its archive.** That failure was
  counted as "already downloaded", which is what a healthy scan with nothing
  new reports — so a channel that had silently stopped downloading looked
  completely up to date. Subscriptions run unattended, which is exactly why
  this needed to be visible.
- **Retry, reorder, pause and resume report on the Download page.** Their only
  feedback went to the log panel on the Browser extension page, so a refused
  action produced no visible response where the button was.
- **Nothing the window scheduled outlives it.** A link typed just before
  closing started a format probe afterwards, spawning a `yt-dlp` the shutdown
  path does not track and leaving it running for up to a minute after quitting.

### Added

- **Imitate a browser.** The bundled yt-dlp can send a real browser's TLS
  fingerprint, which is the usual way past a site that answers 403, and none
  of it was reachable. Settings now lists the targets the installed binary
  actually reports. Off by default, because impersonation can itself provoke
  rate limiting. A target the binary does not have is refused rather than
  passed through — yt-dlp aborts the whole download on an unknown one.
- **A 403 is its own failure.** It used to fall into "network unreachable",
  whose advice is to check the firewall. It now names the refusal and points
  at the browser setting, and becomes retryable once one is chosen.

### Changed

- **Controls have a boundary you can see.** Input borders measured 1.79:1
  against the page where the accessibility floor for a control outline is
  3:1, and the fill was 1.07:1, so on a bright screen there was nothing
  marking where a field was. Secondary buttons had no background and no
  border, making them indistinguishable from the labels beside them until
  hovered — "Save to" looked exactly like "Clip from". Text contrast was
  measured at the same time and was already fine, so it is unchanged.
- "Start Server", "Stop Server" and "Check yt-dlp Update" are now sentence
  case, matching every other label.

## [2.3.0] - 2026-08-06

### Added

- **The quality picker knows what the link actually offers.** It was a fixed
  ladder that knew nothing about the pasted URL, so you could ask for 2160p
  on a 720p video and learn the truth only from the result. A settled single
  link is now probed off the GUI thread, debounced, and the ladder is cut to
  what the link can serve. A video that tops out below the lowest rung keeps
  none of them — measured against a real 240p upload, every rung would have
  named a resolution it cannot serve, so Best is the only honest offer. The
  narrowing is undone the moment the URL leaves the box, a probe that lands
  after you have typed on is discarded, and a probe that fails says nothing.
- **Codec and frame-rate preference, as `--format-sort`.** The picker is a
  resolution ladder and could not express "1080p H.264, never AV1". Three
  settings now compile into one sort. Resolution always leads it: yt-dlp puts
  the fields it is given ahead of its own defaults, so a bare codec
  preference reorders across resolutions — verified against the installed
  binary, `--format-sort vcodec:h264` on a 4K source selects 1080p. The MP4
  container remains a hard H.264 + AAC constraint; these order what it leaves
  open, and the defaults send no flag at all.
- **Playlist bounds.** A pasted playlist queued everything it contained.
  Settings can now cap the item count and filter by upload date and by item
  duration — the way a channel's shorts or its multi-hour streams get left
  behind. They apply only to a run that walks a playlist, so a bound meant
  for a playlist never silently skips the one video you asked for.
  `--download-archive` stays out: the subscription archive keys are this
  project's answer to "already seen", and a second one would make a
  deliberate re-download report "already downloaded" and do nothing.
- **A right-to-left locale is rendered in the smoke set.** Arabic is
  advertised and flips the whole layout, and nothing had ever rendered it, so
  no gate could see what mirroring did to a page. The new scenario pins that
  the hero row reverses and the navigation rail moves to the right half.

### Fixed

- **A quarantined yt-dlp or ffmpeg is re-fetched instead of trusted.**
  Antivirus removing them is the largest single support burden for
  downloaders of this shape, and the damaging case is not removal but a
  quarantine that leaves a zero-byte stub behind. Every gate was an existence
  check, which a stub satisfies, so launch skipped setup, setup reported
  "already installed", and the first download failed with WinError 193 and no
  explanation. A managed binary is now classified against a size floor, and a
  damaged one is re-fetched while the log and the readiness row say antivirus
  may be responsible and name the directory to exclude.
- **A SABR-only link says what it cannot honour, before the run.** yt-dlp
  ignores clip ranges, the bandwidth cap and concurrent fragments on a SABR
  stream, so a clip range typed against one was accepted and quietly produced
  the whole video. Such a link is now recognised from the format probe, its
  clip fields are disabled, and the hint names all three voided options. One
  ordinary format is enough to be unlimited — that format is what gets
  downloaded, so nothing is void.

### Changed

- The translation builder reports per-locale coverage. A missing entry is
  written out as its own English source, which Qt needs for a clean fallback
  but which also made an empty catalogue indistinguishable from a finished
  one: nine advertised locales ship five of twenty-one strings and every
  check passed. The incomplete locales are now named in a test.

## [2.2.0] - 2026-08-06

### Added

- **Throttle recovery, socket timeout and extractor retries.** The only
  transfer controls were a bandwidth cap and a retry count, so a CDN that
  throttled to a trickle ran until the stall watchdog killed it. Settings now
  exposes a throttle floor — below it yt-dlp re-extracts the video rather than
  crawling — plus a socket timeout and a separate retry count for the page
  read that happens before any transfer starts. All three default to off,
  leaving the argv byte-identical until you change something.
- **Request pacing, and an HTTP 429 that says so.** A bandwidth cap does
  nothing about a per-request rate limit. Settings now spaces downloads and
  the requests inside them, with an optional randomised upper bound. A 429 is
  classified as its own failure — previously it fell into the generic
  "network unreachable" bucket, whose advice was to check your firewall — and
  its recovery advice points at the pacing. A paced download now reads
  "waiting 7s" in the queue instead of appearing hung on its last speed.
- **Optional format verification.** yt-dlp can confirm a chosen format is
  actually downloadable before committing to it. Off by default, because it
  costs a request per candidate format.

### Fixed

- **A failure can be retried once you have fixed what it was waiting for.**
  Eight of the thirteen classified failures — missing JavaScript runtime,
  missing FFmpeg, sign-in required — refused Retry with "this failure needs
  its recovery action before it can be retried", and nothing re-checked after
  you performed it. Installing Deno left the download stuck and the only way
  forward was to re-paste the URL. The queue now re-evaluates the actual
  precondition, so Retry appears on the card as soon as it is satisfied, and
  a refusal names what is still missing instead of repeating itself.

### Security

- **yt-dlp no longer loads plugins from your profile.** `--ignore-config`
  stops configuration *files*; plugin directories are a separate mechanism
  with their own defaults, so arbitrary Python under
  `%APPDATA%\yt-dlp\plugins` was imported and executed inside every yt-dlp
  process this app spawns. Verified against the real binary with a marker
  plugin, before and after. `--no-plugin-dirs` and `--no-remote-components`
  are now added at the same process boundary that refuses `--exec` and the
  external downloaders, so an invocation added later cannot forget them.

## [2.1.0] - 2026-08-06

### Security

- **The instance-control port requires the session token.** Any local process
  could send `shutdown` to `127.0.0.1:9752` and force-close the app in the
  middle of a download, or `start` to bring the local API up. Commands now
  carry the token that the HTTP surface already required, and the listener
  drops `SO_REUSEADDR` for `SO_EXCLUSIVEADDRUSE` so a second binder fails
  instead of taking the port.
- **`/health` no longer hands the subscription list to unauthenticated local
  callers.** The endpoint already gated recent log entries behind the bearer
  token; the channel URLs and titles a user follows are the same class of
  thing and now sit behind the same check. The identity and version fields the
  extension needs to discover the server stay open.
- **The yt-dlp process-boundary guard covers the 2026 advisories.** It refused
  the four link-file flags from CVE-2026-55404; it now also refuses `--exec`,
  `--exec-before-download`, the `--netrc` family and every spelling of the
  external-downloader options, with the same long-option abbreviation
  handling. None of these are ever built into an argv — the guard exists to
  catch a future regression that does.

### Added

- **SponsorBlock acts on the categories you choose.** It sent the literal
  `all`, so turning it on to skip sponsors also stripped intros, outros and
  self-promo. Settings now lists the ten yt-dlp categories, defaulting to
  sponsor, self-promotion and interaction reminders; ticking none keeps the
  old all-categories behaviour. Unknown names are dropped rather than passed
  through to the subprocess, and the YouTube-only scoping is unchanged.
- **`ytdl://` and `mediadl://` links download the video they name.** The
  handlers were registered and the URL was thrown away — every such link
  mapped to the literal command "start", so clicking one opened the app and
  queued nothing. The link now goes through the same URL policy a typed link
  does, whether the app was already running or is starting because of it.
  A bare `ytdl://start` still just brings the app up.
- **Send one download somewhere else.** A "Save to" button beside the paste
  box overrides the destination for the next download only; it names the
  folder it will use, says so again in the queued message, and reverts to the
  default afterwards. Clicking it while an override is set clears it.
- **Drop a link on the window and it downloads.** A dragged link, a selection
  of text containing links, or a dropped `.txt` list all land in the paste
  box's batch path — junk lines are ignored, duplicates collapse, and the
  window switches to Download so you can watch the queue.
- **One finished download, one file.** A merged download leaves `.part`,
  `.f###` and `.ytdl` files beside the result, and yt-dlp does not always
  remove them. They are now swept once the download succeeds — never on
  failure, where the `.part` file is what a resume continues from — and only
  files belonging to that download's own destination are touched. Settings has
  a "Keep intermediate files" switch for diagnosing a merge problem.

### Changed

- **Running from source needs Python 3.11.** The pinned yt-dlp raised its
  minimum in 2026.07.04, so on 3.10 the dependency install failed before the
  version guard written to explain the problem ever ran.

### Fixed

- **The queue list stops rebuilding on every yt-dlp progress line.** Each line
  from each of up to three running downloads triggered a full refresh on the
  GUI thread, on top of the 500 ms timer that would have done it anyway. Bursts
  now collapse into one refresh, and typing in the History search waits for a
  pause instead of re-reading and re-sanitising `history.json` per keystroke.
- **Repeated row buttons are distinguishable to a screen reader.** Tabbing the
  History list announced "Show, Show, Show"; each control is now named for the
  file, site, subscription or download it acts on. The visible labels are
  unchanged.
- **Keyboard focus survives a download card rebuild.** A card is destroyed and
  rebuilt on every status transition, so a keyboard user sitting on Cancel lost
  focus to nowhere the moment the download finished. Focus now lands on the
  same action, or on the card, whichever still exists.
- **History reports its own failures on the History page.** Clear, Undo and
  Export wrote their results to the log panel, which lives on the Browser
  extension page — so a permissions error produced no visible response at all.
- **An oversized cookies.txt is refused before it is read.** The 1 MB cap sat
  downstream of a read on the GUI thread, so picking a huge file froze the
  window before the cap could apply.
- **The diagnostics bundle carries the 30 log entries it advertises.** The ring
  behind it held 20; the test injected a synthetic list, so it passed while the
  two constants disagreed.
- **A quarantined state file is announced, and can be put back.** A corrupt
  `config.json` was renamed aside in silence, taking every setting with it and
  regenerating the server token — which breaks extension pairing with no
  explanation. A corrupt `download-queue.json` was indistinguishable from an
  empty one, so pending downloads vanished. The Download page now names the
  file and its backup, says what the consequence was, and offers one-click
  restore; dismissing leaves the backup alone.
- **A startup failure says something instead of nothing.** In a windowed
  build a fatal error meant double-clicking the icon did nothing, forever,
  with the only evidence in a file nobody knew about. It now shows a message
  box naming the crash log and exits non-zero. Exceptions escaping a Qt slot
  reach the crash log and the in-app log panel rather than aborting silently.
- **A download that finishes but cannot be recorded says so.** `history.add`
  reports whether the write landed and the caller discarded it, so on a full
  disk a download completed, the file existed, and History simply never
  mentioned it. The Download page now carries a storage notice for this and
  for a queue that could not be saved, and the failure reaches the log.
- **The proof-of-origin provider status is visible.** The readiness probe has
  always computed it and failure advice referred to it, but no row existed to
  show it, so every update was discarded in silence. The Download page tool
  strip now carries a PO provider row and wraps to a second line, which also
  stops the strip's entries overlapping on a narrow window at a large font.
- **Interrupted downloads resume instead of restarting.** `--force-overwrites`
  was sent on every run, and yt-dlp's own help notes it includes
  `--no-continue`, so a 4 GB file interrupted at 95% re-downloaded in full.
  It is now sent only on a run meant to start over — a retry, a resume, or a
  download recovered after a restart continues from its `.part` file, while
  re-downloading the same URL still overwrites as it always did.

- **`--uninstall` now actually removes the install directory.** The delayed
  removal ran `powershell -Command "<script>" <path>`, which never populates
  `$args`, so the command was well-formed, reported success and deleted
  nothing — leaving per-site cookie jars, the server token, history and
  subscriptions on disk after an uninstall that said it had finished.
- **YouTube URLs are recognised by parsed host, not by pattern match.**
  `https://evil.com?x=.youtube.com/` was classified as YouTube because the
  host pattern could be satisfied from a query string or fragment. That
  predicate selects the cookie jar handed to yt-dlp on a `--cookies` write
  path, so it now compares host labels from `urlparse().hostname`.

## [2.0.0] - 2026-08-05

Astra Downloader is its own product, in its own repository, designed around
the thing it is actually for: downloading a video.

### Changed

- **The window opens on Download.** The paste box is the first thing on the
  first page, sized like the product's front door rather than a field on a
  secondary tab. The queue sits directly beneath it.
- **The server moved to a Browser extension page.** The local API that serves
  the Astra Deck extension is a feature of the downloader, not its dashboard.
  The page says so plainly: downloading by pasting a link never needs it.
- **Tool readiness moved to the Download page.** yt-dlp, FFmpeg, the
  JavaScript runtime and SABR support are what determine whether a download
  works, so they are visible where downloads happen. The Local API row stayed
  with the server.
- **The navigation rail is ordered by use**: Download, History, Sign-ins,
  Subscriptions, Browser extension, Settings.
- **The rail's status line names what it reports.** An unlabelled "Stopped" in
  a downloader reads as a broken app; it now says "Extension server".
- **An empty queue points at the paste box**, not at a server dashboard.
- **Self-update targets this repository.** `APP_VERSION`, the release API, the
  executable and its SHA-256 sidecar all resolve against
  `SysAdminDoc/AstraDownloader` instead of the extension's releases.

### Added

- Version, catch-reason, port-catalogue and Python dependency gates run from
  this repository (`npm run check`), with a `check-versions` gate that also
  pins the name of the `APP_VERSION` test so a bump cannot silently pass while
  naming the previous release.
- Four tests pin the downloader-first layout as a design decision rather than
  an accident of edit order: Download is first and is the landing page, the
  server page is named for the extension it serves, download-tool readiness
  lives with the paste box, and the empty queue points at the paste box.

### Removed

- The extension-side half of the port-catalogue check and generator. Astra
  Deck checks its own consumers against its own copy of the catalogue JSON;
  the two copies are the contract.
- The locale test's dependency on the extension's `_locales` directory. The
  companion now pins its own shipped catalogues: every advertised locale ships
  a compiled `.qm` with a `.ts` source, and nothing ships a catalogue the app
  cannot select.

## Roadmap archive — 2026-08-10 — ROADMAP.md

<details>
<summary>Original roadmap snapshot</summary>

```markdown
# Roadmap

Actionable items only — work a coding agent can pick up and implement without
external dependencies. Completed items are deleted; shipped work lives in git
history and `CHANGELOG.md`. Items that need something outside this repository
live in `Roadmap_Blocked.md`.

## Carried over

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

## Research-Driven Additions — v2.6.0 pass (2026-08-09)

Every item traces to a finding in `RESEARCH.md`. Measurements were taken on this
machine (Intel Core Ultra 9 285, 24 logical cores, Windows 11 26100) against the
binaries the app actually provisions.

### P0

Ten items, all either user-harming or ship-blocking. Suggested order: the three
transcription items are one chain and are worth doing together; the portable
item is one root cause behind three destructive symptoms and should precede any
packaging work; the two keyboard traps and the subscription error are each a
short, self-contained fix; publishing unblocks everything downstream.

- [ ] P0 — Restore a supply chain that can actually transcribe, and probe the capability
  Why: v2.6.0's headline feature cannot work on any current install, and the app
  converges every install to the broken state on its own.
  Evidence: yt-dlp/FFmpeg-Builds disabled the filter in commit `bfcf84000`
  ("Disable Whisper", 2026-06-19) — `scripts.d/50-whisper.sh` now ends
  `ffbuild_enabled() { …; return -1; }` for every target, and the
  `ffmpeg-master-latest-win64-gpl.zip` asset dropped from ~211 MiB to 162.4 MiB.
  `FFMPEG_URL` (`astra_downloader.py:381`) points at exactly that asset. Worse,
  `_ffmpeg_needs_refresh` (`gui.py:703-720`) logs "Installed ffmpeg is below the
  verified security floor; downloading a fresh copy" for any build older than
  `_FFMPEG_MIN_SNAPSHOT_DATE = "2026-06-17"` (`astra_downloader.py:1645`) — i.e.
  for every build old enough to still contain the filter — and enabling the
  setting calls `_run_setup()` (`gui.py:6999`), so the action that turns the
  feature on is the action that removes the capability it needs. The security
  floor and the feature are mutually exclusive under the configured URL. Nothing
  probes for the filter: `FfmpegCapabilitiesProbe` checks version and snapshot
  date only. Note when writing the probe that `ffmpeg -h filter=whisper` exits
  **0 even for an unknown filter** (verified) — parse the output or use
  `-filters`, or the probe becomes another check that always passes. Preferred
  route in `RESEARCH.md` open question 1: a whisper.cpp sidecar
  (`whisper-bin-x64.zip`, ~8 MB, release-asset SHA-256 available) provisioned
  through the same managed-binary path, which keeps both the ffmpeg source and
  the verified-bootstrap story.
  Touches: `astra_downloader/astra_downloader.py`, `astra_downloader/health.py`,
  `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: transcription works on a fresh install whose ffmpeg satisfies the
  security floor; a missing capability is reported on the readiness strip and in
  the failure cause *before* a job runs, not as a generic ffmpeg error; a test
  proves the probe reports "missing" against a binary without the filter.
  Complexity: L

- [ ] P0 — Escape the ffmpeg filtergraph at both levels, and retire the test that pins the bug
  Why: Every Windows path contains a drive-letter colon, so the filter graph
  never parses and no SRT is ever produced — independent of the supply-chain
  defect above.
  Evidence: `escape_ffmpeg_filter_value` (`download.py:1626-1637`) writes one
  backslash; libavfilter strips one layer at the graph level before the option
  parser sees the string, so `C\:/…` arrives as `C:/…` and splits on the colon.
  Running the app's own `build_local_subtitle_args` output verbatim against the
  provisioned ffmpeg: `No option name near '/Users/…'`, rc=-22, no file written.
  Doubling the escapes on the identical command: rc=0, valid SRT. The pinning
  test `test_filter_paths_escape_drive_letters_and_filter_punctuation`
  (`test_astra_downloader.py:15485-15500`) asserts the broken shape, and
  `_TranscriptProcess` (`:15512-15528`) un-escapes with the same wrong rule, so
  the fake reverses the producer's mistake and seven tests pass.
  Touches: `astra_downloader/download.py`,
  `astra_downloader/test_astra_downloader.py`
  Acceptance: a test drives the **real** ffmpeg against a short generated audio
  file and asserts a non-empty SRT on disk; the argv-shape test asserts a string
  that real ffmpeg accepts.
  Complexity: S

- [ ] P0 — Stop a failed transcription from reporting a complete download as failed
  Why: The media file is downloaded, verified and on disk, but History files it
  under a terminal `failed`, and the remedy offered re-downloads the whole thing.
  Evidence: `_run_download` calls `_run_local_subtitles` only when
  `dl.status == 'complete'` (`download.py:4363`), and that method sets
  `dl.status = 'failed'` on every failure path (`:3691`, `:3785`, `:3793`,
  `:3801`). `'transcription-failed'` is in `DOWNLOAD_RETRYABLE_ERROR_CODES`
  (`:102-103`), so Retry re-runs the entire job. The failure copy is already
  honest ("Local subtitle generation failed after the media downloaded",
  `:239`) — only the status is wrong. Knock-on:
  `_sweep_download_intermediates` is gated on `complete` (`:4432`), so the
  staging directory leaks for every affected download.
  Touches: `astra_downloader/download.py`, `astra_downloader/gui.py`
  Acceptance: the download stays `complete` with a visible "subtitles could not
  be generated" annotation and an action that retries **only** transcription;
  staging is still swept; a test covers the terminal state and the sweep.
  Complexity: S

- [ ] P0 — Derive portable mode from where the executable lives, not from argv
  Why: One root cause produces three separate high-severity defects, two of them
  destructive, and it is also the blocker that keeps winget packaging out of
  reach.
  Evidence: `portable_mode_requested` (`astra_downloader.py:312-320`) reads argv
  and `ASTRA_PORTABLE` only, so portability is lost on any launch the user did
  not type the flag for. (a) The one-folder zip that README:146 recommends as
  the antivirus fallback, launched normally, reaches
  `ensure_installed_executable` (`:2872-2906`), which copies **only**
  `AstraDownloader.exe` — verified as a 7,816,473-byte stub in a 289-entry
  archive that needs its sibling `_internal/` — over the installed copy (the
  guard at `:2893` preserves only a *strictly newer* version) and then repoints
  the shortcuts, logon task and protocol handlers at the dead file. (b)
  `_run_companion_self_update` relaunches with a hardcoded `['--start-server']`
  (`:2737-2742`), so a portable copy becomes an installed one and writes every
  registration README:104 promises it will not. (c) `run_uninstall`
  (`:3842-3919`) branches on the same flag, so a portable copy's `--uninstall`
  without `--portable` runs `shutil.rmtree(INSTALL_DIR)` on
  `%LOCALAPPDATA%\AstraDownloader` and destroys a different install's config,
  history and sign-ins. Same flag also leaves the single-instance mutex
  `Local\AstraDownloader.SingleInstance` (`:4365`) and ports 9752/9753 shared, so
  a portable launch silently raises the installed window instead. (The stub's
  *inability to start* is inferred from the PyInstaller layout, not observed —
  needs live validation; the copy, the version guard and the re-pointing are all
  verified from code and artifact.)
  Touches: `astra_downloader/astra_downloader.py`, `README.md`
  Acceptance: a marker file beside the executable (plus an "am I inside
  `INSTALL_DIR`?" check) determines portability, with argv as an override; the
  self-update relaunch propagates it; the onedir build refuses to self-relocate;
  uninstall scope is derived from the running copy; the mutex and control ports
  are namespaced per data root; `README.md` states which layout needs which
  flag. Tests cover each of the three symptoms.
  Complexity: M

- [ ] P0 — Make the PO-token path real, or stop taking the branch that needs it
  Why: The integration cannot work by construction, and the failure is
  inverted — when the provider probe *succeeds*, YouTube downloads get worse.
  Evidence: `build_youtube_extractor_args` (`health.py:285-296`) emits
  `--extractor-args youtubepot-bgutilhttp:base_url=http://127.0.0.1:{port}`.
  That namespace belongs to the bgutil-ytdlp-pot-provider **yt-dlp plugin**:
  `bgutil` appears nowhere in the pinned `yt_dlp` package, and
  `yt_dlp/extractor/youtube/pot/_builtin/` ships only cache providers
  (`MemoryLRUPCP`, `WebPoPCSP`) — no token minter. Meanwhile
  `validate_ytdlp_spawn_args` injects `--no-plugin-dirs` into every spawn
  (`astra_downloader.py:564`, `:587-588`), so no provider plugin can ever load
  and yt-dlp silently ignores the unknown namespace. The `else` arm of that same
  function — the one that restricts the client list to genuinely token-exempt
  clients — is skipped whenever the probe succeeds, so a running bgutil server
  downgrades downloads to SABR-only formats and 403s while `/health` reports the
  provider healthy. `BGUTIL_POT_MIN_VERSION` (`health.py:47`) is also
  unsatisfiable in spirit: the newest released provider is 1.3.1 (2026-03-07) and
  every released version currently mints tokens YouTube rejects
  (bgutil-ytdlp-pot-provider #242, PR #243 open).
  The plugin-free route that fits this architecture: have the companion
  extension mint the token in a real YouTube page context, hand it back over the
  loopback API, and pass `--extractor-args youtube:po_token=web.gvs+<TOKEN>`,
  which needs no plugin at all. Tokens are bound per video ID, so the bridge
  must mint per download.
  Touches: `astra_downloader/health.py`, `astra_downloader/routes.py`,
  `astra_downloader/download.py`
  Acceptance: either the token arrives through a path that works with
  `--no-plugin-dirs` in force, or the bgutil branch is removed so the
  token-exempt fallback always applies; a test proves the emitted argv changes
  the client list in the direction claimed; `/health` reports the provider as
  usable only when it can actually affect a download.
  Complexity: L

- [ ] P0 — Free the forward-Tab focus chain
  Why: Forward Tab does nothing on all six pages — a WCAG 2.1.2 keyboard trap in
  an app that already invested in accessible names and focus rings.
  Evidence: `gui.py:1285-1288` hides the `QTabWidget` tab bar, which is the
  widget's focus **proxy**, so `setFocus()` forwards into a hidden widget and Qt
  still reports success. Reproduced in an isolated 25-line PyQt6 script: tab bar
  visible → `nav0, qt_tabwidget_tabbar, f0, f1, f2, …`; hidden as shipped →
  `nav0, nav0, nav0, …`; hidden with `setFocusPolicy(Qt.FocusPolicy.NoFocus)` →
  `f0, f1, f2, nav0, …`. Zero tests touch keyboard navigation
  (`Key_Tab|focusNextPrevChild|tabChangesFocus` → 0 hits), which is why it
  shipped. Tab traversal is baseline keyboard access, not a keyboard *shortcut* —
  the project's no-shortcuts convention does not cover it.
  Touches: `astra_downloader/gui.py`, `astra_downloader/test_astra_downloader.py`
  Acceptance: Tab from the first nav button reaches every focusable control on
  each page in visual order and wraps; a test walks `focusNextPrevChild(True)`
  and asserts the visited set per page.
  Complexity: S

- [ ] P0 — Stop the Site-profiles editor trapping Tab and eating the keystroke
  Why: It is a second keyboard trap, and every trapped press silently corrupts
  the JSON the user is editing.
  Evidence: `cfg_site_profiles = QTextEdit()` (`gui.py:3836`) with
  `tabChangesFocus()` false. Measured on the live window: 60 Tab presses from the
  settings filter reach 10 of 108 focusable controls, leaving Storage,
  Post-processing, Format preferences, Playlist limits, Performance, Language,
  Tray behavior, Maintenance, Import/export, **Save changes** and **Restore
  defaults** unreachable; each press also appends a tab character to the buffer
  (`len 2 -> 5` after three presses).
  Touches: `astra_downloader/gui.py`
  Acceptance: `setTabChangesFocus(True)` (or an equivalent), Tab moves on without
  modifying the document, and the Settings page is fully traversable; a test
  asserts both.
  Complexity: S

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

- [ ] P0 — Publish the shipped versions, and fail the release gate when a version has no release
  Why: Six versions of fixes — including three `security:` commits and the whole
  v2.6.0 feature set — have never reached a user, and both delivery paths point
  at the stale one.
  Evidence: `gh release list` returns a single release, `v2.0.0` (2026-08-06),
  and `git tag -l` returns a single tag; `APP_VERSION` is 2.6.0. The updater
  resolves `releases/latest` (`astra_downloader.py:410-413`), so an installed
  v2.0.0 sees itself as current forever, and Astra Deck's
  `INSTALLER_URL` (`ytkit-v4.58.2.user.js:32248`) hands new users the same
  v2.0.0 asset. The `v2.0.0` release also carries no `AstraDownloader-onedir.zip`,
  so the antivirus fallback README documents has never been published.
  Touches: `CHANGELOG.md`, `scripts/check-versions.js`,
  `scripts/stage-companion-release.js`, release process
  Acceptance: v2.6.0 is tagged and released with both artifacts and their
  sidecars, intermediate tags are backfilled, and a gate fails when `APP_VERSION`
  has no matching published release/tag.
  Complexity: M

### P1

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

### P2

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

### P3

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
```

</details>
