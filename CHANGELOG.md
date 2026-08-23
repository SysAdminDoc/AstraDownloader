# Changelog

All notable changes to Astra Downloader are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases before 2.0.0 were made from the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) repository, where this
program lived as a companion service. That history is preserved in this
repository's git log.

## [Unreleased]

### Fixed

- **A routine YouTube warning no longer turns a finished download into a
  failure.** If yt-dlp writes the file and exits normally, Astra now reports it
  as complete. The same warning still explains the failure when no file was
  delivered.

- **Disk space is checked no matter where a download begins.** The desktop
  window, browser extension, and scheduled subscriptions now use the same
  probed-size check before anything enters the queue. API callers receive the
  named `insufficient-disk-space` response instead of a later yt-dlp failure.

- **Settings bundles keep each subscription's delivery choices.** Audio-only
  mode, format, quality, naming template, output folder, and upgrade checks now
  survive export and import. A folder outside the bundle's own download roots
  is left out and named in the import result.

## [2.12.0] - 2026-08-22

An audit pass. Nothing here is a new feature; it is a list of things that were
quietly wrong.

### Fixed

- **A history date now filters the way it reads.** The saved-date boxes compare
  what you type against the date stored on each row, as text, and nothing
  checked what you typed. So `2026-8-1` sorted after `2026-08-22` and hid the
  whole list, an American-format date hid it too, and so did half a date on the
  way to typing a whole one. All you saw was the ordinary "no matching
  downloads" panel. Dates are read properly now: one that is not a date is
  ignored, the box it came from is marked, and the page says so. A range whose
  start is after its end says that instead of looking like no results. The API
  had a check, but it accepted `2026-8-1` and then answered 200 with an empty
  page; it does the same thing the window does now.

- **A routine yt-dlp warning no longer decides why a download failed.** yt-dlp
  prints "YouTube is forcing SABR streaming for this client" as a warning on
  ordinary runs. The failure path read the last thirty lines as one string
  after it had already worked out the real cause, so a video that needed a
  sign-in was reported as a SABR limitation: wrong advice, the real message
  thrown away, and no Retry button, because that state has no retry.

- **A retry starts a clean run.** Three things yt-dlp reports about a run were
  never cleared when you retried it. The damaging one meant a first attempt
  that printed the SABR warning and failed could be retried, download the file,
  and be marked failed anyway, in a state with no way out. The other two skipped
  the subtitle generation the retry was for, and left a subscription comparing
  its next upgrade against a height from a run that failed.

- **The cleanup after a download stops deleting files it did not write.** One
  of the four patterns it swept matched `Movie.f1080p.WEB-DL.mp4` when a
  download called `Movie.mp4` finished in the same folder. That is a name a
  person gives a file, in the user's own download folder.

- **A subscription's folder is checked when you set it.** An unusable one used
  to fail on the next scan, and then once per video from then on, while the
  subscription itself looked configured and simply never delivered.

- **Rolling a tool back sticks.** A version check already running against the
  old copy could land after the rollback and put the old version back for an
  hour.

- **The naming-template preview reports the length yt-dlp will write.** It
  parsed the width in a template like `%(title)200.5s` and threw it away, so it
  showed five characters where yt-dlp writes two hundred, and told you a path
  fitted when it did not.

- **Settings tell you what is wrong with a field.** A rejected field turned its
  border a slightly redder shade and the page said "Check the highlighted
  fields before saving." The reason was written where only a screen reader
  could reach it. It is on the field and in the status line now.

- **Exporting settings no longer records a port you never chose.** When the
  configured port is busy, the app picks another one for that session only. An
  export taken in that session wrote the temporary port into the file as your
  setting, and importing it made it permanent.

- **Removing a sign-in cannot leave a cookie jar behind.** If the file could not
  be deleted, the entry was already gone from the index, so the jar stayed on
  disk with nothing listing it and no way to try again.

### Changed

- **A finished download has a More button.** Play, delete the file, copy the
  link, copy the error, download again and view the command were only ever
  reachable by right-clicking the row, with nothing on screen saying so and no
  way to get there from the keyboard.

