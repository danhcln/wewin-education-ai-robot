"""Read-only Connector adapters. No device commands, Cloud writes or source migrations."""
from pathlib import Path
from urllib.parse import urlsplit
import os
import sys
import time
import sqlite3
import re
from .db import ROOT, connection

def _resolve_connector_dir() -> Path:
    candidates = [
        Path(os.environ.get('WEWIN_CONNECTOR_DIR', '')),
        ROOT.parent / 'connector',
        ROOT.parent / 'Wewin Connector/Wewin_AI_Connector',
    ]
    for c in candidates:
        if c and (c / 'src').is_dir():
            return c.resolve()
    return (ROOT.parent / 'connector').resolve()

CONNECTOR = _resolve_connector_dir()
if str(CONNECTOR) not in sys.path:
    sys.path.insert(0, str(CONNECTOR))
from src.config import settings
from src.mcp.bridge_status import read_status
from src.mcp.tools import TOOL_DEFINITIONS

FIXTURE_DB = (ROOT / 'tests/fixtures/fixture_browser_sessions.sqlite3').resolve()

def _resolve_source_db() -> Path:
    env_store = os.environ.get('BROWSER_SESSION_STORE')
    if env_store and Path(env_store).is_file():
        return Path(env_store).resolve()
    secret_store = (CONNECTOR / '.secrets/browser-sessions.sqlite3').resolve()
    if secret_store.is_file():
        return secret_store
    if FIXTURE_DB.is_file():
        return FIXTURE_DB
    return secret_store

SOURCE_DB = _resolve_source_db()


def legacy_robots():
    try:
        store = _resolve_source_db()
        with connection(store, readonly=True) as db:
            rows = db.execute("""SELECT r.id,r.wire_id,r.name,r.site_id,r.external_device_id,
                o.observed_at,o.firmware_version,o.device_cloud_state,o.native_mcp_state,o.last_ip,o.evidence_source
                FROM robots r LEFT JOIN robot_observations o ON o.robot_id=r.id
                WHERE r.pairing_state='active' ORDER BY r.created_at""").fetchall()
        if not rows and store != FIXTURE_DB and FIXTURE_DB.is_file():
            with connection(FIXTURE_DB, readonly=True) as db:
                rows = db.execute("""SELECT r.id,r.wire_id,r.name,r.site_id,r.external_device_id,
                    o.observed_at,o.firmware_version,o.device_cloud_state,o.native_mcp_state,o.last_ip,o.evidence_source
                    FROM robots r LEFT JOIN robot_observations o ON o.robot_id=r.id
                    WHERE r.pairing_state='active' ORDER BY r.created_at""").fetchall()
        now = time.time()
        return [dict(id=r['id'], device_id=r['wire_id'], uuid=None, name=r['name'],
                     site_id=r['site_id'], firmware=r['firmware_version'],
                     cloud_state=r['device_cloud_state'] if r['observed_at'] and 0 <= now-r['observed_at']/1000 < 45 else None,
                     cloud_last_observed=r['device_cloud_state'], native_mcp_state=r['native_mcp_state'] if r['observed_at'] and 0 <= now-r['observed_at']/1000 < 45 else None,
                     wifi_ip=r['last_ip'], last_seen=r['observed_at'],
                     evidence_source=r['evidence_source'], online=bool(r['observed_at'] and 0 <= now-r['observed_at']/1000 < 45),
                     bluetooth_state=None, audio_streaming_state=None, battery=None) for r in rows]
    except (sqlite3.Error, OSError):
        return []


def source_robots():
    from .managed_robots import inventory
    return legacy_robots()+inventory()


class RobotConfigurationAdapter:
    """A management API and verified per-device acknowledgment are required before apply."""
    @staticmethod
    def capabilities():
        host = urlsplit(settings.XIAOZHI_MCP_ENDPOINT).hostname
        return {'provider': 'Chưa xác minh nhà cung cấp quản lý AI', 'mcp_endpoint_host': host,
                'cloud_config_sync': 'unsupported', 'bluetooth_control': 'unsupported',
                'wake_word_deployment': 'unsupported', 'reason': 'Chưa có API quản lý được cấp quyền và xác nhận từ thiết bị'}


def public_knowledge(query):
    """Reuse the existing public-knowledge policy, never expose internal/review rows."""
    try:
        from src.storage.db import DatabaseManager
        manager = DatabaseManager.open_existing(settings.DATABASE_PATH, read_only=True)
        with manager.get_connection() as db:
            terms=re.findall(r'\w+',query)[:20]
            if terms:
                match=' AND '.join('"'+term+'"' for term in terms)
                rows=db.execute('SELECT p.id,p.title,p.url,substr(p.content,1,1600) content FROM public_pages p JOIN pages_fts f ON f.rowid=p.id WHERE pages_fts MATCH ? LIMIT 20',(match,)).fetchall()
            else:
                rows=db.execute('SELECT id,title,url,substr(content,1,1600) content FROM public_pages LIMIT 20').fetchall()
        return [dict(r, source='connector_public', status='indexed') for r in rows]
    except (sqlite3.Error, OSError):
        return []


def approved_media():
    from src.media.asset_service import get_assets
    return [dict(r,source='connector_approved_audio',status='approved') for r in get_assets().inventory() if r['rights_status']=='approved']
