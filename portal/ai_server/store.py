import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager


def digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


@contextmanager
def connect(settings):
    settings.db.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(settings.db,timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:yield db
    finally:db.close()


def migrate(settings):
    with connect(settings) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_versions(agent_id TEXT NOT NULL REFERENCES agents(id),revision INTEGER NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(agent_id,revision));
        CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,request_hash TEXT NOT NULL,revision INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,client_id TEXT NOT NULL,agent_id TEXT NOT NULL REFERENCES agents(id),token_hash TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('simulator','physical')),revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES devices(id),kind TEXT NOT NULL,started_at INTEGER NOT NULL,ended_at INTEGER);
        CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),revision INTEGER NOT NULL,config_hash TEXT NOT NULL,input_kind TEXT NOT NULL,asr_text TEXT,response TEXT,tool_names TEXT NOT NULL,elapsed_ms INTEGER NOT NULL,audio_frames INTEGER NOT NULL,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,target TEXT NOT NULL,detail TEXT NOT NULL,at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_owners(agent_id TEXT PRIMARY KEY REFERENCES agents(id),owner_id TEXT NOT NULL,tenant_id TEXT NOT NULL,created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS managed_devices(device_id TEXT PRIMARY KEY REFERENCES devices(id),owner_id TEXT NOT NULL,tenant_id TEXT NOT NULL,bootstrap_hash TEXT NOT NULL,credential_nonce TEXT NOT NULL,binding_version INTEGER NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL,last_bootstrap_at INTEGER,device_version TEXT,activation_version TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS managed_bootstrap_hash ON managed_devices(bootstrap_hash);
        CREATE TABLE IF NOT EXISTS device_declarations(device_id TEXT PRIMARY KEY REFERENCES managed_devices(device_id),payload TEXT NOT NULL,observed_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS device_transport_policy(device_id TEXT PRIMARY KEY REFERENCES managed_devices(device_id),requires_tls INTEGER NOT NULL,device_origin TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS device_protocols(device_id TEXT PRIMARY KEY REFERENCES managed_devices(device_id),transport TEXT NOT NULL CHECK(transport IN ('websocket','mqtt_udp')));
        ''')
        if settings.device_origin.startswith('https://'):
            # Upgrade only; a later missing/HTTP environment never clears a TLS pin.
            db.execute('INSERT INTO device_transport_policy SELECT device_id,1,? FROM managed_devices WHERE 1 ON CONFLICT(device_id) DO UPDATE SET requires_tls=1,device_origin=excluded.device_origin WHERE device_transport_policy.requires_tls=0',(settings.device_origin.rstrip('/'),))


def audit(db,action,target,detail=''):
    db.execute('INSERT INTO audit(action,target,detail,at) VALUES(?,?,?,?)',(action,target,str(detail)[:300],int(time.time())))
