"""Tests for the site capability registry.

The registry decides which cookies a download is allowed to carry, so its
scoping rules are tested the way a security boundary is: the widening cases
and the lookalike cases both get their own assertions, and the invariants that
keep a row reachable are checked here as well as in the gate, so a plain
`pytest` run catches a dead row without anyone remembering to run `npm run
check`.
"""

import unittest

try:
    from . import sites
except ImportError:  # Flat source-path compatibility.
    import sites


class RegistrableDomainTests(unittest.TestCase):
    def test_reduces_a_host_to_its_registrable_domain(self):
        for host, expected in (
            ("www.reddit.com", "reddit.com"),
            ("clips.twitch.tv", "twitch.tv"),
            ("REDDIT.COM", "reddit.com"),
            ("reddit.com.", "reddit.com"),
            ("youtube.com", "youtube.com"),
        ):
            with self.subTest(host=host):
                self.assertEqual(sites.registrable_domain(host), expected)

    def test_keeps_three_labels_for_a_two_label_public_suffix(self):
        # Reducing bbc.co.uk to co.uk would put every .co.uk site in one
        # cookie scope, which is the failure this list exists to prevent.
        self.assertEqual(sites.registrable_domain("www.bbc.co.uk"), "bbc.co.uk")
        self.assertEqual(sites.registrable_domain("sooplive.co.kr"), "sooplive.co.kr")

    def test_empty_and_malformed_hosts_reduce_to_nothing(self):
        for value in ("", None, "   ", "."):
            with self.subTest(value=value):
                self.assertEqual(sites.registrable_domain(value), "")

    def test_site_key_reads_a_url_or_a_bare_host(self):
        self.assertEqual(
            sites.site_key_for_url("https://www.twitch.tv/videos/1"), "twitch.tv"
        )
        self.assertEqual(sites.site_key_for_url("twitch.tv"), "twitch.tv")
        self.assertEqual(sites.site_key_for_url(""), "")

    def test_a_nonsense_input_produces_a_key_that_matches_no_real_host(self):
        # Garbage in is not an error here, but it must not become a scope that
        # matches something real.
        key = sites.site_key_for_url("not a url")
        self.assertEqual(sites.cookie_domains_for_site(key), frozenset())


class ProfileResolutionTests(unittest.TestCase):
    def test_a_subdomain_resolves_to_its_site(self):
        profile = sites.resolve_site_profile("https://clips.twitch.tv/abc")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["key"], "twitch.tv")

    def test_an_alias_resolves_to_the_site_it_belongs_to(self):
        for url in ("https://youtu.be/abc", "https://www.youtube-nocookie.com/embed/a"):
            with self.subTest(url=url):
                profile = sites.resolve_site_profile(url)
                self.assertIsNotNone(profile)
                self.assertEqual(profile["key"], "youtube.com")

    def test_an_unknown_site_resolves_to_nothing(self):
        # The healthy answer for most of the web: yt-dlp's own extractor
        # handles it and the registry has nothing to add.
        self.assertIsNone(sites.resolve_site_profile("https://example.com/watch"))
        self.assertEqual(sites.site_display_name("https://example.com/v"), "example.com")

    def test_every_key_alias_and_cookie_domain_is_reachable(self):
        # A key that is not its own registrable domain can never match a URL,
        # so the row is dead while looking configured.
        for key, profile in sites.SITE_PROFILES.items():
            with self.subTest(site=key):
                self.assertEqual(sites.registrable_domain(key), key)
                resolved = sites.resolve_site_profile(f"https://{key}/watch")
                self.assertIsNotNone(resolved)
                self.assertEqual(resolved["key"], key)
            for alias in profile["aliases"]:
                with self.subTest(site=key, alias=alias):
                    self.assertEqual(sites.registrable_domain(alias), alias)
            for domain in profile["cookie_domains"]:
                with self.subTest(site=key, cookie_domain=domain):
                    self.assertEqual(sites.registrable_domain(domain), domain)

    def test_declared_categories_and_auth_levels_are_from_the_vocabulary(self):
        for key, profile in sites.SITE_PROFILES.items():
            with self.subTest(site=key):
                self.assertIn(profile["category"], sites.SITE_CATEGORIES)
                self.assertIn(profile["auth"], sites.SITE_AUTH_LEVELS)


