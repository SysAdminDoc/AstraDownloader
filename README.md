# Astra Downloader

[![version](https://img.shields.io/badge/version-2.5.0-ff6552)](https://github.com/SysAdminDoc/AstraDownloader/releases)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows-0078d4)](https://github.com/SysAdminDoc/AstraDownloader/releases/latest)
[![python](https://img.shields.io/badge/python-3.12-3776ab)](astra_downloader/requirements.txt)

A desktop video downloader for Windows. Paste a link — from YouTube, Reddit,
X, TikTok, Vimeo, Instagram, Twitch, or any of the hundreds of sites
[yt-dlp](https://github.com/yt-dlp/yt-dlp) supports — and it downloads.

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
- **Clip a range.** Give a start and end timestamp and get an accurate
  ffmpeg-cut section instead of the whole video.
- **Sign in to sites.** Private and members-only videos work: import a
  `cookies.txt`, or read a browser profile. One jar per site, filtered to
  that site's registrable domain and attached to that site alone.
- **Durable queue.** Downloads survive a restart. Pause intake, retry a
  failure, cancel a run.
- **Keeps output folders clean.** Partial and merge files use a private,
  per-download staging folder and only the finished file is moved into the
  destination. The Settings page can put intermediates beside the output for
  diagnosis.
- **It tells you why.** A failure names its cause — missing JavaScript
  runtime, expired sign-in, size cap, SABR-limited formats, a site refusing
  the request — and offers the control that fixes it.
- **Get past a block.** Imitate a real browser's TLS fingerprint, chosen from
  the targets your yt-dlp actually ships, for sites that answer 403.
- **Subtitles, the ones you asked for.** Creator captions, the machine
  transcript, or the former falling back to the latter. Pick languages from a
  list, normalise everything to SRT, or fetch subtitles without the video.
- **Sets itself up.** First launch fetches yt-dlp and ffmpeg, plus a
  JavaScript runtime if YouTube needs one — Deno if it can be had, otherwise a
  2 MB QuickJS build. No separate installer, no PATH surgery. yt-dlp keeps
  itself current.
- **Move it, or put it back.** Export settings and subscriptions to one JSON
  bundle and import it on another machine. Stored sign-ins are listed by site
  but never exported; cookies stay where they are.
- **Stays out of the way.** Tray icon, optional logon start, Start Menu and
  desktop entries, and a clipboard watcher that can stage copied links.
  Queue progress shows on the taskbar button, and a completion notification
  can be clicked to reveal the file.

## Install

Download `AstraDownloader.exe` from the
[latest release](https://github.com/SysAdminDoc/AstraDownloader/releases/latest)
and run it. It installs to `%LOCALAPPDATA%\AstraDownloader`, registers its
Start Menu and desktop entries, and starts.

The build is unsigned, so SmartScreen will warn on first run — choose **More
info → Run anyway**. That is permanent policy, not an oversight: verify the
download against the SHA-256 published beside it instead of relying on a
signature.

```powershell
Get-FileHash .\AstraDownloader.exe -Algorithm SHA256
```

Compare the result with `AstraDownloader.exe.sha256` from the same release.

To remove it completely, including the shortcuts, the logon task, and the
protocol handlers:

```powershell
& "$env:LOCALAPPDATA\AstraDownloader\AstraDownloader.exe" --uninstall
```

## Run from source

Python 3.11 or newer — the pinned yt-dlp raised its minimum in 2026.07.04.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-virtualenv -r astra_downloader/requirements.txt
.\.venv\Scripts\python.exe astra_downloader/astra_downloader.py
```

Imports are side-effect free: running from source never installs packages
behind your back.

## Build the executable

```powershell
py -3.12 astra_downloader/build.py
```

Produces an unsigned one-file `AstraDownloader.exe` plus its SHA-256 sidecar.
Release dependencies are pinned in
[`astra_downloader/constraints-release.txt`](astra_downloader/constraints-release.txt).

## Tests and gates

```powershell
py -3.12 -m pytest          # 712 tests
npm run check               # port catalogue, catch reasons, versions, pip-audit
npm run smoke:gui           # renders the real Qt window offscreen
```

## The browser extension

[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) is a separate project.
When Astra Downloader is running, the extension finds it on `127.0.0.1` across
a fixed set of ports and hands off downloads with full quality and progress
reporting.

The port list is a contract between the two repositories, checked in both from
identical copies of `scripts/companion-port-catalogue.json`. Requests are
accepted from this machine only and must carry the session token; the server
rejects any request whose `Host` header is not loopback, which closes DNS
rebinding.

## Security

Downloads only reach public internet addresses — loopback, RFC1918,
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
