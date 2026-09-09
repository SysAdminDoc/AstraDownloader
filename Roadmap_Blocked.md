# Blocked

Items that cannot be finished without something such as credentials, a licensing decision or an upstream release. Moved here so `ROADMAP.md` stays
a list of implementation work.

## Translation coverage needs native review

The string extractor currently finds 1,016 user-facing strings. All eleven catalogues contain those keys, including English fallback entries. That is not the same as eleven fully translated interfaces.

The current checker requires complete German coverage and exposes English and German in the language picker. Nine partial catalogues remain for older saved configurations. Run `py -3.13 scripts/check-companion-translations.py` for current per-language coverage; the older 219-string figures no longer describe this release.

Native-speaker review is still needed before advertising each additional language. Translation-platform suggestions from earlier notes have not been re-evaluated in this marketing pass.

## AD-30 | Mint PO tokens from a sidecar the app owns | needs a licence review

**State:** the argv route is confirmed and the candidate is identified, so the
research half of this item is done. `--extractor-args
"youtube:po_token=CLIENT.CONTEXT+TOKEN"` takes a token on the command line, so
the plugin-free posture (`--no-plugin-dirs`) survives a provider running
beside yt-dlp rather than inside it.

**What the survey found (2026-08-22):**

- `Brainicism/bgutil-ytdlp-pot-provider` 1.3.2 publishes exactly one asset, an
  8 KB source zip. Running it means an `npm install` tree at setup time, which
  this project does not do and could not checksum-verify.
- `jim60105/bgutil-ytdlp-pot-provider-rs` v0.8.1 does publish a standalone
  `bgutil-pot-windows-x86_64.exe` (45.7 MB), which is a managed binary this
  app could own. It ships no checksum sidecar file, but the GitHub release
  API carries a per-asset `digest`, and `fetch_expected_sha256` could be
  taught to read it | the app already talks to that API and already meters
  its anonymous budget.

**What is blocked:** adding a runtime helper to `license-policy.json` requires
`"licenseReviewed": true`, and `scripts/resolve-runtime-helpers.js` refuses to
approve an entry without it | on purpose, so that adding a helper cannot
approve it by simply running staging. Reading a third party's terms and
accepting them on the maintainer's behalf is the human judgement that gate
exists to demand. A 45.7 MB binary that talks to YouTube on the user's behalf
is also exactly the kind of dependency that deserves it.

**Also unvalidated:** the acceptance says "a video that previously failed
`po-token-required` succeeds". That precondition cannot be manufactured | it
needs YouTube to be gating this machine at the time of the test. Whoever picks
this up needs a reproducible failing video, not a green suite.

**To unblock:** the maintainer reads the provider's licence and its supply
chain, decides whether a 45.7 MB third-party binary belongs in this install,
and sets `licenseReviewed` on the policy entry. The implementation after that
is: manage the exe like Deno, run it in HTTP-server mode on loopback, mint per
video, and pass the token on argv. No plugin directory is enabled at any point.

## AD-53 | Set `SABR_NATIVE_MIN_VERSION` | waits on an upstream merge

**State:** the wiring is already there. `evaluate_sabr_support` returns
`"limited"` while the sentinel is not a real version, the Download-page SABR
pill reads it, and a test pins both sides.

**What is blocked:** The August review recorded yt-dlp PR #13515 (native SABR) as open, updated
2026-08-19 and not in 2026.08.19, which is the pinned release. The item itself
says "do not invent a version while the PR is open", and the whole value of
the constant is that it names the first stable release that actually contains
the change.

**To unblock:** when a yt-dlp stable ships #13515, set
`SABR_NATIVE_MIN_VERSION` to that version. Nothing else changes; the pill
flips on its own.

## AD-56 | Earlier review gaps | four separate checks

**State:** a self-audit note rather than one task. The four areas and what
each actually needs:

1. **The signed-release chain.** The release is unsigned and has a SHA-256 sidecar. A checksum is not a publisher signature. Exercising a signed chain needs a certificate the maintainer would
   have to buy and hold.
2. **The whisper transcription live path.** Needs a real audio file and the
   whisper.cpp model downloaded for a live run, not a fixture.
3. **Native-host stdio against a real Chrome profile.** Needs a browser
   session with the extension loaded; the loopback pairing route is covered by
   tests but the stdio channel to a live Chrome is not.
4. **The Astra Deck userscript `/health` token echo.** Lives in the Astra-Deck
   repository and is deliberately off.

**To unblock:** each area separately. This is not one item and should not be
picked up as one. When an area gets a live check or a named test, strike it
from this list rather than closing the whole entry.

## AD-123 | The extension shows a green yt-dlp pill on a below-floor build

**State:** the downloader half is done. `evaluate_preflight_checks` reports
`securityFloor` and `belowSecurityFloor` on the `ytdlp-freshness` check, and
`/health` serves them, so everything the extension needs is already on the
wire.

**Where to verify next:** the earlier review placed this fix in the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) repository, not this
one. Its health normalizer whitelists thirteen keys and `preflight` is not
among them, and its yt-dlp pill is rendered unconditionally `ok` while the
ffmpeg and JavaScript-runtime pills tone on state. Nothing in this repository
can change that, and a downloader-side change would be inventing a second
health surface for one consumer.

**To unblock:** ship it in Astra Deck | add `preflight` to the normalizer's
allowed keys and tone the yt-dlp pill from the `ytdlp-freshness` check,
naming the floor when `belowSecurityFloor` is set. Verify against a running
Astra Downloader reporting a below-floor version, which
`ManagedBinaryPins` makes reproducible without waiting for a real old build.
