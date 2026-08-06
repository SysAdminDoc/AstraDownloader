# Roadmap

Actionable items only — work a coding agent can pick up and implement without
external dependencies. Completed items are deleted; shipped work lives in git
history and `CHANGELOG.md`.

## P2 — Downloader-first follow-ups from the v2.0.0 split

- **Format probing before download.** `/formats` already returns the real
  format table for a URL. The GUI's quality picker is a fixed list
  (Best/2160/1440/1080/720/480) that does not know what the pasted link
  actually offers, so a user can pick 2160p on a 720p video and only learn
  the truth from the result. Probe on paste (debounced, cancellable) and
  reduce the picker to what exists.

- **Per-download destination.** `DownloadPath` / `AudioDownloadPath` are
  global settings and `/pick-folder` already opens a native picker. The paste
  box should be able to override the destination for one download without
  changing the default.

- **Drag and drop onto the window.** A downloader should accept a dropped
  link or a dropped text file of links. `_start_quick_download` already takes
  a whitespace-separated batch, so this is a `dragEnterEvent` /
  `dropEvent` pair on the Download page plus the existing batch path.

## P3 — Unaudited — needs a pass

Carried over from the Astra Deck audit backlog: these companion areas were
never given a dedicated audit pass.

- The subscriptions surface (`astra_downloader/subscriptions.py`, 866 lines)
  and its GUI page.
- `astra_downloader/build.py` and the release staging scripts.
- The GUI's light-theme behaviour. The product is dark-first by design, but
  nothing verifies what happens under a light Windows theme.
