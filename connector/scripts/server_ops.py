"""Offline operational checks and WAL-aware backups. No crawler imports or jobs.

Restore requires stopped services, the sync OS lock, and a fresh safety backup.
The operator is responsible for stopping API/bridge and all other DB readers.
"""
import argparse
import hashlib
import json
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def inspect(path):
    from src.storage.db import DatabaseManager
    db = DatabaseManager.open_existing(Path(path), read_only=True)
    with db.get_connection() as conn:
        integrity = conn.execute('PRAGMA integrity_check').fetchall()
        status = db._fts_status(conn)
        access = dict(conn.execute('SELECT visibility,count(*) FROM knowledge_access GROUP BY visibility').fetchall())
        public = conn.execute('SELECT count(*) FROM public_pages').fetchone()[0]
        unclassified = conn.execute('SELECT count(*) FROM pages WHERE id NOT IN (SELECT page_id FROM knowledge_access)').fetchone()[0]
        digests = {}
        for table in ('pages','pages_fts','knowledge_access','protected_knowledge','sync_state','sync_history'):
            rows = [tuple(r) for r in conn.execute('SELECT * FROM '+table+' ORDER BY 1')]
            digests[table] = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if [r[0] for r in integrity] != ['ok'] or not status['consistent']:
        raise RuntimeError('SQLite integrity or FTS consistency failed')
    return {'integrity': 'ok', 'fts': status, 'visibility': access, 'public_searchable': public,
            'unclassified': unclassified, 'fingerprints': digests}


def backup(source, target):
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('Backup requires a new destination')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Restrictive creation before any original data is written.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as reader:
        with closing(sqlite3.connect(target)) as writer:
            reader.backup(writer)
            writer.execute('PRAGMA journal_mode=DELETE')
            if writer.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity failed')
    return target


def restore(source, target, safety, services_stopped=False):
    if not services_stopped:
        raise ValueError('Stop API, bridge, scheduler and every SQLite writer first')
    from src.sync.locking import SyncLock
    source, target = Path(source).resolve(strict=True), Path(target).resolve(strict=True)
    expected = inspect(source)
    lock = SyncLock(target.parent/'sync.lock')
    lock.acquire('offline_restore')
    try:
        backup(target, safety)
        # Restore through SQLite rather than replacing the main file under a WAL.
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as reader:
            with closing(sqlite3.connect(target)) as writer:
                reader.backup(writer)
        actual = inspect(target)
        if actual['fingerprints'] != expected['fingerprints']:
            raise RuntimeError('Restore verification failed; preserve safety backup')
        return actual
    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check','backup','restore'])
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--safety-backup', type=Path)
    parser.add_argument('--services-stopped', action='store_true')
    args = parser.parse_args()
    if args.action == 'check':
        result = inspect(args.database)
    elif args.action == 'backup':
        if not args.snapshot: parser.error('--snapshot required')
        backup(args.database, args.snapshot)
        result = inspect(args.snapshot)
        restored = args.snapshot.with_name(args.snapshot.name+'.restore-check')
        backup(args.snapshot, restored)
        if inspect(restored)['fingerprints'] != result['fingerprints']:
            raise RuntimeError('Restore rehearsal differs')
        result['restore_rehearsal'] = 'PASS'
    else:
        if not args.snapshot or not args.safety_backup: parser.error('--snapshot and --safety-backup required')
        result = restore(args.snapshot,args.database,args.safety_backup,args.services_stopped)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
