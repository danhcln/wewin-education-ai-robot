"""Additive robot configuration/role workflow migration, Portal database only."""
from contextlib import closing
import json
import sqlite3
import time
from uuid import uuid4
from . import db as storage
from .db import connection


def migrate_ai():
    with connection() as db:
        if db.execute('SELECT 1 FROM schema_version WHERE version=5').fetchone():
            return
        with closing(sqlite3.connect(storage.DB.parent/f'education-before-v5-{uuid4().hex}.sqlite3')) as out:
            db.backup(out)
        db.execute('BEGIN IMMEDIATE')
        db.execute('ALTER TABLE ai_roles ADD COLUMN version INTEGER NOT NULL DEFAULT 1')
        for sql in [
            'CREATE TABLE role_versions(role_id TEXT NOT NULL REFERENCES ai_roles(id),version INTEGER NOT NULL,payload TEXT NOT NULL,updated_at INTEGER NOT NULL,actor TEXT NOT NULL,PRIMARY KEY(role_id,version))',
            "CREATE TABLE config_candidates(id TEXT PRIMARY KEY,robot_id TEXT NOT NULL REFERENCES devices(id),base_version INTEGER NOT NULL,payload TEXT NOT NULL,role_id TEXT REFERENCES ai_roles(id),role_version INTEGER,created_by TEXT NOT NULL REFERENCES users(id),created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,consumed INTEGER NOT NULL DEFAULT 0)",
            'CREATE TABLE device_role_bindings(robot_id TEXT PRIMARY KEY REFERENCES devices(id),role_id TEXT NOT NULL REFERENCES ai_roles(id),role_version INTEGER NOT NULL,config_version INTEGER NOT NULL,updated_at INTEGER NOT NULL)',
            'CREATE TABLE config_observations(robot_id TEXT PRIMARY KEY REFERENCES devices(id),payload TEXT NOT NULL,provider_revision TEXT NOT NULL,agent_reference TEXT NOT NULL,observed_at INTEGER NOT NULL)',
            "CREATE TABLE robot_cloud_links(robot_id TEXT PRIMARY KEY REFERENCES devices(id),provider TEXT NOT NULL,agent_reference TEXT NOT NULL,origin TEXT NOT NULL,documentation_url TEXT NOT NULL,credential_env TEXT NOT NULL,version INTEGER NOT NULL,state TEXT NOT NULL CHECK(state='verification_pending'),updated_at INTEGER NOT NULL,updated_by TEXT NOT NULL REFERENCES users(id))",
            'CREATE TABLE action_limits(user_id TEXT NOT NULL REFERENCES users(id),action TEXT NOT NULL,window_start INTEGER NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(user_id,action))',
            'CREATE INDEX candidate_robot_idx ON config_candidates(robot_id,expires_at)',
        ]:
            db.execute(sql)
        for row in db.execute('SELECT * FROM ai_roles').fetchall():
            payload=json.loads(row['payload']);payload['version']=1
            db.execute('INSERT INTO role_versions VALUES(?,?,?,?,?)',(row['id'],1,json.dumps(payload,ensure_ascii=False),row['updated_at'],row['owner_id']))
        db.execute('INSERT INTO schema_version VALUES(5,?)',(int(time.time()),))
