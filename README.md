# Astra Downloader

[![version](https://img.shields.io/badge/version-2.0.0-ff6552)](https://github.com/SysAdminDoc/AstraDownloader/releases)
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
  without transcoding.
- **Clip a range.** Give a start and end timestamp and get an accurate
  ffmpeg-cut section instead of the whole video.
- **Sign in to sites.** Private and members-only videos work: import a
  `cookies.txt`, or read a browser profile. One jar per site, filtered to
  that site's registrable domain and attached to that site alone.
- **Durable queue.** Downloads survive a restart. Pause intake, retry a
  failure, cancel a run.
- **It tells you why.** A failure names its cause — missing JavaScript
  runtime, expired sign-in, size cap, SABR-limited formats — and offers the
  control that fixes it.
- **Sets itself up.** First launch fetches yt-dlp and ffmpeg. No separate
  installer, no PATH surgery. yt-dlp keeps itself current.
- **Stays out of the way.** Tray icon, optional logon start, Start Menu and
  desktop entries, and a clipboard watcher that can stage copied links.

## Install

Download `AstraDownloader.exe` from the
[latest release](https://github.com/SysAdminDoc/AstraDownloader/releases/latest)
and run it. It installs to `%LOCALAPPDATA%\AstraDownloader`, registers its
Start Menu and desktop entries, and starts.

The build is unsigned, so SmartScreen will warn on first run — choose **More
info → Run anyway**.

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
py -3.12 -m pytest          # 450 tests
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
embed credentials. Stored cookies never leave the machine and are never
readable through the API, the GUI, the log, or the diagnostics payload: only
counts, sources, and expiry are exposed. See
[`docs/yt-dlp-cookie-threat-model.md`](docs/yt-dlp-cookie-threat-model.md).

Report a vulnerability by opening a
[security advisory](https://github.com/SysAdminDoc/AstraDownloader/security/advisories/new).

## License

[MIT](LICENSE).

Astra Downloader drives yt-dlp and ffmpeg; each keeps its own license, and
`npm run release:stage` records the resolved third-party inventory alongside
the built binary.