- **The light theme was derived one colour at a time,** which let an earlier
  substitution be rewritten by a later one. The scrollbar handle ended up the
  same colour as its own hover, and it wore the hover colour at rest. Row hover
  did nothing at all in the light theme, because the hover colour and the card
  behind it both came out white. A cancelled or skipped download rendered like
  a pending one. A row that took the keyboard focus drew nothing. A rejected
  site-profiles document was marked in a way nothing drew.

- **Two light-theme colours were below the contrast floor the dark theme
  clears:** the running-server indicator in the sidebar, and the label on every
  primary button. A checked checkbox drew its focus ring on top of its own
  fill, at 1.5:1.

- **One capitalisation convention.** Ten Title Case strings against 237
  sentence-case ones, six of them naming an action a sentence-case string
  already named. The Sign-ins page labels its username and password boxes
  instead of relying on placeholder text that disappears as you type.

- **The gate meant to keep German complete was never wired up.** It was
  written down, documented as enforced, and read by nothing, so a new English
  string could reach the German window untranslated. It also found eighteen
  German translations keyed on English that no longer exists.

## [2.11.0] - 2026-08-22

### Changed

- **Queue writes no longer stall the window.** Saving the pending queue used
  to serialise and fsync while holding the lock the UI takes twice a second,
  so a slow or encrypted disk showed up as a stuttering window. The snapshot
  still happens under the lock; the write happens on its own thread, and a
  burst of them collapses to the newest since the file is a full snapshot.
  The paths that undo a change when a write fails still write synchronously,
  because an answer that arrives after the lock is released is no use to them.

- **The test suite runs in parallel and is split by domain.** 1,100 tests in
  about 45 seconds instead of 140, across seven modules — download, GUI,
  routes, subscriptions, health, config and build — with the shared fixtures
  in one place. Getting there meant fixing what made the suite depend on the
  order it ran in: process-wide probe caches, the yt-dlp activity registry,
  and several two-second waits on background threads that a busy machine
  could miss.

### Fixed

- **The download-health panel is translated all the way through.** Its row
  names and its ten repair buttons took their text from a lookup, which the
  string extractor cannot read, so they stayed English inside a panel that
  was otherwise fully translated. A German capture of the failing panel now
  proves it, and a test refuses a new repair action that arrives without a
  translatable label.

### Added

- **An archive notices when a video disappears.** A scan that saw the whole
  source and no longer lists a captured video marks it, without deleting
  anything — the record, the file and the claim all survive. A scan that only
  covered its usual window never judges, because an old upload falling out of
  that window is not a deletion. The archive also remembers where each file
  landed, so it can tell you when the copy on disk is gone, and neither state
  causes a silent re-download: Allow again is what reverses either one.

- **Subscriptions became an archive manager.** Each one now carries its own
  destination, format, quality and naming template, so one feed can land in
  its own folder shape while everything else keeps your defaults. An Archive
  view lists what a subscription has captured and lets you allow any item
  through again — that forgets the archive claim and never touches the file
  on disk. A subscription can also be told to re-fetch a video only when the
  site offers a taller one than the copy you already have; it is off by
  default because it costs a lookup per captured video on every scan.
  Existing subscriptions keep behaving exactly as they did.

- **Windows shell integrations.** The taskbar button now carries a jump list
  with "Paste and download" and "Open downloads folder", and both work from a
  cold start because Windows offers them whether or not the app is running.
  Astra Downloader also asks Windows to bring it back after an update reboot,
  so a queue no longer ends silently when the machine restarts overnight.
  Deleting a finished download's file from the queue sends it to the Recycle
  Bin instead of removing it outright.

- **Pin a managed tool, or roll one back.** Settings now lists yt-dlp, ffmpeg,
  Deno, QuickJS and whisper with the version installed, a pin field and a Roll
  back button. Pinning holds a tool where it is, which is the way out of an
  update that removed something you were using. A pin below a tool's stated
  security floor is refused and says which floor and why. Setup keeps the copy
  it replaces, so rolling back has something to go back to, and rolling back
  pins there rather than letting the next update undo it. The pinned version
  and the digest of the bytes on disk both reach the licence inventory.

- **The playlist review edits items, not just prunes them.** Every row in
  Review playlist now carries its own format, quality and file name, with an
  Apply to selected bar for changing them in bulk. Videos a subscription scan
  already captured are marked "In archive" and start unticked, so a re-scan of
  a channel you follow no longer re-fetches what you already have. Rows that
  keep the defaults still queue as one download; only edited rows split off.

