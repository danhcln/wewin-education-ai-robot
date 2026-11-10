"""One-worker, frozen-manifest initial backfill; schedulers remain disabled.

No schema changes, ordinary sync, seeds, JSON import/export or remote services.
Private checkpoints store a durable intent before each SQLite transaction;
resume reconciles committed intents without repeating an HTTP page request.
"""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import sys
import threading
import time
import unicodedata
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.canary_crawl import (save, load, snapshot, schedulers_off, BudgetSession,
                                  backup_sqlite, restrict_directory, inspect_database,
                                  verify_target_queries, DatabaseManager, calculate_content_hash,
                                  SyncLock, settings, normalize_url, PoliteHttpClient, WeWinCrawler)
from src.crawler.extractor import PageExtractor
from src.crawler.sitemap_crawler import transport_equivalent_url


class SafetyStop(RuntimeError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def row_hashes(state):
    return {url: digest(row) for url, row in state["pages"].items()}


def disk_check(directory):
    if shutil.disk_usage(directory).free < 2 * 1024**3:
        raise SafetyStop("Less than 2 GiB free space; preserve checkpoint and free space before resuming.")


from src.storage.knowledge_policy import policy_review, result_record


def check_state(database, checkpoint, verify_search=True):
    current = snapshot(database)
    if current["schema"] != checkpoint["schema"]:
        raise SafetyStop("Schema or FTS trigger changed.")
    for key in ("sync_state", "sync_history"):
        if current["fingerprints"][key] != checkpoint["control_fingerprints"][key]:
            raise SafetyStop("Sync cursor/history changed outside backfill.")
    if row_hashes(current) != checkpoint["expected_pages"]:
        raise SafetyStop("Unexpected cached-page change or unresolved transaction intent.")
    status = inspect_database(database)["status"]
    if not status["integrity_ok"] or not status["consistent"] or status["duplicate_page_urls"] or status["canonical_duplicate_groups"]:
        raise SafetyStop("SQLite integrity or FTS consistency/URL uniqueness failed.")
    for url in checkpoint["written_urls"]:
        row = current["pages"][url]
        if row["content_hash"] != calculate_content_hash(row["content"]) or any(unicodedata.normalize("NFC", row[k]) != row[k] for k in ("content", "title", "category")):
            raise SafetyStop("Written content hash or Unicode normalization mismatch.")
    if verify_search:
        verify_target_queries(DatabaseManager.open_existing(database, read_only=True))
    return status


def trigger_rehearsal(path):
    """Exercise existing triggers on an isolated restore only, then roll back."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        url = "https://wewin.edu.vn/backfill-trigger-fixture/"
        conn.execute("INSERT INTO pages(url,title,content,category,retrieved_at) VALUES(?,?,?,?,?)", (url, "fixture", "triggeroriginal", "general", stamp()))
        assert conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'triggeroriginal' AND url=?", (url,)).fetchone()[0] == 1
        conn.execute("UPDATE pages SET title='newtitle',category='newcategory',content='triggerupdated' WHERE url=?", (url,))
        assert conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'triggerupdated' AND title='newtitle' AND category='newcategory' AND url=?", (url,)).fetchone()[0] == 1
        conn.execute("DELETE FROM pages WHERE url=?", (url,))
        assert conn.execute("SELECT count(*) FROM pages_fts WHERE url=?", (url,)).fetchone()[0] == 0
        conn.rollback()


def initialize(database, directory, canary):
    schedulers_off()
    if directory.exists() or directory.is_relative_to(database.parent):
        raise ValueError("Use a new backup directory outside production data.")
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("backfill_prepare")
    try:
        restrict_directory(directory)
        disk_check(directory)
        before = snapshot(database)
        backup_sqlite(database, directory / "before_backfill.db")
        backup_sqlite(directory / "before_backfill.db", directory / "restore_verified.db")
        if snapshot(directory / "restore_verified.db") != before or snapshot(database) != before:
            raise SafetyStop("Backup/restore/source snapshots differ.")
        trigger_rehearsal(directory / "restore_verified.db")
        audit = inspect_database(database)
        if not audit["status"]["consistent"] or not audit["status"]["integrity_ok"]:
            raise SafetyStop("Preflight SQLite/FTS failed.")
        save(directory / "baseline.json", before)
        save(directory / "before_audit.json", audit)
        save(directory / "canary_manifest.json", load(canary / "manifest_current.json"))
        # Import results only when the installation still matches the sealed canary.
        if before != load(canary / "applied_snapshot.json"):
            raise SafetyStop("Database changed after canary; review baseline before importing results.")
        save(directory / "canary_outcomes.json", load(canary / "outcomes.json"))
        checkpoint = {"version": 1, "created_at": stamp(), "database": str(database), "phase": "prepared",
            "schema": before["schema"], "control_fingerprints": before["fingerprints"],
            "expected_pages": row_hashes(before), "outcomes": {}, "manifest": [], "written_urls": [],
            "active_batch": None, "batches": [], "intent": None, "inflight": None,
            "next_batch_after": 0, "consecutive_failed_urls": 0, "stop_reason": None}
        save(directory / "checkpoint.json", checkpoint)
        return {"phase": "prepared", "before": audit["status"], "backup_restore_triggers": "PASS"}
    finally:
        lock.release()


class BackfillSession(BudgetSession):
    def __init__(self, urls, directory, stop, session=None, clock=None, wait=None):
        # The outer limiter starts before ledger fsync. Dispatch guard is placed
        # AFTER that variable I/O, immediately before the transport call.
        owner = self
        transport = session or requests.Session()
        self.dispatch_clock, self.dispatch_wait = clock or time.monotonic, wait or stop.wait
        self.last_dispatch = self.dispatch_clock()

        class GuardedTransport:
            headers = transport.headers

            def get(self, url, **kwargs):
                remaining = max(0, 2.05 - (owner.dispatch_clock() - owner.last_dispatch))
                if remaining:
                    owner.dispatch_wait(remaining)
                if stop.is_set() or (directory / "STOP").exists():
                    raise SafetyStop("Stop requested before guarded dispatch.")
                owner.last_dispatch = owner.dispatch_clock()
                owner.ledger[-1]["dispatch_monotonic"] = owner.last_dispatch
                owner.ledger[-1]["dispatch_utc"] = stamp()
                return transport.get(url, **kwargs)

        super().__init__(urls, directory, GuardedTransport())
        self.stop = stop
        self.bad_streak = 0
        self.pressure_count = sum(isinstance(r["status"], int) and (r["status"] == 429 or r["status"] >= 500) for r in self.ledger)

    def get(self, url, **kwargs):
        if self.stop.is_set() or (self.directory / "STOP").exists():
            raise SafetyStop("Manual stop requested before next HTTP request.")
        response = super().get(url, **kwargs)
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            self.bad_streak += 1
            self.pressure_count += 1
        else:
            self.bad_streak = 0
        if self.bad_streak >= 3:
            response.close()
            raise SafetyStop("Three consecutive HTTP 429/5xx responses; server safety circuit opened.")
        return response


class BackfillHttp(PoliteHttpClient):
    def __init__(self, directory, stop, **kwargs):
        super().__init__(**kwargs)
        self.directory, self.stop = directory, stop
        self.minimum_delay = 2.05
        ledger = getattr(self.session, "ledger", [])
        if ledger:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(ledger[-1]["started_at"])).total_seconds()
            self._last_request = self.clock() - max(0, elapsed)

    def _rate_limit(self):
        # Keep a slower floor after pressure, including bounded retries/resumes.
        pressure = getattr(self.session, "pressure_count", 0)
        self.delay = max(self.minimum_delay, min(10, 2 + 2 * pressure), self.delay)
        super()._rate_limit()

    def _one_url(self, url):
        if self.stop.is_set() or (self.directory / "STOP").exists():
            raise SafetyStop("Manual stop requested; checkpoint preserved.")
        response = super()._one_url(url)
        key = hashlib.sha256(url.encode()).hexdigest()
        payload = self.directory / "responses" / (key + ".body")
        temporary = payload.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write(response.content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, payload)
        save(payload.with_suffix(".json"), {"url": url, "status": response.status_code,
             "sha256": hashlib.sha256(response.content).hexdigest(), "bytes": len(response.content),
             "content_type": response.headers.get("Content-Type", ""), "fetched_at": stamp()})
        return response

    def allowed(self, url):
        # Parent policy failures must stop the run, rather than becoming 400 skips.
        try:
            return super().allowed(url)
        except Exception as error:
            raise SafetyStop("Cannot establish/enforce robots policy: " + type(error).__name__) from error


def matches_record(row, record):
    return row is not None and all(row.get(k) == record[k] for k in
        ("title", "category", "content", "content_hash", "retrieved_at", "last_modified", "source_type", "http_status"))


def commit_intent(database, directory, cp):
    """Reconcile before/after commit; never repeat a completed HTTP request."""
    intent = cp["intent"]
    url = intent["url"]
    record = load(directory / intent["record_file"])
    manager = DatabaseManager.open_existing(database)
    state = snapshot(database)
    current = state["pages"].get(url)
    others = {u: h for u, h in row_hashes(state).items() if u != url}
    expected_others = {u: h for u, h in cp["expected_pages"].items() if u != url}
    if others != expected_others or state["schema"] != cp["schema"] or any(state["fingerprints"][k] != cp["control_fingerprints"][k] for k in ("sync_state", "sync_history")):
        raise SafetyStop("Unexpected writer detected during intent reconciliation.")
    if not matches_record(current, record):
        if (digest(current) if current else None) != intent["old_row_hash"]:
            raise SafetyStop("Intent baseline differs: potential overwrite of valid data.")
        report = manager.index_records([record])
        if report["added"] + report["updated"] + report["unchanged"] != 1:
            raise SafetyStop("Validated record rejected by SQLite writer.")
        current = snapshot(database)["pages"].get(url)
    if not matches_record(current, record):
        raise SafetyStop("Persisted row differs from durable transaction intent.")
    cp["expected_pages"][url] = digest(current)
    cp["outcomes"][url] = intent["outcome"]
    if url not in cp["written_urls"]:
        cp["written_urls"].append(url)
    cp["intent"], cp["inflight"] = None, None
    cp["consecutive_failed_urls"] = 0
    save(directory / "checkpoint.json", cp)


def totals(cp):
    counts = {}
    for outcome in cp["outcomes"].values():
        status = outcome["status"]
        counts[status] = counts.get(status, 0) + 1
    return {"candidates": len(cp["manifest"]), "processed": len(cp["outcomes"]),
            "pending": len(cp["manifest"]) - len(cp["outcomes"]), "outcomes": counts}


def replay_archived(directory):
    """Repair transport-case false aliases + metadata from saved bytes, no HTTP."""
    schedulers_off()
    cp = load(directory / "checkpoint.json")
    database = Path(cp["database"])
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("backfill_offline_qc")
    try:
        check_state(database, cp)
        if cp.get("intent"):
            raise SafetyStop("Reconcile outstanding transaction before offline QC.")
        if cp.get("inflight"):
            ledger = load(directory / "http_ledger.json")
            if any(r["url"] == cp["inflight"] for r in ledger):
                raise SafetyStop("Unresolved attempted HTTP response; review before offline QC.")
            # Proven stop before transport, not a lost HTTP response.
            cp["inflight"] = None
            save(directory / "checkpoint.json", cp)
        original = directory / "offline_qc_originals"
        original.mkdir(exist_ok=True)

        class Archived:
            session = None

            def validate_url(self, url):
                return PoliteHttpClient().validate_url(url)

            def allowed(self, url):
                self.validate_url(url)
                return url in cp["manifest"]

            def get(self, url):
                key = hashlib.sha256(url.encode()).hexdigest()
                payload = directory / "responses" / (key + ".body")
                metadata = load(payload.with_suffix(".json"))
                content = payload.read_bytes()
                if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
                    raise SafetyStop("Archived response checksum mismatch.")
                response = requests.Response()
                response.url = requests.Request("GET", url).prepare().url
                response.status_code = metadata["status"]
                response.headers["Content-Type"] = metadata["content_type"]
                response._content = content
                return response

        crawler = WeWinCrawler(http=Archived())
        replayed, category_fixed = [], []
        for url, previous in list(cp["outcomes"].items()):
            if previous.get("reason") != "redirect_or_canonical_alias_requires_review" or not transport_equivalent_url(previous.get("canonical_url", ""), url):
                continue
            key = hashlib.sha256(url.encode()).hexdigest()
            result_path = directory / "records" / (key + ".result.json")
            if result_path.exists() and not (original / result_path.name).exists():
                shutil.copy2(result_path, original / result_path.name)
            result = crawler.crawl_url_detailed(url)
            save(result_path, result)
            state = snapshot(database)
            old = state["pages"].get(url)
            hashes = {}
            for u, row in state["pages"].items():
                if row["content"].strip():
                    hashes.setdefault(calculate_content_hash(row["content"]), []).append(u)
            record, outcome = result_record(result, old, hashes)
            outcome.update(source="backfill", offline_transport_case_replay=True,
                           completed_at=stamp(), existed_before=previous.get("existed_before", False))
            if record:
                record_file = "records/" + key + ".record.json"
                save(directory / record_file, record)
                cp["intent"] = {"url": url, "old_row_hash": digest(old) if old else None,
                    "record_file": record_file, "outcome": outcome}
                save(directory / "checkpoint.json", cp)
                commit_intent(database, directory, cp)
            else:
                cp["outcomes"][url] = outcome
                save(directory / "checkpoint.json", cp)
            replayed.append(url)

        for url in list(cp["written_urls"]):
            old = snapshot(database)["pages"][url]
            category = PageExtractor._infer_category(url, old["content"])
            if category == old["category"]:
                continue
            record = {**old, "category": category, "last_modified": stamp()}
            outcome = {**cp["outcomes"][url], "category": category,
                       "metadata_category_corrected_from": old["category"]}
            if outcome["status"] == "unchanged":
                outcome["status"] = "updated"
            record_file = "records/" + hashlib.sha256(url.encode()).hexdigest() + ".metadata.record.json"
            save(directory / record_file, record)
            cp["intent"] = {"url": url, "old_row_hash": digest(old), "record_file": record_file, "outcome": outcome}
            save(directory / "checkpoint.json", cp)
            commit_intent(database, directory, cp)
            category_fixed.append(url)

        save(directory / "checkpoint.json", cp)
        status = check_state(database, cp)
        backup = directory / "after_offline_qc.db"
        restore = directory / "after_offline_qc.restore.db"
        if not backup.exists():
            backup_sqlite(database, backup)
        if not restore.exists():
            backup_sqlite(backup, restore)
        if snapshot(restore) != snapshot(database):
            raise SafetyStop("Offline QC backup/restore mismatch.")
        report = {"network_requests": 0, "transport_case_replayed": replayed,
                  "category_corrected": category_fixed, "status": status, "backup_restore": "PASS"}
        save(directory / "offline_qc_result.json", report)
        return report
    finally:
        lock.release()


def finish_batch(database, directory, cp):
    schedulers_off()
    disk_check(directory)
    status = check_state(database, cp)
    urls = cp["active_batch"]["urls"]
    failed = sum(cp["outcomes"].get(u, {}).get("status") == "failed" for u in urls)
    if failed / len(urls) > 0.2:
        raise SafetyStop("Batch HTTP/extraction failure rate exceeds 20 percent.")
    number = len(cp["batches"]) + 1
    prefix = directory / ("batch-%02d" % number)
    backup = prefix.with_suffix(".db")
    restore = prefix.with_suffix(".restore.db")
    if not backup.exists():
        backup_sqlite(database, backup)
    if not restore.exists():
        backup_sqlite(backup, restore)
    if snapshot(restore) != snapshot(database):
        raise SafetyStop("Batch backup/restore mismatch.")
    # Internal FTS test is deliberately performed only on the isolated restore.
    with closing(sqlite3.connect(restore)) as conn:
        conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('integrity-check')")
        conn.commit()
    info = {"number": number, "urls": urls, "completed_at": stamp(), "status": status,
            "counts": totals(cp), "backup_restore": "PASS", "quality": "PASS_ALL_ADMITTED_ROWS"}
    cp["batches"].append(info)
    cp["active_batch"] = None
    cp["next_batch_after"] = time.time() + 30
    save(directory / "checkpoint.json", cp)
    print(json.dumps({"batch_complete": number, **totals(cp), "sqlite": status["pages"],
                      "searchable": status["searchable_unique_urls"], "checks": "PASS"}), flush=True)


def run(directory, max_batches=None):
    schedulers_off()
    cp = load(directory / "checkpoint.json")
    database = Path(cp["database"])
    stop = threading.Event()
    previous_handlers = {}
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("initial_backfill")
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
    try:
        disk_check(directory)
        (directory / "responses").mkdir(exist_ok=True)
        (directory / "records").mkdir(exist_ok=True)
        if cp.get("intent"):
            commit_intent(database, directory, cp)
        check_state(database, cp)
        if cp["phase"] == "complete":
            return {"phase": "complete", "network_requests": 0, **totals(cp)}
        session = BackfillSession(cp["manifest"], directory, stop)
        http = BackfillHttp(directory, stop, session=session)
        crawler = WeWinCrawler(http=http)
        if not cp["manifest"]:
            current, _, _ = crawler.discover_all_urls()
            old = load(directory / "canary_manifest.json")["candidate_urls"]
            save(directory / "manifest.json", {"candidate_urls": current, "discovery": crawler.discovery_stats,
                "added_since_canary": sorted(set(current) - set(old)), "removed_since_canary": sorted(set(old) - set(current))})
            cp["manifest"] = current
            session.urls = set(current)
            if len(current) != len(set(current)):
                raise SafetyStop("Manifest duplicates; refuse ambiguous coverage.")
            for url, outcome in load(directory / "canary_outcomes.json").items():
                if url in current:
                    cp["outcomes"][url] = {**outcome, "source": "sealed_canary", "status": "canary_" + outcome["status"]}
            for url in current:
                if url not in cp["outcomes"] and policy_review(url):
                    cp["outcomes"][url] = {"status": "review", "reason": policy_review(url), "source": "url_policy_no_request"}
            save(directory / "checkpoint.json", cp)
            print(json.dumps({"manifest_frozen": len(current), "sitemap_changed": current != old, **totals(cp)}), flush=True)
        # A crash after HTTP but before its result was durably saved is explicit review.
        if cp.get("inflight"):
            url = cp["inflight"]
            fetched = directory / "records" / (hashlib.sha256(url.encode()).hexdigest() + ".result.json")
            if not fetched.exists():
                cp["outcomes"][url] = {"status": "review", "reason": "interrupted_response_requires_manual_review_no_automatic_refetch"}
                cp["inflight"] = None
                save(directory / "checkpoint.json", cp)
        cp["phase"], cp["stop_reason"] = "running", None
        save(directory / "checkpoint.json", cp)
        starting_batch = len(cp["batches"])
        while True:
            if stop.is_set() or (directory / "STOP").exists():
                raise SafetyStop("Manual stop requested; remove STOP file only after reviewing checkpoint.")
            if cp["active_batch"] and all(u in cp["outcomes"] for u in cp["active_batch"]["urls"]):
                finish_batch(database, directory, cp)
                if max_batches is not None and len(cp["batches"]) - starting_batch >= max_batches:
                    cp["phase"] = "batch_limit_pause"
                    save(directory / "checkpoint.json", cp)
                    return {"phase": cp["phase"], **totals(cp)}
            pending = [u for u in cp["manifest"] if u not in cp["outcomes"]]
            if not pending:
                break
            if not cp["active_batch"]:
                wait = cp["next_batch_after"] - time.time()
                if wait > 0:
                    stop.wait(min(1, wait))
                    continue
                schedulers_off()
                disk_check(directory)
                check_state(database, cp)
                size = 10 if not cp["batches"] else 20
                cp["active_batch"] = {"urls": pending[:size], "started_at": stamp()}
                save(directory / "checkpoint.json", cp)
            url = next(u for u in cp["active_batch"]["urls"] if u not in cp["outcomes"])
            disk_check(directory)
            fetched = directory / "records" / (hashlib.sha256(url.encode()).hexdigest() + ".result.json")
            # Persist marker BEFORE request. A stopped process can never silently restart the page budget.
            cp["inflight"] = url
            save(directory / "checkpoint.json", cp)
            if fetched.exists():
                result = load(fetched)
            else:
                result = crawler.crawl_url_detailed(url)
                save(fetched, result)
            # A valid request blocked by robots is a terminal skip, not a policy bypass.
            if result.get("reason") == "origin_or_robots_policy":
                raise SafetyStop("Origin or robots policy could not be enforced.")
            current = snapshot(database)
            if row_hashes(current) != cp["expected_pages"]:
                raise SafetyStop("Unexpected writer detected before transaction.")
            hashes = {}
            for existing_url, page in current["pages"].items():
                if page["content"].strip():
                    hashes.setdefault(calculate_content_hash(page["content"]), []).append(existing_url)
            old = current["pages"].get(url)
            record, outcome = result_record(result, old, hashes)
            if record and normalize_url(record["url"]) != url:
                raise SafetyStop("Extracted URL differs from frozen manifest target.")
            outcome.update(source="backfill", completed_at=stamp(), existed_before=url in load(directory / "baseline.json")["pages"])
            if record:
                record_file = "records/" + hashlib.sha256(url.encode()).hexdigest() + ".record.json"
                save(directory / record_file, record)
                cp["intent"] = {"url": url, "old_row_hash": digest(old) if old else None,
                                "record_file": record_file, "outcome": outcome}
                save(directory / "checkpoint.json", cp)
                commit_intent(database, directory, cp)
            else:
                cp["outcomes"][url] = outcome
                cp["inflight"] = None
                cp["consecutive_failed_urls"] = cp["consecutive_failed_urls"] + 1 if outcome["status"] == "failed" else 0
                save(directory / "checkpoint.json", cp)
            if cp["consecutive_failed_urls"] >= 3:
                raise SafetyStop("Three consecutive failed page URLs; stop and review website health.")
        check_state(database, cp)
        final = directory / "after_backfill.db"
        restore = directory / "after_restore_verified.db"
        if not final.exists():
            backup_sqlite(database, final)
        if not restore.exists():
            backup_sqlite(final, restore)
        if snapshot(restore) != snapshot(database):
            raise SafetyStop("Final backup/restore mismatch.")
        save(directory / "after_audit.json", inspect_database(database))
        cp["phase"], cp["completed_at"] = "complete", stamp()
        save(directory / "checkpoint.json", cp)
        return {"phase": "complete", "backup_restore": "PASS", **totals(cp)}
    except BaseException as error:
        cp["phase"], cp["stop_reason"], cp["stopped_at"] = "stopped", str(error), stamp()
        save(directory / "checkpoint.json", cp)
        print(json.dumps({"phase": "stopped", "reason": str(error), **totals(cp)}), flush=True)
        raise
    finally:
        lock.release()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run", "replay"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=settings.DATABASE_PATH)
    parser.add_argument("--canary-dir", type=Path)
    parser.add_argument("--max-batches", type=int)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.phase == "prepare":
        if not args.canary_dir:
            parser.error("prepare requires --canary-dir")
        result = initialize(args.database.resolve(strict=True), directory, args.canary_dir)
    elif args.phase == "replay":
        result = replay_archived(directory)
    else:
        result = run(directory, args.max_batches)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
