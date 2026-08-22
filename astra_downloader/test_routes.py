"""Tests for the local API and the processes that talk to it."""

import ast
import hashlib
import inspect
import io
import re
import json
import os
import queue
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
from datetime import datetime, timedelta
from unittest import mock
from pathlib import Path
import xml.etree.ElementTree as ET
import astra_downloader as ad

try:
    from .testing_support import *  # noqa: F401,F403
except ImportError:  # Flat source-path compatibility.
    from testing_support import *  # noqa: F401,F403


class MediaServerSidecarTests(unittest.TestCase):
    """NFO output stays valid, bounded, and in the media folder."""

    def test_item_nfo_uses_provider_ids_and_escapes_fetched_metadata(self):
        payload = ad.build_media_server_nfo({
            "id": "video-123",
            "title": "A & <clip>",
            "description": "Plot with > and < characters",
            "duration": 181,
            "upload_date": "20260811",
            "extractor_key": "Youtube",
            "channel": "Channel & Co",
            "categories": ["News"],
            "tags": ["one", "two"],
            "thumbnail": "https://cdn.example/thumb.jpg",
            "webpage_url": "https://www.youtube.com/watch?v=video-123",
        })
        root = ET.fromstring(payload)

        self.assertEqual(root.tag, "movie")
        self.assertEqual(root.findtext("title"), "A & <clip>")
        self.assertEqual(root.findtext("plot"), "Plot with > and < characters")
        self.assertEqual(root.findtext("runtime"), "3")
        self.assertEqual(root.findtext("premiered"), "2026-08-11")
        self.assertEqual(root.findtext("youtubeid"), "video-123")
        uniqueid = root.find("uniqueid")
        self.assertIsNotNone(uniqueid)
        self.assertEqual(uniqueid.attrib, {"type": "youtube", "default": "true"})
        self.assertEqual(uniqueid.text, "video-123")
        self.assertEqual([item.text for item in root.findall("genre")], ["News"])
        self.assertEqual([item.text for item in root.findall("tag")], ["one", "two"])

    def test_channel_download_writes_item_show_and_season_nfo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "Channel & Co"
            season = root / "Season 01"
            season.mkdir(parents=True)
            records = []
            for index in (1, 2):
                media = season / f"Episode {index}.mp4"
                media.write_bytes(b"media")
                metadata = {
                    "id": f"video-{index}",
                    "title": f"Episode {index}",
                    "playlist_title": "Channel & Co",
                    "playlist_id": "channel-123",
                    "playlist_index": index,
                    "extractor_key": "Youtube",
                    "channel": "Channel & Co",
                }
                info = Path(f"{media}.info.json")
                info.write_text(json.dumps(metadata), encoding="utf-8")
                records.append((media, info))

            written = ad.write_media_server_sidecars(root)

            self.assertEqual(
                {path.name for path in written},
                {"Episode 1.nfo", "Episode 2.nfo", "tvshow.nfo", "season.nfo"},
            )
            item_root = ET.parse(records[0][0].with_suffix(".nfo")).getroot()
            self.assertEqual(item_root.tag, "episodedetails")
            self.assertEqual(item_root.findtext("showtitle"), "Channel & Co")
            self.assertEqual(item_root.findtext("season"), "1")
            self.assertEqual(item_root.findtext("episode"), "1")
            show_root = ET.parse(root / "tvshow.nfo").getroot()
            self.assertEqual(show_root.tag, "tvshow")
            self.assertEqual(show_root.findtext("title"), "Channel & Co")
            self.assertEqual(show_root.findtext("youtubeid"), "channel-123")
            season_root = ET.parse(season / "season.nfo").getroot()
            self.assertEqual(season_root.tag, "season")
            self.assertEqual(season_root.findtext("seasonnumber"), "1")
            self.assertEqual(season_root.findtext("showtitle"), "Channel & Co")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_nfo_writer_rejects_metadata_paths_and_bounds_untrusted_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            media = root / "clip.mp4"
            media.write_bytes(b"media")
            with self.assertRaises(ValueError):
                ad.write_media_server_nfo({}, root / "clip.info.json")
            payload = ad.build_media_server_nfo({
                "title": "\x00" + ("x" * (ad.NFO_MAX_TEXT_CHARS + 50)),
                "id": "safe-id",
            })
            parsed = ET.fromstring(payload)
            self.assertLessEqual(len(parsed.findtext("title")), ad.NFO_MAX_TEXT_CHARS)
            self.assertNotIn("\x00", payload.decode("utf-8"))


class InstanceCommandTests(unittest.TestCase):
    def test_startup_command_detects_protocol_launches(self):
        self.assertEqual(ad.startup_command_from_argv(["mediadl://start"]), "start")
        self.assertEqual(ad.startup_command_from_argv(["ytdl://download"]), "start")
        self.assertEqual(ad.startup_command_from_argv(["--start-server"]), "start")
        self.assertEqual(ad.startup_command_from_argv(["--uninstall"]), "")

    def test_protocol_links_carry_their_url(self):
        # The handler is registered as `<exe> "%1"`, and every one of those
        # links used to map to the literal command 'start' — the app opened
        # and queued nothing.
        cases = (
            ("ytdl://https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc",
             "https://www.youtube.com/watch?v=abc"),
            ("mediadl://https://vimeo.com/123456789",
             "https://vimeo.com/123456789"),
            ("ytdl://www.youtube.com/watch?v=abc",
             "https://www.youtube.com/watch?v=abc"),
            ("ytdl://start", ""),
            ("ytdl://", ""),
            ("ytdl://not a url", ""),
        )
        for argument, expected in cases:
            with self.subTest(argument=argument):
                self.assertEqual(
                    ad.download_url_from_protocol_argv([argument]), expected)

        self.assertEqual(
            ad.startup_command_from_argv(["ytdl://https://vimeo.com/1"]),
            "download https://vimeo.com/1",
        )
        self.assertEqual(ad.startup_command_from_argv(["ytdl://start"]), "start")

    def test_a_download_command_reaches_the_paste_box(self):
        class Window:
            pass

        window = Window()
        events = []
        window._append_log = events.append
        window.enqueue_protocol_download = lambda url: events.append(f"queued {url}")

        ad.MainWindow._handle_instance_command(
            window, "download https://www.youtube.com/watch?v=AbCdEf")

        self.assertEqual(events[-1], "queued https://www.youtube.com/watch?v=AbCdEf")

    def test_send_instance_command_carries_a_download_url_intact(self):
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
                    received.append(conn.recv(512).decode("ascii").strip())

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(15))
        self.assertTrue(ad.send_instance_command(
            "download https://www.youtube.com/watch?v=AbCdEf",
            port=port_holder[0], attempts=1, token="d" * 32,
        ))
        thread.join(2)
        # The token is split off on the FIRST space, so the URL survives whole
        # and its case is not folded.
        self.assertEqual(
            received,
            ["d" * 32 + " download https://www.youtube.com/watch?v=AbCdEf"],
        )

    def test_send_instance_command_posts_start_to_listener(self):
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
            "start", port=port_holder[0], attempts=1, token="t" * 32))
        thread.join(2)
        self.assertEqual(received, ["t" * 32 + " start"])

    def test_send_instance_command_posts_show_to_listener(self):
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
            "show", port=port_holder[0], attempts=1, token="s" * 32))
        thread.join(2)
        self.assertEqual(received, ["s" * 32 + " show"])

    def test_instance_control_listener_rejects_an_untokened_command(self):
        from PySide6.QtWidgets import QApplication, QPushButton

        _get_qapp_or_skip(self)
        token = "c" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        with mock.patch.object(ad.MainWindow, "_start_readiness_probe"), \
                mock.patch.object(ad.MainWindow, "_start_instance_command_listener"), \
                mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())

        try:
            window._dependencies['INSTANCE_CONTROL_PORT'] = lambda: port
            commands = []
            window.instance_command.connect(commands.append)
            window._start_instance_command_listener()

            self.assertTrue(ad.send_instance_command(
                "shutdown", port=port, attempts=10, token="wrong-token"))
            # A protocol link is the command most likely to be dropped: it is
            # the only one carrying an argument, and asserting solely that an
            # untokened command never arrives passes just as happily against a
            # listener that forwards nothing but "show".
            url = "https://www.youtube.com/watch?v=AbCdEf"
            self.assertTrue(ad.send_instance_command(
                f"download {url}", port=port, attempts=10, token=token))
            self.assertTrue(ad.send_instance_command(
                "show", port=port, attempts=10, token=token))

            deadline = time.monotonic() + 3
            while len(commands) < 2 and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)

            self.assertEqual(
                commands, [f"download {url}", "show"],
                "a tokened download must arrive with its URL case intact, and "
                "an unauthenticated shutdown must never reach the window",
            )
        finally:
            window._stop_instance_command_listener()
            _retire_test_window(window)

    def test_occupied_source_lock_delegates_without_killing_existing_instance(self):
        class OccupiedSocket:
            def bind(self, _address):
                raise OSError("occupied")

            def close(self):
                return None

        with mock.patch.object(ad.sys, "platform", "linux"), \
             mock.patch.object(ad.socket, "socket", return_value=OccupiedSocket()), \
             mock.patch.object(ad, "send_instance_command", return_value=True) as send:
            result = ad.check_single_instance()

        self.assertIs(result, ad.INSTANCE_ALREADY_RUNNING)
        send.assert_called_once_with("show", attempts=1)

    def test_existing_window_show_command_restores_window(self):
        class Window:
            pass

        window = Window()
        events = []
        window._append_log = events.append
        window._show_from_tray = lambda: events.append("shown")

        ad.MainWindow._handle_instance_command(window, "show")

        self.assertEqual(events[-1], "shown")


