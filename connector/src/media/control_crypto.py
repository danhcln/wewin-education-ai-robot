"""LAN control bootstrap: approved ephemeral device key + signed server ECDH + AEAD.

The existing audio key signs a new domain only. It is never an ECDH key.
Keys are RAM-only. A device reboot requires fresh explicit public fingerprint approval.
"""
import hashlib
import json
import re
import struct
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from src.media.audio_endpoint import lan_ipv4

HEADER = struct.Struct('!4s16sQB')
MAX_BODY = 1100


def hex_value(value, size):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is not None


def hello(value):
    if not isinstance(value, dict) or set(value) != {'type', 'device_id', 'public_key', 'nonce'} or value['type'] != 'hello':
        raise ValueError('Invalid discovery')
    if not hex_value(value['device_id'], 32) or not hex_value(value['nonce'], 32) or not hex_value(value['public_key'], 130):
        raise ValueError('Invalid identity')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(value['public_key']))
    return value


def fingerprint(public):
    return hashlib.sha256(bytes.fromhex(public)).hexdigest()


def canonical(a):
    return ('wewin-control-v1\n' + '\n'.join(str(a[k]) for k in
        ('device_id', 'public_key', 'nonce', 'server_key', 'lease_id', 'origin', 'expires_at'))).encode('ascii')


def issue(h, origin, signing_key, now, lease_id):
    hello(h)
    private = ec.generate_private_key(ec.SECP256R1())
    a = {**h, 'type': 'welcome', 'server_key': private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint).hex(),
         'lease_id': lease_id, 'origin': origin, 'expires_at': now + 60}
    payload = canonical(a)
    key = serialization.load_pem_private_key(signing_key.read_bytes(), None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('Invalid authority')
    r, s = utils.decode_dss_signature(key.sign(payload, ec.ECDSA(hashes.SHA256())))
    a['signature'] = (r.to_bytes(32, 'big') + s.to_bytes(32, 'big')).hex()
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), bytes.fromhex(h['public_key']))
    secret = private.exchange(ec.ECDH(), peer)
    derived = HKDF(hashes.SHA256(), 32, bytes.fromhex(h['nonce']), payload).derive(secret)
    return a, derived


def encrypt(key, lease, sequence, direction, body):
    payload = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode()
    if not 0 < sequence < 2**63 or direction not in (0, 1) or len(payload) > MAX_BODY:
        raise ValueError('Invalid control packet')
    header = HEADER.pack(b'WWC2', bytes.fromhex(lease), sequence, direction)
    nonce = direction.to_bytes(4, 'big') + sequence.to_bytes(8, 'big')
    return header + AESGCM(key).encrypt(nonce, payload, header)


def decrypt(key, lease, previous, direction, packet):
    if not HEADER.size + 16 <= len(packet) <= HEADER.size + MAX_BODY + 16:
        raise ValueError('Control size')
    magic, sid, sequence, d = HEADER.unpack_from(packet)
    if magic != b'WWC2' or sid.hex() != lease or d != direction or not previous < sequence < 2**63:
        raise ValueError('Stale control packet')
    nonce = d.to_bytes(4, 'big') + sequence.to_bytes(8, 'big')
    payload = AESGCM(key).decrypt(nonce, packet[HEADER.size:], packet[:HEADER.size])
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError('Control object required')
    return sequence, value
