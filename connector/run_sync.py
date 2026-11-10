"""Safe sync launcher: planning by default; real writes require --execute."""
import argparse
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path: sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", "--plan-only", action="store_true", dest="dry_run")
    parser.add_argument("--execute", action="store_true", help="Explicitly permit page fetches and database writes")
    parser.add_argument("--batch-size", "--max-pages", type=int, dest="batch_size")
    parser.add_argument("--all", action="store_true", help="Plan full coverage; processing still respects the per-run batch budget")
    parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled", "task_scheduler", "api", "cron", "systemd"])
    parser.add_argument("--force-unlock", action="store_true", help="Recover stale metadata only; live jobs are never unlocked")
    parser.add_argument("--recover-corrupt", action="store_true", help="Local explicit recovery after legacy workers are verified stopped; live OS locks still refused")
    parser.add_argument("--scheduler-probe", action="store_true", help="No imports of backend, database or crawler; no network")
    parser.add_argument("--probe-output", type=Path)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.scheduler_probe:
        result = {"probe": "PASS", "pid": os.getpid(), "time": datetime.now(timezone.utc).isoformat(), "network_used": False, "database_opened": False}
        if args.probe_output:
            args.probe_output.write_text(json.dumps(result), encoding="utf-8")
        print(json.dumps(result))
        return 0
    import logging
    logging.getLogger("wewin_connector").addHandler(logging.NullHandler())
    from src.config import settings
    from src.storage.db import DatabaseManager
    from src.sync.sync_engine import SyncEngine, SyncLock, SyncAlreadyRunningError
    if args.force_unlock or args.recover_corrupt:
        try: SyncLock().recover_stale(allow_corrupt=args.recover_corrupt)
        except SyncAlreadyRunningError:
            print("Live job detected; unlock refused.")
            return 2
        print("Stale metadata recovered; persistent OS guard retained.")
        return 0
    dry_run = args.dry_run or not args.execute
    if args.trigger in ("scheduled", "task_scheduler", "cron", "systemd"):
        owner = "internal" if args.trigger == "scheduled" else "windows" if args.trigger == "task_scheduler" else "external"
        if not settings.SYNC_SCHEDULE_ARMED or settings.SYNC_SCHEDULER_OWNER != owner:
            print(json.dumps({"status":"disabled", "database_opened":False, "network_used":False}))
            return 0
    db = DatabaseManager.open_existing(settings.DATABASE_PATH, read_only=True) if dry_run else None
    engine = SyncEngine(db=db)
    import signal
    import threading
    cancelled = threading.Event()
    def stop(signum, frame):
        cancelled.set()
        engine.request_stop()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        slot = None
        if args.trigger in ("scheduled", "task_scheduler", "cron", "systemd"):
            from src.sync.scheduler import latest_slot
            slot = latest_slot().isoformat()
        report = engine.run_sync(trigger_type=args.trigger, max_pages=args.batch_size, dry_run=dry_run, crawl_all=args.all, scheduled_slot=slot, cancel_event=cancelled)
        print(json.dumps(report.to_dict(), ensure_ascii=True))
        return 130 if report.status == "interrupted" else 1 if report.status == "failed" else 0
    except SyncAlreadyRunningError:
        print("Another sync job is active; no work started.")
        return 2
    except Exception:
        print("Sync/plan failed. No cursor reset performed; inspect metadata and connectivity.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
