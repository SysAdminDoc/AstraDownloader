"""Tests for scheduled feeds and the archive."""

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


class SubscriptionTests(unittest.TestCase):
    def _store(self, path, clock=lambda: 1000.0):
        return ad.SubscriptionStore(
            path=path,
            reader=ad.load_json_file,
            writer=ad.atomic_write_json,
            logger=self.fail,
            normalize_url=ad.normalize_url,
            is_youtube_url=ad.is_youtube_url,
            clean_text=ad.clean_text,
            clamp_int=ad.clamp_int,
            coerce_bool=ad.coerce_bool,
            clock=clock,
        )

    def test_a_scan_persists_once_regardless_of_candidate_count(self):
        # reserve + mark_queued used to fsync the whole document per candidate,
        # on the same lock the Qt main thread and /health take.
        writes = []

        def counting_writer(target, payload):
            writes.append(target)
            return ad.atomic_write_json(target, payload)

        with tempfile.TemporaryDirectory() as tmp:
            store = ad.SubscriptionStore(
                path=Path(tmp) / "batched.json",
                reader=ad.load_json_file,
                writer=counting_writer,
                logger=self.fail,
                normalize_url=ad.normalize_url,
                is_youtube_url=ad.is_youtube_url,
                clean_text=ad.clean_text,
                clamp_int=ad.clamp_int,
                coerce_bool=ad.coerce_bool,
                clock=lambda: 1000.0,
            )
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", interval_minutes=5, now=1000,
            )
            self.assertIsNone(error)

            candidates = [
                {"id": f"video{index}", "title": f"Video {index}",
                 "url": f"https://www.youtube.com/watch?v=video{index:07d}"}
                for index in range(50)
            ]
            queued_ids = iter(range(1, 1000))
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (candidates, None),
                enqueue=lambda *_args: (f"dl-{next(queued_ids)}", None),
            )

            writes.clear()
            result = manager.scan_subscription(record["id"], now=2000)

            self.assertEqual(result["queued"], 50)
            self.assertFalse(result["error"])
            # begin_scan, the coalesced candidate loop, and finish_scan. The
            # bound is what matters: it must not grow with the candidate count.
            self.assertLessEqual(
                len(writes), 4,
                f"a 50-candidate scan wrote {len(writes)} times",
            )
            reloaded = json.loads((Path(tmp) / "batched.json").read_text(encoding="utf-8"))
            self.assertEqual(
                sum(1 for entry in reloaded["archive"].values()
                    if entry.get("status") == "queued"),
                50,
                "every claim must survive the coalesced write",
            )

    def test_another_thread_still_writes_while_a_scan_batches(self):
        # A store-wide batch would defer the GUI thread's write and hand it
        # back success, so Add subscription during a scan would report "Added"
        # with nothing on disk.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "concurrent.json"
            store = self._store(state)
            barrier = threading.Event()
            released = threading.Event()

            def batching():
                with store.batched_saves():
                    store.add_subscription(
                        "https://www.youtube.com/@first", interval_minutes=5, now=1000,
                    )
                    barrier.set()
                    released.wait(5)

            worker = threading.Thread(target=batching)
            worker.start()
            self.addCleanup(worker.join)
            self.assertTrue(barrier.wait(5))

            record, error = store.add_subscription(
                "https://www.youtube.com/@second", interval_minutes=5, now=1000,
            )
            self.assertIsNone(error)
            on_disk = json.loads(state.read_text(encoding="utf-8"))
            self.assertIn(
                "https://www.youtube.com/@second",
                [item["url"] for item in on_disk["subscriptions"]],
                "a write from outside the batch must not be deferred",
            )
            released.set()
            worker.join(5)

    def test_a_reservation_is_on_disk_before_anything_is_enqueued(self):
        # _enqueue reaches the download manager, which persists its own queue
        # and restores it on the next launch. A claim still only in memory when
        # the process dies leaves a restored download with no archive entry, so
        # the next scan queues the same video again.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "ordering.json"
            store = self._store(state)
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", interval_minutes=5, now=1000,
            )
            self.assertIsNone(error)

            candidates = [
                {"id": f"video{index}", "title": f"Video {index}",
                 "url": f"https://www.youtube.com/watch?v=video{index:07d}"}
                for index in range(5)
            ]
            reserved_at_first_enqueue = []

            def enqueue(*_args):
                if not reserved_at_first_enqueue:
                    document = json.loads(state.read_text(encoding="utf-8"))
                    reserved_at_first_enqueue.append(len(document["archive"]))
                return "dl-1", None

            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (candidates, None),
                enqueue=enqueue,
            )
            manager.scan_subscription(record["id"], now=2000)

            self.assertEqual(
                reserved_at_first_enqueue, [5],
                "every claim must be durable before the first download is queued",
            )

    def test_a_scan_that_cannot_persist_reports_it_once(self):
        # Inside a batch each mutation reports success on the strength of the
        # pending write, so the failure has to surface when the batch flushes.
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "unwritable.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", interval_minutes=5, now=1000,
            )
            self.assertIsNone(error)
            store._logger = lambda _message: None

            def failing_writer(_target, _payload):
                raise OSError("disk full")

            candidates = [
                {"id": f"video{index}", "title": f"Video {index}",
                 "url": f"https://www.youtube.com/watch?v=video{index:07d}"}
                for index in range(5)
            ]
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (candidates, None),
                enqueue=lambda *_args: ("dl-1", None),
            )
            store._writer = failing_writer
            result = manager.scan_subscription(record["id"], now=2000)

            self.assertIn("Could not save subscriptions", result["error"])

    def test_history_reads_the_archive_without_the_deep_copy(self):
        # archive_entries() deep-copies every record under the store lock; at
        # the 20,000-entry cap the Qt main thread paid a multi-megabyte copy
        # per History refresh. The history path must use the scalar
        # projection instead, and the projection must never call the deep
        # copier.
        subs_mod = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "view.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-view", interval_minutes=60)
            self.assertIsNone(error)
            for index in range(20_000):
                store._data["archive"][f"id:v{index}"] = {
                    "url": f"https://www.youtube.com/watch?v=v{index}",
                    "title": f"Video {index}",
                    "status": "complete",
                    "subscriptionId": record["id"],
                    "completedAt": 1000.0 + index,
                    "nested": {"payload": ["that", "history", "never", "reads"]},
                }
            with mock.patch.object(
                subs_mod, "_copy",
                side_effect=AssertionError("history must not deep-copy the archive"),
            ):
                view = store.archive_history_view()
            self.assertEqual(len(view), 20_000)
            sample = view["id:v0"]
            self.assertEqual(sample["title"], "Video 0")
            self.assertNotIn("nested", sample, "the projection carries scalars only")
            result = ad.query_history_entries(
                [], sort="newest", offset=0, limit=5, archive_entries=view)
            self.assertEqual(result["count"], 5)
            self.assertEqual(result["total"], 20_000)
            self.assertEqual(
                result["history"][0]["title"], "Video 19999",
                "the projection must satisfy sorting on the query path",
            )

    def test_manual_scans_are_capped_by_the_scan_gate_and_none_are_dropped(self):
        # request_scan used to spawn an unbounded thread per subscription, each
        # running yt-dlp; at the 100-record cap "Scan now" down the list could
        # hold 100 concurrent probes. The gate must bound concurrency without
        # dropping any scan.
        subs_mod = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "gate.json", clock=time.time)
            sub_ids = []
            for index in range(8):
                record, error = store.add_subscription(
                    f"https://www.youtube.com/@astra-gate-{index}",
                    interval_minutes=60,
                )
                self.assertIsNone(error)
                sub_ids.append(record["id"])

            active = {"now": 0, "peak": 0}
            probed = []
            gate_lock = threading.Lock()

            def probe(url):
                with gate_lock:
                    active["now"] += 1
                    active["peak"] = max(active["peak"], active["now"])
                    probed.append(url)
                time.sleep(0.05)
                with gate_lock:
                    active["now"] -= 1
                return ([], None)

            manager = ad.SubscriptionManager(
                store=store,
                probe=probe,
                enqueue=lambda *_args: (None, None),
            )
            for sub_id in sub_ids:
                result, error = manager.request_scan(sub_id)
                self.assertIsNone(error)
                self.assertTrue(result["scheduled"])

            deadline = time.time() + 15
            while time.time() < deadline:
                with manager._lock:
                    if not manager._scan_ids:
                        break
                time.sleep(0.02)
            with manager._lock:
                self.assertEqual(manager._scan_ids, set(), "scans must all finish")

            with gate_lock:
                self.assertEqual(active["now"], 0)
                self.assertEqual(
                    len(probed), len(sub_ids), "no requested scan may be dropped"
                )
                self.assertLessEqual(
                    active["peak"], subs_mod.SUBSCRIPTION_SCAN_MAX_CONCURRENT,
                    "concurrent yt-dlp probes must stay under the gate",
                )

    def test_subscription_and_archive_state_round_trip_across_store_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            store = self._store(path)
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel",
                interval_minutes=1,
                title="Astra channel",
            )
            self.assertIsNone(error)
            self.assertEqual(record["intervalMinutes"], ad.SUBSCRIPTION_MIN_INTERVAL_MINUTES)
            candidate = {
                "id": "video-001",
                "url": "https://www.youtube.com/watch?v=video-001",
                "title": "First upload",
            }
            key = ad.subscription_archive_key(candidate)
            self.assertEqual(store.reserve_archive(key, candidate, record["id"]),
                             subscriptions_module().RESERVE_OK)
            self.assertTrue(store.mark_archive_queued(key, "dl_subscription_1"))
            self.assertEqual(store.mark_download("dl_subscription_1", "complete"), 1)

            restored = self._store(path)
            self.assertEqual(restored.list_subscriptions()[0]["url"], record["url"])
            self.assertEqual(restored.archive_summary()["complete"], 1)
            self.assertEqual(restored.archive_entries()[key]["status"], "complete")

    def test_missing_and_older_subscription_schemas_migrate_on_save(self):
        for stored_version in (None, ad.SUBSCRIPTION_SCHEMA_VERSION - 1):
            with self.subTest(stored_version=stored_version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "legacy-subscriptions.json"
                payload = {
                    "subscriptions": [{
                        "id": "legacy-subscription",
                        "url": "https://www.youtube.com/@legacy",
                        "enabled": False,
                    }],
                    "archive": {},
                }
                if stored_version is not None:
                    payload["schemaVersion"] = stored_version
                path.write_text(json.dumps(payload), encoding="utf-8")
                logs = []
                store = ad.SubscriptionStore(
                    path=path,
                    reader=ad.load_json_file,
                    writer=ad.atomic_write_json,
                    logger=logs.append,
                )

                self.assertEqual(len(store.list_subscriptions()), 1)
                updated, error = store.update_subscription(
                    "legacy-subscription", title="Migrated"
                )

                self.assertIsNotNone(updated)
                self.assertIsNone(error)
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["schemaVersion"],
                    ad.SUBSCRIPTION_SCHEMA_VERSION,
                )
                self.assertTrue(any("Migrating subscription state" in message for message in logs))

    def test_newer_subscription_schema_is_read_only_and_names_the_real_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future-subscriptions.json"
            future = {
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION + 1,
                "futureOnly": {"preserve": True},
                "subscriptions": [],
                "archive": {},
            }
            path.write_text(json.dumps(future), encoding="utf-8")
            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                logger=lambda _message: None,
            )

            record, error = store.add_subscription("https://www.youtube.com/@future")
            self.assertIsNone(record)
            self.assertIn("newer, incompatible Astra Downloader version", error)
            self.assertNotIn("disk space", error)
            self.assertEqual(
                store.remove_subscription("future-subscription")[1], error
            )
            self.assertEqual(
                store.reserve_archive(
                    "id:future", {
                        "id": "future", "url": "https://www.youtube.com/watch?v=future"
                    }, "future-subscription"
                ),
                subscriptions_module().RESERVE_SAVE_FAILED,
            )
            manager = subscriptions_module().SubscriptionManager(
                store=store,
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: (None, None),
            )
            result = manager.scan_subscription("future-subscription")
            self.assertIn("newer, incompatible Astra Downloader version", result["error"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), future)

    def test_begin_scan_moves_a_due_subscription_to_its_next_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "schedule.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel",
                interval_minutes=5,
                now=1000,
            )
            self.assertIsNone(error)
            self.assertEqual(
                [item["id"] for item in store.due_subscriptions(now=1000)],
                [record["id"]],
            )

            started = store.begin_scan(record["id"], now=1000)

            self.assertEqual(started["lastScanAt"], 1000)
            self.assertEqual(started["nextScanAt"], 1300)
            self.assertEqual(store.due_subscriptions(now=1000), [])
            self.assertEqual(
                [item["id"] for item in store.due_subscriptions(now=1300)],
                [record["id"]],
            )

    def test_due_subscriptions_filters_disabled_and_future_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "due-filter.json")
            due, error = store.add_subscription(
                "https://www.youtube.com/@due-channel", interval_minutes=1,
                now=1000,
            )
            self.assertIsNone(error)
            future, error = store.add_subscription(
                "https://www.youtube.com/@future-channel", interval_minutes=10,
                now=1000,
            )
            self.assertIsNone(error)
            disabled, error = store.add_subscription(
                "https://www.youtube.com/@disabled-channel", interval_minutes=1,
                now=1000,
            )
            self.assertIsNone(error)
            self.assertIsNotNone(store.update_subscription(
                disabled["id"], enabled=False, now=1000
            )[0])
            store.begin_scan(future["id"], now=1000)

            due_ids = [item["id"] for item in store.due_subscriptions(now=1000)]

            self.assertEqual(due_ids, [due["id"]])

    def test_reconcile_reopens_an_interrupted_archive_claim_for_retry(self):
        subs = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "interrupted.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel"
            )
            self.assertIsNone(error)
            candidate = {
                "id": "video-interrupted",
                "url": "https://www.youtube.com/watch?v=video-interrupted",
                "title": "Interrupted upload",
            }
            key = ad.subscription_archive_key(candidate)
            self.assertEqual(
                store.reserve_archive(key, candidate, record["id"], now=1000),
                subs.RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(key, "dl_orphan", now=1000))

            self.assertTrue(store.reconcile_downloads([], now=1001))
            orphan = store.archive_entries()[key]
            self.assertEqual(orphan["status"], "failed")
            self.assertEqual(orphan["downloadId"], "")
            self.assertEqual(orphan["attempts"], 1)
            self.assertIn("interrupted", orphan["lastError"])
            retry_at = 1001 + subs.SUBSCRIPTION_RETRY_BASE_SECONDS
            self.assertEqual(orphan["nextRetryAt"], retry_at)
            self.assertEqual(
                store.reserve_archive(key, candidate, record["id"], now=retry_at),
                subs.RESERVE_OK,
            )

    def test_runtime_archive_trim_keeps_live_claims_at_the_bound(self):
        subs = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            store = ad.SubscriptionStore(
                path=Path(tmp) / "bounded.json",
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                max_archive_entries=2,
            )
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel"
            )
            self.assertIsNone(error)
            candidates = [
                {
                    "id": "video-live",
                    "url": "https://www.youtube.com/watch?v=video-live",
                    "title": "Live claim",
                },
                {
                    "id": "video-complete",
                    "url": "https://www.youtube.com/watch?v=video-complete",
                    "title": "Completed claim",
                },
                {
                    "id": "video-new",
                    "url": "https://www.youtube.com/watch?v=video-new",
                    "title": "New claim",
                },
            ]
            keys = [ad.subscription_archive_key(candidate) for candidate in candidates]
            self.assertEqual(
                store.reserve_archive(keys[0], candidates[0], record["id"], now=1000),
                subs.RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(keys[0], "dl_live", now=1000))
            self.assertEqual(
                store.reserve_archive(keys[1], candidates[1], record["id"], now=1001),
                subs.RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(keys[1], "dl_complete", now=1001))
            self.assertEqual(store.mark_download("dl_complete", "complete", now=1001), 1)
            self.assertEqual(
                store.reserve_archive(keys[2], candidates[2], record["id"], now=1002),
                subs.RESERVE_OK,
            )

            entries = store.archive_entries()
            self.assertEqual(len(entries), 2)
            self.assertEqual(set(entries), {keys[0], keys[2]})
            self.assertEqual(entries[keys[0]]["status"], "queued")

    def test_loading_over_cap_subscriptions_preserves_and_reports_them(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "over-cap-subscriptions.json"
            records = [
                {
                    "id": f"sub_over_{index}",
                    "url": f"https://www.youtube.com/@over-cap-{index}",
                    "enabled": False,
                }
                for index in range(3)
            ]
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": records,
                "archive": {},
            }), encoding="utf-8")
            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                logger=logs.append,
                max_records=2,
            )

            self.assertEqual(len(store.list_subscriptions()), 3)
            self.assertTrue(any("preserving" in message for message in logs))
            self.assertIsNotNone(store.update_subscription(
                "sub_over_0", title="Still here"
            )[0])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["subscriptions"]), 3)

    def test_loading_over_cap_archive_preserves_and_reports_entries(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "over-cap-archive.json"
            archive = {
                f"id:archive-{index}": {
                    "url": f"https://www.youtube.com/watch?v=archive-{index}",
                    "status": "complete",
                    "updatedAt": 1000 + index,
                }
                for index in range(3)
            }
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [],
                "archive": archive,
            }), encoding="utf-8")
            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                logger=logs.append,
                max_archive_entries=2,
            )

            self.assertEqual(len(store.archive_entries()), 3)
            self.assertTrue(any("over-limit" in message for message in logs))
            owner, error = store.add_subscription("https://www.youtube.com/@archive-owner")
            self.assertIsNone(error)
            candidate = {
                "id": "archive-new",
                "url": "https://www.youtube.com/watch?v=archive-new",
                "title": "New archive entry",
            }
            self.assertEqual(
                store.reserve_archive(
                    ad.subscription_archive_key(candidate),
                    candidate,
                    owner["id"],
                    now=2000,
                ),
                subscriptions_module().RESERVE_OK,
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertLessEqual(len(persisted["archive"]), 2)
            self.assertTrue(any("removed" in message for message in logs))

    def test_archive_key_migration_keeps_the_highest_priority_collision(self):
        logs = []
        url = "https://www.youtube.com/watch?v=collision-video"
        key = ad.subscription_archive_key({"url": url})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive-collision.json"
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [],
                "archive": {
                    "url:legacy-collision": {
                        "url": url,
                        "status": "failed",
                        "updatedAt": 9000,
                    },
                    key: {
                        "url": url,
                        "status": "complete",
                        "updatedAt": 1000,
                    },
                },
            }), encoding="utf-8")
            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                logger=logs.append,
            )

            entries = store.archive_entries()
            self.assertEqual(set(entries), {key})
            self.assertEqual(entries[key]["status"], "complete")
            self.assertTrue(any("duplicate" in message for message in logs))

    def test_failed_archive_trim_restores_only_the_changed_entries(self):
        subs = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollback.json"
            writes = {"fail": False}

            def writer(actual_path, data):
                if writes["fail"]:
                    raise OSError("disk full")
                ad.atomic_write_json(actual_path, data)

            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=writer,
                logger=lambda _message: None,
                max_archive_entries=2,
            )
            record, error = store.add_subscription(
                "https://www.youtube.com/@rollback-channel"
            )
            self.assertIsNone(error)
            candidates = [
                {
                    "id": f"video-rollback-{index}",
                    "url": f"https://www.youtube.com/watch?v=video-rollback-{index}",
                    "title": f"Rollback {index}",
                }
                for index in range(3)
            ]
            for candidate in candidates[:2]:
                self.assertEqual(
                    store.reserve_archive(
                        ad.subscription_archive_key(candidate),
                        candidate,
                        record["id"],
                        now=1000,
                    ),
                    subs.RESERVE_OK,
                )
            before = store.archive_entries()
            saved_file = path.read_text(encoding="utf-8")
            writes["fail"] = True

            result = store.reserve_archive(
                ad.subscription_archive_key(candidates[2]),
                candidates[2],
                record["id"],
                now=1001,
            )

            self.assertEqual(result, subs.RESERVE_SAVE_FAILED)
            self.assertEqual(store.archive_entries(), before)
            self.assertEqual(path.read_text(encoding="utf-8"), saved_file)

    def test_completed_download_updates_only_its_subscription_archive_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "completion.json")
            first, error = store.add_subscription(
                "https://www.youtube.com/@astra-first"
            )
            self.assertIsNone(error)
            second, error = store.add_subscription(
                "https://www.youtube.com/@astra-second"
            )
            self.assertIsNone(error)
            candidates = [
                {
                    "id": "video-first",
                    "url": "https://www.youtube.com/watch?v=video-first",
                    "title": "First subscription upload",
                },
                {
                    "id": "video-second",
                    "url": "https://www.youtube.com/watch?v=video-second",
                    "title": "Second subscription upload",
                },
            ]
            keys = [ad.subscription_archive_key(candidate) for candidate in candidates]
            self.assertEqual(
                store.reserve_archive(keys[0], candidates[0], first["id"], now=1000),
                subscriptions_module().RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(keys[0], "dl_first", now=1000))
            self.assertEqual(
                store.reserve_archive(keys[1], candidates[1], second["id"], now=1000),
                subscriptions_module().RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(keys[1], "dl_second", now=1000))
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: (None, "not used"),
                status_reader=lambda download_id: (
                    "complete" if download_id == "dl_first" else "failed"
                ),
            )

            self.assertEqual(manager.handle_download_completed("dl_first"), 1)

            entries = store.archive_entries()
            self.assertEqual(entries[keys[0]]["status"], "complete")
            self.assertEqual(entries[keys[0]]["subscriptionId"], first["id"])
            self.assertIsNotNone(entries[keys[0]]["completedAt"])
            self.assertEqual(entries[keys[1]]["status"], "queued")
            self.assertEqual(entries[keys[1]]["subscriptionId"], second["id"])

    def test_removed_subscription_can_be_restored_without_resetting_its_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "undo.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel",
                interval_minutes=30,
                enabled=False,
                title="Astra channel",
            )
            self.assertIsNone(error)
            removed, error = store.remove_subscription(record["id"])
            self.assertTrue(removed)
            self.assertIsNone(error)

            restored, error = store.restore_subscription(record)
            self.assertIsNone(error)
            self.assertEqual(restored["id"], record["id"])
            self.assertEqual(restored["url"], record["url"])
            self.assertFalse(restored["enabled"])
            self.assertEqual(store.get_subscription(record["id"])["title"], "Astra channel")

    def test_subscription_removal_undo_survives_a_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "undo.json"
            store = self._store(path)
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel",
                interval_minutes=30,
                title="Astra channel",
            )
            self.assertIsNone(error)
            removed, error = store.remove_subscription_with_undo(record["id"])
            self.assertIsNone(error)
            self.assertEqual(removed["id"], record["id"])
            self.assertEqual(store.list_subscriptions(), [])

            reopened = self._store(path)
            snapshot = reopened.load_removal_undo()
            self.assertEqual(snapshot["id"], record["id"])
            restored, error = reopened.restore_subscription(snapshot)
            self.assertIsNone(error)
            self.assertEqual(restored["id"], record["id"])
            self.assertTrue(reopened.clear_removal_undo())
            self.assertIsNone(reopened.load_removal_undo())

    def test_failed_archive_claims_back_off_and_stop_after_three_attempts(self):
        subs = subscriptions_module()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "retry.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel"
            )
            self.assertIsNone(error)
            candidate = {
                "id": "video-retry",
                "url": "https://www.youtube.com/watch?v=video-retry",
                "title": "Retry me",
            }
            key = ad.subscription_archive_key(candidate)

            self.assertEqual(store.reserve_archive(key, candidate, record["id"], now=1000),
                             subs.RESERVE_OK)
            self.assertTrue(store.release_archive(key, "members-only", now=1000))
            first = store.archive_entries()[key]
            self.assertEqual(first["attempts"], 1)
            self.assertEqual(first["nextRetryAt"], 1000 + ad.SUBSCRIPTION_RETRY_BASE_SECONDS)

            download_candidate = {
                "id": "video-download-failure",
                "url": "https://www.youtube.com/watch?v=video-download-failure",
                "title": "Download failure",
            }
            download_key = ad.subscription_archive_key(download_candidate)
            self.assertEqual(
                store.reserve_archive(download_key, download_candidate, record["id"], now=1000),
                subs.RESERVE_OK,
            )
            self.assertTrue(store.mark_archive_queued(download_key, "dl_failed", now=1000))
            self.assertEqual(
                store.mark_download("dl_failed", "failed", "HTTP 403", now=1000),
                1,
            )
            self.assertEqual(
                store.archive_entries()[download_key]["nextRetryAt"],
                1000 + ad.SUBSCRIPTION_RETRY_BASE_SECONDS,
            )

            self.assertEqual(
                store.reserve_archive(key, candidate, record["id"], now=1100),
                subs.RESERVE_RETRY_BACKOFF,
            )
            self.assertEqual(store.reserve_archive(key, candidate, record["id"], now=1300),
                             subs.RESERVE_OK)
            self.assertEqual(store.archive_entries()[key]["attempts"], 2)
            self.assertTrue(store.release_archive(key, "members-only", now=1300))
            self.assertEqual(store.archive_entries()[key]["nextRetryAt"], 1900)

            self.assertEqual(store.reserve_archive(key, candidate, record["id"], now=1900),
                             subs.RESERVE_OK)
            self.assertEqual(store.archive_entries()[key]["attempts"], 3)
            self.assertTrue(store.release_archive(key, "members-only", now=1900))
            self.assertEqual(store.archive_entries()[key]["nextRetryAt"], 3100)
            self.assertEqual(
                store.reserve_archive(key, candidate, record["id"], now=3100),
                subs.RESERVE_RETRY_EXHAUSTED,
            )

    def test_long_url_only_archive_keys_remain_distinct_under_the_key_bound(self):
        prefix = "https://www.youtube.com/watch?v=" + ("a" * 390)
        first = {"url": prefix + "1"}
        second = {"url": prefix + "2"}

        first_key = ad.subscription_archive_key(first)
        second_key = ad.subscription_archive_key(second)

        self.assertNotEqual(first_key, second_key)
        self.assertLessEqual(len(first_key), 430)
        self.assertLessEqual(len(second_key), 430)
        self.assertTrue(first_key.startswith("url-sha256:"))

    def test_loading_an_old_long_url_key_migrates_it_to_a_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_url = "https://www.youtube.com/watch?v=" + ("b" * 410) + "1"
            path = Path(tmp) / "legacy-archive.json"
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [],
                "archive": {
                    "url:legacy-truncated-key": {
                        "url": first_url,
                        "status": "complete",
                    },
                },
            }), encoding="utf-8")

            store = self._store(path)
            keys = set(store.archive_entries())

        self.assertEqual(keys, {ad.subscription_archive_key({"url": first_url})})

    def test_manual_rescan_resets_the_retry_budget_and_names_gave_up_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "manager-retry.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel"
            )
            self.assertIsNone(error)
            entries = [{
                "id": "video-retry",
                "url": "https://www.youtube.com/watch?v=video-retry",
                "title": "Members-only upload",
            }]
            enqueues = []
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (entries, None),
                enqueue=lambda *_args: enqueues.append("attempt") or (
                    None, "members-only"
                ),
            )

            for stamp in (1000, 1300, 1900):
                result = manager.scan_subscription(record["id"], now=stamp)
                self.assertEqual(result["queued"], 0)
                self.assertIn("members-only", result["error"])
            exhausted = manager.scan_subscription(record["id"], now=3100)
            self.assertEqual(exhausted["skipped"], 1)
            self.assertIn("Members-only upload", exhausted["error"])
            self.assertIn("after 3 attempts", exhausted["error"])
            self.assertEqual(len(enqueues), 3)

            manual = manager.scan_subscription(
                record["id"], now=3200, manual=True
            )
            self.assertIn("members-only", manual["error"])
            self.assertEqual(len(enqueues), 4)
            key = ad.subscription_archive_key(entries[0])
            self.assertEqual(store.archive_entries()[key]["attempts"], 1)
            self.assertEqual(
                store.archive_entries()[key]["nextRetryAt"],
                3200 + ad.SUBSCRIPTION_RETRY_BASE_SECONDS,
            )

    def test_scheduler_enqueues_new_uploads_once_and_dedupes_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            store = self._store(path)
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel",
                interval_minutes=5,
            )
            self.assertIsNone(error)
            calls = []
            entries = [
                {"id": "video-001", "url": "video-001", "title": "First upload"},
                {"id": "video-001", "url": "video-001", "title": "Duplicate listing"},
                {"id": "video-002", "url": "video-002", "title": "Second upload"},
            ]

            def enqueue(_subscription, candidate, _archive_key):
                download_id = f"dl_{candidate['id']}"
                calls.append(download_id)
                return download_id, None

            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (entries, None),
                enqueue=enqueue,
                status_reader=lambda _download_id: "complete",
                clock=lambda: 1000.0,
            )
            first = manager.scan_subscription(record["id"], now=1000.0)
            self.assertEqual(first["queued"], 2)
            self.assertEqual(first["skipped"], 1)
            self.assertEqual(calls, ["dl_video-001", "dl_video-002"])

            restored_store = self._store(path)
            restored_calls = []
            restored_manager = ad.SubscriptionManager(
                store=restored_store,
                probe=lambda _url: (entries, None),
                enqueue=lambda *_args: restored_calls.append("unexpected") or ("dl", None),
                clock=lambda: 2000.0,
            )
            second = restored_manager.scan_subscription(record["id"], now=2000.0)
            self.assertEqual(second["queued"], 0)
            self.assertEqual(second["skipped"], 3)
            self.assertEqual(restored_calls, [])

    def test_interrupted_queue_claim_reconciles_from_download_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            store = self._store(path)
            record, error = store.add_subscription("https://www.youtube.com/@astra-channel")
            self.assertIsNone(error)
            candidate = {
                "id": "video-003",
                "url": "https://www.youtube.com/watch?v=video-003",
                "title": "Interrupted upload",
            }
            key = ad.subscription_archive_key(candidate)
            self.assertEqual(store.reserve_archive(key, candidate, record["id"]),
                             subscriptions_module().RESERVE_OK)
            download = ad.Download(
                "dl_subscription_3",
                candidate["url"],
                title=candidate["title"],
                subscription_id=record["id"],
                archive_key=key,
            )
            self.assertTrue(store.reconcile_downloads([download]))
            entry = store.archive_entries()[key]
            self.assertEqual(entry["status"], "queued")
            self.assertEqual(entry["downloadId"], download.id)

    def test_subscription_linkage_survives_download_queue_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "download-queue.json"
            config = FakeConfig({"DownloadPath": tmp, "AudioDownloadPath": tmp})
            manager = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertTrue(manager.pause_intake())
            download_id, error = manager.start_download(
                "https://www.youtube.com/watch?v=queueSubscription",
                title="Queued subscription upload",
                subscription_id="sub_queue",
                archive_key="id:queueSubscription",
            )
            self.assertIsNone(error)
            persisted = json.loads(queue_path.read_text(encoding="utf-8"))
            record = persisted["downloads"][0]
            self.assertEqual(record["subscriptionId"], "sub_queue")
            self.assertEqual(record["archiveKey"], "id:queueSubscription")

            restored = ad.DownloadManager(config, FakeHistory(), queue_path=queue_path)
            self.assertEqual(restored.downloads[download_id].subscription_id, "sub_queue")
            self.assertEqual(restored.downloads[download_id].archive_key, "id:queueSubscription")

    def test_subscription_state_sanitizes_malformed_counters_and_paused_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subscriptions.json"
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [{
                    "id": "sub_malformed",
                    "url": "https://www.youtube.com/@astra-channel",
                    "enabled": False,
                    "nextScanAt": None,
                    "lastQueued": "not-a-number",
                    "lastSkipped": "bad",
                }],
                "archive": {},
            }), encoding="utf-8")
            store = self._store(path)
            record = store.list_subscriptions()[0]
            self.assertFalse(record["enabled"])
            self.assertIsNone(record["nextScanAt"])
            self.assertEqual(record["lastQueued"], 0)
            self.assertEqual(record["lastSkipped"], 0)

    def test_subscription_load_clamps_a_future_scan_to_one_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "future.json"
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [{
                    "id": "sub_future",
                    "url": "https://www.youtube.com/@astra-channel",
                    "intervalMinutes": 15,
                    "enabled": True,
                    "nextScanAt": 9999999999,
                }],
                "archive": {},
            }), encoding="utf-8")
            store = self._store(path, clock=lambda: 1000.0)
            self.assertEqual(store.list_subscriptions()[0]["nextScanAt"], 1900.0)

    def test_subscription_load_preserves_over_cap_archive_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive-bound.json"
            entries = {
                "failed": {
                    "status": "failed", "updatedAt": 5000,
                    "url": "https://www.youtube.com/watch?v=failed",
                },
                "complete": {
                    "status": "complete", "updatedAt": 6000,
                    "url": "https://www.youtube.com/watch?v=complete",
                },
                "queued": {
                    "status": "queued", "updatedAt": 1000,
                    "url": "https://www.youtube.com/watch?v=queued",
                },
            }
            path.write_text(json.dumps({
                "schemaVersion": ad.SUBSCRIPTION_SCHEMA_VERSION,
                "subscriptions": [],
                "archive": entries,
            }), encoding="utf-8")
            store = ad.SubscriptionStore(
                path=path,
                reader=ad.load_json_file,
                writer=ad.atomic_write_json,
                max_archive_entries=2,
            )
            self.assertEqual(
                set(store.archive_entries()), {"failed", "complete", "queued"}
            )

    def test_subscription_routes_cover_crud_and_auth_boundary(self):
        token = "s" * 32
        config = FakeConfig({"ServerToken": token})
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "subscriptions.json")
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: ("dl", None),
            )
            api = ad.create_api(
                config,
                ad.DownloadManager(config, FakeHistory()),
                FakeHistory(),
                subscriptions=manager,
            )
            client = api.test_client()
            headers = {"X-Auth-Token": token, "Host": "127.0.0.1"}
            denied = client.get("/subscriptions", headers={"Host": "127.0.0.1"})
            self.assertEqual(denied.status_code, 401)
            created = client.post(
                "/subscriptions",
                json={"url": "https://www.youtube.com/@astra-channel", "intervalMinutes": 30},
                headers=headers,
            )
            self.assertEqual(created.status_code, 201, created.get_json())
            sub_id = created.get_json()["id"]
            listed = client.get("/subscriptions", headers=headers)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.get_json()["subscriptions"][0]["id"], sub_id)
            updated = client.patch(
                f"/subscriptions/{sub_id}",
                json={"enabled": False},
                headers=headers,
            )
            self.assertEqual(updated.status_code, 200)
            self.assertFalse(updated.get_json()["enabled"])
            removed = client.delete(f"/subscriptions/{sub_id}", headers=headers)
            self.assertEqual(removed.status_code, 200)
            self.assertTrue(removed.get_json()["removed"])

    def test_subscription_scan_endpoint_is_rate_limited(self):
        token = "s" * 32

        class FakeSubscriptions:
            def request_scan(self, subscription_id):
                return {"id": subscription_id, "scheduled": True}, None

        config = FakeConfig({"ServerToken": token})
        api = ad.create_api(
            config,
            ad.DownloadManager(config, FakeHistory()),
            FakeHistory(),
            subscriptions=FakeSubscriptions(),
        )
        client = api.test_client()
        headers = {"X-Auth-Token": token, "Host": "127.0.0.1"}

        responses = [
            client.post("/subscriptions/sub_1/scan", headers=headers)
            for _ in range(ad.RATE_LIMIT_DOWNLOAD_MAX + 1)
        ]

        self.assertEqual(
            [response.status_code for response in responses[:-1]],
            [202] * ad.RATE_LIMIT_DOWNLOAD_MAX,
        )
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(
            responses[-1].get_json()["code"], "subscription-scan-rate-limited"
        )
        self.assertIn("Retry-After", responses[-1].headers)

    def test_manual_scan_claims_before_thread_start_and_coalesces_requests(self):
        release = threading.Event()
        probe_started = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "manual-scan.json")
            record, error = store.add_subscription("https://www.youtube.com/@manual")
            self.assertIsNone(error)

            def probe(_url):
                probe_started.set()
                release.wait(2)
                return [], None

            manager = ad.SubscriptionManager(
                store=store,
                probe=probe,
                enqueue=lambda *_args: ("dl", None),
            )
            first, error = manager.request_scan(record["id"])
            self.assertIsNone(error)
            self.assertTrue(first["scheduled"])
            second, error = manager.request_scan(record["id"])
            self.assertIsNone(error)
            self.assertEqual(second, {
                "id": record["id"], "scheduled": False, "scanning": True
            })
            self.assertTrue(probe_started.wait(1))
            release.set()
            deadline = time.time() + 2
            while manager.snapshot()["scanning"] and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(manager.snapshot()["scanning"], [])

    def test_manual_scan_exception_is_logged_and_releases_claim(self):
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "manual-error.json")
            record, error = store.add_subscription("https://www.youtube.com/@manual-error")
            self.assertIsNone(error)
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: ("dl", None),
                logger=logs.append,
            )

            def fail_scan(*_args, **_kwargs):
                raise RuntimeError("manual probe exploded")

            manager.scan_subscription = fail_scan
            result, error = manager.request_scan(record["id"])
            self.assertIsNone(error)
            self.assertTrue(result["scheduled"])
            deadline = time.time() + 2
            while not logs and time.time() < deadline:
                time.sleep(0.01)

            self.assertTrue(any("manual probe exploded" in message for message in logs))
            self.assertEqual(manager.snapshot()["scanning"], [])

    def test_stopping_a_scan_breaks_before_the_next_candidate(self):
        entries = [
            {
                "id": f"stop-video-{index}",
                "title": f"Stop {index}",
                "url": f"https://www.youtube.com/watch?v=stop-video-{index}",
            }
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "stop-scan.json")
            record, error = store.add_subscription("https://www.youtube.com/@stop")
            self.assertIsNone(error)
            queued = []
            manager = None

            def enqueue(_subscription, candidate, _key):
                queued.append(candidate["id"])
                if len(queued) == 1:
                    manager._stop.set()
                return f"dl_{candidate['id']}", None

            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: (entries, None),
                enqueue=enqueue,
            )
            result = manager.scan_subscription(record["id"])

        self.assertEqual(result["queued"], 1)
        self.assertEqual(queued, ["stop-video-0"])

    def test_stop_logs_when_the_scheduler_thread_outlives_the_timeout(self):
        logs = []

        class StuckThread:
            def is_alive(self):
                return True

            def join(self, timeout):
                self.timeout = timeout

        with tempfile.TemporaryDirectory() as tmp:
            manager = ad.SubscriptionManager(
                store=self._store(Path(tmp) / "stop-timeout.json"),
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: ("dl", None),
                logger=logs.append,
            )
            manager._thread = StuckThread()

            manager.stop(timeout=0.1)

        self.assertTrue(any("stop timed out" in message for message in logs))

    def test_subscription_persistence_failure_is_a_retryable_server_error(self):
        token = "s" * 32
        config = FakeConfig({"ServerToken": token})

        def fail_write(*_args, **_kwargs):
            raise OSError("disk full")

        with tempfile.TemporaryDirectory() as tmp:
            store = ad.SubscriptionStore(
                path=Path(tmp) / "subscriptions.json",
                writer=fail_write,
                logger=lambda _message: None,
            )
            manager = ad.SubscriptionManager(
                store=store,
                probe=lambda _url: ([], None),
                enqueue=lambda *_args: ("dl", None),
            )
            api = ad.create_api(
                config,
                ad.DownloadManager(config, FakeHistory()),
                FakeHistory(),
                subscriptions=manager,
            )

            response = api.test_client().post(
                "/subscriptions",
                json={"url": "https://www.youtube.com/@persistence-failure"},
                headers={"X-Auth-Token": token, "Host": "127.0.0.1"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "subscription-persistence-failed")
        self.assertIn("disk space", response.get_json()["error"])


    def test_subscription_scan_registers_shared_yt_dlp_activity(self):
        registry = ad.YTDLPActivityRegistry()
        scan_started = threading.Event()
        release_scan = threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(Path(tmp) / "subscriptions.json")
            record, error = store.add_subscription(
                "https://www.youtube.com/@astra-channel", now=1000,
            )
            self.assertIsNone(error)

            def probe(_url):
                scan_started.set()
                release_scan.wait(2)
                return [], None

            subscription_manager = ad.SubscriptionManager(
                store=store,
                probe=probe,
                enqueue=lambda *_args: (None, "not used"),
                activity_registry=registry,
            )
            queue_manager = ad.DownloadManager(FakeConfig(), FakeHistory())
            queue_manager._dependencies['ytdlp_activity_count'] = registry.active_count
            worker = threading.Thread(
                target=lambda: subscription_manager.scan_subscription(
                    record['id'], now=1000,
                ),
                daemon=True,
            )
            worker.start()
            self.assertTrue(scan_started.wait(1), "subscription probe did not start")
            self.assertEqual(registry.active_count(), 1)
            self.assertEqual(queue_manager.active_count(), 1)
            release_scan.set()
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(registry.active_count(), 0)


class ArchiveExtractionBoundaryTests(unittest.TestCase):
    def _archive(self, root, entries):
        path = Path(root) / 'helper.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        return path

    def test_exact_nested_executable_extracts_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp, [('bundle/bin/deno.exe', b'MZ valid')])
            destination = Path(tmp) / 'deno.exe'
            result = ad.extract_archive_executable_atomic(
                archive, destination, 'deno.exe', max_bytes=32,
            )
            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), b'MZ valid')

    def test_suffix_lookalike_is_rejected_and_existing_binary_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp, [('bundle/evildeno.exe', b'MZ evil')])
            destination = Path(tmp) / 'deno.exe'
            destination.write_bytes(b'known-good')
            with self.assertRaisesRegex(RuntimeError, 'was not found'):
                ad.extract_archive_executable_atomic(
                    archive, destination, 'deno.exe', max_bytes=32,
                )
            self.assertEqual(destination.read_bytes(), b'known-good')

    def test_duplicate_exact_executables_are_rejected_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp, [
                ('one/ffmpeg.exe', b'first'),
                ('two/ffmpeg.exe', b'second'),
            ])
            destination = Path(tmp) / 'ffmpeg.exe'
            with self.assertRaisesRegex(RuntimeError, 'multiple ffmpeg.exe'):
                ad.extract_archive_executable_atomic(
                    archive, destination, 'ffmpeg.exe', max_bytes=32,
                )
            self.assertFalse(destination.exists())

    def test_expanded_executable_over_limit_is_rejected_and_temp_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(tmp, [('ffmpeg.exe', b'x' * 33)])
            destination = Path(tmp) / 'ffmpeg.exe'
            with self.assertRaisesRegex(RuntimeError, 'expands to 33 bytes'):
                ad.extract_archive_executable_atomic(
                    archive, destination, 'ffmpeg.exe', max_bytes=32,
                )
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(tmp).glob('.ffmpeg.exe.*.extract')), [])


