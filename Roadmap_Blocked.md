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

## AD-56 | Earlier review gaps | three separate checks

**State:** a self-audit note rather than one task. The three areas and what
each actually needs:

1. **The signed-release chain.** The release is unsigned and has a SHA-256 sidecar. A checksum is not a publisher signature. Exercising a signed chain needs a certificate the maintainer would
   have to buy and hold.
2. **The whisper transcription live path.** Needs a real audio file and the
   whisper.cpp model downloaded for a live run, not a fixture.
3. **Native-host stdio against a real Chrome profile.** Needs a browser
   session with the extension loaded; the loopback pairing route is covered by
   tests but the stdio channel to a live Chrome is not.

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

## AD-85 | Sign update metadata independently of release hosting | needs the maintainer's keys and a signing cadence

**The item:** the updater takes the EXE and its SHA-256 sidecar from the same GitHub release, so whoever controls the release can replace both. The fix is TUF: a root of trust bundled in the app, and targets accepted only through signed, versioned, expiring targets, snapshot and timestamp metadata, with trusted metadata kept between runs to refuse rollback and freeze attacks.

**Why it can't be finished from code alone (2026-10-06):**

- The bundled `root.json` has to be signed by root keys the maintainer creates and keeps offline. Nothing can ship until that ceremony has happened, and a root generated by anyone else would defeat the point.
- TUF's timestamp role expires on purpose, usually within days, so somebody has to re-sign it on a schedule for as long as the app checks for updates. That needs a decision on where an online timestamp key lives and what runs the re-signing. GitHub Actions is off the table for this repository and the scheduled tasks on the build PC were all removed, so there's no default home for it.
- Where the metadata is hosted is part of the same decision. It has to be a place a compromised release account can't rewrite without the offline keys showing it.

**What to do once those are decided:** `python-tuf`'s `ngclient.Updater` covers the client side (Apache 2.0 or MIT). It needs a pin in `requirements.txt`, an entry in the license inventory, the dependency audit, and PyInstaller bundling. The release side is a small signing script run at staging. The current sidecar check stays as the fallback until the first signed root ships.

## AD-139 | Drive the Windows shell integration in a real desktop session | split from AD-71

**State:** the jump list (`jump_list_tasks`, `jump_list_command_from_argv`), `RegisterApplicationRestart` and the Recycle Bin delete (`send_to_recycle_bin`) in `astra_downloader/astra_downloader.py` were read in the 2026-08-22 audit and have unit tests, but nothing has watched them work in Explorer and the taskbar.

**What is blocked:** checking them means a real interactive desktop: pinning the app, opening its jump list, letting Windows restart it after a crash or an update reboot, and finding a deleted file in the Recycle Bin. The build PC's display belongs to its user, and offscreen Qt can't show any of these shell surfaces.

**To unblock:** a spare Windows desktop session or VM where the packaged EXE can be installed and driven. The browser extension half of the old AD-71 note lives in the Astra Deck repository (see AD-123).

## AD-159 | Astra Deck should say how to pair an unpacked copy | follow-up to AD-145

**State:** the downloader half is done. `/pair-extension` answers a Chrome ID that isn't published and isn't already paired with 403, code `extension-pairing-closed`, and an `error` that names Allow extension pairing on the Browser extension page.

**What is blocked:** Astra Deck's `_pairWithCompanion` in `extension/features/download-ui/index.js` only logs a failed pair, so an unpacked install lands on the native-channel-required advice ("Update it with Download setup"), which won't fix it. That file had another session's uncommitted edits on 2026-10-09, and that session was still committing to Astra Deck later the same day, so it wasn't changed from here. This matters for most users: the documented install is the release zip loaded unpacked, which has no manifest `key`, so its ID comes from the folder path and never matches the published one.

**To unblock:** in Astra Deck, map `extension-pairing-closed` to its own failure copy (open Astra Downloader, choose Allow extension pairing, then Check again) and show it in place of the native-channel advice. The published CRX ID `lgbiefafhjdbplelniclnflbbilennlg` in its signing-keys doc must stay in step with `PUBLISHED_CHROME_EXTENSION_IDS`. Better still, put the CRX public key in the zip build's manifest as `key` (the base64 SPKI the signing-keys doc derives the ID from). An unpacked copy then gets the published ID and pairs on its own, with no window. Check that the Firefox build drops or ignores the field.
