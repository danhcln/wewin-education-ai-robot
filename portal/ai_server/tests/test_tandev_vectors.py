"""Cross-backend golden packets, not WeWIN encode/decode self-consistency.

CNG oracle is a host adaptation of pinned upstream logic, not ESP firmware.
An expected safety rejection is NOT a positive compatibility verdict.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest import TestCase, SkipTest

from ai_server.mqtt_udp import AudioCipher
from ai_server.audio import OpusInput

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from generate_tandev_vectors import build, call_many

GOLD=json.loads((ROOT/'tests/fixtures/tandev_udp_vectors.json').read_text(encoding='utf-8'))
ROWS={r['id']:r for r in GOLD['vectors']}
KEY=bytes.fromhex(GOLD['key']);NONCE=bytes.fromhex(GOLD['nonce'])


class GoldenVectorTests(TestCase):
    def test_independent_golden_packets_decrypt_in_wewin(self):
        for row in ROWS.values():
            with self.subTest(vector=row['id']):
                self.assertEqual(AudioCipher(KEY,NONCE).decode(bytes.fromhex(row['packet'])),bytes.fromhex(row['plaintext']))

    def test_exact_network_order_header_includes_full_timestamp(self):
        self.assertEqual(ROWS['endian_pattern']['packet'][:32],'01000020123456780102030405060708')

    def test_zero_timestamp_counter_overlap_is_incompatible_with_safety_guard(self):
        first=bytes.fromhex(ROWS['zero_timestamp_seq1']['packet'])
        second=bytes.fromhex(ROWS['zero_timestamp_seq2']['packet'])
        # Public zero plaintext: equality exposes reuse across packet blocks.
        self.assertEqual(first[32:48],second[16:32])
        cipher=AudioCipher(KEY,NONCE)
        self.assertEqual(cipher.decode(first),bytes(32))
        with self.assertRaisesRegex(ValueError,'counter overlap'):cipher.decode(second)
        self.assertEqual(cipher.rx,1)
        self.assertEqual(cipher.decode(bytes.fromhex(ROWS['zero_timestamp_seq3']['packet'])),bytes(32))

    def test_independent_opus_packet_is_raw_60ms_mono_16khz(self):
        raw=AudioCipher(KEY,NONCE).decode(bytes.fromhex(ROWS['raw_opus_60ms']['packet']))
        self.assertEqual(len(OpusInput().decode(raw)),1920)

    def test_late_and_duplicate_packets_drop_but_forward_gap_is_accepted(self):
        cipher=AudioCipher(KEY,NONCE)
        row=bytes.fromhex(ROWS['zero_timestamp_seq3']['packet'])
        self.assertEqual(cipher.decode(row),bytes(32))
        for old in ('zero_timestamp_seq1','zero_timestamp_seq2','zero_timestamp_seq3'):
            with self.assertRaisesRegex(ValueError,'Stale'):cipher.decode(bytes.fromhex(ROWS[old]['packet']))

    def test_explicit_empty_or_malformed_session_keys_do_not_become_random_keys(self):
        for key,nonce in ((b'',NONCE),(KEY,b''),(KEY[:15],NONCE),(KEY,NONCE[:15])):
            with self.assertRaises(ValueError):AudioCipher(key,nonce)
        cipher=AudioCipher(KEY,NONCE);cipher.clear()
        with self.assertRaisesRegex(ValueError,'closed'):cipher.encode(b'x')
        with self.assertRaisesRegex(ValueError,'closed'):cipher.decode(bytes.fromhex(ROWS['one_byte']['packet']))


class CNGCrossImplementationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt' or not shutil.which('gcc'):raise SkipTest('Windows CNG + existing GCC required')
        cls.tmp=tempfile.TemporaryDirectory(prefix='wewin-cng-oracle-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.exe=build(Path(cls.tmp.name))

    def test_oracle_source_provenance_and_frozen_packet_regeneration(self):
        source=(ROOT/'tests/reference/tandev_udp_cng.c').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),GOLD['oracle_source_sha256_lf'])
        rows=list(ROWS.values())
        packets=call_many(self.exe,[('send',GOLD['key'],GOLD['nonce'],r['timestamp'],r['sequence'],r['plaintext']) for r in rows])
        for row,wire in zip(rows,packets):
            with self.subTest(vector=row['id']):
                self.assertEqual(wire,row['packet'])

    def test_cng_decrypts_wewin_downlink_despite_unused_flags_domain(self):
        cipher=AudioCipher(KEY,NONCE)
        requests=[];expected=[]
        for name in ('partial_block','max_opus_payload','raw_opus_60ms'):
            row=ROWS[name];wire=cipher.encode(bytes.fromhex(row['plaintext']))
            self.assertEqual(wire[1],1)
            requests.append(('receive',GOLD['key'],wire.hex(),0));expected.append(row['plaintext'])
        self.assertEqual(call_many(self.exe,requests),expected)

    def test_nist_four_block_answer_and_counter_carry(self):
        key='2b7e151628aed2a6abf7158809cf4f3c'
        iv='f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff'
        plain=('6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51'
               '30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710')
        expected=('874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff'
                  '5ae4df3edbd5d35e5b4f09020db03eab1e031dda2fbe03d1792170a0f3009cee')
        boundary=bytes.fromhex('010000201234567800000000ffffffff')
        raw=bytes(33)
        answers=call_many(self.exe,[('crypt',key,iv,plain),('crypt',GOLD['key'],boundary.hex(),raw.hex())])
        self.assertEqual(answers,[expected,AudioCipher(KEY,NONCE).crypt(boundary,raw).hex()])

    def test_upstream_style_receiver_accepts_zero_timestamp_packets_wewin_rejects(self):
        # Documents actual divergence instead of weakening WeWIN's counter guard.
        requests=[('receive',GOLD['key'],ROWS[f'zero_timestamp_seq{seq}']['packet'],seq-1) for seq in (1,2)]
        requests.append(('receive',GOLD['key'],ROWS['zero_timestamp_seq2']['packet'],3))
        self.assertEqual(call_many(self.exe,requests),[bytes(32).hex(),bytes(32).hex(),'ERROR:4'])
