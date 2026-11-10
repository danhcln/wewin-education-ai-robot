"""Offline privacy/attribution tests; no Portal/serial/network runtime needed."""
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest import TestCase

SPEC=importlib.util.spec_from_file_location('saved_log_evidence',Path(__file__).resolve().parents[1]/'scripts/saved_robot_log_evidence.py')
module=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(module)


class SavedLogEvidenceTests(TestCase):
    def inspect(self,text):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.log';path.write_text(text,encoding='utf-8');return module.inspect_log(path)

    def test_secret_and_identifiers_never_exported(self):
        result=self.inspect('Authorization: Bearer SECRET_BEARER\npassword=SECRET_WIFI\nDevice-Id: aa:bb:cc:dd:ee:ff\nwss://user:SECRET_USER@api.tenclass.net/private/SECRET_PATH?token=SECRET_QUERY\nhttps://SECRET_HOST/path\n')
        output=json.dumps(result)
        for secret in ('SECRET_BEARER','SECRET_WIFI','SECRET_USER','SECRET_PATH','SECRET_QUERY','secret_host','aa:bb:cc:dd:ee:ff'):self.assertNotIn(secret,output)
        self.assertEqual(result['sessions'][0]['endpoints'][0]['host'],'api.tenclass.net')

    def test_two_boots_do_not_inherit_custom_build_identity(self):
        result=self.inspect('ESP-ROM:esp32s3\nApp version: 2.5.2-wewin-audio-poc.2\nMqttProtocol: Connected to MQTT server\nESP-ROM:esp32s3\nWebsocketProtocol: Connecting to websocket server\n')
        self.assertEqual(result['sessions'][0]['build_family'],'CUSTOM_WEWIN')
        self.assertEqual(result['sessions'][1]['build_family'],'UNATTRIBUTED')
        self.assertEqual(result['current_robot_transport'],'UNVERIFIED')

    def test_source_strings_or_failed_attempt_do_not_prove_connected(self):
        result=self.inspect('MQTT supported\nWebSocket compiled\nMqttProtocol: Connecting to api.tenclass.net:8883\nMqttProtocol: Connection failed\n')
        events=[v['event'] for v in result['sessions'][0]['events']]
        self.assertIn('mqtt_connect_attempt',events);self.assertNotIn('mqtt_connected',events)
        self.assertTrue(result['sessions'][0]['protocol_marker_lines']['mqtt'])

    def test_matching_version_does_not_prove_factory_or_current_robot(self):
        result=self.inspect('App version: 2.5.3\nWebsocketProtocol: Connected to websocket server\n')
        self.assertEqual(result['sessions'][0]['build_family'],'UNATTRIBUTED')
        self.assertEqual(result['classification'],'VERIFIED_FROM_SAVED_LOGS')
        self.assertEqual(result['current_robot_transport'],'UNVERIFIED')

    def test_hello_exports_transport_audio_but_never_session_udp_keys(self):
        result=self.inspect('RX {"type":"hello","transport":"udp","session_id":"PRIVATE_SESSION","udp":{"key":"PRIVATE_KEY","nonce":"PRIVATE_NONCE"},"audio_params":{"format":"opus","sample_rate":24000,"channels":1,"frame_duration":60}}')
        event=result['sessions'][0]['events'][0]
        self.assertEqual(event['declared_transport'],'udp');self.assertEqual(event['sample_rate'],24000)
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_negated_connection_is_not_success(self):
        result=self.inspect('MQTT: not connected to server\nMQTT: error connected to server\n')
        self.assertNotIn('mqtt_connected',[e['event'] for e in result['sessions'][0]['events']])

    def test_powershell_utf16_log_is_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.log';path.write_text('App version: 2.5.2-wewin-audio-poc.2\nMQTT: Connected to MQTT server',encoding='utf-16')
            result=module.inspect_log(path)
        self.assertEqual(result['sessions'][0]['build_family'],'CUSTOM_WEWIN')

    def test_boot_resets_an_endpoint_only_fragment(self):
        result=self.inspect('wss://api.tenclass.net/private\nESP-ROM:esp32s3\nApp version: 2.5.2-wewin-audio-poc.2\n')
        self.assertEqual(result['sessions'][0]['build_family'],'UNATTRIBUTED')
        self.assertEqual(result['sessions'][1]['endpoints'],[])

    def test_late_version_does_not_relabel_earlier_unattributed_connection(self):
        result=self.inspect('MQTT: Connected to MQTT server\nApp version: 2.5.2-wewin-audio-poc.2\n')
        self.assertEqual(result['sessions'][0]['build_family'],'UNATTRIBUTED')
        self.assertEqual(result['sessions'][1]['events'],[])
