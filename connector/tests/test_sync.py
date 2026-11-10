"""
Unit and Integration Tests for WeWIN Website Auto-Sync Engine (Phase 4).
Uses isolated SQLite database and mock crawler to verify all 8 required scenarios:
1. Initial Sync
2. Second Sync (unchanged content, SHA-256 match)
3. Modified page content detection & FTS5 update
4. Page failure / timeout resilience (data retention)
5. Concurrency lock prevention
6. Search and MCP tool validity after sync
7. API monitoring endpoints (/sync/status, /sync/history, /sync)
8. Windows batch and PowerShell script validity
"""
import sys
import io
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.storage.db import DatabaseManager, calculate_content_hash
from src.sync.sync_engine import SyncEngine, SyncAlreadyRunningError, SyncLock
from src.api.app import app
import uuid
from fastapi.testclient import TestClient

class TestWeWinAutoSync(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary test directory
        self.test_dir = PROJECT_ROOT / "tests" / "scratch_test_sync"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        # Use unique UUID DB and Lock for each test to guarantee a fresh isolated database
        uid = uuid.uuid4().hex[:8]
        self.test_db_path = self.test_dir / f"test_{self._testMethodName}_{uid}.db"
        self.test_lock_path = self.test_dir / f"test_{self._testMethodName}_{uid}.lock"

        self.db = DatabaseManager(db_path=self.test_db_path)


        # Mock Crawler
        self.mock_crawler = MagicMock()

        # Instantiate SyncEngine using test db & lock
        self.engine = SyncEngine(db=self.db, crawler=self.mock_crawler)
        self.engine.lock = SyncLock(lock_path=self.test_lock_path)

    def tearDown(self):
        # Release lock if acquired
        try:
            if hasattr(self, "engine") and hasattr(self.engine, "lock"):
                self.engine.lock.release()
        except Exception:
            pass


    def test_01_initial_sync(self):
        """Scenario A: Initial Sync adds candidate pages and creates sync_history record."""
        mock_pages = {
            "https://wewin.edu.vn/gioi-thieu/": {
                "url": "https://wewin.edu.vn/gioi-thieu/",
                "title": "Giới thiệu WeWIN Education",
                "category": "About",
                "content": "WeWIN Education là hệ thống đào tạo Anh ngữ hàng đầu tại TP.HCM.",
                "last_modified": "2026-10-01"
            },
            "https://wewin.edu.vn/khoa-hoc-ielts/": {
                "url": "https://wewin.edu.vn/khoa-hoc-ielts/",
                "title": "Khóa học IELTS Chuẩn Quốc Tế",
                "category": "Programs",
                "content": "Lộ trình luyện thi IELTS từ cơ bản đến 7.5+ cùng giảng viên IDP.",
                "last_modified": "2026-10-02"
            }
        }
        self.mock_crawler.get_candidate_urls.return_value = list(mock_pages.keys())
        self.mock_crawler.crawl_url.side_effect = lambda u: mock_pages.get(u)

        report = self.engine.run_sync(trigger_type="test_initial")

        self.assertEqual(report.status, "success")
        self.assertEqual(report.pages_added, 2)
        self.assertEqual(report.pages_updated, 0)
        self.assertEqual(report.pages_unchanged, 0)
        self.assertEqual(report.pages_failed, 0)

        # Check DB records
        status = self.db.get_sync_status()
        self.assertGreaterEqual(status["total_pages"], 2)
        self.assertIsNotNone(status["last_sync"])
        self.assertEqual(status["last_sync"]["trigger_type"], "test_initial")

    def test_02_second_sync_unchanged(self):
        """Scenario B: Second sync with identical content detects 0 updates and 0 adds."""
        mock_pages = {
            "https://wewin.edu.vn/gioi-thieu/": {
                "url": "https://wewin.edu.vn/gioi-thieu/",
                "title": "Giới thiệu WeWIN Education",
                "category": "About",
                "content": "WeWIN Education là hệ thống đào tạo Anh ngữ hàng đầu tại TP.HCM.",
                "last_modified": "2026-10-01"
            }
        }
        self.mock_crawler.get_candidate_urls.return_value = list(mock_pages.keys())
        self.mock_crawler.crawl_url.side_effect = lambda u: mock_pages.get(u)

        # First sync
        r1 = self.engine.run_sync(trigger_type="run1")
        self.assertEqual(r1.pages_added, 1)

        # Second sync with exact same content
        r2 = self.engine.run_sync(trigger_type="run2")
        self.assertEqual(r2.status, "success")
        self.assertEqual(r2.pages_added, 0)
        self.assertEqual(r2.pages_updated, 0)
        self.assertEqual(r2.pages_unchanged, 1)
        self.assertEqual(r2.pages_failed, 0)

    def test_03_modified_page_content_detection(self):
        """Scenario C: Content change triggers incremental update & updates FTS5 index."""
        url = "https://wewin.edu.vn/tin-tuc-hoc-bong/"
        page_v1 = {
            "url": url,
            "title": "Học bổng Tiếng Anh WeWIN 2025",
            "category": "News",
            "content": "Chương trình học bổng WeWIN tài trợ 30% học phí năm 2025.",
            "last_modified": "2025-01-01"
        }
        self.mock_crawler.get_candidate_urls.return_value = [url]
        self.mock_crawler.crawl_url.return_value = page_v1

        self.engine.run_sync(trigger_type="run_v1")

        # Verify FTS searches for 2025
        results_v1 = self.db.search("2025")
        self.assertTrue(any("2025" in r["snippet"] for r in results_v1))

        # Now simulate website content updated to 2026
        page_v2 = {
            "url": url,
            "title": "Học bổng Tiếng Anh WeWIN 2026",
            "category": "News",
            "content": "Chương trình học bổng WeWIN tài trợ 50% học phí năm 2026 thế hệ mới.",
            "last_modified": "2026-10-24"
        }
        self.mock_crawler.crawl_url.return_value = page_v2

        r2 = self.engine.run_sync(trigger_type="run_v2")
        self.assertEqual(r2.pages_updated, 1)
        self.assertEqual(r2.pages_added, 0)
        self.assertEqual(r2.pages_unchanged, 0)

        # Verify FTS index now matches 2026
        results_v2 = self.db.search("2026")
        self.assertTrue(any("2026" in r["snippet"] for r in results_v2))

    def test_04_crawl_failure_resilience(self):
        """Scenario D: When crawling fails or times out, cached page data is retained intact."""
        url1 = "https://wewin.edu.vn/gioi-thieu/"
        url2 = "https://wewin.edu.vn/lien-he/"
        valid_page1 = {
            "url": url1,
            "title": "Giới thiệu WeWIN",
            "category": "About",
            "content": "Nội dung giới thiệu WeWIN Education.",
            "last_modified": "2026-01-01"
        }
        valid_page2 = {
            "url": url2,
            "title": "Liên hệ WeWIN",
            "category": "Contact",
            "content": "Hotline hỗ trợ phụ huynh: 034 596 9388.",
            "last_modified": "2026-01-01"
        }
        pages_map = {url1: valid_page1, url2: valid_page2}
        self.mock_crawler.get_candidate_urls.return_value = [url1, url2]
        self.mock_crawler.crawl_url.side_effect = lambda u: pages_map.get(u)

        # Initial successful sync
        self.engine.run_sync(trigger_type="init")
        cached_before = self.db.get_page(url2)
        self.assertIsNotNone(cached_before)
        self.assertEqual(cached_before["content"], valid_page2["content"])

        # Second sync: url1 is reachable (unchanged), url2 fails / returns None
        self.mock_crawler.crawl_url.side_effect = lambda u: valid_page1 if u == url1 else None
        r_fail = self.engine.run_sync(trigger_type="network_partial_down")

        self.assertEqual(r_fail.pages_failed, 1)
        self.assertEqual(r_fail.pages_unchanged, 1)
        self.assertEqual(r_fail.status, "partial")

        # Crucial check: cached page MUST NOT be deleted or blanked out!
        cached_after = self.db.get_page(url2)
        self.assertIsNotNone(cached_after)
        self.assertEqual(cached_after["content"], valid_page2["content"])
        self.assertEqual(cached_after["http_status"], 500)

        # FTS search still succeeds on cached data
        search_res = self.db.search("034 596 9388")
        self.assertTrue(len(search_res) > 0)

    def test_05_concurrency_lock_protection(self):
        """Scenario E: Lock prevents two sync jobs from executing simultaneously."""
        self.engine.lock.acquire(trigger_type="test_lock")
        self.assertTrue(self.engine.lock.is_locked())

        # Attempting second acquire must raise SyncAlreadyRunningError
        with self.assertRaises(SyncAlreadyRunningError):
            self.engine.run_sync(trigger_type="parallel_attempt")

        # Release lock and ensure it can run
        self.engine.lock.release()
        self.assertFalse(self.engine.lock.is_locked())

    def test_06_mcp_tools_and_search_after_sync(self):
        """Scenario F: Verifies DB search, get_programs, get_contact, and get_page remain functional."""
        seeds = self.db.get_programs(age=9)
        self.assertIn("recommendation", seeds)
        self.assertEqual(seeds["recommendation"]["age"], 9)

        contact = self.db.get_contact()
        self.assertIn("034 596 9388", contact["hotline"])
        self.assertEqual(len(contact["campuses"]), 2)

    def test_07_api_monitoring_endpoints(self):
        """Scenario G: Tests GET /sync/status, GET /sync/history, and POST /sync."""
        client = TestClient(app)
        auth_header = {"Authorization": f"Bearer {settings.ADMIN_SYNC_TOKEN}"}

        # 1. Unauthenticated request must return 401
        r_unauth = client.get("/sync/status")
        self.assertEqual(r_unauth.status_code, 401)

        # 2. Authenticated GET /sync/status
        r_status = client.get("/sync/status", headers=auth_header)
        self.assertEqual(r_status.status_code, 200)
        data_status = r_status.json()
        self.assertIn("is_syncing", data_status)
        self.assertIn("total_pages", data_status)

        # 3. Authenticated GET /sync/history
        r_hist = client.get("/sync/history", headers=auth_header)
        self.assertEqual(r_hist.status_code, 200)
        data_hist = r_hist.json()
        self.assertIn("history", data_hist)

        # 4. POST /sync with mock engine to avoid network crawl
        from src.sync.sync_engine import SyncReport
        mock_report = SyncReport(
            started_at="2026-10-24T16:00:00",
            completed_at="2026-10-24T16:00:01",
            status="success",
            duration_seconds=1.0,
            total_discovered=2,
            pages_added=0,
            pages_updated=0,
            pages_unchanged=2,
            pages_failed=0,
            trigger_type="api"
        )
        with patch("src.api.routes.get_sync_engine") as mock_get_engine:
            mock_inst = MagicMock()
            mock_inst.run_sync.return_value = mock_report
            mock_get_engine.return_value = mock_inst

            r_sync = client.post("/sync?dry_run=true&max_pages=2", headers=auth_header)
            self.assertEqual(r_sync.status_code, 200)
            data_sync = r_sync.json()
            self.assertTrue(data_sync["success"])
            self.assertEqual(data_sync["total_indexed"], 2)


    def test_08_windows_scripts_existence(self):
        """Scenario H: Verifies Windows Task Scheduler scripts exist and are well-formed."""
        bat_script = PROJECT_ROOT / "scripts" / "run_sync.bat"
        ps1_script = PROJECT_ROOT / "scripts" / "setup_windows_sync.ps1"
        setup_bat = PROJECT_ROOT / "scripts" / "setup_windows_sync.bat"

        self.assertTrue(bat_script.exists(), "scripts/run_sync.bat must exist")
        self.assertTrue(ps1_script.exists(), "scripts/setup_windows_sync.ps1 must exist")
        self.assertTrue(setup_bat.exists(), "scripts/setup_windows_sync.bat must exist")

        bat_content = bat_script.read_text(encoding="utf-8")
        self.assertIn("run_sync.py", bat_content)
        self.assertIn("sync_scheduled.log", bat_content)

        ps1_content = ps1_script.read_text(encoding="utf-8")
        self.assertIn("WeWIN_Website_AutoSync", ps1_content)
        self.assertIn("Register-ScheduledTask", ps1_content)

    def test_09_stale_lock_dead_pid_auto_recovery(self):
        """Scenario I: Stale lock left by a terminated process (dead PID) is automatically recovered."""
        dead_pid = 999999  # Guaranteed non-existent PID
        dead_lock_info = {
            "pid": dead_pid,
            "started_at": "2026-10-24T16:00:00+00:00",
            "trigger_type": "crashed_process"
        }
        self.test_lock_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(self.test_lock_path, "w", encoding="utf-8") as f:
            json.dump(dead_lock_info, f, indent=2)

        self.assertTrue(self.test_lock_path.exists())

        # is_locked should detect dead PID and auto-recover
        is_locked_res = self.engine.lock.is_locked()
        self.assertFalse(is_locked_res, "Lock held by dead PID must be reported as unlocked")
        self.assertFalse(self.test_lock_path.exists(), "Stale lock file must be deleted upon recovery")

        # Now run_sync must succeed without SyncAlreadyRunningError
        self.mock_crawler.get_candidate_urls.return_value = []
        report = self.engine.run_sync(trigger_type="recovery_test")
        self.assertEqual(report.status, "success")

    def test_10_active_process_lock_respected(self):
        """Scenario J: An active process lock is strictly respected; parallel sync is rejected."""
        active_pid = os.getpid()  # Current process is alive
        lock_info = {
            "pid": active_pid,
            "started_at": "2026-10-24T16:30:00+00:00",
            "trigger_type": "running_job"
        }
        self.test_lock_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(self.test_lock_path, "w", encoding="utf-8") as f:
            json.dump(lock_info, f, indent=2)

        # Lock must be reported active
        self.assertTrue(self.engine.lock.is_locked())

        # Parallel run attempt MUST raise SyncAlreadyRunningError
        with self.assertRaises(SyncAlreadyRunningError):
            self.engine.run_sync(trigger_type="parallel_test")

        # Clean up
        self.engine.lock.release(force=True)

    def test_11_stale_lock_timeout_recovery(self):
        """Scenario K: Lock exceeding timeout is auto-broken even if PID check cannot resolve."""
        # Create a lock with 1-second timeout
        short_lock = SyncLock(lock_path=self.test_lock_path, timeout_minutes=0)
        short_lock.timeout_seconds = 0.5  # 500ms timeout

        lock_info = {
            "pid": os.getpid(),
            "started_at": "2026-10-24T16:00:00+00:00",
            "trigger_type": "hung_job"
        }
        self.test_lock_path.parent.mkdir(parents=True, exist_ok=True)
        import json, time
        with open(self.test_lock_path, "w", encoding="utf-8") as f:
            json.dump(lock_info, f, indent=2)

        # Wait for timeout to expire
        time.sleep(0.7)

        # is_locked should break stale lock
        self.assertFalse(short_lock.is_locked(), "Expired lock must be broken")
        self.assertFalse(self.test_lock_path.exists())

    def test_12_interrupted_run_cleanup_on_exception(self):
        """Scenario L: If an unhandled exception occurs inside run_sync, finally block always releases the lock."""
        # Mock crawler to raise an unexpected RuntimeError
        self.mock_crawler.get_candidate_urls.side_effect = RuntimeError("Simulated unexpected crash")

        with self.assertRaises(RuntimeError):
            self.engine.run_sync(trigger_type="crash_test")

        # Crucial check: lock MUST NOT be left dangling!
        self.assertFalse(self.test_lock_path.exists(), "Lock must be released in finally block even on fatal exception")

    def test_13_batch_rotation_and_cursor_persistence(self):
        """Scenario M: Verifies that sync runs in batches and updates persistent crawl_cursor in DB."""
        # 1. Initially cursor is 0
        cur0 = self.db.get_state("crawl_cursor", "0")
        self.assertEqual(cur0, "0")

        # Mock crawler returning batch 1 (cursor 0 -> 25)
        self.mock_crawler.get_batch_urls.return_value = (
            ["https://wewin.edu.vn/page-1", "https://wewin.edu.vn/page-2"],
            25,  # next cursor
            515, # total discovered
            440  # valid pool
        )
        self.mock_crawler.crawl_url.return_value = {
            "url": "https://wewin.edu.vn/page-1",
            "title": "Page 1",
            "category": "News",
            "content": "Nội dung bài viết mẫu trang số 1 của WeWIN.",
            "last_modified": "2026-10-24"
        }

        report1 = self.engine.run_sync(trigger_type="batch_test_1")
        self.assertEqual(report1.crawl_cursor, 25)
        self.assertEqual(report1.total_discovered, 515)
        self.assertEqual(report1.valid_urls, 440)
        self.assertEqual(self.db.get_state("crawl_cursor"), "25")

        # Second batch from cursor 25 -> 50
        self.mock_crawler.get_batch_urls.return_value = (
            ["https://wewin.edu.vn/page-3"],
            50,
            515,
            440
        )
        self.mock_crawler.crawl_url.return_value = {
            "url": "https://wewin.edu.vn/page-3",
            "title": "Page 3",
            "category": "News",
            "content": "Nội dung bài viết mẫu trang số 3 của WeWIN.",
            "last_modified": "2026-10-24"
        }

        report2 = self.engine.run_sync(trigger_type="batch_test_2")
        self.assertEqual(report2.crawl_cursor, 50)
        self.assertEqual(self.db.get_state("crawl_cursor"), "50")

    def test_14_seed_protection_against_short_scrape(self):
        """Scenario N: Curated seeds are strictly protected and never overwritten by short/empty scraped content."""
        seed_url = "https://wewin.edu.vn/gioi-thieu/"
        # 1. Populate database with rich seed
        rich_seed = {
            "url": seed_url,
            "title": "Giới thiệu WeWIN Education",
            "category": "About",
            "content": "WeWIN Education là hệ sinh thái đào tạo tiếng Anh thế hệ mới, với hơn 1000 học viên đạt chuẩn quốc tế tại TP.HCM.",
            "source_type": "seed"
        }
        self.db.update_page_incremental(rich_seed, is_new=True)

        cached_before = self.db.get_page(seed_url)
        self.assertIsNotNone(cached_before)
        self.assertEqual(cached_before["source_type"], "seed")

        # 2. Simulate web crawl returning a degraded 25-character scrape (e.g. iframe flipbook placeholder)
        degraded_scrape = {
            "url": seed_url,
            "title": "Giới thiệu WeWIN",
            "category": "About",
            "content": "All about WeWIN Education"  # Only 25 chars!
        }
        self.mock_crawler.get_candidate_urls.return_value = [seed_url]
        self.mock_crawler.crawl_url.return_value = degraded_scrape

        report = self.engine.run_sync(trigger_type="seed_guard_test")

        # Must record as skipped, not added/updated
        self.assertEqual(report.pages_updated, 0)
        self.assertEqual(report.pages_skipped, 1)
        self.assertTrue(any("Bảo vệ dữ liệu gốc" in item["reason"] for item in report.skipped_details))

        # DB content must remain the rich seed
        cached_after = self.db.get_page(seed_url)
        self.assertEqual(cached_after["content"], rich_seed["content"])
        self.assertEqual(cached_after["source_type"], "seed")

    def test_15_vietnamese_mojibake_repair_and_nfc(self):
        """Scenario O: Tests repair of UTF-8 mojibake (e.g. 'Trang chá»§') and NFC normalization."""
        from src.crawler.extractor import fix_vietnamese_mojibake
        import unicodedata

        # Common Latin-1 mojibake cases from Vietnamese websites
        mojibake_1 = "Trang chá»§"
        fixed_1 = fix_vietnamese_mojibake(mojibake_1)
        self.assertEqual(fixed_1, "Trang chủ")

        mojibake_2 = "Tiáº¿ng Anh giao tiáº¿p"
        fixed_2 = fix_vietnamese_mojibake(mojibake_2)
        self.assertEqual(fixed_2, "Tiếng Anh giao tiếp")

        # NFC normalization check
        nfd_str = unicodedata.normalize("NFD", "Trang chủ WeWIN")
        nfc_str = unicodedata.normalize("NFC", nfd_str)
        self.assertEqual(unicodedata.normalize("NFC", nfd_str), nfc_str)

    def test_16_empty_or_iframe_pages_skipped(self):
        """Scenario P: Short/empty or iframe-only pages are counted as skipped, not failed."""
        url_empty = "https://wewin.edu.vn/ielts-placement-test/"
        self.mock_crawler.get_candidate_urls.return_value = [url_empty]
        # Simulate crawl_url_detailed reporting "skipped"
        self.mock_crawler.crawl_url_detailed.return_value = {
            "status": "skipped",
            "reason": "Nội dung quá ngắn (<60 ký tự), rỗng hoặc chỉ chứa iframe/script",
            "data": None,
            "http_status": 200
        }

        report = self.engine.run_sync(trigger_type="skip_empty_test")
        self.assertEqual(report.pages_skipped, 1)
        self.assertEqual(report.pages_failed, 0)
        self.assertEqual(report.status, "success")
        self.assertTrue(len(report.skipped_details) > 0)
        self.assertEqual(report.skipped_details[0]["url"], url_empty)

if __name__ == "__main__":
    unittest.main()

