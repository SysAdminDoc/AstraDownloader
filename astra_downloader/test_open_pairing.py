"""Any copy of Astra Deck pairs on its own unless the user turns that off.

An unpacked extension gets its ID from its folder, so every copy, browser
profile and reinstall is a different ID. Each one used to need the pairing
window reopened, and the extension looked broken until someone found it.
These pin the open default, what it still refuses, and the two request
details older Astra Deck builds got refused for.
"""

import unittest
from unittest import mock

import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


TOKEN = "o" * 32
STRANGER = "ponmlkjihgfedcbaponmlkjihgfedcba"
CLIENT_HEADERS = {"X-MDL-Client": "MediaDL"}


def chrome_id(number):
    letters = "abcdefghijklmnop"
    return "".join(letters[(number >> shift) & 15] for shift in range(0, 128, 4))


class OpenPairingTests(unittest.TestCase):
    def pair(self, config, extension_id=STRANGER, **kwargs):
        kwargs.setdefault("refresh", mock.Mock(return_value=True))
        kwargs.setdefault("window", ad.UserscriptPairingWindow())
        return ad.pair_browser_extension(
            config, f"chrome-extension://{extension_id}", extension_id, **kwargs,
        )

    def test_pairing_is_open_unless_the_setting_says_otherwise(self):
        self.assertTrue(ad.DEFAULT_CONFIG["OpenExtensionPairing"])
        self.assertTrue(ad.open_pairing_enabled(FakeConfig()))
        self.assertFalse(ad.open_pairing_enabled(FakeConfig({"OpenExtensionPairing": False})))
        self.assertFalse(ad.open_pairing_enabled(FakeConfig({"OpenExtensionPairing": "false"})))
        broken = mock.Mock()
        broken.get.side_effect = OSError("config unreadable")
        self.assertFalse(ad.open_pairing_enabled(broken))

    def test_an_unknown_chrome_id_pairs_without_the_window(self):
        config = FakeConfig({"NativeChromeExtensionIds": ""})
        refresh = mock.Mock(return_value=True)
        closed = ad.UserscriptPairingWindow()
        result = self.pair(config, refresh=refresh, window=closed)
        self.assertTrue(result["ok"])
        self.assertTrue(result["paired"])
        self.assertNotIn("token", result)
        self.assertEqual(config.get("NativeChromeExtensionIds"), STRANGER)
        refresh.assert_called_once_with()
        self.assertEqual(closed.state(), "idle", "an unopened window is left alone")

    def test_a_web_page_still_cannot_pair(self):
        config = FakeConfig({"NativeChromeExtensionIds": ""})
        for origin in ("https://www.youtube.com", "null", "http://127.0.0.1:9751", ""):
            with self.subTest(origin=origin):
                result = ad.pair_browser_extension(config, origin, STRANGER, refresh=mock.Mock())
                self.assertEqual(result["code"], "invalid-origin")
        mismatch = ad.pair_browser_extension(
            config, f"chrome-extension://{STRANGER}", chrome_id(7), refresh=mock.Mock(),
        )
        self.assertEqual(mismatch["code"], "id-mismatch")
        self.assertEqual(config.get("NativeChromeExtensionIds"), "")

    def test_a_rebuilt_firefox_copy_with_its_own_id_pairs(self):
        config = FakeConfig({"NativeFirefoxExtensionIds": ""})
        origin = "moz-extension://0f6f1a52-3c1d-4b8e-9d55-2f1f7d0c9a11"
        result = ad.pair_browser_extension(
            config, origin, "astra-deck-dev@example.org", refresh=mock.Mock(return_value=True),
        )
        self.assertTrue(result["ok"])
        self.assertIn("astra-deck-dev@example.org", config.get("NativeFirefoxExtensionIds"))
        closed = FakeConfig({"NativeFirefoxExtensionIds": "", "OpenExtensionPairing": False})
        refused = ad.pair_browser_extension(
            closed, origin, "astra-deck-dev@example.org", refresh=mock.Mock(),
        )
        self.assertEqual(refused["code"], "unknown-firefox-id")

    def test_the_saved_list_keeps_the_newest_ids_and_the_published_one(self):
        published = ad.PUBLISHED_CHROME_EXTENSION_IDS[0]
        limit = ad.MAX_PAIRED_CHROME_EXTENSION_IDS
        config = FakeConfig({"NativeChromeExtensionIds": published})
        ids = [chrome_id(number) for number in range(1, limit + 6)]
        for extension_id in ids:
            self.assertTrue(self.pair(config, extension_id)["ok"])
        saved = ad.parse_native_extension_ids(config.get("NativeChromeExtensionIds"), browser="chrome")
        self.assertEqual(len(saved), limit)
        self.assertEqual(saved[0], published)
        self.assertEqual(saved[1:], ids[-(limit - 1):])
        self.assertEqual(ad._trim_paired_chrome_ids(["a", "b", "c"], 2), ["b", "c"])
        self.assertEqual(ad._trim_paired_chrome_ids([published, "a", "b"], 1), [published])

    def test_the_userscript_pairs_without_the_window(self):
        closed = ad.UserscriptPairingWindow()
        config = FakeConfig({"ServerToken": TOKEN})
        result = ad.pair_userscript(config, "", window=closed)
        self.assertEqual(result.get("token"), TOKEN)
        for origin in ("https://www.youtube.com", "null"):
            with self.subTest(origin=origin):
                refused = ad.pair_userscript(config, origin, window=closed)
                self.assertEqual(refused["code"], "invalid-origin")
                self.assertNotIn("token", refused)

    def test_an_open_window_still_records_who_paired(self):
        window = ad.UserscriptPairingWindow()
        window.open()
        ad.pair_userscript(FakeConfig({"ServerToken": TOKEN}), f"chrome-extension://{STRANGER}", window=window)
        self.assertEqual(window.state(), "paired")
        self.assertEqual(window.client(), f"chrome-extension://{STRANGER}")


