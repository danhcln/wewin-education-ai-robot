"""Opt-in XiaoZhi MQTT 3.1.1/QoS0 + UDP staging transport.

Not a general purpose broker. No retained messages, wildcard ACLs, persistent
sessions, bridges or vendor credentials. Physical clients are deliberately denied:
the legacy AES-CTR audio contract has no message authentication.
"""
import asyncio
import hashlib
import ipaddress
import json
import secrets
import ssl
import struct
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from starlette.websockets import WebSocketState
from .store import connect, audit
from .device_management import binding_valid, tls_required

MAX_PACKET = 16384
MAX_OPUS = 1275


def field(value):
    raw = value.encode('utf-8')
    if len(raw) > 4096 or '\0' in value:
        raise ValueError('Invalid MQTT string')
    return struct.pack('!H', len(raw)) + raw


def take_field(data, offset=0):
    if offset + 2 > len(data):
        raise ValueError('Truncated MQTT string')
    size = struct.unpack_from('!H', data, offset)[0]
    end = offset + 2 + size
    if size > 4096 or end > len(data):
        raise ValueError('Invalid MQTT string length')
    value = data[offset + 2:end].decode('utf-8')
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('Invalid MQTT UTF-8')
    return value, end


def packet(header, body=b''):
    if len(body) > MAX_PACKET:
        raise ValueError('MQTT packet limit')
    length = len(body)
    encoded = bytearray([header])
    while True:
        digit = length % 128
        length //= 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            return bytes(encoded) + body


async def read_packet(reader):
    header = (await reader.readexactly(1))[0]
    length = 0
    for index in range(4):
        digit = (await reader.readexactly(1))[0]
        length += (digit & 127) << (7 * index)
        if length > MAX_PACKET:
            raise ValueError('MQTT packet limit')
        if digit < 128:
            if index and digit == 0:
                raise ValueError('Noncanonical MQTT length')
            return header, await reader.readexactly(length)
    raise ValueError('Invalid MQTT length')


def credentials(body):
    protocol, pos = take_field(body)
    if protocol != 'MQTT' or len(body) < pos + 4 or body[pos] != 4:
        raise ValueError('Only MQTT 3.1.1 is supported')
    # Username/password, clean session; no Will/retained state.
    if body[pos + 1] != 0xC2:
        raise ValueError('Clean authenticated session required')
    keepalive = struct.unpack_from('!H', body, pos + 2)[0]
    if not 5 <= keepalive <= 240:
        raise ValueError('Keepalive outside staging bounds')
    client, pos = take_field(body, pos + 4)
    username, pos = take_field(body, pos)
    password, pos = take_field(body, pos)
    if pos != len(body) or not client or not username or not password:
        raise ValueError('Invalid MQTT credentials')
    return client, username, password, keepalive


def topics(device_id):
    # Registry IDs cannot contain MQTT separators/wildcards.
    return f'wewin/devices/{device_id}/up', f'wewin/devices/{device_id}/down'


def validate_settings(settings):
    for address in (settings.mqtt_bind, settings.udp_bind):
        ip = ipaddress.ip_address(address)
        if ip.version != 4 or ip.is_unspecified or not (ip.is_loopback or ip.is_private):
            raise ValueError('Staging requires an explicit loopback/private IPv4 bind')
    host = settings.mqtt_public_host
    if not host or len(host) > 253 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in host):
        raise ValueError('Invalid owned staging host')
    if bool(settings.mqtt_cert) != bool(settings.mqtt_key):
        raise ValueError('Both MQTT TLS certificate and key are required')
    local = all(ipaddress.ip_address(x).is_loopback for x in (settings.mqtt_bind, settings.udp_bind))
    if not local and (not settings.mqtt_cert or settings.mqtt_port != 8883):
        raise ValueError('LAN staging requires TLS on 8883; firmware selects TLS by port')
    if not local:
        origin = urlsplit(settings.device_origin)
        if origin.scheme != 'https' or origin.hostname != host:
            raise ValueError('LAN MQTT credentials require the same owned HTTPS bootstrap host')
    if not settings.mqtt_cert and host != settings.mqtt_bind:
        raise ValueError('Plaintext simulator host must match loopback bind')
    if not 0 <= settings.mqtt_port <= 65535 or not 0 <= settings.udp_port <= 65535:
        raise ValueError('Invalid staging port')


def bootstrap_config(settings, device, token):
    validate_settings(settings)
    if not settings.mqtt_enabled or device['kind'] != 'simulator':
        raise ValueError('MQTT/UDP is enabled only for explicit staging simulators')
    up, _ = topics(device['id'])
    return {'endpoint': f'{settings.mqtt_public_host}:{settings.mqtt_port}',
            'client_id': device['client_id'], 'username': device['id'],
            'password': token, 'publish_topic': up, 'keepalive': 60}


