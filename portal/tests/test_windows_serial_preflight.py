"""Synthetic Windows DCB parsing; never opens hardware or calls a driver."""
from pathlib import Path
import struct
import sys
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import windows_serial_preflight as preflight


class SerialPreflightTests(TestCase):
    def fixture(self, flags):
        raw = bytearray(52)
        struct.pack_into('<I', raw, 0, len(raw))
        struct.pack_into('<III', raw, 8, 28, 9600, flags)
        return raw

    def test_enabled_defaults_do_not_prove_live_line_levels(self):
        defaults = preflight.decode_defaults(self.fixture(0x1011))
        self.assertEqual(defaults['baud'], 9600)
        self.assertEqual(defaults['dtr_control'], 'ENABLE')
        self.assertEqual(defaults['rts_control'], 'ENABLE')
        self.assertEqual(defaults['actual_line_levels'], 'NOT_MEASURED')
        report = preflight.preflight_report('COM6', defaults)
        self.assertFalse(report['serial_handle_opened_by_script'])
        self.assertEqual(report['decision'], 'BLOCKED_PENDING_VERIFIED_NO_RESET_METHOD')

    def test_disabled_defaults_or_query_failure_never_authorize_open(self):
        disabled = preflight.decode_defaults(self.fixture(1))
        self.assertEqual(disabled['dtr_control'], 'DISABLE')
        self.assertEqual(disabled['rts_control'], 'DISABLE')
        for report in (preflight.preflight_report('COM42', disabled),
                       preflight.preflight_report('COM42', error=5)):
            self.assertEqual(report['open_close_reset_behavior'], 'UNVERIFIED')
            self.assertEqual(report['serial_bytes_written'], 0)
            self.assertTrue(report['decision'].startswith('BLOCKED'))

    def test_invalid_structures_and_non_com_targets_rejected(self):
        for raw in (b'', bytes(52)):
            with self.assertRaises(ValueError):
                preflight.decode_defaults(raw)
        for target in ('COM0', 'com6', r'\\.\COM6', 'http://robot', 'COM6/other'):
            with self.assertRaises(ValueError):
                preflight.preflight_report(target)

    def test_zero_dcb_length_is_reported_as_unvalidated_provider_data(self):
        raw = self.fixture(0x1010)
        struct.pack_into('<I', raw, 8, 0)
        defaults = preflight.decode_defaults(raw)
        self.assertFalse(defaults['dcb_length_validated'])
        self.assertEqual(defaults['dcb_length_reported'], 0)
        self.assertEqual(defaults['dtr_control'], 'ENABLE')
        self.assertTrue(preflight.preflight_report('COM6', defaults)['decision'].startswith('BLOCKED'))