class CookieScopeTests(unittest.TestCase):
    def test_youtube_scope_includes_the_google_account_domains(self):
        # A YouTube session lives on Google's account domains too. Scoping to
        # the registrable domain alone signs the user out silently.
        scope = sites.cookie_domains_for_site("youtube.com")
        self.assertIn("youtube.com", scope)
        self.assertIn("google.com", scope)
        self.assertTrue(
            sites.cookie_domain_belongs_to_site(".accounts.google.com", "youtube.com")
        )

    def test_another_site_does_not_get_the_google_domains(self):
        self.assertNotIn("google.com", sites.cookie_domains_for_site("twitch.tv"))
        self.assertFalse(
            sites.cookie_domain_belongs_to_site(".accounts.google.com", "twitch.tv")
        )

    def test_a_lookalike_domain_is_outside_the_scope(self):
        for domain in (
            "notyoutube.com",
            "youtube.com.evil.net",
            "evilyoutube.com",
        ):
            with self.subTest(domain=domain):
                self.assertFalse(
                    sites.cookie_domain_belongs_to_site(domain, "youtube.com")
                )

    def test_a_real_subdomain_is_inside_the_scope(self):
        self.assertTrue(
            sites.cookie_domain_belongs_to_site(".www.youtube.com", "youtube.com")
        )

    def test_the_filter_accepts_only_the_downloads_own_site(self):
        allow = sites.build_site_cookie_filter("https://www.twitch.tv/videos/1")
        self.assertTrue(allow(".twitch.tv"))
        self.assertTrue(allow("twitch.tv"))
        self.assertFalse(allow(".youtube.com"))
        self.assertFalse(allow(""))

    def test_an_unknown_site_still_gets_a_filter_scoped_to_itself(self):
        # A site with no registry row is the common case, and it must still
        # be able to carry its own cookies.
        allow = sites.build_site_cookie_filter("https://example.com/watch")
        self.assertIsNotNone(allow)
        self.assertTrue(allow(".example.com"))
        self.assertFalse(allow(".youtube.com"))

    def test_a_url_with_no_host_gets_no_filter(self):
        # None means "write no jar", which callers must not confuse with a
        # filter that accepts everything.
        self.assertIsNone(sites.build_site_cookie_filter(""))
        self.assertIsNone(sites.build_site_cookie_filter("not-a-url"))

    def test_a_single_label_host_is_refused_rather_than_scoped_to_a_suffix(self):
        # A scope of {"com"} would match every .com cookie by the subdomain
        # rule, so one jar would carry the whole web's sessions. The URL
        # policy rejects single-label hosts first, but this must fail closed
        # on its own.
        self.assertEqual(sites.cookie_domains_for_site("com"), frozenset())
        self.assertFalse(sites.cookie_domain_belongs_to_site(".youtube.com", "com"))
        self.assertIsNone(sites.build_site_cookie_filter("https://com"))


class ArgvContributionTests(unittest.TestCase):
    def test_extractor_args_are_emitted_as_flag_value_pairs(self):
        for key, profile in sites.SITE_PROFILES.items():
            if not profile["extractor_args"]:
                continue
            args = sites.build_site_extractor_args(f"https://{key}/watch")
            with self.subTest(site=key):
                self.assertEqual(len(args), 2 * len(profile["extractor_args"]))
                self.assertEqual(args[0::2], ["--extractor-args"] * len(profile["extractor_args"]))

    def test_every_declared_extractor_arg_is_a_known_option(self):
        # An invented argument is ignored by yt-dlp without a warning, so a
        # profile carrying one claims to configure something and does not.
        for key, profile in sites.SITE_PROFILES.items():
            for value in profile["extractor_args"]:
                namespace, _, rest = value.partition(":")
                with self.subTest(site=key, arg=value):
                    self.assertIn(
                        f"{namespace}:{rest.partition('=')[0]}",
                        sites.KNOWN_EXTRACTOR_ARG_KEYS,
                    )

    def test_a_site_behind_a_fingerprint_check_asks_for_impersonation(self):
        self.assertEqual(sites.site_impersonate_target("https://kick.com/x"), "chrome")
        self.assertEqual(sites.site_impersonate_target("https://example.com/x"), "")

    def test_referer_is_the_sites_own_origin(self):
        self.assertEqual(
            sites.site_referer_for_url("https://vimeo.com/123"), "https://vimeo.com/"
        )
        self.assertEqual(sites.site_referer_for_url("https://youtube.com/watch"), "")

    def test_referer_is_refused_for_a_non_http_url(self):
        self.assertEqual(sites.site_referer_for_url("ftp://vimeo.com/1"), "")
        self.assertEqual(sites.site_referer_for_url(""), "")


