from src.storage.knowledge_policy import result_record, policy_review
"""
Incremental Synchronization Engine for WeWIN Website Content.
Detects content changes using SHA-256 hashing, updates SQLite FTS5 in transactions,
prevents concurrent runs with file locking, and provides audit reporting.
"""
import os
import sys
import json
import time
import threading
import tempfile
import unicodedata
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional

from src.config import settings
from src.utils.logger import logger
from src.storage.db import get_db, DatabaseManager, calculate_content_hash
from src.crawler.sitemap_crawler import WeWinCrawler, normalize_url, transport_equivalent_url
from src.crawler.curated_seeds import get_curated_seeds

from src.sync.locking import SyncLock, SyncAlreadyRunningError, is_pid_active

@dataclass
class SyncReport:
    started_at: str
    completed_at: str
    status: str                         # 'success', 'partial', 'failed'
    duration_seconds: float
    total_discovered: int               # Total raw URLs discovered from sitemaps (e.g. 515)
    valid_urls: int = 0                 # Valid URLs after exclusion (e.g. 440)
    batch_target_count: int = 0         # Batch size evaluated (e.g. 25 or 440)
    pages_added: int = 0                # New pages added to DB
    pages_updated: int = 0              # Existing pages with modified content
    pages_unchanged: int = 0            # Existing pages with identical SHA-256
    pages_failed: int = 0               # Network/HTTP failures
    pages_skipped: int = 0              # Pages skipped (content too short/empty or seed protected)
    crawl_cursor: int = 0               # Persistent cursor for next batch
    trigger_type: str = "manual"        # 'manual', 'scheduled', 'api'
    error_summary: str = ""
    changes: List[Dict[str, str]] = field(default_factory=list)
    skipped_details: List[Dict[str, str]] = field(default_factory=list)
    pages_unprocessed: int = 0
    duplicate_urls: int = 0
    resumed: bool = False
    planned_urls: List[str] = field(default_factory=list)
    failed_details: List[Dict[str, Any]] = field(default_factory=list)
    cycle_remaining: int = 0

    @property
    def pages_successful(self) -> int:
        """Total pages successfully processed (added + updated + unchanged)."""
        return self.pages_added + self.pages_updated + self.pages_unchanged

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pages_successful"] = self.pages_successful
        return d

