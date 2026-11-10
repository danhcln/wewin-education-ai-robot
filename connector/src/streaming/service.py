"""Bounded authenticated UDP sender. Only an authenticated ESP32 starts capture."""
from collections import deque
import json
import logging
from pathlib import Path
import secrets
import socket
import threading
import time
from uuid import uuid4

from src.media.audio_endpoint import lan_ipv4, select_lan_address
from .authority import sign
from .capture import CapturePipeline, loopback_devices
from .protocol import encode, authenticate, verify, DATA, END, STOP, HEARTBEAT, HELLO, STATE

log=logging.getLogger('WEWIN_STREAM')


class StreamError(Exception):
    def __init__(self,code):self.code=code


class LiveService:
    def __init__(self,key_file=None,address_provider=select_lan_address,capture_factory=CapturePipeline,*,_host_test=False):
        self.key_file=Path(key_file or Path(__file__).resolve().parents[2]/'.secrets/audio-signing/private.pem')
        self.address_provider,self.capture_factory=address_provider,capture_factory
        self.lock=threading.RLock();self.session=None;self.server=None;self.thread=None;self.generation=0
        self._host_test=_host_test

    def devices(self):
        try:return {'status':'ok','capture_method':'WASAPI_SYSTEM_RENDER_LOOPBACK','devices':loopback_devices(),
                    'microphone_capture':False,'process_specific':False,'silent_routing_verified':False}
        except (ImportError,OSError):return {'status':'capture_dependency_missing','devices':[],'silent_routing_verified':False}

    def status(self):
        with self.lock:
            s=self.session
            if not s:return {'status':'ok','state':'IDLE','hardware_audio_verified':False,'pause_resume_supported':False,'transport_active':False}
            return {k:s[k] for k in ('session_id','generation','state','packets_sent','packets_dropped','capture_frames',
                    'capture_pcm_dropped','error','device_report','created_at')}|{'status':'ok','hardware_audio_verified':False,
                    'pause_resume_supported':False,'silent_routing_verified':False,'source':'WASAPI_RENDER_LOOPBACK','transport_active':self.server is not None}

    def start(self,*,endpoint,peer_ipv4,port=8766,allow_system_mix=False,local_output_routed_away=False, source_factory=None):
        if type(endpoint) is not int or endpoint<0 or type(port) is not int or not 1024<=port<=65535:
            raise StreamError('invalid_capture_or_port')
        if source_factory is None and not allow_system_mix:raise StreamError('system_mix_consent_required')
        if source_factory is None and not local_output_routed_away:raise StreamError('silent_local_route_required')
        try:peer,bind=lan_ipv4(peer_ipv4),lan_ipv4(self.address_provider())
        except (ValueError,TypeError):raise StreamError('current_lan_address_required') from None
        with self.lock:
            if self.server is not None:raise StreamError('stream_already_active')
            self.generation+=1
            sid,token=uuid4().hex,secrets.token_hex(32)
            d=dict(session_id=sid,generation=self.generation,stream_url=f'udp://{bind}:{port}/wewin-stream/live',
                   token=token,expires_at=int(time.time())+300)
            try:descriptor=sign(d,self.key_file)
            except (OSError,ValueError):raise StreamError('stream_signing_not_ready') from None
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            try:sock.bind(('127.0.0.1',0) if self._host_test else (bind,port));sock.settimeout(.01)
            except OSError:sock.close();raise StreamError('lan_port_unavailable') from None
            s=dict(source_factory=source_factory,session_id=sid,generation=self.generation,token=token,expires_at=d['expires_at'],peer=peer,endpoint=endpoint,
                   state='CONNECTING',created_at=time.time(),packets_sent=0,packets_dropped=0,capture_frames=0,
                   capture_pcm_dropped=0,error=None,device_report=None,queue=deque(maxlen=10),closed=threading.Event(),
                   control=STOP,sequence=0,ending=threading.Event(),created_mono=time.monotonic(),owner_deadline=time.monotonic()+8)
            self.session,self.server=s,sock
            self.thread=threading.Thread(target=self._run,args=(sock,s),daemon=True,name='wewin-stream-udp');self.thread.start()
            log.info('WEWIN_STREAM session_created generation=%d',s['generation'])
            return {**self.status(),'descriptor':descriptor,'instruction':'Pass unchanged to self.wewin_stream.start on ESP32. Capture begins only after authenticated HELLO. Keep descriptor private.'}

    def _run(self,sock,s):
        pipeline=None;remote=None;last_seen=time.monotonic();last_heartbeat=0.;last_status_stamp=-1
        def packet(payload):
            with self.lock:
                if s['closed'].is_set() and not s['ending'].is_set():return
                if len(s['queue'])==10:s['packets_dropped']+=1
                s['queue'].append((s['sequence'],payload));s['sequence']+=1
        def send(kind,payload=b'',seq=None):
            number=s['sequence'] if seq is None else seq
            stamp=int((time.monotonic()-s['created_mono'])*1000)+1 if kind==HEARTBEAT else number*20
            sock.sendto(authenticate(encode(s['session_id'],s['generation'],number,stamp,payload,kind),s['token']),remote)
        def receive():
            raw,peer=sock.recvfrom(1501)
            expected_peer='127.0.0.1' if self._host_test else s['peer']
            if peer[0]!=expected_peer or (remote is not None and peer!=remote):return None,None
            try:frame=verify(raw,s['token'])
            except ValueError:return None,None
            if frame['session_id']!=s['session_id'] or frame['generation']!=s['generation']:return None,None
            return frame,peer
        try:
            while not s['closed'].is_set() and not s['ending'].is_set():
                try:frame,peer=receive()
                except socket.timeout:frame=peer=None
                if frame:
                    if remote is None and frame['kind']==HELLO:
                        if time.time()>=s['expires_at']:raise StreamError('admission_expired')
                        remote=peer
                        log.info('WEWIN_STREAM hello_received')
                        last_seen=time.monotonic()
                        pipeline=(s['source_factory'](packet) if s['source_factory'] else self.capture_factory(s['endpoint'],packet));pipeline.start()
                        s['state']='BUFFERING';log.info('WEWIN_STREAM capture_started encoder_started generation=%d',s['generation'])
                        send(HEARTBEAT)
                    elif remote is not None and frame['kind']==STATE:
                        if frame['timestamp_ms']<=last_status_stamp:continue
                        last_status_stamp=frame['timestamp_ms'];last_seen=time.monotonic()
                        report=json.loads(frame['payload'])
                        if report.get('state') not in ('BUFFERING','PLAYING','STOPPING','IDLE','ERROR'):raise StreamError('invalid_device_status')
                        s['device_report']={k:v for k,v in report.items() if k in ('state','packets_received','packets_dropped','packets_late','buffer_depth','output_frames','position_ms','expected_sequence','last_packet_time','underflows') and (isinstance(v,str) and v in ('BUFFERING','PLAYING','STOPPING','IDLE','ERROR') or type(v) is int and 0<=v<=0x7fffffffffffffff)}
                        if report['state']=='PLAYING' and s['state']!='PLAYING' and s['packets_sent']>0 and report.get('output_frames',0)>0:log.info('WEWIN_STREAM playing')
                        s['state']=report['state']
                        if report['state'] in ('ERROR','IDLE'):s['closed'].set()
                if time.monotonic()>s['owner_deadline']:
                    s['control']=STOP;s['closed'].set()
                if remote is None:
                    if time.time()>=s['expires_at']:raise StreamError('admission_expired')
                    continue
                payload=None
                with self.lock:
                    if s['queue']:payload=s['queue'].popleft()
                if payload is not None:
                    send(DATA,payload[1],payload[0]);s['packets_sent']+=1
                    if s['packets_sent']==1:log.info('WEWIN_STREAM packet_flow')
                if time.monotonic()-last_heartbeat>=1:send(HEARTBEAT);last_heartbeat=time.monotonic()
                s['capture_frames']=pipeline.frames_captured;s['capture_pcm_dropped']=pipeline.pcm_dropped
                if pipeline.error:raise StreamError('capture_encoder_failed')
                if getattr(pipeline, 'eof', None) is not None and pipeline.eof.is_set():
                    s['control']=END;s['ending'].set()
                if time.monotonic()-last_seen>5:raise StreamError('device_liveness_timeout')
            if pipeline:pipeline.stop(graceful=s['ending'].is_set());pipeline=None
            if s['ending'].is_set() and remote:
                with self.lock:
                    tail=list(s['queue']);s['queue'].clear()
                for seq,payload in tail:send(DATA,payload,seq);s['packets_sent']+=1
            else:
                with self.lock:s['queue'].clear()
            if remote:
                until=time.monotonic()+3
                while time.monotonic()<until:
                    send(s['control'])
                    try:frame,_=receive()
                    except socket.timeout:frame=None
                    if frame and frame['kind']==STATE and json.loads(frame['payload']).get('state')=='IDLE':
                        s['device_report']={'state':'IDLE'};break
                    time.sleep(.02)
        except Exception as error:
            s['error']=error.code if isinstance(error,StreamError) else 'stream_transport_or_capture_failed';s['state']='ERROR'
            if pipeline:pipeline.stop();pipeline=None
            if remote:
                for _ in range(3):
                    try:send(STOP)
                    except OSError:break
                    time.sleep(.02)
            log.warning('WEWIN_STREAM session_error generation=%d',s['generation'])
        finally:
            if pipeline:pipeline.stop()
            s['closed'].set();s['queue'].clear();sock.close()
            if not s['error']:
                s['state']='IDLE' if remote is None or (s.get('device_report') or {}).get('state')=='IDLE' else 'ERROR'
                if s['state']=='ERROR':s['error']='device_close_not_confirmed'
            with self.lock:
                if self.server is sock:self.server=None
            if s['state']=='IDLE':log.info('WEWIN_STREAM idle')
            log.info('WEWIN_STREAM capture_stopped session_closed generation=%d',s['generation'])

    def stop(self,graceful=False):
        with self.lock:
            if self.session and self.server is not None:
                self.session['control']=END if graceful else STOP
                self.session['state']='STOPPING'
                if graceful:self.session['ending'].set()
                else:self.session['closed'].set();self.session['queue'].clear()
        return self.status()

    def heartbeat(self):
        with self.lock:
            if self.session and self.server is not None:self.session['owner_deadline']=time.monotonic()+8
        return self.status()


_service=LiveService()
def get_service():return _service
