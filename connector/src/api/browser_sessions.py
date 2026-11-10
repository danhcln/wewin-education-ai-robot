"""Private browser sessions and player preferences. Never the knowledge SQLite."""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
import time
import tempfile
from urllib.parse import urlsplit
from fastapi import HTTPException, Request, Response
from src.config import BASE_DIR, settings

COOKIE='wewin_browser'
TTL=7*86400
MAX_AGE=30*86400
OWNER='local-admin'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def same_origin(request):
    origin=urlsplit(request.headers.get('origin',''))
    if (request.url.hostname not in ('127.0.0.1','localhost','::1') or
        origin.scheme!={'ws':'http','wss':'https'}.get(request.url.scheme,request.url.scheme) or origin.netloc!=request.headers.get('host') or
        request.headers.get('sec-fetch-site') in ('cross-site','none')):
        raise HTTPException(403,'Same-origin localhost request required.')

class BrowserStore:
    def __init__(self,path,clock=time.time):
        self.path=Path(path).resolve();self.clock=clock
        if self.path.suffix!='.sqlite3' or self.path.parent.name!='.secrets' or self.path.is_relative_to(BASE_DIR/'frontend') or self.path.is_relative_to(BASE_DIR/'data'):
            raise ValueError('Browser state requires a dedicated .secrets directory.')
        from scripts.rotate_admin_token import restrict_directory
        if not self.path.parent.exists():restrict_directory(self.path.parent)
        if not self.path.exists():
            try:
                fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            except FileExistsError:pass
        with self.connection() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS browser_sessions(hash TEXT PRIMARY KEY,owner TEXT,stamp TEXT,expires REAL,created REAL);
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS media_devices(owner TEXT,device TEXT,name TEXT,enabled INTEGER DEFAULT 1,is_default INTEGER DEFAULT 0,PRIMARY KEY(owner,device));
            CREATE TABLE IF NOT EXISTS media_intents(owner TEXT,rid TEXT,device TEXT,epoch TEXT,signature TEXT,created REAL,PRIMARY KEY(owner,rid));
            CREATE UNIQUE INDEX IF NOT EXISTS one_default_player ON media_devices(owner) WHERE is_default=1 AND enabled=1;
            ''')
            c.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)',('csrf_key',secrets.token_hex(32)))
            self.csrf_key=c.execute('SELECT value FROM metadata WHERE key=?',('csrf_key',)).fetchone()[0].encode()

    @contextmanager
    def connection(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def create(self,old=None):
        if not settings.ADMIN_SYNC_TOKEN:raise HTTPException(401,'Admin access is not configured.')
        token=secrets.token_urlsafe(32);now=self.clock()
        with self.connection() as c:
            c.execute('DELETE FROM browser_sessions WHERE expires<=?',(now,))
            if old:c.execute('DELETE FROM browser_sessions WHERE hash=?',(digest(old),))
            cols = [col[1] for col in c.execute("PRAGMA table_info(browser_sessions);").fetchall()]
            if 'principal_id' in cols:
                c.execute(
                    'INSERT INTO browser_sessions (hash, owner, stamp, expires, created, principal_id, auth_version) VALUES (?,?,?,?,?,?,?)',
                    (digest(token), OWNER, digest(settings.ADMIN_SYNC_TOKEN), now+TTL, now, 'principal-local-admin', 1)
                )
            else:
                c.execute(
                    'INSERT INTO browser_sessions (hash, owner, stamp, expires, created) VALUES (?,?,?,?,?)',
                    (digest(token), OWNER, digest(settings.ADMIN_SYNC_TOKEN), now+TTL, now)
                )
        return token

    def read(self,token):
        if not isinstance(token,str) or len(token)!=43 or not settings.ADMIN_SYNC_TOKEN:return None
        with self.connection() as c:row=c.execute('SELECT * FROM browser_sessions WHERE hash=?',(digest(token),)).fetchone()
        if not row or row['expires']<=self.clock() or row['created']+MAX_AGE<=self.clock() or row['stamp']!=digest(settings.ADMIN_SYNC_TOKEN):return None
        return dict(row)

    def csrf(self,token):return hmac.new(self.csrf_key,token.encode(),hashlib.sha256).hexdigest()

    def authorize(self,request,mutating=False):
        token=request.cookies.get(COOKIE,'');row=self.read(token)
        if not row:raise HTTPException(401,'Browser session expired. Sign in again.')
        if mutating:
            same_origin(request)
            if not secrets.compare_digest(request.headers.get('x-wewin-csrf',''),self.csrf(token)):
                raise HTTPException(403,'Invalid CSRF proof.')
        elif request.headers.get('sec-fetch-site')=='cross-site':raise HTTPException(403,'Cross-site access rejected.')
        return row['owner']

    def renew(self,token):
        row=self.read(token)
        if not row:raise HTTPException(401,'Browser session expired.')
        # A bounded sliding lease, not a new credential in JS or storage.
        expires=min(self.clock()+TTL,row['created']+MAX_AGE)
        with self.connection() as c:c.execute('UPDATE browser_sessions SET expires=? WHERE hash=?',(expires,digest(token)))
        return expires

    def revoke(self,token):
        with self.connection() as c:c.execute('DELETE FROM browser_sessions WHERE hash=?',(digest(token),))

    def register_device(self,owner,device,name):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            existing=c.execute('SELECT enabled FROM media_devices WHERE owner=? AND device=?',(owner,device)).fetchone()
            if existing and not existing['enabled']:
                c.execute('UPDATE media_devices SET enabled=1 WHERE owner=? AND device=?',(owner,device))
            count=c.execute('SELECT count(*) FROM media_devices WHERE owner=? AND enabled=1',(owner,)).fetchone()[0]
            if not existing and count>=5:
                stale=c.execute('SELECT device FROM media_devices WHERE owner=? AND is_default=0 ORDER BY rowid ASC LIMIT ?',(owner,count-4)).fetchall()
                for s in stale:c.execute('DELETE FROM media_devices WHERE owner=? AND device=?',(owner,s['device']))
                count=c.execute('SELECT count(*) FROM media_devices WHERE owner=? AND enabled=1',(owner,)).fetchone()[0]
            has_default=c.execute('SELECT count(*) FROM media_devices WHERE owner=? AND is_default=1 AND enabled=1',(owner,)).fetchone()[0]
            c.execute('INSERT OR REPLACE INTO media_devices (owner, device, name, enabled, is_default) VALUES (?,?,?,1,?)',(owner,device,name,0 if has_default else 1))
        return self.device(owner,device)

    def device(self,owner,device):
        with self.connection() as c:row=c.execute('SELECT * FROM media_devices WHERE owner=? AND device=? AND enabled=1',(owner,device)).fetchone()
        if not row:raise HTTPException(404,'Unknown or forgotten player.')
        return dict(row)

    def devices(self,owner):
        with self.connection() as c:return [dict(r) for r in c.execute('SELECT device,name,is_default FROM media_devices WHERE owner=? AND enabled=1',(owner,))]

    def default(self,owner):
        with self.connection() as c:row=c.execute('SELECT * FROM media_devices WHERE owner=? AND is_default=1 AND enabled=1',(owner,)).fetchone()
        return dict(row) if row else None

    def choose(self,owner,device):
        self.device(owner,device)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('UPDATE media_devices SET is_default=0 WHERE owner=?',(owner,))
            c.execute('UPDATE media_devices SET is_default=1 WHERE owner=? AND device=?',(owner,device))

    def forget(self,owner,device):
        self.device(owner,device)
        with self.connection() as c:c.execute('UPDATE media_devices SET enabled=0,is_default=0 WHERE owner=? AND device=?',(owner,device))

    def claim_intent(self,owner,rid,device,epoch,signature):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM media_intents WHERE created<?',(self.clock()-86400,))
            old=c.execute('SELECT * FROM media_intents WHERE owner=? AND rid=?',(owner,rid)).fetchone()
            if old:
                return dict(old)
            c.execute('INSERT INTO media_intents VALUES (?,?,?,?,?,?)',(owner,rid,device,epoch,signature,self.clock()))
        return None

@lru_cache(maxsize=8)
def _store(path):return BrowserStore(path)
def get_store():return _store(str(Path(os.getenv('BROWSER_SESSION_STORE') or BASE_DIR/'.secrets/browser-sessions.sqlite3').resolve()))

def set_cookie(response,request,token,max_age=TTL):
    response.set_cookie(COOKIE,token,max_age=max_age,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')

def bridge_key(create=False):
    path=Path(os.getenv('MEDIA_BRIDGE_KEY_FILE') or BASE_DIR/'.secrets/media_bridge_key').resolve()
    if 'bridge' not in path.name.lower() or path.parent.name!='.secrets' or path.is_relative_to(BASE_DIR/'frontend') or path.is_relative_to(BASE_DIR/'data'):raise ValueError('Invalid bridge key storage.')
    if create and not path.exists():
        from scripts.rotate_admin_token import restrict_directory
        if not path.parent.exists():restrict_directory(path.parent)
        fd,name=tempfile.mkstemp(prefix='bridge-',dir=path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(secrets.token_urlsafe(32));f.flush();os.fsync(f.fileno())
            os.chmod(name,0o600)
            try:os.link(name,path)
            except FileExistsError:pass
        finally:Path(name).unlink(missing_ok=True)
    value=path.read_text(encoding='utf-8').strip()
    if len(value)!=43:raise ValueError('Invalid private bridge credential.')
    return value
