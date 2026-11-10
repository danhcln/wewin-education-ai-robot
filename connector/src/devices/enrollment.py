"""Device Enrollment Engine.

Manages short-lived enrollment challenges and commits durable device ownership
after a signature from the robot's locally armed, single-use physical window.
The browser display_code is a signed challenge field, not proof of an OLED match.
"""
import logging
import secrets
import time
from uuid import uuid4
from src.devices.registry import RobotRegistry, get_robot_registry
from src.devices.store import DeviceStore, get_device_store

logger = logging.getLogger("wewin.devices.enrollment")

CHALLENGE_TTL_MS = 120_000  # 120 seconds
MAX_ATTEMPTS = 5


class EnrollmentEngine:
    def __init__(self, registry: RobotRegistry | None = None, store: DeviceStore | None = None):
        self.store = store or get_device_store()
        self.registry = registry or get_robot_registry(self.store)

    def _now_ms(self) -> int:
        return int(self.store.clock() * 1000)

    def create_challenge(self, site_id: str, principal_id: str,
                         candidate_wire_id: str, candidate_fingerprint: str,
                         candidate_public_key: str, name: str | None = None) -> dict:
        """Creates a short-lived enrollment challenge and generates a display code."""
        now_ms = self._now_ms()
        expires_at = now_ms + CHALLENGE_TTL_MS
        # 6-digit display code (100000 - 999999)
        display_code = f"{secrets.randbelow(900000) + 100000}"
        challenge_id = uuid4().hex

        with self.store.connection() as conn:
            # Resolve principal_id if legacy_owner is passed
            row_p = conn.execute("SELECT id FROM principals WHERE id = ? OR legacy_owner = ?;", (principal_id, principal_id)).fetchone()
            resolved_principal = row_p[0] if row_p else principal_id
            member=conn.execute("SELECT 1 FROM site_memberships m JOIN principals p ON p.id=m.principal_id JOIN sites s ON s.id=m.site_id WHERE m.principal_id=? AND m.site_id=? AND m.role IN ('admin','operator') AND p.enabled=1 AND s.enabled=1",(resolved_principal,site_id)).fetchone()
            if not member:raise ValueError('site_access_denied')


            # Cancel any existing pending challenge for this candidate wire_id
            conn.execute("""
            UPDATE enrollment_challenges
            SET state = 'cancelled'
            WHERE candidate_wire_id = ? AND state = 'pending';
            """, (candidate_wire_id,))

            conn.execute("""
            INSERT INTO enrollment_challenges (
                id, site_id, principal_id, candidate_wire_id,
                candidate_fingerprint, candidate_public_key, candidate_name, display_code,
                expires_at, attempts, state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?);
            """, (
                challenge_id, site_id, resolved_principal, candidate_wire_id,
                candidate_fingerprint, candidate_public_key, name, display_code,
                expires_at, now_ms
            ))

        return {
            "challenge_id": challenge_id,
            "site_id": site_id,
            "candidate_wire_id": candidate_wire_id,
            "display_code": display_code,
            "expires_at": expires_at,
            "instructions": "Triple-click BOOT while robot is idle; call self.wewin_media.enrollment_proof with this challenge_id/display_code. Submit returned signature within 120s."
        }

    def get_challenge(self, challenge_id: str) -> dict | None:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM enrollment_challenges WHERE id = ?;", (challenge_id,)).fetchone()
            return dict(row) if row else None

    def confirm_challenge(self, challenge_id, principal_id, submitted_code=None, codes_match=False,
                          robot_name=None, device_signature=None):
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature
        now_ms=self._now_ms()
        failure=None
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM enrollment_challenges WHERE id=?',(challenge_id,)).fetchone()
            if row is None:raise ValueError('enrollment_challenge_not_found')
            ch=dict(row)
            principal=conn.execute('SELECT id FROM principals WHERE (id=? OR legacy_owner=?) AND enabled=1',(principal_id,principal_id)).fetchone()
            if not principal or ch['principal_id']!=principal[0]:raise ValueError('wrong_enrollment_principal')
            member=conn.execute("SELECT 1 FROM site_memberships m JOIN sites s ON s.id=m.site_id WHERE m.principal_id=? AND m.site_id=? AND m.role IN ('admin','operator') AND s.enabled=1",(principal[0],ch['site_id'])).fetchone()
            if not member:raise ValueError('site_access_denied')
            if ch['state']!='pending':raise ValueError('challenge_not_pending')
            if now_ms>=ch['expires_at']:raise ValueError('challenge_expired')
            if ch['attempts']>=MAX_ATTEMPTS:raise ValueError('max_attempts_exceeded')
            if not submitted_code or not secrets.compare_digest(submitted_code,ch['display_code']):
                failure='display_code_mismatch'
            else:
                try:
                    signature=bytes.fromhex(device_signature or '')
                    if len(signature)!=64:raise ValueError()
                    public=bytes.fromhex(ch['candidate_public_key'])
                    import hashlib
                    if hashlib.sha256(public).hexdigest()!=ch['candidate_fingerprint']:raise ValueError()
                    key=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),public)
                    text='wewin-physical-v1\n'+challenge_id+'\n'+ch['display_code']+'\n'+ch['candidate_wire_id']+'\n'+ch['candidate_fingerprint']
                    der=utils.encode_dss_signature(int.from_bytes(signature[:32],'big'),int.from_bytes(signature[32:],'big'))
                    key.verify(der,text.encode('ascii'),ec.ECDSA(hashes.SHA256()))
                except (TypeError,ValueError,InvalidSignature,UnicodeError):failure='physical_proof_invalid'
            if failure:
                conn.execute("UPDATE enrollment_challenges SET attempts=attempts+1 WHERE id=?",(challenge_id,))
            else:
                previous=conn.execute('SELECT site_id FROM robots WHERE wire_id=?',(ch['candidate_wire_id'],)).fetchone()
                if previous and previous['site_id']!=ch['site_id']:raise ValueError('site_transfer_requires_separate_authorization')
                enrolled=self.registry.enroll_robot(site_id=ch['site_id'],wire_id=ch['candidate_wire_id'],
                    fingerprint=ch['candidate_fingerprint'],public_key=ch['candidate_public_key'],
                    name=robot_name or ch.get('candidate_name'),principal_id=principal[0],_connection=conn)
                conn.execute("UPDATE enrollment_challenges SET state='consumed',physical_confirmed_at=? WHERE id=?",(now_ms,challenge_id))
        if failure:raise ValueError(failure)
        return enrolled

    def cancel_challenge(self, challenge_id: str, principal_id: str) -> bool:
        with self.store.connection() as conn:
            cur = conn.execute("""
            UPDATE enrollment_challenges SET state = 'cancelled'
            WHERE id = ? AND state = 'pending' AND principal_id IN (SELECT id FROM principals WHERE id=? OR legacy_owner=?);
            """, (challenge_id,principal_id,principal_id))
            return cur.rowcount > 0


_default_engine: EnrollmentEngine | None = None


def get_enrollment_engine(registry: RobotRegistry | None = None, store: DeviceStore | None = None) -> EnrollmentEngine:
    global _default_engine
    if registry is not None or store is not None:
        return EnrollmentEngine(registry, store)
    from src.devices.store import default_store_path
    expected = default_store_path()
    if _default_engine is None or _default_engine.store.path != expected or not _default_engine.store.path.exists():
        _default_engine = EnrollmentEngine()
    return _default_engine
