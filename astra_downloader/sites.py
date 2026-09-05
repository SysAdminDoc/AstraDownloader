"""Site capability registry: what the downloader knows about a host.

yt-dlp already recognises well over a thousand sites, so the question this
module answers is never "is this site allowed" — `config.media_url_block_reason`
owns that, and it accepts every public host. The question is what the
downloader should *do* differently once it knows which site a URL belongs to:

* which cookie domains belong to that site's session, so the extension bridge
  can hand over a jar for any site instead of only YouTube's,
* whether a sign-in is expected before the download fails and says so,
* which verified extractor arguments, impersonation target or referer the site
  needs to produce real formats,
* and what to call it in the interface.

Deliberately a leaf module: stdlib only, no package imports, no Qt, no Flask.
`config.py` and `download.py` both depend on it, so anything it imported would
become a dependency of the whole boundary layer.

Every `extractor_args` value here was checked against the extractor sources of
the pinned yt-dlp before being written down. An invented argument is not
harmless — it is silently ignored, so a profile that carries one looks
configured while doing nothing at all. `scripts/check-site-registry.py` re-runs
that check against whichever yt-dlp is installed.
"""

from urllib.parse import urlparse


__all__ = (
    "SITE_AUTH_NONE", "SITE_AUTH_OPTIONAL", "SITE_AUTH_REQUIRED",
    "SITE_AUTH_LEVELS", "SITE_CATEGORIES", "SITE_PROFILES",
    "KNOWN_EXTRACTOR_ARG_KEYS",
    "MULTI_LABEL_SUFFIXES", "registrable_domain", "site_key_for_url",
    "resolve_site_profile", "site_display_name", "site_category",
    "cookie_domains_for_site", "build_site_cookie_filter",
    "cookie_domain_belongs_to_site",
    "build_site_extractor_args", "site_impersonate_target",
    "select_impersonate_target",
    "site_referer_for_url", "site_auth_expectation", "describe_site_auth",
    "site_expects_sign_in", "site_supports_credentials",
    "site_failure_note_for_url",
    "site_catalog", "merge_extractor_names", "search_site_catalog",
    "CATALOG_SOURCE_CURATED", "CATALOG_SOURCE_EXTRACTOR",
)


# --- auth expectations -----------------------------------------------------

# What a first download of a typical public link needs. This is an
# expectation, never a gate: a site marked "required" is still attempted, and
# a site marked "none" can still be handed a stored sign-in.
SITE_AUTH_NONE = "none"
SITE_AUTH_OPTIONAL = "optional"
SITE_AUTH_REQUIRED = "required"

SITE_AUTH_LEVELS = (SITE_AUTH_NONE, SITE_AUTH_OPTIONAL, SITE_AUTH_REQUIRED)

SITE_CATEGORIES = (
    "video", "live", "social", "music", "news", "learning", "anime",
    "sports", "archive", "adult",
)

CATALOG_SOURCE_CURATED = "curated"
CATALOG_SOURCE_EXTRACTOR = "extractor"


# Two-label public suffixes common enough to matter when deciding what "the
# same site" means. Not a full public suffix list — being wrong here only
# makes the site key more or less specific, never broader than the host
# itself, so a cookie jar can never widen past the host it came from.
MULTI_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "co.nz", "net.nz",
    "org.nz", "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "com.br",
    "net.br", "org.br", "com.cn", "net.cn", "org.cn", "com.mx", "com.ar",
    "com.tr", "com.tw", "com.hk", "com.sg", "com.my", "com.ph", "co.in",
    "co.kr", "co.za", "com.pl", "com.ua", "co.il", "com.co", "com.pe",
    "com.ve", "com.ec", "com.uy", "com.do", "com.eg", "com.sa", "com.ng",
    "co.th", "or.th", "in.th", "com.vn", "co.id", "com.pk", "com.bd",
})