- **Four more pre-flight checks, taken from Radarr's list.** Download health
  now also reports whether the download folder exists and accepts a write,
  whether settings and the queue live somewhere an update would erase, how
  many sites are refusing every attempt and for how long, and whether this
  machine's clock has drifted far enough to break certificate checks and
  expire stored sign-ins early. Each has its own repair button, and each
  appears on `/health` too. The clock reading comes off the `Date` header of
  requests the app already makes, so it costs nothing.

- **The original upload wins over YouTube's AI upscale.** YouTube serves
  AI-upscaled renditions that sort above the creator's own file on resolution
  alone. Format preferences carries a new "Prefer the original upload over an
  AI upscale" tick, on by default, that tries the genuine source first and
  falls back to an upscale only when nothing else fits. Verified against the
  pinned yt-dlp with a `--load-info-json` fixture holding both.

- **YouTube pacing now explains the tradeoff.** Settings turns the configured
  pause into per-worker and aggregate hourly estimates at the current
  concurrency, beside yt-dlp's published figures. The first stored YouTube
  sign-in also returns or shows a linked warning about account bans and
  signed-in sessions that can make public videos unplayable.
- **Downloaded release pairs are checked before installation.** When the
  adjacent SHA-256 sidecar is present, a malformed file or digest mismatch
  stops setup with a named integrity error before anything is copied into the
  managed install. This detects mismatched release files; it is not a code
  signature.

### Changed

- **The local API is split by resource.** Download, queue, subscription,
  site-sign-in and system routes now have separate registrars while keeping the
  same dependency contract and HTTP behavior. `create_api` retains the shared
  request guards, error handling and rate-limit state instead of owning all 27
  handlers in one closure.
- **The full-suite floor recognizes the real collection shape.** Running the
  configured test root explicitly still enforces the floor, while intentional
  ignore and deselect filters do not produce a false failure. The terminal
  bucket check now drives the live Download page for every shared terminal
  state instead of checking status labels alone.

- **A green test run now means the full suite ran.** Full runs fail below the
  recorded execution floor and name skipped yt-dlp or Qt groups. Brittle tests
  that searched implementation text now exercise the real UI, API, queue and
  subscription behavior instead.
- **Long translations get their own visual checks.** History, Settings,
  Sign-ins and Subscriptions now render in German and Arabic RTL. Column and
  section labels can grow past their old pixel widths instead of being cut
  off.

## [2.10.0] - 2026-08-21
### Changed

- **The window no longer waits on the disk to write a log line.** Every status
  change wrote to the log file from the main thread, holding a lock every
  worker thread also wanted. Lines are handed to a writer thread now, still in
  order, and the crash log is still written before the process ends.

### Added

- **A Scoop manifest.** `packaging/scoop/astra-downloader.json` installs the
  one-folder build with checkver and autoupdate wired to the release feed. The
  same gate that keeps the winget digest honest now checks the Scoop hash
  against the staged archive, so a manifest naming bytes nobody published
  fails the release.

### Changed

- **Settings groups describe what is in them.** A section headed Language held
  Theme and Language; one headed Tray behavior held the yt-dlp auto-update and
  the clipboard link grabber. With 77 settings the heading is the only
  navigation aid there is, so the yt-dlp update toggle moved to Maintenance,
  clipboard staging got its own group, and the two misnamed headings became
  Appearance and language, and Window and tray.

### Fixed

- **Long names are measured in bytes, which is what Windows counts.** A title
  made of emoji fills a folder or file name four times faster than its
  character count suggests, so a custom output template with a character limit
  bounded nothing and the preview reported a path shorter than the one yt-dlp
  was about to write. Every free-text field in a template is byte-bounded now,
  the preview truncates the way yt-dlp does, and a single folder name over the
  per-name limit is called out instead of being reported as a long path.

- **Native-host extension IDs are validated when they are saved.** The setting
  only trimmed its text, so a hand-edited config could show IDs the browser
  registration would silently drop. What the field stores is now what actually
  gets registered.

## [2.9.0] - 2026-08-21

