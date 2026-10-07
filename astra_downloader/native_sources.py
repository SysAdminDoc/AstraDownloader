"""Native source resolvers: sites yt-dlp's own extractor cannot reach.

yt-dlp covers well over a thousand sites, and for almost all of them the
downloader hands the page URL straight to it. A resolver lives here only when
that path is known to be broken and the fix is small: fetch what the site's
own player fetches, hand yt-dlp the media URL it produces, and keep the page
URL for everything user-facing.

Deliberately a leaf module: stdlib only. `download.py` depends on it, so
anything imported here would become a dependency of the whole boundary layer.

## Kick VODs

yt-dlp's `kick:vod` extractor reads `kick.com/api/v1/video/<uuid>`, which
answers 404 for every VOD created since Kick reworked its site (yt-dlp issue
17284). The watch page is fine; only that endpoint is dead. Kick's own player
instead POSTs to `web.kick.com/api/v1/stream/<uuid>/playback` and plays the
`playback_url.vod` manifest it gets back. That response also carries the
title and duration, so no second lookup is needed.

The manifest URL carries a one-hour JWT, but it only gates the master
manifest fetch: the variant playlists sit behind a CloudFront path hash and
the segments are unsigned. yt-dlp reads the playlists once and then streams
segments, so resolving immediately before the process is spawned is enough
even for an eight-hour stream. The delivery host refuses a request with no
User-Agent (it answers the manifest fetch with a JSON block instead of the
playlist), so the resolver names the header the download must send.

Kick has since swapped which door is open. On 2026-10-06 the v1 endpoint
answered again and `kick:vod` extracted every VOD tried, while the playback
endpoint answered 404 for all of them. An HTTP error from the playback
route therefore hands the VOD's page, in the shape kick:vod accepts, to
yt-dlp instead of failing the download, so whichever of the two routes Kick
keeps working is the one used.

## Keeping the reason honest

`NATIVE_SOURCE_UPSTREAM` records, per resolver, the yt-dlp extractor it
stands in for, the issue it answers, and a hash of that extractor's source
(the real class and its bases up to InfoExtractor, not the lazy-loader stub)
at the reviewed yt-dlp release. `scripts/check-site-registry.py` fails when the
installed extractor no longer matches, which is the cue to test whether the
resolver is still needed rather than keep assuming it.
"""

import json
import re
import urllib.error
import urllib.request


__all__ = (
    "NativeSourceError", "resolve_native_source", "native_source_argv",
    "is_native_source_url", "NATIVE_SOURCE_USER_AGENT",
    "NATIVE_SOURCE_USER_AGENT_REVIEWED", "NATIVE_SOURCE_UPSTREAM",
    "KICK_VOD_URL_RE", "KICK_PLAYBACK_ENDPOINT",
)


# The browser the resolvers claim to be. It tracks the newest desktop Chrome
# profile the pinned curl_cffi impersonates (chrome146 in 0.16.0), so a
# resolved download and an impersonated one name the same browser. The site
# registry gate fails once the review date is more than a year old: a frozen
# fingerprint in a module whose premise is imitating the site's own player
# goes stale quietly.
NATIVE_SOURCE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
NATIVE_SOURCE_USER_AGENT_REVIEWED = "2026-10-06"

# Why each resolver exists. `extractor_sha256` is the SHA-256 of the
# `inspect.getsource()` text (LF line endings) of the real extractor class and
# each base below InfoExtractor, in MRO order, in the yt-dlp release named
# beside it; scripts/check-site-registry.py recomputes it.
NATIVE_SOURCE_UPSTREAM = (
    {
        "resolver": "kick-vod",
        "extractor": "kick:vod",
        "issue": "https://github.com/yt-dlp/yt-dlp/issues/17284",
        "ytdlp_version": "2026.08.19",
        "extractor_sha256": "1367aa980bb87481005c4d934627350c6ee596baef419b7004f9dc90649a10f4",
    },
)
NATIVE_SOURCE_TIMEOUT_SECONDS = 20
# Playback responses are a few kilobytes; a cap keeps a misbehaving endpoint
# from being read into memory without bound.
NATIVE_SOURCE_MAX_BYTES = 1024 * 1024

KICK_VOD_URL_RE = re.compile(
    r"^https?://(?:www\.)?kick\.com/"
    r"(?:(?P<slug>[\w.-]+)/videos?|videos?)/"
    r"(?P<id>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})(?:[/?#]|$)",
    re.IGNORECASE,
)
KICK_PLAYBACK_ENDPOINT = "https://web.kick.com/api/v1/stream/{video_id}/playback"
# The endpoint rejects an empty body. These are the session objects Kick's
# web player sends; `non_personalised_ads` keeps the request from carrying an
# advertising profile.
_KICK_PLAYBACK_PAYLOAD = {
    "video_player": {"player": {}},
    "video_session": {},
    "user_session": {"non_personalised_ads": True},
}


class NativeSourceError(Exception):
    """A native site was recognised but its media could not be resolved.

    `code` is one of `source-unavailable` (the site refused or has nothing for
    this id) or `network-unreachable` (the endpoint could not be reached at
    all). The message is user-facing.
    """

    def __init__(self, message, code="source-unavailable"):
        super().__init__(message)
        self.code = code


def _default_fetch(url, *, data=None, headers=None, timeout=NATIVE_SOURCE_TIMEOUT_SECONDS):
    """Return `(status, body_bytes)` for one request.

    An HTTP error status is returned rather than raised so callers can tell a
    404 (the site has nothing) from an unreachable host (retry later).
    """
    request = urllib.request.Request(url, data=data, headers=dict(headers or {}))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(NATIVE_SOURCE_MAX_BYTES)
    except urllib.error.HTTPError as error:
        try:
            body = error.read(NATIVE_SOURCE_MAX_BYTES)
        except Exception:  # noqa: BLE001
            # reason: the status is the answer; an unreadable error body adds nothing
            body = b""
        return error.code, body