# Extractor-argument namespaces the pinned yt-dlp actually reads. Anything
# outside this set is a typo or a stale copy of a removed option, and a
# profile carrying one is doing nothing while looking configured. The gate
# script re-derives this from the installed yt-dlp rather than trusting the
# copy written down here.
KNOWN_EXTRACTOR_ARG_KEYS = frozenset({
    "archiveorg:check_all",
    "bilibili:prefer_multi_flv",
    "generic:impersonate",
    "generic:fragment_query",
    "generic:variant_query",
    "generic:key_query",
    "generic:hls_key",
    "generic:is_live",
    "instagram:app_id",
    "soundcloud:formats",
    "tiktok:api_hostname",
    "tiktok:app_info",
    "tiktok:device_id",
    "twitch:client_id",
    "twitter:api",
    "vimeo:client",
    "vimeo:original_format_policy",
    "youtube:formats",
    "youtube:player_client",
    "youtube:player_skip",
    "youtube:skip",
    "youtube:po_token",
    "youtube:fetch_pot",
    "youtube:include_duplicate_formats",
    "youtube:webpage_skip",
    "youtube-ejs:jitless",
})


def _profile(
    name,
    category="video",
    *,
    aliases=(),
    cookie_domains=(),
    auth=SITE_AUTH_NONE,
    auth_note="",
    credentials=False,
    extractor_args=(),
    impersonate="",
    referer=False,
    notes="",
    note_explains_failure=False,
):
    """Build one registry row.

    `aliases` are other registrable domains that are the same service, so a
    short link host resolves to the same profile as the main site.
    `cookie_domains` are the *extra* registrable domains whose cookies belong
    to this site's session — the site's own key and its aliases are always
    included, so only a separate identity provider needs listing.
    """
    return {
        "name": name,
        "category": category,
        "aliases": tuple(aliases),
        "cookie_domains": tuple(cookie_domains),
        "auth": auth,
        "auth_note": auth_note,
        "credentials": bool(credentials),
        "extractor_args": tuple(extractor_args),
        "impersonate": impersonate,
        "referer": bool(referer),
        "notes": notes,
        # Most notes describe the site for the catalogue — how its extractor
        # arguments are built, which cookie domains it uses. Only a note that
        # explains why the site cannot produce a file belongs on a failure,
        # and putting the rest there told a user reading a removed-video
        # error how YouTube's client chain is assembled.
        "note_explains_failure": bool(note_explains_failure),
    }


