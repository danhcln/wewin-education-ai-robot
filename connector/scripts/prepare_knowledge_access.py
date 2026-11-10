"""Explicit offline publication review; preserves every original page column.

Call migrate() on a restored copy first. No network, crawl, seed, or token changes.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage.db import DatabaseManager
from src.storage.knowledge_policy import classify, text_hash


def migrate(path, review_queue=()):
    manager = DatabaseManager.open_existing(Path(path))
    held = {r['url']: r for r in review_queue if r.get('status') == 'review'}
    report = []
    with manager.get_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        manager._install_access_schema(conn)
        rows = [dict(r) for r in conn.execute('SELECT * FROM pages ORDER BY id')]
        protected = {text_hash(r['content']) for r in rows
                     if classify(r['url'], r['title'], r['content'])[0] == 'internal'}
        for digest in protected:
            conn.execute('INSERT OR IGNORE INTO protected_knowledge VALUES(?,?)', (digest, 'preserved_internal_original'))
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            scope, reason = classify(row['url'], row['title'], row['content'], protected)
            pending = held.get(row['url'])
            if scope == 'public' and row['source_type'] != 'seed':
                if len(row['content'].strip()) < 120:
                    scope, reason = 'review', 'legacy_short_content'
                elif pending:
                    scope, reason = 'review', pending['reason']
            # Re-running cannot silently promote a previous internal/review decision.
            previous = conn.execute('SELECT visibility,reason FROM knowledge_access WHERE page_id=?', (row['id'],)).fetchone()
            if previous and previous['visibility'] in ('internal', 'review'):
                scope, reason = previous['visibility'], previous['reason']
            conn.execute('INSERT OR REPLACE INTO knowledge_access VALUES(?,?,?,?)', (row['id'], scope, reason, now))
            report.append({'id': row['id'], 'url': row['url'], 'visibility': scope, 'reason': reason,
                           'chars': len(row['content']), 'hash_matches': row['content_hash'] == text_hash(row['content']),
                           'source_type': row['source_type'], 'retrieved_at': row['retrieved_at']})
        assert rows == [dict(r) for r in conn.execute('SELECT * FROM pages ORDER BY id')]
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--queue', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    result = migrate(args.database, json.loads(args.queue.read_text(encoding='utf-8')))
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({s: sum(r['visibility'] == s for r in result) for s in ('public', 'internal', 'review')}))
