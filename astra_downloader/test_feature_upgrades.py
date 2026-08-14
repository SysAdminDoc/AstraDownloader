"""Tests for AD-26 (Playlist Staging), AD-27 (Pipeline Steps), and AD-28 (Command Inspector)."""

import json
import unittest
from unittest import mock
from pathlib import Path
import tempfile

from PyQt6.QtWidgets import QApplication

import astra_downloader as ad


class FakeHistory:
    def __init__(self):
        self.history = []

    def add(self, item):
        self.history.append(item)

    def get_all(self):
        return list(self.history)

    def clear(self):
        self.history.clear()


class FakeConfig:
    def __init__(self, data=None):
        self.data = {
            "DownloadPath": str(Path(tempfile.gettempdir()) / "astra-downloader-tests"),
            "AudioDownloadPath": "",
            "ConcurrentFragments": 4,
            "EmbedMetadata": False,
            "EmbedThumbnail": False,
            "EmbedChapters": False,
            "EmbedSubs": False,
            "SponsorBlock": False,
            "RateLimit": "",
            "Proxy": "",
            "ServerToken": "t" * 32,
        }
        if data:
            self.data.update(data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, val):
        self.data[key] = val

    def save(self):
        pass


class PipelineStepsTests(unittest.TestCase):
    """Tests for granular multi-step pipeline progress (AD-27)."""

    def test_download_initial_step_is_pending(self):
        dl = ad.Download("dl_test_1", "https://example.com/video")
        self.assertEqual(dl.step, "pending")
        self.assertIn("step", dl.to_dict())
        self.assertEqual(dl.to_dict()["step"], "pending")

    def test_pipeline_step_constants(self):
        self.assertIn("fetching", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("downloading", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("merging", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("embedding", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("transcribing", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("complete", ad.DOWNLOAD_PIPELINE_STEPS)
        self.assertIn("failed", ad.DOWNLOAD_PIPELINE_STEPS)

    def test_step_included_in_to_dict_and_rollback(self):
        dl = ad.Download("dl_test_2", "https://example.com/video")
        dl.step = "merging"
        dl.status = "downloading"
        payload = dl.to_dict()
        self.assertEqual(payload["step"], "merging")
        self.assertEqual(payload["status"], "downloading")


class RedactedCommandInspectorTests(unittest.TestCase):
    """Tests for yt-dlp command redaction and API route (AD-28)."""

    def test_format_redacted_command_args_removes_credentials(self):
        dl = ad.Download("dl_test_3", "https://example.com/video")
        dl._credentials = {"username": "secret_user", "password": "secret_password"}
        dl._video_password = "video_super_secret"

        raw_args = [
            "yt-dlp", "--username", "secret_user", "--password", "secret_password",
            "--video-password", "video_super_secret",
            "--cookies", r"C:\Users\testuser\AppData\Local\AstraDownloader\cookies.txt",
            "--add-header", "Authorization: Bearer super_secret_token_123",
            "--extractor-args", "youtube:po_token=sensitive_po_token_val+something",
            "https://example.com/video"
        ]

        redacted = ad.format_redacted_command_args(raw_args, dl)

        self.assertNotIn("secret_user", redacted)
        self.assertNotIn("secret_password", redacted)
        self.assertNotIn("video_super_secret", redacted)
        self.assertNotIn("super_secret_token_123", " ".join(redacted))
        self.assertNotIn("sensitive_po_token_val", " ".join(redacted))

        # Check expected redaction placements
        self.assertIn("[redacted]", redacted)
        self.assertIn("[redacted header]", redacted)
        self.assertTrue(any("po_token=[redacted]" in arg for arg in redacted))

    def test_empty_and_safe_args(self):
        self.assertEqual(ad.format_redacted_command_args([]), [])
        safe_args = ["yt-dlp", "--no-warnings", "-f", "bestvideo+bestaudio", "https://example.com/video"]
        redacted = ad.format_redacted_command_args(safe_args)
        self.assertEqual(redacted, safe_args)

    def test_command_args_stored_on_download_and_in_to_dict(self):
        dl = ad.Download("dl_test_4", "https://example.com/video")
        dl.command_args = ["yt-dlp", "-f", "best", "https://example.com/video"]
        payload = dl.to_dict()
        self.assertIn("commandArgs", payload)
        self.assertEqual(payload["commandArgs"], ["yt-dlp", "-f", "best", "https://example.com/video"])

    def test_command_api_endpoint(self):
        config = FakeConfig()
        manager = ad.DownloadManager(config, FakeHistory())
        dl = ad.Download("dl_test_api", "https://example.com/video")
        dl.command_args = ["yt-dlp", "--no-warnings", "https://example.com/video"]
        manager.downloads["dl_test_api"] = dl

        api = ad.create_api(config, manager, FakeHistory())
        client = api.test_client()

        # Unauthenticated request (Host header required to pass DNS-rebinding guard)
        res = client.get("/downloads/dl_test_api/command", headers={"Host": "127.0.0.1"})
        self.assertEqual(res.status_code, 401)

        # Non-existent download
        headers = {"X-Auth-Token": config.get("ServerToken"), "Host": "127.0.0.1"}
        res_404 = client.get("/downloads/nonexistent/command", headers=headers)
        self.assertEqual(res_404.status_code, 404)

        # Existing download
        res_200 = client.get("/downloads/dl_test_api/command", headers=headers)
        self.assertEqual(res_200.status_code, 200)
        data = res_200.get_json()
        self.assertEqual(data["id"], "dl_test_api")
        self.assertEqual(data["commandArgs"], ["yt-dlp", "--no-warnings", "https://example.com/video"])
        self.assertEqual(data["command"], "yt-dlp --no-warnings https://example.com/video")


class PlaylistStagingTests(unittest.TestCase):
    """Tests for playlist staging and preview summarization (AD-26)."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_summarize_ytdlp_playlist_structure(self):
        raw_info = {
            "id": "PL12345",
            "title": "Sample Course Playlist",
            "uploader": "Test Channel",
            "entries": [
                {"id": "vid1", "title": "Lesson 1", "duration": 120, "playlist_index": 1},
                {"id": "vid2", "title": "Lesson 2", "duration": 360, "playlist_index": 2},
                {"id": "vid3", "title": "Lesson 3", "duration": 240, "playlist_index": 3},
            ]
        }

        summary = ad.summarize_ytdlp_playlist(raw_info)
        self.assertEqual(summary["id"], "PL12345")
        self.assertEqual(summary["title"], "Sample Course Playlist")
        self.assertEqual(summary["channel"], "Test Channel")
        self.assertEqual(summary["total"], 3)
        self.assertEqual(len(summary["items"]), 3)
        self.assertEqual(summary["items"][0]["title"], "Lesson 1")
        self.assertEqual(summary["items"][0]["duration"], 120)
        self.assertEqual(summary["items"][1]["index"], 2)

    def test_playlist_staging_dialog_selection(self):
        playlist_info = {
            "title": "Python 101",
            "channel": "Tech Academy",
            "total": 3,
            "items": [
                {"id": "v1", "title": "Intro", "duration": 60, "index": 1},
                {"id": "v2", "title": "Functions", "duration": 180, "index": 2},
                {"id": "v3", "title": "Classes", "duration": 300, "index": 3},
            ]
        }
        dialog = ad.PlaylistStagingDialog(None, playlist_info)
        self.assertEqual(len(dialog.checkboxes), 3)
        self.assertEqual(dialog.get_selected_indices(), [1, 2, 3])

        # Deselect all
        dialog._deselect_all()
        self.assertEqual(dialog.get_selected_indices(), [])
        self.assertFalse(dialog.btn_download.isEnabled())

        # Select all
        dialog._select_all()
        self.assertEqual(dialog.get_selected_indices(), [1, 2, 3])
        self.assertTrue(dialog.btn_download.isEnabled())

        # Invert (uncheck item 1, then invert -> item 1 checked, 2 and 3 unchecked)
        dialog.checkboxes[0][0].setChecked(False)
        dialog._invert_selection()
        self.assertEqual(dialog.get_selected_indices(), [1])


if __name__ == "__main__":
    unittest.main()
