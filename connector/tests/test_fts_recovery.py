"""FIX 02 regression: temporary databases only, network and real sync forbidden.

python -B -m unittest tests.test_fts_recovery -v
Optional WEWIN_FTS_BACKUP_FIXTURE names a sealed backup; it is opened READ ONLY
and copied before testing. No test ever opens the configured production DB.
"""
import contextlib
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unicodedata
import unittest
from unittest.mock import patch


class FTSRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="wewin-fts-regression-")))
        cls.stack.enter_context(patch.dict(os.environ, {
            "DATABASE_PATH": str(cls.temp / "unused-default.db"),
            "KNOWLEDGE_JSON_PATH": str(cls.temp / "unused-default.json"),
            "AUTO_SYNC_ENABLED": "false", "ADMIN_SYNC_TOKEN": "", "ADMIN_SYNC_TOKEN_FILE": "",
            "XIAOZHI_MCP_ENDPOINT": "", "XIAOZHI_MCP_TOKEN": "",
        }))
        logger = types.ModuleType("src.utils.logger")
        logger.logger = logging.getLogger("fts-regression-isolated")
        logger.logger.handlers = [logging.NullHandler()]
        logger.logger.propagate = False
        cls.stack.enter_context(patch.dict(sys.modules, {"src.utils.logger": logger}))
        cls.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")))
        cls.stack.enter_context(patch("websockets.connect", side_effect=AssertionError("Cloud forbidden")))
        from src.storage.db import DatabaseManager, calculate_content_hash
        cls.DatabaseManager = DatabaseManager
        cls.content_hash = staticmethod(calculate_content_hash)

    def setUp(self):
        self.db = self.DatabaseManager(self.temp / (self._testMethodName + ".db"))

    @staticmethod
    def record(slug="fixture", **changes):
        value = {"url": "https://wewin.edu.vn/" + slug + "/", "title": "Fixture lesson",
                 "content": "An English lesson with searchable originalword content.",
                 "category": "materials", "source_type": "scraped"}
        value.update(changes)
        return value

    def assert_consistent(self, db=None):
        status = (db or self.db).get_fts_status()
        self.assertTrue(status["consistent"], status)
        self.assertEqual(status["fts_rows"], status["eligible_pages"])

    def fts_rows(self):
        with self.db.get_connection() as conn:
            return [tuple(row) for row in conn.execute("SELECT rowid,* FROM pages_fts ORDER BY rowid")]

    def test_01_index_new_page(self):
        report = self.db.index_records([self.record()])
        self.assertEqual(report["added"], 1)
        self.assertEqual(len(self.db.search("originalword")), 1)
        self.assert_consistent()

    def test_02_update_page_preserves_id_and_removes_old_terms(self):
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn: original_id = conn.execute("SELECT id FROM pages").fetchone()[0]
        changed = self.record(content="Updated replacementword lesson content.")
        self.assertTrue(self.db.update_page_incremental(changed, is_new=False))
        with self.db.get_connection() as conn: self.assertEqual(conn.execute("SELECT id FROM pages").fetchone()[0], original_id)
        self.assertEqual(self.db.search("originalword"), [])
        self.assertEqual(len(self.db.search("replacementword")), 1)
        self.assert_consistent()

    def test_03_index_one_seed_does_not_remove_old_pages(self):
        self.db.index_records([self.record()])
        seed = self.record("seed", content="Independent seedword knowledge.", source_type="seed")
        self.db.index_records([seed])
        self.assertEqual(len(self.db.search("originalword")), 1)
        self.assertEqual(len(self.db.search("seedword")), 1)
        self.assertEqual(self.db.get_fts_status()["pages"], 2)

    def test_04_duplicate_urls_are_canonicalized_last_valid_record_wins(self):
        records = [self.record(url="HTTPS://WEWIN.EDU.VN/fixture?utm_source=fixture#ignored"),
                   self.record(content="Last version replacementword content.")]
        report = self.db.index_records(records)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual(self.db.get_fts_status()["pages"], 1)
        self.assertEqual(self.db.search("originalword"), [])
        self.assertEqual(len(self.db.search("replacementword")), 1)
        self.assert_consistent()

    def test_05_title_and_category_updates_refresh_fts(self):
        self.db.index_records([self.record()])
        updated = self.record(title="newtitleword course", category="newcategoryword")
        self.db.update_page_incremental(updated, is_new=False)
        self.assertEqual(len(self.db.search("newtitleword")), 1)
        self.assertEqual(len(self.db.search("newcategoryword")), 1)
        with self.db.get_connection() as conn:
            conn.execute("UPDATE pages SET title='rawtitleword',category='rawcategoryword' WHERE url=?", (updated["url"],))
        self.assertEqual(self.db.search("newtitleword"), [])
        self.assertEqual(len(self.db.search("rawcategoryword")), 1)
        self.assert_consistent()

    def test_06_english_and_vietnamese_search_use_fts_without_fallback(self):
        self.db.index_records([self.record(title="Chương trình tiếng Anh", content="Học bổng Cambridge và giáo trình Oxford dành cho học sinh.")])
        with patch.object(self.db, "_fallback_like_search", side_effect=AssertionError("FTS fallback must not be used")):
            for query in ["Cambridge", "Oxford", "học bổng", "giáo trình", "hoc bong", unicodedata.normalize("NFD", "giáo trình")]:
                self.assertTrue(self.db.search(query), query)

    def test_07_relative_clause_and_oxford_phonics_pages(self):
        self.db.index_records([
            self.record("game-ve-relative-clause", title="Relative Clause", content="Relative Clause activities and English lesson practice."),
            self.record("bo-sach-day-phat-am-tieng-anh-oxford-phonics-world", title="Oxford Phonics World", content="Bộ sách Oxford Phonics World giúp học sinh luyện phát âm."),
        ])
        for query, slug in [("Relative Clause", "game-ve-relative-clause"), ("Oxford Phonics", "bo-sach-day-phat-am-tieng-anh-oxford-phonics-world")]:
            self.assertIn("https://wewin.edu.vn/" + slug + "/", {r["url"] for r in self.db.search(query, 10)})
        self.assert_consistent()

    def test_08_rebuild_repairs_missing_duplicate_orphan_and_stale_fts(self):
        self.db.index_records([self.record("one"), self.record("two")])
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM pages_fts")
            conn.execute("INSERT INTO pages_fts(title,content,category,url) VALUES('stale','stale','wrong',?)", (self.record("one")["url"],))
            conn.execute("INSERT INTO pages_fts(title,content,category,url) VALUES('duplicate','duplicate','wrong',?)", (self.record("one")["url"],))
            conn.execute("INSERT INTO pages_fts(title,content,category,url) VALUES('orphan','orphan','wrong','https://wewin.edu.vn/orphan/')")
        before = self.db.get_data_fingerprints()
        self.assertFalse(self.db.get_fts_status()["consistent"])
        self.db.rebuild_fts(expected_snapshot=before)
        self.assertEqual(self.db.get_data_fingerprints(), before)
        self.assert_consistent()

    def test_09_batch_failure_rolls_back_pages_and_fts(self):
        self.db.index_records([self.record()])
        before, old_fts = self.db.get_data_fingerprints(), self.fts_rows()
        with self.db.get_connection() as conn:
            conn.execute("""CREATE TRIGGER fixture_abort BEFORE INSERT ON pages
                WHEN NEW.url='https://wewin.edu.vn/abort/' BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.index_records([self.record("first-new"), self.record("abort")])
        self.assertEqual(self.db.get_data_fingerprints(), before)
        self.assertEqual(self.fts_rows(), old_fts)

    def test_10_repeated_index_is_idempotent_and_preserves_other_pages(self):
        from src.crawler.curated_seeds import get_curated_seeds
        self.db.index_records([self.record()])
        for _ in range(5):
            self.db.index_records(get_curated_seeds())
            self.db.index_records([self.record()])
            self.assertEqual(self.db.get_fts_status()["pages"], 5)
            self.assertEqual(len(self.db.search("originalword")), 1)
            self.assert_consistent()

    def test_11_empty_and_invalid_inputs_do_not_overwrite_valid_cache(self):
        self.db.index_records([self.record()])
        for bad in ["", " \n\t\u00a0", None, b"invalid bytes"]:
            report = self.db.index_records([self.record(content=bad)])
            self.assertEqual(len(report["skipped"]), 1)
        self.assertEqual(len(self.db.search("originalword")), 1)
        self.assert_consistent()

    def test_12_empty_cached_pages_are_retained_but_not_indexed(self):
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn:
            conn.execute("INSERT INTO pages(url,title,content,retrieved_at) VALUES('https://wewin.edu.vn/empty/','Empty title','','fixture')")
            conn.execute("INSERT INTO pages(url,title,content,retrieved_at) VALUES('https://wewin.edu.vn/space/','Whitespace title',?,'fixture')", (" \n\t\u00a0",))
        before = self.db.get_data_fingerprints()
        result = self.db.rebuild_fts()
        self.assertEqual((result["pages"], result["fts_rows"], result["excluded_pages"]), (3, 1, 2))
        self.assertEqual(self.db.get_data_fingerprints(), before)

    def test_13_rebuild_failure_rolls_back_fts_and_trigger_ddl(self):
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn:
            for name in ["wewin_pages_ai_fts_v2", "wewin_pages_au_fts_v2", "wewin_pages_ad_fts_v2"]:
                conn.execute("DROP TRIGGER " + name)
            conn.execute("DELETE FROM pages_fts")
        before = self.fts_rows()
        with patch.object(self.db, "_fts_status", return_value={"consistent": False}):
            with self.assertRaises(RuntimeError): self.db.rebuild_fts()
        self.assertEqual(self.fts_rows(), before)
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'wewin_pages_%_fts_v2'").fetchone()[0], 0)

    def test_14_seed_sections_are_consolidated_without_loss(self):
        from src.crawler.curated_seeds import get_curated_seeds
        seeds = get_curated_seeds()
        self.assertEqual(len(seeds), len({r["url"] for r in seeds}))
        self.assertEqual(len(seeds), 4)
        self.db.index_records(seeds)
        for query in ["hotline", "học phí", "9 tuổi", "Cambridge", "IELTS"]:
            self.assertTrue(self.db.search(query), query)
        self.assert_consistent()

    def test_15_seed_cannot_replace_existing_scraped_page(self):
        original = self.record()
        self.db.index_records([original])
        before = self.db.get_data_fingerprints()
        report = self.db.index_records([self.record(content="A different seedword section.", source_type="seed")])
        self.assertEqual(report["seed_protected"], 1)
        self.assertEqual(self.db.get_data_fingerprints(), before)

    def test_16_sync_detects_metadata_changes_with_mock_crawler_only(self):
        from src.sync.sync_engine import SyncEngine
        class Crawler:
            page = FTSRecoveryTests.record("metadata-fixture", content="Stable metadata fixture lesson content. Stable metadata fixture lesson content. Stable metadata fixture lesson content. Stable metadata fixture lesson content. ")
            def get_batch_urls(self, **kwargs): return [self.page["url"]], 0, 1, 1
            def crawl_url_detailed(self, url): return {"status": "success", "data": dict(self.page), "http_status": 200}
        class Lock:
            def acquire(self, **kwargs): pass
            def release(self, **kwargs): pass
        crawler = Crawler()
        engine = SyncEngine(db=self.db, crawler=crawler)
        engine.lock = Lock()
        with patch.object(engine, "_export_knowledge_json", return_value=None):
            self.assertEqual(engine.run_sync().pages_added, 1)
            self.assertEqual(engine.run_sync().pages_unchanged, 1)
            crawler.page = {**crawler.page, "title": "Changed metatitleword", "category": "metacategoryword"}
            self.assertEqual(engine.run_sync().pages_updated, 1)
        self.assertTrue(self.db.search("metatitleword"))
        self.assertTrue(self.db.search("metacategoryword"))
        self.assert_consistent()

    def test_17_supplied_wrong_hash_is_recomputed(self):
        self.db.index_records([self.record(content_hash="incorrect")])
        page = self.db.get_page(self.record()["url"])
        self.assertEqual(page["content_hash"], self.content_hash(page["content"]))

    def test_18_delete_and_url_update_triggers_preserve_consistency(self):
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn:
            conn.execute("UPDATE pages SET url='https://wewin.edu.vn/renamed/',id=999")
        self.assertEqual(self.db.search("originalword"), [])  # Changing primary ID revokes publication.
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT url FROM pages_fts WHERE pages_fts MATCH ?", ("originalword",)).fetchone()[0], "https://wewin.edu.vn/renamed/")
        self.assert_consistent()
        with self.db.get_connection() as conn: conn.execute("DELETE FROM pages")
        self.assertEqual(self.db.get_fts_status()["fts_rows"], 0)

    def test_19_backup_includes_uncheckpointed_wal_and_can_be_restored(self):
        from scripts.repair_fts import backup_sqlite
        with self.db.get_connection() as writer:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            self.db.index_records([self.record()])
            self.assertGreater(Path(str(self.db.db_path) + "-wal").stat().st_size, 0)
            backup = self.temp / "wal-backup.db"
            restored = self.temp / "wal-restored.db"
            backup_sqlite(self.db.db_path, backup)
            backup_sqlite(backup, restored)
            restored_db = self.DatabaseManager.open_existing(restored)
            self.assertTrue(restored_db.search("originalword"))
            self.assertEqual(restored_db.get_data_fingerprints(), self.db.get_data_fingerprints())

    def test_20_stale_snapshot_aborts_repair_without_losing_new_data(self):
        self.db.index_records([self.record()])
        original = self.db.get_data_fingerprints()
        self.db.index_records([self.record("newer-page")])
        current = self.db.get_data_fingerprints()
        with self.assertRaises(RuntimeError): self.db.rebuild_fts(expected_snapshot=original)
        self.assertEqual(self.db.get_data_fingerprints(), current)
        self.assert_consistent()

    def test_21_rehearsal_only_never_changes_source_database(self):
        from scripts.repair_fts import repair
        self.db = self.DatabaseManager(self.temp / "rehearsal-source" / "source.db")
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn: conn.execute("DELETE FROM pages_fts")
        before = self.fts_rows()
        report = repair(self.db.db_path, self.temp / "rehearsal-backup", apply=False)
        self.assertFalse(report["applied"])
        self.assertTrue(report["trial_after"]["consistent"])
        self.assertEqual(self.fts_rows(), before)

    def test_23_apply_pipeline_is_verified_on_isolated_database(self):
        from scripts.repair_fts import repair
        self.db = self.DatabaseManager(self.temp / "apply-source" / "source.db")
        self.db.index_records([self.record()])
        with self.db.get_connection() as conn: conn.execute("DELETE FROM pages_fts")
        before = self.db.get_data_fingerprints()
        report = repair(self.db.db_path, self.temp / "apply-backup", apply=True)
        self.assertTrue(report["backup_restore_verified"] and report["applied"])
        self.assertEqual(self.db.get_data_fingerprints(), before)
        self.assert_consistent()

    def test_24_existing_sync_lock_prevents_maintenance(self):
        from scripts.repair_fts import repair
        self.db = self.DatabaseManager(self.temp / "locked-source" / "source.db")
        lock = self.db.db_path.parent / "sync.lock"
        lock.write_text("isolated fixture lock", encoding="utf-8")
        with self.assertRaises(RuntimeError): repair(self.db.db_path, self.temp / "locked-backup", apply=True)
        self.assertTrue(lock.exists())

    def test_25_actual_backup_restores_old_state_after_repair(self):
        fixture = os.environ.get("WEWIN_FTS_BACKUP_FIXTURE")
        if not fixture:
            self.skipTest("Set WEWIN_FTS_BACKUP_FIXTURE to a sealed SQLite backup")
        from scripts.repair_fts import backup_sqlite, inspect_database
        source = Path(fixture).resolve(strict=True)
        copied = self.temp / "rollback-copy.db"
        backup_sqlite(source, copied)
        original = inspect_database(copied)
        self.DatabaseManager.open_existing(copied).rebuild_fts()
        with contextlib.closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
            with contextlib.closing(sqlite3.connect(copied)) as writer:
                reader.backup(writer)
        self.assertEqual(inspect_database(copied), original)
        with contextlib.closing(sqlite3.connect(copied)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 0)

    def test_22_actual_backup_recovery_on_a_copy_only(self):
        fixture = os.environ.get("WEWIN_FTS_BACKUP_FIXTURE")
        if not fixture:
            self.skipTest("Set WEWIN_FTS_BACKUP_FIXTURE to a sealed SQLite backup")
        from scripts.repair_fts import backup_sqlite, inspect_database, verify_target_queries
        source = Path(fixture).resolve(strict=True)
        original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        copied = self.temp / "actual-backup-copy.db"
        backup_sqlite(source, copied)
        copied_db = self.DatabaseManager.open_existing(copied)
        before = inspect_database(copied)
        after = copied_db.rebuild_fts(expected_snapshot=before["data_fingerprints"])
        self.assertTrue(after["consistent"])
        self.assertEqual(copied_db.get_data_fingerprints(), before["data_fingerprints"])
        from scripts.prepare_knowledge_access import migrate
        migrate(copied)  # Explicit publication review on isolated old-schema copy.
        # The old Relative Clause body is branding/footer only; preserve raw FTS,
        # but the new public policy must withhold it until lesson content exists.
        with copied_db.get_connection() as conn:
            for query in ('"Relative Clause"', '"Oxford Phonics"'):
                self.assertGreater(conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", (query,)).fetchone()[0], 0)
        self.assertEqual(len(verify_target_queries(copied_db)), 1)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_sha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
