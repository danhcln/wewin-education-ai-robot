"""Dedicated management and authentication store for WeWIN devices and robots.

Maintains private device identity, ownership, enrollment, and credentials
in .secrets/browser-sessions.sqlite3 (or configured store).
NEVER touches the knowledge database (data/wewin_fts.db).
"""
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4
from src.config import BASE_DIR, settings

logger = logging.getLogger("wewin.devices.store")

CURRENT_SCHEMA_VERSION = 1


def default_store_path() -> Path:
    env_path = os.environ.get("BROWSER_SESSION_STORE")
    if env_path:
        return Path(env_path).resolve()
    return (BASE_DIR / ".secrets" / "browser-sessions.sqlite3").resolve()


class DeviceStore:
    def __init__(self, path: Path | str | None = None, clock=time.time):
        self.path = Path(path).resolve() if path else default_store_path()
        self.clock = clock
        self._ensure_storage()
        self.migrate()

    def _ensure_storage(self):
        from scripts.rotate_admin_token import restrict_directory
        parent = self.path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            try:
                restrict_directory(parent)
            except Exception:
                pass
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            except FileExistsError:
                pass

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def migrate(self):
        """Applies pending migrations transactionally and idempotently."""
        with self.connection() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_versions(
                version INTEGER PRIMARY KEY,
                applied_at INTEGER NOT NULL,
                checksum TEXT NOT NULL
            );
            """)

            row = conn.execute("SELECT MAX(version) FROM schema_versions;").fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            if current_version < 1:
                self._apply_v1(conn)

    def _apply_v1(self, conn: sqlite3.Connection):
        now_ms = int(self.clock() * 1000)

        # 1. Sites
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sites(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """)

        # 2. Principals
        conn.execute("""
        CREATE TABLE IF NOT EXISTS principals(
            id TEXT PRIMARY KEY,
            legacy_owner TEXT UNIQUE,
            display_name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            auth_version INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        """)

        # 3. Site Memberships
        conn.execute("""
        CREATE TABLE IF NOT EXISTS site_memberships(
            principal_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'operator', 'viewer')),
            PRIMARY KEY(principal_id, site_id),
            FOREIGN KEY(principal_id) REFERENCES principals(id),
            FOREIGN KEY(site_id) REFERENCES sites(id)
        );
        """)

        # 4. Integrations
        conn.execute("""
        CREATE TABLE IF NOT EXISTS integrations(
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'xiaozhi',
            agent_reference TEXT,
            endpoint_origin TEXT,
            credential_ref TEXT,
            credential_version INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            authorization_state TEXT NOT NULL DEFAULT 'unconfigured'
                CHECK(authorization_state IN ('unconfigured', 'unknown', 'ready', 'auth_required', 'revoked')),
            authorization_observed_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            revoked_at INTEGER,
            FOREIGN KEY(site_id) REFERENCES sites(id)
        );
        """)

        # 5. Robots
        conn.execute("""
        CREATE TABLE IF NOT EXISTS robots(
            id TEXT PRIMARY KEY,
            site_id TEXT,
            name TEXT NOT NULL,
            wire_id TEXT NOT NULL UNIQUE,
            hardware_alias TEXT,
            integration_id TEXT,
            external_device_id TEXT,
            external_mapping_source TEXT NOT NULL DEFAULT 'unverified'
                CHECK(external_mapping_source IN ('unverified', 'operator_verified', 'provider_verified')),
            external_verified_at INTEGER,
            pairing_state TEXT NOT NULL DEFAULT 'pending'
                CHECK(pairing_state IN ('pending', 'active', 'revoked', 'recovery_required')),
            enrollment_epoch INTEGER NOT NULL DEFAULT 1,
            default_speaker INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            revoked_at INTEGER,
            FOREIGN KEY(site_id) REFERENCES sites(id),
            FOREIGN KEY(integration_id) REFERENCES integrations(id)
        );
        """)

        # 6. Robot Keys
        conn.execute("""
        CREATE TABLE IF NOT EXISTS robot_keys(
            robot_id TEXT NOT NULL,
            credential_version INTEGER NOT NULL DEFAULT 1,
            public_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL DEFAULT 'active'
                CHECK(state IN ('pending', 'active', 'revoked')),
            created_at INTEGER NOT NULL,
            activated_at INTEGER,
            revoked_at INTEGER,
            PRIMARY KEY(robot_id, credential_version),
            FOREIGN KEY(robot_id) REFERENCES robots(id)
        );
        """)

        # 7. Enrollment Challenges
        conn.execute("""
        CREATE TABLE IF NOT EXISTS enrollment_challenges(
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            candidate_wire_id TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            candidate_public_key TEXT NOT NULL,
            candidate_name TEXT,
            display_code TEXT NOT NULL,
            expected_epoch INTEGER NOT NULL DEFAULT 1,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'pending'
                CHECK(state IN ('pending', 'confirmed', 'consumed', 'expired', 'cancelled')),
            physical_confirmed_at INTEGER,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(site_id) REFERENCES sites(id),
            FOREIGN KEY(principal_id) REFERENCES principals(id)
        );
        """)

        # 8. Robot Observations
        conn.execute("""
        CREATE TABLE IF NOT EXISTS robot_observations(
            robot_id TEXT PRIMARY KEY,
            boot_id TEXT,
            lease_id TEXT,
            observed_at INTEGER NOT NULL,
            last_ip TEXT,
            firmware_version TEXT,
            build_id TEXT,
            capabilities TEXT,
            device_cloud_state TEXT,
            native_mcp_state TEXT,
            evidence_source TEXT,
            FOREIGN KEY(robot_id) REFERENCES robots(id)
        );
        """)

        # 9. Bridge Observations
        conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_observations(
            integration_id TEXT PRIMARY KEY,
            instance_id TEXT,
            process_started_at INTEGER,
            state TEXT NOT NULL,
            transport_connected INTEGER NOT NULL DEFAULT 0,
            mcp_initialized INTEGER NOT NULL DEFAULT 0,
            tools_advertised_at INTEGER,
            observed_at INTEGER NOT NULL,
            last_error_code TEXT,
            FOREIGN KEY(integration_id) REFERENCES integrations(id)
        );
        """)

        # 10. Security Events (Audit Log)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS security_events(
            id TEXT PRIMARY KEY,
            site_id TEXT,
            principal_id TEXT,
            robot_id TEXT,
            kind TEXT NOT NULL,
            credential_version INTEGER,
            epoch INTEGER,
            timestamp INTEGER NOT NULL,
            reason_code TEXT NOT NULL,
            correlation_id TEXT,
            FOREIGN KEY(site_id) REFERENCES sites(id),
            FOREIGN KEY(principal_id) REFERENCES principals(id),
            FOREIGN KEY(robot_id) REFERENCES robots(id)
        );
        """)

        # Existing table backward compatibility additions:
        # browser_sessions: principal_id
        cols = [c[1] for c in conn.execute("PRAGMA table_info(browser_sessions);").fetchall()]
        if cols and "principal_id" not in cols:
            conn.execute("ALTER TABLE browser_sessions ADD COLUMN principal_id TEXT;")
        if cols and "auth_version" not in cols:
            conn.execute("ALTER TABLE browser_sessions ADD COLUMN auth_version INTEGER DEFAULT 1;")

        # media_devices: site_id
        cols_media = [c[1] for c in conn.execute("PRAGMA table_info(media_devices);").fetchall()]
        if cols_media and "site_id" not in cols_media:
            conn.execute("ALTER TABLE media_devices ADD COLUMN site_id TEXT;")

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_robots_site_state ON robots(site_id, pairing_state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_robot_keys_state ON robot_keys(robot_id, state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_challenges_expires ON enrollment_challenges(expires_at, state);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_robot ON security_events(robot_id, timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_events_site ON security_events(site_id, timestamp);")

        # Bootstrap default site and local admin principal if missing
        conn.execute("""
        INSERT OR IGNORE INTO sites (id, name, enabled, created_at, updated_at)
        VALUES ('default-site', 'Default Site', 1, ?, ?);
        """, (now_ms, now_ms))

        conn.execute("""
        INSERT OR IGNORE INTO principals (id, legacy_owner, display_name, enabled, auth_version, created_at)
        VALUES ('principal-local-admin', 'local-admin', 'Local Administrator', 1, 1, ?);
        """, (now_ms,))

        conn.execute("""
        INSERT OR IGNORE INTO site_memberships (principal_id, site_id, role)
        VALUES ('principal-local-admin', 'default-site', 'admin');
        """)

        # Record migration ledger
        v1_checksum = hashlib.sha256(b"v1_unified_auth_schema").hexdigest()
        conn.execute("""
        INSERT INTO schema_versions (version, applied_at, checksum)
        VALUES (1, ?, ?);
        """, (now_ms, v1_checksum))

        logger.info("DeviceStore migration v1 applied successfully.")


_default_store: DeviceStore | None = None


def get_device_store(path: Path | str | None = None) -> DeviceStore:
    global _default_store
    if path is not None:
        return DeviceStore(path)
    expected = default_store_path()
    if _default_store is None or _default_store.path != expected or not _default_store.path.exists():
        _default_store = DeviceStore()
    return _default_store
