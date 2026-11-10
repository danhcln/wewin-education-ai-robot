"""
SQLite FTS5 Full-Text Search and Knowledge Cache Manager.
Provides sub-millisecond search across crawled WeWIN articles and seed records.
Supports Incremental Synchronization, Content Hashing, and WAL concurrency.
"""
import sqlite3
import re
import hashlib
import unicodedata
import json
from urllib.parse import urlsplit
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from src.storage.knowledge_policy import classify, text_hash
from src.config import settings
from src.utils.logger import logger
from src.crawler.curated_seeds import get_curated_seeds
from src.crawler.sitemap_crawler import normalize_url


class ManagedConnection(sqlite3.Connection):
    """Commit/rollback normally, then release the SQLite handle (including on Windows)."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def calculate_content_hash(text: str) -> str:
    """Calculates SHA-256 hash of normalized text for change detection."""
    if not text:
        return ""
    normalized = " ".join(unicodedata.normalize("NFC", text).strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DatabaseManager:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @classmethod
    def open_existing(cls, db_path: Path, read_only: bool = False):
        """Open maintenance access without migrations, seeding or implicit DB creation."""
        path = Path(db_path).resolve(strict=True)
        if not path.is_file():
            raise ValueError("Expected an existing SQLite database file.")
        manager = cls.__new__(cls)
        manager.db_path = path
        manager._read_only = read_only
        return manager

    def get_connection(self) -> sqlite3.Connection:
        """Returns SQLite connection with row factory and WAL mode enabled for concurrency."""
        if getattr(self, "_read_only", False):
            conn = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=15, factory=ManagedConnection)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            self._register_public_policy(conn)
            return conn
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode and busy timeout to ensure non-blocking reads during sync
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
        except Exception:
            pass
        self._register_public_policy(conn)
        return conn

    @staticmethod
    def _register_public_policy(conn):
        try:
            protected = {r[0] for r in conn.execute("SELECT content_hash FROM protected_knowledge")}
        except sqlite3.OperationalError:
            protected = set()
        conn.create_function("knowledge_is_public", 3, lambda url, title, body: int(classify(url, title, body, protected)[0] == "public"))

    def init_db(self):
        """Initializes tables, columns, indexes and FTS5 search engine."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            # Relational cache table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    content TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL
                );
            """)

            # Safe column migrations if database already existed
            existing_cols = [row[1] for row in cur.execute("PRAGMA table_info(pages);").fetchall()]
            
            if "content_hash" not in existing_cols:
                cur.execute("ALTER TABLE pages ADD COLUMN content_hash TEXT DEFAULT '';")
            if "last_modified" not in existing_cols:
                cur.execute("ALTER TABLE pages ADD COLUMN last_modified TEXT DEFAULT '';")
            if "source_type" not in existing_cols:
                cur.execute("ALTER TABLE pages ADD COLUMN source_type TEXT DEFAULT 'scraped';")
            if "http_status" not in existing_cols:
                cur.execute("ALTER TABLE pages ADD COLUMN http_status INTEGER DEFAULT 200;")

            # FTS5 virtual table for full-text search with unicode61 tokenizer
            cur.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                    title,
                    content,
                    category,
                    url UNINDEXED,
                    tokenize='unicode61'
                );
            """)

            # Sync history audit table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    total_discovered INTEGER NOT NULL,
                    pages_added INTEGER NOT NULL,
                    pages_updated INTEGER NOT NULL,
                    pages_unchanged INTEGER NOT NULL,
                    pages_failed INTEGER NOT NULL,
                    trigger_type TEXT NOT NULL,
                    error_summary TEXT,
                    valid_urls INTEGER DEFAULT 0,
                    pages_skipped INTEGER DEFAULT 0,
                    batch_target_count INTEGER DEFAULT 0,
                    crawl_cursor INTEGER DEFAULT 0
                );
            """)

            # Safe column migrations for sync_history if already existed
            existing_hist_cols = [row[1] for row in cur.execute("PRAGMA table_info(sync_history);").fetchall()]
            if "valid_urls" not in existing_hist_cols:
                cur.execute("ALTER TABLE sync_history ADD COLUMN valid_urls INTEGER DEFAULT 0;")
            if "pages_skipped" not in existing_hist_cols:
                cur.execute("ALTER TABLE sync_history ADD COLUMN pages_skipped INTEGER DEFAULT 0;")
            if "batch_target_count" not in existing_hist_cols:
                cur.execute("ALTER TABLE sync_history ADD COLUMN batch_target_count INTEGER DEFAULT 0;")
            if "crawl_cursor" not in existing_hist_cols:
                cur.execute("ALTER TABLE sync_history ADD COLUMN crawl_cursor INTEGER DEFAULT 0;")

            # Persistent sync state key-value table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            self._install_access_schema(conn)
            self._install_fts_triggers(conn)
            conn.commit()


    @staticmethod
    def _install_access_schema(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_access (
            page_id INTEGER PRIMARY KEY, visibility TEXT NOT NULL DEFAULT 'review'
            CHECK(visibility IN ('public','internal','review')), reason TEXT NOT NULL,
            reviewed_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS protected_knowledge (
            content_hash TEXT PRIMARY KEY, reason TEXT NOT NULL)""")
        conn.execute("""CREATE VIEW IF NOT EXISTS public_pages AS
            SELECT p.* FROM pages p JOIN knowledge_access a ON a.page_id=p.id
            WHERE a.visibility='public' AND knowledge_is_public(p.url,p.title,p.content)=1""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS wewin_access_delete AFTER DELETE ON pages
            BEGIN DELETE FROM knowledge_access WHERE page_id=OLD.id; END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS wewin_access_id AFTER UPDATE OF id ON pages
            WHEN OLD.id!=NEW.id BEGIN DELETE FROM knowledge_access WHERE page_id=OLD.id;
            DELETE FROM knowledge_access WHERE page_id=NEW.id; END""")

    @staticmethod
    def _classify_written_page(conn, url):
        row = conn.execute("SELECT id,title,content FROM pages WHERE url=?", (url,)).fetchone()
        protected = {r[0] for r in conn.execute("SELECT content_hash FROM protected_knowledge")}
        scope, reason = classify(url, row['title'], row['content'], protected)
        old = conn.execute("SELECT visibility FROM knowledge_access WHERE page_id=?", (row['id'],)).fetchone()
        if old and old[0] in ('internal', 'review'):
            return  # Publishing held data requires an explicit local review, never an upsert flag.
        if scope == 'internal':
            conn.execute("INSERT OR IGNORE INTO protected_knowledge VALUES(?,?)", (text_hash(row['content']), reason))
        conn.execute("""INSERT INTO knowledge_access VALUES(?,?,?,?)
            ON CONFLICT(page_id) DO UPDATE SET visibility=excluded.visibility,
            reason=excluded.reason,reviewed_at=excluded.reviewed_at""",
            (row['id'], scope, reason, datetime.now(timezone.utc).isoformat()))

    def index_records(self, records: List[Dict[str, Any]]):
        """Upsert only the supplied URLs; never clear unrelated FTS/cache records.

        Canonical duplicate URLs use the last valid record, with scraped content
        preferred over seeds. The whole batch and trigger-maintained FTS commit
        together. Invalid/empty inputs are reported without replacing good cache.
        """
        report = {"added": 0, "updated": 0, "unchanged": 0, "duplicates": 0,
                  "seed_protected": 0, "skipped": []}
        prepared = {}
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                report["skipped"].append({"position": position, "reason": "invalid_record"})
                continue
            raw_url, content, title = record.get("url"), record.get("content"), record.get("title")
            if not isinstance(raw_url, str) or not raw_url.strip():
                report["skipped"].append({"position": position, "reason": "invalid_url"})
                continue
            if not isinstance(content, str) or not content.strip():
                report["skipped"].append({"position": position, "reason": "empty_or_invalid_content"})
                continue
            if not isinstance(title, str):
                report["skipped"].append({"position": position, "reason": "invalid_title"})
                continue
            if record.get("category") is not None and not isinstance(record["category"], str):
                report["skipped"].append({"position": position, "reason": "invalid_category"})
                continue
            item = dict(record)
            try:
                item["url"] = normalize_url(raw_url)
                parsed = urlsplit(item["url"])
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ValueError("Invalid URL")
            except ValueError:
                report["skipped"].append({"position": position, "reason": "invalid_url"})
                continue
            item["title"] = unicodedata.normalize("NFC", title)
            item["content"] = unicodedata.normalize("NFC", content)
            item["content_hash"] = calculate_content_hash(item["content"])
            if item["url"] in prepared:
                report["duplicates"] += 1
                if item.get("source_type") == "seed" and prepared[item["url"]].get("source_type", "scraped") != "seed":
                    report["seed_protected"] += 1
                    continue
            prepared[item["url"]] = item

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in prepared.values():
                old_row = conn.execute("SELECT * FROM pages WHERE url = ?", (item["url"],)).fetchone()
                old = dict(old_row) if old_row else {}
                source_type = item.get("source_type") or old.get("source_type") or "scraped"
                if old and source_type == "seed" and old.get("source_type") != "seed":
                    report["seed_protected"] += 1
                    continue
                now = datetime.now(timezone.utc).isoformat()
                category = item.get("category") if item.get("category") is not None else old.get("category", "general")
                if not isinstance(category, str):
                    report["skipped"].append({"reason": "invalid_category"})
                    continue
                changed = not old or any(item[key] != old[key] for key in ("title", "content", "content_hash")) or category != old.get("category") or source_type != old.get("source_type")
                retrieved_at = item.get("retrieved_at") or old.get("retrieved_at") or now
                last_modified = item.get("last_modified") or (now if changed else old.get("last_modified")) or retrieved_at
                http_status = item.get("http_status", 200)
                conn.execute("""
                    INSERT INTO pages (url, title, category, content, content_hash, last_modified, retrieved_at, source_type, http_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET
                        title=excluded.title,
                        category=excluded.category,
                        content=excluded.content,
                        content_hash=excluded.content_hash,
                        last_modified=excluded.last_modified,
                        retrieved_at=excluded.retrieved_at,
                        source_type=excluded.source_type,
                        http_status=excluded.http_status;
                """, (item["url"], item["title"], category, item["content"], item["content_hash"], last_modified, retrieved_at, source_type, http_status))
                self._classify_written_page(conn, item["url"])
                report["added" if not old else "updated" if changed else "unchanged"] += 1
        logger.info(f"Indexed batch: added={report['added']}, updated={report['updated']}, unchanged={report['unchanged']}, skipped={len(report['skipped'])}.")
        return report

    @staticmethod
    def _eligible_sql(prefix: str = "") -> str:
        # Python str.strip() whitespace set, expressed in SQLite for trigger use.
        whitespace = "char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)"
        return f"typeof({prefix}content)='text' AND length(trim({prefix}content,{whitespace}))>0 AND typeof({prefix}url)='text' AND length(trim({prefix}url))>0"

    def _install_fts_triggers(self, conn):
        """Keep the existing FTS table/schema; maintain one row per valid page ID."""
        eligible = self._eligible_sql("NEW.")
        insert = f"INSERT INTO pages_fts(rowid,title,content,category,url) SELECT NEW.id,NEW.title,NEW.content,NEW.category,NEW.url WHERE {eligible};"
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS wewin_pages_ai_fts_v2 AFTER INSERT ON pages BEGIN
            DELETE FROM pages_fts WHERE url=NEW.url OR rowid=NEW.id;
            {insert}
        END""")
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS wewin_pages_au_fts_v2 AFTER UPDATE OF id,title,content,category,url ON pages
            WHEN OLD.id IS NOT NEW.id OR OLD.title IS NOT NEW.title OR OLD.content IS NOT NEW.content OR OLD.category IS NOT NEW.category OR OLD.url IS NOT NEW.url
            BEGIN
            DELETE FROM pages_fts WHERE url=OLD.url OR url=NEW.url OR rowid=OLD.id OR rowid=NEW.id;
            {insert}
        END""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS wewin_pages_ad_fts_v2 AFTER DELETE ON pages BEGIN
            DELETE FROM pages_fts WHERE url=OLD.url OR rowid=OLD.id;
        END""")

    def _fts_status(self, conn) -> Dict[str, Any]:
        eligible = self._eligible_sql("p.")
        queries = {
            "pages": "SELECT COUNT(*) FROM pages",
            "eligible_pages": f"SELECT COUNT(*) FROM pages p WHERE {eligible}",
            "fts_rows": "SELECT COUNT(*) FROM pages_fts",
            "fts_unique_urls": "SELECT COUNT(DISTINCT url) FROM pages_fts",
            "duplicate_fts_urls": "SELECT COUNT(*) FROM (SELECT url FROM pages_fts GROUP BY url HAVING COUNT(*)>1)",
            "missing_eligible_pages": f"SELECT COUNT(*) FROM pages p WHERE {eligible} AND NOT EXISTS (SELECT 1 FROM pages_fts f WHERE f.url=p.url)",
            "unexpected_fts_rows": f"SELECT COUNT(*) FROM pages_fts f LEFT JOIN pages p ON p.url=f.url WHERE p.id IS NULL OR NOT ({eligible})",
            "mismatched_fts_rows": "SELECT COUNT(*) FROM pages_fts f JOIN pages p ON p.url=f.url WHERE f.rowid!=p.id OR f.title IS NOT p.title OR f.content IS NOT p.content OR f.category IS NOT p.category",
        }
        result = {name: conn.execute(sql).fetchone()[0] for name, sql in queries.items()}
        result["excluded_pages"] = result["pages"] - result["eligible_pages"]
        result["consistent"] = result["fts_rows"] == result["eligible_pages"] and not any(result[key] for key in ("duplicate_fts_urls", "missing_eligible_pages", "unexpected_fts_rows", "mismatched_fts_rows"))
        return result

    def get_fts_status(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            return self._fts_status(conn)

    @staticmethod
    def _data_fingerprints(conn) -> Dict[str, str]:
        result = {}
        for table, key in (("pages", "id"), ("sync_history", "id"), ("sync_state", "key")):
            rows = [list(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}")]
            encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=lambda value: {"blob_hex": value.hex()}).encode("utf-8")
            result[table] = hashlib.sha256(encoded).hexdigest()
        return result

    def get_data_fingerprints(self) -> Dict[str, str]:
        with self.get_connection() as conn:
            conn.execute("BEGIN")
            return self._data_fingerprints(conn)

    def rebuild_fts(self, expected_snapshot: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Explicit, transactional repair from pages only; never alter cached pages.

        No JSON, seed data, crawler or sync operation is used here. On any failure
        both trigger DDL and all FTS changes roll back with the transaction.
        """
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            original_data = self._data_fingerprints(conn)
            if expected_snapshot is not None and original_data != expected_snapshot:
                raise RuntimeError("Database changed since backup; repair aborted without changes.")
            self._install_fts_triggers(conn)
            conn.execute("DELETE FROM pages_fts")
            conn.execute(f"""INSERT INTO pages_fts(rowid,title,content,category,url)
                SELECT p.id,p.title,p.content,p.category,p.url FROM pages p WHERE {self._eligible_sql('p.')}""")
            conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('integrity-check')")
            result = self._fts_status(conn)
            if not result["consistent"]:
                raise RuntimeError("FTS/cache consistency check failed; repair rolled back.")
            if self._data_fingerprints(conn) != original_data:
                raise RuntimeError("Cached data changed during repair; repair rolled back.")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite integrity check failed; repair rolled back.")
        return result

    def get_existing_hashes(self) -> Dict[str, Dict[str, Any]]:
        """Returns map of url -> {content_hash, title, retrieved_at, source_type} for incremental diffing."""
        hashes = {}
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT url, title, category, content, content_hash, last_modified, retrieved_at, source_type FROM pages;")
            for row in cur.fetchall():
                hashes[row["url"]] = {
                    "content_hash": row["content_hash"] or "",
                    "title": row["title"],
                    "category": row["category"],
                    "content": row["content"],
                    "last_modified": row["last_modified"],
                    "retrieved_at": row["retrieved_at"],
                    "source_type": row["source_type"] or "scraped"
                }
        return hashes

    def update_page_incremental(self, record: Dict[str, Any], is_new: bool) -> bool:
        """
        Atomically writes a new or modified page to relational table and updates FTS5 index.
        Executes within a database transaction.
        """
        # is_new remains accepted for existing callers; URL uniqueness decides.
        report = self.index_records([record])
        return bool(report["added"] + report["updated"] + report["unchanged"])

    def touch_page_unchanged(self, url: str):
        """Updates retrieved_at timestamp for unchanged pages without modifying content or FTS index."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE pages SET retrieved_at = ?, http_status = 200 WHERE url = ?;", (now_iso, url))
            conn.commit()

    def mark_page_error(self, url: str, status_code: int):
        """Updates http_status code when page crawl fails, preserving content intact."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE pages SET http_status = ? WHERE url = ?;", (status_code, url))
            conn.commit()

    def record_sync_history(self, report: Dict[str, Any]) -> int:
        """Stores synchronization audit report into sync_history table."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sync_history (
                    started_at, completed_at, status, duration_seconds,
                    total_discovered, pages_added, pages_updated, pages_unchanged,
                    pages_failed, trigger_type, error_summary,
                    valid_urls, pages_skipped, batch_target_count, crawl_cursor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                report["started_at"],
                report["completed_at"],
                report["status"],
                report["duration_seconds"],
                report["total_discovered"],
                report["pages_added"],
                report["pages_updated"],
                report["pages_unchanged"],
                report["pages_failed"],
                report["trigger_type"],
                report.get("error_summary", ""),
                report.get("valid_urls", 0),
                report.get("pages_skipped", 0),
                report.get("batch_target_count", 0),
                report.get("crawl_cursor", 0)
            ))
            conn.commit()
            return cur.lastrowid

    def get_state(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Reads a persistent sync state key."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM sync_state WHERE key = ?;", (key,))
            row = cur.fetchone()
            if row:
                return row[0]
        return default

    def set_state(self, key: str, value: str):
        """Stores or updates a persistent sync state key."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sync_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at;
            """, (key, str(value), now_iso))
            conn.commit()

    def set_states(self, values: Dict[str, str], history_report=None):
        """Commit checkpoint/cursor/optional history together; no schema changes."""
        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            now = datetime.now(timezone.utc).isoformat()
            for key, value in values.items():
                conn.execute("""INSERT INTO sync_state(key,value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at""", (key, value, now))
            if history_report is not None:
                keys = ("started_at", "completed_at", "status", "duration_seconds", "total_discovered",
                        "pages_added", "pages_updated", "pages_unchanged", "pages_failed", "trigger_type",
                        "error_summary", "valid_urls", "pages_skipped", "batch_target_count", "crawl_cursor")
                conn.execute(f"INSERT INTO sync_history({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",
                             tuple(history_report.get(key, 0 if key not in ("error_summary",) else "") for key in keys))


    def get_last_sync(self) -> Optional[Dict[str, Any]]:
        """Retrieves the most recent sync record."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM sync_history ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def get_sync_history(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Retrieves recent sync history log records."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM sync_history ORDER BY id DESC LIMIT ?;", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_sync_status(self) -> Dict[str, Any]:
        """Provides high-level synchronization health and article counts."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM pages;")
            total_pages = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM pages WHERE source_type = 'seed';")
            seed_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM pages WHERE source_type = 'scraped';")
            scraped_count = cur.fetchone()[0]

            last_sync = self.get_last_sync()

        return {
            "total_pages": total_pages,
            "seed_pages": seed_count,
            "scraped_pages": scraped_count,
            "last_sync": last_sync
        }

    def search(self, query: str, limit: int = 4) -> List[Dict[str, Any]]:
        """
        Executes full-text search with ranking (bm25) and fallback.
        Returns list of matching documents with snippets and source URLs.
        """
        if not query or not query.strip():
            return []

        clean_q = re.sub(r"[^\w\s\d]", " ", unicodedata.normalize("NFC", query)).strip()
        tokens = [t for t in clean_q.split() if len(t) > 1]
        if not tokens:
            tokens = clean_q.split()
        if not tokens:
            return []

        # Build FTS5 match expression with OR between terms for maximum recall
        match_expr = " OR ".join(f'"{t}"' for t in tokens)

        results: List[Dict[str, Any]] = []

        try:
            with self.get_connection() as conn:
                cur = conn.cursor()
                # Use FTS5 bm25 ranking and snippet() function
                sql = """
                    SELECT 
                        title, 
                        url, 
                        category, 
                        snippet(pages_fts, 1, '...', '...', '...', 25) AS snippet,
                        content,
                        bm25(pages_fts) AS rank
                    FROM pages_fts
                    WHERE pages_fts MATCH ? AND rowid IN (SELECT id FROM public_pages)
                    ORDER BY rank ASC
                    LIMIT ?;
                """
                cur.execute(sql, (match_expr, limit))
                rows = cur.fetchall()

                for r in rows:
                    content_preview = r["content"][:300] + ("..." if len(r["content"]) > 300 else "")
                    results.append({
                        "title": r["title"],
                        "url": r["url"],
                        "category": r["category"],
                        "snippet": r["snippet"] or content_preview,
                        "relevance_rank": round(float(r["rank"]), 4)
                    })
        except Exception as e:
            logger.warning("FTS5 query failed (%s); using filtered fallback.", type(e).__name__)
            # Fallback to standard LIKE search
            results = self._fallback_like_search(tokens, limit)

        return results

    def _fallback_like_search(self, tokens: List[str], limit: int) -> List[Dict[str, Any]]:
        """Fallback search using SQL LIKE if FTS expression has syntax peculiarities."""
        results: List[Dict[str, Any]] = []
        with self.get_connection() as conn:
            cur = conn.cursor()
            conditions = ["(title LIKE ? OR content LIKE ?)" for _ in tokens]
            params: List[str] = []
            for t in tokens:
                p = f"%{t}%"
                params.extend([p, p])
            params.append(str(limit))

            sql = f"""
                SELECT title, url, category, content
                FROM public_pages
                WHERE {' OR '.join(conditions)}
                LIMIT ?;
            """
            cur.execute(sql, params)
            for r in cur.fetchall():
                results.append({
                    "title": r["title"],
                    "url": r["url"],
                    "category": r["category"],
                    "snippet": r["content"][:250] + "...",
                    "relevance_rank": 99.0
                })
        return results

    def get_contact(self) -> Dict[str, Any]:
        """Returns structured contact details for WeWIN Education."""
        return {
            "name": "WeWIN Education (Trung tâm Ngoại ngữ Công Thành)",
            "hotline": "034 596 9388 - 037 866 9388",
            "phone_zalo": "0988 596 388",
            "email": "ntloffice@wewin.edu.vn",
            "campuses": [
                {
                    "name": "Cơ sở 1 (CS1)",
                    "address": "292B Nơ Trang Long, Phường 12, Quận Bình Thạnh, TP.HCM"
                },
                {
                    "name": "Cơ sở 2 (CS2)",
                    "address": "742 Xô Viết Nghệ Tĩnh, Phường 25 (Thạnh Mỹ Tây), Quận Bình Thạnh, TP.HCM"
                }
            ],
            "registration_link": "https://wewin.edu.vn/dang-ky-tai-khoan-sach-online-free/",
            "fanpage": "https://www.facebook.com/winwineducation",
            "source_url": "https://wewin.edu.vn/"
        }

    def get_programs(self, age: Optional[int] = None) -> Dict[str, Any]:
        """
        Returns structured programs list.
        If age is provided, provides tailored recommendation.
        """
        all_programs = [
            {
                "name": "Tiếng Anh Mầm non",
                "age_range": "3 - 6 tuổi",
                "description": "Giúp con làm quen tiếng Anh tự nhiên, hình thành phản xạ nhanh nhạy và sự tự tin ban đầu thông qua trò chơi và phương pháp trực quan.",
                "source_url": "https://wewin.edu.vn/#ctrinhhoc"
            },
            {
                "name": "Tiếng Anh Cambridge (Tiểu học)",
                "age_range": "6 - 12 tuổi",
                "description": "Phát triển toàn diện 4 kỹ năng Nghe - Nói - Đọc - Viết. Lộ trình chinh phục các cấp độ chứng chỉ quốc tế Cambridge: Starters, Movers, Flyers, KET, PET. Kết hợp Speaking AI và hỗ trợ 1:1 ngữ pháp.",
                "source_url": "https://wewin.edu.vn/#ctrinhhoc"
            },
            {
                "name": "IELTS Explorer & Luyện thi IELTS",
                "age_range": "12 - 18 tuổi và trên 18 tuổi",
                "description": "Chương trình tiếng Anh học thuật chuyên sâu, xây dựng nền tảng từ vựng, ngữ pháp vững chắc và bứt phá band điểm IELTS phục vụ xét tuyển đại học hoặc du học. WeWIN là đối tác chính thức của IDP.",
                "source_url": "https://wewin.edu.vn/ielts-placement-test/"
            }
        ]

        recommendation = None
        if age is not None:
            if 3 <= age <= 6:
                recommendation = {
                    "age": age,
                    "recommended_program": "Tiếng Anh Mầm non",
                    "reason": f"Bé {age} tuổi thuộc khung 3-6 tuổi, phù hợp nhất với chương trình Tiếng Anh Mầm non để làm quen ngữ âm, bài hát và phản xạ tự nhiên."
                }
            elif 6 <= age <= 12:
                recommendation = {
                    "age": age,
                    "recommended_program": "Tiếng Anh Cambridge (Tiểu học)",
                    "level_details": "Tùy theo kết quả kiểm tra năng lực đầu vào 4 kỹ năng, bé 9 tuổi sẽ được xếp vào cấp độ phù hợp nhất như Movers hoặc Flyers.",
                    "reason": f"Bé {age} tuổi (tiểu học) nằm trong độ tuổi vàng của hệ thống Tiếng Anh Cambridge tại WeWIN, giúp rèn luyện toàn diện Nghe - Nói - Đọc - Viết và ôn thi chứng chỉ quốc tế."
                }
            elif age > 12:
                recommendation = {
                    "age": age,
                    "recommended_program": "IELTS Explorer & Luyện thi IELTS",
                    "reason": f"Học viên {age} tuổi phù hợp với lộ trình IELTS Explorer để xây dựng tiếng Anh học thuật và đạt điểm IELTS mục tiêu."
                }
            else:
                recommendation = {
                    "age": age,
                    "recommended_program": "Chưa có lớp cho trẻ dưới 3 tuổi",
                    "reason": "WeWIN nhận học viên từ 3 tuổi trở lên."
                }

        return {
            "programs": all_programs,
            "recommendation": recommendation,
            "free_assessment": "Tất cả học viên mới đều được tặng 1 buổi test năng lực 4 kỹ năng miễn phí và tư vấn lộ trình riêng.",
            "source_url": "https://wewin.edu.vn/#ctrinhhoc"
        }

    def get_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Retrieves full cached content for a specific URL."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT url, title, category, content, content_hash, last_modified, retrieved_at, source_type, http_status FROM public_pages WHERE url = ?;", (normalize_url(url),))
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

# Singleton accessor
_db_instance = None

def get_db() -> DatabaseManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