def is_native_source_url(url):
    """True when a resolver here handles this URL instead of yt-dlp's extractor."""
    return bool(KICK_VOD_URL_RE.match(str(url or "").strip()))


def _decode_json(body):
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return None


def _kick_vod_page(match, video_id):
    """The VOD's page in the one shape yt-dlp's kick:vod accepts.

    The resolver takes slugless, singular and dotted-slug permalinks that
    kick:vod's pattern does not, and handed over as typed they would reach
    kick:live instead, which records whatever that channel is streaming now.
    kick:vod reads only the id, so a slug it cannot parse is replaced.
    """
    slug = match.group("slug") or ""
    if not re.fullmatch(r"[\w-]+", slug, re.ASCII):
        slug = "video"
    return {
        "site": "kick",
        "id": video_id,
        "url": f"https://kick.com/{slug}/videos/{video_id}",
        "title": "",
        "duration": 0,
        "channel": "",
        "headers": {},
    }


def _resolve_kick_vod(match, fetch, timeout):
    video_id = match.group("id").lower()
    headers = {
        "User-Agent": NATIVE_SOURCE_USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        status, body = fetch(
            KICK_PLAYBACK_ENDPOINT.format(video_id=video_id),
            data=json.dumps(_KICK_PLAYBACK_PAYLOAD).encode("utf-8"),
            headers=headers,
            timeout=timeout,
        )
    except Exception as error:  # noqa: BLE001
        # reason: every transport failure means the same thing to the user:
        # Kick could not be reached, and the download should be retried later
        raise NativeSourceError(
            f"Kick could not be reached to resolve this video: {error}",
            code="network-unreachable",
        ) from error

    if status >= 400:
        # Kick has broken this endpoint and the one kick:vod reads in turn,
        # so an HTTP error here says this route has nothing, not that the
        # video is gone. yt-dlp's own extractor gets the page instead, and a
        # VOD that really was deleted fails there with yt-dlp's message.
        return _kick_vod_page(match, video_id)

    payload = _decode_json(body)
    if not isinstance(payload, dict):
        raise NativeSourceError("Kick returned something other than a playback session.")
    # A refusal is reported as a 200 whose top-level `data` object carries
    # `type`/`details`, not as an HTTP error.
    refusal = payload.get("data")
    if isinstance(refusal, dict) and refusal:
        kind = str(refusal.get("type") or "refused").strip()
        raise NativeSourceError(
            f"Kick will not play this video ({kind}). It may be private, "
            "subscriber-only, or still processing."
        )

    raw = payload.get("playback_url")
    manifest = ""
    if isinstance(raw, str):
        manifest = raw
    elif isinstance(raw, dict):
        for key in ("vod", "live"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                manifest = value
                break
    if not manifest.startswith(("https://", "http://")):
        raise NativeSourceError("Kick's playback session carried no media URL.")

    session = payload.get("video_session")
    session = session if isinstance(session, dict) else {}
    title = str(session.get("video_title") or "").strip()
    duration = session.get("video_duration")
    try:
        duration = int(duration) if duration is not None else 0
    except (TypeError, ValueError):
        duration = 0
    channel = str(match.group("slug") or session.get("video_series") or "").strip()

    return {
        "site": "kick",
        "id": video_id,
        "url": manifest,
        "title": title or (f"{channel} VOD {video_id[:8]}" if channel else f"Kick VOD {video_id[:8]}"),
        "duration": max(0, duration),
        "channel": channel,
        "headers": {"User-Agent": NATIVE_SOURCE_USER_AGENT},
    }


def resolve_native_source(url, *, fetch=None, timeout=NATIVE_SOURCE_TIMEOUT_SECONDS):
    """Return the media yt-dlp should be pointed at, or None for other sites.

    None is the answer for the whole rest of the web and means "hand the page
    URL to yt-dlp as usual". A dict means yt-dlp gets `url` instead, with the
    argv from `native_source_argv`; when the resolver's own route answers with
    an HTTP error, that `url` is the page in the shape yt-dlp's extractor
    accepts and the argv is empty.
    `NativeSourceError` means the site was recognised and refused; the
    download should fail with that message.
    """
    text = str(url or "").strip()
    match = KICK_VOD_URL_RE.match(text)
    if not match:
        return None
    return _resolve_kick_vod(match, fetch or _default_fetch, timeout)


def _escape_parse_metadata_source(value):
    """Escape a literal for the FROM half of yt-dlp's `--parse-metadata`.

    FROM is an output template, so `%` must be doubled, and the unescaped `:`
    that separates FROM from TO must be written `\\:`. Newlines would end the
    field, so they become spaces.
    """
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return text.replace("%", "%%").replace(":", "\\:")


def native_source_argv(resolved):
    """Return the yt-dlp arguments a resolved native source needs.

    A manifest URL has no page around it, so yt-dlp's generic extractor would
    name the file after the manifest. The real title is injected with
    `--parse-metadata`, which runs before the output template is rendered.
    """
    if not isinstance(resolved, dict):
        return []
    args = []
    for name, value in (resolved.get("headers") or {}).items():
        if str(name).lower() == "user-agent":
            args += ["--user-agent", str(value)]
        else:
            args += ["--add-header", f"{name}:{value}"]
    title = str(resolved.get("title") or "").strip()
    if title:
        args += ["--parse-metadata", f"{_escape_parse_metadata_source(title)}:(?P<title>.+)"]
    return args