class SubscriptionScanReportingTests(unittest.TestCase):
    """A scan that cannot write says so instead of reporting a quiet skip."""

    ENTRIES = [
        {"id": "vid0000001", "title": "First",
         "url": "https://www.youtube.com/watch?v=vid0000001"},
        {"id": "vid0000002", "title": "Second",
         "url": "https://www.youtube.com/watch?v=vid0000002"},
    ]

    def _manager(self, tmpdir, name, failing_after=None):
        subs = subscriptions_module()
        store = subs.SubscriptionStore(path=Path(tmpdir) / name)
        record, error = store.add_subscription("https://www.youtube.com/@astra")
        self.assertIsNone(error)
        if failing_after is not None:
            original = store._save_locked
            calls = {"n": 0}

            def failing_save():
                calls["n"] += 1
                return original() if calls["n"] <= failing_after else False

            store._save_locked = failing_save
        manager = subs.SubscriptionManager(
            store=store,
            probe=lambda _url: (self.ENTRIES, None),
            enqueue=lambda _sub, candidate, _key: (f"dl_{candidate['id']}", None),
        )
        return manager, record

    def test_a_healthy_scan_queues_everything(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, record = self._manager(tmpdir, "ok.json")
            result = manager.scan_subscription(record["id"])
        self.assertEqual((result["queued"], result["skipped"], result["error"]),
                         (2, 0, ""))

    def test_a_second_scan_skips_what_it_already_has(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, record = self._manager(tmpdir, "seen.json")
            manager.scan_subscription(record["id"])
            result = manager.scan_subscription(record["id"])
        self.assertEqual((result["queued"], result["skipped"], result["error"]),
                         (0, 2, ""))

    def test_an_unwritable_archive_is_an_error_not_a_skip(self):
        # This is the case a single boolean collapsed into the one above: the
        # scheduler runs unattended, so a channel that silently stopped
        # downloading reported itself as fully up to date.
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, record = self._manager(tmpdir, "full.json", failing_after=1)
            result = manager.scan_subscription(record["id"])
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertIn("disk space", result["error"])

    def test_a_repeated_failure_is_reported_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager, record = self._manager(tmpdir, "dupe.json", failing_after=1)
            result = manager.scan_subscription(record["id"])
        self.assertEqual(result["error"].count("disk space"), 1)

    def test_the_reserve_outcomes_are_three_distinct_values(self):
        subs = subscriptions_module()
        self.assertEqual(
            len({subs.RESERVE_OK, subs.RESERVE_ALREADY_PRESENT,
                 subs.RESERVE_SAVE_FAILED}),
            3,
        )


if __name__ == "__main__":
    unittest.main()
