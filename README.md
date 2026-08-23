# Astra Downloader

[![version](https://img.shields.io/badge/version-2.12.0-ff6552)](https://github.com/SysAdminDoc/AstraDownloader/releases)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows-0078d4)](https://github.com/SysAdminDoc/AstraDownloader/releases/latest)
[![python](https://img.shields.io/badge/python-3.13-3776ab)](astra_downloader/requirements.txt)

A desktop video downloader for Windows. Paste a link from YouTube, Reddit,
X, TikTok, Vimeo, Instagram, Twitch, or any of the hundreds of sites
[yt-dlp](https://github.com/yt-dlp/yt-dlp) supports. It downloads.

It also runs a local API so the
[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) browser extension can
send downloads straight from a page. That server is a feature, not the point:
pasting a link never needs it.

---

## What it does

- **Any site.** Anything yt-dlp can reach. Paste one link or a whole
  whitespace-separated batch at once.
- **Pick your output.** MP4 / MKV / WebM up to 2160p, or extract audio as
  MP3 / M4A / Opus / FLAC / WAV. MP4 prefers H.264 + AAC so editors import it
  without transcoding, and codec and frame-rate preferences order whatever
  the container leaves open.
- **The picker knows the link.** A pasted link is probed for the formats it
  really has, so the quality list stops offering 2160p on a 720p video.
- **Bound a playlist.** Cap how many items a pasted playlist queues, and
  filter it by upload date or item duration.
- **Name the file.** Give a single download a name in the paste area and it is
  saved under that name; leave it empty and the video title is used as before.
- **Clip a range.** Give a start and end timestamp for an accurate ffmpeg-cut
  section, or use **From link** for a pasted `?t=` timestamp and **Last 30 s**
  for a yt-dlp-native tail clip.
- **Sign in to sites.** Private and members-only videos work: import a
  `cookies.txt`, or read a browser profile. One jar per site, filtered to
  that site's registrable domain and attached to that site alone. A one-time
  YouTube warning appears whether the sign-in is stored in the app or through
  the local API. It explains the account-ban and public-video risks, with a
  link to [yt-dlp's guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).
- **See what pacing means.** Settings turns the configured pause into an
  approximate hourly rate per worker and in total at the current concurrency.
  It puts those figures beside yt-dlp's published YouTube estimates and its
  recommended 5 to 10 second delay.
- **Site profiles.** Name a domain-bound profile in Settings for automatic
  format, quality, proxy, impersonation and pacing defaults. The paste box
  shows the matched profile and offers a one-off profile or no-profile choice;
  cookies and credentials remain in the separate sign-in store.
- **Durable queue.** Downloads survive a restart. Pause intake, retry a
  failure, cancel a run.
- **History you can keep and search.** Choose the local retention cap in
  Settings, search by title, filename, or URL, and see subscription-archive
  records alongside ordinary downloads without duplicating the same URL.
- **Empty pages point the way forward.** History, scheduled subscriptions,
  stored sign-ins, and extension activity explain what to do when there is
  nothing to show yet, including one-click recovery actions.
- **Keeps output folders clean.** Partial and merge files use a private,
  per-download staging folder and only the finished file is moved into the
  destination. The Settings page can put intermediates beside the output for
  diagnosis.
- **Archive deliberately.** Opt into info JSON, Kodi/Jellyfin NFO metadata,
  descriptions and thumbnails, with `tvshow.nfo`/`season.nfo` for channel
  folders, or split chapter files and start a live stream from its beginning.
  A bounded live-video retry interval handles scheduled events without
  changing the existing embed options.
- **Preview Windows-safe names.** Settings renders an example output path,
  flags reserved names and overlong paths before saving, and enables yt-dlp's
  Windows filename sanitization by default.
- **SponsorBlock attribution is visible.** Optional segment removal links to
  [SponsorBlock](https://sponsor.ajay.app/) in the Settings UI. Its data and
  API are CC BY-NC-SA 4.0; Astra Downloader itself is MIT-licensed.
- **Browser pairing stays scoped.** Native messaging is registered for the
  installed Chromium-family browsers and Firefox only after browser-specific
  extension IDs pass validation.
- **It tells you why before it fails.** The Download page pre-flight panel
  names stale yt-dlp, missing JavaScript runtime, stale or incomplete FFmpeg,
  expired sign-ins, GitHub API exhaustion, and token-provider trouble, with a
  repair action for each condition. Download failures retain the same named
  causes and recovery guidance.
- **It checks that the selected format fits.** A known size is compared with
  free space before the request enters the queue, whether it came from the
  desktop window, browser extension, or a scheduled subscription.
- **Get past a block.** Imitate a real browser's TLS fingerprint, chosen from
  the targets your yt-dlp actually ships, for sites that answer 403.
- **Inherit the system proxy.** Turn one Settings option on and downloads use
  the proxy Windows already knows about; the resolved address is shown before
  you save.
- **Work around network geography.** Force IPv4 or IPv6, bind a source address,
  send a geo X-Forwarded-For value, or use a verification-only proxy when a
  site or route needs more than a whole-session proxy.
- **Subtitles, the ones you asked for.** Creator captions, the machine
  transcript, or the former falling back to the latter. Pick languages from a
  list (including all non-live-chat tracks), normalise everything to SRT, set
  a pause between subtitle requests, or fetch subtitles without the video.
- **Transcribe locally when needed.** Enable local subtitle generation in
  Settings and a successful video with no subtitle track gets an SRT sidecar
  beside it. The pinned multilingual Whisper model is downloaded during setup
  only after you opt in; audio-only and subtitle-only jobs never invoke it.
- **Sets itself up.** First launch fetches yt-dlp and ffmpeg, plus a
  JavaScript runtime if YouTube needs one. It uses Deno if available,
  otherwise a 2 MB QuickJS build. No separate installer, no PATH surgery.
  yt-dlp keeps itself current.
- **Move it, or put it back.** Export settings and subscriptions to one JSON
  bundle and import it on another machine. Stored sign-ins are listed by site
  but never exported; cookies stay where they are. Proxy credentials, network
  identity, site profiles and extra output roots stay local. Each
  subscription keeps its format, quality, audio mode, naming template and
  upgrade choice; its folder travels only when it sits under a carried
  download root. An import reports the setting names it changed.
- **Stays out of the way.** Tray icon, optional logon start, Start Menu and
  desktop entries, and a clipboard watcher that can stage copied links.
  Queue progress shows on the taskbar button, and a completion notification
  can be clicked to reveal the file.

## Install

Download `AstraDownloader.exe` from the
[latest release](https://github.com/SysAdminDoc/AstraDownloader/releases/latest)
and run it. It installs to `%LOCALAPPDATA%\AstraDownloader`, registers its
Start Menu and desktop entries, and starts.

For a scripted install that should return without opening the window, run the
packaged executable with `--install`. It copies itself to the managed install
directory and registers the same per-user integrations:

```powershell
.\AstraDownloader.exe --install
```

For a portable copy, extract `AstraDownloader-onedir.zip` into a writable
folder and launch `AstraDownloader.exe` normally. The archive includes a
portable marker, so its state stays beside the executable automatically:

```powershell
.\AstraDownloader.exe
```

Portable mode keeps configuration, queue/history, sign-ins, logs, and the
managed yt-dlp/ffmpeg/runtime files beside the executable. It does not create
Start Menu, desktop, protocol, logon-task, or browser native-messaging
registrations. The checked-in portable manifest under
`packaging/winget/manifests` is validated by Windows Package Manager before
release submission.

The one-file executable is the installable layout: running it normally copies
the executable to `%LOCALAPPDATA%\AstraDownloader` and registers integrations.
If you deliberately keep a one-file copy elsewhere, pass `--portable`; the
running copy then owns its state beside itself. `--install` always selects the
managed install layout. A portable one-folder copy cannot self-update by
replacing only its executable; extract the next one-folder archive instead.

The build is unsigned, so SmartScreen will warn on first run. Choose **More
info → Run anyway**. That is permanent policy, not an oversight: verify the
download against the SHA-256 published beside it instead of relying on a
signature.

When `AstraDownloader.exe.sha256` is beside a downloaded one-file executable,
first launch checks the pair before the managed install begins. A present but
malformed or mismatched sidecar stops setup. This detects a mismatched release
pair; it is not code signing and cannot make a substituted executable
trustworthy. Check the hash before running the file.

```powershell
Get-FileHash .\AstraDownloader.exe -Algorithm SHA256
```

Compare the result with `AstraDownloader.exe.sha256` from the same release.

To remove it completely, including the shortcuts, the logon task, and the
protocol handlers:

```powershell
& "$env:LOCALAPPDATA\AstraDownloader\AstraDownloader.exe" --uninstall
```

To remove only the state from a portable folder while keeping its executable
and downloaded media, run `--uninstall` from that folder.

## Run from source

Python 3.11 or newer. That floor sits one release above what the pinned dependency graph resolves against, because CPython 3.10 reaches end of life in October 2026.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-virtualenv -r astra_downloader/requirements.txt
.\.venv\Scripts\python.exe astra_downloader/astra_downloader.py
```

Imports are side-effect free: running from source never installs packages
behind your back.

## Build the executable

```powershell
py -3.13 astra_downloader/build.py
```

Produces the unsigned one-file `AstraDownloader.exe` and its SHA-256 sidecar,
plus `AstraDownloader-onedir.zip` and a matching sidecar. The zip contains a
normal PyInstaller one-folder build, so it is the recommended antivirus
fallback when the one-file executable is flagged: it avoids runtime
self-extraction at the cost of a larger download and an extracted folder.

The zip is also how this project honours the LGPL. Astra Downloader's own code
is MIT, and it bundles Qt through PySide6-Essentials under the LGPL-3.0-only
arm of the Qt Company's tri-licence. LGPL section 4 asks that you be able to
replace the covered libraries with your own build; the one-folder layout leaves
every Qt DLL sitting next to the executable where you can swap it, which the
one-file executable does not. Both artifacts ship with every release for that
reason. The Qt sources for the exact wheel are at
[code.qt.io](https://code.qt.io/cgit/pyside/pyside-setup.git/), and the
obligations are recorded in
[`astra_downloader/license-policy.json`](astra_downloader/license-policy.json).
Both artifacts are tied to the same version and one-file analysis build ID;
the portable zip carries the shared build metadata for staging verification.
`npm run release:provenance` writes the CycloneDX SBOM and the PEP 751
`pylock.toml`; `npm run release:stage` validates and stages both artifacts
and refuses a release whose SBOM does not describe the staged binary.
Release dependencies are pinned in
[`astra_downloader/constraints-release.txt`](astra_downloader/constraints-release.txt).

## Tests and gates

```powershell
py -3.13 -m pytest          # 1182 tests across every core; scratch stays under build/pytest
npm run check               # all seven gates, PASS/FAIL printed per gate
npm run smoke:gui           # renders the real Qt window offscreen
npm run smoke:yt-dlp        # downloads a small video with the pinned yt-dlp
```

The suite runs in parallel by default, which needs `pytest-xdist`
alongside `pytest-qt` and `pytest-asyncio`. Add `-p no:xdist` for a serial
run when you are debugging how one test affects another. The tests are split
by domain: download, GUI, routes, subscriptions, health, config and build.
`astra_downloader/testing_support.py` holds what they share.

`npm run check` runs the unit tests, the companion port catalogue, the
Python catch-reason gate, the licence inventory, the translation catalogues,
the version/tag agreement and the Python dependency audit. It prints a result
line per gate rather than stopping at the first failure, so a red gate does
not hide the state of the other six.

The test count above is the number `py -3.13 -m pytest --collect-only -q`
reports; re-run it rather than trusting the figure if the two disagree.

## The browser extension

[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) is a separate project.
When Astra Downloader is running, the extension finds it on `127.0.0.1` across
a fixed set of ports and hands off downloads with full quality and progress
reporting.

The port list is a contract between the two repositories, checked in both from
identical copies of `scripts/companion-port-catalogue.json`. Requests are
accepted from this machine only and must carry the session token. Flask accepts
only canonical `127.0.0.1`, `localhost`, or `[::1]` Host authorities with valid
ports, which closes DNS rebinding. Browser preflight methods are generated from
the routes the server actually registers.

## Security

Downloads only reach public internet addresses. Loopback, RFC1918,
link-local, reserved, and multicast targets are refused, as are URLs that
embed credentials. Stored cookies and site username/password credentials
never leave the machine and are never readable through the API, the GUI, the
log, diagnostics, or settings bundles: only safe metadata such as counts,
sources, expiry, and whether credentials are present is exposed. One-off
video passwords are held only for the current single-link download and are
not written to queue or history records. See
[`docs/yt-dlp-cookie-threat-model.md`](docs/yt-dlp-cookie-threat-model.md).

**No external downloader is offered.** aria2c, curl and the rest are refused
at the process boundary, along with `--exec` and the `--netrc` family: they
hand the transfer, or a command line, to a process this program does not
control, and 2026 brought code-execution advisories against two of the common
choices. yt-dlp is also spawned with its plugin directories disabled, so a
plugin you install for yt-dlp itself will not be loaded here.

Report a vulnerability by opening a
[security advisory](https://github.com/SysAdminDoc/AstraDownloader/security/advisories/new).
Accepted properties and non-issues are listed in [`SECURITY.md`](SECURITY.md).

## License

[MIT](LICENSE).

Astra Downloader drives yt-dlp and ffmpeg; each keeps its own license, and
`npm run release:stage` records the resolved third-party inventory alongside
the built binary.