class OpenPairingRouteTests(unittest.TestCase):
    def setUp(self):
        for window in (ad.USERSCRIPT_PAIRING, ad.EXTENSION_PAIRING):
            window.close()
            self.addCleanup(window.close)
        self.config = FakeConfig({
            "ServerToken": TOKEN, "LegacyHealthTokenEcho": False, "NativeChromeExtensionIds": "",
        })
        self.history = FakeHistory()
        manager = ad.DownloadManager(self.config, self.history)
        self.client = ad.create_api(self.config, manager, self.history).test_client()
        patcher = mock.patch.object(ad, "refresh_native_messaging_registration", return_value=True)
        self.refresh = patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_unpacked_copy_pairs_then_reads_the_token_from_health(self):
        origin = f"chrome-extension://{STRANGER}"
        headers = {**CLIENT_HEADERS, "Origin": origin}
        before = self.client.get("/health", headers=headers).get_json()
        self.assertNotIn("token", before)
        paired = self.client.post("/pair-extension", json={"id": STRANGER}, headers=headers)
        self.assertEqual(paired.status_code, 200)
        self.assertNotIn("token", paired.get_json())
        self.assertEqual(paired.headers.get("Access-Control-Allow-Origin"), origin)
        after = self.client.get("/health", headers=headers).get_json()
        self.assertEqual(after.get("token"), TOKEN)

    def test_a_web_page_gets_nothing_from_the_pairing_route(self):
        for body in ({"id": STRANGER}, {"id": ad.USERSCRIPT_CLIENT_ID}):
            with self.subTest(body=body):
                resp = self.client.post(
                    "/pair-extension", json=body,
                    headers={**CLIENT_HEADERS, "Origin": "https://www.youtube.com"},
                )
                self.assertEqual(resp.status_code, 403)
                self.assertNotIn("token", resp.get_json())
        self.assertEqual(self.config.get("NativeChromeExtensionIds"), "")

    def test_the_userscript_route_hands_over_the_token_without_a_window(self):
        resp = self.client.post(
            "/pair-extension", json={"id": ad.USERSCRIPT_CLIENT_ID}, headers=CLIENT_HEADERS,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["token"], TOKEN)

    def test_history_accepts_the_token_as_a_bearer_credential(self):
        # Astra Deck through 4.110 sent only Authorization: Bearer here, so its
        # history panel always read 401.
        def history(headers):
            return self.client.get("/history", headers={**CLIENT_HEADERS, **headers}).status_code

        self.assertEqual(history({"Authorization": f"Bearer {TOKEN}"}), 200)
        self.assertEqual(history({"Authorization": f"bearer {TOKEN}"}), 200)
        self.assertEqual(history({"X-Auth-Token": TOKEN}), 200)
        self.assertEqual(history({}), 401)
        self.assertEqual(history({"Authorization": "Bearer " + "x" * 32}), 401)
        self.assertEqual(history({"Authorization": f"Basic {TOKEN}"}), 401)
        self.assertEqual(history({"Authorization": TOKEN}), 401)
        # A wrong header token isn't rescued by a right bearer token.
        self.assertEqual(history({"X-Auth-Token": "x" * 32, "Authorization": f"Bearer {TOKEN}"}), 401)

    def test_one_busy_extension_does_not_use_up_everyones_health_checks(self):
        busy = {**CLIENT_HEADERS, "Origin": f"chrome-extension://{STRANGER}"}
        codes = [self.client.get("/health", headers=busy).status_code
                 for _ in range(ad.RATE_LIMIT_HEALTH_MAX + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(set(codes[:-1]), {200})
        other = {**CLIENT_HEADERS, "Origin": f"chrome-extension://{chrome_id(9)}"}
        self.assertEqual(self.client.get("/health", headers=other).status_code, 200)
        self.assertEqual(self.client.get("/health", headers=CLIENT_HEADERS).status_code, 200)


if __name__ == "__main__":
    unittest.main()
