"""Bounded FIX03B canary. Separate prepare/fetch/apply; never start ordinary sync.

Checkpoints and response evidence stay in a private directory outside data/.
Only an explicit allowlist of 3-5 pages can be fetched. Completed requests are
replayed offline for restore rehearsal and production apply, without refetching.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unicodedata
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
logging.getLogger("wewin_connector").addHandler(logging.NullHandler())
from scripts.repair_fts import backup_sqlite, inspect_database, verify_target_queries
from scripts.rotate_admin_token import restrict_directory
from src.config import settings
from src.crawler.http_client import PoliteHttpClient, CrawlPolicyError
from src.crawler.sitemap_crawler import WeWinCrawler, normalize_url
from src.storage.db import DatabaseManager, calculate_content_hash
from src.sync.locking import SyncLock


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        return {
            "pages": {r["url"]: dict(r) for r in conn.execute("SELECT * FROM pages ORDER BY id")},
            "schema": [list(r) for r in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")],
            "fingerprints": DatabaseManager._data_fingerprints(conn),
        }


def schedulers_off():
    if settings.AUTO_SYNC_ENABLED or settings.SYNC_SCHEDULE_ARMED:
        raise RuntimeError("Both scheduler configuration flags must be false.")
    if os.name == "nt":
        command = "$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName 'WeWIN_Website_AutoSync'; if ($t.Settings.Enabled -or $t.State -eq 'Running') {exit 2}"
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True)


def validate_plan(urls, candidates):
    if not 3 <= len(urls) <= 5 or len(set(urls)) != len(urls):
        raise ValueError("Canary requires exactly 3-5 distinct allowlisted pages.")
    for url in urls:
        PoliteHttpClient().validate_url(url)
        if normalize_url(url) != url or url not in candidates:
            raise ValueError("Canary URL must be normalized and present in reviewed manifest.")


def prepare(database, directory, manifest, urls):
    schedulers_off()
    candidates = load(manifest)["candidate_urls"]
    validate_plan(urls, candidates)
    if directory.exists() or directory.is_relative_to(database.parent):
        raise ValueError("Use a new private run directory outside production data.")
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("canary_prepare")
    try:
        restrict_directory(directory)
        before = snapshot(database)
        backup_sqlite(database, directory / "before_canary.db")
        backup_sqlite(directory / "before_canary.db", directory / "restore_verified.db")
        if snapshot(directory / "restore_verified.db") != before or snapshot(database) != before:
            raise RuntimeError("Restore mismatch or database changed during backup.")
        audit = inspect_database(database)
        if not audit["status"]["consistent"] or not audit["status"]["integrity_ok"]:
            raise RuntimeError("Database/FTS must be consistent before canary.")
        save(directory / "baseline.json", before)
        save(directory / "before_audit.json", audit)
        save(directory / "manifest_before.json", load(manifest))
        save(directory / "checkpoint.json", {"version": 1, "database": str(database), "urls": urls,
             "attempted": [], "results": {}, "phase": "prepared"})
        return {"backup_restore": "PASS", "before": audit["status"], "allowlist": urls}
    finally:
        lock.release()


class BudgetSession:
    """Guard every HTTP attempt, including redirects and retries, before network I/O."""
    METADATA = {"https://wewin.edu.vn/" + name for name in
                ("robots.txt", "sitemap_index.xml", "sitemap.xml", "page-sitemap.xml", "post-sitemap.xml")}

    def __init__(self, urls, directory, session=None):
        self.urls, self.directory = set(urls), directory
        self.session = session or requests.Session()
        self.headers = self.session.headers
        path = directory / "http_ledger.json"
        self.ledger = load(path) if path.exists() else []

    def get(self, url, **kwargs):
        if url not in self.urls and url not in self.METADATA:
            raise CrawlPolicyError("Canary HTTP allowlist refused an unapproved URL/redirect.")
        item = {"url": url, "kind": "metadata" if url in self.METADATA else "page",
                "started_at": datetime.now(timezone.utc).isoformat(), "status": "in_flight"}
        self.ledger.append(item)
        save(self.directory / "http_ledger.json", self.ledger)
        try:
            response = self.session.get(url, **kwargs)
            item["status"] = response.status_code
            return response
        except requests.RequestException:
            item["status"] = "transport_error"
            raise
        finally:
            save(self.directory / "http_ledger.json", self.ledger)


class EvidenceHttp(PoliteHttpClient):
    def __init__(self, directory, **kwargs):
        super().__init__(**kwargs)
        self.directory = directory

    def _rate_limit(self):
        self.delay = max(2.0, self.delay)
        super()._rate_limit()

    def get(self, url, **kwargs):
        response = super().get(url, **kwargs)
        name = hashlib.sha256(url.encode()).hexdigest()
        (self.directory / (name + ".response")).write_bytes(response.content)
        save(self.directory / (name + ".response.json"), {"url": url, "final_url": response.url,
             "http_status": response.status_code, "bytes": len(response.content),
             "sha256": hashlib.sha256(response.content).hexdigest(),
             "content_type": response.headers.get("Content-Type", "")})
        return response


def fetch(directory):
    schedulers_off()
    checkpoint = load(directory / "checkpoint.json")
    if checkpoint["phase"] in ("fetched", "applied"):
        return {"phase": checkpoint["phase"], "network_requests": 0}
    database = Path(checkpoint["database"])
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("canary_fetch")
    try:
        if snapshot(database) != load(directory / "baseline.json"):
            raise RuntimeError("Database changed since approved backup; no crawl performed.")
        candidates = load(directory / "manifest_before.json")["candidate_urls"]
        validate_plan(checkpoint["urls"], candidates)
        http = EvidenceHttp(directory, session=BudgetSession(checkpoint["urls"], directory))
        crawler = WeWinCrawler(http=http)
        if not checkpoint.get("discovery_verified"):
            current, skipped, raw = crawler.discover_all_urls()
            save(directory / "manifest_current.json", {"candidate_urls": current, "discovery": crawler.discovery_stats})
            if current != candidates:
                raise RuntimeError("Manifest changed; review difference before fetching pages.")
            checkpoint["discovery_verified"] = True
            save(directory / "checkpoint.json", checkpoint)
        checkpoint["phase"] = "fetching"
        for url in checkpoint["urls"]:
            if url in checkpoint["results"]:
                continue
            if url in checkpoint["attempted"]:
                # A crash can leave an unknown response. Never silently fetch again.
                checkpoint["results"][url] = {"status": "skipped", "reason": "interrupted_request_requires_review", "data": None}
            else:
                checkpoint["attempted"].append(url)
                save(directory / "checkpoint.json", checkpoint)
                checkpoint["results"][url] = crawler.crawl_url_detailed(url)
            save(directory / "checkpoint.json", checkpoint)
        checkpoint["phase"] = "fetched"
        save(directory / "checkpoint.json", checkpoint)
        return {"phase": "fetched", "unique_pages_attempted": len(checkpoint["attempted"]),
                "http_requests_this_invocation": http.request_count, "retries": http.retry_count,
                "results": {u: {k: v for k, v in r.items() if k != "data"} for u, r in checkpoint["results"].items()}}
    finally:
        lock.release()


def records_from_results(checkpoint, before):
    validate_plan(checkpoint["urls"], checkpoint["urls"])
    if set(checkpoint["results"]) != set(checkpoint["urls"]):
        raise RuntimeError("Fetch all selected URLs or record explicit terminal outcomes first.")
    records, outcomes = [], {}
    for url in checkpoint["urls"]:
        result = checkpoint["results"][url]
        page, old = result.get("data"), before["pages"].get(url)
        if result["status"] != "success" or not page:
            outcomes[url] = {k: v for k, v in result.items() if k != "data"}
            continue  # Failed/skipped requests leave every old column unchanged.
        if page.get("url") != url or not all(isinstance(page.get(k), str) and page[k].strip() for k in ("title", "category", "content")):
            raise ValueError("Invalid extracted metadata or URL.")
        page = {**page, **{k: unicodedata.normalize("NFC", page[k]) for k in ("title", "category", "content")}}
        if len(page["content"].strip()) < 60 or (old and old["source_type"] == "seed" and len(page["content"]) < 300):
            outcomes[url] = {"status": "skipped", "reason": "short_content_or_seed_protected"}
            continue
        page.update(source_type="scraped", content_hash=calculate_content_hash(page["content"]), http_status=200)
        changed = not old or any(page[k] != old[k] for k in ("title", "category", "content", "content_hash", "source_type"))
        page["last_modified"] = page["retrieved_at"] if changed else old["last_modified"]
        records.append(page)
        outcomes[url] = {"status": "added" if not old else "updated" if changed else "unchanged",
                         "title": page["title"], "category": page["category"], "content_chars": len(page["content"])}
    return records, outcomes


def reextract(directory):
    """Replay archived responses with the current extractor; absolutely no HTTP."""
    schedulers_off()
    checkpoint = load(directory / "checkpoint.json")
    if checkpoint["phase"] != "fetched":
        raise RuntimeError("Offline extraction requires fetched, unapplied checkpoint.")
    lock = SyncLock(Path(checkpoint["database"]).parent / "sync.lock")
    lock.acquire("canary_offline_extract")
    try:
        if snapshot(Path(checkpoint["database"])) != load(directory / "baseline.json"):
            raise RuntimeError("Database changed before offline extraction.")
        original = directory / "checkpoint_fetched_original.json"
        if not original.exists():
            save(original, checkpoint)

        class ArchivedHttp:
            session = None

            def validate_url(self, url):
                return PoliteHttpClient().validate_url(url)

            def allowed(self, url):
                self.validate_url(url)
                return url in checkpoint["urls"]

            def get(self, url):
                if url not in checkpoint["urls"]:
                    raise CrawlPolicyError("Offline URL is outside canary allowlist.")
                name = hashlib.sha256(url.encode()).hexdigest()
                metadata = load(directory / (name + ".response.json"))
                content = (directory / (name + ".response")).read_bytes()
                if metadata["sha256"] != hashlib.sha256(content).hexdigest():
                    raise RuntimeError("Archived response checksum mismatch.")
                response = requests.Response()
                response.url, response.status_code = metadata["final_url"], metadata["http_status"]
                response.headers["Content-Type"] = metadata["content_type"]
                response._content = content
                return response

        crawler = WeWinCrawler(http=ArchivedHttp())
        for url in checkpoint["urls"]:
            name = hashlib.sha256(url.encode()).hexdigest()
            if (directory / (name + ".response.json")).exists():
                checkpoint["results"][url] = crawler.crawl_url_detailed(url)
        save(directory / "checkpoint.json", checkpoint)
        return {"phase": "fetched", "offline_reextracted": True, "network_requests": 0,
                "results": {u: r["status"] for u, r in checkpoint["results"].items()}}
    finally:
        lock.release()


def verify_changes(before, after, records):
    allowed = {r["url"] for r in records}
    if before["schema"] != after["schema"] or any(before["fingerprints"][k] != after["fingerprints"][k] for k in ("sync_state", "sync_history")):
        raise RuntimeError("Schema, triggers, cursor or history changed unexpectedly.")
    for url in set(before["pages"]) | set(after["pages"]):
        if url not in allowed and before["pages"].get(url) != after["pages"].get(url):
            raise RuntimeError("Unrelated cached page changed.")
    for record in records:
        row = after["pages"].get(record["url"])
        if not row or any(row[k] != record[k] for k in ("title", "category", "content", "content_hash", "retrieved_at", "last_modified", "source_type", "http_status")):
            raise RuntimeError("Stored record differs from rehearsed Unicode/hash/metadata.")


def apply(directory):
    schedulers_off()
    checkpoint = load(directory / "checkpoint.json")
    if checkpoint["phase"] not in ("fetched", "applied"):
        raise RuntimeError("Fetch must finish before offline rehearsal/apply.")
    database = Path(checkpoint["database"])
    lock = SyncLock(database.parent / "sync.lock")
    lock.acquire("canary_apply")
    try:
        before = load(directory / "baseline.json")
        current = snapshot(database)
        completed = directory / "applied_snapshot.json"
        expected_path = directory / "trial_snapshot.json"
        # Recover an interrupted acknowledgement after the single atomic commit.
        if completed.exists() and current == load(completed) and (directory / "canary_result.json").exists():
            return {"phase": "applied", "writes": 0}
        recovering = expected_path.exists() and current == load(expected_path)
        if current != before and not recovering:
            raise RuntimeError("Database changed since backup; apply refused.")
        records, outcomes = records_from_results(checkpoint, before)
        trial_path = directory / ("trial-" + str(time.time_ns()) + ".db")
        backup_sqlite(directory / "before_canary.db", trial_path)
        trial = DatabaseManager.open_existing(trial_path)
        counts = trial.index_records(records)
        staged = snapshot(trial_path)
        verify_changes(before, staged, records)
        if not inspect_database(trial_path)["status"]["consistent"]:
            raise RuntimeError("Trial FTS consistency failed.")
        verify_target_queries(trial)
        save(expected_path, staged)
        save(directory / "prepared_records.json", records)
        save(directory / "outcomes.json", outcomes)
        # Same validated records, one transaction; no seeds, cursor, export or crawl.
        actual = counts if recovering else DatabaseManager.open_existing(database).index_records(records)
        after = snapshot(database)
        verify_changes(before, after, records)
        if after != staged or actual != counts:
            raise RuntimeError("Production differs from restore rehearsal; stop for review.")
        audit = inspect_database(database)
        if not audit["status"]["consistent"] or not audit["status"]["integrity_ok"]:
            raise RuntimeError("Post-apply SQLite/FTS verification failed.")
        queries = verify_target_queries(DatabaseManager.open_existing(database, read_only=True))
        if not (directory / "after_canary.db").exists():
            backup_sqlite(database, directory / "after_canary.db")
        if not (directory / "after_restore_verified.db").exists():
            backup_sqlite(directory / "after_canary.db", directory / "after_restore_verified.db")
        if snapshot(directory / "after_restore_verified.db") != after:
            raise RuntimeError("Post-canary restore verification failed.")
        save(completed, after)
        save(directory / "after_audit.json", audit)
        checkpoint["phase"] = "applied"
        save(directory / "checkpoint.json", checkpoint)
        report = {"phase": "applied", "counts": actual, "outcomes": outcomes, "after": audit["status"],
                  "queries": queries, "unrelated_pages_schema_cursor_history_unchanged": True,
                  "before_and_after_restore": "PASS"}
        save(directory / "canary_result.json", report)
        return report
    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "fetch", "reextract", "apply"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=settings.DATABASE_PATH)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--url", action="append", default=[])
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if args.phase == "prepare":
        if not args.manifest:
            parser.error("prepare requires --manifest")
        result = prepare(args.database.resolve(strict=True), directory, args.manifest, args.url)
    elif args.phase == "fetch":
        result = fetch(directory)
    elif args.phase == "reextract":
        result = reextract(directory)
    else:
        result = apply(directory)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
