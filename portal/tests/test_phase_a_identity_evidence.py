"""No app/server imports: masked offline identity correlation only."""
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
import phase_a_identity_evidence as evidence


class PhaseAEvidenceTests(TestCase):
    def result(self,text,rows=None):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'fixture.log';file.write_text(text,encoding='utf-8')
            return evidence.summarize([file],rows or [])

    def test_station_mac_is_not_bssid_or_bluetooth_speaker(self):
        result=self.result('App version: 2.5.2-wewin-fixture\nwifi:mode : sta (12:34:56:78:90:ab)\nwifi: connected with PRIVATE_SSID, bssid: aa:bb:cc:dd:ee:ff\nBT RX paired aa:bb:cc:dd:ee:ff')
        self.assertEqual(result['distinct_historical_station_macs'],1)
        self.assertEqual(result['logs'][0]['excluded_bluetooth_mac_line_count'],1)
        self.assertNotIn('12:34:56:78:90:ab',json.dumps(result));self.assertNotIn('PRIVATE_SSID',json.dumps(result))

    def test_station_ip_not_gateway_and_match_is_still_historical(self):
        result=self.result('App version: 2.5.2-wewin-fixture\nesp_netif_handlers: sta ip: 192.168.2.41, mask: 255.255.255.0, gw: 192.168.2.1', [{'wire_id':'a'*32,'last_ip':'192.168.2.41','observed_at':1793707506703}])
        self.assertEqual(len(result['logs'][0]['facts']),1)
        self.assertTrue(result['registry'][0]['historical_ip_matches'])
        self.assertEqual(result['current_monster_desk']['ip'],'UNVERIFIED')
        self.assertNotIn('192.168.2.41',json.dumps(result));self.assertNotIn('192.168.2.1"',json.dumps(result))

    def test_wire_hash_name_or_registry_active_does_not_prove_hardware_identity(self):
        result=self.result('',[{'wire_id':'a'*32,'name':'Monster Desk','pairing_state':'active','external_device_id':None}])
        row=result['registry'][0];self.assertEqual(row['wire_id_shape'],'OPAQUE_HEX32_NOT_MAC')
        self.assertEqual(row['current_monster_desk_identity'],'UNVERIFIED')

    def test_unneeded_secret_columns_and_log_secrets_not_exported(self):
        result=self.result('password=PRIVATE_PASSWORD\nAuthorization: Bearer PRIVATE_TOKEN', [{'wire_id':'a'*32,'private_key':'PRIVATE_KEY','session':'PRIVATE_SESSION','name':'PRIVATE_PERSON'}])
        self.assertNotIn('PRIVATE_',json.dumps(result))
