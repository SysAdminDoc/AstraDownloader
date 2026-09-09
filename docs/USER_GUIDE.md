# Using Astra Downloader v2.15.1

[Back to the download page](../README.md)

## Choose files, not command-line options

Paste one link in Download, or paste a whitespace-separated batch. The app probes a single link so the quality picker can reflect its available formats. A probe can fail even when a different site works; read the error before retrying.

Video output supports MP4, MKV and WebM. MP4 prefers H.264 with AAC for compatibility. Audio choices include MP3, M4A, Opus, FLAC and WAV. Codec and frame-rate preferences order formats the source actually provides; they aren't an upscaler.

Use the filename field for a single download, or leave it empty to use the source title. Settings has a naming-template preview with checks for Windows reserved names and path length. Windows filename sanitization is on by default.

For a clip, set start and end timestamps. **From link** reads a supported timestamp from the URL. **Last 30 s** requests a tail clip. Precise cutting uses FFmpeg and may take longer than downloading the original stream.

## Queue and history

The queue is saved locally so pending work can survive a restart. Pause intake to stop accepting more work, retry a failed job, or cancel a running download. The error card includes recovery guidance where the failure is recognized.

A playlist can be limited by item count, upload date or duration. If an entry is private or unavailable, that doesn't necessarily explain a different entry's failure.

History searches titles, filenames and URLs. Settings controls its retention cap. Subscription archive entries appear alongside ordinary downloads without duplicating the same URL.

By default, each download uses its own staging folder. Finished output is moved to the destination; partial and merge files stay out of the media folder. The diagnostic option to keep intermediates beside output is available in Settings. Known file sizes are checked against free space before a job is queued, but unknown sizes can still run out of room later.

## Subtitles and archives

Choose creator subtitles, automatic captions, or creator subtitles with an automatic fallback. Select languages, normalize output to SRT, or download subtitle tracks without the video. You can set a delay between subtitle requests.

Optional local transcription uses a pinned multilingual Whisper model. Opting in downloads the model and required tool. After a successful video download with no subtitle track, it can write an SRT beside the file. Audio-only and subtitle-only jobs don't invoke that fallback.

For a media archive, enable the sidecars you need: info JSON, descriptions, thumbnails or Kodi/Jellyfin NFO files. Channel folders can include `tvshow.nfo` and `season.nfo`. Chapter splitting and starting a supported live stream from its beginning are separate options. A retry interval is available for scheduled live events.

Subscriptions remember format, quality, audio mode, naming template and upgrade preferences. They scan while the application and scheduler are running; closing the app isn't a cloud scheduling service.

## Sites, profiles and sign-ins

Sites combines a curated guidance catalogue with extractors reported by your installed yt-dlp. Search it or filter by category. Site-specific referers and extractor arguments are applied where configured. There is also a native resolver for supported Kick VOD links; this is not a promise that every Kick URL remains available.

Site profiles hold domain-specific defaults for formats, quality, proxy, browser impersonation and pacing. The paste area shows the matched profile. You can choose a different profile for that job or disable matching. Secrets remain in the separate sign-in store.

Sign-ins can import a Netscape-format `cookies.txt`, read a supported browser profile, or receive a session from the paired extension. Cookies are scoped to the site's registrable domain. A site may reject an imported session, require additional checks or change its login flow. Don't import your everyday account without considering the risk, particularly on YouTube.

The app warns about YouTube account risks and links to [yt-dlp's guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies). Settings shows approximate rates based on your configured pause and worker count. These estimates aren't a service quota or a guarantee against rate limits.

Optional SponsorBlock segment removal uses [SponsorBlock](https://sponsor.ajay.app/). Its service data has separate terms and attribution, shown in the interface. Turning it on makes requests to that service.

## Network and browser handoff

Settings can use a configured proxy or the Windows system proxy. The displayed address is redacted when it includes credentials. Network choices also apply to first-party setup and update requests where supported.

Advanced options include IPv4 or IPv6 preference, a source address, geo-related headers and a verification proxy. Browser impersonation is limited to targets included in your yt-dlp build. None of these options grants access to content you aren't authorized to use.

[Astra Deck](https://github.com/SysAdminDoc/Astra-Deck) is optional and maintained separately. Its handoff uses the local API's fixed loopback port catalogue and session token. Browser-specific extension IDs are checked before native-messaging registration. A native bootstrap can prove the endpoint knows the session secret before receiving cookies. Pairing a live browser wasn't part of the screenshot capture.

## Installation and portable storage

Running the one-file executable normally installs it under `%LOCALAPPDATA%\AstraDownloader` and registers per-user integrations. `--install` performs installation without opening the window.

```powershell
.\AstraDownloader.exe --install
```

The portable ZIP has a marker beside its executable. Extract the whole archive to a writable folder and run it there. New portable copies store settings, history, queue, subscriptions, sign-ins and managed helpers under `data`. Portable mode doesn't create desktop, Start Menu, protocol, logon-task or browser native-messaging registrations. Existing older copies with loose state beside the executable retain that layout.

A one-file copy can also be run with `--portable`. Don't combine it with `--install`.

```powershell
.\AstraDownloader.exe --portable
```

The portable one-folder build cannot update itself by replacing only its executable. Extract the next complete ZIP while retaining its data folder. Keep a backup before replacing an existing installation.

The [Scoop manifest](../packaging/scoop/astra-downloader.json) uses the portable layout and persists the entire `data` folder. It is an alternative for people already using Scoop; the README's direct downloads don't require a package manager.

```powershell
scoop install https://raw.githubusercontent.com/SysAdminDoc/AstraDownloader/main/packaging/scoop/astra-downloader.json
```

`scoop update astra-downloader` retains that folder. `scoop uninstall -p astra-downloader` removes it, including stored sign-ins and settings.

## Moving settings or removing the app

Export settings and subscriptions to a JSON bundle, then import that bundle on another machine. The import reports the names it changed. Stored sign-ins are listed as metadata but aren't exported. Cookies, credentials, network identity, site profiles and extra output roots remain local. A subscription's folder travels only when it's under a carried download root.

Close-to-tray, logon start and clipboard link watching are optional. Clipboard watching is off by default. Completion and failure notifications have separate settings.

To remove the managed installation and its integrations:

```powershell
& "$env:LOCALAPPDATA\AstraDownloader\AstraDownloader.exe" --uninstall
```

This removes application state. Back up anything you need first. In a portable folder, `--uninstall` removes local app state but keeps the executable and downloaded media. See the [security policy](../SECURITY.md) for the boundaries of local storage and credentials.
