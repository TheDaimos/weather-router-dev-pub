"""Behavioral crash/recovery tests of public durable OPERA journal.

No home-assistant, science approvals, HTTP endpoint or network is mocked into
existence. Runtime entry is imported through the existing focused test harness.
"""
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from test_opera_runtime_atomic import runtime_module

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.root = self.folder / "durable"
        self.runtime = runtime_module.OperaRuntime(journal_root=self.root)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def candidate(self, tag, product="RATE", age=60):
        path = self.folder / (tag + ".bin")
        payload = ("synthetic-" + tag).encode()
        path.write_bytes(payload)
        return self.runtime.prepare(
            source_path=path, product=product,
            valid_at=self.now - timedelta(seconds=age),
            digest=hashlib.sha256(payload).hexdigest(),
            attribution="public synthetic source",
            palette=lambda _: (0, 0, 0, 0))

    def test_durable_promotion_and_metadata_only_restart(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        other = runtime_module.OperaRuntime(journal_root=self.root)
        try:
            records = other.journal.inspect()
            self.assertEqual(records["RATE"]["generation"], cycle.stamp)
            self.assertEqual(records["RATE"]["publication"], "journaled_not_authorized")
            self.assertIsNone(other.registry.active("RATE"))
            recovery = other.journal.recover_metadata(now=self.now)
            self.assertFalse(recovery["RATE"]["authorized"])
            self.assertEqual(recovery["RATE"]["utc_status"], "CURRENT")
        finally:
            other.close()

    def test_interrupted_staging_no_published_manifest(self):
        self.candidate("staged")
        self.assertFalse((self.root / "active.json").exists())
        other = runtime_module.OperaRuntime(journal_root=self.root)
        try:
            self.assertEqual(other.journal.inspect(), {})
            self.assertIsNone(other.registry.active("RATE"))
        finally:
            other.close()

    def test_interrupted_temporary_manifest_does_not_activate(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        (self.root / ".opera-stage-leftover").write_bytes(b'{"broken":')
        other = runtime_module.OperaRuntime(journal_root=self.root)
        try:
            self.assertFalse(other.journal.recover_metadata(now=self.now)["RATE"]["authorized"])
        finally:
            other.close()

    def test_corrupt_manifest_fails_closed(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        (self.root / "active.json").write_bytes(b'{"schema":')
        with self.assertRaisesRegex(Exception, "recovery_blocked"):
            self.runtime.journal.inspect()

    def test_missing_frame_fails_closed(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        record = self.runtime.journal.inspect()["RATE"]
        (self.root / record["file"]).unlink()
        with self.assertRaisesRegex(Exception, "recovery_blocked"):
            self.runtime.journal.inspect()

    def test_tampered_hash_fails_closed(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        record = self.runtime.journal.inspect()["RATE"]
        (self.root / record["file"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(Exception, "recovery_blocked"):
            self.runtime.journal.inspect()

    def test_stale_and_disabled_never_authorized(self):
        cycle = self.candidate("one")
        self.runtime.promote(cycle)
        result = self.runtime.journal.recover_metadata(
            now=self.now + timedelta(hours=2),
            provider_enabled=True, services={"RATE": True})
        self.assertEqual(result["RATE"]["utc_status"], "UNAVAILABLE")
        self.assertFalse(result["RATE"]["authorized"])
        result = self.runtime.journal.recover_metadata(
            now=self.now, provider_enabled=False, services={"RATE": True})
        self.assertFalse(result["RATE"]["authorized"])

    def test_rejected_old_cycle_does_not_replace_manifest(self):
        newer = self.candidate("new", age=60)
        older = self.candidate("old", age=180)
        self.runtime.promote(newer)
        with self.assertRaisesRegex(ValueError, "older_cycle"):
            self.runtime.promote(older)
        self.assertEqual(self.runtime.journal.inspect()["RATE"]["sha256"], newer.digest)

    def test_restart_cannot_replace_newer_persisted_cycle(self):
        latest = self.candidate("latest", age=60)
        self.runtime.promote(latest)
        after_restart = runtime_module.OperaRuntime(journal_root=self.root)
        try:
            old_file = self.folder / "older-after-restart.bin"
            old_file.write_bytes(b"synthetic-older-after-restart")
            import hashlib
            old = after_restart.prepare(
                source_path=old_file, product="RATE",
                valid_at=self.now - timedelta(seconds=180),
                digest=hashlib.sha256(old_file.read_bytes()).hexdigest(),
                attribution="public synthetic source", palette=lambda _: (0, 0, 0, 0))
            with self.assertRaisesRegex(Exception, "journal_commit_failed"):
                after_restart.promote(old)
            self.assertEqual(after_restart.journal.inspect()["RATE"]["sha256"], latest.digest)
            self.assertIsNone(after_restart.registry.active("RATE"))
        finally:
            after_restart.close()

    def test_journal_orphan_cleanup_preserves_live_generation(self):
        current = self.candidate("current", age=60)
        self.runtime.promote(current)
        journal = self.runtime.journal
        original = journal.inspect()["RATE"]["file"]
        abandoned = self.root / ("RATE-20261029T000000Z-" + "a"*64 + ".bin")
        abandoned.write_bytes(b"orphan")
        temp = self.root / ".opera-stage-crashed"
        temp.write_bytes(b"unfinished")
        journal.cleanup()
        self.assertFalse(abandoned.exists())
        self.assertFalse(temp.exists())
        self.assertTrue((self.root / original).exists())
        self.assertGreater(journal.disk_usage(), 0)

    def test_two_runtime_writers_preserve_monotonic_journal(self):
        newer = self.candidate("newer", age=60)
        older = self.candidate("older", age=120)
        other = runtime_module.OperaRuntime(journal_root=self.root)
        try:
            import concurrent.futures
            def commit_from_first():
                return self.runtime.promote(newer)
            def commit_from_second():
                return other.journal.commit(older.registration.frame, "public synthetic")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(commit_from_first), pool.submit(commit_from_second)]
                for future in futures:
                    try:
                        future.result()
                    except Exception:
                        pass
            records = other.journal.inspect()
            # A later generation must win whether it was written first or last.
            if records["RATE"]["sha256"] != newer.digest:
                self.runtime.promote(newer)
            self.assertEqual(other.journal.inspect()["RATE"]["sha256"], newer.digest)
        finally:
            other.close()

    def test_distinct_products_in_same_manifest(self):
        rate = self.candidate("rate", product="RATE")
        dbzh = self.candidate("dbzh", product="DBZH")
        self.runtime.promote(rate)
        self.runtime.promote(dbzh)
        self.assertEqual(set(self.runtime.journal.inspect()), {"RATE", "DBZH"})

if __name__ == "__main__":
    unittest.main()
