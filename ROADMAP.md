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
- [ ] P1 | AD-163 | Whisper setup can overwrite a good rollback copy with a broken runtime
  Why: `provision_whisper_runtime` retains the current folder as `.whisper.last-known-good` before downloading, checking only `whisper-cli.exe`'s size. A runtime that's present but won't run (a DLL removed) replaces the working rollback copy, and a failed upgrade then restores the broken one.
  Acceptance: WHEN the current runtime isn't usable, or the download fails, the rollback copy SHALL stay as it was.
  Where: `astra_downloader/astra_downloader.py` `provision_whisper_runtime` (around 2389) and `retain_managed_binary_rollback`.
- [ ] P2 | AD-164 | A transcription disk-space skip names the wrong drive
  Why: the check now runs against the staging folder on the install drive, but the advice still says to free space on the destination drive and retry the download.
  Acceptance: WHEN transcription is skipped for disk space, the advice SHALL name the install drive and say a subtitle retry is enough.
  Where: `astra_downloader/download.py` around 957 and 6281.
- [ ] P2 | AD-165 | A subtitle error in the main download path marks a finished download failed
  Why: an exception before `_transcribe_with_held_model`'s own try (runtime probe, intermediate dir) reaches the generic except in `_run_download`, which overrides the complete status.
  Acceptance: WHEN local subtitles fail with an exception after the media finished, the download SHALL stay complete with a transcription failure, as the subtitle-retry path already does.
  Where: `astra_downloader/download.py` around 7443 and 7455.
- [ ] P3 | AD-166 | Whisper follow-ups from the 2026-10-09 review
  Why: (a) an unknown language is skipped for the next listed one instead of `auto`, and YouTube's `fil` isn't mapped to `tl`; (b) the startup leftover sweep runs under `--visual-smoke`, which skips the single-instance guard; (c) the held model blocks a same-name model re-fetch for the whole transcription; (d) a subtitle retry with nothing to do ends complete at 0%; (e) `test_a_current_or_rollback_pinned_runtime_is_left_alone` doesn't prove a stale stamp triggers a refresh.
  Acceptance: each of (a) to (e) fixed or covered by a test that fails on today's code.
  Where: `astra_downloader/download.py` `subtitle_language_for_transcription`, `_run_local_subtitles`; `astra_downloader/astra_downloader.py` `main`; `astra_downloader/test_health.py`.
- [ ] P3 | AD-167 | Pairing and launcher loose ends
  Why: Register on the Browser extension page writes the ID field outside `_EXTENSION_ID_SAVE_LOCK`, so it can drop an ID a route just paired; `write_native_host_launcher` uses a fixed `.tmp` name; unticking every SponsorBlock box saves "" (every category), so there's no way to pick none.
  Acceptance: each fixed, with a test.
  Where: `astra_downloader/gui.py` `_apply_native_chrome_ids`, `astra_downloader/astra_downloader.py` `write_native_host_launcher`, the SponsorBlock save in `gui.py`.
