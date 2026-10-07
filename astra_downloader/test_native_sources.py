"""Tests for the native source resolvers.

The resolver is the thing standing between "Kick VOD" and "HTTP 404", so it is
tested against recorded response shapes rather than the live site: the
success body Kick's player receives, the 200-with-`data` refusal, a plain
404, and an unreachable host. The live path is exercised separately by hand
because it depends on a VOD that will not exist forever.
"""

import datetime
import importlib.util
import json
import unittest
from pathlib import Path

try:
    from . import native_sources as ns
except ImportError:  # Flat source-path compatibility.
    import native_sources as ns


VOD = "01a04eaf-79f0-71f9-ad3e-342286927538"
MANIFEST = "https://web.kick.com/api/v1/stream/manifest.m3u8?init=eyJ.token.sig"


def _ok_body(**overrides):
    body = {
        "playback_url": {"vod": MANIFEST, "live": ""},
        "video_session": {
            "creator_id": "111631",
            "video_duration": 30116,
            "video_title": "HUGE BOXING EVENT | ORLANDO, FL",
            "video_series": "Loulz",
        },
        "user_session": {},
        "video_player": {},
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


class _Fetch:
    """A fake transport that records the one request it answers."""

    def __init__(self, status=200, body=b"", error=None):
        self.status, self.body, self.error = status, body, error
        self.calls = []

    def __call__(self, url, *, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": dict(headers or {}), "timeout": timeout})
        if self.error:
            raise self.error
        return self.status, self.body


class UrlRecognitionTests(unittest.TestCase):
    def test_kick_vod_permalinks_are_recognised_in_every_shape(self):
        for url in (
            f"https://kick.com/loulz/videos/{VOD}",
            f"https://www.kick.com/loulz/videos/{VOD}",
            f"https://kick.com/loulz/video/{VOD}",
            f"https://kick.com/video/{VOD}",
            f"https://kick.com/videos/{VOD}?t=120",
            f"HTTPS://KICK.COM/LOULZ/VIDEOS/{VOD.upper()}",
        ):
            with self.subTest(url=url):
                self.assertTrue(ns.is_native_source_url(url))

    def test_everything_else_is_left_to_ytdlp(self):
        for url in (
            "https://kick.com/loulz",
            "https://kick.com/loulz/clips/clip_01ABC",
            "https://kick.com/loulz/videos/not-a-uuid",
            f"https://notkick.com/loulz/videos/{VOD}",
            f"https://kick.com.evil.net/loulz/videos/{VOD}",
            "https://www.youtube.com/watch?v=abc",
            "",
            None,
        ):
            with self.subTest(url=url):
                self.assertFalse(ns.is_native_source_url(url))
                self.assertIsNone(ns.resolve_native_source(url, fetch=_Fetch()))


class KickResolutionTests(unittest.TestCase):
    def test_a_vod_resolves_to_its_manifest_with_title_and_duration(self):
        fetch = _Fetch(200, _ok_body())
        found = ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=fetch)
        self.assertEqual(found["url"], MANIFEST)
        self.assertEqual(found["title"], "HUGE BOXING EVENT | ORLANDO, FL")
        self.assertEqual(found["duration"], 30116)
        self.assertEqual(found["channel"], "loulz")
        self.assertEqual(found["site"], "kick")
        self.assertEqual(found["headers"]["User-Agent"], ns.NATIVE_SOURCE_USER_AGENT)

    def test_the_request_is_the_one_kicks_player_makes(self):
        fetch = _Fetch(200, _ok_body())
        ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=fetch)
        [call] = fetch.calls
        self.assertEqual(call["url"], ns.KICK_PLAYBACK_ENDPOINT.format(video_id=VOD))
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["headers"]["User-Agent"], ns.NATIVE_SOURCE_USER_AGENT)
        payload = json.loads(call["data"])
        # The endpoint rejects an empty body; the ads flag keeps the session
        # from carrying an advertising profile.
        self.assertEqual(payload["user_session"], {"non_personalised_ads": True})
        self.assertIn("video_player", payload)

    def test_a_slugless_permalink_takes_the_channel_from_the_session(self):
        found = ns.resolve_native_source(
            f"https://kick.com/video/{VOD}", fetch=_Fetch(200, _ok_body()),
        )
        self.assertEqual(found["channel"], "Loulz")

    def test_a_missing_title_falls_back_to_something_nameable(self):
        body = _ok_body(video_session={"video_duration": "oops"})
        found = ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=_Fetch(200, body))
        self.assertEqual(found["title"], f"loulz VOD {VOD[:8]}")
        self.assertEqual(found["duration"], 0)

    def test_a_bare_string_playback_url_is_accepted(self):
        body = _ok_body(playback_url=MANIFEST)
        found = ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=_Fetch(200, body))
        self.assertEqual(found["url"], MANIFEST)

    def test_a_refusal_is_a_200_with_a_data_object(self):
        body = json.dumps({"data": {"type": "Forbidden", "details": "subscriber"}}).encode()
        with self.assertRaises(ns.NativeSourceError) as raised:
            ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=_Fetch(200, body))
        self.assertEqual(raised.exception.code, "source-unavailable")
        self.assertIn("Forbidden", str(raised.exception))

    def test_a_404_hands_the_link_back_to_ytdlp(self):
        # On 2026-10-06 the playback endpoint answered 404 for every VOD while
        # yt-dlp's kick:vod extracted them again, so a 404 is a retired route,
        # not a missing video.
        body = json.dumps({"data": {"details": "Requested resource not found", "type": "NOT_FOUND"}}).encode()
        self.assertIsNone(
            ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=_Fetch(404, body))
        )

    def test_an_unreachable_host_is_a_network_condition(self):
        fetch = _Fetch(error=OSError("connection reset"))
        with self.assertRaises(ns.NativeSourceError) as raised:
            ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=fetch)
        self.assertEqual(raised.exception.code, "network-unreachable")

    def test_a_session_with_no_media_url_is_refused_not_handed_to_ytdlp(self):
        for body in (
            _ok_body(playback_url={"vod": "", "live": ""}),
            _ok_body(playback_url="ftp://nope"),
            b"not json",
            b"[]",
        ):
            with self.subTest(body=body[:20]):
                with self.assertRaises(ns.NativeSourceError):
                    ns.resolve_native_source(f"https://kick.com/loulz/videos/{VOD}", fetch=_Fetch(200, body))


