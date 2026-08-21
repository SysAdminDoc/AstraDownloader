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

**Corrected 2026-08-21:** the History column headers used to be named here as
strings the extractor could not see. They are extracted and translated now —
the German catalogue carries `Duration` as `Dauer`. What is left is the fixed
column width, which a longer translated header overflows, and that is tracked
as AD-35 in `ROADMAP.md` rather than here.

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

## AD-53 — Set `SABR_NATIVE_MIN_VERSION` — waits on an upstream merge

**State:** the wiring is already there. `evaluate_sabr_support` returns
`"limited"` while the sentinel is not a real version, the Download-page SABR
pill reads it, and a test pins both sides.

**What is blocked:** yt-dlp PR #13515 (native SABR) is still open — updated
2026-08-19 and not in 2026.08.19, which is the pinned release. The item itself
says "do not invent a version while the PR is open", and the whole value of
the constant is that it names the first stable release that actually contains
the change.

**To unblock:** when a yt-dlp stable ships #13515, set
`SABR_NATIVE_MIN_VERSION` to that version. Nothing else changes; the pill
flips on its own.

## AD-56 — Areas this audit did not exercise — five separate external needs

**State:** a self-audit note rather than one task. The five areas and what
each actually needs:

1. **The signed-release chain.** There is no code-signing certificate on this
   machine and the release ships unsigned by design, with a SHA-256 sidecar
   instead. Exercising a signed chain needs a certificate the maintainer would
   have to buy and hold.
2. **The whisper transcription live path.** Needs a real audio file and the
   whisper.cpp model downloaded — a live run, not a fixture.
3. **winget publish.** Submitting to `microsoft/winget-pkgs` is a publication
   decision the maintainer has not taken; see the winget entry above.
4. **Native-host stdio against a real Chrome profile.** Needs a browser
   session with the extension loaded; the loopback pairing route is covered by
   tests but the stdio channel to a live Chrome is not.
5. **The Astra Deck userscript `/health` token echo.** Lives in the Astra-Deck
   repository and is deliberately off.

**To unblock:** each area separately. This is not one item and should not be
picked up as one — when an area gets a live check or a named test, strike it
from this list rather than closing the whole entry.
