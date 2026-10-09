# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## v2.15.2 marketing delivery

The README opens with one evergreen share card and keeps release numbers in text and badges. The usage guide and build guide separate verified product behavior from site-dependent claims. A dated concept archive retains the original source and every review capture. The package review runs offscreen in a new disposable profile. Existing feature work below remains open.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1


### P2

- [ ] P2 | AD-131 | Digit fields can still form LPT1 or COM1 folders
  Why: the template check renders every field as `_` for its "all present" pass, which can't stand in for a number, so `LPT%(playlist_index)s/%(title)s.%(ext)s` and `COM%(track_number)s/...` pass and create reserved folder names on short playlists.
  Where: `astra_downloader/config.py` reserved name check in `normalize_output_template`. Add a pass that renders numeric fields as a digit. `Season %(season_number)s/...` must still pass.
- [ ] P2 | AD-132 | Title filter worker outlives a crashed or self-updating app
  Why: the worker isn't in a kill-on-close job object. If the app exits through `os._exit(0)` during self-update, or crashes, while the child is inside a runaway `re.search`, the child keeps burning a core, and in the frozen build it's `AstraDownloader.exe`, so the update's `os.replace` hits a locked image and ends as `activation-failed`.
  Where: `astra_downloader/config.py` `_TitleFilterWorker._connection`. Assign the child to a Job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and keep the handle open for the parent's life.
- [ ] P2 | AD-133 | A slow title filter respawns its worker on every title
  Why: each timeout kills and respawns the worker, so a pattern that times out on most titles costs one second plus a spawn per title under the lock previews also wait on, and a worker that can't start costs up to 60 s per title.
  Where: `astra_downloader/config.py` `_TitleFilterWorker.search`. Fail fast as `filter-timeout` for a cooldown after three timeouts in a row on one pattern, and after a failed start.

### P3

- [ ] P3 | AD-134 | Small filter and profile import leftovers
  Why: `sanitize_subscription_filters` strips patterns, so `" live "` is saved altered although filters are meant to be stored as typed. A refused profile import runs its folder preflight `mkdir` before the overflow refusal and can leave empty folders behind.
  Where: `astra_downloader/config.py` `sanitize_subscription_filters` and the profile import preflight. Strip only to decide blankness, and refuse before creating any folder.
- [ ] P3 | AD-71 | Areas the 2026-08-22 audit did not reach
  Why: recorded so the next pass starts where this one stopped rather than re-covering it. Not audited: the PyInstaller build pipeline beyond running it; the native messaging host registration; the Windows shell integration (jump list, `RegisterApplicationRestart`, Recycle Bin delete) beyond reading it, since driving it needs a real desktop session; the whisper transcription path; the SponsorBlock and NFO writers; and the browser extension, which is a separate repository. The GUI was exercised offscreen through `npm run smoke:gui` and the Qt test suite, never driven interactively, so nothing here rests on watching a real window.
  Where: `astra_downloader/build.py`, the native-host block in `astra_downloader/astra_downloader.py`, the taskbar and jump-list block in `astra_downloader/gui.py`, the transcription block in `astra_downloader/download.py`.


