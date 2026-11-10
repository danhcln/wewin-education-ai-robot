"""Actual loopback MQTT/UDP sockets + temporary Registry + explicit AI doubles.

No real device, vendor Cloud, external broker or production providers are used.
"""
import asyncio
import hashlib
import ipaddress
import json
import ssl
import struct
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from ai_server.app import create_app
from ai_server.audio import encode_audio, opus_library
from ai_server.mqtt_simulator import Simulator
from ai_server.mqtt_udp import AudioCipher, MQTTUDP, packet, field, read_packet, validate_settings
from ai_server.settings import Settings
from ai_server.store import connect
from ai_server.tests.test_service import FakeProviders


class RecordingProviders(FakeProviders):
    def __init__(self):
        self.turn_slots = asyncio.Semaphore(1)
        self.inputs = []
        self.transcriptions = []

    async def transcribe(self, pcm, language):
        self.transcriptions.append((len(pcm), language))
        return 'WeWIN test connection'

    async def llm(self, messages, model):
        self.inputs.append(messages)
        return {'content': 'Fixture English lesson.'}

    async def synthesize(self, answer, profile):
        return np.sin(np.arange(2880) * 2 * np.pi * 440 / 24000).astype(np.float32) * .1, 24000


async def eventually(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.02)
    raise AssertionError('Condition did not become true')


class CipherTests(TestCase):
    def test_aes_ctr_nist_known_answer_not_just_roundtrip(self):
        cipher = AudioCipher(key=bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c'))
        iv = bytes.fromhex('f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff')
        plain = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
        self.assertEqual(cipher.crypt(iv, plain).hex(), '874d6191b620e3261bef6864990db6ce')

    def test_bounds_replay_and_overlapping_counter_ranges(self):
        c = AudioCipher(key=b'k' * 16, nonce=bytes.fromhex('01000000123456780000000000000000'))
        def make(seq, stamp=0):
            iv = struct.pack('!BBHIII', 1, 0, 32, 0x12345678, stamp, seq)
            return iv + c.crypt(iv, b'x' * 32)
        self.assertEqual(c.decode(make(1)), b'x' * 32)
        for invalid in (make(1), make(2), make(3)[:-1], b'\0' * 17):
            with self.assertRaises(ValueError):
                c.decode(invalid)
        self.assertEqual(c.decode(make(3)), b'x' * 32)
        c.clear()
        self.assertEqual(c.key, b'')

    def test_direction_iv_domains_and_session_keys_differ(self):
        a, b = AudioCipher(), AudioCipher()
        self.assertNotEqual(a.key, b.key)
        self.assertEqual(a.nonce[1], 0)
        self.assertEqual(a.encode(b'x')[1], 1)

    def test_non_loopback_plaintext_or_public_wildcard_refused(self):
        for bind in ('0.0.0.0', '8.8.8.8', '192.168.2.82'):
            with self.assertRaises(ValueError):
                validate_settings(Settings(mqtt_bind=bind))
        lan = Settings(mqtt_bind='192.168.2.82', udp_bind='192.168.2.82', mqtt_port=8883,
                       mqtt_cert='fixture-cert-path', mqtt_key='fixture-key-path', mqtt_public_host='owned.invalid',
                       device_origin='http://owned.invalid:8013')
        with self.assertRaises(ValueError):validate_settings(lan)
        lan.device_origin='https://other.invalid:8014'
        with self.assertRaises(ValueError):validate_settings(lan)
        lan.device_origin='https://owned.invalid:8014'
        validate_settings(lan)  # configuration only, no DNS/socket/cert read


class MQTTFixture(TestCase):
    use_tls = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        key = self.root / 'management'
        key.write_text('isolated-mqtt-management-fixture-12345678')
        self.settings = Settings(db=self.root / 'ai.sqlite3', key_file=key,
                                 connector_db=self.root / 'knowledge.sqlite3',
                                 device_origin='http://127.0.0.1:8010',
                                 mqtt_enabled=True, mqtt_port=0, udp_port=0)
        self.tls = None
        if self.use_tls:
            self.configure_tls()
        self.providers = RecordingProviders()
        self.app = create_app(self.settings, self.providers)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'Authorization': 'Bearer ' + key.read_text(), 'X-WeWIN-Owner': 'fixture-owner', 'X-WeWIN-Tenant': 'fixture-tenant'}
        self.profile = {'ai_model': 'fixture-model', 'voice': 'F1', 'language': 'en-US', 'system_prompt': 'Teacher alpha', 'greeting': 'Hello fixture', 'ai_role': 'builtin-english-teacher'}
        self.assertEqual(self.client.put('/v1/agents/mqtt-agent', headers=self.headers, json={'expected_revision': 0, 'operation_id': 'mqtt-create-fixture-1234', 'config': self.profile}).status_code, 200)
        self.body = {'device_id': 'mqtt-fixture', 'client_id': 'mqtt-client', 'agent_id': 'mqtt-agent', 'transport': 'mqtt_udp', 'kind': 'simulator', 'confirmed': True, 'ownership_attested': True, 'ownership_evidence': 'Isolated owned simulator fixture'}
        p = self.client.post('/v1/device-provisions', headers=self.headers, json=self.body)
        self.assertEqual(p.status_code, 200)
        self.url = p.json()['bootstrap_url']
        self.native = {'Device-Id': 'mqtt-fixture', 'Client-Id': 'mqtt-client', 'Activation-Version': '2'}
        response = self.client.post(self.url, headers=self.native, json={'application': {'version': 'fixture-tandev-2.5.3'}})
        self.assertEqual(response.status_code, 200)
        self.ota = response.json()
        self.config = self.ota['mqtt']
        self.gateway = self.app.state.mqtt_gateway
        self.frame = encode_audio(np.zeros(960, dtype=np.float32), 16000, 16000)[0]

    def configure_tls(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'WeWIN isolated TLS fixture')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
                .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=True,
                                             crl_sign=True, content_commitment=False, data_encipherment=False,
                                             key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                .sign(key, hashes.SHA256()))
        certfile, keyfile = self.root / 'fixture-cert.pem', self.root / 'fixture-key.pem'
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.settings.mqtt_cert, self.settings.mqtt_key = str(certfile), str(keyfile)
        self.tls = ssl.create_default_context(cafile=str(certfile))

    async def simulator(self, **overrides):
        sim = Simulator({**self.config, **overrides}, tls=self.tls)
        self.assertEqual(await sim.connect(), (0x20, b'\0\0'))
        return sim

    async def eof(self, sim):
        self.assertEqual(await asyncio.wait_for(sim.reader.read(1), 4), b'')


