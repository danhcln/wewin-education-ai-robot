"""Loopback-only test client; never discovers/connects a physical device."""
import asyncio
import ipaddress
import json
import struct
from .mqtt_udp import packet, field, read_packet, take_field


class DatagramInbox(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=128)
        self.closed = asyncio.get_running_loop().create_future()

    def connection_lost(self, exc):
        if not self.closed.done():self.closed.set_result(None)

    def datagram_received(self, data, address):
        if not self.queue.full():
            self.queue.put_nowait(data)


class Simulator:
    def __init__(self, config, tls=None):
        self.config, self.tls = config, tls
        self.reader = self.writer = self.udp = None
        self.sequence = 0

    async def connect(self):
        host, port = self.config['endpoint'].rsplit(':', 1)
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError('Simulator is restricted to loopback')
        self.reader, self.writer = await asyncio.open_connection(host, int(port), ssl=self.tls)
        body = field('MQTT') + b'\x04\xc2\x00\x3c'
        body += field(self.config['client_id']) + field(self.config['username']) + field(self.config['password'])
        await self.write(packet(0x10, body))
        return await asyncio.wait_for(read_packet(self.reader), 5)

    async def write(self, raw):
        self.writer.write(raw)
        await self.writer.drain()

    async def send(self, value, topic=None):
        await self.write(packet(0x30, field(topic or self.config['publish_topic']) + json.dumps(value).encode()))

    async def receive(self):
        header, body = await asyncio.wait_for(read_packet(self.reader), 5)
        if header != 0x30:
            raise ValueError('Expected MQTT control reply')
        _, offset = take_field(body)
        return json.loads(body[offset:])

    async def hello(self, mcp=True):
        if self.udp:
            self.udp.close()
            await asyncio.wait_for(asyncio.shield(self.inbox.closed), 2)
        await self.send({'type': 'hello', 'version': 3, 'transport': 'udp', 'features': {'mcp': mcp},
                         'audio_params': {'format': 'opus', 'sample_rate': 16000, 'channels': 1, 'frame_duration': 60}})
        self.negotiation = await self.receive()
        self.session = self.negotiation['session_id']
        self.sequence = 0
        self.udp, self.inbox = await asyncio.get_running_loop().create_datagram_endpoint(DatagramInbox, local_addr=('127.0.0.1', 0))
        return self.negotiation

    def encrypted_audio(self, opus, timestamp=None, sequence=None):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        self.sequence = sequence if sequence is not None else self.sequence + 1
        iv = bytearray.fromhex(self.negotiation['udp']['nonce'])
        struct.pack_into('!H', iv, 2, len(opus))
        struct.pack_into('!II', iv, 8, self.sequence * 60 if timestamp is None else timestamp, self.sequence)
        encryptor = Cipher(algorithms.AES(bytes.fromhex(self.negotiation['udp']['key'])), modes.CTR(bytes(iv))).encryptor()
        return bytes(iv) + encryptor.update(opus) + encryptor.finalize()

    def audio(self, opus, **kwargs):
        payload = self.encrypted_audio(opus, **kwargs)
        target = self.negotiation['udp']
        self.udp.sendto(payload, (target['server'], target['port']))
        return payload

    async def receive_audio(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        data = await asyncio.wait_for(self.inbox.queue.get(), 5)
        if len(data) < 17 or data[0] != 1 or len(data) != 16 + int.from_bytes(data[2:4], 'big'):
            raise ValueError('Invalid downlink frame')
        decryptor = Cipher(algorithms.AES(bytes.fromhex(self.negotiation['udp']['key'])), modes.CTR(data[:16])).decryptor()
        return decryptor.update(data[16:]) + decryptor.finalize()

    async def close(self):
        if self.udp:
            self.udp.close()
            await asyncio.wait_for(asyncio.shield(self.inbox.closed), 2)
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
