# Changelog

All notable changes to Astra Downloader are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases before 2.0.0 were made from the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) repository, where this
program lived as a companion service. That history is preserved in this
repository's git log.

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
  source catalogues now cover all 221 extracted strings across all 11 locales,
  and the translation gate fails when generated keys drift from the GUI.
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
