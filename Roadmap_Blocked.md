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

`py -3.12 scripts/build-companion-translations.py` prints current coverage per
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