# Sites worth knowing something specific about. Absence from this table is not
# a refusal — an unlisted host still downloads through yt-dlp's own extractor
# for it, and the catalogue surfaces those too. A row earns its place by
# carrying a fact the downloader would otherwise get wrong: a separate cookie
# domain, a sign-in expectation, a verified extractor argument, or a TLS
# fingerprint the site checks.
SITE_PROFILES = {
    # --- the big video hosts ---
    "youtube.com": _profile(
        "YouTube", "video",
        aliases=("youtu.be", "youtube-nocookie.com"),
        # YouTube's session lives on Google's account domains, not only on
        # youtube.com. Dropping these is what makes a signed-in jar behave as
        # if it were signed out.
        cookie_domains=("google.com", "googlevideo.com"),
        auth=SITE_AUTH_OPTIONAL,
        auth_note=(
            "Public videos need no sign-in. Age-restricted, members-only and "
            "private videos do."
        ),
        notes=(
            "Extractor arguments for YouTube are built separately so the "
            "plugin-free token-exempt client chain stays in one place."
        ),
    ),
    "vimeo.com": _profile(
        "Vimeo", "video",
        auth=SITE_AUTH_OPTIONAL,
        auth_note="Private, password-protected and unlisted videos need a sign-in.",
        credentials=True,
        referer=True,
        notes=(
            "Embed-restricted videos only resolve when the request carries a "
            "referer the video is allowed to play under."
        ),
    ),
    "dailymotion.com": _profile("Dailymotion", "video", aliases=("dai.ly",)),
    "rumble.com": _profile(
        "Rumble", "video",
        impersonate="chrome",
        notes="Fronted by a bot check that reads the TLS fingerprint.",
    ),
    "odysee.com": _profile("Odysee", "video", aliases=("lbry.tv",)),
    "bitchute.com": _profile("BitChute", "video"),
    "streamable.com": _profile("Streamable", "video"),
    "veoh.com": _profile("Veoh", "video"),
    "vevo.com": _profile("Vevo", "music"),
    "metacafe.com": _profile("Metacafe", "video"),
    "9gag.com": _profile("9GAG", "social"),
    "imgur.com": _profile("Imgur", "social"),
    "gfycat.com": _profile("Gfycat", "social"),
    "redgifs.com": _profile("RedGIFs", "adult"),
    "newgrounds.com": _profile("Newgrounds", "video"),
    "coub.com": _profile("Coub", "video"),
    "rutube.ru": _profile("Rutube", "video"),
    "vk.com": _profile(
        "VK", "social",
        auth=SITE_AUTH_OPTIONAL,
        auth_note="Community and restricted videos need a sign-in.",
        credentials=True,
    ),
    "ok.ru": _profile("OK.ru", "social"),
    "bilibili.com": _profile(
        "Bilibili", "video",
        aliases=("b23.tv",),
        auth=SITE_AUTH_OPTIONAL,
        auth_note="1080p and above are only offered to signed-in accounts.",
        notes="Region-locked titles also need an exit inside mainland China.",
        note_explains_failure=True,
    ),
    "youku.com": _profile("Youku", "video"),
    "iqiyi.com": _profile("iQIYI", "video", auth=SITE_AUTH_OPTIONAL),
    "nicovideo.jp": _profile(
        "Niconico", "video",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Niconico serves video only to a signed-in account.",
        credentials=True,
    ),
    "naver.com": _profile("Naver TV", "video"),
    "tver.jp": _profile("TVer", "video"),
    "abema.tv": _profile("ABEMA", "video", auth=SITE_AUTH_OPTIONAL, credentials=True),

    # --- live streaming ---
    "twitch.tv": _profile(
        "Twitch", "live",
        auth=SITE_AUTH_OPTIONAL,
        auth_note="Subscriber-only VODs and some channels need a sign-in.",
        notes=(
            "Live captures start from the current segment; past VODs download "
            "whole. Mid-roll ad segments can leave gaps in a live capture."
        ),
    ),
    "kick.com": _profile(
        "Kick", "live",
        impersonate="chrome",
        notes=(
            "Behind a bot check that inspects the TLS fingerprint, so a "
            "plain request is refused before the extractor is reached."
        ),
    ),
    "trovo.live": _profile("Trovo", "live"),
    "dlive.tv": _profile("DLive", "live"),
    "sooplive.co.kr": _profile("SOOP", "live", aliases=("afreecatv.com",)),
    "huya.com": _profile("Huya", "live"),
    "douyu.com": _profile("Douyu", "live"),
    "younow.com": _profile("YouNow", "live"),
    "picarto.tv": _profile("Picarto", "live"),

    # --- social ---
    "twitter.com": _profile(
        "X (Twitter)", "social",
        aliases=("x.com", "t.co"),
        auth=SITE_AUTH_REQUIRED,
        auth_note=(
            "X stopped serving video to signed-out clients, so a sign-in is "
            "needed for almost every post."
        ),
    ),
    "instagram.com": _profile(
        "Instagram", "social",
        auth=SITE_AUTH_REQUIRED,
        auth_note=(
            "Reels, stories and most posts are only served to a signed-in "
            "session."
        ),
        notes="Stories expire, so a stored sign-in goes stale quickly.",
    ),
    "facebook.com": _profile(
        "Facebook", "social",
        aliases=("fb.watch", "fb.com"),
        auth=SITE_AUTH_REQUIRED,
        auth_note="Most videos, and every private or group post, need a sign-in.",
    ),
    "tiktok.com": _profile(
        "TikTok", "social",
        auth=SITE_AUTH_OPTIONAL,
        auth_note="Region-limited and age-gated posts need a sign-in.",
    ),
    "reddit.com": _profile(
        "Reddit", "social",
        aliases=("redd.it",),
        auth=SITE_AUTH_OPTIONAL,
        auth_note="NSFW and quarantined subreddits need a sign-in.",
        notes=(
            "Reddit has no username and password path for yt-dlp; sign in "
            "with cookies."
        ),
    ),
    "bsky.app": _profile("Bluesky", "social"),
    "threads.net": _profile(
        "Threads", "social",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Threads serves media to signed-in sessions only.",
    ),
    "snapchat.com": _profile("Snapchat", "social"),
    "linkedin.com": _profile(
        "LinkedIn", "social",
        auth=SITE_AUTH_REQUIRED,
        auth_note="LinkedIn video needs a signed-in session.",
        notes="Sign in with cookies; LinkedIn has no credential path here.",
    ),
    "pinterest.com": _profile("Pinterest", "social"),
    "tumblr.com": _profile("Tumblr", "social", auth=SITE_AUTH_OPTIONAL),
    "weibo.com": _profile("Weibo", "social"),
    "telegram.org": _profile("Telegram", "social", aliases=("t.me",)),
    "mastodon.social": _profile("Mastodon", "social"),
    "peertube.tv": _profile("PeerTube", "video"),

    # --- music and audio ---
    "soundcloud.com": _profile(
        "SoundCloud", "music",
        auth=SITE_AUTH_OPTIONAL,
        auth_note="Private and subscriber-only tracks need a sign-in.",
        credentials=True,
    ),
    "bandcamp.com": _profile("Bandcamp", "music"),
    "mixcloud.com": _profile("Mixcloud", "music"),
    "audiomack.com": _profile("Audiomack", "music"),
    "audius.co": _profile("Audius", "music"),
    "apple.com": _profile("Apple Music and Podcasts", "music"),
    "deezer.com": _profile("Deezer (previews)", "music"),
    "jamendo.com": _profile("Jamendo", "music"),
    "spotify.com": _profile(
        "Spotify", "music",
        notes=(
            "Only podcast episodes resolve. Spotify music is DRM-protected "
            "and cannot be downloaded."
        ),
        note_explains_failure=True,
    ),

    # --- news and broadcast ---
    "bbc.co.uk": _profile("BBC", "news", aliases=("bbc.com",)),
    "cnn.com": _profile("CNN", "news"),
    "nbcnews.com": _profile("NBC News", "news"),
    "cbsnews.com": _profile("CBS News", "news"),
    "go.com": _profile("ABC News", "news"),
    "foxnews.com": _profile("Fox News", "news"),
    "aljazeera.com": _profile("Al Jazeera", "news"),
    "dw.com": _profile("Deutsche Welle", "news"),
    "france24.com": _profile("France 24", "news"),
    "reuters.com": _profile("Reuters", "news"),
    "bloomberg.com": _profile("Bloomberg", "news"),
    "washingtonpost.com": _profile("The Washington Post", "news"),
    "nytimes.com": _profile("The New York Times", "news", auth=SITE_AUTH_OPTIONAL),
    "theguardian.com": _profile("The Guardian", "news"),
    "vice.com": _profile("VICE", "news"),
    "arte.tv": _profile("ARTE", "news"),
    "zdf.de": _profile("ZDF", "news"),
    "ardmediathek.de": _profile("ARD Mediathek", "news"),
    "rai.it": _profile("Rai", "news"),
    "nhk.or.jp": _profile("NHK", "news"),
    "cbc.ca": _profile("CBC", "news"),
    "abc.net.au": _profile("ABC (Australia)", "news"),

    # --- learning ---
    "ted.com": _profile("TED", "learning"),
    "coursera.org": _profile(
        "Coursera", "learning",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Course video is served only to enrolled accounts.",
        credentials=True,
    ),
    "udemy.com": _profile(
        "Udemy", "learning",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Course video needs a signed-in account that owns the course.",
        credentials=True,
    ),
    "khanacademy.org": _profile("Khan Academy", "learning"),
    "skillshare.com": _profile("Skillshare", "learning", auth=SITE_AUTH_REQUIRED),
    "brightcove.com": _profile("Brightcove", "video", referer=True),
    "kaltura.com": _profile("Kaltura", "video", referer=True),
    "wistia.com": _profile("Wistia", "video", referer=True),
    "vidyard.com": _profile("Vidyard", "video", referer=True),
    "loom.com": _profile("Loom", "video", auth=SITE_AUTH_OPTIONAL),
    "jwplayer.com": _profile("JW Player", "video", referer=True),

    # --- subscription video ---
    "patreon.com": _profile(
        "Patreon", "video",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Posts are served only to a signed-in supporting account.",
    ),
    "nebula.tv": _profile(
        "Nebula", "video",
        auth=SITE_AUTH_REQUIRED,
        credentials=True,
        auth_note="Nebula is subscription-only.",
    ),
    "curiositystream.com": _profile(
        "CuriosityStream", "video",
        auth=SITE_AUTH_REQUIRED, credentials=True,
    ),
    "dropout.tv": _profile(
        "Dropout", "video", auth=SITE_AUTH_REQUIRED, credentials=True,
    ),
    "crunchyroll.com": _profile(
        "Crunchyroll", "anime",
        auth=SITE_AUTH_REQUIRED,
        auth_note="Crunchyroll serves streams only to a signed-in account.",
        notes=(
            "Premium titles are DRM-protected and will not produce a file "
            "even with a valid sign-in."
        ),
        note_explains_failure=True,
    ),
    "funimation.com": _profile("Funimation", "anime", auth=SITE_AUTH_REQUIRED),
    "hidive.com": _profile("HIDIVE", "anime", auth=SITE_AUTH_REQUIRED,
                           credentials=True),
    "animelab.com": _profile("AnimeLab", "anime", auth=SITE_AUTH_REQUIRED),

    # --- sports ---
    "nfl.com": _profile("NFL", "sports"),
    "nba.com": _profile("NBA", "sports"),
    "mlb.com": _profile("MLB", "sports"),
    "nhl.com": _profile("NHL", "sports"),
    "espn.com": _profile("ESPN", "sports", auth=SITE_AUTH_OPTIONAL),
    "formula1.com": _profile("Formula 1", "sports", auth=SITE_AUTH_OPTIONAL),
    "wwe.com": _profile("WWE", "sports", auth=SITE_AUTH_OPTIONAL),
    "dazn.com": _profile("DAZN", "sports", auth=SITE_AUTH_REQUIRED),

    # --- archive and misc ---
    "archive.org": _profile(
        "Internet Archive", "archive",
        notes="Large items can carry hundreds of files; expect long queues.",
    ),
    "c-span.org": _profile("C-SPAN", "archive"),
    "ustream.tv": _profile("IBM Video", "video"),
    "steamcommunity.com": _profile("Steam", "video"),
    "gamejolt.com": _profile("Game Jolt", "video"),
    "itch.io": _profile("itch.io", "video"),
    "vrv.co": _profile("VRV", "video", auth=SITE_AUTH_REQUIRED),
    "pluto.tv": _profile("Pluto TV", "video"),
    "tubitv.com": _profile("Tubi", "video"),
    "crackle.com": _profile("Crackle", "video"),
    "roku.com": _profile("The Roku Channel", "video"),
    "plex.tv": _profile("Plex", "video", auth=SITE_AUTH_OPTIONAL),

    # --- adult ---
    # Included because yt-dlp supports them and leaving them out would make
    # the catalogue quietly wrong about what the downloader can do. Grouped
    # so the interface can filter them out of view.
    "pornhub.com": _profile("Pornhub", "adult", auth=SITE_AUTH_OPTIONAL,
                            credentials=True),
    "xvideos.com": _profile("XVideos", "adult"),
    "xhamster.com": _profile("xHamster", "adult"),
    "youporn.com": _profile("YouPorn", "adult"),
    "spankbang.com": _profile("SpankBang", "adult"),
    "xnxx.com": _profile("XNXX", "adult"),
    "chaturbate.com": _profile("Chaturbate", "adult"),
    "onlyfans.com": _profile(
        "OnlyFans", "adult",
        auth=SITE_AUTH_REQUIRED,
        notes="Not supported by yt-dlp; listed so the failure is not a mystery.",
        note_explains_failure=True,
    ),
}


