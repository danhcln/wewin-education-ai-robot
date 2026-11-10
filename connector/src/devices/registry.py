"""Robot and device authorization registry.

Provides authoritative ownership, enrollment, and revocation checks.
Separate from the Browser PlayerRegistry (src/media/registry.py).
"""
from contextlib import nullcontext
import json
import logging
import time
from uuid import uuid4
from src.devices.store import DeviceStore, get_device_store

logger = logging.getLogger("wewin.devices.registry")


class RobotRegistry:
    def __init__(self, store: DeviceStore | None = None):
        self.store = store or get_device_store()

    def _now_ms(self) -> int:
        return int(self.store.clock() * 1000)

    def is_authorized(self, wire_id: str, fingerprint: str) -> bool:
        """Cryptographic authorization check: returns True iff device is ACTIVE and key matches."""
        with self.store.connection() as conn:
            row = conn.execute("""
            SELECT r.id, r.pairing_state, k.state
            FROM robots r
            JOIN robot_keys k ON r.id = k.robot_id
            WHERE r.wire_id = ? AND k.fingerprint = ? AND r.pairing_state = 'active' AND k.state = 'active';
            """, (wire_id, fingerprint)).fetchone()
            return row is not None

    def is_revoked(self, wire_id_or_fingerprint: str) -> bool:
        """Returns True if device or key is revoked."""
        with self.store.connection() as conn:
            # Check by wire_id
            row = conn.execute("""
            SELECT pairing_state FROM robots WHERE wire_id = ?;
            """, (wire_id_or_fingerprint,)).fetchone()
            if row and row["pairing_state"] == "revoked":
                return True

            # Check by fingerprint
            row_key = conn.execute("""
            SELECT state FROM robot_keys WHERE fingerprint = ?;
            """, (wire_id_or_fingerprint,)).fetchone()
            if row_key and row_key["state"] == "revoked":
                return True

            return False

    def get_robot_by_wire_id(self, wire_id: str) -> dict | None:
        with self.store.connection() as conn:
            row = conn.execute("""
            SELECT r.*, k.fingerprint, k.public_key, k.credential_version, k.state as key_state
            FROM robots r
            LEFT JOIN robot_keys k ON r.id = k.robot_id AND k.state = 'active'
            WHERE r.wire_id = ?;
            """, (wire_id,)).fetchone()
            return dict(row) if row else None

    def get_robot(self, robot_id: str) -> dict | None:
        with self.store.connection() as conn:
            row = conn.execute("""
            SELECT r.*, k.fingerprint, k.public_key, k.credential_version, k.state as key_state
            FROM robots r
            LEFT JOIN robot_keys k ON r.id = k.robot_id AND k.state = 'active'
            WHERE r.id = ?;
            """, (robot_id,)).fetchone()
            return dict(row) if row else None

    def list_robots(self, site_id: str | None = None) -> list[dict]:
        with self.store.connection() as conn:
            query = """
            SELECT r.*, k.fingerprint, k.public_key, k.state as key_state,
                   o.observed_at, o.last_ip, o.firmware_version, o.device_cloud_state
            FROM robots r
            LEFT JOIN robot_keys k ON r.id = k.robot_id AND k.state = 'active'
            LEFT JOIN robot_observations o ON r.id = o.robot_id
            """
            params = []
            if site_id:
                query += " WHERE r.site_id = ?"
                params.append(site_id)
            query += " ORDER BY r.created_at ASC;"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def enroll_robot(self, site_id: str, wire_id: str, fingerprint: str, public_key: str,
                      name: str | None = None, principal_id: str | None = None, _connection=None) -> dict:
        """Enrolls or re-enrolls a robot with an active cryptographic key."""
        now_ms = self._now_ms()
        with (nullcontext(_connection) if _connection is not None else self.store.connection()) as conn:
            # Resolve principal_id
            resolved_p = None
            if principal_id:
                row_p = conn.execute("SELECT id FROM principals WHERE id = ? OR legacy_owner = ?;", (principal_id, principal_id)).fetchone()
                resolved_p = row_p[0] if row_p else principal_id
            # Check existing robot
            existing = conn.execute("SELECT * FROM robots WHERE wire_id = ?;", (wire_id,)).fetchone()
            if existing:
                robot_id = existing["id"]
                epoch = existing["enrollment_epoch"] + 1
                robot_name = name or existing["name"]
                conn.execute("""
                UPDATE robots SET
                    site_id = ?, name = ?, pairing_state = 'active',
                    enrollment_epoch = ?, updated_at = ?, revoked_at = NULL
                WHERE id = ?;
                """, (site_id, robot_name, epoch, now_ms, robot_id))
            else:
                robot_id = uuid4().hex
                epoch = 1
                robot_name = name or f"ESP32-Robot-{wire_id[-6:]}"
                # If this is the first robot in the site, make it default speaker
                count = conn.execute("SELECT COUNT(*) FROM robots WHERE site_id = ? AND default_speaker = 1;", (site_id,)).fetchone()[0]
                default_speaker = 1 if count == 0 else 0

                conn.execute("""
                INSERT INTO robots (
                    id, site_id, name, wire_id, pairing_state,
                    enrollment_epoch, default_speaker, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?);
                """, (robot_id, site_id, robot_name, wire_id, epoch, default_speaker, now_ms, now_ms))

            # Revoke previous active keys for this robot
            conn.execute("""
            UPDATE robot_keys SET state = 'revoked', revoked_at = ?
            WHERE robot_id = ? AND state = 'active';
            """, (now_ms, robot_id))

            # Check if this exact key fingerprint already exists for this robot
            existing_key = conn.execute(
                "SELECT credential_version FROM robot_keys WHERE robot_id = ? AND fingerprint = ?;",
                (robot_id, fingerprint)
            ).fetchone()

            if existing_key:
                active_ver = existing_key[0]
                conn.execute("""
                UPDATE robot_keys SET state = 'active', activated_at = ?, revoked_at = NULL
                WHERE robot_id = ? AND credential_version = ?;
                """, (now_ms, robot_id, active_ver))
            else:
                # Find next credential_version
                max_ver_row = conn.execute("SELECT MAX(credential_version) FROM robot_keys WHERE robot_id = ?;", (robot_id,)).fetchone()
                next_ver = (max_ver_row[0] or 0) + 1

                conn.execute("""
                INSERT INTO robot_keys (
                    robot_id, credential_version, public_key, fingerprint,
                    state, created_at, activated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?);
                """, (robot_id, next_ver, public_key, fingerprint, now_ms, now_ms))
                active_ver = next_ver

            # Audit event
            conn.execute("""
            INSERT INTO security_events (
                id, site_id, principal_id, robot_id, kind,
                credential_version, epoch, timestamp, reason_code
            ) VALUES (?, ?, ?, ?, 'robot_enrolled', ?, ?, ?, 'enrollment_completed');
            """, (uuid4().hex, site_id, resolved_p, robot_id, active_ver, epoch, now_ms))

        if _connection is not None:
            return dict(_connection.execute("SELECT r.*, k.fingerprint,k.public_key,k.credential_version FROM robots r JOIN robot_keys k ON r.id=k.robot_id AND k.state='active' WHERE r.id=?",(robot_id,)).fetchone())
        return self.get_robot(robot_id)

    def revoke_robot(self, robot_id: str, reason: str = "operator_revoked",
                     principal_id: str | None = None, correlation_id: str | None = None) -> bool:
        """Server-side revocation: immediately revokes device ownership and all active keys."""
        now_ms = self._now_ms()
        with self.store.connection() as conn:
            # Resolve principal_id
            resolved_p = None
            if principal_id:
                row_p = conn.execute("SELECT id FROM principals WHERE id = ? OR legacy_owner = ?;", (principal_id, principal_id)).fetchone()
                resolved_p = row_p[0] if row_p else principal_id
            robot = conn.execute("SELECT * FROM robots WHERE id = ?;", (robot_id,)).fetchone()
            if not robot:
                return False

            epoch = robot["enrollment_epoch"] + 1
            conn.execute("""
            UPDATE robots SET
                pairing_state = 'revoked', enrollment_epoch = ?,
                default_speaker = 0, updated_at = ?, revoked_at = ?
            WHERE id = ?;
            """, (epoch, now_ms, now_ms, robot_id))

            conn.execute("""
            UPDATE robot_keys SET
                state = 'revoked', revoked_at = ?
            WHERE robot_id = ? AND state = 'active';
            """, (now_ms, robot_id))

            # Audit event
            conn.execute("""
            INSERT INTO security_events (
                id, site_id, principal_id, robot_id, kind,
                epoch, timestamp, reason_code, correlation_id
            ) VALUES (?, ?, ?, ?, 'robot_revoked', ?, ?, ?, ?);
            """, (uuid4().hex, robot["site_id"], resolved_p, robot_id, epoch, now_ms, reason, correlation_id))

            return True

    def set_default_speaker(self, robot_id: str, site_id: str | None = None):
        now_ms = self._now_ms()
        with self.store.connection() as conn:
            robot = conn.execute("SELECT site_id, pairing_state FROM robots WHERE id = ?;", (robot_id,)).fetchone()
            if not robot or robot["pairing_state"] != "active":
                raise ValueError("Only active enrolled robots can be default speaker")
            target_site = site_id or robot["site_id"]
            conn.execute("UPDATE robots SET default_speaker = 0 WHERE site_id = ?;", (target_site,))
            conn.execute("UPDATE robots SET default_speaker = 1, updated_at = ? WHERE id = ?;", (now_ms, robot_id))

    def record_observation(self, wire_id: str, last_ip: str | None = None,
                           firmware_version: str | None = None, boot_id: str | None = None,
                           lease_id: str | None = None, capabilities: str | None = None,
                           device_cloud_state: str | None = None, native_mcp_state: str | None = None):
        now_ms = self._now_ms()
        with self.store.connection() as conn:
            robot = conn.execute("SELECT id FROM robots WHERE wire_id = ?;", (wire_id,)).fetchone()
            if not robot:
                return
            robot_id = robot["id"]
            conn.execute("""
            INSERT INTO robot_observations (
                robot_id, boot_id, lease_id, observed_at, last_ip,
                firmware_version, capabilities, device_cloud_state,
                native_mcp_state, evidence_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'lan_presence')
            ON CONFLICT(robot_id) DO UPDATE SET
                boot_id = coalesce(excluded.boot_id, robot_observations.boot_id),
                lease_id = coalesce(excluded.lease_id, robot_observations.lease_id),
                observed_at = excluded.observed_at,
                last_ip = coalesce(excluded.last_ip, robot_observations.last_ip),
                firmware_version = coalesce(excluded.firmware_version, robot_observations.firmware_version),
                capabilities = coalesce(excluded.capabilities, robot_observations.capabilities),
                device_cloud_state = coalesce(excluded.device_cloud_state, robot_observations.device_cloud_state),
                native_mcp_state = coalesce(excluded.native_mcp_state, robot_observations.native_mcp_state);
            """, (robot_id, boot_id, lease_id, now_ms, last_ip, firmware_version, capabilities, device_cloud_state, native_mcp_state))


_default_registry: RobotRegistry | None = None


def get_robot_registry(store: DeviceStore | None = None) -> RobotRegistry:
    global _default_registry
    if store is not None:
        return RobotRegistry(store)
    from src.devices.store import default_store_path
    expected_path = default_store_path()
    if _default_registry is None or _default_registry.store.path != expected_path:
        _default_registry = RobotRegistry()
    return _default_registry