### Added
- **Status messages now reach screen readers.** Changing a label's text tells
  assistive technology nothing on its own, so a screen-reader user who pressed
  Download and got rejected heard silence. Status labels now raise a Qt
  accessibility alert whenever their text changes, which is WCAG 2.2 SC 4.1.3.
  Repeating an unchanged message stays quiet, so a live preview does not
  interrupt a screen reader on every keystroke.
- **Astra Deck can pair Chrome and Edge itself.** Download buttons in the
  extension used to fail until you pasted the 32-letter ID from
  chrome://extensions: native messaging is the only token channel, and that
  ID was never in the host manifest after a fresh install. The extension now
  posts its ID to a loopback `/pair-extension` route (Origin-bound, no token
  echo). Source runs register a cmd wrapper so the browser can launch the
  native host without a packaged exe.
- **Download health now starts with a useful summary.** Six readiness checks
  stay one click away when everything is ready and open automatically when a
  repair is needed.
- **Less common download controls have a More options section.** Password,
  clip range, and custom file name fields remain available without crowding
  the normal paste-and-download path.

### Changed
- **The download you just started is visible without scrolling.** At the
  standard 1120x760 window an active download's queue row now sits wholly
  inside the page, and reaching it takes no scrolling at all.
- **Every button has its own icon now.** Fifteen of them shared one
  three-lines-and-dots default, which meant Remove and Undo remove were the
  same picture, as were Restore defaults and Undo defaults, and the
  Subscriptions and Settings rail entries. Sixteen new glyphs cover the
  buttons that had none, and the default is back to meaning "unnamed".

- **A subscription scan no longer rewrites the whole archive per candidate.**
  Reserving and queueing each item used to serialize and fsync the entire
  document, up to 20,000 records, twice per candidate, while holding the lock
  the window and `/health` also take. A 50-item scan measured 102 writes and
  598 ms; it now takes 3 writes and 11 ms.
- **The Qt binding is now PySide6 instead of PyQt6.** Astra Downloader's own
  code is MIT, and PyQt6 offered only GPL-3.0 or a paid Riverbank entitlement,
  which left the licence of the shipped executable genuinely unsettled. PySide6
  comes from the Qt Company under LGPL-3.0, so the combined binary has a clean
  route. `AstraDownloader-onedir.zip` is the artifact that keeps the Qt
  libraries replaceable, and it ships with every release for that reason. The
  one-file executable grew by about 2.9 MB.

- **Release builds now run on CPython 3.13.** python.org shipped no Windows
  installer after 3.12.10, so the build interpreter had been sitting on a
  branch that gets no more binaries. Running from source still works on 3.11
  and newer. Every `py -3.12` call in the scripts, gates and docs moved with
  it.

- **The release build now uses PyInstaller 6.22.2.** 6.22.1 closed
  GHSA-9fxf-4qw3-ghmr, and 6.22.2 fixed the spurious security-validation error
  a one-file executable raises when it is launched through a Windows symlink or
  junction, which portable copies on mapped folders hit.

- **The reviewed yt-dlp is now 2026.08.19**, the build the managed auto-update
  actually fetches. The extractor smoke runs against it, and against the
  managed executable with the shipped hardening flags, so the wheel and the
  standalone build are both proven before a release.
- **The active queue stays in the first Download viewport.** The primary
  link, media choices, health summary, and first queue row now fit at the
  standard 1120 by 760 window size.
- **Settings actions remain visible while the form scrolls.** Save Changes,
  Restore defaults, and the saved or unsaved status now sit in a fixed action
  bar.
- History, sign-in, and subscription filters use the same bounded surface,
  while cards, status callouts, select menus, scrollbars, and row hover states
  share one clearer visual hierarchy in dark and light themes.
- Playlist review now gives every video a distinct row, readable duration,
  accessible selection label, useful empty state, and a clear queue action.
- Command and diagnostics reviews now keep their copy actions visible, report
  success in place, distinguish primary and secondary actions, and explain
  what their redacted read-only content contains.
- Browser-profile controls no longer crowd the sign-in actions, History uses
  plain missing-value labels, and pagination reads naturally at a glance.
- Recovery messages now use short sentences with direct next steps instead of
  punctuation-heavy fragments across setup, downloads, updates, and sign-ins.