# Aliases resolve to the profile they belong to. Built once, at import, so a
# lookup is a dict hit rather than a scan of every row.
def _build_alias_index(profiles):
    index = {}
    for key, profile in profiles.items():
        index.setdefault(key, key)
        for alias in profile["aliases"]:
            # A real row always wins over an alias pointing at another row, so
            # `youtube.com` staying itself does not depend on table order.
            if alias not in profiles:
                index.setdefault(alias, key)
    return index


_ALIAS_INDEX = _build_alias_index(SITE_PROFILES)


# --- host resolution -------------------------------------------------------

def registrable_domain(host):
    """Return the "same site" key for a host: `www.reddit.com` -> `reddit.com`.

    Falls back to the host itself when it is already minimal or unparseable.
    """
    host = str(host or "").strip().strip(".").lower()
    if not host:
        return ""
    labels = [label for label in host.split(".") if label]
    if len(labels) < 3:
        return ".".join(labels)
    if ".".join(labels[-2:]) in MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def site_key_for_url(url):
    """Return the registrable domain of a URL or bare hostname."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        try:
            raw = urlparse(raw).hostname or ""
        except ValueError:
            return ""
    else:
        raw = raw.split("/", 1)[0].split(":", 1)[0]
    return registrable_domain(raw)


def resolve_site_profile(url):
    """Return the registry row for a URL, or None when nothing is known.

    None is the common and entirely healthy answer: it means yt-dlp's own
    extractor handles the site with no help, which is true for most of the
    sites it supports.
    """
    key = site_key_for_url(url)
    if not key:
        return None
    canonical = _ALIAS_INDEX.get(key)
    if not canonical:
        return None
    profile = SITE_PROFILES.get(canonical)
    if profile is None:
        return None
    resolved = dict(profile)
    resolved["key"] = canonical
    resolved["matched"] = key
    return resolved


def site_failure_note_for_url(url):
    """Return the note that explains why a site cannot produce a file, or "".

    Only the handful of profiles carrying `note_explains_failure` answer here
    — Spotify music and Crunchyroll premium titles are DRM-protected, OnlyFans
    has no extractor. Those are worth putting in front of a user looking at
    the failure rather than on a Sites page they would have to think to visit.
    Every other note describes the site for the catalogue, and putting one on
    a failure told a user reading a removed-video error how YouTube's client
    chain is assembled.
    """
    profile = resolve_site_profile(url)
    if not profile or not profile.get("note_explains_failure"):
        return ""
    return str(profile.get("notes") or "").strip()


def site_display_name(url):
    """Return the friendly name of a site, falling back to its domain."""
    profile = resolve_site_profile(url)
    if profile:
        return profile["name"]
    return site_key_for_url(url)


def site_category(url):
    """Return the catalogue category for a URL, or "video" when unknown."""
    profile = resolve_site_profile(url)
    return profile["category"] if profile else "video"


# --- cookie scoping --------------------------------------------------------

def cookie_domains_for_site(site_key):
    """Return every registrable domain whose cookies belong to one site.

    This is what lets the extension hand over a jar for any site rather than
    only YouTube's, without letting a jar widen into a general cookie dump: a
    request for `twitch.tv` accepts Twitch cookies and nothing else, while a
    request for `youtube.com` also accepts the Google account domains the
    YouTube session actually lives on.
    """
    key = registrable_domain(site_key) if site_key else ""
    if not key:
        return frozenset()
    # A single-label key is a whole public suffix, and a scope of {"com"}
    # matches every `.com` cookie by the subdomain rule below — a jar for one
    # site would carry the entire web's session. `media_url_block_reason`
    # already refuses single-label hosts long before a jar is written, so this
    # is unreachable through the download path, but a scoping function is the
    # wrong place to rely on someone else having validated first.
    if len(key.split(".")) < 2:
        return frozenset()
    canonical = _ALIAS_INDEX.get(key, key)
    domains = {key, canonical}
    profile = SITE_PROFILES.get(canonical)
    if profile:
        domains.update(profile["aliases"])
        domains.update(profile["cookie_domains"])
    return frozenset(domain for domain in domains if domain)


def cookie_domain_belongs_to_site(cookie_domain, site_key):
    """True when a cookie's domain is in scope for the site being downloaded.

    Subdomains of an in-scope domain count; a bare suffix match does not, so
    `notyoutube.com` is never mistaken for a subdomain of `youtube.com`.
    """
    domain = str(cookie_domain or "").strip().lstrip(".").lower().rstrip(".")
    if not domain:
        return False
    scope = cookie_domains_for_site(site_key)
    if not scope:
        return False
    return any(
        domain == allowed or domain.endswith("." + allowed) for allowed in scope
    )


def build_site_cookie_filter(url):
    """Return a `domain -> bool` filter scoped to one URL's site.

    Handed to `download.write_cookies_netscape` so a per-download jar carries
    only the cookies of the site the download is for. Returns None when the
    URL has no usable host, which callers treat as "write no jar at all"
    rather than "write every cookie".
    """
    key = site_key_for_url(url)
    if not key:
        return None
    scope = cookie_domains_for_site(key)
    if not scope:
        return None

    def allow(domain):
        candidate = str(domain or "").strip().lstrip(".").lower().rstrip(".")
        if not candidate:
            return False
        return any(
            candidate == allowed or candidate.endswith("." + allowed)
            for allowed in scope
        )

    return allow


# --- argv contributions ----------------------------------------------------

def build_site_extractor_args(url):
    """Return the verified extractor arguments this site needs.

    Empty for the overwhelming majority of sites, which is the correct answer:
    yt-dlp's defaults already work, and an argument added "just in case"
    changes behaviour no one asked it to change. YouTube is deliberately not
    served from here — its client chain is built in `health.py` so there is one
    place that decides it.
    """
    profile = resolve_site_profile(url)
    if not profile:
        return []
    args = []
    for value in profile["extractor_args"]:
        args += ["--extractor-args", value]
    return args


def site_impersonate_target(url):
    """Return the browser *family* this site needs impersonated, or "".

    A family, not a target: yt-dlp reports targets as `Chrome-133`,
    `Chrome-136`, `Safari-18.0`, and those version numbers move with every
    curl_cffi release. Pinning `Chrome-136` here would silently stop matching
    the day it changed, which is the same dead-configuration failure the
    registry gate exists to prevent. `select_impersonate_target` resolves the
    family against whatever the installed binary actually reports.
    """
    profile = resolve_site_profile(url)
    return profile["impersonate"] if profile else ""


def _target_sort_key(name):
    """Order targets so the newest version of a family sorts last.

    `Chrome-99` must not beat `Chrome-136`, so the version segment is compared
    numerically per component rather than as text.
    """
    _, _, version = str(name).partition("-")
    parts = []
    for chunk in version.split("."):
        parts.append((0, int(chunk)) if chunk.isdigit() else (1, 0))
    return (len(parts), parts)


def select_impersonate_target(family, available_targets):
    """Return the newest available target in `family`, or "".

    Matching is on the name before the version and is case-insensitive, so a
    registry entry of `chrome` finds `Chrome-136`. Returns "" when the family
    is absent, because an `--impersonate` target the binary does not have is
    not a warning: yt-dlp raises and the download dies.
    """
    wanted = str(family or "").strip().casefold()
    if not wanted:
        return ""
    matches = [
        str(name) for name in (available_targets or ())
        if str(name).partition("-")[0].casefold() == wanted
    ]
    if not matches:
        return ""
    return max(matches, key=_target_sort_key)


def site_referer_for_url(url):
    """Return the referer this site's embeds need, or "".

    Some hosts only release a stream to a request that looks like it came from
    a page allowed to embed it. Sending the site's own origin is the least
    surprising choice and is what an ordinary browser sends when the video is
    played on the site itself.
    """
    profile = resolve_site_profile(url)
    if not profile or not profile["referer"]:
        return ""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc}/"


# --- auth expectations -----------------------------------------------------

def site_auth_expectation(url):
    """Return `(level, note)` for a URL's sign-in expectation."""
    profile = resolve_site_profile(url)
    if not profile:
        return SITE_AUTH_NONE, ""
    return profile["auth"], profile["auth_note"]


