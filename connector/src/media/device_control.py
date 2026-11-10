"""Bounded LAN presence/control, independent of capture opt-in. No listener on import.

Unknown keys are pending only. Admin must compare public fingerprint on the
trusted native MCP pairing_info tool before approval. No TOFU auto-approval.
"""
from collections import OrderedDict, deque
import json
import logging
from pathlib import Path
import os
import secrets
import socket
import threading
import time
from uuid import uuid4
from src.config import BASE_DIR
from src.media.audio_endpoint import lan_ipv4, select_lan_address
from . import control_crypto as crypto

log = logging.getLogger('WEWIN_MEDIA')


class DeviceControl:
    def __init__(self, directory=None, key_file=None, address_provider=select_lan_address):
        self.directory = Path(directory or os.environ.get('WEWIN_MEDIA_CONTROL_DIR') or BASE_DIR / '.secrets/media-control')
        self.key_file = Path(key_file or BASE_DIR / '.secrets/audio-signing/private.pem')
        self.address_provider = address_provider
        self.lock = threading.RLock()
        self.config = {'enabled': False, 'capture_name': '', 'system_mix_consent': False,
                       'local_route_confirmed': False, 'approved': {}, 'default_device': None}
        self.pending = OrderedDict()
        self.leases = {}
        self.socket = None
        self.closed = threading.Event()
        self.handler = None
        self.status_provider = lambda: {}
        self.error = None

    def load(self):
        path = self.directory / 'settings.json'
        if path.exists():
            if path.stat().st_size > 16384:
                raise ValueError('Invalid media configuration')
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value.get('approved'), dict) or len(value['approved']) > 8:
                raise ValueError('Invalid approved devices')
            self.config.update(value)
        return self.config

    def save(self):
        from scripts.rotate_admin_token import restrict_directory
        restrict_directory(self.directory)
        temporary = self.directory / ('settings-' + uuid4().hex + '.tmp')
        temporary.write_text(json.dumps(self.config), encoding='utf-8')
        temporary.replace(self.directory / 'settings.json')

    def configure(self, capture_name, system_mix_consent, local_route_confirmed, enabled):
        if enabled and (not system_mix_consent or not local_route_confirmed or not capture_name):
            raise ValueError('Capture consent and silent-route confirmation required')
        if enabled and self.socket is None:
            self.start()
        with self.lock:
            self.config.update(enabled=enabled, capture_name=capture_name,
                               system_mix_consent=system_mix_consent, local_route_confirmed=local_route_confirmed)
            self.save()
        return self.status()

    def approve(self, device_id, fingerprint):
        with self.lock:
            h = self.pending.get(device_id)
            if not h or time.monotonic() - h['seen'] > 30 or not secrets.compare_digest(h['fingerprint'], fingerprint):
                raise ValueError('Compare a fresh native MCP public fingerprint first')
            if len(self.config['approved']) >= 8 and device_id not in self.config['approved']:
                raise ValueError('Device limit')
            self.config['approved'][device_id] = fingerprint
            self.config['default_device'] = device_id
            # Revoke previous lease if an operator deliberately re-pairs after reboot.
            for lease in self.leases.values():
                if lease['device_id'] == device_id:
                    lease['revoked'] = True
            self.save()

    def revoke_device(self, device_id):
        with self.lock:
            if device_id in self.config.get('approved', {}):
                del self.config['approved'][device_id]
            if self.config.get('default_device') == device_id:
                self.config['default_device'] = None
            for lease in self.leases.values():
                if lease.get('device_id') == device_id:
                    lease['revoked'] = True
            self.save()

    def status(self):
        with self.lock:
            return {'enabled': self.config['enabled'], 'listening': self.socket is not None,
                    'capture_name': self.config['capture_name'], 'error': self.error,
                    'default_device': self.config['default_device'],
                    'pending': [{'device_id': did, 'fingerprint': p['fingerprint']}
                        for did, p in self.pending.items() if time.monotonic() - p['seen'] < 30],
                    'devices': [self._public(x) for x in self.leases.values() if not x['revoked']],
                    'capture_method': 'WASAPI_SYSTEM_RENDER_LOOPBACK', 'silent_routing_verified': False}

    @staticmethod
    def _public(x):
        return {'device_id': x['device_id'], 'ip': x.get('authenticated_ip'),
                'online': bool(x.get('authenticated_ip')) and time.monotonic() - x['seen'] < 5,
                'stream': x.get('stream', {}), 'file_active': x.get('file_active', False), 'ack': x.get('ack'),
                'command_error': x.get('command_error', 'none'),
                'volume': x.get('volume', 70), 'muted': x.get('muted', False)}

    def device(self):
        with self.lock:
            target = self.config.get('default_device')
            if target:
                matches = [x for x in self.leases.values() if not x['revoked'] and
                           x['device_id'] == target and self._public(x)['online']]
            else:
                matches = [x for x in self.leases.values() if not x['revoked'] and self._public(x)['online']]
            if len(matches) != 1:
                raise ValueError('device_unavailable')
            return self._public(matches[0])

    def send(self, operation, generation, descriptor=None, value=None):
        with self.lock:
            device = self.device()
            lease = next(x for x in self.leases.values() if not x['revoked'] and
                         x['device_id'] == device['device_id'] and self._public(x)['online'])
            job = {'type': 'command', 'op': operation, 'generation': generation, 'job_id': uuid4().hex}
            if descriptor is not None:
                job['descriptor'] = descriptor
            if value is not None:
                job['value'] = int(value)
            if operation in ('set_volume', 'volume', 'mute', 'unmute'):
                lease['commands'] = deque([c for c in lease['commands'] if c['op'] not in ('set_volume', 'volume', 'mute', 'unmute')], maxlen=4)
                lease['commands'].append(job)
            else:
                # New epoch makes all queued older starts obsolete before transmission.
                lease['commands'].clear()
                lease['commands'].append(job)
            return job['job_id']

    def set_volume(self, value: int, generation: int = 0):
        with self.lock:
            vol = max(0, min(100, int(value)))
            device = self.device()
            lease = next(x for x in self.leases.values() if not x['revoked'] and
                         x['device_id'] == device['device_id'] and self._public(x)['online'])
            lease['volume'] = vol
            lease['muted'] = (vol == 0)
            if vol > 0:
                lease['pre_mute_volume'] = vol
            return self.send('set_volume', generation, value=vol)

    def mute(self, generation: int = 0):
        with self.lock:
            device = self.device()
            lease = next(x for x in self.leases.values() if not x['revoked'] and
                         x['device_id'] == device['device_id'] and self._public(x)['online'])
            if lease.get('volume', 70) > 0:
                lease['pre_mute_volume'] = lease.get('volume', 70)
            lease['volume'] = 0
            lease['muted'] = True
            return self.send('mute', generation, value=0)

    def unmute(self, value: int | None = None, generation: int = 0):
        with self.lock:
            device = self.device()
            lease = next(x for x in self.leases.values() if not x['revoked'] and
                         x['device_id'] == device['device_id'] and self._public(x)['online'])
            vol = value if (value is not None and value > 0) else lease.get('pre_mute_volume', 70)
            vol = max(10, min(100, int(vol or 70)))
            lease['volume'] = vol
            lease['muted'] = False
            return self.send('unmute', generation, value=vol)

    def start(self):
        if self.socket is not None:
            return
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        authority = serialization.load_pem_private_key(self.key_file.read_bytes(), None)
        if not isinstance(authority, ec.EllipticCurvePrivateKey) or not isinstance(authority.curve, ec.SECP256R1):
            raise ValueError('Control signing authority unavailable')
        bind = lan_ipv4(self.address_provider())
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((bind, 8767))
            sock.settimeout(.1)
        except OSError:
            sock.close()
            raise ValueError('control_lan_port_unavailable') from None
        self.origin = f'udp://{bind}:8767/wewin-control'
        self.socket = sock
        self.closed.clear()
        self.thread = threading.Thread(target=self._run, args=(sock,), daemon=True, name='wewin-media-control')
        self.thread.start()
        log.info('WEWIN_DEVICE_CONTROL listening')

    def stop(self):
        self.closed.set()
        sock, self.socket = self.socket, None
        if sock:
            sock.close()
        with self.lock:
            self.leases.clear()

    def _hello(self, data, peer):
        h = crypto.hello(json.loads(data))
        fp, did = crypto.fingerprint(h['public_key']), h['device_id']
        with self.lock:
            if did not in self.pending:
                log.info('WEWIN_DEVICE_CONTROL discovered')
            self.pending[did] = {'fingerprint': fp, 'public_key': h['public_key'], 'seen': time.monotonic()}
            self.pending.move_to_end(did)
            while len(self.pending) > 8:
                self.pending.popitem(last=False)

            is_enrolled = False
            try:
                from src.devices.registry import get_robot_registry
                reg = get_robot_registry()
                if reg.is_revoked(did) or reg.is_revoked(fp):
                    return None
                is_enrolled = reg.is_authorized(did, fp)
            except Exception:
                pass

            is_approved = is_enrolled  # Legacy JSON approvals do not prove physical enrollment.
            if not is_approved:
                return None
            for lease in self.leases.values():
                if not lease['revoked'] and lease['hello'] == h:
                    return lease['welcome']
            # Public HELLO is not proof of device possession; it must never revoke
            # an authenticated lease. Retire the old lease only after AEAD proof.
            self.leases = {k: v for k, v in self.leases.items() if not v['revoked'] and
                           time.monotonic() - max(v['seen'], v['created']) < 10}
            if len(self.leases) >= 8:
                return
            sid = uuid4().hex
            welcome, key = crypto.issue(h, self.origin, self.key_file, int(time.time()), sid)
            self.leases[sid] = dict(device_id=did, hello=h, welcome=welcome, key=key, received=0,
                sent=0, seen=0., created=time.monotonic(), peer=None, authenticated_ip=None, commands=deque(maxlen=4), revoked=False)
            return welcome

    def receive(self, data, peer):
        lan_ipv4(peer[0])
        if data.startswith(b'{'):
            welcome = self._hello(data, peer)
            return json.dumps(welcome, separators=(',', ':')).encode() if welcome else None
        if len(data) < crypto.HEADER.size:
            return
        sid = data[4:20].hex()
        with self.lock:
            lease = self.leases.get(sid)
            if not lease or lease['revoked']:
                return
            seq, body = crypto.decrypt(lease['key'], sid, lease['received'], 0, data)
            for other_id, other in self.leases.items():
                if other_id != sid and other['device_id'] == lease['device_id']:
                    other['revoked'] = True
            first_proof = lease['authenticated_ip'] is None
            lease.update(received=seq, seen=time.monotonic(), peer=peer, authenticated_ip=peer[0])
            if first_proof:
                log.info('WEWIN_DEVICE_CONTROL authenticated')
            kind = body.get('type')
            if kind == 'presence':
                lease['ack'] = body.get('ack') if crypto.hex_value(body.get('ack'), 32) else None
                import re
                error = body.get('command_error', 'none')
                lease['command_error'] = error if isinstance(error, str) and re.fullmatch('[a-z_]{1,64}', error) else 'invalid_device_status'
                stream = body.get('stream', {})
                if not isinstance(stream, dict):
                    raise ValueError('Invalid device state')
                lease['stream'] = {k: v for k, v in stream.items() if
                    (k == 'state' and v in ('IDLE','CONNECTING','BUFFERING','PLAYING','STOPPING','ERROR')) or
                    (k in ('worker_running','owner_released') and type(v) is bool) or
                    (k in ('output_frames','generation') and type(v) is int and 0 <= v <= 2147483647) or
                    (k == 'error' and isinstance(v, str) and re.fullmatch('[a-z_]{1,64}', v))}
                lease['file_active'] = body.get('file_active') is True
                vol = body.get('volume')
                if isinstance(vol, int) and 0 <= vol <= 100:
                    lease['volume'] = vol
                    lease['muted'] = (vol == 0)
                if lease['commands'] and body.get('ack') == lease['commands'][0]['job_id']:
                    lease['commands'].popleft()
                try:
                    from src.devices.registry import get_robot_registry
                    get_robot_registry().record_observation(
                        wire_id=lease['device_id'],
                        last_ip=peer[0],
                        lease_id=sid
                    )
                    if first_proof:
                        log.info('WEWIN_DEVICE_CONTROL observation_recorded')
                except Exception:
                    log.warning('WEWIN_DEVICE_CONTROL observation_failed')
            elif kind == 'intent':
                if self.handler is None:
                    raise ValueError('orchestrator_not_ready')
                default_target = self.config.get('default_device') or lease['device_id']
                if lease['device_id'] == default_target:
                    self.handler(body, lease['device_id'])  # Nonblocking admission only.
                lease['intent_ack'] = body.get('request_id')
            default_target = self.config.get('default_device') or lease['device_id']
            public = self.status_provider() if lease['device_id'] == default_target else {'state':'IDLE','last_error':'not_default_device'}
            public = {k: v for k, v in public.items() if k in
                ('state', 'title', 'video_id', 'browser_state', 'stream_state', 'last_error', 'generation')}
            if isinstance(public.get('title'), str):
                public['title'] = public['title'][:140]
            reply = dict(lease['commands'][0]) if lease['commands'] else {'type': 'state', 'media': public}
            reply['intent_ack'] = lease.get('intent_ack', '')
            lease['sent'] += 1
            return crypto.encrypt(lease['key'], sid, lease['sent'], 1, reply)

    def _run(self, sock):
        window, count = time.monotonic(), 0
        while not self.closed.is_set():
            try:
                data, peer = sock.recvfrom(1300)
                if time.monotonic() - window > 1:
                    window, count = time.monotonic(), 0
                count += 1
                if count > 30 or len(data) > 1200:
                    continue
                response = self.receive(data, peer)
                if response:
                    sock.sendto(response, peer)
            except socket.timeout:
                continue
            except OSError:
                if not self.closed.is_set():
                    self.error = 'control_socket_error'
                break
            except Exception:
                # No raw datagram, descriptor, exception message, or token in logs.
                continue


_control = DeviceControl()
def get_control():
    return _control
