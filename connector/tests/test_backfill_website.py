"""Initial backfill regression: temporary SQLite, mocked HTTP, no real schedulers."""
import contextlib
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import requests


class BackfillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.root = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix="wewin-backfill-tests-")))
        cls.stack.enter_context(patch.dict(os.environ, {"DATABASE_PATH": str(cls.root / "unused.db"),
            "ADMIN_SYNC_TOKEN": "", "ADMIN_SYNC_TOKEN_FILE": "", "AUTO_SYNC_ENABLED": "false",
            "SYNC_SCHEDULE_ARMED": "false", "XIAOZHI_MCP_ENDPOINT": "", "XIAOZHI_MCP_TOKEN": ""}))
        cls.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("Real network forbidden")))
        from scripts import backfill_website
        cls.b = backfill_website
        cls.stack.enter_context(patch.object(backfill_website, "schedulers_off"))

    def setUp(self):
        self.directory = self.root / self._testMethodName
        self.directory.mkdir()
        (self.directory / "records").mkdir()
        self.database = self.directory / "data" / "fixture.db"
        self.db = self.b.DatabaseManager(self.database)
        self.url = "https://wewin.edu.vn/fixture/"
        self.db.index_records([self.page(self.url), self.page("https://wewin.edu.vn/unrelated/", content="Separate educational oldword knowledge. " * 10)])
        self.db.set_state("crawl_cursor", "55")
        self.before = self.b.snapshot(self.database)
        self.cp = {"version": 1, "phase": "prepared", "database": str(self.database),
            "schema": self.before["schema"], "control_fingerprints": self.before["fingerprints"],
            "expected_pages": self.b.row_hashes(self.before), "written_urls": [], "outcomes": {},
            "manifest": [self.url], "intent": None, "inflight": None, "active_batch": None,
            "batches": [], "next_batch_after": 0, "consecutive_failed_urls": 0}
        self.b.save(self.directory / "checkpoint.json", self.cp)
        self.b.save(self.directory / "baseline.json", self.before)

    @staticmethod
    def page(url, **changes):
        value = {"url": url, "title": "Bài học tiếng Việt", "category": "materials",
            "content": "Kiến thức tiếng Việt và English lesson phù hợp cho học sinh. " * 10,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_type": "scraped"}
        value.update(changes)
        return value

    def result(self, **changes):
        return {"status": "success", "data": self.page(self.url, **changes)}

    def prepare_intent(self):
        record, outcome = self.b.result_record(self.result(title="Metadata mới", category="cambridge"), self.before["pages"][self.url], {})
        self.b.save(self.directory / "records" / "prepared.json", record)
        self.cp["intent"] = {"url": self.url, "old_row_hash": self.b.digest(self.before["pages"][self.url]), "record_file": "records/prepared.json", "outcome": outcome}
        self.cp["inflight"] = self.url
        self.b.save(self.directory / "checkpoint.json", self.cp)
        return record

    def test_admit_unicode_title_category_hash(self):
        record, outcome = self.b.result_record(self.result(title="Tiêu đề mới", category="ielts"), self.before["pages"][self.url], {})
        self.assertEqual(outcome["status"], "updated")
        self.assertEqual(record["content_hash"], self.b.calculate_content_hash(record["content"]))
        self.assertEqual(record["category"], "ielts")

    def test_short_and_form_link_only_requires_review(self):
        for content in ("short", "[Tài liệu Google Form https://docs.google.com/forms/example]"):
            record, outcome = self.b.result_record(self.result(content=content), None, {})
            self.assertIsNone(record)
            self.assertEqual(outcome["status"], "review")

    def test_sensitive_internal_credentials_are_not_admitted(self):
        for text in ("mật khẩu", "password", "nội bộ", "internal use", "confidential"):
            record, outcome = self.b.result_record(self.result(content=("Nội dung " * 50) + text), None, {})
            self.assertIsNone(record)
            self.assertIn("internal", outcome["reason"])

    def test_seed_and_shrink_are_preserved(self):
        seed = {**self.before["pages"][self.url], "source_type": "seed"}
        self.assertIsNone(self.b.result_record(self.result(), seed, {})[0])
        self.assertIsNone(self.b.result_record(self.result(content="x" * 150), self.before["pages"][self.url], {})[0])

    def test_duplicate_content_requires_review(self):
        content = self.page(self.url)["content"]
        record, outcome = self.b.result_record(self.result(), None, {self.b.calculate_content_hash(content): ["https://wewin.edu.vn/other/"]})
        self.assertIsNone(record)
        self.assertIn("duplicate", outcome["reason"])

    def test_error_and_empty_does_not_modify_cache(self):
        for status in ("failed", "skipped"):
            self.assertIsNone(self.b.result_record({"status": status, "data": None, "http_status": 503}, self.before["pages"][self.url], {})[0])
        self.assertEqual(self.b.snapshot(self.database), self.before)

    def test_commit_intent_and_postcommit_recovery_no_rewrite(self):
        record = self.prepare_intent()
        self.db.index_records([record])  # Simulated crash after SQL commit, before JSON acknowledgement.
        expected = self.b.snapshot(self.database)
        with patch.object(self.b.DatabaseManager, "index_records", side_effect=AssertionError("Already committed")):
            self.b.commit_intent(self.database, self.directory, self.cp)
        self.assertEqual(self.b.snapshot(self.database), expected)
        self.assertIsNone(self.cp["intent"])
        self.assertEqual(self.cp["outcomes"][self.url]["status"], "updated")
        self.b.check_state(self.database, self.cp)

    def test_precommit_intent_resumes_and_preserves_unrelated(self):
        self.prepare_intent()
        self.b.commit_intent(self.database, self.directory, self.cp)
        self.assertEqual(self.db.get_page(self.url)["title"], "Metadata mới")
        self.assertEqual(self.b.snapshot(self.database)["pages"]["https://wewin.edu.vn/unrelated/"], self.before["pages"]["https://wewin.edu.vn/unrelated/"])
        self.b.check_state(self.database, self.cp)

    def test_external_writer_blocks_intent(self):
        self.prepare_intent()
        self.db.index_records([self.page("https://wewin.edu.vn/unrelated/", title="external")])
        before = self.b.snapshot(self.database)
        with self.assertRaises(self.b.SafetyStop): self.b.commit_intent(self.database, self.directory, self.cp)
        self.assertEqual(self.b.snapshot(self.database), before)

    def test_atomic_rollback_preserves_old_fts(self):
        self.prepare_intent()
        with self.db.get_connection() as conn:
            conn.execute("CREATE TRIGGER fixture_fail BEFORE UPDATE ON pages BEGIN SELECT RAISE(ABORT,'fixture'); END")
        # update schema expectation only in this fixture, to exercise writer rollback.
        self.cp["schema"] = self.b.snapshot(self.database)["schema"]
        before = self.b.snapshot(self.database)
        with self.assertRaises(sqlite3.IntegrityError): self.b.commit_intent(self.database, self.directory, self.cp)
        self.assertEqual(self.b.snapshot(self.database), before)
        self.assertTrue(self.db.get_fts_status()["consistent"])

    def test_missing_fts_and_changed_cursor_stop(self):
        with self.db.get_connection() as conn: conn.execute("DELETE FROM pages_fts")
        with self.assertRaises(self.b.SafetyStop): self.b.check_state(self.database, self.cp)
        self.db.rebuild_fts()
        self.db.set_state("crawl_cursor", "56")
        with self.assertRaises(self.b.SafetyStop): self.b.check_state(self.database, self.cp)

    def test_disk_pressure_stops(self):
        with patch.object(self.b.shutil, "disk_usage", return_value=type("Usage", (), {"free": 10})()):
            with self.assertRaises(self.b.SafetyStop): self.b.disk_check(self.directory)

    def test_staff_policy_without_request(self):
        self.assertTrue(self.b.policy_review("https://wewin.edu.vn/thong-tin-nhan-vien/"))
        self.assertFalse(self.b.policy_review("https://wewin.edu.vn/ielts-speaking/"))

    def test_three_server_errors_open_circuit_before_fourth_request(self):
        class Session:
            headers = {}
            def get(inner, url, **kwargs):
                response = requests.Response()
                response.url, response.status_code = url, 503
                response._content, response._content_consumed = b"temporary", True
                return response
        now = [0.0]
        session = self.b.BackfillSession([self.url], self.directory, threading.Event(), Session(),
            clock=lambda: now[0], wait=lambda seconds: now.__setitem__(0, now[0] + seconds))
        session.get(self.url); session.get(self.url)
        with self.assertRaises(self.b.SafetyStop): session.get(self.url)
        self.assertEqual(len(session.ledger), 3)

    def test_redirect_allowlist_and_manual_stop(self):
        session = self.b.BackfillSession([self.url], self.directory, threading.Event())
        with self.assertRaises(self.b.CrawlPolicyError if hasattr(self.b, 'CrawlPolicyError') else RuntimeError):
            session.get("https://wewin.edu.vn/not-approved/")
        (self.directory / "STOP").write_text("stop")
        with self.assertRaises(self.b.SafetyStop): session.get(self.url)
        self.assertFalse(session.ledger)

    def test_robots_failure_stops_entire_run(self):
        http = self.b.BackfillHttp(self.directory, threading.Event())
        with patch.object(self.b.PoliteHttpClient, "allowed", side_effect=RuntimeError("unavailable")):
            with self.assertRaises(self.b.SafetyStop): http.allowed(self.url)

    def test_adaptive_rate_floor_after_server_pressure(self):
        sleeps = []
        http = self.b.BackfillHttp(self.directory, threading.Event(), clock=lambda: 10, sleep=sleeps.append)
        http.session.pressure_count = 1
        http._last_request = 10
        http._rate_limit()
        self.assertEqual(sleeps, [4])

    def test_trigger_rehearsal_rolls_back_its_fixture(self):
        self.b.trigger_rehearsal(self.database)
        self.assertEqual(self.b.snapshot(self.database), self.before)

    def test_stop_marker_preserves_checkpoint(self):
        (self.directory / "STOP").write_text("stop")
        with self.assertRaises(self.b.SafetyStop): self.b.run(self.directory)
        self.assertEqual(self.b.load(self.directory / "checkpoint.json")["phase"], "stopped")
        self.assertEqual(self.b.snapshot(self.database), self.before)

    def test_second_lock_prevents_backfill(self):
        lock = self.b.SyncLock(self.database.parent / "sync.lock")
        lock.acquire("fixture")
        try:
            with self.assertRaises(RuntimeError): self.b.run(self.directory)
        finally: lock.release()
        self.assertEqual(self.b.snapshot(self.database), self.before)

    def test_ten_then_twenty_checkpoint_resume_and_terminal_idempotence(self):
        self.cp['manifest'] = ['https://wewin.edu.vn/batch-fixture-%d/' % i for i in range(30)]
        self.b.save(self.directory / 'checkpoint.json', self.cp)
        calls = []

        def crawl(url):
            calls.append(url)
            return {'status': 'success', 'data': self.page(url, content=(url + ' Kiến thức độc lập. ') * 10)}

        finish = self.b.finish_batch

        def fast_finish(database, directory, checkpoint):
            finish(database, directory, checkpoint)
            self.assertGreater(checkpoint['next_batch_after'], self.b.time.time() + 28)
            checkpoint['next_batch_after'] = 0  # Skip real wall-clock waits only in fixture.
            self.b.save(directory / 'checkpoint.json', checkpoint)

        with patch.object(self.b.WeWinCrawler, 'crawl_url_detailed', side_effect=crawl), patch.object(self.b, 'finish_batch', side_effect=fast_finish):
            first = self.b.run(self.directory, max_batches=1)
            self.assertEqual(first['processed'], 10)
            self.assertEqual(first['phase'], 'batch_limit_pause')
            second = self.b.run(self.directory)
            self.assertEqual(second['phase'], 'complete')
            self.assertEqual(second['processed'], 30)
            self.assertEqual(self.b.run(self.directory)['network_requests'], 0)
        checkpoint = self.b.load(self.directory / 'checkpoint.json')
        self.assertEqual([len(b['urls']) for b in checkpoint['batches']], [10, 20])
        self.assertEqual(len(calls), len(set(calls)))
        self.b.check_state(self.database, checkpoint)

    def test_transport_escape_case_equivalence_preserves_path_security(self):
        equal = self.b.transport_equivalent_url
        self.assertTrue(equal('https://wewin.edu.vn/tuye%cc%89n/', 'https://wewin.edu.vn/tuye%CC%89n/'))
        self.assertFalse(equal('https://wewin.edu.vn/Path/', 'https://wewin.edu.vn/path/'))
        self.assertFalse(equal('https://wewin.edu.vn/a%2Fb/', 'https://wewin.edu.vn/a/b/'))
        self.assertFalse(equal('https://wewin.edu.vn/a/', 'https://example.com/a/'))

    def test_recruitment_category_does_not_capture_educational_teacher_job_words(self):
        infer = self.b.PageExtractor._infer_category
        for slug in ('bo-suu-tap-33-tro-choi-cho-giao-vien', 'describe-your-dream-job', 'de-tuyen-sinh-so-4'):
            self.assertEqual(infer('https://wewin.edu.vn/' + slug + '/', ''), 'general')
        for slug in ('can-tuyen-giao-vien', 'teacher-hiring', 'tuyen-dung-giao-vien'):
            self.assertEqual(infer('https://wewin.edu.vn/' + slug + '/', ''), 'careers')

    def test_archived_percent_case_replay_does_not_fetch_or_change_url_key(self):
        url = 'https://wewin.edu.vn/tuye%cc%89n-fixture/'
        self.cp['manifest'] = [url]
        self.cp['outcomes'][url] = {'status': 'skipped', 'reason': 'redirect_or_canonical_alias_requires_review', 'canonical_url': url}
        self.cp['inflight'] = self.url  # Proven not requested; maintenance may clear it.
        self.b.save(self.directory / 'checkpoint.json', self.cp)
        self.b.save(self.directory / 'http_ledger.json', [])
        folder = self.directory / 'responses'
        folder.mkdir()
        key = hashlib.sha256(url.encode()).hexdigest()
        content = ('<html><head><title>Archived lesson</title><link rel="canonical" href="' + url + '"></head><body><article>' + 'Một bài học lưu riêng để thử offline. ' * 20 + '</article></body></html>').encode()
        (folder / (key + '.body')).write_bytes(content)
        self.b.save(folder / (key + '.json'), {'url':url,'status':200,'content_type':'text/html','sha256':hashlib.sha256(content).hexdigest()})
        report = self.b.replay_archived(self.directory)
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(report['transport_case_replayed'], [url])
        checkpoint = self.b.load(self.directory / 'checkpoint.json')
        self.assertEqual(checkpoint['outcomes'][url]['status'], 'added')
        self.assertIsNotNone(self.db.get_page(url))
        self.b.check_state(self.database, checkpoint)

    def test_ambiguous_inflight_prevents_offline_replay(self):
        self.cp['inflight'] = self.url
        self.b.save(self.directory / 'checkpoint.json', self.cp)
        self.b.save(self.directory / 'http_ledger.json', [{'url':self.url,'status':'in_flight'}])
        with self.assertRaises(self.b.SafetyStop): self.b.replay_archived(self.directory)
        self.assertEqual(self.b.snapshot(self.database), self.before)

    def test_offline_category_correction_preserves_text_and_admission_count(self):
        # Simulate a previously admitted educational resource mislabelled careers.
        self.db.index_records([self.page(self.url, category='careers')])
        old = self.b.snapshot(self.database)
        self.cp['expected_pages'] = self.b.row_hashes(old)
        self.cp['written_urls'] = [self.url]
        self.cp['outcomes'][self.url] = {'status':'added','category':'careers'}
        self.b.save(self.directory / 'checkpoint.json', self.cp)
        report = self.b.replay_archived(self.directory)
        current = self.b.snapshot(self.database)
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(report['category_corrected'], [self.url])
        self.assertEqual(current['pages'][self.url]['category'], 'general')
        self.assertEqual(current['pages'][self.url]['content'], old['pages'][self.url]['content'])
        self.assertEqual(current['pages'][self.url]['retrieved_at'], old['pages'][self.url]['retrieved_at'])
        self.assertEqual(self.b.load(self.directory/'checkpoint.json')['outcomes'][self.url]['status'], 'added')

    def test_dispatch_guard_after_variable_ledger_work(self):
        now, dispatched = [0.0], []
        class Session:
            headers = {}
            def get(inner, url, **kwargs):
                dispatched.append(now[0])
                response = requests.Response()
                response.url, response.status_code = url, 200
                response._content, response._content_consumed = b'ok', True
                return response
        session = self.b.BackfillSession([self.url], self.directory, threading.Event(), Session(),
            clock=lambda: now[0], wait=lambda seconds: now.__setitem__(0, now[0] + seconds))
        session.get(self.url)
        now[0] += 0.000458  # Work before next request must not shorten dispatch interval.
        session.get(self.url)
        self.assertGreaterEqual(dispatched[1] - dispatched[0], 2.05)
        self.assertEqual(session.ledger[-1]['dispatch_monotonic'], dispatched[-1])


if __name__ == "__main__":
    unittest.main()
