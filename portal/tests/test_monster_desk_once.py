"""Exact one-shot changes only: synthetic inventory/serial/native calls, no hardware."""
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import monster_desk_once as once
import windows_readonly_collector as c
from test_windows_readonly_collector import ClosedSerial, Clock, Reader


def inventory():
    return [{'port': 'COM6', 'vid': 0x303A, 'pid': 0x1001,
             'serial_present': True, 'serial_hash': c.PROTECTED_SERIAL_HASH}]


class OneShotTests(TestCase):
    def audit(self, native=lambda *args: 123, error=5):
        self.native_calls, self.restored = [], []
        def call(*args):
            self.native_calls.append(args)
            return native(*args)
        return once.ExclusiveOpenAudit(call, -1, lambda: error, self.restored.append)

    def args(self):
        return ('COM6', 0xC0000000, 0, None, 3, 0x40000080, None)

    def test_exclusive_native_open_one_call_no_second_attempt(self):
        audit = self.audit()
        self.assertEqual(audit(*self.args()), 123)
        self.assertEqual((audit.calls, audit.successes), (1, 1))
        with self.assertRaises(ValueError):
            audit(*self.args())
        self.assertEqual(len(self.native_calls), 1)

    def test_failed_open_preserves_windows_code_and_does_not_retry(self):
        audit = self.audit(lambda *args: -1, error=5)
        self.assertEqual(audit(*self.args()), -1)
        self.assertEqual((audit.calls, audit.successes, audit.windows_error), (1, 0, 5))
        self.assertEqual(self.restored, [5])
        with self.assertRaises(ValueError):
            audit(*self.args())
        self.assertEqual(len(self.native_calls), 1)

    def test_nonexclusive_wrong_device_or_disposition_fails_before_native(self):
        for index, value in ((0, 'COM7'), (1, 0x80000000), (2, 1), (3, 1),
                             (4, 2), (5, 0), (6, 1)):
            audit = self.audit()
            args = list(self.args()); args[index] = value
            with self.assertRaises(ValueError):
                audit(*args)
            self.assertEqual(audit.calls, 0)

    def test_identity_exact_match_duplicates_or_missing_fail(self):
        once.check_identity(inventory())
        for rows in ([], inventory()*2, [dict(inventory()[0], port='COM7')],
                     [dict(inventory()[0], serial_hash='f'*64)],
                     [dict(inventory()[0], pid=0)], [dict(inventory()[0], serial_present=False)]):
            with self.assertRaises(ValueError):
                once.check_identity(rows)

    def test_durable_claim_prevents_second_process_or_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'attempt.json'
            once.OneAttempt(path).claim()
            with self.assertRaises(FileExistsError):
                once.OneAttempt(path).claim()
            state = json.loads(path.read_text())
            self.assertTrue(state['attempt_reserved'])
            self.assertFalse(state['automatic_retry_allowed'])

    def test_bad_settings_identity_or_supervisor_stop_never_claim_or_open(self):
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('settings', 'identity', 'stop'):
                ser = c.configure_closed(ClosedSerial, 'COM6')
                ticket = once.OneAttempt(Path(folder)/(kind+'.json'))
                if kind == 'settings':
                    ser.rts = True
                reader = once.ApprovedReader(ser, ticket,
                    lambda: [] if kind == 'identity' else inventory(), self.audit(),
                    stop_requested=lambda: kind == 'stop')
                with self.assertRaises(ValueError):
                    reader.open()
                self.assertFalse(ticket.ledger.exists())
                self.assertEqual(ser.opens, 0)

    def test_failed_serial_open_consumes_claim_and_exports_numeric_error_only(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = self.audit(lambda *args: -1, error=32)
            class Denied(ClosedSerial):
                def open(inner):
                    audit(*self.args())
                    raise OSError('PRIVATE_CREDENTIAL_IN_DRIVER_MESSAGE')
            ser = c.configure_closed(Denied, 'COM6')
            ticket = once.OneAttempt(Path(folder)/'attempt.json')
            reader = once.ApprovedReader(ser, ticket, inventory, audit)
            clock = Clock()
            result = c.collect(reader, c.Limits(seconds=1), scope='AUTHORIZED_MONSTER_DESK_ONCE',
                               clock=clock, pause=clock.pause)
            self.assertEqual(reader.open_attempts, 1)
            self.assertEqual(reader.close_attempts, 1)
            self.assertEqual(audit.calls, 1)
            self.assertTrue(ticket.ledger.exists())
            self.assertEqual(result['lifecycle'][1]['winerror'], 32)
            self.assertNotIn('PRIVATE_', json.dumps(result))
            with self.assertRaises(ValueError):
                reader.open()

    def test_successful_mock_open_cleanup_once_and_no_settings_changed_after_open(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = self.audit()
            class Allowed(ClosedSerial):
                def open(inner):
                    audit(*self.args())
                    super().open()
            ser = c.configure_closed(Allowed, 'COM6')
            before = list(ser.changes)
            reader = once.ApprovedReader(ser, once.OneAttempt(Path(folder)/'attempt.json'), inventory, audit)
            clock = Clock()
            result = c.collect(reader, c.Limits(seconds=0.05), scope='AUTHORIZED_MONSTER_DESK_ONCE',
                               clock=clock, pause=clock.pause)
            self.assertEqual((ser.opens, ser.closes, audit.calls), (1, 1, 1))
            self.assertFalse(ser.is_open)
            self.assertEqual(before, ser.changes)
            self.assertFalse(result['tandev_transport_verified'])

    def test_supervisor_stop_closes_once_without_serial_command(self):
        clock = Clock(); reader = Reader(clock)
        result = c.collect(reader, c.Limits(seconds=60), scope='AUTHORIZED_MONSTER_DESK_ONCE',
                           clock=clock, pause=clock.pause, stop_requested=lambda: True)
        self.assertEqual(result['stop_reason'], 'supervisor_stop_requested')
        self.assertEqual((reader.opens, reader.reads, reader.closes, reader.writes), (1, 0, 1, 0))

    def test_missing_approval_or_supervision_denied_before_backend(self):
        with patch.object(c, 'windows_module', side_effect=AssertionError('No backend')):
            for approved, supervised in ((False, True), (True, False)):
                with self.assertRaises(ValueError):
                    once.run_once(approved=approved, normal_and_supervised=supervised)
