"""No physical serial ports: bounded read-only collector and authorization tests."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import windows_readonly_collector as c


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds


class Reader:
    def __init__(self, clock, data=b'', open_error=None, read_error=None, close_error=None):
        self.clock, self.data = clock, data
        self.open_error, self.read_error, self.close_error = open_error, read_error, close_error
        self.opens = self.closes = self.reads = self.writes = 0

    def open(self):
        self.opens += 1
        if self.open_error:
            raise self.open_error

    def read(self, size):
        self.reads += 1
        self.clock.pause(0.01)
        if self.read_error:
            raise self.read_error
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk

    def close(self):
        self.closes += 1
        if self.close_error:
            raise self.close_error

    def write(self, data):
        self.writes += 1
        raise AssertionError('Transmit must never occur')


class ClosedSerial:
    def __init__(self, **kwargs):
        assert kwargs['port'] is None
        self.is_open = False
        self.changes = []
        self.opens = self.closes = 0
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __setattr__(self, key, value):
        if key in ('port', 'dtr', 'rts', 'timeout', 'rtscts', 'dsrdtr', 'xonxoff'):
            assert not getattr(self, 'is_open', False), 'No settings after open'
            if hasattr(self, 'changes'):
                self.changes.append((key, value))
        object.__setattr__(self, key, value)

    def open(self):
        assert self.dtr is self.rts is self.rtscts is self.dsrdtr is self.xonxoff is False
        self.opens += 1
        self.is_open = True

    def read(self, size):
        return b''

    def close(self):
        self.closes += 1
        self.is_open = False


class CollectorTests(TestCase):
    def run_reader(self, data=b'', limits=None, **errors):
        clock = Clock()
        reader = Reader(clock, data, **errors)
        result = c.collect(reader, limits or c.Limits(seconds=0.1), clock=clock, pause=clock.pause)
        self.assertEqual(reader.writes, 0)
        self.assertEqual(reader.opens, 1)
        self.assertEqual(reader.closes, 1)
        return result, reader

    def test_no_data_has_time_limit_but_does_not_prove_firmware_silent(self):
        result, _ = self.run_reader()
        self.assertEqual(result['stop_reason'], 'time_limit')
        self.assertFalse(result['serial_output_observed'])
        self.assertEqual(result['reset_at_open'], 'UNVERIFIED')
        self.assertEqual(result['reset_at_close'], 'UNVERIFIED')
        self.assertEqual(result['usb_enumeration'], 'UNVERIFIED')

    def test_byte_limit_and_truncated_line_never_expose_raw_bytes(self):
        result, _ = self.run_reader(b'PRIVATE_NO_NEWLINE'*40, c.Limits(seconds=1, max_bytes=15))
        self.assertEqual(result['bytes_received'], 15)
        self.assertEqual(result['stop_reason'], 'byte_limit')
        self.assertTrue(result['partial_line_discarded'])
        self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_event_limit_stops_without_unbounded_output(self):
        result, _ = self.run_reader(b'MqttProtocol: Connected to api.tenclass.net:8883\n'*100,
                                    c.Limits(seconds=1, max_events=3))
        self.assertEqual(len(result['facts']), 3)
        self.assertEqual(result['stop_reason'], 'event_limit')

    def test_oversized_line_discarded_until_newline_not_parsed_as_tail(self):
        data = b'x'*50+b'MqttProtocol: Connected to api.tenclass.net:8883\nApp version: 2.5.3\n'
        result, _ = self.run_reader(data, c.Limits(seconds=1, max_line_bytes=30))
        self.assertEqual(result['oversized_lines_discarded'], 1)
        self.assertEqual([f['event'] for f in result['facts']], ['app_version'])

    def test_read_error_sanitized_no_retry_close_always(self):
        error = OSError('PRIVATE_TOKEN http://user:password@cloud.invalid/')
        error.winerror = 5
        result, reader = self.run_reader(read_error=error)
        self.assertEqual(reader.reads, 1)
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(result))
        fault = next(e for e in result['lifecycle'] if e['event']=='open_or_read_error')
        self.assertEqual((fault['phase'], fault['winerror']), ('read', 5))

    def test_open_error_is_not_mistaken_for_open_success_or_retried(self):
        result, reader = self.run_reader(open_error=PermissionError('PRIVATE_SESSION'))
        self.assertEqual(reader.reads, 0)
        self.assertNotIn('open_returned', [e['event'] for e in result['lifecycle']])
        self.assertEqual(result['lifecycle'][1]['phase'], 'open')
        self.assertNotIn('PRIVATE_SESSION', json.dumps(result))

    def test_close_error_recorded_without_exception_message(self):
        result, _ = self.run_reader(close_error=OSError('PRIVATE_KEY'))
        self.assertTrue(result['close_failed'])
        self.assertEqual(result['lifecycle'][-1]['event'], 'close_error')
        self.assertNotIn('PRIVATE_KEY', json.dumps(result))

    def test_interrupt_does_not_send_control_c_to_device(self):
        result, _ = self.run_reader(read_error=KeyboardInterrupt())
        self.assertEqual(result['stop_reason'], 'user_interrupt')

    def test_boot_download_marker_stops_without_claiming_causality(self):
        result, _ = self.run_reader(b'ESP-ROM:esp32s3\nMqttProtocol: Connected to cloud\n')
        self.assertEqual(result['stop_reason'], 'boot_or_download_marker')
        self.assertEqual(len(result['facts']), 1)
        self.assertEqual(result['facts'][0]['caused_by_open'], 'UNVERIFIED')
        self.assertEqual(result['download_mode'], 'UNVERIFIED')

    def test_reset_marker_on_sensitive_line_still_stops_without_leaking(self):
        result, _ = self.run_reader(b'ESP-ROM:esp32s3 token=PRIVATE_TOKEN\n')
        self.assertEqual(result['stop_reason'], 'boot_or_download_marker')
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(result))

    def test_output_allows_facts_but_not_credentials_identity_or_content(self):
        data = (b'App version: 2.5.3-private-version\n'
                b'MqttProtocol: Connected to mqtts://privateuser:PRIVATE_PASS@api.tenclass.net:8883/PRIVATE_PATH?q=PRIVATE_QUERY\n'
                b'Device-ID: PRIVATE_DEVICE\nClient-ID: PRIVATE_DEVICE\n'
                b'{"type":"hello","version":3,"transport":"udp","udp":{"key":"PRIVATE_UDP_KEY"},'
                b'"audio_params":{"format":"opus","sample_rate":24000,"channels":1,"frame_duration":60}}\n'
                b'Authorization: Bearer PRIVATE_BEARER\nSSID: PRIVATE_WIFI\n'
                b'{"type":"tts","text":"PRIVATE_CHILD_SPEECH"}\n')
        result, _ = self.run_reader(data, c.Limits(seconds=1))
        output = json.dumps(result)
        self.assertNotIn('PRIVATE_', output)
        self.assertNotIn('privateuser', output)
        self.assertNotIn('private-version', output)
        self.assertIn('api.tenclass.net', output)
        hello = next(f for f in result['facts'] if f['event']=='logged_hello')
        self.assertEqual((hello['protocol_version'], hello['declared_transport']), (3, 'udp'))
        ids = [f for f in result['facts'] if f['event']=='logged_identity']
        self.assertEqual([f['alias'] for f in ids], ['ID1', 'ID1'])
        self.assertFalse(result['tandev_transport_verified'])

    def test_partial_utf8_binary_and_unknown_hosts_not_exported(self):
        result, _ = self.run_reader(b'\xff\x00PRIVATE\nhttps://PRIVATE_HOST.invalid/private\n')
        self.assertEqual(result['facts'], [])

    def test_negative_connection_message_not_connected_proof(self):
        result, _ = self.run_reader(b'MqttProtocol: not connected successfully\n')
        self.assertNotIn('mqtt_connected', [f['event'] for f in result['facts']])

    def test_invalid_limits_rejected_before_open(self):
        for limits in (c.Limits(seconds=61), c.Limits(seconds=float('nan')),
                       c.Limits(seconds=float('inf')), c.Limits(seconds=True),
                       c.Limits(max_bytes=65537), c.Limits(max_events=257),
                       c.Limits(max_line_bytes=0)):
            clock = Clock()
            reader = Reader(clock)
            with self.assertRaises(ValueError):
                c.collect(reader, limits, clock=clock, pause=clock.pause)
            self.assertEqual(reader.opens, 0)

    def test_immediate_empty_reads_have_secondary_call_bound(self):
        result, _ = self.run_reader(limits=c.Limits(seconds=60, max_read_calls=2))
        self.assertEqual(result['read_calls'], 2)
        self.assertEqual(result['stop_reason'], 'read_call_limit')

    def test_fragmented_line_reassembles_without_raw_logging(self):
        clock = Clock()
        class Fragmented(Reader):
            def read(self, size):
                return super().read(min(size, 3))
        result = c.collect(Fragmented(clock, b'App version: 2.5.3\n'), c.Limits(seconds=1),
                           clock=clock, pause=clock.pause)
        self.assertEqual(result['facts'][0]['version'], '2.5.3')

    def test_open_delay_consumes_read_window_without_forced_driver_reset(self):
        clock = Clock()
        class DelayedOpen(Reader):
            def open(self):
                super().open()
                self.clock.pause(61)
        reader = DelayedOpen(clock, b'App version: 2.5.3\n')
        result = c.collect(reader, c.Limits(seconds=60), clock=clock, pause=clock.pause)
        self.assertEqual(reader.reads, 0)
        self.assertEqual(reader.closes, 1)
        self.assertGreater(result['elapsed_ms'], 60000)  # OS calls are not a hard deadline.

    def test_last_read_not_started_without_timeout_budget(self):
        clock = Clock()
        reader = Reader(clock)
        reader.read_timeout_seconds = 0.1
        result = c.collect(reader, c.Limits(seconds=0.05), clock=clock, pause=clock.pause)
        self.assertEqual(reader.reads, 0)
        self.assertEqual(result['stop_reason'], 'time_limit')

    def test_reader_contract_failure_is_sanitized_and_stops(self):
        clock = Clock()
        class BadReader(Reader):
            def read(self, size):
                return b'PRIVATE_DATA'*100
        result = c.collect(BadReader(clock), c.Limits(seconds=1), clock=clock, pause=clock.pause)
        self.assertEqual(result['stop_reason'], 'driver_or_reader_error')
        self.assertNotIn('PRIVATE_DATA', json.dumps(result))


class LabGuardTests(TestCase):
    fingerprint = c.serial_fingerprint('12:34:56:78:90:ab')

    def inventory(self, **overrides):
        row = {'port':'COM42', 'vid':0x303A, 'pid':0x1001,
               'serial_present':True, 'serial_hash':self.fingerprint}
        row.update(overrides)
        return [row]

    def test_com6_and_protected_identity_denied_before_backend(self):
        with patch.object(c, 'windows_inventory', side_effect=AssertionError('Must not inspect backend')):
            for port, fp, confirmed in (('COM6', self.fingerprint, True),
                                         ('COM42', c.PROTECTED_SERIAL_HASH, True),
                                         ('COM42', self.fingerprint, False)):
                with self.assertRaises(ValueError):
                    c.collect_lab(port, fp, confirmed)

    def test_wrong_target_missing_duplicate_and_mismatched_inventory_fail(self):
        for inventory in ([], self.inventory()*2, self.inventory(pid=0),
                          self.inventory(serial_present=False), self.inventory(serial_hash='f'*64)):
            with self.assertRaises(ValueError):
                c.authorize_lab('COM42', self.fingerprint, True, inventory)
        c.authorize_lab('COM42', self.fingerprint, True, self.inventory())

    def test_serial_format_normalization_prevents_identity_bypass(self):
        self.assertEqual(c.serial_fingerprint('12:34:56:78:90:AB'),
                         c.serial_fingerprint('1234567890ab'))
        self.assertEqual(c.serial_fingerprint('12-34-56-78-90-AB'), self.fingerprint)

    def test_closed_configuration_and_wrapper_never_change_lines_after_open(self):
        ser = c.configure_closed(ClosedSerial, 'COM42')
        self.assertEqual(ser.opens, 0)
        changes = list(ser.changes)
        reader = c.PySerialReader(ser, 'COM42', self.fingerprint)
        self.assertFalse(hasattr(reader, 'write'))
        reader.open()
        reader.read(10)
        reader.close()
        self.assertEqual((ser.opens, ser.closes), (1, 1))
        self.assertEqual(ser.changes, changes)
        with self.assertRaises(ValueError):
            reader.open()

    def test_port_change_before_open_rejected_and_wrapper_com6_rejected(self):
        ser = c.configure_closed(ClosedSerial, 'COM42')
        reader = c.PySerialReader(ser, 'COM42', self.fingerprint)
        ser.port = 'COM6'
        with self.assertRaises(ValueError):
            reader.open()
        self.assertEqual(ser.opens, 0)
        for target in ('COM6', 'com6', 'COM06', r'\\.\COM6'):
            with self.assertRaises(ValueError):
                c.PySerialReader(ser, target, self.fingerprint)

    def test_complete_lab_pipeline_mock_does_not_promote_enumeration_to_reset_proof(self):
        with patch.object(c, 'windows_module', return_value=SimpleNamespace(Serial=ClosedSerial)), \
             patch.object(c, 'windows_inventory', return_value=self.inventory()):
            result = c.collect_lab('COM42', self.fingerprint, True, c.Limits(seconds=0.05))
        self.assertEqual(result['scope'], 'AUTHORIZED_SPARE_BOARD')
        self.assertEqual(result['target']['port'], 'COM42')
        self.assertEqual(result['target']['usb_serial_sha256'], self.fingerprint)
        self.assertTrue(result['enumeration_after_close_same_identity'])
        self.assertEqual(result['reset_at_close'], 'UNVERIFIED')
        self.assertEqual(result['transient_enumeration_loss'], 'UNVERIFIED_NO_CONTINUOUS_TRACE')

    def test_inventory_change_between_gate_and_open_never_opens(self):
        created = []
        def factory(**kwargs):
            ser = ClosedSerial(**kwargs)
            created.append(ser)
            return ser
        with patch.object(c, 'windows_module', return_value=SimpleNamespace(Serial=factory)), \
             patch.object(c, 'windows_inventory', side_effect=[self.inventory(), self.inventory(pid=0)]):
            with self.assertRaises(ValueError):
                c.collect_lab('COM42', self.fingerprint, True)
        self.assertEqual(created[0].opens, 0)
