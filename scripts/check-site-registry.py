#!/usr/bin/env python
"""Check the site registry against the yt-dlp that is actually installed.

Two ways a registry row can be wrong while looking right, both of which this
gate refuses:

1. **An unreachable key.** Rows are looked up by registrable domain, so a key
   that is not its own registrable domain (``chzzk.naver.com``,
   ``linkedin.com/learning``) can never match a URL. The row sits in the file
   looking configured and is dead.
2. **An invented extractor argument.** yt-dlp ignores an argument it does not
   know, without a warning, so a profile carrying a typo or a copy of an option
   that was removed upstream keeps claiming to configure something.

The second check re-derives the real argument names from the installed
extractor sources rather than trusting the copy in ``sites.py``, so the gate
still catches a drift after a yt-dlp upgrade removes an option.

Run directly, or through ``npm run check``.
"""

import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "astra_downloader"))

import sites  # noqa: E402  (path is set up immediately above)


_CONFIGURATION_ARG = re.compile(
    r"""_configuration_arg\(\s*['"]([A-Za-z0-9_]+)['"]"""
)
# Not every extractor argument is read through `_configuration_arg`. The
# JavaScript-runtime options reach their namespace through a plain
# `get_param('extractor_args')['youtube-ejs']` and a small `ejs_setting`
# helper, so a gate that only knew the first pattern reported the shipped
# `youtube-ejs:jitless` as invented. Matching both is what keeps this check
# honest about a real option instead of failing the code for its own blind
# spot.
_HELPER_ARG = re.compile(
    r"""(?:ejs_setting|_ejs_setting)\(\s*['"]([A-Za-z0-9_]+)['"]"""
)


def discovered_extractor_args():
    """Return every `namespace:option` the installed yt-dlp actually reads.

    Returns None when yt-dlp is not importable, which is a skip rather than a
    failure: the registry is still checked for reachability, and a machine
    without yt-dlp installed has nothing to compare against.
    """
    try:
        import yt_dlp.extractor as extractor_package
    except ImportError:
        return None

    root = pathlib.Path(extractor_package.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # The namespace an option belongs to is the extractor's own key, which
        # is not recoverable from the source text alone. Collect bare option
        # names per module and let the membership check below compare on the
        # option half — a name that exists in no module at all is the drift
        # this gate is looking for.
        for match in _CONFIGURATION_ARG.finditer(text):
            found.add(match.group(1))
        for match in _HELPER_ARG.finditer(text):
            found.add(match.group(1))
    return found


def check_reachable_keys(failures):
    """Every registry key and alias must be its own registrable domain."""
    for key, profile in sites.SITE_PROFILES.items():
        if sites.registrable_domain(key) != key:
            failures.append(
                f"site key {key!r} is not its own registrable domain "
                f"({sites.registrable_domain(key)!r}), so no URL can ever match it"
            )
        for alias in profile["aliases"]:
            if sites.registrable_domain(alias) != alias:
                failures.append(
                    f"alias {alias!r} on {key!r} is not its own registrable "
                    f"domain, so it can never resolve"
                )
        for domain in profile["cookie_domains"]:
            if sites.registrable_domain(domain) != domain:
                failures.append(
                    f"cookie domain {domain!r} on {key!r} is not its own "
                    f"registrable domain, so it widens nothing"
                )


def check_round_trip(failures):
    """A key must resolve back to itself through the public lookup."""
    for key in sites.SITE_PROFILES:
        resolved = sites.resolve_site_profile(f"https://{key}/watch")
        if resolved is None:
            failures.append(f"site key {key!r} does not resolve through resolve_site_profile")
        elif resolved["key"] != key:
            failures.append(
                f"site key {key!r} resolves to {resolved['key']!r} instead of itself"
            )


def check_declared_shape(failures):
    """Categories and auth levels must come from the declared vocabularies."""
    for key, profile in sites.SITE_PROFILES.items():
        if profile["category"] not in sites.SITE_CATEGORIES:
            failures.append(
                f"{key!r} has category {profile['category']!r}, which is not in "
                f"SITE_CATEGORIES"
            )
        if profile["auth"] not in sites.SITE_AUTH_LEVELS:
            failures.append(
                f"{key!r} has auth {profile['auth']!r}, which is not in "
                f"SITE_AUTH_LEVELS"
            )
        if profile["impersonate"] and profile["referer"]:
            # Not illegal, but it has never been the right answer and is far
            # more likely to be a copied row than a decision.
            failures.append(
                f"{key!r} sets both an impersonation target and a referer; "
                f"confirm that is deliberate before allowing it"
            )


def check_extractor_args(failures, discovered):
    """Registry arguments must name options the installed yt-dlp reads."""
    declared = set()
    for key, profile in sites.SITE_PROFILES.items():
        for value in profile["extractor_args"]:
            if ":" not in value:
                failures.append(
                    f"{key!r} extractor arg {value!r} is not in namespace:option form"
                )
                continue
            namespace, _, rest = value.partition(":")
            option = rest.partition("=")[0]
            declared.add((key, f"{namespace}:{option}", option))

    for key, qualified, option in sorted(declared):
        if qualified not in sites.KNOWN_EXTRACTOR_ARG_KEYS:
            failures.append(
                f"{key!r} uses extractor arg {qualified!r}, which is not listed "
                f"in KNOWN_EXTRACTOR_ARG_KEYS"
            )
        if discovered is not None and option not in discovered:
            failures.append(
                f"{key!r} uses extractor option {option!r}, which the installed "
                f"yt-dlp does not read anywhere — it would be silently ignored"
            )

    if discovered is None:
        return
    for qualified in sorted(sites.KNOWN_EXTRACTOR_ARG_KEYS):
        option = qualified.partition(":")[2].partition("=")[0]
        if option not in discovered:
            failures.append(
                f"KNOWN_EXTRACTOR_ARG_KEYS lists {qualified!r}, but the installed "
                f"yt-dlp no longer reads {option!r}"
            )


def main():
    failures = []
    discovered = discovered_extractor_args()
    check_reachable_keys(failures)
    check_round_trip(failures)
    check_declared_shape(failures)
    check_extractor_args(failures, discovered)

    if failures:
        print("[check-site-registry] FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    curated = len(sites.SITE_PROFILES)
    known = len(sites.KNOWN_EXTRACTOR_ARG_KEYS)
    source = (
        f"{len(discovered)} extractor options"
        if discovered is not None
        else "yt-dlp not installed, argument names unverified"
    )
    print(
        f"[check-site-registry] OK - {curated} curated sites, "
        f"{known} known extractor args, checked against {source}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