class SyncEngine:
    def __init__(self, db=None, crawler=None):
        self.db = db or get_db()
        self.crawler = crawler or WeWinCrawler()
        self.lock = SyncLock(lock_path=self.db.db_path.parent / "sync.lock")
        self._stop = threading.Event()
        self.active_trigger = None
        if hasattr(self.crawler, "http"):
            self.crawler.http.cancel_event = self._stop

    def request_stop(self):
        self._stop.set()

    def _checkpoint(self):
        raw = self.db.get_state("sync_checkpoint", "")
        if not raw: return None
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get("version") != 1 or
            not isinstance(value.get("urls"), list) or not all(isinstance(u, str) for u in value["urls"]) or
            not isinstance(value.get("offset"), int) or not 0 <= value["offset"] <= len(value["urls"])):
            raise RuntimeError("Invalid saved sync checkpoint; no cursor was reset.")
        return value

    def _make_plan(self, limit, crawl_all):
        saved = self._checkpoint()
        if saved: return saved, True, 0
        cursor = int(self.db.get_state("crawl_cursor", "0") or 0)
        retries = json.loads(self.db.get_state("sync_retry_urls", "[]") or "[]")
        if not isinstance(retries, list) or not all(isinstance(u, str) for u in retries):
            raise RuntimeError("Invalid retry queue; no state was reset.")
        head = retries[:min(3, limit // 3)] if not crawl_all else []
        cycle = None
        saved_cycle = self.db.get_state("sync_cycle", "")
        if saved_cycle and not crawl_all:
            cycle = json.loads(saved_cycle)
            if not isinstance(cycle, dict) or cycle.get("version") != 1 or not isinstance(cycle.get("urls"), list):
                raise RuntimeError("Invalid saved discovery manifest; no cursor reset performed.")
            urls, next_cursor = self.crawler.select_batch_urls(cycle["urls"], limit-len(head), cursor,
                                                              remaining=cycle["rotating_count"]-cycle["visited"])
            raw, valid = cycle["raw"], len(cycle["urls"])
        elif hasattr(self.crawler, "get_batch_urls"):
            urls, next_cursor, raw, valid = self.crawler.get_batch_urls(batch_size=limit-len(head), cursor=cursor, crawl_all=crawl_all)
        else:
            urls = self.crawler.get_candidate_urls()
            raw = valid = len(urls)
            urls = urls if crawl_all else urls[cursor:cursor+limit]
            next_cursor = (cursor + len(urls)) % max(1, valid)
        unique = list(dict.fromkeys(normalize_url(url) for url in head + urls))
        stats = getattr(self.crawler, "discovery_stats", {})
        manifest = getattr(self.crawler, "manifest_urls", None)
        if cycle is None and manifest is not None and not crawl_all:
            core = set(normalize_url(u) for u in self.crawler.CORE_PRIORITY_URLS)
            cycle = {"version":1,"urls":manifest,"visited":0,"raw":raw,
                     "rotating_count":sum(u not in core for u in manifest),
                     "manifest_sha256":stats.get("manifest_sha256", "")}
        cycle_advance = 0
        if cycle is not None:
            core = set(normalize_url(u) for u in self.crawler.CORE_PRIORITY_URLS)
            cycle_advance = sum(u not in core for u in urls)
        duplicates = len(head + urls) - len(unique) + stats.get("duplicates", 0)
        return {"version": 1, "urls": unique, "offset": 0, "next_cursor": next_cursor,
                "base_cursor": cursor, "total_discovered": raw, "valid_urls": valid,
                "cycle":cycle,"cycle_advance":cycle_advance}, False, duplicates

    def run_sync(self, trigger_type="manual", max_pages=None, dry_run=False, crawl_all=False, scheduled_slot=None, cancel_event=None):
        started = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        limit = max_pages if max_pages is not None else settings.MAX_PAGES_TO_CRAWL
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Batch size must be between 1 and 500.")
        report = SyncReport(started_at=started, completed_at=started, status="dry_run" if dry_run else "success",
                            duration_seconds=0, total_discovered=0, trigger_type=trigger_type)
        if trigger_type in ("scheduled", "task_scheduler", "cron", "systemd"):
            expected_owner = "internal" if trigger_type == "scheduled" else "windows" if trigger_type == "task_scheduler" else "external"
            if not settings.SYNC_SCHEDULE_ARMED or settings.SYNC_SCHEDULER_OWNER != expected_owner:
                report.status = "disabled"
                return report
        if dry_run:
            if self.lock.is_locked():
                raise SyncAlreadyRunningError("Planning refused while a sync job is active.")
            plan, resumed, duplicates = self._make_plan(limit, crawl_all)
            report.total_discovered, report.valid_urls = plan["total_discovered"], plan["valid_urls"]
            report.planned_urls = plan["urls"][plan["offset"]:plan["offset"]+limit]
            report.batch_target_count = len(report.planned_urls)
            report.pages_unprocessed = len(plan["urls"]) - plan["offset"]
            report.crawl_cursor, report.resumed, report.duplicate_urls = plan["base_cursor"], resumed, duplicates
            if plan.get("cycle"):
                report.cycle_remaining = plan["cycle"]["rotating_count"] - plan["cycle"]["visited"]
            report.completed_at = datetime.now(timezone.utc).isoformat()
            report.duration_seconds = round(time.monotonic()-start, 2)
            return report  # No lock, seed, page fetch, export, history or state write.
        self.lock.acquire(trigger_type=trigger_type)
        self.active_trigger = trigger_type
        self._stop.clear()
        if cancel_event is not None and cancel_event.is_set(): self._stop.set()
        plan, errors = None, []
        try:
            if self._stop.is_set():
                report.status = "interrupted"
                return report
            if scheduled_slot and self.db.get_state("last_scheduled_slot", "") == scheduled_slot:
                report.status = "already_completed"
                return report
            plan, report.resumed, report.duplicate_urls = self._make_plan(limit, crawl_all)
            report.total_discovered, report.valid_urls = plan["total_discovered"], plan["valid_urls"]
            report.crawl_cursor = plan["base_cursor"]
            initial_states = {"sync_checkpoint": json.dumps(plan, ensure_ascii=False)}
            if plan.get("cycle"): initial_states["sync_cycle"] = json.dumps(plan["cycle"],ensure_ascii=False)
            self.db.set_states(initial_states)
            existing = self.db.get_existing_hashes()
            seed_urls = set()
            for seed in get_curated_seeds():
                url = normalize_url(seed["url"])
                seed_urls.add(url)
                if url not in existing:
                    self.db.update_page_incremental(seed, is_new=True)
            existing = self.db.get_existing_hashes()
            retries = json.loads(self.db.get_state("sync_retry_urls", "[]") or "[]")
            targets = plan["urls"][plan["offset"]:plan["offset"]+limit]
            report.batch_target_count = len(targets)
            for url in targets:
                if self._stop.is_set(): break
                outcome, detail = self._process_url(url, existing, seed_urls)
                if outcome == "cancelled":
                    self._stop.set()
                    break
                if outcome == "failed":
                    report.pages_failed += 1
                    errors.append(detail.get("reason", "URL failed"))
                    report.failed_details.append({"url": url, **detail})
                    retries = [u for u in retries if u != url] + [url]
                elif outcome == "skipped":
                    report.pages_skipped += 1
                    report.skipped_details.append({"url": url, **detail})
                    retries = [u for u in retries if u != url]
                else:
                    setattr(report, "pages_" + outcome, getattr(report, "pages_" + outcome) + 1)
                    retries = [u for u in retries if u != url]
                    if outcome in ("added", "updated"):
                        report.changes.append({"url": url, "action": outcome, "title": detail.get("title", "")})
                plan["offset"] += 1
                # Page commit precedes checkpoint. A crash in the tiny gap only
                # repeats the last URL; idempotent upsert prevents data loss.
                self.db.set_states({"sync_checkpoint": json.dumps(plan, ensure_ascii=False),
                                    "sync_retry_urls": json.dumps(retries, ensure_ascii=False)})
            report.pages_unprocessed = len(plan["urls"]) - plan["offset"]
            report.status = "interrupted" if self._stop.is_set() else "partial" if report.pages_unprocessed or report.pages_failed else "success"
            if report.pages_failed and report.pages_successful == 0 and not report.pages_unprocessed:
                report.status = "failed"
            if self._export_knowledge_json() is False:
                errors.append("Atomic JSON export failed; SQLite cache retained.")
                if report.status == "success": report.status = "partial"
            report.error_summary = "; ".join(errors[:5])
            report.completed_at = datetime.now(timezone.utc).isoformat()
            report.duration_seconds = round(time.monotonic()-start, 2)
            states = {"sync_checkpoint": json.dumps(plan, ensure_ascii=False), "sync_retry_urls": json.dumps(retries, ensure_ascii=False)}
            cycle = plan.get("cycle")
            if cycle:
                report.cycle_remaining = max(0,cycle["rotating_count"]-cycle["visited"])
            if report.pages_unprocessed == 0:
                report.crawl_cursor = plan["next_cursor"]
                states.update({"crawl_cursor": str(plan["next_cursor"]), "sync_checkpoint": ""})
                if cycle:
                    cycle["visited"] += plan["cycle_advance"]
                    report.cycle_remaining = max(0,cycle["rotating_count"]-cycle["visited"])
                    states["sync_cycle"] = json.dumps(cycle,ensure_ascii=False) if report.cycle_remaining else ""
                else:
                    states["sync_cycle"] = ""
                if scheduled_slot and report.batch_target_count > 0:
                    states["last_scheduled_slot"] = scheduled_slot
            states["last_sync_report"] = json.dumps(report.to_dict(), ensure_ascii=False)
            self.db.set_states(states, history_report=report.to_dict())
            return report
        except Exception as error:
            report.status, report.error_summary = "failed", str(error)
            report.completed_at = datetime.now(timezone.utc).isoformat()
            report.duration_seconds = round(time.monotonic()-start, 2)
            if plan:
                report.pages_unprocessed = len(plan["urls"]) - plan["offset"]
            # Do not erase checkpoint/cursor on discovery or storage failure.
            self.db.set_states({"last_sync_report": json.dumps(report.to_dict(), ensure_ascii=False)}, history_report=report.to_dict())
            return report
        finally:
            self.active_trigger = None
            self.lock.release()

    def _process_url(self, url, existing, seed_urls):
        try:
            if policy_review(url):
                return "skipped", {"reason": policy_review(url)}
            if hasattr(self.crawler, "crawl_url_detailed"):
                result = self.crawler.crawl_url_detailed(url)
            else:
                result = {"status": "success", "data": self.crawler.crawl_url(url), "http_status": 200}
            if result.get("status") == "cancelled": return "cancelled", {}
            page = result.get("data")
            if not page:
                reason = result.get("reason") or "Empty crawler response"
                if result.get("status") == "skipped":
                    return "skipped", {"reason": reason, "canonical_url": result.get("canonical_url", "")}
                if url in existing:
                    self.db.mark_page_error(url, result.get("http_status") or 500)
                return "failed", {"reason": reason, "http_status": result.get("http_status")}
            content = page.get("content")
            if not isinstance(content, str) or not content.strip() or not isinstance(page.get("title"), str) or not isinstance(page.get("category", "general"), str):
                return "skipped", {"reason": "empty_short_or_invalid_page"}
            if not transport_equivalent_url(page.get("url", url), url):
                return "skipped", {"reason": "canonical_alias_requires_review", "canonical_url": page.get("url", "")}
            old = existing.get(url)
            hashes = {}
            for cached_url, cached in existing.items():
                hashes.setdefault(cached.get("content_hash", ""), []).append(cached_url)
            page = {**page, "url": url, "category": page.get("category", "general"),
                    "retrieved_at": page.get("retrieved_at") or datetime.now(timezone.utc).isoformat()}
            page, decision = result_record({"status": "success", "data": page}, old, hashes)
            if page is None:
                return "skipped", {"reason": decision.get("reason", "quality_review")}
            if old and all(old.get(key) == page[key] for key in ("title", "category", "content_hash")):
                self.db.touch_page_unchanged(url)
                return "unchanged", {"title": page["title"]}
            if not self.db.update_page_incremental(page, is_new=old is None):
                return "skipped", {"reason": "cache_validation_rejected"}
            existing[url] = page
            return "updated" if old else "added", {"title": page["title"]}
        except Exception as error:
            return "failed", {"reason": str(error)}

    def _export_knowledge_json(self):
        path = settings.KNOWLEDGE_JSON_PATH
        temporary = None
        try:
            with self.db.get_connection() as conn:
                rows = [dict(r) for r in conn.execute("SELECT url,title,category,content,content_hash,last_modified,retrieved_at,source_type FROM public_pages ORDER BY id")]
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".knowledge-", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(rows, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return True
        except Exception:
            return False
        finally:
            if temporary and os.path.exists(temporary): os.unlink(temporary)


_engine_instance = None


def get_sync_engine():
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SyncEngine()
    return _engine_instance
