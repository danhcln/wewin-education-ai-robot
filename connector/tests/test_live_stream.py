import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,utils
from src.streaming.protocol import encode,decode,authenticate,verify,DATA,END,STOP,HELLO,STATE
from src.streaming.authority import canonical,sign
from src.streaming.service import LiveService,StreamError
from src.streaming.capture import encoder_command,ogg_packets,CapturePipeline

SID='a'*32;TOKEN='b'*64


class FakeCapture:
    calls=0
    def __init__(self,endpoint,on_packet):
        self.frames_captured=4800;self.pcm_dropped=0;self.error=None;self.on_packet=on_packet
    def start(self):
        FakeCapture.calls+=1
        for _ in range(20):self.on_packet(b'\xd8\x00')
    def stop(self,graceful=False):pass


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.private=ec.generate_private_key(ec.SECP256R1());self.key=self.root/'key.pem'
        self.key.write_bytes(self.private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.d=dict(session_id=SID,generation=4,stream_url='udp://10.20.30.40:8766/wewin-stream/live',token=TOKEN,expires_at=int(time.time())+250)
    def tearDown(self):self.temp.cleanup()
    def test_01_binary_roundtrip(self):
        frame=decode(encode(SID,4,17,340,b'\xd8\x00'));self.assertEqual(frame['sequence'],17);self.assertEqual(frame['timestamp_ms'],340)
    def test_02_hmac_authentication(self):
        signed=authenticate(encode(SID,4,0,0,b'\xd8\x00'),TOKEN)
        self.assertEqual(verify(signed,TOKEN)['generation'],4)
        for bad in (signed[:-1],signed[:-1]+bytes([signed[-1]^1]),b'x'*1500):
            with self.assertRaises(ValueError):verify(bad,TOKEN)
        with self.assertRaises(ValueError):verify(signed,'c'*64)
    def test_03_no_json_audio_or_arbitrary_size(self):
        for data in (b'',b'x'*1276):
            with self.assertRaises(ValueError):encode(SID,4,0,0,data)
    def test_04_domain_separated_signature(self):
        d=sign(self.d,self.key);raw=bytes.fromhex(d.pop('signature'));sig=utils.encode_dss_signature(int.from_bytes(raw[:32]),int.from_bytes(raw[32:]));self.private.public_key().verify(sig,canonical(d),ec.ECDSA(hashes.SHA256()))
        changed={**d,'generation':5}
        with self.assertRaises(Exception):self.private.public_key().verify(sig,canonical(changed),ec.ECDSA(hashes.SHA256()))
        self.assertTrue(canonical(d).startswith(b'wewin-stream-v1\n'))
    def test_05_origin_allowlist(self):
        for url in ('file:///secret','udp://127.0.0.1:8766/wewin-stream/live','udp://169.254.169.254:8766/wewin-stream/live','udp://10.20.30.40:80/wewin-stream/live','udp://10.20.30.40:8766/.env','udp://10.20.30.40:8766/wewin-stream/live?token=x','ws://10.20.30.40:8766/wewin-stream/live'):
            with self.assertRaises(ValueError):canonical({**self.d,'stream_url':url})
    def test_06_expiry_and_clock(self):
        for now in (0,self.d['expires_at'],self.d['expires_at']-301):
            with self.assertRaises(ValueError):canonical(self.d,now)
    def test_07_explicit_capture_and_routing_gate(self):
        service=LiveService(self.key,lambda:'10.20.30.40',FakeCapture,_host_test=True)
        for kwargs in ({},{'allow_system_mix':True}):
            with self.assertRaises(StreamError):service.start(endpoint=0,peer_ipv4='10.20.30.41',**kwargs)
        self.assertIsNone(service.server);self.assertEqual(FakeCapture.calls,0)
    def test_08_real_udp_loopback_auth_stop_and_no_replay(self):
        FakeCapture.calls=0
        service=LiveService(self.key,lambda:'10.20.30.40',FakeCapture,_host_test=True)
        result=service.start(endpoint=0,peer_ipv4='10.20.30.41',allow_system_mix=True,local_output_routed_away=True)
        descriptor=result['descriptor'];target=service.server.getsockname()
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.settimeout(.2)
        try:
            sock.sendto(authenticate(encode(descriptor['session_id'],descriptor['generation'],0,1,kind=HELLO),'f'*64),target)
            time.sleep(.05);self.assertEqual(FakeCapture.calls,0)
            sock.sendto(authenticate(encode(descriptor['session_id'],descriptor['generation'],0,1,kind=HELLO),descriptor['token']),target)
            deadline=time.monotonic()+2;received=[]
            while time.monotonic()<deadline and not received:
                raw,_=sock.recvfrom(1500);frame=verify(raw,descriptor['token'])
                if frame['kind']==DATA:received.append(frame)
            self.assertTrue(received);self.assertEqual(FakeCapture.calls,1)
            self.assertLessEqual(len(service.session['queue']),10)
            self.assertNotIn(descriptor['token'],json.dumps(service.status()))
            self.assertEqual(service.status()['state'],'BUFFERING') # Sending does not prove output.
            service.stop()
            deadline=time.monotonic()+2;stopped=False
            while time.monotonic()<deadline:
                raw,_=sock.recvfrom(1500);frame=verify(raw,descriptor['token'])
                if frame['kind']==STOP:
                    stopped=True
                    ack=encode(descriptor['session_id'],descriptor['generation'],0,1000,b'{"state":"IDLE"}',STATE)
                    sock.sendto(authenticate(ack,descriptor['token']),target);break
            self.assertTrue(stopped);service.thread.join(timeout=4);self.assertIsNone(service.server);self.assertEqual(service.status()['state'],'IDLE')
            service.stop();self.assertEqual(service.status()['state'],'IDLE')
            self.assertGreater(service.status()['packets_dropped'],0)
        finally:
            service.stop();sock.close()
            if service.thread:service.thread.join(timeout=4)
    def test_09_encoder_never_accepts_a_media_url(self):
        cmd=encoder_command('ffmpeg',48000,2);self.assertEqual(cmd[cmd.index('-i')+1],'pipe:0');self.assertIn('24000',cmd);self.assertIn('20',cmd);self.assertIn('32k',cmd)
    def test_10_loopback_only_no_microphone(self):
        # Validate before a subprocess or capture stream can start.
        class Audio:
            def get_device_info_by_index(self,index):return dict(hostApi=0,isLoopbackDevice=False)
            def get_host_api_info_by_index(self,index):return dict(type=1)
            def terminate(self):pass
        import types,sys
        fake=types.SimpleNamespace(PyAudio=Audio,paWASAPI=1)
        with patch.dict(sys.modules,{'pyaudiowpatch':fake}):
            with self.assertRaises(ValueError):CapturePipeline(0,lambda p:None,ffmpeg='not-called').start()
    def test_11_stream_status_has_no_authority(self):
        service=LiveService();status=service.status();self.assertFalse(status['hardware_audio_verified']);self.assertFalse(status['pause_resume_supported']);self.assertNotIn('token',status)
    def test_12_real_ffmpeg_realtime_packets(self):
        ffmpeg=os.environ.get('WEWIN_STREAM_FFMPEG')
        if not ffmpeg:self.skipTest('Explicit FFmpeg path required for offline encoder test')
        pcm=b'\0'*(48000*2*4) # One second of synthetic PCM, not browser acceptance.
        run=subprocess.run(encoder_command(ffmpeg,48000,2),input=pcm,capture_output=True,timeout=15)
        self.assertEqual(run.returncode,0)
        packets=list(ogg_packets(io.BytesIO(run.stdout)));self.assertGreaterEqual(len(packets),50)
        self.assertTrue(all(0<len(p)<=1275 for p in packets))
        self.assertGreater(sum(len(p) for p in packets),3000)
    def test_13_framing_rejects_truncated_encoder_output(self):
        with self.assertRaises(ValueError):list(ogg_packets(io.BytesIO(b'OggS')))


if __name__=='__main__':unittest.main()
