"""Bounded, allowlisted Serial evidence collector; no real-device CLI mode.

CLI: simulate or windows-check (constructs pySerial with port=None, never open).
Physical lab use requires a separately confirmed spare board and exact inventory
match through collect_lab(). COM6 and the known Monster Desk USB identity are
denied. Nothing here proves glitch-free Windows driver open/close behavior.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from saved_robot_log_evidence import endpoint_facts, EVENTS, VERSION

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_SERIAL_HASH = '3fd6e8596a617aae6fb8cef52b338677e7295a5458a0680eb60bfbf09033cb37'
REVIEWED_WIN32_HASH = '17681ea9a650120c71db1aae9b8881301a40d38c47b34bb0da050e3f5bfbbe00'
SENSITIVE = re.compile(r'password|passwd|token|secret|authorization|\bssid\b|'
                       r'activation.?code|license|nonce|api.?key|system.?prompt', re.I)
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
BOOT = re.compile(r'ESP-ROM:|\brst:0x|DOWNLOAD[_ ]BOOT|waiting for download', re.I)


@dataclass(frozen=True)
class Limits:
    seconds: float = 60
    max_bytes: int = 32768
    max_events: int = 256
    max_line_bytes: int = 2048
    max_read_calls: int = 1000

    def validate(self):
        if type(self.seconds) not in (int, float) or not math.isfinite(self.seconds) or not 0 < self.seconds <= 60:
            raise ValueError('Capture duration must be finite and at most 60 seconds')
        for value, ceiling in ((self.max_bytes, 65536), (self.max_events, 256),
                               (self.max_line_bytes, 2048), (self.max_read_calls, 1000)):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError('Invalid collector bound')


def serial_fingerprint(value):
    value = (value or '').strip().lower()
    compact = re.sub(r'[:-]', '', value)
    if re.fullmatch(r'[0-9a-f]{12}', compact):
        value = ':'.join(compact[i:i+2] for i in range(0, 12, 2))
    return hashlib.sha256(value.encode()).hexdigest()


def authorize_lab(port, fingerprint, confirmed_spare_board, inventory):
    """Authorization attestation is supplied by a human, never inferred from PnP."""
    if not re.fullmatch(r'COM[1-9][0-9]*', port) or port == 'COM6':
        raise ValueError('Protected or invalid COM target')
    if confirmed_spare_board is not True:
        raise ValueError('No separately confirmed authorized spare board')
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint) or fingerprint == PROTECTED_SERIAL_HASH:
        raise ValueError('Protected or invalid USB identity')
    matches = [p for p in inventory if p['port'] == port]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous port inventory')
    p = matches[0]
    if (p.get('vid'), p.get('pid')) != (0x303A, 0x1001) or not p.get('serial_present'):
        raise ValueError('Expected native ESP USB Serial/JTAG identity missing')
    if p.get('serial_hash') != fingerprint:
        raise ValueError('USB identity changed')


class Allowlist:
    """No raw lines, arbitrary strings, URL paths or device identifiers escape."""
    def __init__(self):
        self.identity_aliases = {}
        self.sensitive_lines_discarded = 0

    def facts(self, raw):
        line = ANSI.sub('', raw.decode('utf-8', errors='replace'))
        if BOOT.search(line):
            if SENSITIVE.search(line):
                self.sensitive_lines_discarded += 1
            return [{'event': 'boot_or_download_marker', 'caused_by_open': 'UNVERIFIED'}]
        if SENSITIVE.search(line):
            self.sensitive_lines_discarded += 1
            return []
        facts = []
        version = VERSION.search(line)
        if version:
            facts.append({'event': 'app_version', 'version': version[1],
                          'family': 'CUSTOM_WEWIN' if 'wewin' in version[2].lower()
                          else 'UNATTRIBUTED_NOT_TANDEV_ATTESTATION'})
        for event, pattern in EVENTS:
            if event.endswith('_connected') and re.search(r'not\s+connected|failed|error|disconnected', line, re.I):
                continue
            if re.search(pattern, line, re.I):
                facts.append({'event': event})
        for endpoint in endpoint_facts(line):
            facts.append({'event': 'public_endpoint', **endpoint})
        start = line.find('{')
        if start >= 0:
            try:
                payload, _ = json.JSONDecoder().raw_decode(line[start:])
            except ValueError:
                payload = None
            if isinstance(payload, dict) and payload.get('type') == 'hello':
                safe = {'event': 'logged_hello', 'direction': 'UNKNOWN'}
                if payload.get('transport') in ('udp', 'websocket'):
                    safe['declared_transport'] = payload['transport']
                if type(payload.get('version')) is int and 1 <= payload['version'] <= 4:
                    safe['protocol_version'] = payload['version']
                params = payload.get('audio_params')
                if isinstance(params, dict):
                    for key, allowed in (('sample_rate', (16000, 24000, 48000)),
                                         ('channels', (1, 2)), ('frame_duration', (20, 40, 60))):
                        if type(params.get(key)) is int and params[key] in allowed:
                            safe[key] = params[key]
                    if params.get('format') == 'opus':
                        safe['format'] = 'opus'
                facts.append(safe)
        identity = re.search(r'\b(device[-_ ]id|client[-_ ]id)\b["\s]*[:=]\s*["\x27]?'
                             r'([A-Za-z0-9:_-]{1,128})(?=[\s,"\x27}]|$)', line, re.I)
        if identity:
            value = identity[2]
            alias = self.identity_aliases.setdefault(value, 'ID'+str(len(self.identity_aliases)+1))
            facts.append({'event': 'logged_identity', 'alias': alias,
                          'field': 'device_id' if identity[1].lower().startswith('device') else 'client_id',
                          'hardware_or_cloud_link': 'UNVERIFIED'})
        return facts


def safe_error(exc):
    # Driver exception messages may embed the port, identifiers or received data.
    name = type(exc).__name__
    code = getattr(exc, 'winerror', None)
    return {'category': name if name in ('OSError', 'PermissionError', 'SerialException',
                                         'SerialTimeoutException') else 'OTHER_ERROR',
            'winerror': code if type(code) is int and 0 <= code <= 65535 else None}


def collect(reader, limits=Limits(), *, scope='SIMULATION', clock=time.monotonic,
            pause=time.sleep, stop_requested=None):
    """Reader exposes open/read/close only. No writes, retries or interactive input.

    Read window includes open time; close always runs, even after partial open.
    Driver calls can hang; the timeout is not a proof of a 60s OS-call deadline.
    """
    limits.validate()
    if scope not in ('SIMULATION', 'AUTHORIZED_SPARE_BOARD', 'AUTHORIZED_MONSTER_DESK_ONCE'):
        raise ValueError('Invalid collector scope')
    result = {'scope': scope, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'lifecycle': [], 'facts': [], 'bytes_received': 0, 'lines_received': 0,
              'oversized_lines_discarded': 0, 'partial_line_discarded': False,
              'application_transmit_api_calls': 0, 'raw_log_exported': False,
              'reset_at_open': 'UNVERIFIED', 'reset_at_close': 'UNVERIFIED',
              'download_mode': 'UNVERIFIED', 'usb_enumeration': 'UNVERIFIED',
              'tandev_transport_verified': False, 'stop_reason': None}
    started = clock()
    deadline = started + limits.seconds
    parser = Allowlist()
    pending = bytearray()
    discarding = False
    reads = 0
    phase = 'open'

    def lifecycle(event, **data):
        result['lifecycle'].append({'event': event, 'elapsed_ms': round((clock()-started)*1000), **data})

    try:
        lifecycle('open_attempt')
        reader.open()
        lifecycle('open_returned')
        phase = 'read'
        while clock() < deadline and result['stop_reason'] is None:
            if stop_requested is not None and stop_requested():
                result['stop_reason'] = 'supervisor_stop_requested'
                break
            if result['bytes_received'] >= limits.max_bytes:
                result['stop_reason'] = 'byte_limit'
                break
            if reads >= limits.max_read_calls:
                result['stop_reason'] = 'read_call_limit'
                break
            if clock() + getattr(reader, 'read_timeout_seconds', 0) >= deadline:
                result['stop_reason'] = 'time_limit'
                break
            reads += 1
            chunk = reader.read(min(256, limits.max_bytes-result['bytes_received']))
            if not isinstance(chunk, bytes) or len(chunk) > min(256, limits.max_bytes-result['bytes_received']):
                raise ValueError('Reader violated bounded read contract')
            result['bytes_received'] += len(chunk)
            if not chunk:
                pause(min(0.01, max(0, deadline-clock())))
            for byte in chunk:
                if byte == 10:
                    result['lines_received'] += 1
                    if not discarding:
                        facts = parser.facts(bytes(pending))
                        for fact in facts:
                            if len(result['facts']) >= limits.max_events:
                                result['stop_reason'] = 'event_limit'
                                break
                            result['facts'].append({'line': result['lines_received'],
                                                    'elapsed_ms': round((clock()-started)*1000), **fact})
                            if fact['event'] == 'boot_or_download_marker':
                                result['stop_reason'] = 'boot_or_download_marker'
                                break
                            if len(result['facts']) >= limits.max_events:
                                result['stop_reason'] = 'event_limit'
                                break
                    pending.clear()
                    discarding = False
                    if result['stop_reason']:
                        break
                elif not discarding:
                    if len(pending) >= limits.max_line_bytes:
                        pending.clear()
                        discarding = True
                        result['oversized_lines_discarded'] += 1
                    else:
                        pending.append(byte)
        if result['stop_reason'] is None:
            result['stop_reason'] = 'time_limit'
    except KeyboardInterrupt:
        result['stop_reason'] = 'user_interrupt'
        lifecycle('interrupted')
    except Exception as exc:
        result['stop_reason'] = 'driver_or_reader_error'
        lifecycle('open_or_read_error', phase=phase, **safe_error(exc))
    finally:
        result['partial_line_discarded'] = bool(pending or discarding)
        pending.clear()
        parser.identity_aliases.clear()
        result['sensitive_lines_discarded'] = parser.sensitive_lines_discarded
        lifecycle('close_attempt')
        try:
            reader.close()
            lifecycle('close_returned')
        except Exception as exc:
            lifecycle('close_error', **safe_error(exc))
            result['close_failed'] = True
    result['elapsed_ms'] = round((clock()-started)*1000)
    result['read_calls'] = reads
    result['serial_output_observed'] = bool(result['bytes_received'])
    return result


def configure_closed(factory, port=None):
    ser = factory(port=None, baudrate=115200, timeout=0.1, write_timeout=0,
                  xonxoff=False, rtscts=False, dsrdtr=False)
    if ser.is_open:
        raise ValueError('Serial factory must return a closed object')
    ser.dtr = False
    ser.rts = False
    ser.port = port
    if ser.is_open:
        raise ValueError('Unexpected open during configuration')
    return ser


class PySerialReader:
    """Reviewed pySerial wrapper. Application read-only, OS handle is READ+WRITE."""
    read_timeout_seconds = 0.1

    def __init__(self, closed_serial, port, fingerprint):
        if (not re.fullmatch(r'COM[1-9][0-9]*', port) or port == 'COM6'
                or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)
                or fingerprint == PROTECTED_SERIAL_HASH):
            raise ValueError('Protected device cannot use this lab reader')
        self.__serial = closed_serial
        self.__port = port
        self.__attempted = False

    def open(self):
        if self.__attempted:
            raise ValueError('No reopen or automatic reconnect')
        self.__attempted = True
        if self.__serial.port != self.__port or self.__port == 'COM6':
            raise ValueError('Serial target changed before open')
        self.__serial.open()

    def read(self, size):
        return self.__serial.read(size)

    def close(self):
        self.__serial.close()  # No added line setters/reset/purge/flush here.


def windows_module():
    if os.name != 'nt':
        raise OSError('Windows only')
    import serial
    import serial.serialwin32
    source = Path(serial.serialwin32.__file__)
    if hashlib.sha256(source.read_bytes()).hexdigest() != REVIEWED_WIN32_HASH:
        raise ValueError('Unreviewed pySerial Windows backend')
    return serial


def windows_inventory():
    windows_module()
    from serial.tools import list_ports
    return [{'port': p.device, 'vid': p.vid, 'pid': p.pid,
             'serial_present': bool(p.serial_number),
             'serial_hash': serial_fingerprint(p.serial_number)} for p in list_ports.comports()]


def windows_closed_check():
    module = windows_module()
    ser = configure_closed(module.Serial)
    return {'mode': 'WINDOWS_CLOSED_OBJECT_CHECK', 'pyserial_version': module.VERSION,
            'reviewed_backend_sha256': REVIEWED_WIN32_HASH, 'is_open': ser.is_open,
            'port_is_none': ser.port is None, 'dtr': ser.dtr, 'rts': ser.rts,
            'rtscts': ser.rtscts, 'dsrdtr': ser.dsrdtr, 'xonxoff': ser.xonxoff,
            'timeout': ser.timeout, 'serial_open_called': False,
            'driver_control_lines_measured': False,
            'inventory': [{'port': p['port'], 'vid': p['vid'], 'pid': p['pid'],
                           'protected_identity': p['serial_hash'] == PROTECTED_SERIAL_HASH}
                          for p in windows_inventory()]}


def collect_lab(port, fingerprint, confirmed_spare_board=False, limits=Limits()):
    """Not invoked by CLI. Requires separate human approval of an exact spare board."""
    limits.validate()
    # Reject the protected target/absent authorization before importing a backend.
    if port == 'COM6' or fingerprint == PROTECTED_SERIAL_HASH or confirmed_spare_board is not True:
        raise ValueError('Protected device or no authorized spare board')
    inventory = windows_inventory()
    authorize_lab(port, fingerprint, confirmed_spare_board, inventory)
    ser = configure_closed(windows_module().Serial, port)
    # Recheck cached OS inventory immediately before the sole open attempt.
    authorize_lab(port, fingerprint, confirmed_spare_board, windows_inventory())
    result = collect(PySerialReader(ser, port, fingerprint), limits, scope='AUTHORIZED_SPARE_BOARD')
    result['target'] = {'port': port, 'usb_serial_sha256': fingerprint,
                        'vid': 0x303A, 'pid': 0x1001,
                        'reviewed_backend_sha256': REVIEWED_WIN32_HASH}
    try:
        after = windows_inventory()
        result['enumeration_after_close_same_identity'] = any(
            p['port'] == port and p['serial_hash'] == fingerprint for p in after)
    except Exception as exc:
        result['inventory_after_close_error'] = safe_error(exc)
    result['transient_enumeration_loss'] = 'UNVERIFIED_NO_CONTINUOUS_TRACE'
    return result


class FixtureReader:
    """Synthetic data only; never a serial URL or an OS resource."""
    def __init__(self, data):
        self.data = data

    def open(self):
        pass

    def read(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk

    def close(self):
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('simulate', 'windows-check'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    target = args.out.resolve()
    if not target.is_relative_to(ROOT/'artifacts') or target.exists():
        raise ValueError('Use a new output file inside ignored artifacts/')
    if args.mode == 'windows-check':
        result = windows_closed_check()
    else:
        fixture = (b'App version: 2.5.3\nMqttProtocol: Connected to api.tenclass.net:8883\n'
                   b'{"type":"hello","version":3,"transport":"udp","audio_params":{"format":"opus"}}\n'
                   b'Authorization: Bearer SYNTHETIC_SECRET\n')
        result = collect(FixtureReader(fixture), Limits(seconds=0.1))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'mode': args.mode, 'real_device_capture_started': False,
                      'output': str(target), 'tandev_transport_verified': False}))