### Fixed
- **A version mismatch with the browser extension says so.** The downloader has
  refused too-old extensions with a named 426 since 2.7.0, but the extension
  reported it as a lost connection and offered to repair a downloader that was
  running fine. Astra Deck now names both directions: an extension older than
  the downloader accepts, and a downloader newer than the extension
  understands.
- **An Add subscription during a scan is saved immediately again.** A scan
  batched its writes across the whole store rather than its own thread, so
  anything else saved while a scan was running reported success with nothing on
  disk.
- **A scan interrupted midway no longer re-queues what it already started.**
  Every claim is written before the first download is queued, so a restart
  matches the restored downloads against their archive entries instead of
  treating them as new.

- **The catch-reason gate now covers handlers that swallow without `pass`.**
  It only examined handlers whose body was nothing but `pass`, so every
  `except Exception: return None` went unread. It now examines any broad
  handler that neither logs, re-raises, nor carries the error into what the
  caller gets back, and 34 more of them say in one line why discarding the
  failure is the right answer there.
- **Provisioning the Deno runtime works again.** Deno publishes its checksum
  as PowerShell `Get-FileHash` output rather than the `sha256sum` layout yt-dlp
  and FFmpeg use, and the parser did not recognise it. The verification refused
  the runtime rather than letting it through, which was the right call, but it
  meant a JavaScript runtime could never be installed from Deno. The sidecar
  parses now, and a digest still has to name the file it belongs to.
- **`npm run check` passes every gate except the release tag.** Staging
  resolves the exact version and SHA-256 that each runtime helper's rolling
  download alias currently points at, records them in the licence policy, and
  the inspection accepts an alias only when a resolved digest accompanies it.
  The licence inventory is down from 18 open issues to none.
- **YouTube downloads no longer send the dead `android_vr` player client.**
  yt-dlp 2026.08.19 403s that client, and auto-update would fetch it while
  argv still listed it last in the token-exempt chain.
- **Cookie jars that make a public YouTube video UNPLAYABLE are named as
  such.** Those logs used to classify as sign-in-required and tell you to
  add cookies. The downloader now retries once without the jar, and the
  recovery copy tells you to skip the YouTube sign-in.
- **A SABR leftover 360p run is no longer marked complete.** yt-dlp exits 0
  after downloading the combined stream; the queue now treats the SABR
  warning as a failure even when progress lines bury it.
- **The Windows system-proxy setting actually saves.** Toggling it and
  clicking Save reported success while the config kept the old value.
- **Keyboard focus stays visible on invalid Settings fields.** The error
  border used to outrank the focus ring.
- **Buttons that change their label now update the name a screen reader
  hears.** Start/Stop server, Pause intake, Saved, and the yt-dlp update
  check used to keep their original accessible name.
- **History export no longer stops at 500 filtered rows.**
- **Clearing a clipboard-staged link lets the same copied URL stage again.**
- **A stale format probe no longer blocks looking up the same URL.**
- **Playlist review now waits for the first-run folder confirmation.**
- **Importing a settings bundle restarts the local API when the port
  changed.** The restore-defaults path already did this.

## [2.8.0] - 2026-08-14

### Added

- **Chrome and Edge can pair from the Browser extension page.** The Astra
  Deck handoff was dead on every Chromium browser: the native-messaging
  host is the only token channel, and the extension-ID setting that
  registration requires had no input anywhere in the GUI. The Extension page
  now takes the ID from chrome://extensions, validates it before it can
  reach a manifest's `allowed_origins`, registers the Chrome and Edge hosts
  immediately on save, and revokes them when cleared. Firefox remains
  registered automatically.
- **A playlist can be reviewed before anything downloads.** A pasted playlist
  URL shows a Review playlist button that previews the items and lets you
  select which ones to queue; only the committed selection enters the queue.
- **Every job can show the exact command it ran.** The queue context menu's
  "View yt-dlp command" opens the argv the job executed with credentials,
  tokens, PO tokens, and cookie paths redacted, and the redacted diagnostics
  bundle carries the same command line for recent finished jobs.
- **Progress names the pipeline step.** Queue rows report fetching metadata,
  downloading, merging, extracting, embedding metadata, and generating
  subtitles as distinct stages, and `/queue` and `/status/<id>` expose the
  step so the extension can show it too.