def site_expects_sign_in(url):
    """True when a typical public link on this site needs a stored sign-in."""
    level, _ = site_auth_expectation(url)
    return level == SITE_AUTH_REQUIRED


def site_supports_credentials(url):
    """True when this site accepts a username and password, not only cookies.

    Most sites do not: their sign-in is a browser flow yt-dlp cannot replay,
    so cookies are the only path. Saying so up front is better than letting a
    stored password fail on every download.
    """
    profile = resolve_site_profile(url)
    return bool(profile and profile["credentials"])


def describe_site_auth(url):
    """Return one sentence about what this site expects, or "" when nothing."""
    profile = resolve_site_profile(url)
    if not profile:
        return ""
    note = profile["auth_note"].strip()
    if note:
        return note
    if profile["auth"] == SITE_AUTH_REQUIRED:
        return f"{profile['name']} needs a stored sign-in."
    if profile["auth"] == SITE_AUTH_OPTIONAL:
        return f"Some {profile['name']} links need a stored sign-in."
    return ""


# --- catalogue -------------------------------------------------------------

def site_catalog():
    """Return the curated rows, sorted by display name.

    Each row is a flat dict the interface can render without knowing the
    registry's shape.
    """
    rows = []
    for key, profile in SITE_PROFILES.items():
        rows.append({
            "key": key,
            "name": profile["name"],
            "category": profile["category"],
            "auth": profile["auth"],
            "auth_note": profile["auth_note"],
            "credentials": profile["credentials"],
            "notes": profile["notes"],
            "source": CATALOG_SOURCE_CURATED,
        })
    rows.sort(key=lambda row: (row["name"].casefold(), row["key"]))
    return tuple(rows)


