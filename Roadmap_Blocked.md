# Blocked

Items that cannot be finished without something outside this repository —
credentials, a human decision, or a service. Moved here so `ROADMAP.md` stays
a list of work a coding agent can actually pick up.

## Translate the nine incomplete locales — needs native speakers

**State:** the machinery is done and shipped. `scripts/extract_companion_strings.py`
discovers every user-facing literal from the GUI's syntax tree (219 of them,
against the 21 a hand-written tuple used to declare), the generator builds all
eleven catalogues from that list, and `npm run check` fails when a string
reaches the UI without reaching the catalogues. German is complete at 219/219
and the render scenario asserts translated body copy on all six pages.

**What is blocked:** Arabic, Spanish, French, Italian, Japanese, Korean,
Brazilian Portuguese, Russian and Simplified Chinese each declare only their
five navigation strings. Filling them means 214 strings per locale, and doing
that without a speaker of the language produces a UI that is confidently
wrong in ways nobody here can review. The roadmap research already recorded
what comparable projects do: ytDownloader uses Crowdin across 23 languages
and Parabolic uses Weblate. Both outsource exactly this.

`py -3.13 scripts/build-companion-translations.py` prints current coverage per
locale, so the gap is measured rather than assumed.

**To unblock:** stand up a translation platform (Crowdin and Weblate are both
free for open source) and seed it from
`build/companion-translatable-strings.json`, or take contributions per locale.
Astra Deck issue #1 asks for Chinese, which makes `zh_CN` the first one worth
having.

**Not blocked, and still in `ROADMAP.md`:** the strings the extractor cannot
see because they are set at runtime through `setText()` rather than built
through `tr()` — the History column headers render as "Duration", "Format"
and "Quality" in every locale. That is a code change, not a translation.

## Submit the portable manifest to the official winget repository — needs a release

**State:** the application now has a self-contained `--portable` mode, a
GUI-free `--install` path, and a schema-valid manifest under
`packaging/winget/manifests`. The manifest points at the release artifact and
its checksum, and `winget validate` passes locally.

**What is blocked:** this repository has no published GitHub Release artifact
for the manifest's version, and official winget publication requires a release
URL with matching bytes plus a submission to `microsoft/winget-pkgs`. Creating
that release and submitting the manifest is external release coordination, not
a code change.

**To unblock:** publish the versioned `AstraDownloader.exe` and sidecar from a
release, update the manifest checksum if the release bytes differ, then submit
the manifest directory to the official winget-pkgs repository.

## Make `npm run check` pass — needs license-policy decisions

**State:** `npm run check` now runs every gate and prints a per-gate summary
instead of stopping at the first failure, so the six green gates are visible
rather than hidden behind the red one. The inspection is down from 32 issues to
18: `blinker`, `colorama`, `itsdangerous`, `jinja2` and `packaging` now carry
reviewed policy entries whose SPDX expression was read out of each wheel's
embedded licence text rather than guessed from a trove classifier.

**What is blocked, precisely — one decision:**

The Qt binding question is settled and no longer blocked. The application
moved from PyQt6 to PySide6-Essentials, which the Qt Company tri-licenses
LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. Taking the LGPL arm is what
lets an MIT application ship Qt inside a combined binary, and
`AstraDownloader-onedir.zip` is the artifact that keeps the Qt libraries
replaceable. Both entries are `decision: approved` in
`astra_downloader/license-policy.json`.

1. **Whether the runtime helpers may keep moving `latest` pointers.** `yt-dlp`,
   `ffmpeg` and `deno` account for the other 16 issues. The inspection refuses a
   distribution URL containing `/latest/` because such a URL cannot resolve to
   the reviewed bytes forever — a correct rule. But the app deliberately fetches
   the rolling alias and verifies it against the publisher's checksum sidecar at
   download time, and pinning is not symmetrical across the three:
   - `yt-dlp` and `deno` publish immutable tagged assets under the same filename
     (`2026.07.04`, `v2.9.5` as of 2026-08-11), so pinning is mechanical.
   - `ffmpeg` is not. Measured 2026-08-11: the rolling
     `ffmpeg-master-latest-win64-gpl.zip` is SHA-256
     `3479fe702a3a9410c6b646480c2890111e3b16d1e5a29091de411f0e810407da`, while
     the same-minute dated release `autobuild-2026-08-09-14-45` ships a
     *differently named* archive
     (`ffmpeg-N-126000-g1e0279143d-win64-gpl.zip`) with a different digest
     (`f705c4ab…`). They are not the same bytes, so the dated URL cannot be
     recorded as provenance for what the app actually downloads. Pinning the
     dated build instead was examined and rejected in `RESEARCH.md`: those tags
     have limited retention, so a pruned pin breaks first-run setup for every
     user.

**To unblock:** decide the helper question one of two ways — either pin all three helpers to immutable assets and accept a
refresh cadence that outruns FFmpeg-Builds retention, or state in the policy
that a publisher-verified rolling alias is an accepted delivery form and narrow
the inspection rule to say so. Do not simply delete the rule to make the gate
green.