class ArgvTests(unittest.TestCase):
    def test_the_argv_sends_the_user_agent_and_injects_the_title(self):
        args = ns.native_source_argv({
            "url": MANIFEST,
            "title": "Fight night",
            "headers": {"User-Agent": "UA/1", "X-Extra": "v"},
        })
        self.assertEqual(args[args.index("--user-agent") + 1], "UA/1")
        self.assertIn("--add-header", args)
        self.assertEqual(args[args.index("--add-header") + 1], "X-Extra:v")
        self.assertEqual(args[args.index("--parse-metadata") + 1], "Fight night:(?P<title>.+)")

    def test_title_characters_that_would_break_parse_metadata_are_escaped(self):
        args = ns.native_source_argv({"url": MANIFEST, "title": "A: 100% real\nB", "headers": {}})
        value = args[args.index("--parse-metadata") + 1]
        # `:` splits FROM from TO, `%` is a template escape, and a newline
        # would end the option value.
        self.assertEqual(value, "A\\: 100%% real B:(?P<title>.+)")

    def test_nothing_resolved_means_no_argv(self):
        self.assertEqual(ns.native_source_argv(None), [])
        self.assertEqual(ns.native_source_argv({"url": MANIFEST, "title": "", "headers": {}}), [])


class _ChangedExtractor:
    """Stands in for an upstream extractor whose source has moved on."""


class UpstreamReasonGateTests(unittest.TestCase):
    """scripts/check-site-registry.py re-checks why each resolver exists."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "scripts" / "check-site-registry.py"
        spec = importlib.util.spec_from_file_location("astra_check_site_registry", path)
        cls.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.gate)
        cls.reviewed = datetime.date.fromisoformat(ns.NATIVE_SOURCE_USER_AGENT_REVIEWED)

    def test_the_recorded_extractor_matches_the_installed_ytdlp(self):
        extractors = self.gate.installed_extractor_classes()
        if extractors is None:
            self.skipTest("yt-dlp is not installed")
        failures = []
        self.gate.check_native_sources(
            failures, extractors, today=self.reviewed, upstream=ns.NATIVE_SOURCE_UPSTREAM,
        )
        self.assertEqual(failures, [])

    def test_a_changed_or_missing_extractor_is_reported(self):
        for extractors in ({"kick:vod": _ChangedExtractor}, {}):
            with self.subTest(names=sorted(extractors)):
                failures = []
                self.gate.check_native_sources(
                    failures, extractors, today=self.reviewed, upstream=ns.NATIVE_SOURCE_UPSTREAM,
                )
                self.assertEqual(len(failures), 1)
                self.assertIn("kick:vod", failures[0])

    def test_the_user_agent_review_lapses_after_a_year(self):
        for days, expected in ((365, 0), (366, 1)):
            with self.subTest(days=days):
                failures = []
                self.gate.check_native_sources(
                    failures, None, today=self.reviewed + datetime.timedelta(days=days),
                )
                self.assertEqual(len(failures), expected)


if __name__ == "__main__":
    unittest.main()
