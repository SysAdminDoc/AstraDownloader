"""Fixtures and helpers every domain test module shares.

Named `testing_support` rather than `test_support` on purpose: pytest
collects `test_*.py`, and this module holds no tests.
"""

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
from datetime import date, datetime, timedelta
from unittest import mock
from pathlib import Path
import xml.etree.ElementTree as ET
import astra_downloader as ad


__all__ = (
    "FakeConfig",
    "FakeHistory",
    "fresh_ytdlp_version",
    "ytdlp_invocations",
    "_retire_test_window",
    "_get_qapp_or_skip",
    "subscriptions_module",
    "gui_module_for_tests",
    "_RETAINED_TEST_WINDOWS",
    "_qapp_singleton",
)


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
            # Keep tests hermetic: start_download now opens the throttled
            # yt-dlp auto-update window, and the real DownloadManager wires the
            # real network updater. Default it off here so exercising a
            # download never spawns a background `yt-dlp -U`. Auto-update tests
            # pass their own config with this enabled.
            "AutoUpdateYtDlp": False,
        }
        if data:
            self.data.update(data)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def update(self, mapping):
        if mapping:
            self.data.update(mapping)
        return True

    def save(self):
        pass


class FakeHistory:
    def __init__(self):
        self.entries = []

    def add(self, entry):
        self.entries.append(entry)
        # HistoryStore.add reports whether the write landed. The double
        # returned None, which reads as a failed write now that the caller
        # checks it.
        return True

    def load(self):
        return list(self.entries)


_RETAINED_TEST_WINDOWS = []


_qapp_singleton = None


def fresh_ytdlp_version(reference=None):
    """Return a yt-dlp version string the freshness check calls current.

    `evaluate_preflight_checks` measures a dated yt-dlp release against
    `date.today()` through a relative window (`YTDLP_STALE_AFTER_DAYS`), so a
    literal version written into a fixture that asserts a fresh outcome is a
    fuse: it passes on the day it is written and fails, weeks later, a run
    that changed nothing. Derive the version from the same clock the check
    reads instead.

    The opposite case needs no helper. A fixture that asserts a *stale* or
    error outcome may keep an absolute version, because an absolute date can
    only get staler.
    """
    if reference is None:
        today = date.today()
    elif isinstance(reference, datetime):
        today = reference.date()
    else:
        today = reference
    return f"{today.year}.{today.month:02d}.{today.day:02d}"


def ytdlp_invocations(captured):
    """Only the yt-dlp download calls out of everything Popen was handed.

    A version or capability probe reaching the same fake is not a defect: it
    means the module-wide probe cache was cold, which depends on what ran
    before this test and, under `-n auto`, on which worker drew it. Select the
    download by the flag only a download carries.
    """
    return [
        list(args) for args in captured
        if any(str(argument) == '--ignore-config' for argument in args)
    ]


def _retire_test_window(window):
    """Close a window without deleting it.

    Deleting a complex Qt window immediately can invalidate queued callbacks
    that Qt itself still owns; a later processEvents in another test then walks
    freed memory and the interpreter dies with an access violation. Application
    shutdown performs the final disposal.
    """
    from PySide6.QtWidgets import QApplication

    try:
        window.tray.hide()
    except Exception:
        # reason: the tray icon is optional and teardown must not fail on it
        pass
    window._force_exit = True
    window.close()
    QApplication.processEvents()
    _RETAINED_TEST_WINDOWS.append(window)


def _get_qapp_or_skip(test_case):
    """Lazily construct the QApplication singleton for GUI smoke tests.

    Qt requires exactly one QApplication per process; constructing
    a second one raises. We cache the first instance and reuse it.
    On a CI runner without a display server (Linux without xvfb,
    SSH session without X-forwarding), construction raises — the
    test is skipped rather than failing the whole pytest run.
    """
    global _qapp_singleton
    if _qapp_singleton is not None:
        return _qapp_singleton
    try:
        from PySide6.QtWidgets import QApplication
        _qapp_singleton = QApplication.instance() or QApplication([])
        return _qapp_singleton
    except Exception as e:  # noqa: BLE001
        test_case.skipTest(f"QApplication construction failed: {e!r}")
        return None


def subscriptions_module():
    import subscriptions as subscriptions_mod
    return subscriptions_mod


def gui_module_for_tests():
    import gui as gui_module
    return gui_module
