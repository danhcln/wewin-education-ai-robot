"""WAL-aware backup, restore rehearsal and optional transactional FTS repair.

No crawler, real sync, JSON import, seeding or service is started. --apply must
be explicit. A new private backup directory is required for every invocation.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Maintenance reports are explicit files; importing app logging must not append
# to the running installation's logs (or print cached content/credentials).
logging.getLogger("wewin_connector").addHandler(logging.NullHandler())
from src.storage.db import DatabaseManager, calculate_content_hash
from src.crawler.sitemap_crawler import normalize_url
from scripts.rotate_admin_token import restrict_directory
from src.sync.locking import SyncLock


def backup_sqlite(source: Path, destination: Path):
    if destination.exists():
        raise FileExistsError("Backup destination already exists.")
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as reader:
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer)
            # Produce a self-contained backup, not a DB file requiring sidecars.
            writer.execute("PRAGMA journal_mode=DELETE")
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed.")


def inspect_database(database: Path):
    """Read a coherent snapshot without migrations or PRAGMA journal changes."""
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN")
        manager = DatabaseManager.open_existing(database)
        status = manager._fts_status(conn)
        # Count documents actually represented in the inverted index, not just
        # rows in the FTS content table. The vocabulary lives only in temp.
        conn.execute("CREATE VIRTUAL TABLE temp.fts_audit_vocab USING fts5vocab(main, pages_fts, instance)")
        status["searchable_unique_urls"] = conn.execute("SELECT COUNT(DISTINCT f.url) FROM pages_fts f JOIN temp.fts_audit_vocab v ON v.doc=f.rowid").fetchone()[0]
        status["duplicate_page_urls"] = conn.execute("SELECT COUNT(*) FROM (SELECT url FROM pages GROUP BY url HAVING COUNT(*)>1)").fetchone()[0]
        status["integrity_ok"] = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        quality, canonical = [], {}
        for row in conn.execute("SELECT id,url,title,content,content_hash FROM pages ORDER BY id"):
            reasons, content = [], row["content"]
            if not isinstance(content, str):
                reasons.append("invalid_content_type")
            else:
                if not content.strip(): reasons.append("empty_content")
                elif len(content.strip()) < 60: reasons.append("short_content_under_60")
                if row["content_hash"] != calculate_content_hash(content): reasons.append("hash_mismatch")
            if reasons:
                quality.append({"id": row["id"], "url": row["url"], "title": row["title"], "content_chars": len(content) if isinstance(content, (str, bytes)) else None, "issues": reasons})
            try:
                canonical.setdefault(normalize_url(row["url"]), []).append(row["id"])
            except (TypeError, ValueError):
                quality.append({"id": row["id"], "issues": ["invalid_url"]})
        status["canonical_duplicate_groups"] = [ids for ids in canonical.values() if len(ids) > 1]
        return {"status": status, "quality_issues": quality, "data_fingerprints": manager._data_fingerprints(conn)}


def verify_target_queries(manager: DatabaseManager):
    checks = []
    for query, url in [
        ("Relative Clause", "https://wewin.edu.vn/game-ve-relative-clause/"),
        ("Oxford Phonics", "https://wewin.edu.vn/bo-sach-day-phat-am-tieng-anh-oxford-phonics-world/"),
    ]:
        page = manager.get_page(url)
        if page and isinstance(page["content"], str) and page["content"].strip():
            found = url in {row["url"] for row in manager.search(query, limit=10000)}
            if not found:
                raise RuntimeError("Required cached page not found through recovered FTS.")
            checks.append({"query": query, "url": url, "found": True})
    return checks


def repair(database: Path, backup_dir: Path, apply: bool = False):
    database = database.resolve(strict=True)
    backup_dir = backup_dir.resolve()
    if backup_dir.exists():
        raise FileExistsError("Use a new backup directory for each repair attempt.")
    if backup_dir.is_relative_to(database.parent):
        raise ValueError("Keep the backup outside the production data directory.")
    if SyncLock(database.parent / "sync.lock").is_locked():
        raise RuntimeError("Sync lock exists. Stop active jobs before maintenance; no lock was removed.")
    restrict_directory(backup_dir)
    before = inspect_database(database)
    backup_path = backup_dir / "before_repair.db"
    backup_sqlite(database, backup_path)
    backed_up = inspect_database(backup_path)
    if backed_up["data_fingerprints"] != before["data_fingerprints"]:
        raise RuntimeError("Source changed while backing up; maintenance aborted.")
    trial_path = backup_dir / "restored_trial.db"
    backup_sqlite(backup_path, trial_path)
    restored = inspect_database(trial_path)
    if restored != backed_up:
        raise RuntimeError("Backup restore verification failed.")
    trial = DatabaseManager.open_existing(trial_path)
    trial_after = trial.rebuild_fts(expected_snapshot=before["data_fingerprints"])
    queries = verify_target_queries(trial)
    if trial.get_data_fingerprints() != before["data_fingerprints"]:
        raise RuntimeError("Rehearsal changed cached data.")
    if trial.rebuild_fts(expected_snapshot=before["data_fingerprints"]) != trial_after:
        raise RuntimeError("Rehearsal was not idempotent.")
    report = {
        "timestamp": datetime.now(timezone(timedelta(hours=7))).isoformat(),
        "database": str(database), "backup": str(backup_path),
        "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "backup_method": "SQLite Backup API; committed WAL included; standalone DELETE-journal backup",
        "backup_restore_verified": True, "before": before, "trial_after": trial_after,
        "trial_queries": queries, "trial_repeated_repair_passed": True, "applied": False,
    }
    # Save rehearsal evidence before opening a write transaction on production.
    report_path = backup_dir / "repair_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if apply:
        if SyncLock(database.parent / "sync.lock").is_locked():
            raise RuntimeError("Sync started during rehearsal; apply aborted.")
        production = DatabaseManager.open_existing(database)
        result = production.rebuild_fts(expected_snapshot=before["data_fingerprints"])
        report["after"] = inspect_database(database)
        report["queries_after"] = verify_target_queries(production)
        report["applied"] = True
        if report["after"]["data_fingerprints"] != before["data_fingerprints"] or not result["consistent"]:
            raise RuntimeError("Post-apply verification failed; retain backup and inspect before rollback.")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = repair(args.database, args.backup_dir, args.apply)
    print(json.dumps({"applied": report["applied"], "backup_restore_verified": True,
                      "before": report["before"]["status"],
                      "after": report.get("after", {}).get("status", report["trial_after"]),
                      "report": str(args.backup_dir / "repair_report.json")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
