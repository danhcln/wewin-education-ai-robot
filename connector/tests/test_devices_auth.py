"""Unit and integration tests for Phase 2.1 Device Management Store, Registry, and Enrollment."""
import contextlib
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient

from src.devices.store import DeviceStore
from src.devices.registry import RobotRegistry
from src.devices.enrollment import EnrollmentEngine


from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization
import hashlib

def physical_signature(key, cid, code, wire, fp):
    text='wewin-physical-v1\n'+cid+'\n'+code+'\n'+wire+'\n'+fp
    r,s=utils.decode_dss_signature(key.sign(text.encode(),ec.ECDSA(hashes.SHA256())))
    return (r.to_bytes(32,'big')+s.to_bytes(32,'big')).hex()

class DeviceAuthTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.temp_dir = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.db_path = self.temp_dir / "browser.sqlite3"
        self.store = DeviceStore(self.db_path)
        self.registry = RobotRegistry(self.store)
        self.engine = EnrollmentEngine(self.registry, self.store)

        # Candidate test device
        self.wire_id = "0123456789abcdef0123456789abcdef"
        self.key=ec.generate_private_key(ec.SECP256R1())
        raw=self.key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        self.fingerprint=hashlib.sha256(raw).hexdigest()
        self.public_key=raw.hex()
        self.site_id = "default-site"
        self.principal_id = "principal-local-admin"

    def test_01_store_migration_and_idempotence(self):
        # Verify tables exist
        with self.store.connection() as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            for expected in ["schema_versions", "sites", "principals", "site_memberships",
                             "robots", "robot_keys", "enrollment_challenges", "integrations",
                             "robot_observations", "bridge_observations", "security_events"]:
                self.assertIn(expected, tables)

            # Check bootstrap records
            site = conn.execute("SELECT * FROM sites WHERE id = 'default-site';").fetchone()
            self.assertIsNotNone(site)
            self.assertEqual(site["name"], "Default Site")

            principal = conn.execute("SELECT * FROM principals WHERE id = 'principal-local-admin';").fetchone()
            self.assertIsNotNone(principal)
            self.assertEqual(principal["legacy_owner"], "local-admin")

        # Second migration call must be completely idempotent
        self.store.migrate()
        with self.store.connection() as conn:
            ver = conn.execute("SELECT MAX(version) FROM schema_versions;").fetchone()[0]
            self.assertEqual(ver, 1)

    def test_02_enrollment_challenge_lifecycle(self):
        # Create challenge
        ch = self.engine.create_challenge(
            site_id=self.site_id,
            principal_id=self.principal_id,
            candidate_wire_id=self.wire_id,
            candidate_fingerprint=self.fingerprint,
            candidate_public_key=self.public_key
        )
        self.assertIn("challenge_id", ch)
        self.assertEqual(len(ch["display_code"]), 6)
        self.assertTrue(ch["display_code"].isdigit())

        # Unenrolled check before confirm
        self.assertFalse(self.registry.is_authorized(self.wire_id, self.fingerprint))

        # Confirm challenge with correct code
        enrolled = self.engine.confirm_challenge(
            challenge_id=ch["challenge_id"],
            principal_id=self.principal_id,
            submitted_code=ch["display_code"],
            device_signature=physical_signature(self.key,ch["challenge_id"],ch["display_code"],self.wire_id,self.fingerprint)
        )
        self.assertEqual(enrolled["wire_id"], self.wire_id)
        self.assertEqual(enrolled["pairing_state"], "active")

        # Now device MUST be authorized
        self.assertTrue(self.registry.is_authorized(self.wire_id, self.fingerprint))
        # Wrong fingerprint must NOT be authorized
        self.assertFalse(self.registry.is_authorized(self.wire_id, "c" * 64))

    def test_03_challenge_wrong_code_and_exhaustion(self):
        ch = self.engine.create_challenge(
            site_id=self.site_id,
            principal_id=self.principal_id,
            candidate_wire_id=self.wire_id,
            candidate_fingerprint=self.fingerprint,
            candidate_public_key=self.public_key
        )
        # Attempt with wrong code
        with self.assertRaises(ValueError):
            self.engine.confirm_challenge(ch["challenge_id"], self.principal_id, submitted_code="000000")

        # Exhaust 5 attempts
        for _ in range(4):
            with self.assertRaises(ValueError):
                self.engine.confirm_challenge(ch["challenge_id"], self.principal_id, submitted_code="000000")

        # 6th attempt should fail because challenge was cancelled due to exceeding max attempts
        with self.assertRaises(ValueError) as ctx:
            self.engine.confirm_challenge(ch["challenge_id"], self.principal_id, submitted_code=ch["display_code"])
        self.assertTrue("challenge_not_pending:cancelled" in str(ctx.exception) or "max_attempts_exceeded" in str(ctx.exception))

    def test_04_server_side_revocation(self):
        # Enroll
        enrolled = self.registry.enroll_robot(
            site_id=self.site_id,
            wire_id=self.wire_id,
            fingerprint=self.fingerprint,
            public_key=self.public_key
        )
        self.assertTrue(self.registry.is_authorized(self.wire_id, self.fingerprint))
        self.assertFalse(self.registry.is_revoked(self.wire_id))

        # Revoke
        revoked = self.registry.revoke_robot(enrolled["id"], reason="test_revocation")
        self.assertTrue(revoked)

        # After revocation:
        self.assertFalse(self.registry.is_authorized(self.wire_id, self.fingerprint))
        self.assertTrue(self.registry.is_revoked(self.wire_id))
        self.assertTrue(self.registry.is_revoked(self.fingerprint))

        # Check security audit event
        with self.store.connection() as conn:
            events = conn.execute("SELECT * FROM security_events WHERE robot_id = ?;", (enrolled["id"],)).fetchall()
            kinds = [e["kind"] for e in events]
            self.assertIn("robot_enrolled", kinds)
            self.assertIn("robot_revoked", kinds)

    def test_05_reboot_identity_persistence_simulation(self):
        """Simulates board reboot where persistent key is reused: authorization MUST succeed without re-enrolling."""
        # Enroll device with persistent key
        self.registry.enroll_robot(
            site_id=self.site_id,
            wire_id=self.wire_id,
            fingerprint=self.fingerprint,
            public_key=self.public_key
        )
        self.assertTrue(self.registry.is_authorized(self.wire_id, self.fingerprint))

        # "Reboot" -> create brand new store and registry instances pointing to the SAME db
        rebooted_store = DeviceStore(self.db_path)
        rebooted_registry = RobotRegistry(rebooted_store)

        # Persistent identity with SAME wire_id and fingerprint MUST remain authorized
        self.assertTrue(rebooted_registry.is_authorized(self.wire_id, self.fingerprint))
        robot = rebooted_registry.get_robot_by_wire_id(self.wire_id)
        self.assertIsNotNone(robot)
        self.assertEqual(robot["pairing_state"], "active")


class DeviceRoutesIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.temp_dir = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.admin = secrets.token_urlsafe(32)

        env_patch = {
            "BROWSER_SESSION_STORE": str(self.temp_dir / ".secrets" / "browser.sqlite3"),
            "ADMIN_SYNC_TOKEN": self.admin,
            "ADMIN_SYNC_TOKEN_FILE": "",
            "DATABASE_PATH": str(self.temp_dir / "knowledge.db"),
            "WEWIN_MEDIA_CONTROL_DIR": str(self.temp_dir / "control"),
            "AUTO_SYNC_ENABLED": "false",
            "SYNC_SCHEDULE_ARMED": "false"
        }
        self.stack.enter_context(patch.dict(os.environ, env_patch))
        from src.config import settings
        settings.reload()

        from src.api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app, base_url="http://127.0.0.1")
        self.addCleanup(self.client.close)

        # Login to obtain CSRF and cookie
        resp = self.client.post("/api/browser/login", headers={"Origin": "http://127.0.0.1", "Authorization": f"Bearer {self.admin}"}, json={})
        self.assertEqual(resp.status_code, 200)
        self.csrf = resp.json()["csrf"]
        self.headers = {"Origin": "http://127.0.0.1", "X-WeWIN-CSRF": self.csrf}

    def test_device_routes_flow(self):
        # 1. Initially no robots
        r = self.client.get("/api/devices", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["robots"], [])

        # 2. Simulate device HELLO in control
        from src.media.device_control import get_control
        control = get_control()
        wire_id = "11223344556677889900aabbccddeeff"
        key=ec.generate_private_key(ec.SECP256R1())
        raw=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
        fp=hashlib.sha256(raw).hexdigest();pub=raw.hex()
        with control.lock:
            control.pending[wire_id] = {"fingerprint": fp, "public_key": pub, "seen": time.monotonic()}

        # 3. Discovery shows candidate
        disc = self.client.get("/api/devices/discovery", headers=self.headers)
        self.assertEqual(disc.status_code, 200)
        self.assertEqual(len(disc.json()["candidates"]), 1)
        self.assertEqual(disc.json()["candidates"][0]["wire_id"], wire_id)

        # 4. Initiate enrollment
        enr_resp = self.client.post("/api/devices/enrollments", headers=self.headers, json={
            "candidate_wire_id": wire_id,
            "site_id": "default-site",
            "name": "Classroom 1 Robot"
        })
        self.assertEqual(enr_resp.status_code, 200)
        ch_id = enr_resp.json()["challenge"]["challenge_id"]
        code = enr_resp.json()["challenge"]["display_code"]

        # 5. Confirm enrollment with displayed code
        conf_resp = self.client.post(f"/api/devices/enrollments/{ch_id}/confirm", headers=self.headers, json={
            "code": code,
            "codes_match": True,
            "device_signature":physical_signature(key,ch_id,code,wire_id,fp)
        })
        self.assertEqual(conf_resp.status_code, 200)
        robot_id = conf_resp.json()["robot"]["id"]

        # 6. Device is now in active list
        dev_list = self.client.get("/api/devices", headers=self.headers).json()["robots"]
        self.assertEqual(len(dev_list), 1)
        self.assertEqual(dev_list[0]["pairing_state"], "active")
        self.assertEqual(dev_list[0]["name"], "Classroom 1 Robot")

        # 7. Unpair (server-side revocation)
        unpair_resp = self.client.post(f"/api/devices/{robot_id}/unpair", headers=self.headers, json={
            "reason": "lost_device"
        })
        self.assertEqual(unpair_resp.status_code, 200)

        # 8. Verification: robot is marked revoked
        dev_list_after = self.client.get("/api/devices", headers=self.headers).json()["robots"]
        self.assertEqual(dev_list_after[0]["pairing_state"], "revoked")


if __name__ == "__main__":
    unittest.main()