class AuthExpectationTests(unittest.TestCase):
    def test_a_site_that_needs_a_sign_in_says_so(self):
        level, note = sites.site_auth_expectation("https://www.instagram.com/reel/a/")
        self.assertEqual(level, sites.SITE_AUTH_REQUIRED)
        self.assertTrue(note)
        self.assertTrue(sites.site_expects_sign_in("https://www.instagram.com/reel/a/"))

    def test_an_unknown_site_expects_nothing(self):
        level, note = sites.site_auth_expectation("https://example.com/v")
        self.assertEqual(level, sites.SITE_AUTH_NONE)
        self.assertEqual(note, "")
        self.assertEqual(sites.describe_site_auth("https://example.com/v"), "")

    def test_credential_support_is_declared_rather_than_assumed(self):
        # Most sites can only be signed in to with cookies. Saying so up front
        # beats letting a stored password fail on every download.
        self.assertTrue(sites.site_supports_credentials("https://vimeo.com/1"))
        self.assertFalse(
            sites.site_supports_credentials("https://www.reddit.com/r/a/comments/b/c/")
        )


class CatalogueTests(unittest.TestCase):
    def test_the_catalogue_covers_every_profile_and_is_sorted_by_name(self):
        rows = sites.site_catalog()
        self.assertEqual(len(rows), len(sites.SITE_PROFILES))
        names = [row["name"].casefold() for row in rows]
        self.assertEqual(names, sorted(names))
        self.assertTrue(
            all(row["source"] == sites.CATALOG_SOURCE_CURATED for row in rows)
        )

    def test_extractor_names_are_merged_under_the_curated_rows(self):
        rows = sites.merge_extractor_names(["SomeObscureSite", "Twitch", "youtube.com"])
        curated = [r for r in rows if r["source"] == sites.CATALOG_SOURCE_CURATED]
        extra = [r for r in rows if r["source"] == sites.CATALOG_SOURCE_EXTRACTOR]
        self.assertEqual(len(curated), len(sites.SITE_PROFILES))
        # "Twitch" and "youtube.com" already exist as a curated name and key,
        # so only the unknown extractor is added.
        self.assertEqual([row["name"] for row in extra], ["SomeObscureSite"])

    def test_merging_is_case_insensitive_and_drops_duplicates(self):
        rows = sites.merge_extractor_names(["Dupe", "dupe", "DUPE", "", None])
        extra = [r for r in rows if r["source"] == sites.CATALOG_SOURCE_EXTRACTOR]
        self.assertEqual([row["name"] for row in extra], ["Dupe"])

    def test_search_matches_name_domain_and_notes(self):
        rows = sites.site_catalog()
        self.assertTrue(sites.search_site_catalog(rows, "twitch"))
        self.assertTrue(sites.search_site_catalog(rows, "kick.com"))
        self.assertFalse(sites.search_site_catalog(rows, "zzzz-no-such-site"))

    def test_search_filters_by_category(self):
        rows = sites.site_catalog()
        live = sites.search_site_catalog(rows, "", "live")
        self.assertTrue(live)
        self.assertTrue(all(row["category"] == "live" for row in live))

    def test_search_combines_query_and_category(self):
        rows = sites.site_catalog()
        self.assertTrue(sites.search_site_catalog(rows, "kick", "live"))
        self.assertFalse(sites.search_site_catalog(rows, "kick", "news"))


if __name__ == "__main__":
    unittest.main()
