# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

- [ ] P1 — AD-58 — A benign warning can still steer the failure path from `_apply_zero_exit_outcome`
  Why: the classification chain no longer re-decides from the joined output, but `_line_shows_sabr_capped_stream` still turns a single warning line into a `failed` result on an exit-0 run that wrote the file. It is now cleared between runs, so the stuck-forever case is gone; what remains is that one warning outranks a delivered file, and `sabr-limited` is not retryable, so the only route back is Download again.
  Where: `astra_downloader/download.py` `_consume_ytdlp_output` (the `sabr_capped_warning` write) and `_apply_zero_exit_outcome`.

- [ ] P1 — AD-59 — A disk-space check runs only for downloads the GUI starts
  Why: `estimate_download_bytes` / `check_download_disk_space` are called from `gui.py` before a paste-box download. Nothing on the API or subscription path calls them, so `insufficient-disk-space` is unreachable for an extension-initiated or scheduled download; those fail partway with whatever yt-dlp says instead. A subscription filling a disk overnight is the case that matters.
  Where: `astra_downloader/gui.py` (the two call sites), `astra_downloader/download.py` `start_download`, `astra_downloader/routes.py` `/download`.

### P2

- [ ] P2 — AD-60 — A site profile's download type is stored and never applied outside the paste box
  Why: `sanitize_site_profiles` validates and stores `DownloadType`, and `start_download` applies a profile's `VideoFormat`, `AudioFormat` and `Quality` but not its `DownloadType`. The only consumer is the GUI paste box. An API or subscription download for a profiled domain therefore ignores the audio-only or subtitles-only preference the user set for that site. Decide whether the field is a paste-box default (rename it, or say so in the setting's help text) or a profile rule, then make one true.
  Where: `astra_downloader/config.py` (`DownloadType` in the profile schema), `astra_downloader/download.py` `start_download`, `astra_downloader/gui.py` `_sync_quick_download_profile`.

- [ ] P2 — AD-61 — Six error toasts splice raw exception text and name no next step
  Why: `Could not read stored sign-ins: {error}`, `Could not read that file: {error}` (twice), `Could not write the bundle: {error}`, `Could not read that bundle: {error}`, `Could not export download history: {error}`, plus `{label}: {error}` paired with a bare "Test failed". Their siblings all end in a concrete action ("check disk permissions and retry"). These end in a Python exception string, unbounded in length, with no suggestion of what to do.
  Where: `astra_downloader/gui.py`, the seven `tr_format` sites listed above.

- [ ] P2 — AD-62 — A rejected link's reason is translated around, not translated
  Why: `describe_rejected_links` wraps `{reason}` in a translated frame, but the reason itself comes from the URL policy untranslated. A German build shows a German sentence containing an English clause.
  Where: `astra_downloader/gui_support.py` `describe_rejected_links`; the reasons originate in `astra_downloader/config.py` `normalize_url` and its callers.

- [ ] P2 — AD-63 — Tray notifications raise no accessibility event
  Why: every status label in the app announces itself through `StatusLabel.setText` / `announce_status`. The five `QSystemTrayIcon.showMessage` balloons bypass that path entirely, so a completion or a failure that fires while the window is minimised is announced to nobody. That is exactly when the balloon is the only report.
  Where: `astra_downloader/gui.py`, the five `showMessage` call sites; `astra_downloader/gui_support.py` `announce_status`.

- [ ] P2 — AD-64 — `_arm_host_backoff_wakeup` decides on liveness it does not hold
  Why: the timer is created under the lock and started outside it, so `current.is_alive()` is False for a timer another thread has installed but not yet started. Two threads can each install and start one; the loser is unreachable by `cancel_all` and fires anyway. The observed cost is a redundant daemon timer rather than a missed wakeup, which is why it is here and not above, but the check-then-act is real.
  Where: `astra_downloader/download.py` `_arm_host_backoff_wakeup`.

- [ ] P2 — AD-65 — `_persist_stop` is set by nothing
  Why: the queue writer thread has a stop event that is never signalled anywhere in the tree. Retirement relies entirely on the two-second idle timeout, and `cancel_all` does not stop the writer. Either wire the event into shutdown or delete it; as written it reads like a shutdown path that exists.
  Where: `astra_downloader/download.py` (`_persist_stop`, and the writer loop that reads it).

### P3

- [ ] P3 — AD-66 — `read_settings_bundle` and `ConfigStore` disagree about a boolean schema version
  Why: `read_settings_bundle` accepts `"schemaVersion": true` because `int(True) == 1`, while `ConfigStore._load_and_sanitize` rejects a bool for the same field on purpose. One of the two is wrong about what a version marker is.
  Where: `astra_downloader/config.py`, `read_settings_bundle` and `_load_and_sanitize`.

- [ ] P3 — AD-67 — Two interactive surfaces have no focus or selection styling
  Why: `QScrollArea` is keyboard-scrollable with `border: none` and no `:focus` rule, so a keyboard user scrolling a long list has no indication of where they are. `QComboBox QAbstractItemView` sets `selection-background-color` but the popup has no `::item` rule, so the keyboard highlight inside an open combo falls back to the platform default over a custom background. Neither is measured by the focus-ring test added this pass, because neither declares a ring to measure.
  Where: `astra_downloader/astra_downloader.py`, the `QScrollArea` and `QComboBox QAbstractItemView` rules.

- [ ] P3 — AD-68 — Three sibling spin boxes spell their units three ways
  Why: `' entries'`, `' seconds'`, `' s'`, `' MB'`, `' min'`. Two of them sit on the same Settings page. Pick one convention: spelled out, or abbreviated, not both.
  Where: `astra_downloader/gui_settings_page.py` (`setSuffix` at the retention, timeout and size fields), `astra_downloader/gui_subscriptions_page.py`.

- [ ] P3 — AD-69 — The playlist dialog calls the same thing a video and an item
  Why: "Select every video in this playlist preview" sits beside "Select playlist item {index}", and the confirm button says "Download selected" while the resulting toast says "Queued {count} items from playlist." The subscription archive has the mirror problem: "Captured subscription items" beside "The source no longer lists this video."
  Where: `astra_downloader/gui.py`, the `PlaylistStagingDialog` and `SubscriptionArchiveDialog` strings.

- [ ] P3 — AD-70 — The empty-state ETA is punctuation where every other empty state is a word
  Why: an unknown ETA renders as `--`. Everywhere else the app writes "Not set", "unknown", "Off", "No limit".
  Where: `astra_downloader/gui.py`, the download-card ETA field.
