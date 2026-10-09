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

- [ ] P3 | AD-162 | Two extension pairings at once can lose an ID
  Why: `pair_browser_extension` reads the saved Chrome IDs, then writes the joined list back. Two requests between those steps each save a list without the other's ID.
  Acceptance: WHEN two IDs pair at the same moment, both SHALL be saved.
  Where: `astra_downloader/astra_downloader.py` `pair_browser_extension`.