def merge_extractor_names(names):
    """Layer yt-dlp's own extractor list under the curated rows.

    The honest answer to "which sites are supported" is whatever the installed
    yt-dlp says, which is far more than any hand-kept table. The curated rows
    add what the downloader knows on top of that; every remaining extractor is
    listed as itself so the count in the interface is the real one rather than
    the size of this file.
    """
    curated = site_catalog()
    seen = {row["name"].casefold() for row in curated}
    seen.update(row["key"].casefold() for row in curated)
    extra = []
    for name in names or ():
        label = str(name or "").strip()
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        extra.append({
            "key": "",
            "name": label,
            "category": "video",
            "auth": SITE_AUTH_NONE,
            "auth_note": "",
            "credentials": False,
            "notes": "",
            "source": CATALOG_SOURCE_EXTRACTOR,
        })
    extra.sort(key=lambda row: row["name"].casefold())
    return curated + tuple(extra)


def search_site_catalog(rows, query="", category=""):
    """Filter catalogue rows by a free-text query and an optional category."""
    wanted = str(query or "").strip().casefold()
    group = str(category or "").strip().casefold()
    results = []
    for row in rows or ():
        if group and str(row.get("category") or "").casefold() != group:
            continue
        if wanted:
            haystack = " ".join(
                str(row.get(field) or "")
                for field in ("name", "key", "category", "notes", "auth_note")
            ).casefold()
            if wanted not in haystack:
                continue
        results.append(row)
    return tuple(results)
