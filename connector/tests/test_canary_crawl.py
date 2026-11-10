"""FIX03B: isolated SQLite + mocked website. Never use the installed DB/network."""
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import requests


class CanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.root = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="wewin-canary-tests-")))
        cls.stack.enter_context(patch.dict(os.environ, {"DATABASE_PATH": str(cls.root / "unused.db"),
            "ADMIN_SYNC_TOKEN": "", "ADMIN_SYNC_TOKEN_FILE": "", "AUTO_SYNC_ENABLED": "false",
            "SYNC_SCHEDULE_ARMED": "false", "XIAOZHI_MCP_ENDPOINT": "", "XIAOZHI_MCP_TOKEN": ""}))
        cls.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Real network forbidden")))
        from scripts import canary_crawl
        cls.c = canary_crawl
        cls.stack.enter_context(patch.object(canary_crawl, "schedulers_off"))

    def setUp(self):
        self.folder = self.root / self._testMethodName
        self.folder.mkdir()
        self.database = self.folder / "data" / "fixture.db"
        self.db = self.c.DatabaseManager(self.database)
        self.urls = ["https://wewin.edu.vn/fixture-" + str(i) + "/" for i in range(3)]
        self.db.index_records([self.page(self.urls[0]), self.page("https://wewin.edu.vn/unrelated/")])
        self.db.set_state("crawl_cursor", "55")
        self.directory = self.folder / "run"
        self.directory.mkdir()
        self.before = self.c.snapshot(self.database)
        self.c.backup_sqlite(self.database, self.directory / "before_canary.db")
        self.c.save(self.directory / "baseline.json", self.before)
        self.c.save(self.directory / "manifest_before.json", {"candidate_urls": self.urls})
        self.checkpoint = {"version": 1, "database": str(self.database), "urls": self.urls,
             "attempted": [], "results": {}, "phase": "prepared", "discovery_verified": True}
        self.write_checkpoint()

    @staticmethod
    def page(url, **changes):
        value = {"url": url, "title": "Bài học tiếng Việt", "category": "materials",
                 "content": "Nội dung giáo dục Việt Nam với Relative Clause và Oxford Phonics. " * 5,
                 "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_type": "scraped"}
        value.update(changes)
        return value

    def write_checkpoint(self):
        self.c.save(self.directory / "checkpoint.json", self.checkpoint)

    def results(self):
        self.checkpoint.update(phase="fetched", attempted=self.urls.copy(), results={
            self.urls[0]: {"status": "success", "data": self.page(self.urls[0], title="Metadata mới", category="cambridge")},
            self.urls[1]: {"status": "success", "data": self.page(self.urls[1])},
            self.urls[2]: {"status": "failed", "data": None, "http_status": 503, "reason": "HTTP 503"}})
        self.write_checkpoint()

    def test_plan_cap_and_duplicate(self):
        for urls in (self.urls[:2], self.urls * 2, [self.urls[0]] * 3):
            with self.assertRaises(ValueError): self.c.validate_plan(urls, self.urls)

    def test_plan_origin_manifest_and_normalization(self):
        for url in ("https://example.com/", "https://wewin.edu.vn/not-reviewed/", self.urls[0].rstrip("/")):
            with self.assertRaises((ValueError, self.c.CrawlPolicyError)):
                self.c.validate_plan([*self.urls[:2], url], self.urls)

    def test_allowlist_blocks_unapproved_redirect_before_network(self):
        session = self.c.BudgetSession(self.urls, self.directory)
        with self.assertRaises(self.c.CrawlPolicyError): session.get("https://wewin.edu.vn/unapproved/")
        self.assertFalse(session.ledger)

    def test_prepare_wal_backup_restore(self):
        # Keep a writer handle alive so committed WAL data cannot be missed.
        with contextlib.closing(sqlite3.connect(self.database)) as writer:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("UPDATE pages SET title='WAL fixture' WHERE url=?", (self.urls[0],))
            writer.commit()
            manifest = self.folder / "manifest.json"
            self.c.save(manifest, {"candidate_urls": self.urls})
            report = self.c.prepare(self.database, self.folder / "prepared", manifest, self.urls)
            self.assertEqual(report["backup_restore"], "PASS")
            restored = self.c.snapshot(self.folder / "prepared" / "restore_verified.db")
            self.assertEqual(restored, self.c.snapshot(self.database))

    def test_restore_apply_unicode_fts_metadata_and_unrelated_rows(self):
        self.results()
        report = self.c.apply(self.directory)
        self.assertEqual(report["counts"]["added"], 1)
        self.assertEqual(report["counts"]["updated"], 1)
        self.assertTrue(report["unrelated_pages_schema_cursor_history_unchanged"])
        self.assertEqual(self.db.get_page(self.urls[0])["category"], "cambridge")
        self.assertIn(self.urls[1], {p["url"] for p in self.db.search("giáo dục", limit=100)})
        self.assertTrue(self.db.get_fts_status()["consistent"])
        self.assertEqual(self.c.snapshot(self.directory / "after_restore_verified.db"), self.c.snapshot(self.database))

    def test_apply_is_idempotent_without_new_writes(self):
        self.results()
        self.c.apply(self.directory)
        before = self.c.snapshot(self.database)
        self.assertEqual(self.c.apply(self.directory)["writes"], 0)
        self.assertEqual(self.c.snapshot(self.database), before)

    def test_existing_failed_page_is_completely_unchanged(self):
        self.results()
        self.checkpoint["results"][self.urls[0]] = {"status": "failed", "data": None, "http_status": 503}
        self.write_checkpoint()
        self.c.apply(self.directory)
        self.assertEqual(self.c.snapshot(self.database)["pages"][self.urls[0]], self.before["pages"][self.urls[0]])

    def test_short_result_preserves_seed(self):
        before = json.loads(json.dumps(self.before))
        before["pages"][self.urls[0]]["source_type"] = "seed"
        self.results()
        self.checkpoint["results"][self.urls[0]]["data"]["content"] = "x" * 80
        records, outcomes = self.c.records_from_results(self.checkpoint, before)
        self.assertNotIn(self.urls[0], {r["url"] for r in records})
        self.assertEqual(outcomes[self.urls[0]]["status"], "skipped")

    def test_alias_extracted_url_refused(self):
        self.results()
        self.checkpoint["results"][self.urls[0]]["data"]["url"] = self.urls[1]
        with self.assertRaises(ValueError): self.c.records_from_results(self.checkpoint, self.before)

    def test_apply_refuses_changed_database(self):
        self.results()
        self.db.set_state("crawl_cursor", "56")
        before = self.c.snapshot(self.database)
        with self.assertRaises(RuntimeError): self.c.apply(self.directory)
        self.assertEqual(before, self.c.snapshot(self.database))

    def test_atomic_rollback_on_second_record(self):
        self.results()
        with self.db.get_connection() as conn:
            conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON pages WHEN NEW.url='" + self.urls[1] + "' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before = self.c.snapshot(self.database)
        records, _ = self.c.records_from_results(self.checkpoint, before)
        with self.assertRaises(sqlite3.IntegrityError): self.db.index_records(records)
        self.assertEqual(before, self.c.snapshot(self.database))
        self.assertTrue(self.db.get_fts_status()["consistent"])

    def test_fetch_resume_does_not_refetch_completed_or_ambiguous_request(self):
        self.checkpoint["attempted"] = self.urls.copy()
        self.checkpoint["results"][self.urls[0]] = {"status": "failed", "data": None}
        self.write_checkpoint()
        with patch.object(self.c.WeWinCrawler, "crawl_url_detailed", side_effect=AssertionError("No refetch")):
            report = self.c.fetch(self.directory)
        self.assertEqual(report["http_requests_this_invocation"], 0)
        self.assertEqual(report["results"][self.urls[1]]["reason"], "interrupted_request_requires_review")
        self.assertEqual(self.c.snapshot(self.database), self.before)

    def test_fetch_completed_phase_has_zero_network(self):
        self.results()
        self.assertEqual(self.c.fetch(self.directory)["network_requests"], 0)

    def test_concurrent_sync_lock_blocks_fetch_and_apply(self):
        self.results()
        lock = self.c.SyncLock(self.database.parent / "sync.lock")
        lock.acquire("fixture")
        try:
            with self.assertRaises(RuntimeError): self.c.apply(self.directory)
            self.checkpoint["phase"] = "prepared"
            self.write_checkpoint()
            with self.assertRaises(RuntimeError): self.c.fetch(self.directory)
        finally:
            lock.release()
        self.assertEqual(self.c.snapshot(self.database), self.before)

    def test_evidence_rate_limit_minimum_two_seconds(self):
        sleeps = []
        client = self.c.EvidenceHttp(self.directory, sleep=sleeps.append, clock=lambda: 10)
        client._last_request = 10
        client.delay = 0.8
        client._rate_limit()
        self.assertEqual(sleeps, [2.0])

    def test_iframe_link_only_is_not_knowledge(self):
        from src.crawler.extractor import PageExtractor
        html = '<html><head><title>IELTS form</title><meta name="description" content="' + 'description ' * 20 + '"></head><body><iframe src="https://docs.google.com/forms/example"></iframe></body></html>'
        self.assertIsNone(PageExtractor.clean_html(html, self.urls[0]))

    def test_real_text_can_keep_attachment_reference(self):
        from src.crawler.extractor import PageExtractor
        html = '<html><body><article>' + 'Kiến thức tiếng Việt hữu ích. ' * 10 + '</article><iframe src="https://docs.google.com/document/example"></iframe></body></html>'
        page = PageExtractor.clean_html(html, self.urls[0])
        self.assertIn('Tài liệu', page['content'])
        self.assertIn('Kiến thức', page['content'])

    def test_category_exam_tokens_do_not_match_ket_hop(self):
        from src.crawler.extractor import PageExtractor
        for slug, expected in [('chuong-trinh-ket-hop-tieng-anh', 'general'),
                               ('complete-ket', 'cambridge'), ('tieng-anh-6-ket', 'cambridge'),
                               ('pre_flyers-unit-6', 'cambridge'), ('pet', 'cambridge'),
                               ('competition', 'general'), ('luyen-ielts', 'ielts')]:
            self.assertEqual(PageExtractor._infer_category('https://wewin.edu.vn/' + slug + '/', ''), expected)

    def test_offline_reextract_uses_archived_bytes_and_no_network(self):
        import hashlib
        self.results()
        for url in self.urls:
            name = hashlib.sha256(url.encode()).hexdigest()
            content = ('<html><head><title>Bài học</title></head><body><article>' + 'Nội dung tiếng Việt chính xác. ' * 10 + '</article></body></html>').encode()
            (self.directory / (name + '.response')).write_bytes(content)
            self.c.save(self.directory / (name + '.response.json'), {'final_url': url,
                'http_status': 200, 'content_type': 'text/html', 'sha256': hashlib.sha256(content).hexdigest()})
        report = self.c.reextract(self.directory)
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(set(report['results'].values()), {'success'})
        self.assertEqual(self.c.snapshot(self.database), self.before)

    def test_commit_acknowledgement_recovery_finishes_verification(self):
        self.results()
        records, _ = self.c.records_from_results(self.checkpoint, self.before)
        self.db.index_records(records)
        committed = self.c.snapshot(self.database)
        self.c.save(self.directory / 'trial_snapshot.json', committed)
        report = self.c.apply(self.directory)
        self.assertEqual(report['phase'], 'applied')
        self.assertTrue((self.directory / 'after_restore_verified.db').exists())
        self.assertEqual(self.c.snapshot(self.database), committed)


if __name__ == "__main__":
    unittest.main()
