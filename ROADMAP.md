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

- [ ] P3 | AD-161 | A template ending in a fixed extension gets no NFO
  Why: `normalize_output_template` only needs `%(ext)s` somewhere in the template. One that ends in a literal extension makes yt-dlp name the metadata `Title.mp4.info.json`, which doesn't pair by stem, so that file gets no NFO. (Plausible; confirm first.)
  Acceptance: WHEN a delivered file's `<stem>.info.json` is missing but `<name>.info.json` exists beside it, the NFO step SHALL use that one.
  Where: `astra_downloader/download.py` `write_media_server_sidecars`.
- [ ] P3 | AD-162 | Two extension pairings at once can lose an ID
  Why: `pair_browser_extension` reads the saved Chrome IDs, then writes the joined list back. Two requests between those steps each save a list without the other's ID.
  Acceptance: WHEN two IDs pair at the same moment, both SHALL be saved.
  Where: `astra_downloader/astra_downloader.py` `pair_browser_extension`.
