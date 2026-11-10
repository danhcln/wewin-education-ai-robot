"""Exact-device, durable one-attempt session explicitly approved on 2026-11-09.

Reuses the bounded/sanitized collector. No Handle, elevation, driver installation,
Serial commands, auto-reset or retry. A failed exclusive open consumes the attempt.
The lab guards remain unchanged. Never delete the attempt ledger to try again.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import windows_readonly_collector as collector

SESSION = collector.ROOT/'artifacts/monster-desk-once-20261109'


def check_identity(inventory):
    rows = [p for p in inventory if p.get('port') == 'COM6']
    if (len(rows) != 1 or (rows[0].get('vid'), rows[0].get('pid')) != (0x303A, 0x1001)
            or rows[0].get('serial_present') is not True
            or rows[0].get('serial_hash') != collector.PROTECTED_SERIAL_HASH):
        raise ValueError('Exact COM6 USB identity guard failed')


class OneAttempt:
    def __init__(self, ledger):
        self.ledger = Path(ledger)

    def claim(self):
        # Atomic across processes; retained even when open fails or process crashes.
        payload = {'scope': 'AUTHORIZED_MONSTER_DESK_ONCE', 'port': 'COM6',
                   'usb_serial_sha256': collector.PROTECTED_SERIAL_HASH,
                   'claimed_at_utc': datetime.now(timezone.utc).isoformat(),
                   'attempt_reserved': True, 'automatic_retry_allowed': False}
        fd = os.open(self.ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(payload, file, indent=2)
            file.flush()
            os.fsync(file.fileno())


class ExclusiveOpenAudit:
    """Check native arguments and count the single actual port CreateFile call."""
    def __init__(self, original, invalid_handle, get_error, set_error):
        self.original, self.invalid_handle = original, invalid_handle
        self.get_error, self.set_error = get_error, set_error
        self.calls = self.successes = 0
        self.windows_error = None

    def __call__(self, name, access, share, security, disposition, flags, template):
        if (self.calls or name not in ('COM6', r'\\.\COM6') or share != 0
                or disposition != 3 or template not in (0, None)
                or flags != 0x40000080 or access != 0xC0000000 or security is not None):
            raise ValueError('Exclusive one-shot CreateFile guard failed')
        self.calls += 1
        handle = self.original(name, access, share, security, disposition, flags, template)
        if handle == self.invalid_handle:
            code = self.get_error()  # Before logging/other Windows calls.
            self.windows_error = int(code)
            self.set_error(code)  # Preserve pySerial's own error handling.
        else:
            self.successes += 1
        return handle


class ApprovedReader:
    read_timeout_seconds = 0.1

    def __init__(self, serial_object, ticket, inventory, audit, stop_requested=lambda: False):
        self.serial, self.ticket, self.inventory, self.audit = serial_object, ticket, inventory, audit
        self.open_attempts = self.close_attempts = 0
        self.stop_requested = stop_requested

    def open(self):
        if self.open_attempts:
            raise ValueError('One approved open attempt already spent')
        if self.stop_requested():
            raise ValueError('Supervisor stop requested before open')
        check_identity(self.inventory())
        s = self.serial
        if (s.is_open or s.port != 'COM6' or s.dtr is not False or s.rts is not False
                or s.rtscts is not False or s.dsrdtr is not False or s.xonxoff is not False
                or s.timeout != 0.1):
            raise ValueError('Closed-object safety settings guard failed')
        self.ticket.claim()
        self.open_attempts += 1
        try:
            s.open()
        except Exception as exc:
            if self.audit.windows_error is not None:
                exc.winerror = self.audit.windows_error
            raise

    def read(self, size):
        return self.serial.read(size)

    def close(self):
        if self.close_attempts:
            raise ValueError('Cleanup already attempted')
        self.close_attempts += 1
        self.serial.close()


def run_once(*, approved=False, normal_and_supervised=False):
    if approved is not True or normal_and_supervised is not True:
        raise ValueError('Explicit one-shot approval and supervisor status required')
    SESSION.mkdir(parents=True, exist_ok=True)
    if (SESSION/'attempt.json').exists() or (SESSION/'result.json').exists():
        raise ValueError('Session already reserved/completed; never reopen')
    module = collector.windows_module()  # Pins reviewed backend, no open.
    check_identity(collector.windows_inventory())
    serial_object = collector.configure_closed(module.Serial, 'COM6')
    from serial import win32
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32')
    set_error = kernel.SetLastError
    set_error.argtypes, set_error.restype = (wintypes.DWORD,), None
    audit = ExclusiveOpenAudit(win32.CreateFile, win32.INVALID_HANDLE_VALUE,
                               win32.GetLastError, set_error)
    reader = ApprovedReader(serial_object, OneAttempt(SESSION/'attempt.json'),
                            collector.windows_inventory, audit,
                            stop_requested=lambda: (SESSION/'stop.request').exists())
    writes = {'attempts': 0}

    def deny_write(*args, **kwargs):
        writes['attempts'] += 1
        raise ValueError('Serial transmission forbidden')

    # Trap any accidental application transmit before it can reach the driver.
    with patch.object(win32, 'CreateFile', new=audit), patch.object(win32, 'WriteFile', new=deny_write):
        result = collector.collect(reader, collector.Limits(seconds=60, max_bytes=32768),
                                   scope='AUTHORIZED_MONSTER_DESK_ONCE',
                                   stop_requested=lambda: (SESSION/'stop.request').exists())
    result.update(port='COM6', usb_serial_sha256=collector.PROTECTED_SERIAL_HASH,
                  actual_createfile_calls=audit.calls, successful_native_opens=audit.successes,
                  native_open_windows_error=audit.windows_error,
                  serial_open_method_attempts=reader.open_attempts,
                  cleanup_method_attempts=reader.close_attempts,
                  serial_is_open_after_cleanup=serial_object.is_open,
                  blocked_transmit_attempts=writes['attempts'],
                  exclusive_share_mode=0, retry_allowed=False,
                  collector_sha256=hashlib.sha256(Path(collector.__file__).read_bytes()).hexdigest(),
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    try:
        check_identity(collector.windows_inventory())
        result['same_usb_identity_present_after_close'] = True
    except Exception as exc:
        result['same_usb_identity_present_after_close'] = False
        result['post_inventory_error'] = collector.safe_error(exc)
    result['robot_state_after'] = 'AWAITING_USER_OBSERVATION'
    # Only sanitized facts/journal; never raw serial content or raw exception text.
    with (SESSION/'result.json').open('x', encoding='utf-8') as file:
        json.dump(result, file, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-approved-once', action='store_true', required=True)
    parser.add_argument('--normal-and-supervised', action='store_true', required=True)
    args = parser.parse_args()
    result = run_once(approved=args.execute_approved_once,
                      normal_and_supervised=args.normal_and_supervised)
    print(json.dumps({k: result[k] for k in ('actual_createfile_calls', 'successful_native_opens',
                     'native_open_windows_error', 'bytes_received', 'stop_reason',
                     'serial_is_open_after_cleanup', 'elapsed_ms')}))
