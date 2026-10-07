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


- [ ] P3 | AD-71 | Areas the 2026-08-22 audit did not reach
  Why: recorded so the next pass starts where this one stopped rather than re-covering it. Not audited: the PyInstaller build pipeline beyond running it; the native messaging host registration; the Windows shell integration (jump list, `RegisterApplicationRestart`, Recycle Bin delete) beyond reading it, since driving it needs a real desktop session; the whisper transcription path; the SponsorBlock and NFO writers; and the browser extension, which is a separate repository. The GUI was exercised offscreen through `npm run smoke:gui` and the Qt test suite, never driven interactively, so nothing here rests on watching a real window.
  Where: `astra_downloader/build.py`, the native-host block in `astra_downloader/astra_downloader.py`, the taskbar and jump-list block in `astra_downloader/gui.py`, the transcription block in `astra_downloader/download.py`.


- [ ] P3 | AD-128 | A tone label loses its padding when its tone changes
  Why: repolish (unpolish then polish) never delivers a StyleChange event, so a label whose tone changes keeps the frame width of its previous tone. It shows most in the high-contrast fixture, where the dashed warning bar overlaps the first letter, and in the RTL probe warning.
  Evidence: astra_downloader/gui_support.py repolish; the downloads-high-contrast-black and RTL probe-warning renders from 2026-10-06.
  Touches: astra_downloader/gui_support.py, astra_downloader/test_gui.py.
  Acceptance: Changing a label's tone recomputes its frame, pinned by a test that measures contentsRect before and after a tone change, and the two renders show no overlap.
  Complexity: S

- [ ] P3 | AD-129 | Two readiness labels stay English in German
  Why: the SABR and PO provider readiness rows render English labels in the German build while the rest of the Download page is translated.
  Evidence: the German Download-page render; astra_downloader/health.py readiness labels.
  Touches: astra_downloader/health.py or astra_downloader/gui_download_page.py, scripts/build-companion-translations.py, translation catalogues.
  Acceptance: Both labels reach the catalogues through the extractor and German carries them; the German render shows no English readiness label.
  Complexity: S
