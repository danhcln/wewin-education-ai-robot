"""Query Windows serial defaults without opening a serial handle.

This is a preflight, not a monitor. It never grants permission to open a port:
stored DCB values cannot prove driver/hardware control-line behavior on open/close.
No serial library, CreateFile, control-line setter or transmit API is used.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]


def decode_defaults(raw):
    """COMMCONFIG's DCB starts at offset 8; Windows DWORDs are 32 bits."""
    if len(raw) < 36:
        raise ValueError('Truncated COMMCONFIG/DCB')
    if struct.unpack_from('<I', raw, 0)[0] < 36:
        raise ValueError('Unexpected Windows COMMCONFIG size')
    dcb_length = struct.unpack_from('<I', raw, 8)[0]
    # Some providers return zero here despite populating the fixed DCB fields.
    # Preserve this limitation; never promote defaults to live signal evidence.
    if dcb_length not in (0, 28):
        raise ValueError('Unexpected Windows DCB size')
    flags = struct.unpack_from('<I', raw, 16)[0]
    dtr_modes = {0: 'DISABLE', 1: 'ENABLE', 2: 'HANDSHAKE', 3: 'RESERVED'}
    rts_modes = {0: 'DISABLE', 1: 'ENABLE', 2: 'HANDSHAKE', 3: 'TOGGLE'}
    return {
        'dcb_length_reported': dcb_length,
        'dcb_length_validated': dcb_length == 28,
        'baud': struct.unpack_from('<I', raw, 12)[0],
        'dtr_control': dtr_modes[(flags >> 4) & 3],
        'rts_control': rts_modes[(flags >> 12) & 3],
        'software_flow_out': bool(flags & (1 << 8)),
        'software_flow_in': bool(flags & (1 << 9)),
        'actual_line_levels': 'NOT_MEASURED',
    }


def preflight_report(port, defaults=None, error=None):
    if not re.fullmatch(r'COM[1-9][0-9]*', port):
        raise ValueError('Use an explicitly enumerated Windows COM port')
    return {
        'scope': 'WINDOWS_HOST_DEFAULT_CONFIG_ONLY',
        'port': port,
        'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'api': 'GetDefaultCommConfigW',
        'success': error is None,
        'defaults': defaults,
        'windows_error': error,
        'serial_handle_opened_by_script': False,
        'serial_bytes_read': 0,
        'serial_bytes_written': 0,
        'device_identity': 'UNVERIFIED',
        'open_close_reset_behavior': 'UNVERIFIED',
        'decision': 'BLOCKED_PENDING_VERIFIED_NO_RESET_METHOD',
        'reason': 'Default configuration does not prove glitch-free open/close',
    }


def query_defaults(port):
    preflight_report(port)  # Validate before any Windows call.
    if os.name != 'nt':
        raise OSError('This preflight requires Windows')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    query = api.GetDefaultCommConfigW
    query.argtypes = (wintypes.LPCWSTR, ctypes.c_void_p,
                      ctypes.POINTER(wintypes.DWORD))
    query.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(4096)
    size = wintypes.DWORD(len(buffer))
    if not query(port, buffer, ctypes.byref(size)):
        return preflight_report(port, error=ctypes.get_last_error())
    try:
        defaults = decode_defaults(buffer.raw[:size.value])
    except ValueError as exc:
        result = preflight_report(port)
        result['decode_error'] = str(exc)
        return result
    return preflight_report(port, defaults=defaults)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    target = args.out.resolve()
    if not target.is_relative_to(ROOT / 'artifacts'):
        raise ValueError('Write evidence only inside ignored artifacts/')
    result = query_defaults(args.port)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