### Changed

- **HTTP dependency floors raised and certifi declared.** Werkzeug's floor
  moves to 3.1.8 (quoted list-header parsing, Transfer-Encoding as a set,
  host validation, empty `Request.host` on an invalid header), requests to
  the maintained 2.34 line, and certifi — a trust store, not a library — is
  now declared explicitly instead of riding transitively at whatever version
  the resolver picked. The dependency-policy gate pins all three floors.
- **Deno now has a security floor separate from its runtime floor.** A
  provisioned Deno below 2.8.1 (the release that closes the 2026-05-27
  advisory batch) is refreshed even though yt-dlp would still accept it, and
  the readiness panel names which floor was missed.

### Fixed

- **History no longer deep-copies the subscription archive on every
  refresh.** Merging archive records into the History view copied all
  20,000 possible records — nested payloads included — under the store lock,
  on the Qt main thread, per refresh. A scalar projection now copies only
  the eight fields History reads, on both the GUI and `/history` paths.
- **Icons render sharp on scaled displays.** Every line icon was an 18-pixel
  bitmap upscaled by Qt at 125/150/200 % display scaling. The backing pixmap
  is now allocated at the device pixel ratio, so strokes stay crisp.
- **The completion counter and shutdown cancellation are thread-safe.** The
  session's completed-downloads tally was a bare increment shared by all
  worker threads (losing counts under contention), and shutdown mutated
  download records outside the manager lock while workers wrote the same
  fields under it. Both now hold the lock; a 48-download, 8-thread hammer
  test requires an exact tally.
- **Windows system binaries are invoked by absolute path, with timeouts.**
  `icacls`, `powershell`, and `schtasks` were spawned by bare name, which
  CreateProcess resolves through the current working directory before PATH —
  and the icacls call is the one that applies the cookie jar's owner-only
  ACL. All six sites now resolve through `%SystemRoot%\System32`, every
  `subprocess.run` in the package carries a timeout, and a test pins both
  properties so a bare-name spawn cannot come back.
- **Status messages carry a visible tone.** "Download queue is full" used to
  render in the same grey as "Clip ranges apply to a single link" — every
  status label set a `state` property that no stylesheet rule matched. All
  five status surfaces (download, history, sign-ins, subscriptions,
  first-run) now share the settingsStatus tone convention, so an error is
  red, a success green, and a warning amber, with a test that fails when a
  tone value gains no matching stylesheet rule.
- **Concurrent subscription scans are capped.** Requesting a scan spawned an
  unbounded thread per subscription, each running its own yt-dlp probe — at
  the 100-subscription cap, "Scan now" down the list could hold 100
  concurrent processes. A bounded gate now allows two at a time; the rest
  wait their turn and none are dropped.
- **The winget manifest digest is generated, and the gate compares it.** The
  2.7.0 manifest carried an `InstallerSha256` that matched no artifact in
  existence, and `check:versions` only confirmed it was 64 hex digits.
  `npm run release:stage` now writes the staged executable's digest into the
  manifest, and the version gate fails when the two differ.
- GUI tests now default to Qt's offscreen platform, with an explicit
  `ASTRA_DOWNLOADER_ALLOW_ONSCREEN=1` opt-out for native-display checks.
- A JavaScript-runtime version-parser fault is no longer reported as a probe
  failure: only the subprocess call sits inside the probe's exception
  handler, so a parser bug surfaces loudly instead of masquerading as
  `runtime-probe-failed`.

## [2.7.0] - 2026-08-11

### Changed

- **yt-dlp capability gaps are now covered.** Subtitle requests can exclude
  live chat and translated catalogues, pause between tracks, and use the
  safer JavaScript and color argv defaults; format sorting prefers richer and
  original-language audio, while the clip controls add URL-relative and
  last-30-second selectors.
- **Release dependencies now follow the current secure graph.** PyInstaller,
  curl_cffi, certifi, PyQt6_sip, cffi, and packaging are refreshed; curl_cffi's
  CLI-only Rich stack is no longer carried by the release environment, while
  Qt 6.11.1 and setuptools 83 remain deliberately held.

### Fixed