def server_tls_context(cert, key):
    """Shared by the listener and controlled certificate-chain validation gate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


class AudioCipher:
    """16-byte network-order header is also the AES-CTR IV (reference contract).

    CTR is NOT authenticated. Tuple pinning/sequence checks are only mitigations.
    Detect overlapping uplink counter ranges; stock zero-timestamp streams can
    violate nonce safety. Downlink uses a separate flags domain and 60ms clock.
    """
    def __init__(self, key=None, nonce=None):
        self.key = secrets.token_bytes(16) if key is None else key
        self.nonce = b'\x01\x00\x00\x00' + secrets.token_bytes(4) + b'\0' * 8 if nonce is None else nonce
        if len(self.key) != 16 or len(self.nonce) != 16 or self.nonce[:2] != b'\x01\x00':
            raise ValueError('Invalid audio key/nonce')
        self.rx = self.tx = 0
        self.ranges = {}

    def crypt(self, iv, data):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        cipher = Cipher(algorithms.AES(self.key), modes.CTR(iv)).encryptor()
        return cipher.update(data) + cipher.finalize()

    def decode(self, data):
        if len(self.key)!=16 or len(self.nonce)!=16:
            raise ValueError('Audio session closed')
        if len(data) < 17:
            raise ValueError('Truncated UDP audio')
        iv = data[:16]
        kind, flags, length, ssrc, timestamp, seq = struct.unpack('!BBHIII', iv)
        if kind != 1 or flags != 0 or iv[4:8] != self.nonce[4:8] or not 0 < length <= MAX_OPUS or len(data) != length + 16:
            raise ValueError('Invalid UDP header')
        if not self.rx < seq < 0xFFFFFF00:
            raise ValueError('Stale UDP sequence')
        previous = self.ranges.get(iv[:12], 0)
        if seq < previous or len(self.ranges) >= 10000:
            raise ValueError('Unsafe CTR counter overlap/session limit')
        plain = self.crypt(iv, data[16:])
        self.ranges[iv[:12]] = seq + (length + 15) // 16
        self.rx = seq
        return plain

    def encode(self, opus):
        if len(self.key)!=16 or len(self.nonce)!=16:
            raise ValueError('Audio session closed')
        if not 0 < len(opus) <= MAX_OPUS or self.tx >= 10000:
            raise ValueError('Downlink audio limit')
        self.tx += 1
        # The firmware decrypts with each received header and ignores flags.
        iv = struct.pack('!BBHIII', 1, 1, len(opus), int.from_bytes(self.nonce[4:8], 'big'), self.tx * 60, self.tx)
        return iv + self.crypt(iv, opus)

    def clear(self):
        self.key = self.nonce = b''
        self.ranges.clear()


class DeviceSocket:
    """Transport facade into the existing authenticated Agent/audio/MCP pipeline."""
    def __init__(self, peer):
        self.peer = peer
        self.headers = {'authorization': 'Bearer ' + peer.password,
                        'device-id': peer.device['id'], 'client-id': peer.device['client_id'], 'protocol-version': '1'}
        self.url = SimpleNamespace(query='')
        self.client = SimpleNamespace(host=peer.address[0])
        self.secure = bool(peer.writer.get_extra_info('ssl_object'))
        self.application_state = WebSocketState.CONNECTING
        self.queue = asyncio.Queue(maxsize=128)
        self.cipher = AudioCipher()
        self.address = None
        self.opened_at = time.monotonic()

    async def accept(self):
        self.application_state = WebSocketState.CONNECTED

    async def receive_json(self):
        item = await self.receive()
        if item['type'] == 'websocket.disconnect':
            raise ValueError('Session closed')
        return json.loads(item['text'])

    async def receive(self):
        return await self.queue.get()

    async def send_json(self, value):
        if not self.peer.downlink_enabled:
            return
        if value.get('type') == 'hello':
            value = {**value, 'udp': {'server': self.peer.gateway.settings.mqtt_public_host,
                                     'port': self.peer.gateway.udp_port,
                                     'key': self.cipher.key.hex(), 'nonce': self.cipher.nonce.hex()}}
            self.peer.session_id = value['session_id']
        await self.peer.send(packet(0x30, field(self.peer.down) + json.dumps(value, separators=(',', ':')).encode()))

    async def send_bytes(self, opus):
        if not self.address:
            raise ValueError('UDP peer has not sent a valid audio packet')
        self.peer.gateway.udp_transport.sendto(self.cipher.encode(opus), self.address)

    def incoming(self, item):
        if self.application_state == WebSocketState.DISCONNECTED:
            return
        self.queue.put_nowait(item)

    async def close(self, code=1000):
        self.peer.writer.close()
        self.finish()

    def finish(self):
        self.application_state = WebSocketState.DISCONNECTED
        self.cipher.clear()
        # Ensure blocked receive wakes even if the bounded queue was full.
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait({'type': 'websocket.disconnect'})


class Peer:
    def __init__(self, gateway, reader, writer):
        self.gateway, self.reader, self.writer = gateway, reader, writer
        self.address = writer.get_extra_info('peername')
        self.device = self.password = self.client_id = None
        self.socket = self.runtime = None
        self.session_id = None
        self.last_packet = time.monotonic()
        self.keepalive = 10
        self.count = 0
        self.window = self.last_packet
        self.send_lock = asyncio.Lock()
        self.downlink_enabled = True  # implicit private subscription at CONNECT

    async def send(self, value):
        async with self.send_lock:
            self.writer.write(value)
            await asyncio.wait_for(self.writer.drain(), 5)

    def authorized(self):
        with connect(self.gateway.settings) as db:
            row = db.execute('SELECT * FROM devices WHERE id=?', (self.device['id'],)).fetchone()
            choice = db.execute('SELECT transport FROM device_protocols WHERE device_id=?', (self.device['id'],)).fetchone()
            return bool(row and choice and choice[0] == 'mqtt_udp' and row['kind'] == 'simulator' and not row['revoked'] and
                        row['client_id'] == self.client_id and row['agent_id'] == self.device['agent_id'] and
                        secrets.compare_digest(row['token_hash'], hashlib.sha256(self.password.encode()).hexdigest()) and
                        binding_valid(db, row) and (not tls_required(db, self.gateway.settings, row['id']) or self.writer.get_extra_info('ssl_object')))

    async def end_audio(self, notify=False):
        if self.socket:
            if notify and not self.writer.is_closing():
                try:await self.socket.send_json({'type': 'goodbye', 'session_id': self.session_id})
                except (ConnectionError, OSError, asyncio.TimeoutError):self.writer.close()
            self.socket.finish()
            if self.runtime:
                self.runtime.cancel()
                await asyncio.gather(self.runtime, return_exceptions=True)
            self.socket = self.runtime = None
            self.session_id = None

    async def publish(self, raw):
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Control object required')
        if value.get('type') == 'hello':
            if self.socket:
                raise ValueError('Duplicate HELLO; close audio before renegotiation')
            self.socket = DeviceSocket(self)
            self.socket.incoming({'type': 'websocket.receive', 'text': raw.decode()})
            self.runtime = asyncio.create_task(self.gateway.serve(self.socket))
        elif value.get('type') == 'goodbye':
            if not self.socket or value.get('session_id') != self.session_id:
                raise ValueError('Goodbye session mismatch')
            await self.end_audio(notify=True)
        else:
            if not self.socket or value.get('session_id') != self.session_id or value.get('type') not in ('listen', 'abort', 'mcp'):
                raise ValueError('Invalid control/session')
            self.socket.incoming({'type': 'websocket.receive', 'text': raw.decode()})

    async def run(self):
        try:
            header, body = await asyncio.wait_for(read_packet(self.reader), 5)
            if header != 0x10:
                raise ValueError('CONNECT required')
            self.client_id, username, self.password, self.keepalive = credentials(body)
            with connect(self.gateway.settings) as db:
                row = db.execute('SELECT * FROM devices WHERE id=?', (username,)).fetchone()
            self.device = dict(row) if row else None
            if not self.device or not self.authorized():
                await self.send(packet(0x20, b'\0\x05'))
                return
            if self.device['id'] in self.gateway.devices or self.device['id'] in self.gateway.connections:
                await self.send(packet(0x20, b'\0\x03'))
                return
            self.gateway.devices[self.device['id']] = self
            self.up, self.down = topics(self.device['id'])
            with connect(self.gateway.settings) as db:
                audit(db, 'mqtt_authenticated', self.device['id'], 'simulator; scoped ACL; clean session')
            await self.send(packet(0x20, b'\0\0'))
            while True:
                header, body = await asyncio.wait_for(read_packet(self.reader), self.keepalive * 1.5)
                self.last_packet = time.monotonic()
                if not self.authorized():
                    break
                if self.last_packet - self.window >= 60:
                    self.window, self.count = self.last_packet, 0
                self.count += 1
                if self.count > 1500:
                    raise ValueError('MQTT rate limit')
                if header == 0xC0 and not body:
                    await self.send(packet(0xD0))
                elif header == 0xE0 and not body:
                    break
                elif header == 0x30:  # QoS0 only, no retained / DUP control replay.
                    topic, pos = take_field(body)
                    if topic != self.up:
                        raise ValueError('Publish ACL denied')
                    await self.publish(body[pos:])
                elif header == 0x82:
                    if len(body) < 3 or body[:2] == b'\0\0':
                        raise ValueError('Invalid subscription')
                    topic, pos = take_field(body, 2)
                    if pos + 1 != len(body) or body[pos] != 0 or topic != self.down:
                        raise ValueError('Subscribe ACL/QoS denied')
                    self.downlink_enabled = True
                    await self.send(packet(0x90, body[:2] + b'\0'))
                elif header == 0xA2:
                    topic, pos = take_field(body, 2)
                    if pos != len(body) or body[:2] == b'\0\0' or topic != self.down:
                        raise ValueError('Unsubscribe ACL denied')
                    self.downlink_enabled = False
                    await self.send(packet(0xB0, body[:2]))
                else:
                    raise ValueError('Unsupported MQTT packet/QoS')
        except (ValueError, UnicodeError, RecursionError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionError, OSError, asyncio.QueueFull):
            # Never log CONNECT/password, JSON, keys, audio or exception payload.
            pass
        finally:
            await self.end_audio()
            if self.device and self.gateway.devices.get(self.device['id']) is self:
                self.gateway.devices.pop(self.device['id'], None)
                with connect(self.gateway.settings) as db:
                    audit(db, 'mqtt_disconnected', self.device['id'], 'session keys discarded')
            self.password = None
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), 5)
            except (OSError, asyncio.TimeoutError):
                pass


class MQTTUDP(asyncio.DatagramProtocol):
    def __init__(self, settings, serve, connections):
        self.settings, self.serve, self.connections = settings, serve, connections
        self.devices = {}
        self.peers = set()
        self.tasks = set()
        self.server = self.udp_transport = self.watchdog = None
        self.udp_port = None
        self.dropped_datagrams = 0
        self.udp_closed = None

    def connection_lost(self, exc):
        if self.udp_closed and not self.udp_closed.done():self.udp_closed.set_result(None)

    async def start(self):
        validate_settings(self.settings)
        context = None
        if self.settings.mqtt_cert:
            context = server_tls_context(self.settings.mqtt_cert, self.settings.mqtt_key)
        try:
            self.udp_closed = asyncio.get_running_loop().create_future()
            self.udp_transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: self, local_addr=(self.settings.udp_bind, self.settings.udp_port))
            self.udp_port = self.udp_transport.get_extra_info('sockname')[1]
            self.server = await asyncio.start_server(self.accept, self.settings.mqtt_bind, self.settings.mqtt_port,
                                                     ssl=context, limit=MAX_PACKET + 8, **({'ssl_handshake_timeout': 5} if context else {}))
            self.settings.mqtt_port = self.server.sockets[0].getsockname()[1]
            self.watchdog = asyncio.create_task(self.sweep())
        except BaseException:
            await self.stop()
            raise

    async def accept(self, reader, writer):
        if len(self.peers) >= 8:
            writer.close()
            return
        peer = Peer(self, reader, writer)
        task = asyncio.current_task()
        self.peers.add(peer)
        self.tasks.add(task)
        try:
            await peer.run()
        finally:
            self.peers.discard(peer)
            self.tasks.discard(task)

    def datagram_received(self, data, address):
        # Never answer unknown UDP sources (no reflection/discovery).
        try:
            if len(data) < 17 or len(data) > 16 + MAX_OPUS:
                raise ValueError('UDP bounds')
            matches = [p for p in self.devices.values() if p.socket and
                       p.socket.application_state == WebSocketState.CONNECTED and
                       p.socket.cipher.nonce[4:8] == data[4:8]]
            if len(matches) != 1:
                raise ValueError('Unknown UDP session')
            peer = matches[0]
            channel = peer.socket
            if address[0] != peer.address[0] or channel.address and channel.address != address or not peer.authorized():
                raise ValueError('UDP peer/authorization mismatch')
            plain = channel.cipher.decode(data)
            channel.incoming({'type': 'websocket.receive', 'bytes': plain})
            channel.address = address
        except (ValueError, asyncio.QueueFull):
            self.dropped_datagrams += 1

    async def sweep_once(self):
        now = time.monotonic()
        for peer in list(self.devices.values()):
            if not peer.authorized() or now - peer.last_packet > peer.keepalive * 1.5:
                peer.writer.close()
            elif peer.socket and now - peer.socket.opened_at > 600:
                await peer.end_audio(notify=True)

    async def sweep(self):
        while True:
            await asyncio.sleep(1)
            await self.sweep_once()

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.watchdog:
            self.watchdog.cancel()
            await asyncio.gather(self.watchdog, return_exceptions=True)
        for peer in list(self.peers):
            peer.writer.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.udp_transport:
            self.udp_transport.close()
            if self.udp_closed:
                await asyncio.wait_for(asyncio.shield(self.udp_closed), 2)
