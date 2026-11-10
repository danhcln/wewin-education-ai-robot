"""PC-only real-time owned-fixture -> Opus -> WWS1 loopback -> offline decoder.

Receiver status is simulated; never a claim of ESP32, I2S or DODO validation.
No external listener, production credentials, serial device, or audio output.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from src.streaming.service import LiveService
from src.streaming.asset_source import AssetSource
from src.streaming.protocol import encode,authenticate,verify,HELLO,STATE,DATA,END


def ogg_page(packet,sequence,granule,flags=0):
    lacing=bytes([255]*(len(packet)//255)+[len(packet)%255])
    page=bytearray(b'OggS'+bytes([0,flags])+struct.pack('<QIII',granule,1,sequence,0)+bytes([len(lacing)])+lacing+packet)
    crc=0
    for b in page:
        crc^=b<<24
        for _ in range(8):crc=((crc<<1)^0x04c11db7 if crc&0x80000000 else crc<<1)&0xffffffff
    page[22:26]=struct.pack('<I',crc)
    return page


def run(asset,ffmpeg,output,duration):
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        key=ec.generate_private_key(ec.SECP256R1())
        authority=root/'test-key.pem'
        authority.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        source=root/'repeated-approved-fixture.ogg'
        subprocess.run([ffmpeg,'-nostdin','-loglevel','error','-stream_loop','-1','-i',str(asset),'-t',str(duration),'-ac','1','-ar','24000','-c:a','libopus','-b:a','32k','-frame_duration','20',str(source)],check=True,timeout=60)
        service=LiveService(authority,lambda:'10.20.30.40',_host_test=True)
        sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.settimeout(.05)
        result=service.start(endpoint=0,peer_ipv4='10.20.30.41',source_factory=lambda cb:AssetSource(source,cb))
        descriptor=result['descriptor'];target=service.server.getsockname();packets=[]
        def state(name):
            payload=json.dumps({'state':name,'output_frames':len(packets),'position_ms':len(packets)*20}).encode()
            sock.sendto(authenticate(encode(descriptor['session_id'],descriptor['generation'],0,int(time.monotonic()*1000),payload,STATE),descriptor['token']),target)
        start=time.monotonic();last_status=0;ended=False
        try:
            sock.sendto(authenticate(encode(descriptor['session_id'],descriptor['generation'],0,0,kind=HELLO),descriptor['token']),target)
            while time.monotonic()-start<duration+20:
                now=time.monotonic()
                if now-last_status>.2:state('PLAYING');service.heartbeat();last_status=now
                try:frame=verify(sock.recvfrom(1500)[0],descriptor['token'])
                except socket.timeout:continue
                if frame['kind']==DATA:
                    if frame['sequence']!=len(packets):raise AssertionError('packet gap/replay')
                    packets.append(frame['payload'])
                elif frame['kind']==END:
                    state('IDLE');ended=True;break
            service.thread.join(timeout=5)
            assert ended and service.status()['state']=='IDLE'
            assert service.status()['packets_dropped']==0
            assert duration*50<=len(packets)<=duration*50+4
            captured=root/'received.ogg'
            with captured.open('wb') as out:
                out.write(ogg_page(b'OpusHead'+bytes([1,1])+struct.pack('<HIhB',0,24000,0,0),0,0,2))
                out.write(ogg_page(b'OpusTags'+struct.pack('<II',0,0),1,0))
                for n,p in enumerate(packets):out.write(ogg_page(p,n+2,(n+1)*960,4 if n==len(packets)-1 else 0))
            decoded=subprocess.run([ffmpeg,'-nostdin','-loglevel','error','-i',str(captured),'-ac','1','-ar','24000','-f','s16le','pipe:1'],capture_output=True,check=True,timeout=60).stdout
            seconds=len(decoded)/48000
            assert duration-.1<=seconds<=duration+.2 and any(decoded)
            answer={'status':'PASS','duration_requested':duration,'wall_seconds':round(time.monotonic()-start,2),'packets':len(packets),'decoded_seconds':seconds,'drops':0,'hardware_tested':False,'receiver_status':'simulated','source':'repeated authorized fixture, no real YouTube mapping'}
            output.write_text(json.dumps(answer,indent=2),encoding='utf-8')
            print(json.dumps(answer),flush=True)
        finally:
            service.stop();sock.close()
            service.thread.join(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset',type=Path,required=True)
    parser.add_argument('--ffmpeg',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    os.environ['WEWIN_STREAM_FFMPEG']=args.ffmpeg
    args.output.mkdir(parents=True,exist_ok=True)
    for duration in (60,300):run(args.asset,args.ffmpeg,args.output/f'audio-{duration}s.json',duration)
