"""Structural corruption/known CRC checks; no firmware or device execution."""
from pathlib import Path
import struct
import sys
from unittest import TestCase

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_tandev_offline import image,otadata


class OfflineImageTests(TestCase):
    def test_known_ota_sequence_crc_and_valid_state(self):
        data=bytearray(b'\xff'*8192)
        struct.pack_into('<I',data,0,1)
        struct.pack_into('<II',data,24,2,0x4743989A)
        result=otadata(data)
        self.assertTrue(result['entries'][0]['crc_valid'])
        self.assertTrue(result['entries'][0]['structurally_selectable'])
        self.assertEqual(result['entries'][0]['two_slot_candidate'],'ota_0')
        self.assertFalse(result['entries'][1]['structurally_selectable'])
        self.assertIn('UNVERIFIED',result['runtime_slot'])

    def test_ota_bad_crc_or_invalid_state_not_selectable(self):
        data=bytearray(b'\xff'*8192)
        struct.pack_into('<I',data,0,1)
        struct.pack_into('<II',data,24,3,0x4743989A)
        self.assertFalse(otadata(data)['entries'][0]['structurally_selectable'])
        struct.pack_into('<II',data,24,2,0)
        self.assertFalse(otadata(data)['entries'][0]['crc_valid'])
        with self.assertRaises(ValueError):otadata(data[:4096])

    def test_blank_not_an_image_and_truncated_segment_refused(self):
        self.assertFalse(image(b'\xff'*128)['is_esp_image'])
        data=bytearray(32);data[0:2]=b'\xe9\x01'
        struct.pack_into('<II',data,24,0x42000000,100)
        with self.assertRaises(ValueError):image(data)

    def test_checksum_and_footer_corruption_detected(self):
        data=bytearray(48);data[0:2]=b'\xe9\x01'
        struct.pack_into('<II',data,24,0x42000000,4)
        data[32:36]=b'\x01\x02\x03\x04';data[47]=0xEB
        self.assertTrue(image(data)['checksum_valid'])
        data[32]^=1
        self.assertFalse(image(data)['checksum_valid'])
        with self.assertRaises(ValueError):image(data[:47])
