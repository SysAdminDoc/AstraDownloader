# Roadmap

Actionable work only. Historical and completed roadmap material is archived in CHANGELOG.md; blocked work is kept in Roadmap_Blocked.md.

## v2.15.2 marketing delivery

The README opens with one evergreen share card and keeps release numbers in text and badges. The usage guide and build guide separate verified product behavior from site-dependent claims. A dated concept archive retains the original source and every review capture. The package review runs offscreen in a new disposable profile. Existing feature work below remains open.

## Research-Driven Additions

ID scheme: `AD-nn`, continue sequentially from the highest below.

### P0

### P1

- [ ] P1 | AD-142 | Local subtitles fail when downloads are on another drive
  Why: the finished SRT moves from the temp folder under the install dir to the video's folder with `os.replace`, which Windows refuses across drives. Install on C:, downloads on D: ends every transcription with "Unexpected local subtitle error."
  Acceptance: WHEN the temp folder and the video's folder are on different drives, the SRT SHALL land beside the video (copied there under a temp name, then renamed), and the temp copy SHALL be removed.
  Where: `astra_downloader/download.py` around 6349.
- [ ] P1 | AD-143 | A skipped transcription leaves a finished download marked failed
  Why: the job is set to `transcribing` before it waits for the transcription slot. If the second check then skips (subtitles turned off meanwhile, the video moved, an .srt appeared), it returns with that status still set, and the worker cleanup turns it into `failed` ("Download worker stopped before reporting a result"). The subtitle-only retry path does the same with `downloading`.
  Acceptance: WHEN the transcription step returns early for any reason, the download SHALL end `complete` (or keep its retry outcome), never `failed` by the worker cleanup.
  Where: `astra_downloader/download.py` around 6052, 6058 and 6076.
- [ ] P1 | AD-144 | Subtitle language "all" makes local subtitles fail
  Why: the language check accepts any 2 or 3 letters, so Subtitle languages `all` (saved as `all,-live_chat`) becomes `-l all`, and `eng`, `iw` and `und` get through the same way. whisper.cpp stops on a language it doesn't know, and the user sees "completed without producing an SRT sidecar".
  Acceptance: WHEN the configured subtitle language isn't one whisper.cpp knows, transcription SHALL run with `-l auto`.
  Where: `astra_downloader/download.py` `subtitle_language_for_transcription` (around 2595).

### P2

- [ ] P2 | AD-147 | Subtitles can't be retried after a disk-space skip
  Why: a failed disk check marks the item `complete` with `insufficient-disk-space`, which isn't in the subtitle-retry list, so after freeing space the retry says "Only failed or skipped downloads can be retried".
  Acceptance: WHEN a transcription was skipped for disk space, a subtitle retry SHALL be offered and accepted.
  Where: `astra_downloader/download.py` around 260 and 6123.
- [ ] P2 | AD-148 | Switching the Whisper model mid-transcription can delete the model in use
  Why: the model path is picked before the audio step. Saving base in Settings during that step provisions base and retires tiny, then whisper-cli starts on a deleted file. (Plausible; confirm first.)
  Acceptance: WHEN the model changes while a transcription is running, that transcription SHALL finish with the model it started with, or pick the new one after it exists.
  Where: `astra_downloader/download.py` around 6079, `astra_downloader/astra_downloader.py` `_retire_other_whisper_models` (around 2153) and `provision_whisper_model` (around 2217).
- [ ] P2 | AD-149 | The whisper.cpp runtime has no version stamp, so rollback always fails and it never upgrades
  Why: the runtime check never returns a version, so the version probe is empty and Roll back always fails with "retained-copy-unverified"; the rollback copy lives inside the `whisper` folder the next install swaps out; a working runtime is never replaced, so raising `WHISPER_BIN_VERSION` never reaches existing installs.
  Acceptance: WHEN `WHISPER_BIN_VERSION` changes, an existing runtime SHALL be replaced on the next setup, and Roll back SHALL restore a verified previous copy kept outside the swapped folder.
  Where: `astra_downloader/astra_downloader.py` around 1576, 2229 and 2526.
- [ ] P2 | AD-152 | The transcription disk check assumes an hour of audio
  Why: no download carries a duration, so every one is sized as one hour (about 115 MB). A 4 hour video writes about 460 MB to the install drive after passing a 147 MB check. The check also wants that space in the output folder, which only gets the small SRT. (Plausible; confirm first.)
  Acceptance: WHEN the duration is known (yt-dlp's info or an ffprobe), the WAV estimate SHALL use it, and the free-space check SHALL be against the temp folder's drive.
  Where: `astra_downloader/download.py` `estimate_transcription_wav_bytes` (around 3080) and around 6108.
### P3

- [ ] P3 | AD-156 | Whisper progress and interrupted setup leftovers
  Why: the progress bar sits at 0% through the audio step because ffmpeg's `progress=continue` lines never match the parser. Closing the app during setup stops the setup thread after 5 s and can leave half-downloaded model files and `.whisper.*.zip` or `.extract` leftovers in the install dir that nothing cleans up.
  Acceptance: WHEN ffmpeg reports progress, the bar SHALL move during the audio step, and WHEN the app starts, setup leftovers SHALL be removed.
  Where: `astra_downloader/download.py` `parse_whisper_progress` and the audio step, `astra_downloader/astra_downloader.py` provisioning.
- [ ] P3 | AD-157 | build.py's drift check doesn't pin the environment itself
  Why: it checks each pinned package's version but not that it runs in `.release-venv`, that nothing extra is installed, or that `PYTHONPATH` and `PYTHONHOME` are unset, so a global Python with the pins plus an optional import would bundle a package the license inventory never lists. The venv is clean today. (Plausible.)
  Acceptance: WHEN build.py runs outside `.release-venv`, with a package missing from the constraints, or with `PYTHONPATH` or `PYTHONHOME` set, it SHALL refuse.
  Where: `astra_downloader/build.py` around 95 to 183.
- [ ] P3 | AD-140 | SponsorBlock category labels are never translated
  Why: the Settings page builds the category checkboxes from a dict and calls `tr()` on its values, so the string extractor never sees "Self-promotion", "Recap or preview" and the rest, and the German interface shows them in English. Same shape as the readiness row labels fixed in 9bd60f8.
  Where: `astra_downloader/gui_settings_page.py` `category_labels`, `scripts/build-companion-translations.py`. Make the labels extractable (literal `tr()` calls or the 9bd60f8 approach), add German, re-run the build script.


