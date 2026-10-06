"""The Astra Deck userscript pairs through a window the user opens here.

A userscript manager sends no Origin and has no native messaging channel, so
neither extension path can reach it. These pin the one-shot window, the route
that hands over the token while it is open, the /health flag that tells a
saved token from a stale one, and the Browser extension page controls.
"""

import socket
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


TOKEN = "u" * 32
USERSCRIPT_BODY = {"id": ad.USERSCRIPT_CLIENT_ID}
CLIENT_HEADERS = {"X-MDL-Client": "MediaDL"}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class UserscriptPairingWindowTests(unittest.TestCase):
    def test_the_window_is_single_use(self):
        clock = _Clock()
        window = ad.UserscriptPairingWindow(clock=clock)
        self.assertEqual(window.state(), "idle")
        self.assertFalse(window.consume(), "a window nobody opened grants nothing")

        self.assertEqual(window.open(), ad.USERSCRIPT_PAIRING_WINDOW_SECONDS)
        self.assertEqual(window.state(), "open")
        self.assertTrue(window.consume())
        self.assertEqual(window.state(), "paired")
        self.assertEqual(window.remaining(), 0)
        self.assertFalse(window.consume(), "the first grant closes it")

    def test_the_window_expires(self):
        clock = _Clock()
        window = ad.UserscriptPairingWindow(clock=clock)
        window.open(120)
        clock.now += 119
        self.assertEqual(window.remaining(), 1)
        clock.now += 1
        self.assertEqual(window.state(), "expired")
        self.assertFalse(window.consume())

    def test_reopening_clears_an_earlier_grant(self):
        window = ad.UserscriptPairingWindow(clock=_Clock())
        window.open()
        window.consume()
        window.open()
        self.assertEqual(window.state(), "open")
        window.close()
        self.assertEqual(window.state(), "idle")


class PairUserscriptTests(unittest.TestCase):
    def _open_window(self):
        window = ad.UserscriptPairingWindow(clock=_Clock())
        window.open()
        return window

    def test_hands_over_the_token_with_no_origin(self):
        window = self._open_window()
        result = ad.pair_userscript(FakeConfig({"ServerToken": TOKEN}), "", window=window)
        self.assertTrue(result["ok"])
        self.assertTrue(result["userscript"])
        self.assertEqual(result["token"], TOKEN)

    def test_accepts_a_userscript_managers_extension_origin(self):
        window = self._open_window()
        result = ad.pair_userscript(
            FakeConfig({"ServerToken": TOKEN}),
            "chrome-extension://dhdgffkkebhmkfjojejmpbldmpobfkfo",
            window=window,
        )
        self.assertEqual(result.get("token"), TOKEN)

    def test_web_and_null_origins_never_spend_the_window(self):
        window = self._open_window()
        config = FakeConfig({"ServerToken": TOKEN})
        for origin in ("https://www.youtube.com", "null", "http://127.0.0.1:9751"):
            with self.subTest(origin=origin):
                result = ad.pair_userscript(config, origin, window=window)
                self.assertEqual(result["code"], "invalid-origin")
                self.assertNotIn("token", result)
        self.assertEqual(window.state(), "open")

    def test_closed_window_and_missing_token_are_refused(self):
        closed = ad.UserscriptPairingWindow(clock=_Clock())
        result = ad.pair_userscript(FakeConfig({"ServerToken": TOKEN}), "", window=closed)
        self.assertEqual(result["code"], "userscript-pairing-closed")
        self.assertNotIn("token", result)

        result = ad.pair_userscript(FakeConfig({"ServerToken": ""}), "", window=self._open_window())
        self.assertEqual(result["code"], "token-unavailable")


