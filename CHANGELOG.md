# Changelog

All notable changes to Astra Downloader are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases before 2.0.0 were made from the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) repository, where this
program lived as a companion service. That history is preserved in this
repository's git log.

## [Unreleased]

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

### Changed

- **Running from source needs Python 3.11.** The pinned yt-dlp raised its
  minimum in 2026.07.04, so on 3.10 the dependency install failed before the
  version guard written to explain the problem ever ran.

### Fixed

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
