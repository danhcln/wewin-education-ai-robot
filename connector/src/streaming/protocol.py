"""WWS1 binary framing. Opus packets, not whole Ogg files or JSON audio."""
import struct
import uuid
import hmac

HEADER = struct.Struct('!4s16sIIQHBB')
DATA, END, STOP, HEARTBEAT, HELLO, STATE = 1, 2, 3, 4, 5, 6
MAX_OPUS = 1275
FRAME_MS = 20


def encode(session, generation, sequence, timestamp_ms, payload=b'', kind=DATA):
    if type(generation) is not int or not 1 <= generation <= 0x7fffffff or not 0 <= sequence <= 0xffffffff:
        raise ValueError('Invalid stream generation/sequence')
    if kind not in (DATA, END, STOP, HEARTBEAT, HELLO, STATE) or not isinstance(payload, bytes) or len(payload) > MAX_OPUS or bool(payload) != (kind in (DATA, STATE)):
        raise ValueError('Invalid Opus/control frame')
    if not 0 <= timestamp_ms <= 0xffffffff * FRAME_MS:
        raise ValueError('Invalid media timestamp')
    return HEADER.pack(b'WWS1', uuid.UUID(hex=session).bytes, generation, sequence,
                       timestamp_ms, len(payload), kind, 1) + payload


def decode(frame):
    if not isinstance(frame, bytes) or not HEADER.size <= len(frame) <= HEADER.size + MAX_OPUS:
        raise ValueError('Invalid frame size')
    magic, sid, gen, seq, timestamp, length, kind, version = HEADER.unpack_from(frame)
    if magic != b'WWS1' or version != 1 or gen < 1 or gen > 0x7fffffff or kind not in (DATA, END, STOP, HEARTBEAT, HELLO, STATE) or length != len(frame)-HEADER.size or bool(length) != (kind in (DATA, STATE)):
        raise ValueError('Invalid frame header')
    return dict(session_id=uuid.UUID(bytes=sid).hex, generation=gen, sequence=seq,
                timestamp_ms=timestamp, kind=kind, payload=frame[HEADER.size:])


def authenticate(frame,token):
    decode(frame)
    return frame+hmac.digest(bytes.fromhex(token),frame,'sha256')


def verify(datagram,token):
    if not isinstance(datagram,bytes) or not HEADER.size+32<=len(datagram)<=HEADER.size+MAX_OPUS+32:
        raise ValueError('Invalid authenticated datagram size')
    frame,mac=datagram[:-32],datagram[-32:]
    if not hmac.compare_digest(hmac.digest(bytes.fromhex(token),frame,'sha256'),mac):
        raise ValueError('Invalid datagram authority')
    return decode(frame)