class MQTTTests(MQTTFixture):
    def test_abort_cancels_inflight_turn_without_audio_or_model_fallback(self):
        marks = []
        async def stalled(messages, model):
            marks.append('started')
            try:await asyncio.sleep(30)
            finally:marks.append('cancelled')
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                with patch.object(self.providers, 'llm', stalled):
                    await sim.send({'type': 'listen', 'state': 'detect', 'text': 'hello fixture', 'session_id': sim.session})
                    await eventually(lambda: 'started' in marks)
                    await sim.send({'type': 'abort', 'session_id': sim.session})
                    self.assertEqual((await sim.receive())['type'], 'stt')
                    self.assertEqual((await sim.receive())['state'], 'stop')
                    self.assertIn('cancelled', marks)
                    self.assertTrue(sim.inbox.queue.empty())
            finally:await sim.close()
        asyncio.run(scenario())

    def test_owner_guard_and_agent_rebind_fence_active_mqtt(self):
        bad = {**self.headers, 'X-WeWIN-Owner': 'wrong-owner'}
        self.assertEqual(self.client.get('/v1/devices/mqtt-fixture/diagnostics', headers=bad).status_code, 403)
        self.assertEqual(self.client.put('/v1/agents/second-agent', headers=self.headers, json={'expected_revision': 0, 'operation_id': 'second-mqtt-agent-fixture-1234', 'config': self.profile}).status_code, 200)
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                response = self.client.post('/v1/devices/mqtt-fixture/binding', headers=self.headers,
                                            json={'confirmed': True, 'expected_binding_version': 1, 'agent_id': 'second-agent'})
                self.assertEqual(response.status_code, 200)
                await self.eof(sim)
            finally:await sim.close()
            await eventually(lambda: not self.gateway.devices)
            fresh = self.client.post(self.url, headers=self.native, json={}).json()['mqtt']
            self.assertNotEqual(fresh['password'], self.config['password'])
            new = Simulator(fresh)
            try:
                self.assertEqual(await new.connect(), (0x20, b'\0\0'))
                await new.hello(mcp=False)
                self.assertEqual(self.gateway.devices['mqtt-fixture'].device['agent_id'], 'second-agent')
            finally:await new.close()
        asyncio.run(scenario())

    def test_expired_binding_closes_idle_mqtt_and_blocks_bootstrap(self):
        async def scenario():
            sim = await self.simulator()
            try:
                with connect(self.settings) as db:
                    db.execute('UPDATE managed_devices SET expires_at=0 WHERE device_id=?', ('mqtt-fixture',))
                self.client.portal.call(self.gateway.sweep_once)
                await self.eof(sim)
                self.assertEqual(self.client.post(self.url, headers=self.native, json={}).status_code, 403)
            finally:await sim.close()
        asyncio.run(scenario())

    def test_packet_limit_and_unnegotiated_control_fail_closed(self):
        async def scenario():
            for data in (b'\x30\xff\xff\xff\x7f', packet(0x30, field(self.config['publish_topic']) + b'{"type":"listen"}')):
                sim = await self.simulator()
                try:
                    await sim.write(data)
                    await self.eof(sim)
                finally:await sim.close()
                await eventually(lambda: not self.gateway.devices)
        asyncio.run(scenario())

    def test_startup_bind_failure_closes_its_udp_socket(self):
        async def scenario():
            settings = Settings(mqtt_enabled=True, mqtt_port=self.settings.mqtt_port, udp_port=0)
            gateway = MQTTUDP(settings, None, {})
            with self.assertRaises(OSError):await gateway.start()
            self.assertTrue(gateway.udp_transport.is_closing())
            self.assertFalse(gateway.tasks)
        asyncio.run(scenario())

    def test_bootstrap_is_opt_in_and_matches_firmware_settings(self):
        self.assertNotIn('websocket', self.ota)
        self.assertNotIn('firmware', self.ota)
        self.assertNotIn('activation', self.ota)
        self.assertEqual(set(self.config), {'endpoint', 'client_id', 'username', 'password', 'publish_topic', 'keepalive'})
        self.assertTrue(self.client.get('/health').json()['mqtt_udp'])
        self.assertFalse(self.client.get('/health').json()['mqtt_udp_physical_enabled'])
        other = {**self.body, 'device_id': 'websocket-fixture', 'client_id': 'websocket-client', 'transport': 'websocket'}
        p = self.client.post('/v1/device-provisions', headers=self.headers, json=other).json()
        response = self.client.post(p['bootstrap_url'], headers={'Device-Id': other['device_id'], 'Client-Id': other['client_id']}, json={}).json()
        self.assertIn('websocket', response)
        self.assertNotIn('mqtt', response)
        self.settings.mqtt_enabled = False
        self.assertEqual(self.client.post(self.url, headers=self.native, json={}).status_code, 503)

    def test_auth_rejects_wrong_token_client_and_device(self):
        async def scenario():
            for override in ({'password': 'wrong'}, {'client_id': 'other-client'}, {'username': 'other-device'}):
                sim = Simulator({**self.config, **override}, tls=self.tls)
                try:
                    self.assertEqual(await sim.connect(), (0x20, b'\0\x05'))
                    await self.eof(sim)
                finally:
                    await sim.close()
        asyncio.run(scenario())

    def test_hello_mcp_goodbye_and_renegotiation_without_tcp_reconnect(self):
        async def scenario():
            sim = await self.simulator()
            try:
                hello = await sim.hello()
                self.assertEqual((hello['transport'], hello['version']), ('udp', 3))
                self.assertEqual(hello['audio_params']['sample_rate'], 24000)
                init = await sim.receive()
                self.assertEqual(init['payload']['method'], 'initialize')
                await sim.send({'type': 'mcp', 'session_id': sim.session, 'payload': {'jsonrpc': '2.0', 'id': 1, 'result': {}}})
                self.assertEqual((await sim.receive())['payload']['method'], 'notifications/initialized')
                self.assertEqual((await sim.receive())['payload']['method'], 'tools/list')
                await sim.send({'type': 'mcp', 'session_id': sim.session, 'payload': {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': []}}})
                old_socket = self.gateway.devices['mqtt-fixture'].socket
                await sim.send({'type': 'goodbye', 'session_id': sim.session})
                self.assertEqual((await sim.receive())['type'], 'goodbye')
                await eventually(lambda: self.gateway.devices['mqtt-fixture'].socket is None)
                self.assertEqual(old_socket.cipher.key, b'')
                sim.udp.close()
                hello2 = await sim.hello(mcp=False)
                self.assertNotEqual(hello2['session_id'], hello['session_id'])
                self.assertNotEqual(hello2['udp']['key'], hello['udp']['key'])
            finally:
                await sim.close()
        asyncio.run(scenario())

    def test_udp_opus_asr_mcp_tts_and_next_turn_role_revision(self):
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                # First uplink establishes the observed UDP tuple; never guess it.
                sim.audio(self.frame)
                await eventually(lambda: self.gateway.devices['mqtt-fixture'].socket.address is not None)
                for revision in (1, 2):
                    if revision == 2:
                        response = self.client.put('/v1/agents/mqtt-agent', headers=self.headers, json={'expected_revision': 1, 'operation_id': 'mqtt-role-change-fixture-1234', 'config': {**self.profile, 'system_prompt': 'Teacher beta', 'ai_role': 'builtin-consultant'}})
                        self.assertEqual(response.status_code, 200)
                    await sim.send({'type': 'listen', 'state': 'start', 'mode': 'manual', 'session_id': sim.session})
                    sim.audio(self.frame)
                    await asyncio.sleep(.04)
                    await sim.send({'type': 'listen', 'state': 'stop', 'session_id': sim.session})
                    events = []
                    while True:
                        event = await sim.receive()
                        events.append(event)
                        if event.get('type') == 'tts' and event.get('state') == 'stop':
                            break
                    self.assertNotIn('error', [x['type'] for x in events])
                    evidence = next(x for x in events if x['type'] == 'wewin_config')
                    self.assertEqual(evidence['revision'], revision)
                    self.assertIn('wewin_test_connection', evidence['tools'])
                    frame = await sim.receive_audio()
                    decoded = opus_library().Decoder(24000, 1).decode(frame, 1440, False)
                    self.assertEqual(len(decoded), 2880)
                    await sim.receive_audio()
                self.assertEqual(self.providers.transcriptions, [(1920, 'en'), (1920, 'en')])
                self.assertIn('Teacher beta', self.providers.inputs[-1][0]['content'])
                self.assertFalse(any('Teacher alpha' in x.get('content', '') for x in self.providers.inputs[-1]))
            finally:
                await sim.close()
        asyncio.run(scenario())
        with connect(self.settings) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM turns').fetchone()[0], 2)
            self.assertNotIn(self.config['password'], json.dumps([tuple(r) for r in db.execute('SELECT * FROM audit')] ))

    def test_acl_denies_cross_device_wildcards_and_retained_control(self):
        async def scenario():
            for raw in (packet(0x30, field('wewin/devices/other-device/up') + b'{}'),
                        packet(0x82, b'\0\x01' + field('#') + b'\0'),
                        packet(0x31, field(self.config['publish_topic']) + b'{}')):
                sim = await self.simulator()
                try:
                    await sim.write(raw)
                    await self.eof(sim)
                finally:
                    await sim.close()
                await eventually(lambda: not self.gateway.devices)
        asyncio.run(scenario())

    def test_keepalive_subscription_and_reconnect(self):
        async def scenario():
            for _ in range(2):
                sim = await self.simulator()
                try:
                    await sim.write(packet(0x82, b'\0\x07' + field('wewin/devices/mqtt-fixture/down') + b'\0'))
                    self.assertEqual(await read_packet(sim.reader), (0x90, b'\0\x07\0'))
                    await sim.write(packet(0xA2, b'\0\x08' + field('wewin/devices/mqtt-fixture/down')))
                    self.assertEqual(await read_packet(sim.reader), (0xB0, b'\0\x08'))
                    self.assertFalse(self.gateway.devices['mqtt-fixture'].downlink_enabled)
                    await sim.write(packet(0x82, b'\0\x09' + field('wewin/devices/mqtt-fixture/down') + b'\0'))
                    self.assertEqual(await read_packet(sim.reader), (0x90, b'\0\x09\0'))
                    await sim.write(packet(0xC0))
                    self.assertEqual(await read_packet(sim.reader), (0xD0, b''))
                    await sim.hello(mcp=False)
                finally:
                    await sim.close()
                await eventually(lambda: not self.gateway.devices)
            with connect(self.settings) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM sessions WHERE ended_at IS NULL').fetchone()[0], 0)
        asyncio.run(scenario())

    def test_duplicate_client_does_not_evict_existing_session(self):
        async def scenario():
            first = await self.simulator()
            second = Simulator(self.config)
            try:
                self.assertEqual(await second.connect(), (0x20, b'\0\x03'))
                await first.write(packet(0xC0))
                self.assertEqual(await read_packet(first.reader), (0xD0, b''))
            finally:
                await second.close()
                await first.close()
        asyncio.run(scenario())

    def test_udp_replay_wrong_tuple_and_stale_session_are_dropped(self):
        async def scenario():
            sim = await self.simulator()
            attacker = None
            try:
                await sim.hello(mcp=False)
                raw = sim.audio(self.frame)
                await eventually(lambda: self.gateway.devices['mqtt-fixture'].socket.cipher.rx == 1)
                channel = self.gateway.devices['mqtt-fixture'].socket
                target = ('127.0.0.1', self.gateway.udp_port)
                before = self.gateway.dropped_datagrams
                sim.udp.sendto(raw, target)
                attacker, _ = await asyncio.get_running_loop().create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=('127.0.0.1', 0))
                attacker.sendto(sim.encrypted_audio(self.frame), target)
                sim.udp.sendto(b'\0' * 2000, target)
                await eventually(lambda: self.gateway.dropped_datagrams >= before + 3)
                self.assertEqual(channel.cipher.rx, 1)
                await sim.send({'type': 'goodbye', 'session_id': sim.session})
                await sim.receive()
                await eventually(lambda: self.gateway.devices['mqtt-fixture'].socket is None)
                before = self.gateway.dropped_datagrams
                sim.udp.sendto(raw, target)
                await eventually(lambda: self.gateway.dropped_datagrams > before)
            finally:
                if attacker: attacker.close()
                await sim.close()
        asyncio.run(scenario())

    def test_revocation_closes_idle_connection_and_prevents_reconnect(self):
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                response = self.client.post('/v1/devices/mqtt-fixture/revoke', headers=self.headers, json={'confirmed': True})
                self.assertEqual(response.status_code, 200)
                await self.eof(sim)
            finally:
                await sim.close()
            await eventually(lambda: not self.gateway.devices)
            denied = Simulator(self.config)
            try:
                self.assertEqual(await denied.connect(), (0x20, b'\0\x05'))
            finally:
                await denied.close()
        asyncio.run(scenario())

    def test_credential_rotation_fences_old_password(self):
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                rotated = self.client.post('/v1/devices/mqtt-fixture/credentials/rotate', headers=self.headers, json={'confirmed': True, 'expected_binding_version': 1})
                self.assertEqual(rotated.status_code, 200)
                await self.eof(sim)
            finally:
                await sim.close()
            await eventually(lambda: not self.gateway.devices)
            old = Simulator(self.config)
            try:
                self.assertEqual(await old.connect(), (0x20, b'\0\x05'))
            finally:
                await old.close()
            fresh = self.client.post(rotated.json()['bootstrap_url'], headers=self.native, json={}).json()['mqtt']
            self.assertNotEqual(fresh['password'], self.config['password'])
            new = Simulator(fresh)
            try:
                self.assertEqual(await new.connect(), (0x20, b'\0\0'))
            finally:
                await new.close()
        asyncio.run(scenario())

    def test_bad_hello_and_session_mismatch_close_cleanly(self):
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.send({'type': 'hello', 'transport': 'udp', 'version': 1, 'audio_params': {}})
                await self.eof(sim)
            finally:
                await sim.close()
            await eventually(lambda: not self.gateway.devices)
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                await sim.send({'type': 'listen', 'state': 'start', 'session_id': 'wrong'})
                await self.eof(sim)
            finally:
                await sim.close()
        asyncio.run(scenario())

    def test_timeout_cleanup_and_physical_enrollment_denied(self):
        self.settings.real_devices = self.settings.trusted_tls_edge = True
        self.settings.device_origin = 'https://192.168.2.82:8014'
        physical = {**self.body, 'device_id': 'physical-fixture', 'client_id': 'physical-client', 'kind': 'physical'}
        self.assertEqual(self.client.post('/v1/device-provisions', headers=self.headers, json=physical).status_code, 403)
        self.settings.device_origin = 'http://127.0.0.1:8010'
        async def scenario():
            sim = await self.simulator()
            try:
                await sim.hello(mcp=False)
                peer = self.gateway.devices['mqtt-fixture']
                peer.last_packet = time.monotonic() - 400
                self.client.portal.call(self.gateway.sweep_once)
                await self.eof(sim)
            finally:
                await sim.close()
        asyncio.run(scenario())


class MQTTTLSTests(MQTTFixture):
    use_tls = True

    def test_tls_engine_verifies_certificate_chain_and_hostname(self):
        # MemoryBIO executes real OpenSSL TLS records, independent of host AV
        # network interception. It is not a broker socket/ESP trust result.
        def handshake(context, hostname):
            server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.load_cert_chain(self.settings.mqtt_cert, self.settings.mqtt_key)
            ci, co, si, so = [ssl.MemoryBIO() for _ in range(4)]
            client = context.wrap_bio(ci, co, server_hostname=hostname)
            peer = server.wrap_bio(si, so, server_side=True)
            for _ in range(12):
                for stream in (client, peer):
                    try:stream.do_handshake()
                    except ssl.SSLWantReadError:pass
                si.write(co.read());ci.write(so.read())
            return client.version()
        self.assertIn(handshake(self.tls, '127.0.0.1'), ('TLSv1.2', 'TLSv1.3'))
        for context, hostname in ((ssl.create_default_context(), '127.0.0.1'), (self.tls, 'wrong-host.invalid')):
            with self.assertRaises(ssl.SSLCertVerificationError):handshake(context, hostname)

    def test_tls_broker_socket_verified_ca_and_hostname(self):
        observed_issuer = []
        def certificate_message(conn, direction, version, kind, msg, data):
            if direction == 'read' and int(msg) == 11 and version == ssl.TLSVersion.TLSv1_3:
                from cryptography import x509
                pos = 5 + data[4] + 3
                length = int.from_bytes(data[pos:pos+3], 'big')
                observed_issuer.append(x509.load_der_x509_certificate(data[pos+3:pos+3+length]).issuer.rfc4514_string())
        self.tls._msg_callback = certificate_message
        async def scenario():
            try:
                sim = await self.simulator()
            except ssl.SSLCertVerificationError:
                if any('Avast Web/Mail Shield' in issuer for issuer in observed_issuer):
                    self.skipTest('BLOCKED: host Avast substitutes loopback TLS certificate; validation kept enabled, no AV/CA settings changed')
                raise
            try:
                self.assertIn(sim.writer.get_extra_info('ssl_object').version(), ('TLSv1.2', 'TLSv1.3'))
                await sim.hello(mcp=False)
            finally:
                await sim.close()
            for context, hostname in ((ssl.create_default_context(), '127.0.0.1'), (self.tls, 'wrong-host.invalid')):
                with self.assertRaises(ssl.SSLCertVerificationError):
                    await asyncio.open_connection('127.0.0.1', self.settings.mqtt_port, ssl=context, server_hostname=hostname)
        asyncio.run(scenario())


class MQTTEdgeTests(TestCase):
    def test_mqtt_bootstrap_edge_checks_https_host_and_8883_before_returning_secret(self):
        import httpx
        from ai_server.edge import create_edge
        from ai_server.device_management import PREFIX
        for base, endpoint, expected in (('https://owned.invalid:8014', 'owned.invalid:8883', 200),
                                         ('https://owned.invalid:8014', 'other.invalid:8883', 502),
                                         ('https://owned.invalid:8014', 'owned.invalid:1883', 502),
                                         ('http://owned.invalid:8013', 'owned.invalid:8883', 502)):
            with TestClient(create_edge(), base_url=base) as client, patch('ai_server.edge.httpx.AsyncClient') as factory:
                upstream = factory.return_value.__aenter__ = AsyncMock()
                factory.return_value.__aexit__ = AsyncMock(return_value=False)
                upstream.return_value.post = AsyncMock(return_value=httpx.Response(200, json={'mqtt': {'endpoint': endpoint, 'password': 'fixture-secret'}}))
                response = client.post(PREFIX + 'a' * 43, json={})
                self.assertEqual(response.status_code, expected)
                if expected != 200:self.assertNotIn('fixture-secret', response.text)
