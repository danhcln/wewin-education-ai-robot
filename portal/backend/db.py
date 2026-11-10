"""Portal-only SQLite storage. No migrations run against Connector databases."""
from contextlib import contextmanager, closing
from pathlib import Path
import os
import sqlite3
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('WEWIN_EDUCATION_DB', ROOT / 'data/education.sqlite3'))


@contextmanager
def connection(path=None, readonly=False):
    path = Path(path or DB).resolve()
    if not readonly:
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rwc'), uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    if readonly:
        db.execute('PRAGMA query_only=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def migrate():
    """Back up before an additive migration; execute DDL and version in one transaction."""
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)')
        current = db.execute('SELECT COALESCE(MAX(version),0) FROM schema_version').fetchone()[0]
        if current >= 2:
            return
        if current:
            backup = DB.parent / f'education-before-v2-{uuid4().hex}.sqlite3'
            with closing(sqlite3.connect(backup)) as out:
                db.backup(out)
        db.execute('BEGIN IMMEDIATE')
        if current < 1:
            for sql in [
                'CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires INTEGER NOT NULL, role TEXT NOT NULL)',
                'CREATE TABLE robot_config(robot_id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL, sync_state TEXT NOT NULL, updated_at INTEGER NOT NULL, updated_by TEXT NOT NULL)',
                'CREATE TABLE config_history(robot_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, sync_state TEXT NOT NULL, updated_at INTEGER NOT NULL, updated_by TEXT NOT NULL, PRIMARY KEY(robot_id,version))',
                'CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, robot_id TEXT, version INTEGER, at INTEGER NOT NULL, actor TEXT NOT NULL)',
            ]:
                db.execute(sql)
            db.execute('INSERT INTO schema_version VALUES(1,?)', (int(time.time()),))
        statements = [
            "CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','teacher','student','guardian')), active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)",
            "CREATE TABLE user_profiles(user_id TEXT PRIMARY KEY REFERENCES users(id), level TEXT NOT NULL DEFAULT 'STARTER', goal TEXT NOT NULL DEFAULT '')",
            'ALTER TABLE sessions ADD COLUMN user_id TEXT REFERENCES users(id)',
            'CREATE TABLE guardian_links(guardian_id TEXT NOT NULL REFERENCES users(id), student_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(guardian_id,student_id))',
            'CREATE TABLE devices(id TEXT PRIMARY KEY, source TEXT NOT NULL, created_at INTEGER NOT NULL)',
            'CREATE TABLE device_bindings(device_id TEXT NOT NULL REFERENCES devices(id), user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(device_id,user_id))',
            "CREATE TABLE ai_roles(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','draft','archived')), created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)",
            "CREATE TABLE lessons(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, level TEXT NOT NULL, topic TEXT NOT NULL, language TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','published','archived')), created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)",
            'CREATE TABLE lesson_modules(id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id), position INTEGER NOT NULL, title TEXT NOT NULL, UNIQUE(lesson_id,position))',
            'CREATE TABLE learning_paths(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, level TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)',
            'CREATE TABLE path_lessons(path_id TEXT NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE, lesson_id TEXT NOT NULL REFERENCES lessons(id), position INTEGER NOT NULL, PRIMARY KEY(path_id,lesson_id), UNIQUE(path_id,position))',
            'CREATE TABLE enrollments(user_id TEXT NOT NULL REFERENCES users(id), path_id TEXT NOT NULL REFERENCES learning_paths(id), created_at INTEGER NOT NULL, PRIMARY KEY(user_id,path_id))',
            "CREATE TABLE learning_sessions(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), lesson_id TEXT NOT NULL REFERENCES lessons(id), started_at INTEGER NOT NULL, completed_at INTEGER, duration_seconds INTEGER, score REAL, evidence TEXT NOT NULL DEFAULT 'browser_practice', lesson_snapshot TEXT NOT NULL, answers TEXT)",
            'CREATE TABLE learning_progress(user_id TEXT NOT NULL REFERENCES users(id), lesson_id TEXT NOT NULL REFERENCES lessons(id), completed_at INTEGER NOT NULL, best_score REAL NOT NULL, PRIMARY KEY(user_id,lesson_id))',
            'CREATE TABLE learning_bindings(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), device_id TEXT REFERENCES devices(id), role_id TEXT REFERENCES ai_roles(id), lesson_id TEXT REFERENCES lessons(id), path_id TEXT REFERENCES learning_paths(id), knowledge_id TEXT, media_id TEXT, created_at INTEGER NOT NULL)',
            "CREATE TABLE tasks(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, content TEXT NOT NULL, due_date TEXT, priority TEXT NOT NULL, status TEXT NOT NULL, student_id TEXT REFERENCES users(id), device_id TEXT REFERENCES devices(id), lesson_id TEXT REFERENCES lessons(id), created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)",
            'CREATE TABLE task_history(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, at INTEGER NOT NULL)',
            'CREATE TABLE memories(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, content TEXT NOT NULL, category TEXT NOT NULL, device_id TEXT REFERENCES devices(id), session_id TEXT REFERENCES learning_sessions(id), created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)',
            'CREATE TABLE homework_requests(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), question TEXT NOT NULL, explanation TEXT, status TEXT NOT NULL, created_at INTEGER NOT NULL)',
            "CREATE TABLE knowledge_documents(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)",
            "CREATE VIRTUAL TABLE knowledge_fts USING fts5(id UNINDEXED,title,content,tokenize='unicode61 remove_diacritics 2')",
            "CREATE TRIGGER knowledge_insert AFTER INSERT ON knowledge_documents BEGIN INSERT INTO knowledge_fts VALUES(new.id,new.title,new.content); END",
            "CREATE TRIGGER knowledge_delete AFTER DELETE ON knowledge_documents BEGIN DELETE FROM knowledge_fts WHERE id=old.id; END",
            "CREATE TRIGGER knowledge_update AFTER UPDATE ON knowledge_documents BEGIN DELETE FROM knowledge_fts WHERE id=old.id; INSERT INTO knowledge_fts VALUES(new.id,new.title,new.content); END",
            'CREATE TABLE media_assets(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), title TEXT NOT NULL, kind TEXT NOT NULL, url TEXT NOT NULL, created_at INTEGER NOT NULL)',
            'CREATE TABLE media_lesson_bindings(media_id TEXT NOT NULL REFERENCES media_assets(id), lesson_id TEXT NOT NULL REFERENCES lessons(id), PRIMARY KEY(media_id,lesson_id))',
            'CREATE TABLE config_sync_history(id INTEGER PRIMARY KEY AUTOINCREMENT, robot_id TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL, at INTEGER NOT NULL, actor TEXT NOT NULL)',
            'CREATE INDEX session_user_idx ON learning_sessions(user_id,started_at)',
            'CREATE INDEX lesson_filter_idx ON lessons(status,level,topic)',
            'CREATE INDEX memory_owner_idx ON memories(owner_id,category)',
            'CREATE INDEX task_student_idx ON tasks(student_id,status)',
            'CREATE INDEX audit_at_idx ON audit(at)',
        ]
        for sql in statements:
            db.execute(sql)
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', ('local-admin','local-admin','Quản trị WeWIN','!token-only','admin',1,int(time.time())))
        db.execute('INSERT INTO user_profiles(user_id) VALUES(?)', ('local-admin',))
        db.execute('INSERT INTO schema_version VALUES(2,?)', (int(time.time()),))


def audit(db, action, actor, resource=None, version=None):
    db.execute('INSERT INTO audit(action,robot_id,version,at,actor) VALUES(?,?,?,?,?)',
               (action, resource, version, int(time.time()), actor))
