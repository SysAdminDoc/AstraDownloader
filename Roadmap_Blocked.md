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

## Submit the portable manifest to the official winget repository — maintainer decision

**State:** the application has a self-contained `--portable` mode, a GUI-free
`--install` path, and a schema-valid manifest under
`packaging/winget/manifests` whose installer digest staging keeps in step with
the released bytes. `winget validate` passes locally.

**What is blocked:** nothing technical any more. `v2.9.0` is published with the
artifact the manifest points at, so the release URL and checksum requirements
are met. Submitting to `microsoft/winget-pkgs` is a publication decision the
maintainer has not taken, and it is not something a coding agent should make on
their behalf.

**To unblock:** the maintainer opens the pull request against
`microsoft/winget-pkgs` with `packaging/winget/manifests`, or decides the
project is distributed through GitHub Releases only and the manifest directory
is retired.