class UserscriptPairingRouteTests(unittest.TestCase):
    def setUp(self):
        ad.USERSCRIPT_PAIRING.close()
        self.addCleanup(ad.USERSCRIPT_PAIRING.close)
        self.config = FakeConfig({"ServerToken": TOKEN, "LegacyHealthTokenEcho": False})
        manager = ad.DownloadManager(self.config, FakeHistory())
        self.client = ad.create_api(self.config, manager, FakeHistory()).test_client()

    def test_closed_window_names_the_fix(self):
        resp = self.client.post("/pair-extension", json=USERSCRIPT_BODY, headers=CLIENT_HEADERS)
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertEqual(body["code"], "userscript-pairing-closed")
        self.assertIn("Pair userscript", body["error"])
        self.assertNotIn("token", body)

    def test_open_window_pairs_once_without_an_origin(self):
        ad.USERSCRIPT_PAIRING.open()
        first = self.client.post("/pair-extension", json=USERSCRIPT_BODY, headers=CLIENT_HEADERS)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["token"], TOKEN)
        self.assertIsNone(first.headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(ad.USERSCRIPT_PAIRING.state(), "paired")

        second = self.client.post("/pair-extension", json=USERSCRIPT_BODY, headers=CLIENT_HEADERS)
        self.assertEqual(second.status_code, 403)
        self.assertNotIn("token", second.get_json())

    def test_a_web_page_cannot_pair_as_the_userscript(self):
        ad.USERSCRIPT_PAIRING.open()
        resp = self.client.post(
            "/pair-extension",
            json=USERSCRIPT_BODY,
            headers={**CLIENT_HEADERS, "Origin": "https://www.youtube.com"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "invalid-origin")
        self.assertEqual(ad.USERSCRIPT_PAIRING.state(), "open")

    def test_an_extension_id_still_needs_an_extension_origin(self):
        ad.USERSCRIPT_PAIRING.open()
        resp = self.client.post(
            "/pair-extension",
            json={"id": "abcdefghijklmnopabcdefghijklmnop"},
            headers=CLIENT_HEADERS,
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "invalid-origin")
        self.assertEqual(ad.USERSCRIPT_PAIRING.state(), "open")

    def test_health_says_whether_the_presented_token_is_current(self):
        def health(token=None):
            headers = dict(CLIENT_HEADERS)
            if token is not None:
                headers["X-Auth-Token"] = token
            return self.client.get("/health", headers=headers).get_json()

        self.assertFalse(health()["authorized"])
        self.assertFalse(health("v" * 32)["authorized"])
        current = health(TOKEN)
        self.assertTrue(current["authorized"])
        self.assertNotIn("token", current, "a valid bearer is not a reason to echo it")


class PairUserscriptCommandTests(unittest.TestCase):
    def test_a_second_copy_sends_the_command_to_the_running_one(self):
        # The sender keeps its own allowlist; a verb missing from it was
        # dropped before it reached the socket, so `--pair-userscript` on a
        # running companion did nothing at all.
        ready = threading.Event()
        received = []
        port_holder = []

        def run_server():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.bind(("127.0.0.1", 0))
                port_holder.append(server.getsockname()[1])
                server.listen(1)
                ready.set()
                conn, _addr = server.accept()
                with conn:
                    received.append(conn.recv(128).decode("ascii").strip())

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(15))
        self.assertTrue(ad.send_instance_command(
            "pair-userscript", port=port_holder[0], attempts=1, token="t" * 32))
        thread.join(2)
        self.assertEqual(received, ["t" * 32 + " pair-userscript"])

    def test_the_listener_accepts_what_the_sender_sends(self):
        gui_source = Path(gui_module_for_tests().__file__).read_text(encoding="utf-8")
        self.assertIn("{'show', 'start', 'shutdown', 'pair-userscript'}", gui_source)

    def test_the_command_line_flag_outranks_a_background_start(self):
        self.assertEqual(
            ad.startup_command_from_argv(["--portable", "--start-server", "--pair-userscript"]),
            "pair-userscript",
        )
        self.assertEqual(ad.startup_command_from_argv(["--start-server"]), "start")


class UserscriptPairingPageTests(unittest.TestCase):
    class _Status:
        def __init__(self):
            self.value = ""
            self.visible = False
            self.properties = {}

        def setText(self, value):
            self.value = value

        def setVisible(self, value):
            self.visible = bool(value)

        def setProperty(self, key, value):
            self.properties[key] = value

    def _window(self, pairing):
        window = types.SimpleNamespace()
        window.logs = []
        window._append_log = window.logs.append
        window.userscript_pairing_status = self._Status()
        window._userscript_pairing_timer = mock.Mock()
        window._dependencies = {"userscript_pairing": lambda: pairing}
        gui = gui_module_for_tests()
        window._refresh_userscript_pairing = types.MethodType(
            gui.MainWindowCore._refresh_userscript_pairing, window
        )
        return window

    def _refresh(self, window):
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._refresh_userscript_pairing()
        return window.userscript_pairing_status

    def test_counts_down_then_reports_the_pairing(self):
        clock = _Clock()
        pairing = ad.UserscriptPairingWindow(clock=clock)
        pairing.open(120)
        clock.now += 15
        window = self._window(pairing)

        status = self._refresh(window)
        self.assertIn("1:45", status.value)
        self.assertTrue(status.visible)
        self.assertEqual(status.properties["tone"], "warning")
        window._userscript_pairing_timer.stop.assert_not_called()

        pairing.consume()
        status = self._refresh(window)
        self.assertIn("paired", status.value)
        self.assertEqual(status.properties["tone"], "success")
        window._userscript_pairing_timer.stop.assert_called_once_with()
        self.assertIn("Paired the Astra Deck userscript.", window.logs)

    def test_an_expired_window_says_to_try_again(self):
        clock = _Clock()
        pairing = ad.UserscriptPairingWindow(clock=clock)
        pairing.open(120)
        clock.now += 121
        status = self._refresh(self._window(pairing))
        self.assertIn("Pair userscript", status.value)
        self.assertEqual(status.properties["tone"], "danger")


if __name__ == "__main__":
    unittest.main()