- **The download cookie cap matches the store that accepts them.** `/download`
  truncated to a hardcoded 200 while the sign-in store keeps 400, so a jar the
  store held whole was halved on the way to yt-dlp and the only symptom was a
  failed sign-in. The bound is now the store's, and a truncated request says so
  in its response.
- **Subscription schedules no longer drift.** The next scan is anchored to when
  the previous one started rather than when it finished, so a two-minute scan on
  an hourly subscription no longer slips about 48 minutes a day; a scan that
  outruns its own interval still schedules forward instead of queueing a
  backlog.
- **A retry-exhausted candidate reads one archive entry.** It deep-copied the
  entire 20,000-entry archive under the store lock, once per candidate, to read
  two fields.
- **Expired recovery-precondition entries are dropped.** The cache kept one
  entry per URL for the life of a process that runs for days.
- **The local API version is a contract rather than a number.** `/health` now
  advertises the oldest client wire version this build serves, and a client that
  sends `X-MDL-Api` below it gets a named 426 with a remediation instead of
  drifting into wrong answers. A client that sends no version — which is every
  shipped Astra Deck today — is served exactly as before.

- **A release carries a lock file and an SBOM.** `npm run release:provenance`
  writes a CycloneDX 1.6 document carrying the fields CISA's 2026 minimum
  elements require, and a PEP 751 `pylock.toml` resolved against PyPI with a
  SHA-256 for every wheel and sdist. Staging now refuses to proceed when either
  is missing or when the SBOM describes a different binary, so a release cannot
  ship last build's inventory beside a fresh executable.

- **Downloads can inherit the proxy Windows is configured with.** A Settings
  option, off by default, reads the per-user WinINET configuration and shows the
  resolved value before you save it. A proxy typed by hand always wins, a
  disabled proxy is never read from a stale registry value, and the option stays
  out of settings bundles because it describes one machine's network.

- **A download can carry its own file name.** "Save as" on the Download page,
  and `outputName` through the local API, name a single download's output; the
  extension is still added by yt-dlp. The name is a stem, never a path: folder
  separators, drive letters, `..`, `%` template syntax, control characters and
  Windows reserved device names are refused rather than sanitized, the resolved
  path is proved to stay inside the download folder, and a name is re-checked
  when the durable queue is restored so an older build's record cannot become an
  output path after a restart.

- **`npm run check` reports every gate.** The `&&` chain meant the first red
  gate hid the six behind it; a runner now executes all of them, prints a
  per-gate PASS/FAIL summary, and treats a gate that cannot be spawned as a
  failure rather than a skip.
- **Five dependency licences resolved from their embedded texts.** `blinker`
  (MIT), `colorama`, `itsdangerous`, `jinja2` (BSD-3-Clause) and `packaging`
  (Apache-2.0 branch of its dual licence) declared their licence only through a
  trove classifier, which the resolver deliberately refuses to guess from. Each
  now carries a reviewed policy entry citing the wheel's own licence file.
- **The version gate fails when a version was never tagged.** Five version
  sources agreeing with each other said nothing about whether that version ever
  reached a user.

- **History is now a durable, visible record.** Settings controls its local
  retention cap, the History page shows the active limit and searches URLs,
  subscription archive rows appear without duplicate URLs, and `/history?url=`
  reports an exact cross-store lookup.
- **Media-server sidecars are opt-in.** Completed downloads can convert
  yt-dlp metadata into Kodi/Jellyfin-compatible item NFO files and channel
  `tvshow.nfo`/`season.nfo` files with stable provider IDs.
- **Download pre-flight names known failure causes.** The Download page and
  `/health` now classify stale yt-dlp, missing JavaScript runtime, FFmpeg
  security/filter gaps, expired sign-ins, anonymous GitHub API exhaustion, and
  token-provider failures, with a safe action for each condition.
- **Native browser pairing now covers the Chromium family safely.** Chrome,
  Edge, Brave, Vivaldi, Opera and Chromium receive their own per-user
  registry roots, while Chrome and Firefox extension IDs are validated before
  they enter a native-host manifest.
- **Output-template diagnostics now follow the download path.** Literal `%%`
  fields stay literal, Windows-safe filename sanitization and reserved names
  are previewed, and MAX_PATH is checked against the private staging prefix as
  well as the finished-file destination. The local Whisper model URL is pinned
  to its reviewed Hugging Face revision.
