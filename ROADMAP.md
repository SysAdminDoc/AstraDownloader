# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## v2.15.2 marketing delivery

The README opens with one evergreen share card and keeps release numbers in text and badges. The usage guide and build guide separate verified product behavior from site-dependent claims. A dated concept archive retains the original source and every review capture. The package review runs offscreen in a new disposable profile. Existing feature work below remains open.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1


### P2

### P3

- [ ] P3 | AD-140 | SponsorBlock category labels are never translated
  Why: the Settings page builds the category checkboxes from a dict and calls `tr()` on its values, so the string extractor never sees "Self-promotion", "Recap or preview" and the rest, and the German interface shows them in English. Same shape as the readiness row labels fixed in 9bd60f8.
  Where: `astra_downloader/gui_settings_page.py` `category_labels`, `scripts/build-companion-translations.py`. Make the labels extractable (literal `tr()` calls or the 9bd60f8 approach), add German, re-run the build script.
- [ ] P3 | AD-135 | Audit the NFO and SponsorBlock writers (split from AD-71)
  Acceptance: WHEN `build_media_server_nfo`, `build_tvshow_nfo`, `build_season_nfo`, `write_media_server_nfo` and the SponsorBlock argv are read against what yt-dlp, Kodi and Jellyfin expect, every confirmed defect SHALL be fixed with a test or filed as its own item.
  Where: `astra_downloader/download.py` (`_nfo_*`, NFO writers), `astra_downloader/config.py` `normalize_sponsorblock_categories` and the SponsorBlock flags in the yt-dlp argv.
- [ ] P3 | AD-136 | Audit the Whisper transcription path (split from AD-71)
  Acceptance: WHEN the model and runtime provisioning, the FFmpeg and whisper.cpp argv, the progress parser, the watchdog and the temp file cleanup are read end to end, every confirmed defect SHALL be fixed with a test or filed as its own item. A live run with a real model stays in Roadmap_Blocked.md (AD-56).
  Where: `astra_downloader/download.py` (`build_whisper_*`, `parse_whisper_progress`, the transcription block near `_mark_transcription_failure`), `astra_downloader/astra_downloader.py` (`provision_whisper_*`, `_retire_other_whisper_models`).
- [ ] P3 | AD-137 | Audit the native messaging host registration (split from AD-71)
  Acceptance: WHEN the manifest builder, the registry writes, the launcher and the unregister path are read against Chrome's and Firefox's native messaging rules, every confirmed defect SHALL be fixed with a test or filed as its own item. The stdio channel against a live browser stays in Roadmap_Blocked.md (AD-56).
  Where: `astra_downloader/astra_downloader.py` (`build_native_host_manifest`, `register_native_host_registry_value`, `unregister_native_host_registry_value`, `write_native_host_launcher`, `native_host_executable`, `argv_requests_native_host`).
- [ ] P3 | AD-138 | Audit the PyInstaller build script beyond running it (split from AD-71)
  Acceptance: WHEN `build.py` is read for environment drift checks, collected data and native origins, the runtime hooks and failure handling, every confirmed defect SHALL be fixed with a test or filed as its own item. Anything that only a build can show is listed as an owed release-venv build.
  Where: `astra_downloader/build.py`.