class PoTokenProviderNudgeTests(unittest.TestCase):
    """No token-free client covers the whole catalogue, so a failure that a
    provider would fix has to say so."""

    def _classify(self, text):
        return ad.classify_download_failure(text, [text])

    def test_age_gate_and_unplayable_statuses_classify_as_sign_in_required(self):
        # The token-exempt chain surfaces the age gate as a bare playability
        # status rather than prose, and that used to classify as nothing.
        for text in (
            'ERROR: [youtube] abc: Video unavailable. Status: LOGIN_REQUIRED',
            'ERROR: [youtube] abc: This video is age-restricted',
            'ERROR: [youtube] abc: Playability status UNPLAYABLE',
            'ERROR: [youtube] abc: This video is available to members only',
        ):
            self.assertEqual(self._classify(text), 'sign-in-required', text)

    def test_tv_downgraded_unplayable_is_cookie_incompatible_not_sign_in(self):
        # yt-dlp#17389: some jars make public videos UNPLAYABLE on tv_downgraded.
        # Telling the user to add cookies is the opposite of the fix.
        self.assertEqual(
            self._classify(
                'ERROR: [youtube] abc: Playability status UNPLAYABLE; tv_downgraded'
            ),
            'cookie-incompatible',
        )
        dl = ad.Download('dl_cookie', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        ad.apply_download_failure_classification(dl, 'cookie-incompatible')
        self.assertNotIn('sign in', dl.error_advice.lower())
        self.assertIn('skip', dl.error_advice.lower())

    def test_advice_does_not_recommend_a_disabled_provider(self):
        nudge = ad.po_provider_nudge_advice
        self.assertEqual(ad.PO_PROVIDER_NUDGE_CODES, frozenset())
        for code in ('sign-in-required', 'sabr-limited', 'po-token-required'):
            self.assertEqual(nudge('Base advice.', code, False), 'Base advice.')
            self.assertEqual(nudge('Base advice.', code, True), 'Base advice.')
        self.assertEqual(nudge('Base advice.', 'ffmpeg-missing-or-stale', False), 'Base advice.')

    def test_failure_classification_does_not_offer_a_disabled_provider(self):
        dl = ad.Download('dl_nudge', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        ad.apply_download_failure_classification(
            dl, 'sign-in-required', provider_running=False,
        )
        self.assertNotIn('bgutil-ytdlp-pot-provider', dl.error_advice)

        running = ad.Download('dl_ok', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        ad.apply_download_failure_classification(
            running, 'sign-in-required', provider_running=True,
        )
        self.assertNotIn('No PO-token provider is running', running.error_advice)

    def test_download_path_does_not_probe_or_route_through_a_provider(self):
        captured = []

        class Proc:
            returncode = 0

            def __init__(self, args, **_kwargs):
                captured.append(list(args))
                self.stdout = iter(["[download] Destination: clip.mp4\n"])

            def wait(self):
                return 0

            def poll(self):
                return self.returncode

            def terminate(self):
                pass

            def kill(self):
                pass

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ad.DownloadManager(
                FakeConfig({"DownloadPath": tmpdir, "AudioDownloadPath": tmpdir}),
                FakeHistory(),
            )
            manager._dependencies["probe_po_token_provider"] = mock.Mock(
                side_effect=AssertionError("download path must not probe a provider")
            )
            manager._dependencies["spawn_ytdlp"] = Proc
            manager._dependencies["probe_javascript_runtime"] = (
                lambda **_kwargs: {}
            )
            manager._dependencies["build_javascript_runtime_args"] = (
                lambda *_args, **_kwargs: []
            )
            download = ad.Download(
                "dl_nudge_behavior",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir=tmpdir,
            )
            download.status = "queued"
            manager._run_download(download)

        self.assertEqual(download.status, "complete")
        self.assertEqual(len(captured), 1)
        self.assertTrue(any(
            argument.startswith(
                "youtube:player_client=visionos,tv,web_embedded"
            )
            for argument in captured[0]
        ))
        self.assertFalse(any(
            "android_vr" in argument for argument in captured[0]
        ))
        self.assertFalse(any(
            "youtubepot-bgutilhttp" in argument for argument in captured[0]
        ))


class PickFolderRouteTests(unittest.TestCase):
    """Flask-level coverage for /pick-folder.

    Regression: a nested route handler named ``queue`` shadowed the stdlib
    ``queue`` module inside create_api's closure scope, so every /pick-folder
    request died with an AttributeError-driven 500 before reaching the GUI
    bridge.
    """

    def test_pick_folder_round_trips_through_the_gui_bridge(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())

        while not ad._folder_pick_q.empty():
            ad._folder_pick_q.get_nowait()
        original_service = ad._folder_picker_service
        ad._folder_picker_service = object()  # non-None: picker "available"
        picked = tempfile.gettempdir()

        def serve_one_pick():
            request = ad._folder_pick_q.get(timeout=10)
            request['response'].put({'path': picked})

        worker = threading.Thread(target=serve_one_pick, daemon=True)
        worker.start()
        try:
            resp = api.test_client().post(
                "/pick-folder",
                json={},
                headers={"X-Auth-Token": token},
            )
        finally:
            worker.join(timeout=15)
            ad._folder_picker_service = original_service

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body.get('path'), picked)
        self.assertIn('outsideAllowlist', body)


class ApiSecurityTests(unittest.TestCase):
    def test_health_advertises_service_identity(self):
        config = FakeConfig({"ServerToken": "a" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/health", headers={"X-MDL-Client": "MediaDL"})
        body = resp.get_json()

        self.assertEqual(body["service"], ad.SERVICE_ID)
        self.assertEqual(body["api"], ad.SERVICE_API_VERSION)
        self.assertTrue(body["token_required"])
        self.assertFalse(body["legacyTokenEcho"])
        self.assertTrue(body["nativeChannelRequired"])
        self.assertIn("updateRecovery", body)
        self.assertNotIn("token", body)

    def test_health_recent_errors_require_auth(self):
        # Recent log lines can carry absolute paths / exception text, so the
        # otherwise-unauthenticated /health surface must only expose them to a
        # caller holding the bearer token.
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        ad.write_persistent_log("secret path C:/Users/tester/leak.txt")

        anon = client.get("/health", headers={"X-MDL-Client": "MediaDL"})
        self.assertEqual(anon.get_json()["recentErrors"], [])

        authed = client.get("/health", headers={
            "X-MDL-Client": "MediaDL",
            "X-Auth-Token": token,
        })
        entries = authed.get_json()["recentErrors"]
        self.assertTrue(entries, "authenticated /health must expose recent log entries")
        self.assertIn("leak.txt", json.dumps(entries))

    def test_health_subscription_list_requires_auth(self):
        # The snapshot names every channel this user follows. /health gates
        # recentErrors for the same reason and this sat two lines below it.
        class FakeSubscriptions:
            def snapshot(self):
                return {
                    "schedulerRunning": True,
                    "subscriptions": [{
                        "url": "https://www.youtube.com/@private-channel",
                        "title": "Private Channel",
                    }],
                    "archive": {},
                }

        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory(), FakeSubscriptions())
        client = api.test_client()

        anon = client.get("/health", headers={"X-MDL-Client": "MediaDL"}).get_json()
        self.assertNotIn("private-channel", json.dumps(anon))
        self.assertIn("version", anon, "discovery fields must stay unauthenticated")
        self.assertEqual(anon["service"], "astra-downloader")

        authed = client.get("/health", headers={
            "X-MDL-Client": "MediaDL",
            "X-Auth-Token": token,
        }).get_json()
        self.assertIn("private-channel", json.dumps(authed["subscriptions"]))

    def test_health_omits_local_runtime_paths_and_probes_once(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        runtime = {
            "runtime": "deno",
            "installed": True,
            "version": "2.4.1",
            "supported": True,
            "ejsReady": True,
            "source": "bundled",
            "path": "C:/Users/tester/AppData/Local/Astra Downloader/deno.exe",
            "ytdlpNeedsRuntime": True,
        }
        with mock.patch.object(ad, "probe_javascript_runtime", return_value=runtime) as probe:
            api = ad.create_api(config, manager, FakeHistory())
            body = api.test_client().get("/health").get_json()

        self.assertEqual(probe.call_count, 1)
        self.assertEqual(body["javascriptRuntime"], body["denoRuntime"])
        self.assertNotIn("path", body["javascriptRuntime"])
        self.assertEqual(body["javascriptRuntime"]["source"], "bundled")

    def test_evaluate_sabr_support_reflects_capability(self):
        import health as _health
        # Until the native SABR downloader (PR #13515) merges, the sentinel is
        # None and every version reports "limited".
        self.assertIsNone(_health.SABR_NATIVE_MIN_VERSION)
        self.assertEqual(_health.evaluate_sabr_support("2026.07.04"), "limited")
        self.assertEqual(_health.evaluate_sabr_support(""), "limited")
        # When the sentinel is set, capable versions flip to "supported".
        with mock.patch.object(_health, "SABR_NATIVE_MIN_VERSION", "2026.09.01"):
            self.assertEqual(_health.evaluate_sabr_support("2026.09.01"), "supported")
            self.assertEqual(_health.evaluate_sabr_support("2026.10.15"), "supported")
            self.assertEqual(_health.evaluate_sabr_support("2026.07.04"), "limited")

    def test_health_sabr_support_is_not_hardcoded(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        body = api.test_client().get("/health").get_json()
        self.assertIn(body.get("sabrSupport"), ("limited", "supported"))

    def test_summarize_ytdlp_formats_filters_and_shapes(self):
        info = {
            "id": "abc", "title": "T", "duration": 12,
            "formats": [
                {"format_id": "18", "ext": "mp4", "height": 360, "width": 640,
                 "vcodec": "avc1", "acodec": "mp4a", "filesize": 1000, "fps": 30},
                {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus",
                 "filesize_approx": 500},
                {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none"},
                {"format_id": None, "ext": "mp4"},
            ],
        }
        summary = ad.summarize_ytdlp_formats(info)
        ids = [f["format_id"] for f in summary["formats"]]
        self.assertEqual(ids, ["18", "251"], "mhtml + null-id + empty entries dropped")
        muxed = summary["formats"][0]
        self.assertTrue(muxed["has_video"] and muxed["has_audio"])
        audio = summary["formats"][1]
        self.assertFalse(audio["has_video"])
        self.assertTrue(audio["has_audio"])
        self.assertEqual(audio["filesize"], 500)
        self.assertEqual(summary["id"], "abc")

    def test_summarize_ytdlp_playlist_is_bounded_and_ui_safe(self):
        entries = [
            {
                "playlist_index": index,
                "id": f"video-{index}",
                "title": f"Video {index}",
                "channel": "Fixture channel",
                "duration": "12.9",
                "availability": "public",
            }
            for index in range(1, ad.PLAYLIST_PREVIEW_LIMIT + 2)
        ]
        summary = ad.summarize_ytdlp_playlist({
            "id": "PLfixture",
            "title": "Fixture playlist",
            "channel": "Fixture channel",
            "playlist_count": 275,
            "entries": entries,
        })

        self.assertEqual(summary["id"], "PLfixture")
        self.assertEqual(summary["total"], 275)
        self.assertTrue(summary["truncated"])
        self.assertEqual(summary["limit"], ad.PLAYLIST_PREVIEW_LIMIT)
        self.assertEqual(len(summary["items"]), ad.PLAYLIST_PREVIEW_LIMIT)
        self.assertEqual(summary["items"][0]["index"], 1)
        self.assertEqual(summary["items"][0]["duration"], 12)
        self.assertEqual(summary["items"][-1]["index"], ad.PLAYLIST_PREVIEW_LIMIT)

    def test_playlist_endpoint_requires_auth_youtube_playlist_and_returns_preview(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        playlist_url = "https://www.youtube.com/playlist?list=PLfixture"
        self.assertEqual(client.post("/playlist", json={"url": playlist_url}).status_code, 401)
        rejected = client.post(
            "/playlist",
            json={"url": "http://192.168.1.10/playlist?list=PLfixture"},
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.get_json()["code"], "private-host")

        preview = {
            "id": "PLfixture",
            "title": "Fixture",
            "total": 2,
            "truncated": False,
            "limit": 200,
            "items": [{"index": 1, "id": "one", "title": "One"}],
        }
        with mock.patch.object(manager, "preview_playlist", return_value=(preview, None)):
            response = client.post(
                "/playlist",
                json={"url": playlist_url},
                headers={"X-Auth-Token": token},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), preview)

    def test_playlist_preview_uses_flat_bounded_probe_and_shared_gate(self):
        captured = []

        class FakeProc:
            returncode = 0

            def communicate(self, timeout=None):
                self.timeout = timeout
                return json.dumps({
                    "id": "PLfixture",
                    "playlist_count": 1,
                    "entries": [{"id": "one", "title": "One"}],
                }), ""

        manager = ad.DownloadManager(FakeConfig(), FakeHistory())
        with mock.patch.object(ad, "spawn_ytdlp", side_effect=lambda args, **_kwargs: captured.append(list(args)) or FakeProc()), \
             mock.patch.object(ad, "probe_po_token_provider", return_value=None), \
             mock.patch.object(ad, "probe_javascript_runtime", return_value={}):
            result, err = manager.preview_playlist(
                "https://www.youtube.com/playlist?list=PLfixture",
                timeout=7,
            )

        self.assertIsNone(err)
        self.assertEqual(result["items"][0]["id"], "one")
        args = captured[0]
        self.assertIn("--flat-playlist", args)
        self.assertIn("--dump-single-json", args)
        self.assertIn("--skip-download", args)
        self.assertEqual(
            args[args.index("--playlist-end") + 1],
            str(ad.PLAYLIST_PREVIEW_LIMIT + 1),
        )
        self.assertNotIn("--yes-playlist", args)

        for _ in range(manager.FORMATS_PROBE_LIMIT):
            self.assertTrue(manager._formats_gate.acquire(blocking=False))
        try:
            result, err = manager.preview_playlist(
                "https://www.youtube.com/playlist?list=PLfixture"
            )
            self.assertIsNone(result)
            self.assertEqual(err, manager.PLAYLIST_BUSY_MESSAGE)
        finally:
            for _ in range(manager.FORMATS_PROBE_LIMIT):
                manager._formats_gate.release()

    def test_formats_endpoint_requires_auth_and_public_host(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        # no token
        self.assertEqual(client.post("/formats", json={"url": "https://youtube.com/watch?v=x"}).status_code, 401)
        # private-network target rejected before spawning yt-dlp
        resp = client.post("/formats", json={"url": "http://127.0.0.1/x"}, headers={"X-Auth-Token": token})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json().get("code"), "private-host")
        # missing url
        self.assertEqual(client.post("/formats", json={}, headers={"X-Auth-Token": token}).status_code, 400)

    def test_formats_endpoint_returns_summary(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        summary = {"id": "dQw4w9WgXcQ", "title": "T", "duration": 1,
                   "formats": [{"format_id": "18", "ext": "mp4", "has_video": True, "has_audio": True}]}
        with mock.patch.object(manager, 'list_formats', return_value=(summary, None)):
            api = ad.create_api(config, manager, FakeHistory())
            resp = api.test_client().post(
                "/formats", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers={"X-Auth-Token": token})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["formats"][0]["format_id"], "18")

    def test_formats_endpoint_surfaces_listing_error(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(manager, 'list_formats', return_value=(None, "Video unavailable")):
            api = ad.create_api(config, manager, FakeHistory())
            resp = api.test_client().post(
                "/formats", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers={"X-Auth-Token": token})
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.get_json().get("error"), "Video unavailable")

    def test_formats_probe_concurrency_is_bounded(self):
        # Each `yt-dlp -J` probe holds a waitress worker thread for up to
        # 60s; the semaphore keeps saturating /formats calls from starving
        # /health, /status and /download.
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        # Occupy every probe slot.
        for _ in range(manager.FORMATS_PROBE_LIMIT):
            self.assertTrue(manager._formats_gate.acquire(blocking=False))
        try:
            result, err = manager.list_formats("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertIsNone(result)
            self.assertEqual(err, manager.FORMATS_BUSY_MESSAGE)
            api = ad.create_api(config, manager, FakeHistory())
            resp = api.test_client().post(
                "/formats", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers={"X-Auth-Token": token})
            self.assertEqual(resp.status_code, 429)
            self.assertEqual(resp.get_json().get("code"), "formats-busy")
            self.assertTrue(resp.headers.get("Retry-After"))
        finally:
            for _ in range(manager.FORMATS_PROBE_LIMIT):
                manager._formats_gate.release()

    def test_shutdown_is_post_only(self):
        token = "a" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        # GET is no longer allowed (state-changing action must not be a safe method)
        self.assertEqual(client.get("/shutdown", headers={"X-Auth-Token": token}).status_code, 405)
        # POST still requires auth
        self.assertEqual(client.post("/shutdown").status_code, 401)
        # POST with auth returns a teardown status (202 when no werkzeug hook)
        self.assertIn(client.post("/shutdown", headers={"X-Auth-Token": token}).status_code, (200, 202))

    def test_config_response_is_allowlisted(self):
        token = "a" * 32
        config = FakeConfig({
            "ServerToken": token,
            "Proxy": "https://user:secret@example.invalid:8443",
            "NativeChromeExtensionIds": "private-extension-id",
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/config", headers={"X-Auth-Token": token})
        body = resp.get_json()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["downloadPath"], config.get("DownloadPath"))
        self.assertEqual(body["DownloadPath"], config.get("DownloadPath"))
        for private_key in ("ServerToken", "Proxy", "NativeChromeExtensionIds"):
            self.assertNotIn(private_key, body)

    def test_health_legacy_token_echo_is_origin_allowlisted(self):
        trusted_origin = "chrome-extension://trustedlegacyid"
        config = FakeConfig({
            "ServerToken": "a" * 32,
            "LegacyHealthTokenEcho": True,
            "LegacyHealthTokenOrigins": trusted_origin,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        null_origin = client.get("/health", headers={
            "Origin": "null",
            "X-MDL-Client": "MediaDL",
        })
        self.assertNotIn("Access-Control-Allow-Origin", null_origin.headers)
        self.assertNotIn("token", null_origin.get_json())

        arbitrary_origin = "chrome-extension://abcdefghijklmnop"
        arbitrary_resp = client.get("/health", headers={
            "Origin": arbitrary_origin,
            "X-MDL-Client": "MediaDL",
        })
        self.assertNotIn("Access-Control-Allow-Origin", arbitrary_resp.headers)
        self.assertNotIn("token", arbitrary_resp.get_json())

        trusted_resp = client.get("/health", headers={
            "Origin": trusted_origin,
            "X-MDL-Client": "MediaDL",
        })
        self.assertEqual(trusted_resp.headers.get("Access-Control-Allow-Origin"), trusted_origin)
        self.assertEqual(trusted_resp.get_json()["token"], "a" * 32)

        background_resp = client.get("/health", headers={"X-MDL-Client": "MediaDL"})
        self.assertNotIn("token", background_resp.get_json())

        native_resp = client.get("/health", headers={
            "X-MDL-Client": "MediaDL",
            "X-MDL-Token-Source": "native",
        })
        native_body = native_resp.get_json()
        self.assertEqual(native_body["tokenSource"], "native")
        self.assertNotIn("token", native_body)

    def test_health_legacy_echo_allows_configured_native_chrome_id(self):
        extension_origin = "chrome-extension://configuredchromeid"
        config = FakeConfig({
            "ServerToken": "c" * 32,
            "LegacyHealthTokenEcho": True,
            "NativeChromeExtensionIds": "configuredchromeid",
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/health", headers={
            "Origin": extension_origin,
            "X-MDL-Client": "MediaDL",
        })
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), extension_origin)
        self.assertEqual(resp.get_json()["token"], "c" * 32)

    def test_health_legacy_token_echo_can_be_disabled(self):
        token = "b" * 32
        extension_origin = "chrome-extension://trustedlegacyid"
        config = FakeConfig({
            "ServerToken": token,
            "LegacyHealthTokenEcho": False,
            "LegacyHealthTokenOrigins": extension_origin,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        background_resp = client.get("/health", headers={"X-MDL-Client": "MediaDL"})
        background_body = background_resp.get_json()
        self.assertEqual(background_body["status"], "ok")
        self.assertFalse(background_body["legacyTokenEcho"])
        self.assertTrue(background_body["nativeChannelRequired"])
        self.assertNotIn("token", background_body)

        extension_resp = client.get("/health", headers={
            "Origin": extension_origin,
            "X-MDL-Client": "MediaDL",
        })
        extension_body = extension_resp.get_json()
        self.assertEqual(extension_resp.headers.get("Access-Control-Allow-Origin"), extension_origin)
        self.assertFalse(extension_body["legacyTokenEcho"])
        self.assertTrue(extension_body["nativeChannelRequired"])
        self.assertNotIn("token", extension_body)

        native_resp = client.get("/health", headers={
            "X-MDL-Client": "MediaDL",
            "X-MDL-Token-Source": "native",
        })
        native_body = native_resp.get_json()
        self.assertEqual(native_body["status"], "ok")
        self.assertEqual(native_body["tokenSource"], "native")
        self.assertNotIn("token", native_body)

        authenticated_resp = client.get("/history?limit=1", headers={
            "X-Auth-Token": token,
            "X-MDL-Token-Source": "native",
        })
        self.assertEqual(authenticated_resp.status_code, 200)

    def test_auth_and_legacy_health_settings_are_read_after_config_restore(self):
        old_token = "d" * 32
        new_token = "e" * 32
        extension_origin = "chrome-extension://restoredconfigid"
        config = FakeConfig({
            "ServerToken": old_token,
            "LegacyHealthTokenEcho": False,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        self.assertEqual(
            client.get("/history?limit=1", headers={"X-Auth-Token": old_token}).status_code,
            200,
        )
        config.set("ServerToken", new_token)
        config.set("LegacyHealthTokenEcho", True)
        config.set("LegacyHealthTokenOrigins", extension_origin)

        self.assertEqual(
            client.get("/history?limit=1", headers={"X-Auth-Token": old_token}).status_code,
            401,
        )
        self.assertEqual(
            client.get("/history?limit=1", headers={"X-Auth-Token": new_token}).status_code,
            200,
        )
        restored_health = client.get("/health", headers={
            "Origin": extension_origin,
            "X-MDL-Client": "MediaDL",
        }).get_json()
        self.assertEqual(restored_health.get("token"), new_token)
        self.assertTrue(restored_health["legacyTokenEcho"])

        config.set("LegacyHealthTokenEcho", False)
        disabled_health = client.get("/health", headers={
            "Origin": extension_origin,
            "X-MDL-Client": "MediaDL",
        }).get_json()
        self.assertNotIn("token", disabled_health)

    def test_download_rejects_non_object_json_body(self):
        token = "c" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().post(
            "/download",
            json=["https://example.com/video"],
            headers={"X-Auth-Token": token},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["error"], "Missing download URL.")

    def test_queue_mutations_reject_non_object_json_bodies(self):
        token = "c" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        manager.pause_intake()
        dl_id, _ = manager.start_download(
            "https://www.youtube.com/watch?v=jsonBoundary",
        )
        api = ad.create_api(config, manager, FakeHistory())
        headers = {"X-Auth-Token": token}
        client = api.test_client()

        for endpoint in (
            f"/queue/{dl_id}/resume",
            f"/queue/{dl_id}/retry",
            f"/queue/{dl_id}/move",
        ):
            with self.subTest(endpoint=endpoint):
                resp = client.post(endpoint, json=["not", "an", "object"], headers=headers)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("JSON object", resp.get_json()["error"])

        with mock.patch.object(ad, "_folder_picker_service", object()):
            resp = client.post(
                "/pick-folder",
                json=["not", "an", "object"],
                headers=headers,
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "invalid-request-body")

    def test_download_request_body_allows_reviewed_extension_fields(self):
        body = {
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "audioOnly": False,
            "format": "mp4",
            "quality": "1080",
            "outputDir": str(Path(tempfile.gettempdir())),
            "title": "Fixture",
            "referer": "https://www.youtube.com/",
            "cookies": [],
            "section": {"start": "1:02.5", "end": "1:05"},
            "playlistItems": ["5", 1, 3, 3],
            "videoPassword": "one-link-secret",
        }
        validated, err, code = ad.validate_download_request_body(body)
        self.assertEqual(validated["section"], {"start": 62.5, "end": 65.0})
        self.assertEqual(validated["playlistItems"], [1, 3, 5])
        self.assertEqual(validated["videoPassword"], "one-link-secret")
        self.assertIsNone(err)
        self.assertIsNone(code)

    def test_download_request_body_allows_yt_dlp_native_clip_selectors(self):
        for section, expected in (
            (
                {"start": "*from-url", "end": "inf"},
                {"start": "*from-url", "end": "inf"},
            ),
            (
                {"start": "*-30", "end": "inf"},
                {"start": "*-30", "end": "inf"},
            ),
        ):
            with self.subTest(section=section):
                validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "section": section,
                })
                self.assertEqual(validated["section"], expected)
                self.assertIsNone(err)
                self.assertIsNone(code)

    def test_download_request_body_rejects_invalid_clip_ranges(self):
        invalid_sections = (
            {"start": "", "end": "1:00"},
            {"start": "1:00", "end": "0:59"},
            {"start": "0:00", "end": "25:00:00"},
            {"start": "0:00", "end": "1:00", "args": "--copy"},
            {"start": "*-0", "end": "inf"},
            {"start": "*-86400.1", "end": "inf"},
            {"start": "*from-url", "end": "0"},
            ["0:00", "1:00"],
        )
        for section in invalid_sections:
            with self.subTest(section=section):
                _validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "section": section,
                })
                self.assertEqual(code, "invalid-download-section")
                self.assertTrue(err)

    def test_download_request_body_rejects_invalid_playlist_items(self):
        for playlist_items in ([], "1-3", [0], [1, "--exec"], list(range(1, 202))):
            with self.subTest(playlist_items=playlist_items):
                _validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/playlist?list=PLfixture",
                    "playlistItems": playlist_items,
                })
                self.assertEqual(code, "invalid-playlist-items")
                self.assertTrue(err)

    def test_download_request_body_rejects_client_supplied_ytdlp_flags(self):
        hostile_args = ["--netrc-cmd", "calc.exe", *ad.YTDLP_FORBIDDEN_LINK_FLAGS]
        for field in ad.DOWNLOAD_REQUEST_FORBIDDEN_YTDLP_ARG_FIELDS:
            with self.subTest(field=field):
                _validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    field: hostile_args,
                })
                self.assertEqual(code, "unsupported-ytdlp-flags")
                self.assertIn("Client-supplied yt-dlp flags are not allowed", err)

    def test_download_request_body_rejects_unknown_fields(self):
        _validated, err, code = ad.validate_download_request_body({
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "writeInfoJson": True,
        })
        self.assertEqual(code, "unsupported-download-fields")
        self.assertIn("writeInfoJson", err)

    def test_download_request_body_rejects_non_string_format_and_quality(self):
        for field, value, expected_code in (
            ("format", ["mp4"], "invalid-download-format"),
            ("quality", {}, "invalid-download-quality"),
        ):
            with self.subTest(field=field):
                validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    field: value,
                })
                self.assertIsNone(validated)
                self.assertTrue(err)
                self.assertEqual(code, expected_code)

    def test_download_request_body_rejects_an_invalid_video_password(self):
        for value in (123, "x\x00y", "x" * 4097):
            with self.subTest(value=repr(value)):
                _validated, err, code = ad.validate_download_request_body({
                    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "videoPassword": value,
                })
                self.assertEqual(code, "invalid-video-password")
                self.assertTrue(err)

    def test_download_endpoint_rejects_non_string_format_and_quality_with_cors(self):
        token = "j" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        for field, value, expected_code in (
            ("format", ["mp4"], "invalid-download-format"),
            ("quality", {}, "invalid-download-quality"),
        ):
            with self.subTest(field=field):
                resp = client.post(
                    "/download",
                    json={
                        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        field: value,
                    },
                    headers={"X-Auth-Token": token},
                )
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["code"], expected_code)
                self.assertIn("POST", resp.headers["Access-Control-Allow-Methods"])
        self.assertEqual(manager.downloads, {})

    def test_download_endpoint_rejects_ytdlp_args_before_queueing(self):
        token = "h" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().post(
            "/download",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "ytDlpArgs": ["--netrc-cmd", "calc.exe"],
            },
            headers={"X-Auth-Token": token},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "unsupported-ytdlp-flags")
        self.assertEqual(manager.downloads, {})

    def test_download_endpoint_rejects_private_network_url_before_queueing(self):
        # SSRF hardening: v1.8.0 replaced the YouTube-only allowlist with a
        # private-network denylist, and the server — not the extension — must
        # enforce it. A token-holder pointing at an internal/LAN/metadata host
        # must be rejected before yt-dlp (and the cookie jar) is ever invoked.
        token = "n" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        for hostile, expected_code in (
            ("http://169.254.169.254/latest/meta-data/", "private-host"),
            ("http://192.168.1.1/admin", "private-host"),
            ("http://127.0.0.1:9999/", "private-host"),
            ("http://localhost:9751/download", "private-host"),
            ("http://nas/movie.mp4", "private-host"),
            ("http://printer.local/stream", "private-host"),
            ("https://[::1]/video", "private-host"),
            ("http://2130706433/", "private-host"),
            ("http://0x7f.0.0.1/", "non-public-host"),
            ("https://user:secret@example.com/watch?v=abc", "credentials-in-url"),
        ):
            resp = client.post(
                "/download",
                json={"url": hostile, "cookies": [{"name": "SID", "value": "secret"}]},
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(resp.status_code, 400, hostile)
            self.assertEqual(resp.get_json()["code"], expected_code, hostile)
        self.assertEqual(manager.downloads, {})

    def test_download_endpoint_accepts_any_public_media_host(self):
        # The whole point of v1.8.0: YouTube keeps working AND every other
        # public site yt-dlp supports reaches the queue.
        token = "y" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        ok_urls = (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
            "https://www.reddit.com/r/videos/comments/abc123/clip/",
            "https://v.redd.it/abc123",
            "https://x.com/someone/status/1234567890",
            "https://twitter.com/someone/status/1234567890",
            "https://www.tiktok.com/@someone/video/1234567890",
            "https://vimeo.com/123456789",
            "https://www.twitch.tv/someone/clip/SomeClip",
            "https://cdn.example.com/media/clip.mp4",
        )
        with mock.patch.object(manager, 'start_download', return_value=('dl_test', None)) as start:
            for ok_url in ok_urls:
                resp = client.post(
                    "/download",
                    json={"url": ok_url},
                    headers={"X-Auth-Token": token},
                )
                # Must get PAST the URL policy without launching a real yt-dlp
                # worker from the unit suite.
                body = resp.get_json() or {}
                self.assertNotIn(
                    body.get("code"),
                    set(ad.MEDIA_URL_BLOCK_MESSAGES),
                    ok_url,
                )
                self.assertEqual(resp.status_code, 200, ok_url)

        self.assertEqual(start.call_count, len(ok_urls))

    def test_download_endpoint_queue_full_response_includes_capacity_and_remediation(self):
        token = 'q' * 32
        config = FakeConfig({'ServerToken': token})
        manager = ad.DownloadManager(config, FakeHistory())
        manager.intake_paused = True
        for index in range(ad.MAX_QUEUED_TOTAL):
            dl = ad.Download(
                f'pending-{index}',
                f'https://www.youtube.com/watch?v={index:011d}',
                output_dir=config.get('DownloadPath'),
                queue_order=index + 1,
            )
            manager.downloads[dl.id] = dl
        api = ad.create_api(config, manager, FakeHistory())
        with mock.patch.object(ad, 'probe_javascript_runtime', return_value={
            'ytdlpNeedsRuntime': False,
            'supported': True,
            'ejsReady': True,
        }):
            resp = api.test_client().post(
                '/download',
                json={'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'},
                headers={'X-Auth-Token': token},
            )

        self.assertEqual(resp.status_code, 429)
        payload = resp.get_json()
        self.assertEqual(payload['code'], 'queue-full')
        self.assertEqual(payload['capacity']['total'], ad.MAX_QUEUED_TOTAL)
        self.assertEqual(payload['capacity']['available'], 0)
        self.assertIn('Cancel a pending item', payload['remediation'])

        failed = ad.Download(
            'failed-retry',
            'https://www.youtube.com/watch?v=failedRetry',
            output_dir=config.get('DownloadPath'),
        )
        failed.status = 'failed'
        failed.error_code = 'network-unreachable'
        failed.mark_terminal()
        manager.downloads[failed.id] = failed
        retry_resp = api.test_client().post(
            f'/queue/{failed.id}/retry',
            headers={'X-Auth-Token': token},
        )
        retry_payload = retry_resp.get_json()
        self.assertEqual(retry_resp.status_code, 429)
        self.assertEqual(retry_payload['code'], 'queue-full')
        self.assertEqual(retry_payload['capacity']['available'], 0)
        self.assertIn('Cancel a pending item', retry_payload['remediation'])

    def test_queue_api_controls_pause_reorder_and_fresh_auth_resume(self):
        token = 'r' * 32
        config = FakeConfig({'ServerToken': token})
        manager = ad.DownloadManager(config, FakeHistory())
        manager.pause_intake()
        first, _ = manager.start_download('https://www.youtube.com/watch?v=firstQueue1')
        second, _ = manager.start_download('https://www.youtube.com/watch?v=secondQueue')
        auth = ad.Download(
            'auth-recovery',
            'https://www.youtube.com/watch?v=authRecover',
            output_dir=config.get('DownloadPath'),
            requires_auth=True,
            queue_order=3,
        )
        auth.status = 'needs-auth'
        manager.downloads[auth.id] = auth
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        headers = {'X-Auth-Token': token}

        moved = client.post(f'/queue/{second}/move', json={'position': 0}, headers=headers)
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.get_json()['queue']['downloads'][0]['id'], second)

        missing = client.post(f'/queue/{auth.id}/resume', json={}, headers=headers)
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.get_json()['code'], 'fresh-auth-required')

        resumed = client.post(
            f'/queue/{auth.id}/resume',
            json={'cookies': [{
                'domain': '.youtube.com', 'name': 'SID', 'value': 'fresh-secret',
                'path': '/', 'secure': True,
            }]},
            headers=headers,
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(manager.downloads[auth.id].status, 'pending')
        queue_payload = client.get('/queue', headers=headers).get_json()
        self.assertTrue(queue_payload['capacity']['intakePaused'])
        self.assertNotIn('fresh-secret', json.dumps(queue_payload))
        self.assertIn(first, {item['id'] for item in queue_payload['downloads']})

    def test_history_limit_is_clamped(self):
        token = "d" * 32
        history = FakeHistory()
        history.entries = [{"id": str(i), "url": "https://example.com", "title": str(i)} for i in range(3)]
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, history)
        api = ad.create_api(config, manager, history)

        resp = api.test_client().get("/history?limit=-5", headers={"X-Auth-Token": token})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["count"], 1)
        self.assertEqual(resp.get_json()["filteredTotal"], 3)
        self.assertEqual(resp.get_json()["total"], 3)

    def test_history_query_filters_sorts_and_pages_retained_rows(self):
        entries = ad.sanitize_history_entries([
            {
                "id": "1", "title": "Alpha lecture", "filename": "alpha.mp4",
                "format": "mp4", "quality": "1080", "date": "2026-07-27",
            },
            {
                "id": "2", "title": "Beta lecture", "filename": "beta.m4a",
                "format": "m4a", "quality": "best", "date": "2026-07-28",
            },
            {
                "id": "3", "title": "Beta follow-up", "filename": "follow-up.mp4",
                "format": "mp4", "quality": "720", "date": "2026-07-29",
            },
        ])

        result = ad.query_history_entries(
            entries,
            query="beta",
            status="complete",
            fmt="mp4",
            date_from="2026-07-28",
            date_to="2026-07-30",
            sort="oldest",
            offset=0,
            limit=1,
        )

        self.assertEqual([item["id"] for item in result["history"]], ["3"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["filteredTotal"], 1)
        self.assertFalse(result["hasMore"])
        self.assertEqual(entries[0]["status"], "complete")

    def test_history_lookup_includes_subscription_archive_and_searches_url(self):
        url = "https://www.youtube.com/watch?v=archive-only"
        archive = {
            "sha256:archive-only": {
                "url": url,
                "title": "Scheduled archive item",
                "subscriptionId": "sub-1",
                "status": "complete",
                "completedAt": 1_754_000_000,
            },
        }

        result = ad.query_history_entries(
            [], query=url, archive_entries=archive,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["filteredTotal"], 1)
        self.assertEqual(result["history"][0]["source"], "subscription")
        self.assertEqual(result["history"][0]["url"], url)
        lookup = ad.lookup_history_url([], url, archive_entries=archive)
        self.assertEqual(lookup["count"], 1)
        self.assertTrue(lookup["found"])

    def test_history_archive_row_is_deduplicated_when_download_history_has_url(self):
        url = "https://example.com/watch?v=same"
        entries = ad.sanitize_history_entries([{
            "id": "download-1", "url": url, "title": "Downloaded copy",
        }])
        result = ad.query_history_entries(
            entries,
            query=url,
            archive_entries={
                "archive-key": {
                    "url": url,
                    "title": "Scheduled copy",
                    "status": "complete",
                },
            },
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual([row["id"] for row in result["history"]], ["download-1"])

    def test_history_preserves_terminal_diagnostics_and_filters_statuses(self):
        entries = ad.sanitize_history_entries([
            {
                "id": "complete", "title": "Finished", "status": "complete",
                "date": "2026-08-01",
            },
            {
                "id": "failed", "title": "Private video", "status": "failed",
                "errorCode": "sign-in-required", "error": "Sign in first.",
                "date": "2026-08-02",
            },
            {
                "id": "cancelled", "title": "Stopped", "status": "cancelled",
                "error_code": "cancelled-by-user", "errorText": "Cancelled by user.",
                "date": "2026-08-03",
            },
            {
                "id": "skipped", "title": "No media", "status": "skipped",
                "date": "2026-08-04",
            },
        ])

        self.assertEqual(entries[1]["errorCode"], "sign-in-required")
        self.assertEqual(entries[1]["error"], "Sign in first.")
        self.assertEqual(entries[2]["errorCode"], "cancelled-by-user")
        self.assertEqual(entries[2]["error"], "Cancelled by user.")

        for status in ("complete", "failed", "cancelled", "skipped"):
            with self.subTest(status=status):
                result = ad.query_history_entries(entries, status=status)
                self.assertEqual(result["filteredTotal"], 1)
                self.assertEqual(result["history"][0]["status"], status)

    def test_history_route_exposes_filtered_page_metadata(self):
        token = "d" * 32
        history = FakeHistory()
        history.entries = [
            {
                "id": str(index),
                "title": f"Lecture {index}",
                "filename": f"lecture-{index}.mp4",
                "format": "mp4" if index % 2 else "m4a",
                "date": f"2026-07-{20 + index:02d}",
            }
            for index in range(1, 6)
        ]
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, history)
        client = ad.create_api(config, manager, history).test_client()

        response = client.get(
            "/history?q=lecture&format=mp4&sort=oldest&offset=1&limit=1"
            "&dateFrom=2026-07-20&dateTo=2026-07-29",
            headers={"X-Auth-Token": token},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual([item["id"] for item in body["history"]], ["3"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 5)
        self.assertEqual(body["filteredTotal"], 3)
        self.assertTrue(body["hasMore"])
        self.assertEqual(body["sort"], "oldest")

    def test_history_route_reports_exact_url_lookup_from_subscription_archive(self):
        token = "e" * 32
        url = "https://www.youtube.com/watch?v=scheduled"
        history = FakeHistory()
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, history)
        subscriptions = types.SimpleNamespace(archive_entries=lambda: {
            "archive-key": {
                "url": url,
                "title": "Scheduled item",
                "status": "queued",
                "updatedAt": 1_754_000_000,
            },
        })
        client = ad.create_api(
            config, manager, history, subscriptions=subscriptions,
        ).test_client()

        response = client.get(
            "/history?url=" + url,
            headers={"X-Auth-Token": token},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["lookup"]["found"])
        self.assertEqual(body["lookup"]["count"], 1)
        self.assertEqual(body["history"][0]["source"], "subscription")

    def test_history_rejects_malformed_limit(self):
        token = "d" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())

        resp = api.test_client().get(
            "/history?limit=many",
            headers={"X-Auth-Token": token},
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "invalid-limit")

        bad_date = api.test_client().get(
            "/history?dateFrom=07-29-2026",
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(bad_date.status_code, 400)
        self.assertEqual(bad_date.get_json()["code"], "invalid-date")

    def test_cancel_finished_download_returns_conflict_not_not_found(self):
        token = "b" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        dl = ad.Download("done", "https://example.com/done")
        dl.status = "complete"
        manager.downloads[dl.id] = dl
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().delete(f"/cancel/{dl.id}", headers={"X-Auth-Token": token})

        self.assertEqual(resp.status_code, 409)
        self.assertIn("already finished", resp.get_json()["error"])

    def test_dns_rebinding_attack_is_rejected_before_handler(self):
        """Verify Host-header validation blocks DNS rebinding to attacker-controlled domains."""
        token = "e" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        # Simulate a DNS-rebinding attack: the browser resolved attacker.com
        # to 127.0.0.1 after the page loaded, but it still sends the attacker
        # hostname in the Host header. Legitimate local clients always send
        # 127.0.0.1 / localhost / ::1.
        for bad_host in ("attacker.com", "attacker.com:9751", "example.org:80"):
            with self.subTest(host=bad_host):
                resp = client.get(
                    "/health",
                    headers={"Host": bad_host, "X-MDL-Client": "MediaDL"},
                )
                self.assertEqual(resp.status_code, 421, f"Expected 421 Misdirected Request for Host={bad_host}")
                self.assertIn("Invalid Host", resp.get_json().get("error", ""))

        for good_host in ("127.0.0.1:9751", "localhost:9751", "[::1]:9751"):
            with self.subTest(host=good_host):
                resp = client.get(
                    "/health",
                    headers={"Host": good_host, "X-MDL-Client": "MediaDL"},
                )
                self.assertEqual(resp.status_code, 200, f"Expected 200 for Host={good_host}")

    def test_missing_source_dependency_message_requires_explicit_virtualenv_setup(self):
        error = ModuleNotFoundError("missing PySide6", name="PySide6")
        message = ad.source_dependency_error(error)
        self.assertIn("will not install packages during import", message)
        self.assertIn("py -3.13 -m venv .venv", message)
        self.assertIn("--require-virtualenv -r", message)
        self.assertIn(str(ad.REQUIREMENTS_PATH), message)

    def test_source_import_has_no_package_install_path(self):
        script = r'''
import subprocess

calls = []
def refuse_install(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError("package installation attempted during import")

subprocess.check_call = refuse_install
import astra_downloader.astra_downloader  # noqa: F401
assert calls == []
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_boundary_module_imports_do_not_load_gui_server_or_legacy_root(self):
        script = r'''
import importlib
import sys

for name in (
    "astra_downloader.config",
    "astra_downloader.download",
    "astra_downloader.health",
):
    module = importlib.import_module(name)
    assert module.__all__, f"{name} must expose its compatibility contract"

config = importlib.import_module("astra_downloader.config")
download = importlib.import_module("astra_downloader.download")
health = importlib.import_module("astra_downloader.health")
assert config.normalize_url("https://example.com/video") == (
    "https://example.com/video", None
)
assert config.validate_download_request_body({"url": "https://example.com"})[1] is None
assert config.sanitize_config({"ServerPort": 999999})["ServerPort"] == 65535
assert config.DEFAULT_CONFIG["JavaScriptRuntime"] == "auto"
model = download.Download("owned", "https://example.com", clock=lambda: 123.0)
assert model.start_time == 123.0
model.status = "complete"
model.mark_terminal()
assert model.finished_time == 123.0
assert download.classify_download_failure("connection timed out") == "network-unreachable"
assert health.is_youtube_url("https://youtu.be/abcdefghijk")
assert health.parse_ffmpeg_major("8.1.1") == 8
assert health.ytdlp_needs_external_runtime("2026.04.01")
runtime = health.evaluate_javascript_runtime(
    "deno",
    "/tools/deno",
    "test",
    runner=lambda args, timeout: "deno 2.8.1" if "--version" in args else "READY",
    marker="READY",
)
assert runtime["supported"] and runtime["ejsReady"]
assert download.build_subprocess_env(
    "/missing/deno", environ={"PATH": "safe", "SECRET": "drop"}
) == {"PATH": "safe"}

for forbidden in (
    "astra_downloader.astra_downloader",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "flask",
):
    assert forbidden not in sys.modules, f"boundary import loaded {forbidden}"
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_boundary_modules_preserve_legacy_symbol_identity_on_access(self):
        import config
        import download
        import gui
        import health
        import routes

        self.assertIs(config.Config, ad.Config)
        self.assertIs(config.DEFAULT_CONFIG, ad.DEFAULT_CONFIG)
        self.assertIs(config.sanitize_config, ad.sanitize_config)
        self.assertIs(config.clean_text, ad.clean_text)
        self.assertIs(config.clamp_int, ad.clamp_int)
        self.assertIs(config.validate_download_request_body, ad.validate_download_request_body)
        self.assertIs(config.allowed_output_roots, ad.allowed_output_roots)
        self.assertIs(config.normalize_output_dir, ad.normalize_output_dir)
        self.assertIs(config.atomic_write_json, ad.atomic_write_json)
        self.assertIs(config.load_json_file, ad.load_json_file)
        self.assertIs(config.sanitize_history_entries, ad.sanitize_history_entries)
        self.assertIs(download.DownloadManager, download.DownloadManagerCore)
        self.assertTrue(issubclass(ad.DownloadManager, download.DownloadManagerCore))
        self.assertIs(download.Download, ad.Download)
        self.assertIs(download.DownloadQueueStore, ad.DownloadQueueStore)
        self.assertIs(download.build_video_format_args, ad.build_video_format_args)
        self.assertIs(download.classify_download_failure, ad.classify_download_failure)
        self.assertIs(download.DOWNLOAD_ACTIVE_STATES, ad.DOWNLOAD_ACTIVE_STATES)
        self.assertIs(health.get_ytdlp_version, ad.get_ytdlp_version)
        self.assertIs(health.is_youtube_url, ad.is_youtube_url)
        self.assertIs(health.parse_ffmpeg_major, ad.parse_ffmpeg_major)
        self.assertIs(health.build_youtube_extractor_args, ad.build_youtube_extractor_args)
        self.assertIs(health.build_javascript_runtime_args, ad.build_javascript_runtime_args)
        self.assertEqual(routes.create_api.__module__, routes.__name__)
        self.assertIsNot(routes.create_api, ad.create_api)
        self.assertIs(gui.MainWindow, gui.MainWindowCore)
        self.assertTrue(issubclass(ad.MainWindow, gui.MainWindowCore))
        self.assertIs(gui.make_label, ad.make_label)
        self.assertIs(gui.make_empty_state, ad.make_empty_state)
        self.assertIs(gui.human_status, ad.human_status)
        self.assertTrue(issubclass(ad.ReadinessProbe, gui.ReadinessProbe))
        self.assertTrue(issubclass(ad.FolderPickerService, gui.FolderPickerService))
        self.assertIs(gui.SetupWorker, gui.SetupWorkerCore)
        self.assertTrue(issubclass(ad.SetupWorker, gui.SetupWorkerCore))

    def test_pending_queue_states_share_the_warning_tone(self):
        # Every not-yet-running queue state must read as the same amber tone in
        # the Downloads list; 'pending' previously fell through to neutral and
        # showed a grey dot beside its amber 'paused'/'needs-auth' siblings.
        for status in sorted(ad.DOWNLOAD_PENDING_STATES):
            self.assertEqual(
                ad.download_status_tone(status), "warning",
                f"pending-set status {status!r} must use the warning tone",
            )
        self.assertEqual(ad.download_status_tone("queued"), "warning")
        self.assertEqual(ad.download_status_tone("complete"), "success")
        self.assertEqual(ad.download_status_tone("failed"), "danger")

    def test_argv_credential_visibility_is_a_stated_accepted_property(self):
        # build_site_login_credential_args emits --username/--password on the
        # yt-dlp command line, visible in Win32_Process.CommandLine to any
        # same-user process. That is a deliberate decision (netrc is refused,
        # yt-dlp has no stdin channel) — but a decision is only accepted if it
        # is stated. If the mechanism ever changes, move the SECURITY.md entry
        # with it.
        security = (Path(ad.__file__).resolve().parent.parent / "SECURITY.md").read_text(
            encoding="utf-8")
        self.assertIn("Stored site credentials travel to yt-dlp on its command line",
                      security)
        self.assertIn("Win32_Process.CommandLine", security)
        import download as _download_module
        args = _download_module.build_site_login_credential_args(
            {"username": "user@example.com", "password": "hunter2"})
        self.assertIn("--username", args)
        self.assertIn("--password", args)

    def test_every_doc_referenced_from_source_exists(self):
        # Two accepted-risk rationales cited HARDENING.md, which never
        # existed — the code was right and the justification unrecoverable.
        # Any .md a source comment points a reader at must resolve.
        module_dir = Path(ad.__file__).resolve().parent
        repo_root = module_dir.parent
        referenced = set()
        for source_file in module_dir.glob("*.py"):
            if source_file.name.startswith("test_"):
                continue
            text = source_file.read_text(encoding="utf-8")
            referenced.update(re.findall(r"\b[\w./-]*[\w-]+\.md\b", text))
        self.assertTrue(referenced, "the scan must find doc references")
        for name in sorted(referenced):
            candidates = (
                repo_root / name,
                repo_root / "docs" / Path(name).name,
                module_dir / name,
            )
            self.assertTrue(
                any(candidate.is_file() for candidate in candidates),
                f"source references {name} but no such document exists",
            )

    def test_every_status_tone_and_state_literal_has_a_stylesheet_rule(self):
        # A status label used to set a `state` property that no stylesheet
        # rule ever matched, so "queue is full" rendered in the same grey as a
        # hint. Scan the GUI sources for the literal tone/state values they
        # set and require a matching rule, so the next unmatched value fails
        # here instead of rendering invisibly.
        module_dir = Path(ad.__file__).resolve().parent
        tone_values = set()
        state_values = set()
        for name in ("gui.py", "gui_support.py", "gui_download_page.py",
                     "gui_history_page.py", "gui_site_logins_page.py",
                     "gui_subscriptions_page.py", "gui_settings_page.py",
                     "gui_extension_page.py"):
            tree = ast.parse((module_dir / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if (isinstance(func, ast.Attribute) and func.attr == "setProperty"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    prop, value = node.args[0].value, node.args[1].value
                    if prop == "tone" and value:
                        tone_values.add(value)
                    elif prop == "state" and value:
                        state_values.add(value)
                elif (isinstance(func, ast.Name) and func.id == "set_status_tone"
                        and len(node.args) >= 2
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)):
                    raw = node.args[1].value or "neutral"
                    tone_values.add({"error": "danger"}.get(raw, raw))
        self.assertTrue(tone_values, "the scan must find tone literals")
        for value in sorted(tone_values):
            self.assertIn(
                f'[tone="{value}"]', ad.STYLESHEET,
                f'tone "{value}" is set somewhere but no stylesheet rule matches it',
            )
        for value in sorted(state_values):
            self.assertIn(
                f'[state="{value}"]', ad.STYLESHEET,
                f'state "{value}" is set somewhere but no stylesheet rule matches it',
            )

    def test_status_change_raises_a_screen_reader_alert(self):
        # WCAG 2.2 SC 4.1.3: setText() alone delivers nothing to assistive
        # technology, so assert against the real Qt call rather than a stand-in
        # helper that could drift from what ships.
        import gui_support as gs
        if _get_qapp_or_skip(self) is None:
            return

        label = gs.make_label("ready", "fieldHint", status=True)
        self.addCleanup(label.deleteLater)
        with mock.patch.object(gs.QAccessible, "updateAccessibility") as posted:
            label.setText("Download rejected.")
        self.assertEqual(posted.call_count, 1)
        event = posted.call_args.args[0]
        self.assertIs(event.object(), label)
        self.assertEqual(event.type(), gs.QAccessible.Event.Alert)

    def test_repeating_the_same_status_says_nothing(self):
        # _update_output_template_preview runs on every keystroke of the output
        # template. Announcing an unchanged message would interrupt a screen
        # reader mid-word 40 times while someone types.
        import gui_support as gs
        if _get_qapp_or_skip(self) is None:
            return

        label = gs.make_label("", "fieldHint", status=True)
        self.addCleanup(label.deleteLater)
        label.setText("Preview unavailable until the template is valid.")
        with mock.patch.object(gs.QAccessible, "updateAccessibility") as posted:
            for _ in range(40):
                label.setText("Preview unavailable until the template is valid.")
        self.assertEqual(posted.call_count, 0)

    def test_every_status_label_announces_its_own_writes(self):
        # Routing the Alert through set_status_tone left every call site that
        # writes the label directly silent, and there were dozens of them.
        gs = gui_module_for_tests()
        import gui_support

        module_dir = Path(ad.__file__).resolve().parent
        assignments = []
        for source in sorted(module_dir.glob("gui_*_page.py")):
            for line in source.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.startswith("self.") or "make_label(" not in stripped:
                    continue
                name = stripped.split("=", 1)[0].strip()
                if name.endswith("_status") or name.endswith("status"):
                    assignments.append((source.name, stripped))

        self.assertTrue(assignments, "the scan must find the status labels")
        missing = [
            f"{name}: {line}" for name, line in assignments
            if "status=True" not in line
        ]
        self.assertEqual(
            missing, [],
            "a status label must be built with status=True so its writes announce",
        )

    def test_announcing_a_widget_double_is_a_no_op(self):
        # Several harnesses drive lightweight doubles through the same setters.
        import gui_support as gs

        class FakeLabel:
            def setProperty(self, name, value):
                pass

        self.assertFalse(gs.announce_status(FakeLabel()))

    @staticmethod
    def _tool_button_labels():
        """Every literal a button or rail icon is built from."""
        module_dir = Path(ad.__file__).resolve().parent
        labels = set()
        for source in sorted(module_dir.glob("gui*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name not in ("_make_tool_button", "make_line_icon", "set_line_icon"):
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        labels.add(arg.value)
                        break
                    if isinstance(arg, ast.Call) and getattr(arg.func, "id", None) == "tr":
                        if arg.args and isinstance(arg.args[0], ast.Constant):
                            labels.add(arg.args[0].value)
                        break
        return labels

    def test_every_named_button_resolves_to_a_deliberate_glyph(self):
        # 15 of 48 tool buttons used to fall through to one three-lines-and-dots
        # default, which put Remove and Undo remove on the same picture.
        gs = gui_module_for_tests()
        import gui_support

        # Property values, not icon names — _make_tool_button also takes a
        # style class and a selection mode as string literals.
        not_icon_names = {"ghost", "select", "primary", "danger", "quiet"}
        labels = {
            label for label in self._tool_button_labels()
            if label and label not in not_icon_names
        }
        self.assertGreaterEqual(len(labels), 40, "the scan must find the button labels")

        fell_through = sorted(
            label for label in labels
            if gui_support.line_icon_glyph(label) == "fallback"
        )
        self.assertEqual(
            fell_through, [],
            f"named buttons must not share the unnamed-icon default: {fell_through}",
        )
        self.assertEqual(gui_support.line_icon_glyph("some unnamed control"), "fallback",
                         "the fallback must still exist for a genuinely unnamed icon")

    def test_a_destructive_action_and_its_undo_do_not_share_a_glyph(self):
        import gui_support

        for destructive, undo in (
            ("Remove", "Undo remove"),
            ("Import settings", "Undo import"),
            ("Restore defaults", "Undo defaults"),
            ("Clear history", "Undo clear"),
        ):
            with self.subTest(action=destructive):
                self.assertNotEqual(
                    gui_support.line_icon_glyph(destructive),
                    gui_support.line_icon_glyph(undo),
                )

    def test_the_nav_entries_each_draw_something_different(self):
        # Subscriptions and Settings used to collide on the fallback.
        gs = gui_module_for_tests()
        import gui_support
        if _get_qapp_or_skip(self) is None:
            return

        rendered = {}
        for name in ("Download", "History", "Sign-ins", "Subscriptions",
                     "Browser extension", "Settings"):
            icon = gui_support.make_line_icon(name, dpr=1.0)
            image = icon.pixmap(18, 18).toImage()
            pixels = bytes(image.constBits())[:image.sizeInBytes()]
            self.assertNotIn(
                pixels, rendered.values(),
                f"{name} draws the same glyph as "
                f"{next((k for k, v in rendered.items() if v == pixels), '?')}",
            )
            rendered[name] = pixels

    def test_set_status_tone_maps_error_onto_the_danger_convention(self):
        gs = gui_module_for_tests()
        applied = []

        class FakeLabel:
            def setProperty(self, name, value):
                applied.append((name, value))

            def style(self):
                class _S:
                    def unpolish(self, _w):
                        pass

                    def polish(self, _w):
                        pass
                return _S()

            def update(self):
                pass

        label = FakeLabel()
        gs.set_status_tone(label, "error")
        gs.set_status_tone(label, "success")
        gs.set_status_tone(label, "")
        self.assertEqual(applied, [
            ("tone", "danger"), ("tone", "success"), ("tone", "neutral"),
        ])

    def test_gui_boundary_imports_pyqt_without_creating_application(self):
        script = r'''
import importlib
import sys

gui = importlib.import_module("astra_downloader.gui")
from PySide6.QtWidgets import QApplication
assert QApplication.instance() is None
assert gui.human_status("needs-auth") == "Needs sign-in"
assert gui.format_duration(3660) == "1h 1m"
assert "astra_downloader.astra_downloader" not in sys.modules
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gui_pages_are_importable_mixins_without_the_composition_root(self):
        script = r'''
import importlib
import sys

gui = importlib.import_module("astra_downloader.gui")
pages = {
    "download": ("DownloadPageMixin", "_build_download"),
    "history": ("HistoryPageMixin", "_build_history"),
    "site_logins": ("SiteLoginsPageMixin", "_build_site_logins"),
    "subscriptions": ("SubscriptionsPageMixin", "_build_subscriptions"),
    "extension": ("ExtensionPageMixin", "_build_extension"),
    "settings": ("SettingsPageMixin", "_build_settings"),
}
for page, (mixin_name, builder_name) in pages.items():
    module = importlib.import_module(f"astra_downloader.gui_{page}_page")
    mixin = getattr(module, mixin_name)
    assert callable(getattr(mixin, builder_name))
    assert issubclass(gui.MainWindowCore, mixin)
assert "astra_downloader.astra_downloader" not in sys.modules
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_routes_boundary_owns_handlers_without_loading_legacy_root(self):
        script = r'''
import importlib
import sys

routes = importlib.import_module("astra_downloader.routes")
assert routes.create_api.__module__ == "astra_downloader.routes"
assert "astra_downloader.astra_downloader" not in sys.modules
try:
    routes.create_api(None, None, None, dependencies={})
except ValueError as error:
    assert "Missing API dependencies" in str(error)
else:
    raise AssertionError("missing route dependencies were accepted")
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_health_version_probe_uses_injected_cache_dependencies(self):
        import health

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tool.exe"
            executable.touch()
            calls = []
            current_time = [100.0]

            def run(args):
                calls.append(args)
                return "tool 1.2.3"

            probe = health.ExecutableVersionProbe(
                path=executable,
                args=("--version",),
                parser=lambda output: output.rsplit(" ", 1)[-1],
                runner=run,
                clock=lambda: current_time[0],
                ttl_seconds=60,
            )
            self.assertEqual(probe.get(), "1.2.3")
            current_time[0] += 30
            self.assertEqual(probe.get(), "1.2.3")
            self.assertEqual(len(calls), 1)
            self.assertEqual(probe.get(force=True), "1.2.3")
            self.assertEqual(len(calls), 2)

    def test_health_version_probe_coalesces_concurrent_runner_calls(self):
        import health

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tool.exe"
            executable.touch()
            first_started = threading.Event()
            release_first = threading.Event()
            second_finished = threading.Event()
            call_lock = threading.Lock()
            call_count = 0
            results = []

            def run(_args):
                nonlocal call_count
                with call_lock:
                    call_count += 1
                    call_number = call_count
                if call_number == 1:
                    first_started.set()
                    release_first.wait(timeout=2)
                return "tool 1.2.3"

            probe = health.ExecutableVersionProbe(
                path=executable,
                args=("--version",),
                parser=lambda output: output.rsplit(" ", 1)[-1],
                runner=run,
                clock=lambda: 100.0,
                ttl_seconds=60,
            )
            first = threading.Thread(
                target=lambda: results.append(probe.get()), daemon=True
            )
            second = threading.Thread(
                target=lambda: (results.append(probe.get()), second_finished.set()),
                daemon=True,
            )
            first.start()
            self.assertTrue(first_started.wait(timeout=1))
            second.start()
            self.assertFalse(
                second_finished.wait(timeout=0.1),
                "a concurrent cache miss must wait on the in-flight probe",
            )
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(call_count, 1)
            self.assertEqual(results, ["1.2.3", "1.2.3"])

    def test_health_version_probe_caches_negative_results_for_the_ttl(self):
        import health

        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "tool.exe"
            executable.touch()
            calls = []
            current_time = [100.0]
            probe = health.ExecutableVersionProbe(
                path=executable,
                args=("--version",),
                parser=lambda _output: None,
                runner=lambda args: calls.append(args) or "",
                clock=lambda: current_time[0],
                ttl_seconds=60,
            )

            self.assertIsNone(probe.get())
            current_time[0] += 30
            self.assertIsNone(probe.get())
            self.assertEqual(len(calls), 1)
            current_time[0] += 31
            self.assertIsNone(probe.get())
            self.assertEqual(len(calls), 2)

    def test_ffmpeg_capability_probe_uses_injected_floor_and_cache(self):
        import health

        versions = iter(["6.1.1", "8.1.1"])
        probe = health.FfmpegCapabilitiesProbe(
            version_getter=lambda: next(versions),
            clock=lambda: 100.0,
            minimum_major=7,
            ttl_seconds=60,
        )
        first = probe.check()
        self.assertFalse(first["current"])
        first["current"] = True
        self.assertFalse(probe.check()["current"], "cached payload must be defensive")
        self.assertTrue(probe.check(force=True)["current"])

    def test_ffmpeg_capability_probe_does_not_hold_cache_lock_during_version_getter(self):
        import health

        first_started = threading.Event()
        release_first = threading.Event()
        second_finished = threading.Event()
        call_lock = threading.Lock()
        call_count = 0

        def version_getter():
            nonlocal call_count
            with call_lock:
                call_count += 1
                call_number = call_count
            if call_number == 1:
                first_started.set()
                release_first.wait(timeout=2)
            return "8.1.2"

        probe = health.FfmpegCapabilitiesProbe(
            version_getter=version_getter,
            clock=lambda: 100.0,
            minimum_major=8,
            minimum_version="8.1.2",
            ttl_seconds=60,
        )
        first = threading.Thread(target=probe.check, daemon=True)
        second = threading.Thread(
            target=lambda: (probe.check(), second_finished.set()),
            daemon=True,
        )
        first.start()
        self.assertTrue(first_started.wait(timeout=1))
        second.start()
        self.assertTrue(
            second_finished.wait(timeout=1),
            "a second ffmpeg capability check must not wait on version I/O",
        )
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertGreaterEqual(call_count, 2)

    def test_ffmpeg_capability_probe_enforces_exact_semver_floor(self):
        import health

        def probe_for(version):
            return health.FfmpegCapabilitiesProbe(
                version_getter=lambda: version,
                clock=lambda: 100.0,
                minimum_major=8,
                minimum_version="8.1.2",
                ttl_seconds=60,
            ).check()

        # Below the exact floor (RV60 OOB / MagicYUV RCE range) is flagged even
        # though the major (8) alone would pass a major-only check.
        below = probe_for("8.0.1-full_build-www.gyan.dev")
        self.assertFalse(below["current"])
        self.assertIn("8.1.2", below["message"])
        # An older major is likewise flagged.
        self.assertFalse(probe_for("7.1.1")["current"])
        # At or above the floor passes, build suffix ignored.
        self.assertTrue(probe_for("8.1.2-full_build")["current"])
        self.assertTrue(probe_for("9.0")["current"])
        # BtbN n-prefixed tagged builds compare like their bare version —
        # n8.0.1 must be flagged, n8.1.2 must pass (previously the n prefix
        # silently routed them to the never-flagged snapshot path).
        self.assertFalse(probe_for("n8.0.1-9-g1234567")["current"])
        self.assertTrue(probe_for("n8.1.2")["current"])
        # Master/snapshot builds carry no numeric version and remain unknown
        # when no dated snapshot floor is configured.
        snapshot = probe_for("N-119847-g1a2b3c4d-win64-gpl")
        self.assertIsNone(snapshot["current"])
        self.assertIsNone(snapshot["majorVersion"])

    def test_ffmpeg_snapshot_build_date_is_parsed_and_compared(self):
        import health

        self.assertEqual(
            health.parse_ffmpeg_snapshot_date(
                'N-123918-gf7ca6f7481-20260411'
            ),
            '2026-04-11',
        )
        self.assertIsNone(health.parse_ffmpeg_snapshot_date('N-123918-gabc'))

        def probe_for(version):
            return health.FfmpegCapabilitiesProbe(
                version_getter=lambda: version,
                clock=lambda: 100.0,
                minimum_snapshot_date='2026-06-17',
            ).check()

        old = probe_for('N-123918-gabc-20260411')
        self.assertFalse(old['current'])
        self.assertEqual(old['comparison'], 'snapshot-date')
        self.assertIn('2026-04-11', old['message'])
        fresh = probe_for('N-124000-gabc-20260618')
        self.assertTrue(fresh['current'])
        self.assertEqual(fresh['buildDate'], '2026-06-18')

    def test_ffmpeg_probe_is_configured_with_the_security_floor(self):
        self.assertEqual(ad._FFMPEG_MIN_VERSION, "8.1.2")
        self.assertEqual(ad._FFMPEG_MIN_SNAPSHOT_DATE, "2026-06-17")
        self.assertGreaterEqual(ad._FFMPEG_MIN_MAJOR, 8)

    def test_routes_module_owns_injected_wsgi_backend_selection_and_teardown(self):
        import routes

        calls = []

        class FakeServer:
            def run(self):
                calls.append("run")

            def close(self):
                calls.append("close")

        def make_waitress(api, **kwargs):
            calls.append((api, kwargs))
            return FakeServer()

        adapter = routes._build_wsgi_server(9751, "api", waitress_factory=make_waitress)
        self.assertIs(routes._ServerAdapter, ad._ServerAdapter)
        self.assertIs(routes._build_wsgi_server, ad._build_wsgi_server)
        self.assertEqual(adapter.backend, "waitress")
        self.assertEqual(calls[0][1], {
            "host": "127.0.0.1",
            "port": 9751,
            "threads": 8,
            "ident": "Astra Downloader",
        })
        adapter.run()
        adapter.stop()
        self.assertEqual(calls[-2:], ["run", "close"])

    def test_routes_module_normalizes_werkzeug_bind_abort_without_opening_socket(self):
        import routes

        def abort_bind(*_args, **_kwargs):
            raise SystemExit(1)

        with self.assertRaisesRegex(OSError, "Werkzeug aborted while binding port 9761"):
            routes._build_wsgi_server(
                9761,
                "api",
                waitress_factory=False,
                werkzeug_factory=abort_bind,
            )

    def test_importing_companion_modules_never_spawns_a_process(self):
        script = r'''
import importlib
import subprocess

def forbidden(*args, **kwargs):
    raise AssertionError(f"process launch during import: {args!r}")

subprocess.Popen = forbidden
subprocess.call = forbidden
subprocess.check_call = forbidden
subprocess.check_output = forbidden
subprocess.run = forbidden

for name in (
    "astra_downloader.astra_downloader",
    "astra_downloader.config",
    "astra_downloader.download",
    "astra_downloader.gui",
    "astra_downloader.health",
    "astra_downloader.routes",
):
    importlib.import_module(name)
'''
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(ad.__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class RateLimiterTests(unittest.TestCase):
    """v1.2.0 S2 — sliding-window rate limit on /download."""

    def test_allows_up_to_max_events_then_rejects(self):
        limiter = ad.RateLimiter(max_events=3, window_seconds=60)
        for _ in range(3):
            allowed, retry = limiter.allow('download')
            self.assertTrue(allowed)
            self.assertEqual(retry, 0.0)
        allowed, retry = limiter.allow('download')
        self.assertFalse(allowed)
        self.assertGreater(retry, 0.0)

    def test_separate_bucket_keys_are_independent(self):
        limiter = ad.RateLimiter(max_events=1, window_seconds=60)
        self.assertTrue(limiter.allow('a')[0])
        # Second call to 'a' rejected, but 'b' gets its own budget.
        self.assertFalse(limiter.allow('a')[0])
        self.assertTrue(limiter.allow('b')[0])

    def test_routes_owns_rate_limiter_and_clock_is_injectable(self):
        import routes

        now = [100.0]
        limiter = routes.RateLimiter(1, 10, clock=lambda: now[0])
        self.assertIs(routes.RateLimiter, ad.RateLimiter)
        self.assertTrue(limiter.allow('download')[0])
        self.assertFalse(limiter.allow('download')[0])
        now[0] = 111.0
        self.assertTrue(limiter.allow('download')[0])


class ApiRateLimitTests(unittest.TestCase):
    """End-to-end /download rate limit via the Flask test client."""

    def test_download_endpoint_returns_429_after_burst(self):
        token = "f" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        # Force a low limit so we can exhaust it without actually starting
        # 30 real downloads (which would be blocked by MAX_CONCURRENT first).
        # We replicate the burst at the HTTP layer by patching the limiter
        # state after construction.
        # Simpler: send many OPTIONS-bypassed requests with invalid bodies.
        # The rate check runs after auth but BEFORE body parsing, so a
        # missing body still consumes a token.
        saw_429 = False
        for _ in range(ad.RATE_LIMIT_DOWNLOAD_MAX + 2):
            resp = client.post(
                "/download",
                headers={"X-Auth-Token": token, "Content-Type": "application/json"},
                data="{}",
            )
            if resp.status_code == 429:
                saw_429 = True
                self.assertIn("Retry-After", resp.headers)
                break
        self.assertTrue(saw_429, "rate limiter should reject eventually")

    def test_health_endpoint_returns_429_after_burst(self):
        config = FakeConfig({"ServerToken": "f" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()
        with mock.patch.object(ad, "probe_javascript_runtime", return_value={}), \
                mock.patch.object(ad, "get_ytdlp_version", return_value=None), \
                mock.patch.object(ad, "get_ffmpeg_version", return_value=None), \
                mock.patch.object(ad, "check_ffmpeg_capabilities", return_value={}), \
                mock.patch.object(ad, "probe_po_token_provider", return_value=None):
            responses = [
                client.get("/health", headers={"X-MDL-Client": "MediaDL"})
                for _ in range(ad.RATE_LIMIT_HEALTH_MAX + 1)
            ]

        limited = next((response for response in responses if response.status_code == 429), None)
        self.assertIsNotNone(limited, "health rate limiter should reject eventually")
        self.assertIn("Retry-After", limited.headers)


class CorsHeaderTests(unittest.TestCase):
    def test_response_advertises_max_age(self):
        token = "g" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/health", headers={"X-MDL-Client": "MediaDL"})
        self.assertEqual(resp.headers.get("Access-Control-Max-Age"), str(ad.CORS_MAX_AGE_SECONDS))

    def test_preflight_advertises_supported_auth_headers(self):
        token = "g" * 32
        origin = "chrome-extension://trustedlegacyid"
        config = FakeConfig({
            "ServerToken": token,
            "LegacyHealthTokenOrigins": origin,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().options(
            "/provision-deno",
            headers={
                "Origin": origin,
                "Access-Control-Request-Headers": "X-MDL-Token,X-MDL-Token-Source",
            },
        )
        allowed = {
            header.strip().lower()
            for header in resp.headers.get("Access-Control-Allow-Headers", "").split(",")
        }
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({"x-mdl-token", "x-mdl-token-source"}.issubset(allowed))

    def test_response_disables_intermediary_caching(self):
        # v1.4.0 NX11: defense-in-depth against intermediary caching of
        # auth-bearing responses (CVE-2026-27205 class). Every cors_response
        # must declare Cache-Control: no-store and Vary: Cookie so a future
        # session-bearing variant can't ride on a stale cache entry.
        token = "n" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/health", headers={"X-MDL-Client": "MediaDL"})
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        vary = resp.headers.get("Vary", "")
        self.assertIn("Cookie", vary)

    def test_response_disables_caching_on_extension_origin_too(self):
        # The Origin-allow path adds "Vary: Origin"; the no-store + Cookie
        # token must compose with it, not overwrite it.
        token = "p" * 32
        extension_origin = "chrome-extension://trustedlegacyid"
        config = FakeConfig({
            "ServerToken": token,
            "LegacyHealthTokenOrigins": extension_origin,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get(
            "/health",
            headers={
                "X-MDL-Client": "MediaDL",
                "Origin": extension_origin,
            },
        )
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        vary = resp.headers.get("Vary", "")
        self.assertIn("Cookie", vary)
        self.assertIn("Origin", vary)


class HealthAdditionsTests(unittest.TestCase):
    """v1.2.0 additions to /health schema — version strings + rate-limit policy."""

    def test_health_surface_includes_rate_limit_policy(self):
        token = "h" * 32
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        resp = api.test_client().get("/health", headers={"X-MDL-Client": "MediaDL"})
        body = resp.get_json()
        self.assertIn("rateLimit", body)
        self.assertEqual(body["rateLimit"]["downloadMaxPerWindow"], ad.RATE_LIMIT_DOWNLOAD_MAX)
        self.assertEqual(body["rateLimit"]["downloadWindowSeconds"], ad.RATE_LIMIT_DOWNLOAD_WINDOW_SECONDS)
        self.assertEqual(body["rateLimit"]["healthMaxPerWindow"], ad.RATE_LIMIT_HEALTH_MAX)
        self.assertEqual(body["rateLimit"]["healthWindowSeconds"], ad.RATE_LIMIT_HEALTH_WINDOW_SECONDS)
        # ytDlpVersion / ffmpegVersion are present but may be None in CI; the
        # wire contract is "key exists, value is string or null" — assert both.
        self.assertIn("ytDlpVersion", body)
        self.assertIn("ffmpegVersion", body)


class FolderPickerWatchdogTests(unittest.TestCase):
    """v4.47.0 NF35 — the folder picker dialog can hang on slow file
    systems or stalled Qt event loops. Previously the Flask handler
    timed out at 120s with no GUI-side diagnostic pointing at the
    cause. The watchdog times the QFileDialog.exec() call and emits
    a persistent log line when the dialog blocks past the documented
    threshold (60s).
    """

    def test_threshold_constant_is_60_seconds(self):
        # Pin the threshold so it can't be silently raised to the
        # point of uselessness or lowered to spam the log.
        self.assertEqual(
            ad.FolderPickerService.DIALOG_WATCHDOG_THRESHOLD_SECONDS,
            60,
            "Watchdog threshold must be 60 seconds — leaves a 60s "
            "margin before the Flask handler's 120s timeout, so the "
            "log line gets written before the HTTP request gives up.",
        )

    def test_watchdog_emits_log_when_dialog_blocks_past_threshold(self):
        from PySide6.QtWidgets import QApplication

        _get_qapp_or_skip(self)

        class DialogTypes:
            FileMode = types.SimpleNamespace(Directory=1)
            Option = types.SimpleNamespace(ShowDirsOnly=2, DontResolveSymlinks=4)
            DialogCode = types.SimpleNamespace(Accepted=1)

        class Dialog:
            def setFileMode(self, _value):
                pass

            def setOption(self, *_args):
                pass

            def windowFlags(self):
                return 0

            def setWindowFlags(self, _value):
                pass

            def activateWindow(self):
                pass

            def raise_(self):
                pass

            def exec(self):
                return DialogTypes.DialogCode.Accepted

            def selectedFiles(self):
                return [r"C:\Videos"]

        requests = queue.Queue()
        response = queue.Queue()
        requests.put({"response": response, "initial": r"C:\Videos"})
        logs = []
        clock_values = iter((0.0, 61.0))
        service = gui_module_for_tests().FolderPickerService(
            request_queue=requests,
            dialog_factory=lambda *_args: Dialog(),
            dialog_types=lambda: DialogTypes,
            clock=lambda: next(clock_values),
            logger=logs.append,
        )
        self.addCleanup(service.deleteLater)

        service._tick()
        QApplication.processEvents()

        self.assertEqual(response.get_nowait()["path"], r"C:\Videos")
        self.assertEqual(len(logs), 1)
        self.assertIn("FolderPickerService: dialog blocked for 61.0s", logs[0])
        self.assertIn("threshold 60s", logs[0])
        self.assertIn("Possible Qt event-loop or file-system hang.", logs[0])

    def test_watchdog_does_not_log_for_fast_dialogs(self):
        _get_qapp_or_skip(self)

        class DialogTypes:
            FileMode = types.SimpleNamespace(Directory=1)
            Option = types.SimpleNamespace(ShowDirsOnly=2, DontResolveSymlinks=4)
            DialogCode = types.SimpleNamespace(Accepted=1)

        class Dialog:
            def setFileMode(self, _value):
                pass

            def setOption(self, *_args):
                pass

            def windowFlags(self):
                return 0

            def setWindowFlags(self, _value):
                pass

            def activateWindow(self):
                pass

            def raise_(self):
                pass

            def exec(self):
                return DialogTypes.DialogCode.Accepted

            def selectedFiles(self):
                return [r"C:\Videos"]

        requests = queue.Queue()
        response = queue.Queue()
        requests.put({"response": response, "initial": r"C:\Videos"})
        logs = []
        clock_values = iter((0.0, 1.0))
        service = gui_module_for_tests().FolderPickerService(
            request_queue=requests,
            dialog_factory=lambda *_args: Dialog(),
            dialog_types=lambda: DialogTypes,
            clock=lambda: next(clock_values),
            logger=logs.append,
        )
        self.addCleanup(service.deleteLater)

        service._tick()

        self.assertEqual(response.get_nowait()["path"], r"C:\Videos")
        self.assertEqual(logs, [])


class NativeExtensionIdSanitizeTests(unittest.TestCase):
    """A config field that keeps IDs registration would drop is a lie.

    ``clean_text`` only trimmed and truncated, so a hand-edited config could
    show four Chrome IDs on the Extension page while the native host manifest
    carried one.
    """

    def test_sanitize_keeps_only_ids_the_registrar_would_accept(self):
        valid = "abcdefghijklmnopabcdefghijklmnop"
        other = "ponmlkjihgfedcbaponmlkjihgfedcba"
        cleaned = ad.sanitize_config({
            "NativeChromeExtensionIds": (
                f"{valid} NOT-AN-ID {other} tooshort {valid}"
            ),
        })["NativeChromeExtensionIds"]
        self.assertEqual(cleaned.split(), [valid, other])

    def test_sanitize_lowercases_chrome_ids_and_deduplicates(self):
        cleaned = ad.sanitize_config({
            "NativeChromeExtensionIds": "ABCDEFGHIJKLMNOPABCDEFGHIJKLMNOP abcdefghijklmnopabcdefghijklmnop",
        })["NativeChromeExtensionIds"]
        self.assertEqual(cleaned, "abcdefghijklmnopabcdefghijklmnop")

    def test_sanitize_uses_the_firefox_rule_for_the_firefox_field(self):
        # Firefox IDs are an email-like or GUID shape, not the Chrome alphabet.
        cleaned = ad.sanitize_config({
            "NativeFirefoxExtensionIds": "astra@example.com  <script>  {a-b-c}",
        })["NativeFirefoxExtensionIds"]
        self.assertIn("astra@example.com", cleaned.split())
        self.assertNotIn("<script>", cleaned)

    def test_sanitize_is_idempotent(self):
        once = ad.sanitize_config({
            "NativeChromeExtensionIds": "abcdefghijklmnopabcdefghijklmnop bogus",
        })["NativeChromeExtensionIds"]
        twice = ad.sanitize_config({
            "NativeChromeExtensionIds": once,
        })["NativeChromeExtensionIds"]
        self.assertEqual(once, twice)

    def test_the_parser_lives_where_sanitize_can_reach_it(self):
        # The composition root re-exports it; config.py owns it. A copy in both
        # is the drift this move exists to prevent.
        import config as config_module
        self.assertIs(ad.parse_native_extension_ids,
                      config_module.parse_native_extension_ids)
        self.assertIs(ad.is_valid_native_extension_id,
                      config_module.is_valid_native_extension_id)


class PoTokenProviderTests(unittest.TestCase):
    def setUp(self):
        ad.reset_po_token_provider_cache()

    def tearDown(self):
        ad.reset_po_token_provider_cache()

    def test_is_youtube_url_matches_canonical_hosts(self):
        for url in (
            "https://www.youtube.com/watch?v=abc",
            "https://youtube.com/watch?v=abc",
            "https://m.youtube.com/watch?v=abc",
            "https://youtu.be/abc",
            "https://www.youtube-nocookie.com/embed/abc",
            "http://youtube.com/",
        ):
            with self.subTest(url=url):
                self.assertTrue(ad.is_youtube_url(url))

    def test_is_youtube_url_rejects_non_youtube(self):
        for url in (
            "",
            None,
            "https://example.com/watch?v=abc",
            "https://fake-youtube.com.evil.example/",
            "https://youtubevideos.example.com/",
            "ftp://youtube.com/",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url):
                self.assertFalse(ad.is_youtube_url(url))

    def test_is_youtube_url_resolves_the_host_not_the_url_text(self):
        # This predicate decides which cookie jar a yt-dlp process receives on a
        # `--cookies` write path, so anything that merely *contains* a YouTube
        # host must be refused. Each case here defeats a substring match.
        cases = (
            ("https://evil.com?x=.youtube.com/", False),
            ("https://evil.com#.youtube.com/", False),
            ("https://evil.com/?redirect=https://youtube.com/", False),
            ("https://youtube.com@evil.com/", False),
            ("https://user:youtube.com@evil.com/watch", False),
            ("https://youtube.com.evil.com/", False),
            ("https://notyoutube.com/", False),
            ("https://youtube.com.", True),
            ("https://WWW.YouTube.COM/watch?v=abc", True),
            ("https://youtu.be/abcdefghijk", True),
            ("https://music.youtube.com/watch?v=abc", True),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(ad.is_youtube_url(url), expected)

    def test_subscription_default_youtube_predicate_matches_health(self):
        # subscriptions.py keeps its own fallback copy because module
        # boundaries never cross-import; the two must not drift.
        import subscriptions as _subscriptions

        for url in (
            "https://evil.com?x=.youtube.com/",
            "https://youtube.com@evil.com/",
            "https://www.youtube.com/@channel",
            "https://notyoutube.com/",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    _subscriptions._default_is_youtube_url(url),
                    ad.is_youtube_url(url),
                )

    def test_build_youtube_extractor_args_empty_for_non_youtube(self):
        # Non-YouTube URLs must never receive YouTube-specific extractor args
        # so the helper stays safe to splat unconditionally in _run_download.
        for url in ("https://example.com/v/1", "https://vimeo.com/1"):
            self.assertEqual(
                ad.build_youtube_extractor_args(
                    url,
                    po_token_provider={'ok': True, 'port': 4416, 'version': None},
                ),
                [],
            )

    def test_build_youtube_extractor_args_always_includes_sabr_formats_duplicate(self):
        # N2: SABR-only adaptiveFormats silently break downloads on the
        # 2026 web client. ``youtube:formats=duplicate`` asks yt-dlp to
        # return both HTTPS and SABR families. Must be emitted whether or
        # not a PO Token provider is reachable, because SABR is a read-time
        # concern, not a token-mediated one.
        without_provider = ad.build_youtube_extractor_args(
            "https://www.youtube.com/watch?v=abc",
        )
        with_provider = ad.build_youtube_extractor_args(
            "https://www.youtube.com/watch?v=abc",
            po_token_provider={'ok': True, 'port': 4416, 'version': '1.2.3'},
        )
        for label, args in (("no-provider", without_provider),
                            ("with-provider", with_provider)):
            with self.subTest(label=label):
                self.assertIn('youtube:formats=duplicate', args)
                idx = args.index('youtube:formats=duplicate')
                self.assertEqual(args[idx - 1], '--extractor-args')
                for extractor_arg in (
                    'youtube:skip=translated_subs',
                    'youtube-ejs:jitless=true',
                ):
                    self.assertIn(extractor_arg, args)
                    extractor_idx = args.index(extractor_arg)
                    self.assertEqual(args[extractor_idx - 1], '--extractor-args')

    def test_build_youtube_extractor_args_includes_only_sabr_when_provider_absent(self):
        # Validates that PO token routing is gated on provider availability
        # while SABR is unconditional. Prevents future regressions where
        # somebody short-circuits the helper to return [] on provider miss.
        for absent in (None, {'ok': False}, {}):
            with self.subTest(provider=absent):
                args = ad.build_youtube_extractor_args(
                    "https://www.youtube.com/watch?v=abc",
                    po_token_provider=absent,
                )
                self.assertIn('youtube:formats=duplicate', args)
                self.assertFalse(any(
                    a.startswith('youtubepot-bgutilhttp:') for a in args
                ))

    def test_build_youtube_extractor_args_ignores_a_reachable_provider(self):
        args = ad.build_youtube_extractor_args(
            "https://www.youtube.com/watch?v=abc",
            po_token_provider={'ok': True, 'port': 4416, 'version': '1.2.3'},
        )
        self.assertIn('--extractor-args', args)
        self.assertFalse(any(a.startswith('youtubepot-bgutilhttp:') for a in args))
        self.assertIn(
            'youtube:player_client=visionos,tv,web_embedded',
            args,
        )
        self.assertFalse(any('android_vr' in a for a in args))
        # SABR arg remains alongside the deterministic token-exempt fallback.
        self.assertIn('youtube:formats=duplicate', args)

    def test_build_youtube_extractor_args_falls_back_to_token_exempt_clients(self):
        # Without a reachable PO-token provider the default web/mweb clients
        # need GVS tokens and fail; fall back to the token-exempt clients first
        # so extraction degrades instead of failing outright.
        fallback = 'youtube:player_client=visionos,tv,web_embedded'
        for absent in (None, {'ok': False}, {}):
            with self.subTest(provider=absent):
                args = ad.build_youtube_extractor_args(
                    "https://www.youtube.com/watch?v=abc",
                    po_token_provider=absent,
                )
                self.assertIn(fallback, args)
                idx = args.index(fallback)
                self.assertEqual(args[idx - 1], '--extractor-args')
        # Chain hygiene: bare `web` is NOT token-exempt (SABR-only without a
        # GVS token), visionos is the measured first choice, and android_vr
        # is gone (yt-dlp 2026.08.19 403s that client).
        clients = fallback.split('=', 1)[1].split(',')
        self.assertNotIn('web', clients)
        self.assertNotIn('android_vr', clients)
        self.assertEqual(clients[0], 'visionos')
        self.assertEqual(clients[-1], 'web_embedded')
        # A reachable bgutil process cannot change the argv while plugin
        # loading is disabled, so the same fallback remains in force.
        ok_args = ad.build_youtube_extractor_args(
            "https://www.youtube.com/watch?v=abc",
            po_token_provider={'ok': True, 'port': 4416},
        )
        self.assertIn(fallback, ok_args)
        self.assertFalse(any(a.startswith('youtubepot-bgutilhttp:') for a in ok_args))
        # A stale provider is equally unable to alter the plugin-free path.
        stale_args = ad.build_youtube_extractor_args(
            "https://www.youtube.com/watch?v=abc",
            po_token_provider={'ok': True, 'port': 4416, 'stale': True},
        )
        self.assertIn(fallback, stale_args)
        self.assertFalse(any(a.startswith('youtubepot-bgutilhttp:') for a in stale_args))
        # Non-YouTube URLs get no extractor args at all, fallback included.
        self.assertEqual(ad.build_youtube_extractor_args("https://example.com/x"), [])

    def test_probe_never_claims_a_provider_is_usable(self):
        original_get = ad.http_requests.get
        calls = []
        ad.http_requests.get = lambda *args, **kwargs: calls.append(args) or None
        try:
            self.assertIsNone(ad.probe_po_token_provider(force=True))
            self.assertIsNone(ad.probe_po_token_provider())
        finally:
            ad.http_requests.get = original_get
        self.assertEqual(calls, [])

    def test_compare_semver_handles_unusual_inputs(self):
        # Pre-release suffix is truncated at first non-digit segment.
        self.assertEqual(ad._compare_semver('1.3.1-rc.2', '1.3.1'), 0)
        # 'v' prefix is stripped.
        self.assertEqual(ad._compare_semver('v1.3.1', '1.3.1'), 0)
        # Different lengths normalize with zero-pad.
        self.assertEqual(ad._compare_semver('1.3', '1.3.0'), 0)
        self.assertEqual(ad._compare_semver('1.3', '1.3.1'), -1)
        # Garbage inputs compare as empty lists (equal).
        self.assertEqual(ad._compare_semver(None, None), 0)
        self.assertEqual(ad._compare_semver('', ''), 0)


class PreflightHealthTests(unittest.TestCase):
    """The download failure taxonomy is named before a job starts."""

    @staticmethod
    def _base(**overrides):
        values = {
            'ytdlp_version': '2026.08.01',
            'ffmpeg_capabilities': {
                'current': True,
                'filterCheck': True,
                'missingFilters': [],
            },
            'javascript_runtime': {'ytdlpNeedsRuntime': False},
            'sign_in_entries': [],
            'github_api_budget': {'remaining': 20, 'limit': 60},
            'po_token_provider': None,
            'now': '2026-08-11',
        }
        values.update(overrides)
        return ad.evaluate_preflight_checks(**values)

    def _check(self, result, check_id):
        return next(item for item in result['checks'] if item['id'] == check_id)

    def test_ytdlp_freshness_names_stale_release_and_refresh_action(self):
        check = self._check(
            self._base(ytdlp_version='2026.06.01'), 'ytdlp-freshness'
        )
        self.assertEqual(check['status'], 'warning')
        self.assertEqual(check['action'], 'refresh-ytdlp')
        self.assertEqual(check['details']['ageDays'], 71)

    def test_javascript_runtime_names_missing_external_runtime(self):
        check = self._check(self._base(
            javascript_runtime={
                'ytdlpNeedsRuntime': True,
                'supported': False,
                'ejsReady': False,
                'reason': 'runtime-not-installed',
            },
        ), 'javascript-runtime')
        self.assertEqual(check['status'], 'error')
        self.assertEqual(check['action'], 'provision-runtime')

    def test_ffmpeg_filter_gap_is_a_named_repair(self):
        check = self._check(self._base(
            ffmpeg_capabilities={
                'current': True,
                'filterCheck': True,
                'missingFilters': ['aformat'],
            },
        ), 'ffmpeg-capabilities')
        self.assertEqual(check['status'], 'error')
        self.assertEqual(check['action'], 'refresh-ffmpeg')
        self.assertEqual(check['details']['missingFilters'], ['aformat'])

    def test_expired_sign_in_is_aggregate_and_never_exposes_site_names(self):
        result = self._base(sign_in_entries=[{
            'site': 'private.example', 'cookies': 4, 'expired': True,
            'stored': True,
        }])
        check = self._check(result, 'sign-in-expiry')
        self.assertEqual(check['status'], 'warning')
        self.assertEqual(check['action'], 'refresh-sign-in')
        self.assertEqual(check['details']['expiredCount'], 1)
        self.assertNotIn('private.example', json.dumps(result))

    def test_exhausted_github_budget_is_blocking_and_retryable(self):
        check = self._check(
            self._base(github_api_budget={'remaining': 0, 'resetAt': 123}),
            'github-api-budget',
        )
        self.assertEqual(check['status'], 'error')
        self.assertEqual(check['action'], 'retry-github')
        self.assertIn('github-api-budget', self._base(
            github_api_budget={'remaining': 0}
        )['blocking'])

    def test_failed_token_provider_names_the_sign_in_fallback(self):
        check = self._check(self._base(
            po_token_provider={'ok': False, 'reason': 'mint-failed'},
        ), 'po-token-provider')
        self.assertEqual(check['status'], 'warning')
        self.assertEqual(check['action'], 'use-sign-in')

    def test_filter_parser_accepts_ffmpeg_table_and_ignores_banners(self):
        output = """
        ffmpeg version 8.1.2
        Filters:
          T.. aformat      A->A       Convert the input audio format
          ... scale        V->V       Scale the input video
        """
        self.assertEqual(ad.missing_ffmpeg_filters(output), [])
        self.assertEqual(
            ad.missing_ffmpeg_filters("Filters:\n  ... scale V->V Scale"),
            ['aformat'],
        )

    def test_output_folder_names_a_disconnected_drive_and_a_read_only_folder(self):
        gone = self._check(self._base(output_folder={
            'configured': True, 'exists': False, 'writable': False,
        }), 'output-folder')
        self.assertEqual(gone['status'], 'error')
        self.assertEqual(gone['action'], 'choose-output-folder')
        self.assertIn('not connected', gone['message'])
        read_only = self._check(self._base(output_folder={
            'configured': True, 'exists': True, 'writable': False,
        }), 'output-folder')
        self.assertEqual(read_only['status'], 'error')
        unset = self._check(self._base(output_folder={
            'configured': False, 'exists': False, 'writable': False,
        }), 'output-folder')
        self.assertEqual(unset['status'], 'error')
        self.assertIs(unset['details']['configured'], False)
        healthy = self._check(self._base(output_folder={
            'configured': True, 'exists': True, 'writable': True,
        }), 'output-folder')
        self.assertEqual(healthy['status'], 'ok')

    def test_output_folder_probe_reports_what_the_filesystem_says(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(
                ad.probe_output_folder(root),
                {'configured': True, 'exists': True, 'writable': True},
            )
            self.assertEqual(
                ad.probe_output_folder(root / 'not-there'),
                {'configured': True, 'exists': False, 'writable': False},
            )
            self.assertEqual(
                ad.probe_output_folder(''),
                {'configured': False, 'exists': False, 'writable': False},
            )
            # The probe must leave nothing behind, or every readiness pass
            # litters the user's download folder.
            self.assertEqual(list(root.iterdir()), [])

    def test_state_location_names_the_update_that_would_erase_it(self):
        portable = self._check(self._base(state_location={
            'portable': True, 'exists': True, 'writable': True, 'protected': False,
        }), 'state-location')
        self.assertEqual(portable['status'], 'warning')
        self.assertEqual(portable['action'], 'review-state-location')
        self.assertIn('erases them', portable['message'])
        protected = self._check(self._base(state_location={
            'portable': True, 'exists': True, 'writable': True, 'protected': True,
        }), 'state-location')
        self.assertEqual(protected['status'], 'warning')
        self.assertIn('protected program folder', protected['message'])
        unwritable = self._check(self._base(state_location={
            'portable': False, 'exists': True, 'writable': False, 'protected': False,
        }), 'state-location')
        self.assertEqual(unwritable['status'], 'error')
        installed = self._check(self._base(state_location={
            'portable': False, 'exists': True, 'writable': True, 'protected': False,
        }), 'state-location')
        self.assertEqual(installed['status'], 'ok')

    def test_state_location_probe_sees_a_protected_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ad.probe_state_location(root, portable=True,
                                            protected_roots=[str(root.parent)])
            self.assertTrue(state['portable'])
            self.assertTrue(state['writable'])
            self.assertTrue(state['protected'])
            self.assertEqual(list(root.iterdir()), [])
            outside = ad.probe_state_location(root, protected_roots=[])
            self.assertFalse(outside['protected'])
            self.assertFalse(outside['portable'])

    def test_site_availability_separates_a_long_streak_from_a_fresh_one(self):
        fresh = self._check(self._base(site_refusals=[
            {'failures': 3, 'openForSeconds': 120.0},
        ]), 'site-availability')
        self.assertEqual(fresh['status'], 'warning')
        self.assertEqual(fresh['action'], 'review-site-refusals')
        self.assertIs(fresh['details']['longTerm'], False)
        long_term = self._check(self._base(site_refusals=[
            {'failures': 9, 'openForSeconds': 4 * 60 * 60},
            {'failures': 3, 'openForSeconds': 30.0},
        ]), 'site-availability')
        self.assertEqual(long_term['status'], 'warning')
        self.assertIs(long_term['details']['longTerm'], True)
        self.assertEqual(long_term['details']['refusingSites'], 2)
        self.assertIn('4 hour(s)', long_term['message'])
        quiet = self._check(self._base(site_refusals=[]), 'site-availability')
        self.assertEqual(quiet['status'], 'not-applicable')

    def test_system_clock_escalates_with_the_size_of_the_drift(self):
        fine = self._check(self._base(system_clock={
            'measured': True, 'offsetSeconds': 12,
        }), 'system-clock')
        self.assertEqual(fine['status'], 'ok')
        drifting = self._check(self._base(system_clock={
            'measured': True, 'offsetSeconds': -20 * 60,
        }), 'system-clock')
        self.assertEqual(drifting['status'], 'warning')
        self.assertEqual(drifting['action'], 'sync-system-clock')
        self.assertIn('20 minute(s)', drifting['message'])
        broken = self._check(self._base(system_clock={
            'measured': True, 'offsetSeconds': 3 * 24 * 60 * 60,
        }), 'system-clock')
        self.assertEqual(broken['status'], 'error')
        self.assertIn('72 hour(s)', broken['message'])
        unmeasured = self._check(self._base(), 'system-clock')
        self.assertEqual(unmeasured['status'], 'not-applicable')

    def test_system_clock_offset_is_read_off_a_response_date_header(self):
        # RFC 7231 Date, against a local clock ten minutes ahead of it.
        measured = ad.measure_system_clock_offset(
            'Fri, 21 Aug 2026 10:00:00 GMT',
            local_epoch=ad.parse_http_date_epoch(
                'Fri, 21 Aug 2026 10:10:00 GMT'),
        )
        self.assertEqual(measured, {'measured': True, 'offsetSeconds': 600.0})
        self.assertIsNone(ad.measure_system_clock_offset(''))
        self.assertIsNone(ad.measure_system_clock_offset('not a date'))

    def test_a_response_without_rate_limit_headers_still_sets_the_clock(self):
        class _Response:
            headers = {'Date': 'Fri, 21 Aug 2026 10:00:00 GMT'}

        with mock.patch.object(ad, 'measure_system_clock_offset', return_value={
            'measured': True, 'offsetSeconds': 42.0,
        }):
            ad.observe_github_api_budget(_Response())
        self.assertEqual(
            ad.get_system_clock_state(),
            {'measured': True, 'offsetSeconds': 42.0},
        )

    def test_a_refusal_circuit_reports_how_long_it_has_been_open(self):
        config = FakeConfig({'ServerToken': 'q' * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        self.assertEqual(manager.refusing_sites(), [])
        for _attempt in range(2):
            manager._record_host_circuit_failure(
                'https://refuser.invalid/watch', 'blocked-by-site')
        # Below the threshold the circuit is not open, so nothing is reported.
        self.assertEqual(manager.refusing_sites(), [])
        manager._record_host_circuit_failure(
            'https://refuser.invalid/watch', 'blocked-by-site')
        open_circuits = manager.refusing_sites()
        self.assertEqual(len(open_circuits), 1)
        self.assertEqual(open_circuits[0]['failures'], 3)
        self.assertGreaterEqual(open_circuits[0]['openForSeconds'], 0.0)
        self.assertGreater(open_circuits[0]['remainingSeconds'], 0.0)
        # A success clears it, which is what keeps the check from crying wolf.
        completed = ad.Download('d', 'https://refuser.invalid/watch')
        completed.status = 'complete'
        manager._record_host_circuit_outcome(completed)
        self.assertEqual(manager.refusing_sites(), [])

    def test_every_check_has_a_panel_row_with_a_named_remedy(self):
        # A check the panel has no row for is a check nobody sees, and a row
        # whose action the handler does not know reads "Fix" and does nothing.
        # The row table has to be the one BOTH sides use: the page builds
        # widgets from it and _apply_preflight writes statuses through it.
        import gui_download_page

        rows = {
            key: action
            for key, _label, action in gui_download_page.PREFLIGHT_ROW_SPECS
        }
        self.assertIs(
            gui_module_for_tests().PREFLIGHT_ROW_SPECS,
            gui_download_page.PREFLIGHT_ROW_SPECS,
        )
        produced = {
            item['id']: item['action']
            for item in self._base(
                output_folder={'configured': True, 'exists': True, 'writable': True},
                state_location={'portable': False, 'exists': True,
                                'writable': True, 'protected': False},
                site_refusals=[],
                system_clock={'measured': True, 'offsetSeconds': 0},
            )['checks']
        }
        self.assertEqual(set(produced), set(rows))
        self.assertEqual(produced, rows)
        handler = inspect.getsource(ad.MainWindow._run_preflight_action)
        labels = inspect.getsource(ad.MainWindow._set_preflight_row)
        for action in sorted(set(rows.values())):
            with self.subTest(action=action):
                self.assertIn(f'"{action}"', handler)
                self.assertIn(f'"{action}":', labels)

    def test_apply_preflight_writes_every_check_the_evaluator_produces(self):
        # The panel test above proves the two tables agree. This one proves
        # the write actually lands: a row nobody updates sits on "Checking"
        # forever, and the summary short-circuits on it.
        _get_qapp_or_skip(self)
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad.MainWindow, "_start_instance_command_listener"),                 mock.patch.object(ad.MainWindow, "_start_readiness_probe"),                 mock.patch.object(ad.QSystemTrayIcon, "show"):
            window = ad.MainWindow(config, manager, FakeHistory())
        try:
            healthy = self._base(
                output_folder={'configured': True, 'exists': True, 'writable': True},
                state_location={'portable': False, 'exists': True,
                                'writable': True, 'protected': False},
                site_refusals=[],
                system_clock={'measured': True, 'offsetSeconds': 0},
                po_token_provider=None,
            )
            window._apply_preflight(healthy)
            self.assertNotIn(
                "unknown", set(window._preflight_statuses.values()),
                f"a row was left unwritten: {window._preflight_statuses}",
            )
            self.assertEqual(
                window.preflight_summary.text(),
                f"All {len(window.preflight_values)} checks passed. "
                "Downloads are ready.",
            )
            broken = self._base(
                output_folder={'configured': True, 'exists': False, 'writable': False},
                state_location={'portable': False, 'exists': True,
                                'writable': True, 'protected': False},
                site_refusals=[],
                system_clock={'measured': True, 'offsetSeconds': 0},
                po_token_provider=None,
            )
            window._apply_preflight(broken)
            self.assertEqual(window._preflight_statuses["output-folder"], "error")
            self.assertIn("repair", window.preflight_summary.text().lower())
        finally:
            _retire_test_window(window)

    def test_health_exposes_preflight_without_network_or_site_metadata(self):
        config = FakeConfig({'ServerToken': 'p' * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.08.01'), \
                mock.patch.object(ad, 'get_ffmpeg_version', return_value='8.1.2'), \
                mock.patch.object(ad, 'probe_javascript_runtime', return_value={
                    'ytdlpNeedsRuntime': False,
                }), \
                mock.patch.object(ad, 'get_preflight_ffmpeg_capabilities', return_value={
                    'current': True, 'filterCheck': True, 'missingFilters': [],
                }), \
                mock.patch.object(ad, 'get_github_api_budget', return_value={
                    'remaining': 42, 'limit': 60,
                }):
            api = ad.create_api(config, manager, FakeHistory())
            body = api.test_client().get(
                '/health', headers={'X-MDL-Client': 'MediaDL'},
            ).get_json()
        self.assertIn('preflight', body)
        self.assertEqual(
            body['preflight']['status'], 'ready',
            f"blocking={body['preflight'].get('blocking')} "
            f"attention={body['preflight'].get('attention')}",
        )
        self.assertEqual(
            {item['id'] for item in body['preflight']['checks']},
            {
                'ytdlp-freshness', 'javascript-runtime',
                'ffmpeg-capabilities', 'sign-in-expiry',
                'github-api-budget', 'po-token-provider',
                'output-folder', 'state-location', 'site-availability',
                'system-clock',
            },
        )
        # The site-availability check counts refusing domains, so a substring
        # search for "site" no longer says anything. Drive a real refusal
        # circuit open and assert the domain itself never reaches the wire.
        for _attempt in range(3):
            manager._record_host_circuit_failure(
                'https://refuser.invalid/watch', 'blocked-by-site',
            )
        with mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.08.01'),                 mock.patch.object(ad, 'get_ffmpeg_version', return_value='8.1.2'),                 mock.patch.object(ad, 'probe_javascript_runtime', return_value={
                    'ytdlpNeedsRuntime': False,
                }):
            refused = api.test_client().get(
                '/health', headers={'X-MDL-Client': 'MediaDL'},
            ).get_json()['preflight']
        availability = next(
            item for item in refused['checks'] if item['id'] == 'site-availability'
        )
        self.assertEqual(availability['status'], 'warning')
        self.assertEqual(availability['details']['refusingSites'], 1)
        self.assertNotIn('refuser.invalid', json.dumps(refused))


class HealthPoTokenSurfaceTests(unittest.TestCase):
    def setUp(self):
        ad.reset_po_token_provider_cache()

    def tearDown(self):
        ad.reset_po_token_provider_cache()

    def test_health_includes_po_token_provider_field_null_when_absent(self):
        # The extension popup keys the amber "PO Token provider not detected"
        # pill off this exact field shape. Pin it so the wire contract is
        # explicit.
        config = FakeConfig({"ServerToken": "f" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())

        # Force the probe to return None without hitting the network.
        original_get = ad.http_requests.get
        ad.http_requests.get = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
        try:
            resp = api.test_client().get(
                "/health", headers={"X-MDL-Client": "MediaDL"},
            )
        finally:
            ad.http_requests.get = original_get
        body = resp.get_json()
        self.assertIn("poTokenProvider", body)
        self.assertIsNone(body["poTokenProvider"])


class HealthDenoRuntimeSurfaceTests(unittest.TestCase):
    """/health.denoRuntime field on the wire."""

    def setUp(self):
        ad.reset_deno_runtime_cache()
        ad.reset_po_token_provider_cache()

    def tearDown(self):
        ad.reset_deno_runtime_cache()
        ad.reset_po_token_provider_cache()

    def test_health_includes_deno_runtime_field(self):
        config = FakeConfig({"ServerToken": "f" * 32})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        original_which = ad.shutil.which
        original_get_version = ad.get_ytdlp_version
        original_po_get = ad.http_requests.get
        ad.shutil.which = lambda binary: None
        ad.get_ytdlp_version = lambda force=False: '2025.10.22'
        ad.http_requests.get = lambda *a, **k: (_ for _ in ()).throw(Exception("offline"))
        try:
            resp = api.test_client().get(
                "/health", headers={"X-MDL-Client": "MediaDL"},
            )
        finally:
            ad.shutil.which = original_which
            ad.get_ytdlp_version = original_get_version
            ad.http_requests.get = original_po_get
        body = resp.get_json()
        self.assertIn("denoRuntime", body)
        self.assertIn("javascriptRuntime", body)
        self.assertIsInstance(body["denoRuntime"], dict)
        for key in ("installed", "version", "ytdlpNeedsRuntime", "advice"):
            self.assertIn(key, body["denoRuntime"])
        self.assertNotIn("path", body["denoRuntime"])
        for key in ("runtime", "version", "supported", "ejsReady", "reason"):
            self.assertIn(key, body["javascriptRuntime"])

    def test_api_version_constant_at_2(self):
        # Adding fields to /health is additive — wire-major stays at 2.
        # Pin so a future bump is a deliberate, reviewed change.
        self.assertEqual(ad.SERVICE_API_VERSION, 2)

    def test_app_version_bumped_to_2_11_0(self):
        # v2.11.0: subscriptions carry their own destination, format, quality
        # and naming, their archive is browsable and reversible, and a scan
        # can notice an upload that vanished or a file that was deleted; a
        # managed binary can be pinned and rolled back; the taskbar gains a
        # jump list and the app comes back after an update reboot; the
        # original upload wins over YouTube's AI upscale; download health
        # gained the four environment checks Radarr proves matter; and the
        # queue no longer fsyncs under the lock the window takes.
        # v2.8.0: playlists stage for review before queueing, progress names
        # its pipeline step, every job records a redacted argv (queue menu,
        # API, diagnostics), Chrome/Edge pair from the Extension page, Deno
        # gains a security floor, status labels carry a visible tone, system
        # binaries spawn by absolute path, and the winget digest is generated
        # from the staged artifact.
        # v2.7.0: a download can carry its own file name, downloads can inherit
        # the proxy Windows is configured with, a release ships a CycloneDX SBOM
        # and a PEP 751 lock beside the binary, every check gate reports its own
        # result, and the local API version became a negotiated contract.
        # v2.6.0: local SRT sidecars, an antivirus-resistant one-folder build,
        # bounded subscription rollback and first-run setup guidance join the
        # existing subtitle, QuickJS, taskbar, bundle and translation work.
        # v2.5.0: subtitle tracks can be chosen and fetched without the video,
        # QuickJS is a 2 MB fallback when Deno cannot be had, the taskbar shows
        # queue progress under an explicit app identity, settings and
        # subscriptions export to a portable bundle, and the UI strings are
        # extracted from the source rather than listed by hand.
        self.assertEqual(ad.APP_VERSION, "2.11.0")

    def test_v1_8_0_any_site_download_surface_is_still_present(self):
        # v1.8.0 any-site downloads: the YouTube-only URL allowlist became a
        # private-network denylist, the JS-runtime gate and the cookie jar are
        # YouTube-scoped, non-YouTube singles download with --no-playlist, a
        # zero-exit run that wrote no file reports `skipped`, and the quick
        # download box accepts a multi-link paste.
        # Pinned by capability rather than by version so the v1.8.0 surface
        # cannot quietly regress behind a later bump.
        self.assertTrue(ad.is_supported_media_url("https://www.reddit.com/r/videos/x/"))
        self.assertEqual(ad.media_url_block_reason("http://127.0.0.1/x"), "private-host")
        self.assertIn("skipped", ad.DOWNLOAD_TERMINAL_STATES)
        self.assertTrue(ad.is_playlist_url("https://soundcloud.com/a/sets/b"))
        self.assertFalse(ad.is_playlist_url("https://x.com/a/status/1"))


class UpdateYtdlpEndpointTests(unittest.TestCase):
    """v4.47.0 NF18 — on-demand `yt-dlp -U` via `/update-ytdlp` so a
    user can fix a broken-on-YouTube yt-dlp build without waiting up
    to 24 h for the auto-update throttle (NF26). Endpoint shares the
    `_run_ytdlp_self_update` runner with the auto-update path so a
    successful manual update also stamps the throttle marker and
    invalidates the version cache.
    """

    TOKEN = "u" * 32

    def _client(self, *, in_flight=0, ytdlp_present=True):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        install_dir = Path(temp_dir.name)
        ytdlp_path = install_dir / 'yt-dlp.exe'
        if ytdlp_present:
            ytdlp_path.write_bytes(b'old-ytdlp')
        path_patch = mock.patch.object(ad, 'YTDLP_PATH', ytdlp_path)
        install_patch = mock.patch.object(ad, 'INSTALL_DIR', install_dir)
        path_patch.start()
        install_patch.start()
        self.addCleanup(path_patch.stop)
        self.addCleanup(install_patch.stop)
        config = FakeConfig({"ServerToken": self.TOKEN})

        class _FakeManager:
            downloads = {}
            _lock = threading.Lock()

            def active_count(_self):
                return in_flight

        manager = _FakeManager()
        api = ad.create_api(config, manager, FakeHistory())
        return api.test_client()

    def test_unauthenticated_request_is_rejected(self):
        client = self._client()
        resp = client.post("/update-ytdlp")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("rejected", resp.get_json()["error"])

    def test_missing_ytdlp_returns_503(self):
        client = self._client(ytdlp_present=False)
        resp = client.post("/update-ytdlp", headers={"X-Auth-Token": self.TOKEN})
        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("not installed", body["error"])

    def test_in_flight_downloads_block_update_with_409(self):
        client = self._client(in_flight=2)
        resp = client.post("/update-ytdlp", headers={"X-Auth-Token": self.TOKEN})
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("inFlight"), 2)
        # Error must explain WHY the update is blocked so the popup
        # can render an actionable status string. The phrase
        # references the atomic-replace race documented in NF26.
        self.assertIn("in flight", body["error"])
        self.assertIn("atomically replaces", body["error"])

    def test_successful_self_update_returns_200_with_version_delta(self):
        client = self._client()
        old_payload = b'old-ytdlp'
        new_payload = b'new-ytdlp'

        def probe(path, timeout=15):
            payload = Path(path).read_bytes() if Path(path).exists() else b''
            return '2026.04.01' if payload == old_payload else ('2026.05.10' if payload == new_payload else '')

        def run_update(args, **_kwargs):
            self.assertEqual(args[1], '--update-to')
            self.assertEqual(args[2], 'nightly@latest')
            Path(args[0]).write_bytes(new_payload)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='updated', stderr='')

        with mock.patch.object(ad, '_probe_ytdlp_binary', side_effect=probe), \
             mock.patch.object(ad.subprocess, 'run', side_effect=run_update):
            resp = client.post("/update-ytdlp", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("exit_code"), 0)
        self.assertEqual(body.get("version_before"), '2026.04.01')
        self.assertEqual(body.get("version_after"), '2026.05.10')
        self.assertEqual(body.get("rollback_version"), '2026.04.01')
        self.assertEqual(ad.YTDLP_PATH.read_bytes(), new_payload)
        self.assertEqual((ad.INSTALL_DIR / ad.YTDLP_ROLLBACK_FILENAME).read_bytes(), old_payload)
        self.assertEqual(body.get("source"), 'manual')

    def test_nonzero_exit_returns_500_with_stderr(self):
        client = self._client()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Update failed: network unreachable",
        )
        with mock.patch.object(ad.subprocess, 'run', return_value=completed), \
             mock.patch.object(ad, '_probe_ytdlp_binary', return_value='2026.04.01'):
            resp = client.post("/update-ytdlp", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("exit_code"), 1)
        self.assertIn("network unreachable", body.get("error"))
        # version_before == version_after on failure (no replacement happened).
        self.assertEqual(body.get("version_before"), body.get("version_after"))

    def test_failed_update_records_attempt_and_short_backoff(self):
        self._client()
        config = {"AutoUpdateYtDlp": True, "LastYtDlpUpdateCheck": ""}
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="offline",
        )
        with mock.patch.object(ad.subprocess, 'run', return_value=completed), \
             mock.patch.object(ad, '_probe_ytdlp_binary', return_value='2026.04.01'):
            result = ad._run_ytdlp_self_update(config, source_tag='unit-test')

        self.assertFalse(result['ok'])
        self.assertTrue(config.get('LastYtDlpUpdateAttempt'))
        self.assertTrue(config.get('LastYtDlpUpdateFailure'))
        self.assertFalse(ad.should_check_ytdlp_update(config))

    def test_subprocess_timeout_returns_500_with_timeout_error(self):
        client = self._client()
        with mock.patch.object(
            ad.subprocess, 'run',
            side_effect=subprocess.TimeoutExpired(cmd=['yt-dlp', '-U'], timeout=120),
        ), mock.patch.object(ad, '_probe_ytdlp_binary', return_value='2026.04.01'):
            resp = client.post("/update-ytdlp", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("exit_code"), -1)
        self.assertIn("timed out", body.get("error"))

    def test_cached_version_cannot_bypass_live_binary_probe(self):
        client = self._client()
        with mock.patch.object(ad, '_probe_ytdlp_binary', return_value=''), \
             mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.04.01'), \
             mock.patch.object(ad.subprocess, 'run') as run:
            resp = client.post('/update-ytdlp', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()['error_code'], 'active-version-unverified')
        run.assert_not_called()

    def test_post_activation_failure_restores_verified_backup(self):
        client = self._client()
        old_payload = b'old-ytdlp'
        new_payload = b'new-ytdlp'

        def probe(path, timeout=15):
            candidate = Path(path)
            payload = candidate.read_bytes() if candidate.exists() else b''
            if payload == old_payload:
                return '2026.04.01'
            if payload == new_payload and candidate.name.startswith('.yt-dlp.update.'):
                return '2026.05.10'
            # The same updated bytes fail only after activation at the live path.
            return ''

        def run_update(args, **_kwargs):
            Path(args[0]).write_bytes(new_payload)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='updated', stderr='')

        with mock.patch.object(ad, '_probe_ytdlp_binary', side_effect=probe), \
             mock.patch.object(ad.subprocess, 'run', side_effect=run_update):
            resp = client.post('/update-ytdlp', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body['ok'])
        self.assertTrue(body['rolled_back'])
        self.assertEqual(body['version_after'], '2026.04.01')
        self.assertEqual(body['rollback_version'], '2026.04.01')
        self.assertEqual(ad.YTDLP_PATH.read_bytes(), old_payload)
        state = ad.read_update_recovery_status()['ytDlp']
        self.assertEqual(state['status'], 'rolled-back')
        self.assertEqual(state['activeVersion'], '2026.04.01')

    def test_staged_version_failure_never_replaces_live_binary(self):
        client = self._client()

        def run_update(args, **_kwargs):
            Path(args[0]).write_bytes(b'broken-update')
            return subprocess.CompletedProcess(args=args, returncode=0, stdout='updated', stderr='')

        def probe(path, timeout=15):
            return '2026.04.01' if Path(path).read_bytes() == b'old-ytdlp' else ''

        with mock.patch.object(ad, '_probe_ytdlp_binary', side_effect=probe), \
             mock.patch.object(ad.subprocess, 'run', side_effect=run_update):
            resp = client.post('/update-ytdlp', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()['error_code'], 'staged-version-unverified')
        self.assertEqual(ad.YTDLP_PATH.read_bytes(), b'old-ytdlp')

    def test_shared_runner_returns_structured_dict(self):
        # _run_ytdlp_self_update is the shared subprocess runner used
        # by both the manual endpoint and the background auto-update
        # path. Asserting the exact key set keeps the wire schema
        # stable for the popup consumer.
        self._client()
        config = FakeConfig({"ServerToken": self.TOKEN, "LastYtDlpUpdateCheck": ""})
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr="",
        )
        with mock.patch.object(ad.subprocess, 'run', return_value=completed), \
             mock.patch.object(ad, '_probe_ytdlp_binary', return_value='2026.04.01'), \
             mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.04.01'):
            result = ad._run_ytdlp_self_update(config.data, source_tag='unit-test')

        for required in ('ok', 'exit_code', 'stdout', 'stderr',
                         'version_before', 'version_after', 'source'):
            self.assertIn(required, result,
                          f"_run_ytdlp_self_update result must carry {required!r}")
        self.assertEqual(result['source'], 'unit-test')

    def test_self_update_targets_configured_channel(self):
        # v1.5.5: the updater must switch/track the configured channel via
        # --update-to <channel>@latest instead of the old channel-locked -U.
        self._client()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        captured = {}

        def _capture(args, **kwargs):
            captured['args'] = list(args)
            return completed

        cases = (("nightly", "nightly@latest"), ("stable", "stable@latest"), (None, "nightly@latest"))
        for channel, expected in cases:
            with self.subTest(channel=channel):
                cfg = {"ServerToken": self.TOKEN, "LastYtDlpUpdateCheck": ""}
                if channel is not None:
                    cfg["YtDlpUpdateChannel"] = channel
                with mock.patch.object(ad.subprocess, 'run', side_effect=_capture), \
                        mock.patch.object(ad, '_probe_ytdlp_binary', return_value='2026.04.01'), \
                        mock.patch.object(ad, 'get_ytdlp_version', return_value='2026.04.01'):
                    ad._run_ytdlp_self_update(cfg, source_tag='unit-test')
                self.assertIn('--update-to', captured['args'])
                target = captured['args'][captured['args'].index('--update-to') + 1]
                self.assertEqual(target, expected)
                self.assertNotIn('-U', captured['args'])

    def test_config_defaults_and_clamps_update_channel(self):
        import config as _config
        self.assertEqual(_config.DEFAULT_CONFIG["YtDlpUpdateChannel"], "nightly")
        self.assertEqual(_config.sanitize_config({"YtDlpUpdateChannel": "stable"})["YtDlpUpdateChannel"], "stable")
        self.assertEqual(_config.sanitize_config({"YtDlpUpdateChannel": "bogus"})["YtDlpUpdateChannel"], "nightly")
        self.assertEqual(_config.sanitize_config({})["YtDlpUpdateChannel"], "nightly")

    def test_config_defaults_and_clamps_concurrency_and_retries(self):
        import config as _config
        self.assertEqual(_config.DEFAULT_CONFIG["MaxConcurrentDownloads"], 3)
        self.assertEqual(_config.DEFAULT_CONFIG["DownloadRetries"], 10)
        self.assertEqual(_config.sanitize_config({"MaxConcurrentDownloads": 99})["MaxConcurrentDownloads"], 10)
        self.assertEqual(_config.sanitize_config({"MaxConcurrentDownloads": 0})["MaxConcurrentDownloads"], 1)
        self.assertEqual(_config.sanitize_config({"DownloadRetries": -5})["DownloadRetries"], 0)
        self.assertEqual(_config.sanitize_config({"DownloadRetries": 999})["DownloadRetries"], 50)

    def test_clipboard_link_grabber_is_opt_in_and_boolean_sanitized(self):
        import config as _config
        self.assertFalse(_config.DEFAULT_CONFIG["ClipboardLinkGrabber"])
        self.assertFalse(_config.sanitize_config({})["ClipboardLinkGrabber"])
        self.assertTrue(
            _config.sanitize_config({"ClipboardLinkGrabber": "yes"})[
                "ClipboardLinkGrabber"
            ]
        )
        self.assertFalse(
            _config.sanitize_config({"ClipboardLinkGrabber": "invalid"})[
                "ClipboardLinkGrabber"
            ]
        )
        self.assertEqual(_config.DEFAULT_CONFIG["Language"], "system")
        self.assertEqual(_config.sanitize_config({"Language": "de"})["Language"], "de")
        self.assertEqual(
            _config.sanitize_config({"Language": "xx-YY"})["Language"],
            "system",
        )

    def test_normalize_output_template_allows_safe_and_rejects_unsafe(self):
        import config as _config
        n = _config.normalize_output_template
        # valid (free-text fields come back length-bounded)
        self.assertEqual(
            n("%(uploader)s/%(title)s.%(ext)s"),
            "%(uploader).100B/%(title).100B.%(ext)s",
        )
        self.assertEqual(n("%(title)s [%(id)s].%(ext)s"), "%(title).200B [%(id)s].%(ext)s")
        self.assertEqual(n("%(title)s.%(ext)s".replace("/", "\\")), "%(title).200B.%(ext)s")
        # empty -> ""
        self.assertEqual(n(""), "")
        self.assertEqual(n("   "), "")
        # missing %(ext)s -> rejected
        self.assertEqual(n("%(title)s"), "")
        # traversal / absolute -> rejected
        self.assertEqual(n("../%(title)s.%(ext)s"), "")
        self.assertEqual(n("/etc/%(title)s.%(ext)s"), "")
        self.assertEqual(n("C:/x/%(title)s.%(ext)s"), "")
        # non-allowlisted field -> rejected
        self.assertEqual(n("%(filepath)s.%(ext)s"), "")
        self.assertEqual(n("%(title)s.%(ext)s; rm -rf"), "")

    def test_normalize_output_template_rejects_broken_printf_syntax(self):
        # These passed the charset/field checks but made yt-dlp fail EVERY
        # download at startup with an opaque "Invalid output template".
        import config as _config
        n = _config.normalize_output_template
        self.assertEqual(n("%(title/%(ext)s"), "", "unclosed field must be rejected")
        self.assertEqual(n("50% %(title)s.%(ext)s"), "", "stray percent must be rejected")
        self.assertEqual(n("%(title)s.%(ext)"), "", "field without conversion must be rejected")
        # yt-dlp precision/padding conversions stay valid.
        self.assertEqual(n("%(title).200B.%(ext)s"), "%(title).200B.%(ext)s")
        self.assertEqual(n("%%/%(title)s.%(ext)s"), "%%/%(title).200B.%(ext)s",
                         "literal %% is valid printf")

    def test_normalize_output_template_bounds_free_text_expansions(self):
        # A custom template used to expand %(title)s unbounded, so a 200+
        # character title under a deep DownloadPath rendered past MAX_PATH and
        # failed with an opaque file error. Built-in templates bound their
        # fields; custom ones now get the same treatment.
        import config as _config
        n = _config.normalize_output_template
        # Budget is split across the free-text fields the template uses.
        self.assertEqual(n("%(title)s.%(ext)s"), "%(title).200B.%(ext)s")
        self.assertEqual(
            n("%(channel)s/%(playlist_title)s/%(title)s.%(ext)s"),
            "%(channel).66B/%(playlist_title).66B/%(title).66B.%(ext)s",
        )
        # Short/structured fields are left alone.
        self.assertEqual(
            n("%(upload_date)s-%(id)s-%(playlist_index)d.%(ext)s"),
            "%(upload_date)s-%(id)s-%(playlist_index)d.%(ext)s",
        )
        # An over-generous explicit bound is clamped; a tighter one is kept.
        self.assertEqual(n("%(title).500B.%(ext)s"), "%(title).200B.%(ext)s")
        # A user's explicit `.Ns` becomes `.NB`. The N is kept, but the unit is
        # not: the budget being split here is bytes, and a character precision
        # bounds nothing on a title made of four-byte characters.
        self.assertEqual(n("%(title).30s.%(ext)s"), "%(title).30B.%(ext)s")
        # A literal %% must never be treated as the start of an expansion.
        self.assertEqual(n("%%(title)s-%(id)s.%(ext)s"), "%%(title)s-%(id)s.%(ext)s")
        # Re-normalizing a saved template must not shrink it further.
        once = n("%(uploader)s/%(title)s.%(ext)s")
        self.assertEqual(n(once), once, "normalization must be idempotent")

    def test_manager_max_concurrent_reads_config(self):
        mgr = ad.DownloadManager(FakeConfig({"MaxConcurrentDownloads": 5}), FakeHistory())
        self.assertEqual(mgr._max_concurrent(), 5)
        self.assertEqual(mgr.capacity()["runningLimit"], 5)
        mgr2 = ad.DownloadManager(FakeConfig({"MaxConcurrentDownloads": 99}), FakeHistory())
        self.assertEqual(mgr2._max_concurrent(), 10, "clamped to the max")
        mgr3 = ad.DownloadManager(FakeConfig(), FakeHistory())
        self.assertEqual(mgr3._max_concurrent(), 3, "defaults to historical MAX_CONCURRENT")


class CompanionUpdateEndpointTests(unittest.TestCase):
    """v4.47.0 NF6 — on-demand Astra Downloader self-update via /update."""

    TOKEN = "v" * 32

    def _client(self, *, in_flight=0):
        probe_patch = mock.patch.object(ad, 'probe_companion_update_binary', return_value=True)
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        config = FakeConfig({"ServerToken": self.TOKEN})

        class _FakeManager:
            downloads = {}
            _lock = threading.Lock()

            def __init__(_self):
                # Sequence support: a list yields one value per active_count()
                # call (last value sticky) so tests can model downloads that
                # start during the update's download/verify window.
                _self._in_flight = (
                    list(in_flight) if isinstance(in_flight, (list, tuple))
                    else [in_flight]
                )
                _self.intake_paused = False
                _self.pause_calls = 0
                _self.resume_calls = 0
                _self.persisted_flags = []

            def active_count(_self):
                if len(_self._in_flight) > 1:
                    return _self._in_flight.pop(0)
                return _self._in_flight[0]

            def pause_intake(_self):
                _self.pause_calls += 1
                _self.intake_paused = True
                return True

            def resume_intake(_self):
                _self.resume_calls += 1
                _self.intake_paused = False
                return True

            def persist_intake_flag(_self, paused):
                _self.persisted_flags.append(bool(paused))
                return True

        manager = _FakeManager()
        self._manager = manager
        api = ad.create_api(config, manager, FakeHistory())
        return api.test_client()

    class _ReleaseResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _release_and_source(self, source_response, tag='v9.9.9'):
        """Return a fake http get that answers the release API then the source."""
        calls = []

        def get(url, *_args, **_kwargs):
            calls.append(url)
            if url == ad.COMPANION_UPDATE_RELEASE_API_URL:
                return self._ReleaseResponse({'tag_name': tag})
            return source_response
        return get, calls

    def test_parse_companion_release_tag_rejects_anything_but_a_release_tag(self):
        self.assertEqual(ad.parse_companion_release_tag({'tag_name': 'v4.50.7'}), 'v4.50.7')
        # Draft/prerelease builds are not installable updates.
        self.assertEqual(ad.parse_companion_release_tag({'tag_name': 'v1.0.0', 'draft': True}), '')
        self.assertEqual(ad.parse_companion_release_tag({'tag_name': 'v1.0.0', 'prerelease': True}), '')
        # The tag is interpolated into a URL, so its shape is enforced.
        for tag in ('main', '../../etc', 'v1.2', 'v1.2.3-rc1', ''):
            self.assertEqual(ad.parse_companion_release_tag({'tag_name': tag}), '', tag)
        self.assertEqual(ad.parse_companion_release_tag(None), '')

    def test_version_check_reads_the_tagged_release_not_a_branch(self):
        # A version bump on main with no published release must not advertise
        # an update: the binary can only come from a Release asset.
        response = self._VersionSourceResponse([b'APP_VERSION = "9.9.9"\n'])
        get, calls = self._release_and_source(response, tag='v9.9.9')
        with mock.patch.object(ad.http_requests, 'get', side_effect=get):
            self.assertEqual(ad.fetch_latest_companion_version(), '9.9.9')
        self.assertEqual(calls[0], ad.COMPANION_UPDATE_RELEASE_API_URL)
        self.assertEqual(
            calls[1],
            ad.COMPANION_UPDATE_VERSION_URL_TEMPLATE.format(tag='v9.9.9'),
        )
        self.assertNotIn('/main/', calls[1])

    def test_version_check_fails_closed_when_no_release_is_published(self):
        def get(url, *_args, **_kwargs):
            self.assertEqual(url, ad.COMPANION_UPDATE_RELEASE_API_URL)
            return self._ReleaseResponse({'tag_name': 'v1.0.0', 'draft': True})
        with mock.patch.object(ad.http_requests, 'get', side_effect=get):
            with self.assertRaisesRegex(RuntimeError, 'No published'):
                ad.fetch_latest_companion_version()

    def test_parse_companion_version_source_extracts_app_version(self):
        self.assertEqual(
            ad.parse_companion_version_source('APP_VERSION = "1.2.3"\n'),
            "1.2.3",
        )
        self.assertEqual(ad.parse_companion_version_source("no version"), "")

    class _VersionSourceResponse:
        def __init__(self, chunks, headers=None):
            self._chunks = list(chunks)
            self.headers = headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, _chunk_size):
            return iter(self._chunks)

    def test_version_source_fetch_is_streamed_and_size_limited(self):
        response = self._VersionSourceResponse([
            b'header\nAPP_VER', b'SION = "9.9.9"\n',
        ])
        get, _calls = self._release_and_source(response)
        with mock.patch.object(ad.http_requests, 'get', side_effect=get) as patched:
            self.assertEqual(ad.fetch_latest_companion_version(), '9.9.9')
        self.assertTrue(patched.call_args.kwargs['stream'])

        oversized = self._VersionSourceResponse([
            b'x' * (ad.COMPANION_VERSION_SOURCE_MAX_BYTES + 1),
        ])
        get, _calls = self._release_and_source(oversized)
        with mock.patch.object(ad.http_requests, 'get', side_effect=get):
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                ad.fetch_latest_companion_version()

    def test_version_source_rejects_oversized_content_length_without_reading(self):
        response = self._VersionSourceResponse(
            [b'APP_VERSION = "9.9.9"\n'],
            headers={
                'content-length': str(ad.COMPANION_VERSION_SOURCE_MAX_BYTES + 1),
            },
        )
        get, _calls = self._release_and_source(response)
        with mock.patch.object(ad.http_requests, 'get', side_effect=get):
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                ad.fetch_latest_companion_version()

    def test_unauthenticated_request_is_rejected(self):
        client = self._client()
        resp = client.post("/update")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("rejected", resp.get_json()["error"])

    def test_in_flight_downloads_block_companion_update_with_409(self):
        client = self._client(in_flight=3)
        resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("inFlight"), 3)
        self.assertIn("restart", body["error"])
        self.assertIn("atomically replacing", body["error"])

    def test_current_version_returns_200_without_download(self):
        client = self._client()
        with mock.patch.object(ad, 'fetch_latest_companion_version', return_value=ad.APP_VERSION), \
             mock.patch.object(ad, 'download_file_atomic') as download:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertFalse(body.get("update_available"))
        self.assertEqual(body.get("status"), "current")
        download.assert_not_called()

    def test_version_check_failure_returns_502(self):
        client = self._client()
        with mock.patch.object(ad, 'fetch_latest_companion_version', side_effect=RuntimeError("offline")), \
             mock.patch.object(ad, 'download_file_atomic') as download:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 502)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("error_code"), "version-check-failed")
        self.assertIn("Check Astra Downloader logs", body.get("error"))
        download.assert_not_called()

    def test_update_endpoint_rate_limits_repeated_release_checks(self):
        client = self._client()
        result = {
            'ok': True, 'update_available': False, 'status': 'current',
            'current_version': ad.APP_VERSION, 'latest_version': ad.APP_VERSION,
        }
        with mock.patch.object(ad, '_run_companion_self_update', return_value=result) as run_update:
            responses = [
                client.post('/update', headers={'X-Auth-Token': self.TOKEN})
                for _ in range(ad.RATE_LIMIT_UPDATE_MAX + 1)
            ]

        self.assertEqual([response.status_code for response in responses[:-1]], [200] * ad.RATE_LIMIT_UPDATE_MAX)
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(responses[-1].get_json()['error_code'], 'update-rate-limited')
        self.assertEqual(run_update.call_count, ad.RATE_LIMIT_UPDATE_MAX)

    def test_update_endpoint_backs_off_after_a_failed_attempt(self):
        client = self._client()
        failure = {
            'ok': False, 'error': 'offline', 'error_code': 'install-failed',
            'current_version': ad.APP_VERSION, 'latest_version': '',
        }
        with mock.patch.object(ad, '_run_companion_self_update', return_value=failure) as run_update:
            first = client.post('/update', headers={'X-Auth-Token': self.TOKEN})
            second = client.post('/update', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(first.status_code, 500)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()['error_code'], 'update-backoff')
        self.assertGreaterEqual(
            int(second.headers['Retry-After']),
            ad.COMPANION_UPDATE_FAILURE_BACKOFF_SECONDS,
        )
        run_update.assert_called_once()

    def test_concurrent_companion_update_is_rejected_before_network_work(self):
        client = self._client()
        self.assertTrue(ad._COMPANION_UPDATE_LOCK.acquire(blocking=False))
        try:
            with mock.patch.object(ad, 'fetch_latest_companion_version') as fetch:
                resp = client.post('/update', headers={'X-Auth-Token': self.TOKEN})
        finally:
            ad._COMPANION_UPDATE_LOCK.release()

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()['error_code'], 'update-in-progress')
        fetch.assert_not_called()

    def test_successful_companion_update_schedules_replace_and_restart(self):
        client = self._client()
        payload = b"MZ" + (b"\0" * ad.COMPANION_UPDATE_MIN_BYTES)
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart',
                               return_value={'scheduled': True, 'target': str(Path(tmp) / "AstraDownloader.exe")}) as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("update_available"))
        self.assertEqual(body.get("status"), "restart_scheduled")
        self.assertEqual(body.get("current_version"), ad.APP_VERSION)
        self.assertEqual(body.get("latest_version"), "9.9.9")
        schedule.assert_called_once()
        exit_later.assert_called_once()

    def test_failed_schedule_records_terminal_activation_state(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value='9.9.9'), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart', side_effect=RuntimeError('helper refused')), \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            response = client.post('/update', headers={'X-Auth-Token': self.TOKEN})
            state = ad._read_update_state(ad._companion_update_state_path())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()['error_code'], 'schedule-failed')
        self.assertEqual(state['status'], 'activation-failed')
        self.assertEqual(state['error_code'], 'schedule-failed')
        self.assertEqual(state['active_version'], ad.APP_VERSION)
        self.assertTrue(state['updated_at'].endswith('Z'))
        exit_later.assert_not_called()

    def test_download_started_during_update_window_aborts_restart_with_409(self):
        # TOCTOU regression: the route checks active_count() once at entry,
        # but the exe download + SHA fetch + staged probe can take minutes.
        # A /download accepted on another waitress thread in that window must
        # abort the restart (os._exit would orphan its yt-dlp tree). The
        # in_flight sequence models exactly that: 0 at route entry, 2 at the
        # pre-restart re-check.
        client = self._client(in_flight=[0, 2])
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(
                 ad, 'schedule_companion_update_restart',
                 return_value={'scheduled': True, 'target': 'AstraDownloader.exe'},
             ) as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
            leftovers = list(Path(tmp).glob("*.exe"))

        self.assertEqual(resp.status_code, 409)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertEqual(body.get("error_code"), "downloads-in-flight")
        self.assertEqual(body.get("inFlight"), 2)
        self.assertIn("in flight", body.get("error", ""))
        schedule.assert_not_called()
        exit_later.assert_not_called()
        self.assertEqual(leftovers, [], "aborted update must unlink the staged exe")
        # Intake was paused for the update window and resumed on abort.
        self.assertEqual(self._manager.pause_calls, 1)
        self.assertEqual(self._manager.resume_calls, 1)
        self.assertFalse(self._manager.intake_paused)

    def test_update_pauses_intake_and_persists_prior_flag_on_restart(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart',
                               return_value={'scheduled': True, 'target': str(Path(tmp) / "AstraDownloader.exe")}), \
             mock.patch.object(ad, 'schedule_companion_process_exit'):
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json().get("status"), "restart_scheduled")
        self.assertEqual(self._manager.pause_calls, 1)
        # The dying process must keep the live pause (nothing may spawn
        # yt-dlp between the re-check and os._exit) ...
        self.assertEqual(self._manager.resume_calls, 0)
        self.assertTrue(self._manager.intake_paused)
        # ... while the relaunched companion gets the user's pre-update flag.
        self.assertEqual(self._manager.persisted_flags, [False])

    def test_failed_update_resumes_intake(self):
        client = self._client()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(b"MZ" + (b"\0" * ad.COMPANION_UPDATE_MIN_BYTES))

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=None):
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(self._manager.pause_calls, 1)
        self.assertEqual(self._manager.resume_calls, 1)
        self.assertFalse(self._manager.intake_paused)
        self.assertEqual(self._manager.persisted_flags, [])

    def test_update_does_not_touch_a_user_paused_intake(self):
        client = self._client()
        self._manager.intake_paused = True
        with mock.patch.object(ad, 'fetch_latest_companion_version', return_value=ad.APP_VERSION):
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._manager.pause_calls, 0)
        self.assertEqual(self._manager.resume_calls, 0)
        self.assertTrue(self._manager.intake_paused)

    def test_companion_update_requires_sha256_sidecar(self):
        client = self._client()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(b"MZ" + (b"\0" * ad.COMPANION_UPDATE_MIN_BYTES))

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=None), \
             mock.patch.object(ad, 'schedule_companion_update_restart') as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("SHA-256 sidecar", body.get("error", ""))
        schedule.assert_not_called()
        exit_later.assert_not_called()

    def test_companion_update_rejects_sha256_mismatch(self):
        """When the SHA-256 sidecar is reachable but doesn't match, the
        update must fail before scheduling a replace."""
        client = self._client()
        fake_hash = "a" * 64

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(b"MZ" + (b"\0" * ad.COMPANION_UPDATE_MIN_BYTES))

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=fake_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart') as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        body = resp.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("SHA-256", body.get("error", ""))
        schedule.assert_not_called()
        exit_later.assert_not_called()

    def test_companion_update_rejects_failed_staged_startup_probe(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value='9.9.9'), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'probe_companion_update_binary', return_value=False), \
             mock.patch.object(ad, 'schedule_companion_update_restart') as schedule:
            resp = client.post('/update', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()['error_code'], 'staged-health-check-failed')
        schedule.assert_not_called()

    def test_companion_probe_cli_is_non_gui_and_version_strict(self):
        self.assertEqual(ad.companion_probe_exit_code(['--version']), 0)
        self.assertEqual(
            ad.companion_probe_exit_code(['--update-health-check', ad.APP_VERSION]), 0,
        )
        self.assertEqual(ad.companion_probe_exit_code(['--update-health-check', '9.9.9']), 3)
        self.assertEqual(ad.companion_probe_exit_code(['--update-health-check']), 2)
        self.assertIsNone(ad.companion_probe_exit_code(['--start-server']))

    def test_windowed_build_health_probe_does_not_require_stdout_or_qapplication(self):
        with mock.patch.object(ad.sys, 'argv', ['AstraDownloader.exe', '--update-health-check', ad.APP_VERSION]), \
             mock.patch.object(ad.sys, 'stdout', None), \
             mock.patch.object(ad, 'QApplication') as application:
            ad.main()
        application.assert_not_called()

    def test_windows_update_helper_contains_verified_backup_and_rollback_contract(self):
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad.sys, 'platform', 'win32'):
            root = Path(tmp)
            update = root / '.AstraDownloader.update.abc.exe'
            target = root / 'AstraDownloader.exe'
            update.write_bytes(payload)
            target.write_bytes(self._fake_payload(b'B'))
            with mock.patch.object(ad.subprocess, 'Popen') as popen:
                result = ad.schedule_companion_update_restart(
                    update, target, ['--start-server'], pid=123,
                    expected_sha256=expected_hash,
                    expected_version='9.9.9', previous_version=ad.APP_VERSION,
                )
                helper_args = popen.call_args.args[0]
            scripts = list(root.glob('.AstraDownloader.apply-update.*.ps1'))
            self.assertEqual(len(scripts), 1)
            helper_source = scripts[0].read_text(encoding='utf-8')
            if os.name == 'nt':
                escaped_script_path = str(scripts[0]).replace("'", "''")
                parser_command = (
                    "$tokens=$null; $errors=$null; "
                    f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped_script_path}', "
                    "[ref]$tokens, [ref]$errors) | Out-Null; "
                    "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
                )
                parsed = subprocess.run(
                    ['powershell', '-NoProfile', '-Command', parser_command],
                    capture_output=True, text=True, timeout=15,
                    creationflags=ad.CREATE_NO_WINDOW,
                )
                self.assertEqual(parsed.returncode, 0, parsed.stderr)

        self.assertTrue(result['scheduled'])
        self.assertEqual(result['rollback_version'], ad.APP_VERSION)
        self.assertIn('Copy-Verified $TargetPath $BackupPath', helper_source)
        self.assertIn("Write-RecoveryState 'rolled-back'", helper_source)
        self.assertIn("'--update-health-check'", helper_source)
        self.assertIn('-WindowStyle Hidden', helper_source)
        self.assertIn('Wait-Process -Id $probe.Id -Timeout 30', helper_source)
        self.assertIn('$probeFinished = $probe.HasExited', helper_source)
        self.assertIn('$probe.Refresh()\n        if ($probe.HasExited)', helper_source)
        self.assertIn('Get-Process -Id $probe.Id -ErrorAction SilentlyContinue', helper_source)
        self.assertIn('Stop-Process -Id $probe.Id -Force', helper_source)
        self.assertIn('$MOVEFILE_WRITE_THROUGH = 0x8', helper_source)
        self.assertIn('$stream.Flush($true)', helper_source)
        self.assertIn("if ($Status -eq 'active')", helper_source)
        self.assertNotIn('-Wait -PassThru', helper_source)
        self.assertIn('-BackupPath', helper_args)

    def test_update_recovery_health_state_omits_paths_and_digests(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)):
            ad._write_update_state(
                ad._companion_update_state_path(), status='active',
                active_version='9.9.9', rollback_version=ad.APP_VERSION,
                active_sha256='a' * 64, source_path='C:/Users/secret/update.exe',
            )
            public = ad.read_update_recovery_status()['companion']
        self.assertEqual(public['activeVersion'], '9.9.9')
        self.assertEqual(public['rollbackVersion'], ad.APP_VERSION)
        self.assertNotIn('active_sha256', public)
        self.assertNotIn('source_path', public)

    def test_stale_companion_activation_marker_is_reconciled_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'write_persistent_log') as log:
            stale = datetime.now() - timedelta(
                seconds=ad.COMPANION_UPDATE_TIMEOUT_SECONDS + 1
            )
            state_path = ad._companion_update_state_path()
            state_path.write_text(json.dumps({
                'status': 'activation-pending',
                'active_version': ad.APP_VERSION,
                'rollback_version': '2.4.0',
                'updated_at': stale.strftime('%Y-%m-%d %H:%M:%S'),
            }), encoding='utf-8')
            state = ad._reconcile_stale_companion_activation()
            public = ad.read_update_recovery_status()['companion']

        self.assertEqual(state['status'], 'activation-failed')
        self.assertEqual(state['error_code'], 'activation-timeout')
        self.assertEqual(public['status'], 'activation-failed')
        self.assertEqual(public['errorCode'], 'activation-timeout')
        log.assert_called_once()

    def test_fresh_companion_activation_marker_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)):
            ad._write_update_state(
                ad._companion_update_state_path(),
                status='activation-pending',
                active_version=ad.APP_VERSION,
                rollback_version='2.4.0',
            )
            state = ad._reconcile_stale_companion_activation()

        self.assertEqual(state['status'], 'activation-pending')
        self.assertTrue(state['updated_at'].endswith('Z'))

    def test_startup_sweep_removes_single_and_double_dot_update_scratch(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)):
            root = Path(tmp)
            stale = {
                '.AstraDownloader.update.old.exe',
                '..AstraDownloader.update.old.exe.123.download',
                '.AstraDownloader.apply-update.old.ps1',
                '.yt-dlp.update.old.exe',
                '..yt-dlp.update.old.exe.456.download',
            }
            retained = {
                'AstraDownloader.exe',
                '.AstraDownloader.last-known-good.exe',
                'notes.txt',
            }
            for name in stale | retained:
                (root / name).write_bytes(b'placeholder')

            self.assertEqual(ad.cleanup_update_scratch_files(), len(stale))
            self.assertEqual({path.name for path in root.iterdir()}, retained)

    # ── Audit fix: version-skew reinstall-loop guard ──
    # main's APP_VERSION can be bumped before the release asset exists; in
    # that window releases/latest serves the binary already installed. The
    # guard compares the asset digest against the last scheduled update (and
    # the running frozen binary) and refuses to re-schedule a no-op replace.

    @staticmethod
    def _fake_payload(tag=b"A"):
        return b"MZ" + tag + (b"\0" * ad.COMPANION_UPDATE_MIN_BYTES)

    def test_same_asset_as_last_installed_update_is_not_rescheduled(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart') as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            # State file says: this exact digest was already installed.
            ad.record_last_installed_update_sha256(expected_hash)
            resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
            leftovers = list(Path(tmp).glob(".AstraDownloader.update.*.exe"))

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertFalse(body.get("update_available"),
            "re-serving the already-installed asset must not loop the update")
        self.assertEqual(body.get("status"), "release-pending")
        self.assertEqual(body.get("latest_version"), "9.9.9")
        schedule.assert_not_called()
        exit_later.assert_not_called()
        self.assertEqual(leftovers, [],
            "the downloaded duplicate asset must be deleted")

    def test_asset_matching_running_frozen_binary_is_not_rescheduled(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(ad, 'schedule_companion_update_restart') as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later, \
             mock.patch.object(ad, 'is_frozen_app', return_value=True):
            # Simulate the running frozen exe being byte-identical to the
            # releases/latest asset. No state file exists — the running-binary
            # digest alone must stop the loop.
            running = Path(tmp) / "AstraDownloader.exe"
            running.write_bytes(payload)
            with mock.patch.object(ad, 'current_executable_path', return_value=running):
                resp = client.post("/update", headers={"X-Auth-Token": self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body.get("ok"))
        self.assertFalse(body.get("update_available"))
        self.assertEqual(body.get("status"), "release-pending")
        schedule.assert_not_called()
        exit_later.assert_not_called()

    def test_successful_update_records_digest_and_newer_release_installs(self):
        client = self._client()
        payload_a = self._fake_payload(b"A")
        payload_b = self._fake_payload(b"B")
        hash_a = hashlib.sha256(payload_a).hexdigest()
        hash_b = hashlib.sha256(payload_b).hexdigest()
        serving = {'payload': payload_a, 'hash': hash_a}

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(serving['payload'])

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value="9.9.9"), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256',
                               side_effect=lambda *a, **k: serving['hash']), \
             mock.patch.object(ad, 'schedule_companion_update_restart',
                               return_value={'scheduled': True,
                                             'target': str(Path(tmp) / "AstraDownloader.exe")}) as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit'):
            # First cycle: release A is only scheduled. The detached helper is
            # the authority that records a digest after activation succeeds.
            resp_a = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
            self.assertEqual(resp_a.status_code, 200)
            self.assertTrue(resp_a.get_json().get("update_available"))
            self.assertEqual(schedule.call_count, 1)
            self.assertIsNone(ad.read_last_installed_update_sha256(),
                "a scheduled update must not suppress retries before activation")
            pending_state = ad._read_update_state(ad._companion_update_state_path())
            self.assertEqual(pending_state.get("status"), "activation-pending")
            self.assertEqual(pending_state.get("sha256"), hash_a)

            ad._write_update_state(
                ad._companion_update_state_path(), status='active',
                active_version='9.9.9', rollback_version=ad.APP_VERSION,
                sha256=hash_a,
            )
            self.assertEqual(ad.read_last_installed_update_sha256(), hash_a)

            # Same release served again: refused (no reinstall loop).
            resp_repeat = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
            self.assertEqual(resp_repeat.get_json().get("status"), "release-pending")
            self.assertEqual(schedule.call_count, 1)

            # A genuinely newer release (different bytes): installs normally.
            serving['payload'], serving['hash'] = payload_b, hash_b
            resp_b = client.post("/update", headers={"X-Auth-Token": self.TOKEN})
            self.assertEqual(resp_b.status_code, 200)
            self.assertTrue(resp_b.get_json().get("update_available"))
            self.assertEqual(schedule.call_count, 2)
            self.assertIsNone(ad.read_last_installed_update_sha256(),
                "a new scheduled digest must wait for the detached helper to activate")

            ad._write_update_state(
                ad._companion_update_state_path(), status='active',
                active_version='9.9.9', rollback_version=ad.APP_VERSION,
                sha256=hash_b,
            )
            self.assertEqual(ad.read_last_installed_update_sha256(), hash_b)

    def test_failed_activation_state_does_not_suppress_retry(self):
        client = self._client()
        payload = self._fake_payload()
        expected_hash = hashlib.sha256(payload).hexdigest()

        def fake_download(_url, path, **_kwargs):
            Path(path).write_bytes(payload)

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)), \
             mock.patch.object(ad, 'fetch_latest_companion_version', return_value='9.9.9'), \
             mock.patch.object(ad, 'download_file_atomic', side_effect=fake_download), \
             mock.patch.object(ad, 'fetch_expected_sha256', return_value=expected_hash), \
             mock.patch.object(
                 ad, 'schedule_companion_update_restart',
                 return_value={'scheduled': True, 'target': 'AstraDownloader.exe'},
             ) as schedule, \
             mock.patch.object(ad, 'schedule_companion_process_exit') as exit_later:
            ad._write_update_state(
                ad._companion_update_state_path(),
                status='activation-failed', active_version=ad.APP_VERSION,
                rollback_version=ad.APP_VERSION, sha256=expected_hash,
                error_code='staged-health-failed',
            )
            resp = client.post('/update', headers={'X-Auth-Token': self.TOKEN})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get('update_available'))
        self.assertEqual(resp.get_json().get('status'), 'restart_scheduled')
        schedule.assert_called_once()
        exit_later.assert_called_once()

    def test_update_state_helpers_tolerate_missing_and_garbage_state(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, 'INSTALL_DIR', Path(tmp)):
            # No state file yet.
            self.assertIsNone(ad.read_last_installed_update_sha256())
            # Garbage / wrong-shape contents must read as None, not raise.
            state = Path(tmp) / "companion-update-state.json"
            for garbage in (b"not json", b"[]", b'{"sha256": 42}',
                            b'{"sha256": "nothex"}'):
                state.write_bytes(garbage)
                self.assertIsNone(ad.read_last_installed_update_sha256())
            # Round trip normalizes to lowercase hex.
            digest = "A" * 64
            ad.record_last_installed_update_sha256(digest)
            self.assertEqual(ad.read_last_installed_update_sha256(), "a" * 64)

            state.write_text(json.dumps({
                'status': 'activation-failed', 'sha256': 'b' * 64,
            }), encoding='utf-8')
            self.assertIsNone(ad.read_last_installed_update_sha256())
            state.write_text(json.dumps({
                'status': 'active', 'sha256': 'b' * 64,
            }), encoding='utf-8')
            self.assertEqual(ad.read_last_installed_update_sha256(), 'b' * 64)


class NativeChromePairingUiTests(unittest.TestCase):
    """The Extension page's Chrome/Edge ID field (AD-47)."""

    class _Config(FakeConfig):
        def update(self, values):
            self.data.update(values)
            return True

    class _TextWidget:
        def __init__(self, value=""):
            self.value = value
            self.visible = False
            self.properties = {}

        def setText(self, value):
            self.value = value

        def text(self):
            return self.value

        def setProperty(self, key, value):
            self.properties[key] = value

        def show(self):
            self.visible = True

    def _window(self, config, *, refresh_result=True):
        window = types.SimpleNamespace()
        window.config = config
        window.logs = []
        window._append_log = window.logs.append
        window.refresh_calls = []
        window.cfg_native_chrome_ids = self._TextWidget()
        window.native_pairing_status = self._TextWidget()
        window._dependencies = {
            "parse_native_extension_ids": ad.parse_native_extension_ids,
            "refresh_native_messaging_registration": lambda: (
                window.refresh_calls.append(True) or refresh_result
            ),
        }
        gui = gui_module_for_tests()
        for name in ("_apply_native_chrome_ids", "_show_native_pairing_status"):
            setattr(window, name, types.MethodType(
                getattr(gui.MainWindowCore, name), window))
        return window

    def test_a_valid_id_is_saved_normalized_and_registration_reruns(self):
        config = self._Config({"NativeChromeExtensionIds": ""})
        window = self._window(config)
        window.cfg_native_chrome_ids.setText("  ABCDEFGHIJKLMNOPABCDEFGHIJKLMNOP  ")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_native_chrome_ids()
        self.assertEqual(
            config.get("NativeChromeExtensionIds"),
            "abcdefghijklmnopabcdefghijklmnop",
        )
        self.assertEqual(window.refresh_calls, [True])
        self.assertEqual(window.native_pairing_status.properties["tone"], "success")
        self.assertEqual(
            window.cfg_native_chrome_ids.text(),
            "abcdefghijklmnopabcdefghijklmnop",
            "the field shows the normalized value that was saved",
        )

    def test_an_invalid_id_is_refused_before_any_save_or_registration(self):
        config = self._Config({"NativeChromeExtensionIds": ""})
        window = self._window(config)
        window.cfg_native_chrome_ids.setText("not-a-chrome-id!")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_native_chrome_ids()
        self.assertEqual(config.get("NativeChromeExtensionIds"), "")
        self.assertEqual(window.refresh_calls, [])
        self.assertEqual(window.native_pairing_status.properties["tone"], "danger")
        self.assertIn("chrome://extensions", window.native_pairing_status.text())

    def test_clearing_the_field_revokes_and_reports_neutral(self):
        config = self._Config({
            "NativeChromeExtensionIds": "abcdefghijklmnopabcdefghijklmnop",
        })
        window = self._window(config)
        window.cfg_native_chrome_ids.setText("")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_native_chrome_ids()
        self.assertEqual(config.get("NativeChromeExtensionIds"), "")
        self.assertEqual(window.refresh_calls, [True])
        self.assertEqual(window.native_pairing_status.properties["tone"], "neutral")

    def test_a_copy_that_cannot_register_reports_the_warning(self):
        config = self._Config({"NativeChromeExtensionIds": ""})
        window = self._window(config, refresh_result=False)
        window.cfg_native_chrome_ids.setText("abcdefghijklmnopabcdefghijklmnop")
        with mock.patch.object(gui_module_for_tests(), "repolish"):
            window._apply_native_chrome_ids()
        self.assertEqual(
            config.get("NativeChromeExtensionIds"),
            "abcdefghijklmnopabcdefghijklmnop",
        )
        self.assertEqual(window.native_pairing_status.properties["tone"], "warning")


class NativeMessagingBootstrapTests(unittest.TestCase):
    """Token bootstrap over the browser-pinned native-messaging stdio channel."""

    def test_message_framing_round_trips(self):
        buf = io.BytesIO()
        ad.write_native_message(buf, {"type": "get-token", "n": 1})
        buf.seek(0)
        self.assertEqual(ad.read_native_message(buf), {"type": "get-token", "n": 1})
        # A second read at EOF returns None (clean pipe close), not an error.
        self.assertIsNone(ad.read_native_message(buf))

    def test_read_rejects_oversized_length_prefix(self):
        buf = io.BytesIO(struct.pack('<I', ad.NATIVE_MESSAGE_MAX_BYTES + 1) + b'{}')
        with self.assertRaises(ValueError):
            ad.read_native_message(buf)

    def test_handler_returns_token_only_for_get_token(self):
        ok = ad.handle_native_bootstrap_request({"type": "get-token"}, "tok-123")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["token"], "tok-123")
        self.assertEqual(ok["service"], ad.SERVICE_ID)

        ping = ad.handle_native_bootstrap_request({"type": "ping"}, "tok-123")
        self.assertTrue(ping["ok"])
        self.assertNotIn("token", ping)

    def test_handler_rejects_unknown_and_malformed_requests(self):
        for bad in ({"type": "evil"}, {}, "not-a-dict", 42, None):
            resp = ad.handle_native_bootstrap_request(bad, "tok")
            self.assertFalse(resp["ok"])
            self.assertNotIn("token", resp)

    def test_handler_withholds_token_when_unconfigured(self):
        resp = ad.handle_native_bootstrap_request({"type": "get-token"}, "")
        self.assertFalse(resp["ok"])
        self.assertNotIn("token", resp)

    def test_run_host_serves_then_exits_on_eof(self):
        request = io.BytesIO()
        ad.write_native_message(request, {"type": "get-token"})
        request.seek(0)
        out = io.BytesIO()
        ad.run_native_messaging_host("tok-xyz", stdin=request, stdout=out)
        out.seek(0)
        reply = ad.read_native_message(out)
        self.assertEqual(reply["token"], "tok-xyz")

    def test_argv_gate_matches_chrome_origins_and_registered_firefox_manifest(self):
        self.assertTrue(ad.argv_requests_native_host(["chrome-extension://abc/", "--parent-window=9"]))
        self.assertTrue(ad.argv_requests_native_host(["--native-host"]))
        self.assertTrue(ad.argv_requests_native_host(["-native-host", "chrome-extension://abc/"]))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp)):
            manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.firefox.json"
            manifest.write_text(
                json.dumps(ad.build_native_host_manifest(
                    "C:/AstraDownloader.exe",
                    ["ytkit@sysadmindoc.github.io"],
                    browser="firefox",
                )),
                encoding="utf-8",
            )
            self.assertTrue(
                ad.argv_requests_native_host([
                    str(manifest),
                    "ytkit@sysadmindoc.github.io",
                ])
            )
            self.assertFalse(ad.argv_requests_native_host([str(manifest), "other@example.test"]))

        for normal in (["-Background"], ["--uninstall"], [], ["start"]):
            self.assertFalse(ad.argv_requests_native_host(normal))

    def test_main_handles_firefox_shape_before_gui_or_single_instance(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp)):
            manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.firefox.json"
            manifest.write_text(
                json.dumps(ad.build_native_host_manifest(
                    "C:/AstraDownloader.exe",
                    ["ytkit@sysadmindoc.github.io"],
                    browser="firefox",
                )),
                encoding="utf-8",
            )
            with mock.patch.object(ad.sys, "argv", [
                "AstraDownloader.exe",
                str(manifest),
                "ytkit@sysadmindoc.github.io",
            ]), \
                 mock.patch.object(ad, "Config", return_value=FakeConfig({"ServerToken": "tok"})), \
                 mock.patch.object(ad, "run_native_messaging_host") as run_host, \
                 mock.patch.object(ad, "QApplication") as application, \
                 mock.patch.object(ad, "check_single_instance") as single_instance:
                ad.main()

            run_host.assert_called_once_with("tok")
            application.assert_not_called()
            single_instance.assert_not_called()

    def test_main_native_host_reads_config_without_rewriting_it(self):
        token = "t" * 32
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "AstraDownloader"
            install_dir.mkdir()
            config_path = install_dir / "config.json"
            original_bytes = json.dumps(
                {"ServerToken": token}, separators=(",", ":")
            ).encode("utf-8")
            config_path.write_bytes(original_bytes)
            before = config_path.stat()

            with mock.patch.object(ad, "INSTALL_DIR", install_dir), \
                 mock.patch.object(ad, "CONFIG_PATH", config_path), \
                 mock.patch.object(ad.sys, "argv", [
                     "AstraDownloader.exe", "chrome-extension://abc/",
                 ]), \
                 mock.patch.object(ad, "run_native_messaging_host") as run_host:
                ad.main()

            after = config_path.stat()
            after_bytes = config_path.read_bytes()

        run_host.assert_called_once_with(token)
        self.assertEqual(after_bytes, original_bytes)
        self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)

    def test_parse_native_extension_ids_dedupes_comma_semicolon_and_lines(self):
        self.assertEqual(
            ad.parse_native_extension_ids(" aaa,bbb; aaa\nccc "),
            ["aaa", "bbb", "ccc"],
        )
        self.assertEqual(ad.parse_native_extension_ids("", fallback=("fallback",)), ["fallback"])

    def test_host_manifest_pins_allowed_extension_origins(self):
        chrome_a = "a" * 32
        chrome_b = "b" * 32
        m = ad.build_native_host_manifest(
            "C:/x/AstraDownloader.exe", [chrome_a, chrome_b], browser="chrome"
        )
        self.assertEqual(m["name"], ad.NATIVE_HOST_NAME)
        self.assertEqual(m["type"], "stdio")
        self.assertEqual(
            m["allowed_origins"],
            [f"chrome-extension://{chrome_a}/", f"chrome-extension://{chrome_b}/"],
        )
        self.assertNotIn("allowed_extensions", m)

    def test_native_manifest_filters_invalid_browser_ids(self):
        self.assertEqual(
            ad.parse_native_extension_ids(
                "short " + ("c" * 32) + " " + ("d" * 32), browser="chrome"
            ),
            ["c" * 32, "d" * 32],
        )
        manifest = ad.build_native_host_manifest(
            "C:/x/AstraDownloader.exe",
            ["not an id", "chrome-extension://evil", "e" * 32],
            browser="chrome",
        )
        self.assertEqual(manifest["allowed_origins"], [
            "chrome-extension://" + ("e" * 32) + "/",
        ])
        self.assertFalse(ad.is_valid_native_extension_id("../escape", "firefox"))

    def test_firefox_host_manifest_pins_allowed_extension_ids(self):
        m = ad.build_native_host_manifest(
            "C:/x/AstraDownloader.exe",
            ["ytkit@sysadmindoc.github.io"],
            browser="firefox",
        )
        self.assertEqual(m["name"], ad.NATIVE_HOST_NAME)
        self.assertEqual(m["type"], "stdio")
        self.assertEqual(m["allowed_extensions"], ["ytkit@sysadmindoc.github.io"])
        self.assertNotIn("allowed_origins", m)

    def test_register_native_messaging_hosts_writes_browser_manifests(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp)), \
             mock.patch.object(ad.sys, "platform", "win32"), \
             mock.patch.object(ad, "register_native_host_registry_value") as reg:
            config = FakeConfig({
                "NativeChromeExtensionIds": "a" * 32,
                "NativeFirefoxExtensionIds": "ytkit@sysadmindoc.github.io",
            })

            ad.register_native_messaging_hosts("C:/AstraDownloader.exe", [], config)

            chrome_manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.chrome.json"
            firefox_manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.firefox.json"
            self.assertTrue(chrome_manifest.exists())
            self.assertTrue(firefox_manifest.exists())
            self.assertEqual(
                json.loads(chrome_manifest.read_text(encoding="utf-8"))["allowed_origins"],
                ["chrome-extension://" + ("a" * 32) + "/"],
            )
            self.assertEqual(
                json.loads(firefox_manifest.read_text(encoding="utf-8"))["allowed_extensions"],
                ["ytkit@sysadmindoc.github.io"],
            )
            registry_keys = [call.args[0] for call in reg.call_args_list]
            for root in ad.CHROMIUM_NATIVE_MESSAGING_REGISTRY_ROOTS:
                self.assertIn(f"{root}\\{ad.NATIVE_HOST_NAME}", registry_keys)
            self.assertIn(
                f"{ad.FIREFOX_NATIVE_MESSAGING_REGISTRY_ROOT}\\{ad.NATIVE_HOST_NAME}",
                registry_keys,
            )

    def test_register_native_messaging_hosts_revokes_cleared_allowlists(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp)), \
             mock.patch.object(ad.sys, "platform", "win32"), \
             mock.patch.object(ad, "unregister_native_host_registry_value") as revoke:
            chrome_manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.chrome.json"
            firefox_manifest = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.firefox.json"
            chrome_manifest.write_text("stale", encoding="utf-8")
            firefox_manifest.write_text("stale", encoding="utf-8")
            config = FakeConfig({
                "NativeChromeExtensionIds": "",
                "NativeFirefoxExtensionIds": "",
            })

            ad.register_native_messaging_hosts("C:/AstraDownloader.exe", [], config)

            self.assertFalse(chrome_manifest.exists())
            self.assertFalse(firefox_manifest.exists())
            revoked = [call.args[0] for call in revoke.call_args_list]
            for root in ad.CHROMIUM_NATIVE_MESSAGING_REGISTRY_ROOTS:
                self.assertIn(f"{root}\\{ad.NATIVE_HOST_NAME}", revoked)
            self.assertIn(
                f"{ad.FIREFOX_NATIVE_MESSAGING_REGISTRY_ROOT}\\{ad.NATIVE_HOST_NAME}",
                revoked,
            )

    def test_source_registration_writes_a_cmd_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ad, "NATIVE_HOST_DIR", Path(tmp)), \
             mock.patch.object(ad.sys, "platform", "win32"), \
             mock.patch.object(ad, "register_native_host_registry_value"):
            config = FakeConfig({
                "NativeChromeExtensionIds": "a" * 32,
                "NativeFirefoxExtensionIds": "ytkit@sysadmindoc.github.io",
            })
            script = str(Path(ad.__file__).resolve())
            ad.register_native_messaging_hosts(sys.executable, [script], config)
            launcher = Path(tmp) / f"{ad.NATIVE_HOST_NAME}.cmd"
            self.assertTrue(launcher.is_file())
            body = launcher.read_text(encoding="utf-8")
            self.assertIn("--native-host", body)
            chrome_manifest = json.loads(
                (Path(tmp) / f"{ad.NATIVE_HOST_NAME}.chrome.json").read_text(encoding="utf-8")
            )
            self.assertEqual(Path(chrome_manifest["path"]), launcher)


class ExtensionPairingTests(unittest.TestCase):
    """Loopback pairing so Astra Deck can register its Chrome ID itself."""

    def test_pair_persists_a_chrome_id_bound_to_origin(self):
        chrome_id = "abcdefghijklmnopabcdefghijklmnop"
        config = FakeConfig({"NativeChromeExtensionIds": ""})
        refresh = mock.Mock(return_value=True)
        result = ad.pair_browser_extension(
            config,
            f"chrome-extension://{chrome_id}",
            chrome_id,
            refresh=refresh,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["paired"])
        self.assertFalse(result["alreadyPaired"])
        self.assertNotIn("token", result)
        self.assertEqual(config.get("NativeChromeExtensionIds"), chrome_id)
        refresh.assert_called_once_with()

    def test_pair_rejects_mismatched_chrome_id_and_youtube_origin(self):
        chrome_id = "abcdefghijklmnopabcdefghijklmnop"
        config = FakeConfig({"NativeChromeExtensionIds": ""})
        refresh = mock.Mock(return_value=True)
        mismatch = ad.pair_browser_extension(
            config,
            f"chrome-extension://{chrome_id}",
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            refresh=refresh,
        )
        self.assertEqual(mismatch["code"], "id-mismatch")
        web = ad.pair_browser_extension(
            config,
            "https://www.youtube.com",
            chrome_id,
            refresh=refresh,
        )
        self.assertEqual(web["code"], "invalid-origin")
        self.assertEqual(config.get("NativeChromeExtensionIds"), "")
        refresh.assert_not_called()

    def test_pair_route_registers_chrome_id_without_echoing_the_token(self):
        chrome_id = "abcdefghijklmnopabcdefghijklmnop"
        origin = f"chrome-extension://{chrome_id}"
        config = FakeConfig({
            "ServerToken": "z" * 32,
            "NativeChromeExtensionIds": "",
            "LegacyHealthTokenEcho": False,
        })
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad, "refresh_native_messaging_registration", return_value=True):
            api = ad.create_api(config, manager, FakeHistory())
            resp = api.test_client().post(
                "/pair-extension",
                json={"id": chrome_id},
                headers={"Origin": origin, "X-MDL-Client": "MediaDL"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["paired"])
        self.assertEqual(body["id"], chrome_id)
        self.assertNotIn("token", body)
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), origin)
        self.assertEqual(config.get("NativeChromeExtensionIds"), chrome_id)

    def test_pair_route_rejects_a_web_origin(self):
        config = FakeConfig({"ServerToken": "z" * 32, "NativeChromeExtensionIds": ""})
        manager = ad.DownloadManager(config, FakeHistory())
        with mock.patch.object(ad, "refresh_native_messaging_registration", return_value=True) as refresh:
            api = ad.create_api(config, manager, FakeHistory())
            resp = api.test_client().post(
                "/pair-extension",
                json={"id": "abcdefghijklmnopabcdefghijklmnop"},
                headers={"Origin": "https://www.youtube.com", "X-MDL-Client": "MediaDL"},
            )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "invalid-origin")
        self.assertEqual(config.get("NativeChromeExtensionIds"), "")
        refresh.assert_not_called()


class SiteLoginApiTests(unittest.TestCase):
    """/site-logins is authenticated, write-only for secrets, and URL-policed."""

    EXPORT = ".x.com\tTRUE\t/\tTRUE\t2000000000\tauth_token\tX-SECRET"

    def _client(self, token):
        config = FakeConfig({"ServerToken": token})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        return api.test_client(), manager

    def test_requires_authentication(self):
        client, _manager = self._client("z" * 32)
        self.assertEqual(client.get("/site-logins").status_code, 401)
        self.assertEqual(
            client.post("/site-logins", json={"site": "x.com"}).status_code, 401
        )
        self.assertEqual(
            client.delete("/site-logins", json={"site": "x.com"}).status_code, 401
        )

    def test_import_list_and_delete_round_trip(self):
        token = "z" * 32
        client, manager = self._client(token)
        with tempfile.TemporaryDirectory() as tmp:
            manager.site_logins = ad.SiteLoginStore(tmp)
            created = client.post(
                "/site-logins",
                json={"site": "https://x.com/", "cookiesText": self.EXPORT},
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.get_json()["site"], "x.com")

            listing = client.get("/site-logins", headers={"X-Auth-Token": token})
            self.assertEqual(listing.status_code, 200)
            body = listing.get_data(as_text=True)
            self.assertIn("x.com", body)
            self.assertNotIn("X-SECRET", body, "cookie values must never be readable")
            self.assertNotIn("auth_token", body)

            removed = client.delete(
                "/site-logins", json={"site": "x.com"}, headers={"X-Auth-Token": token}
            )
            self.assertEqual(removed.status_code, 200)
            self.assertTrue(removed.get_json()["removed"])
            self.assertEqual(
                client.get("/site-logins", headers={"X-Auth-Token": token}).get_json()["sites"],
                [],
            )

    def test_extension_shaped_cookie_records_are_accepted(self):
        token = "z" * 32
        client, manager = self._client(token)
        with tempfile.TemporaryDirectory() as tmp:
            manager.site_logins = ad.SiteLoginStore(tmp)
            resp = client.post(
                "/site-logins",
                json={
                    "site": "instagram.com",
                    "source": "extension",
                    "cookies": [
                        {"name": "sessionid", "value": "IG", "domain": ".instagram.com",
                         "path": "/", "secure": True, "expirationDate": 2_000_000_000},
                        {"name": "SID", "value": "YT", "domain": ".youtube.com",
                         "path": "/", "secure": True, "expirationDate": 2_000_000_000},
                    ],
                },
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_json()["cookies"], 1)
            self.assertEqual(resp.get_json()["skipped"], 1, "the YouTube cookie is dropped")

    def test_credentials_can_be_written_but_never_read_back_from_the_api(self):
        token = "z" * 32
        username = "member@example.com"
        password = "API-PASSWORD-SECRET"
        client, manager = self._client(token)
        with tempfile.TemporaryDirectory() as tmp:
            manager.site_logins = ad.SiteLoginStore(tmp)
            created = client.post(
                "/site-logins",
                json={
                    "site": "youtube.com",
                    "username": username,
                    "password": password,
                },
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(created.status_code, 200)
            created_payload = created.get_json()
            self.assertEqual(created_payload["warningCode"], "youtube-account-risk")
            self.assertTrue(created_payload["warningStatePersisted"])
            self.assertIn("temporary or permanent bans", created_payload["warning"])
            self.assertIn("signed-in sessions", created_payload["warning"])
            self.assertIn("public videos unplayable", created_payload["warning"])
            self.assertIn("yt-dlp/wiki/Extractors", created_payload["warningUrl"])
            self.assertTrue(
                manager.config.get("YouTubeSignInRiskNoticeShown"),
                "the API must persist the same one-time warning state as the GUI",
            )
            created_text = created.get_data(as_text=True)
            self.assertNotIn(username, created_text)
            self.assertNotIn(password, created_text)
            listing = client.get("/site-logins", headers={"X-Auth-Token": token})
            listing_text = listing.get_data(as_text=True)
            self.assertNotIn(username, listing_text)
            self.assertNotIn(password, listing_text)
            self.assertTrue(listing.get_json()["sites"][0]["credentialed"])

            repeated = client.post(
                "/site-logins",
                json={
                    "site": "youtube.com",
                    "username": username,
                    "password": password,
                },
                headers={"X-Auth-Token": token},
            )
            self.assertEqual(repeated.status_code, 200)
            self.assertNotIn("warningCode", repeated.get_json())

        class FailingNoticeConfig(FakeConfig):
            def update(self, mapping):
                if mapping == {"YouTubeSignInRiskNoticeShown": True}:
                    return False
                return super().update(mapping)

        failing_config = FailingNoticeConfig({"ServerToken": token})
        failing_manager = ad.DownloadManager(failing_config, FakeHistory())
        failing_api = ad.create_api(failing_config, failing_manager, FakeHistory())
        failing_client = failing_api.test_client()
        with tempfile.TemporaryDirectory() as tmp:
            failing_manager.site_logins = ad.SiteLoginStore(tmp)
            warning_responses = [
                failing_client.post(
                    "/site-logins",
                    json={
                        "site": "youtube.com",
                        "username": username,
                        "password": password,
                    },
                    headers={"X-Auth-Token": token},
                ).get_json()
                for _attempt in range(2)
            ]
        self.assertFalse(warning_responses[0]["warningStatePersisted"])
        self.assertNotIn(
            "warningCode", warning_responses[1],
            "a failed disk write must not repeat the warning in one API process",
        )

        update_barrier = threading.Barrier(2)

        class RacingNoticeConfig(FakeConfig):
            def update(self, mapping):
                if mapping == {"YouTubeSignInRiskNoticeShown": True}:
                    try:
                        update_barrier.wait(timeout=0.5)
                    except threading.BrokenBarrierError:
                        # reason: the lock intentionally makes the second party time out
                        pass
                return super().update(mapping)

        class RacingStore:
            @staticmethod
            def save_credentials(site, _username, _password, source="credentials"):
                del site, source
                return {
                    "site": "youtube.com", "cookies": 0,
                    "skipped": 0, "credentialed": True,
                }, None

        racing_config = RacingNoticeConfig({"ServerToken": token})
        racing_manager = ad.DownloadManager(racing_config, FakeHistory())
        racing_manager.site_logins = RacingStore()
        racing_api = ad.create_api(racing_config, racing_manager, FakeHistory())
        concurrent_payloads = []

        def post_concurrently():
            response = racing_api.test_client().post(
                "/site-logins",
                json={
                    "site": "youtube.com",
                    "username": username,
                    "password": password,
                },
                headers={"X-Auth-Token": token},
            )
            concurrent_payloads.append(response.get_json())

        workers = [threading.Thread(target=post_concurrently) for _index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(
            sum("warningCode" in payload for payload in concurrent_payloads),
            1,
            "threaded API requests must claim the one-time warning atomically",
        )

    def test_private_network_sites_are_refused(self):
        token = "z" * 32
        client, manager = self._client(token)
        with tempfile.TemporaryDirectory() as tmp:
            manager.site_logins = ad.SiteLoginStore(tmp)
            for hostile in ("http://192.168.1.5/", "localhost", "127.0.0.1"):
                resp = client.post(
                    "/site-logins",
                    json={"site": hostile, "cookiesText": self.EXPORT},
                    headers={"X-Auth-Token": token},
                )
                self.assertEqual(resp.status_code, 400, hostile)
                self.assertEqual(resp.get_json()["code"], "private-host", hostile)

    def test_missing_payload_is_rejected(self):
        token = "z" * 32
        client, manager = self._client(token)
        with tempfile.TemporaryDirectory() as tmp:
            manager.site_logins = ad.SiteLoginStore(tmp)
            resp = client.post(
                "/site-logins", json={"site": "x.com"}, headers={"X-Auth-Token": token}
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.get_json()["code"], "missing-cookies")


class ClientApiHandshakeTests(unittest.TestCase):
    """Two independently-versioned products sharing one port catalogue.

    The downloader advertised an API version nothing read. A floor plus a
    named refusal turns that number into a contract, while a client that sends
    no version keeps working exactly as before.
    """

    TOKEN = "t" * 32

    def _client(self):
        config = FakeConfig({"ServerToken": self.TOKEN, "DownloadPath": "."})
        manager = ad.DownloadManager(config, FakeHistory())
        api = ad.create_api(config, manager, FakeHistory())
        api.config.update(TESTING=True)
        return api.test_client()

    def test_health_advertises_the_floor_it_will_serve(self):
        response = self._client().get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["api"], ad.SERVICE_API_VERSION)
        self.assertEqual(payload["minimumClientApi"], ad.SERVICE_API_MINIMUM_CLIENT)

    def test_a_client_that_sends_no_version_is_served_as_before(self):
        # The shipped Astra Deck sends nothing. Absence must not be a refusal.
        response = self._client().get(
            "/status", headers={"X-Auth-Token": self.TOKEN}
        )
        self.assertNotEqual(response.status_code, 426)

    def test_a_client_below_the_floor_is_refused_by_name(self):
        response = self._client().get(
            "/status",
            headers={"X-Auth-Token": self.TOKEN, "X-MDL-Api": "0"},
        )
        self.assertEqual(response.status_code, 426)
        payload = response.get_json()
        self.assertEqual(payload["code"], "client-api-too-old")
        self.assertEqual(payload["minimumClientApi"], ad.SERVICE_API_MINIMUM_CLIENT)
        self.assertIn("Update the Astra Deck", payload["remediation"])

    def test_an_old_client_can_still_read_health_to_explain_itself(self):
        response = self._client().get("/health", headers={"X-MDL-Api": "0"})
        self.assertEqual(
            response.status_code, 200,
            "an out-of-date client must still be able to read the numbers "
            "that tell the user why it stopped working",
        )

    def test_a_junk_version_header_is_ignored_rather_than_refused(self):
        response = self._client().get(
            "/status",
            headers={"X-Auth-Token": self.TOKEN, "X-MDL-Api": "not-a-number"},
        )
        self.assertNotEqual(response.status_code, 426)

    def test_the_version_header_survives_preflight(self):
        response = self._client().options("/status")
        allowed = response.headers.get("Access-Control-Allow-Headers", "")
        self.assertIn("X-MDL-Api", allowed)


if __name__ == "__main__":
    unittest.main()