- **Settings controls are clearer to assistive technology.** Browse buttons
  identify their destination, and the site-profile editor contributes safe
  names, domains and format values to Settings search without indexing proxy
  credentials.
- **Companion self-update handoff is more observable.** The production path
  records a verified digest as activation-pending before the detached helper
  takes over, and the helper rechecks fast health probes when a process exits
  during the `Wait-Process` handoff race.
- **SponsorBlock now carries visible attribution.** The optional Settings
  control links to SponsorBlock and identifies its CC BY-NC-SA 4.0 data/API
  alongside Astra Downloader's MIT licence.
- **Empty pages now explain the next action.** History, subscriptions,
  sign-ins, and the browser-extension log offer a useful recovery or setup
  action instead of leaving a blank panel.
- **The companion UI render harness now covers focus, DPI, locales, and recovery states.**
  It renders the bundled locale set, 1x/1.25x/2x scale fixtures, genuine empty
  states, filters, pagination, queue recovery, format probing, and invalid settings.
- **The default pytest command now preserves its own result summary.** Tests
  use an ignored project-local base directory, so stale account-wide temp
  permissions cannot replace a green run with a teardown traceback.
- **The Qt companion shell is split by page boundary.** Download, History,
  Sign-ins, Subscriptions, Browser extension, and Settings builders now live in
  focused mixin modules, while shared visual primitives and the injected core
  contract remain centralized. Cross-module translation discovery keeps the
  German catalogue complete across all 759 companion strings.
- **Safety regressions now test observable behavior.** Download argv policy,
  CORS size rejection, queue-idle refresh, folder-picker watchdogs, settings
  recovery, and window teardown are exercised through calls and fixtures rather
  than line-sensitive function-source inspection.
- **Companion translation extraction now follows the UI boundary.** Qt setter
  roots, constant picker loops, tray/dialog copy, and dynamic status templates
  are catalogued together; the shipped German catalogue remains complete and
  the translation gate now covers 759 companion strings.
- **The language picker now advertises only usable translations.** English and
  German clear the 80% coverage floor; partial catalogues remain available for
  legacy configurations and RTL compatibility, but are no longer presented as
  finished choices. The translation gate enforces the same floor for advertised
  locales.
- **The companion now follows light and dark system themes.** The new Theme
  setting supports system, light, and dark modes; native title bars, controls,
  inline status colors, generated icons, and the hidden render harness all
  track the selected scheme.
- **Undo snapshots survive restarts.** History clears, sign-in and subscription
  removals, settings imports, and Restore defaults now persist adjacent recovery
  journals; the companion restores their affordances on launch and cleans up
  snapshots only after a successful undo.
- **Interactive control boundaries now meet the non-text contrast floor.**
  Resting, disabled, hover, input, menu, text-edit, ghost-button, and
  checkbox boundaries are declared against their actual stylesheet fills.
- **Download options reflow at the minimum window size.** Profile, media,
  destination, and clip controls use readable rows inside a scrollable page;
  the headless large-font fixture now checks their bounds, overlap, and text.
- **Local transcription uses a verified whisper.cpp sidecar.** Setup now fetches
  the pinned CLI and sibling DLLs, probes the SRT capability, and reports a
  missing runtime before a job starts; successful media stays complete when
  subtitle generation fails, with a retry that regenerates only the SRT.
- **Local transcription follows the current whisper.cpp release.** The pinned
  v1.9.2 sidecar is checksum-verified, SRT output splits on words, and the
  CLI thread count follows the host CPU count within a safe bound.
- **Repeated site refusals now open a per-domain circuit.** Three consecutive
  bot/sign-in or HTTP 403 failures pause later items for that registrable
  domain, keep other hosts flowing, and show the retry countdown in the queue.
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
- **Local transcription scratch now stays out of download folders.** WAV and
  intermediate SRT files use the managed per-download staging directory, with
  a conservative disk-space preflight before either helper starts.
- **Release artifacts now share build provenance.** The one-folder archive carries
  the same version and one-file analysis ID as the executable metadata; staging
  rejects mismatches and builds remove stale root artifacts first.
- **The winget manifest now follows the shipped version gate.** Its directory,
  package fields, release links, and installer checksum target v2.6.0 together.
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
