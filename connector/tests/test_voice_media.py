"""Phase 2: real host cryptography + deterministic orchestration adapters, no production I/O."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from src.media import control_crypto as crypto
from src.media.device_control import DeviceControl
from src.media.intent import intent
from src.media.resolver import MediaResolver
from src.media.orchestration import MediaSession

A = dict(video_id='2_IweGD2uM4', title='Thánh Gióng | The Legend of Saint Giong | WEWIN STORYLAND',
         is_wewin=True, embeddable=True, url='https://www.youtube.com/watch?v=2_IweGD2uM4', channel_title='WeWIN Education')
B = dict(A, video_id='AbCdEf01234', title='Con Rồng Cháu Tiên | Dragon and Fairy | WEWIN STORYLAND')


class YouTube:
    def __init__(self, videos=None): self.videos = videos if videos is not None else [A, B]
    def search(self, query, scope, limit): return {'videos': self.videos}
    def video(self, vid): return next(v for v in self.videos if v['video_id'] == vid)


class ResolverTests(unittest.TestCase):
    def test_vietnamese_alias(self):
        x = MediaResolver(YouTube()).resolve('Thánh Gióng'); self.assertEqual(x['youtube_video_id'], A['video_id']); self.assertEqual(x['match_type'], 'alias')
    def test_exact_normalized_title(self):
        self.assertEqual(MediaResolver(YouTube()).resolve(A['title'].upper())['match_type'], 'exact')
    def test_english_alias(self):
        self.assertEqual(MediaResolver(YouTube()).resolve('The Legend of Saint Giong')['youtube_video_id'], A['video_id'])
    def test_whole_catalog_not_single_title(self):
        self.assertEqual(MediaResolver(YouTube()).resolve('Con Rồng Cháu Tiên')['youtube_video_id'], B['video_id'])
    def test_strong_fuzzy(self): self.assertEqual(MediaResolver(YouTube()).resolve('Thánh Gión')['match_type'], 'fuzzy')
    def test_low_confidence_no_fallback(self): self.assertEqual(MediaResolver(YouTube()).resolve('không có tên này')['status'], 'ambiguous')
    def test_duplicate_title_ambiguous(self): self.assertEqual(MediaResolver(YouTube([A, dict(A, video_id=B['video_id'])])).resolve('Thánh Gióng')['status'], 'ambiguous')
    def test_wrong_channel_never_selected(self): self.assertEqual(MediaResolver(YouTube([dict(A, is_wewin=False)])).resolve('Thánh Gióng')['status'], 'ambiguous')
    def test_unavailable_excluded(self): self.assertEqual(MediaResolver(YouTube([dict(A, embeddable=False)])).resolve('Thánh Gióng')['status'], 'ambiguous')
    def test_contextual_commands(self):
        for text, action in [('Ngừng','pause'),('Tạm dừng','pause'),('Dừng lại một chút','pause'),('Tiếp tục','resume'),('Phát tiếp','resume'),('Tắt video','stop'),('Đóng video','stop'),('Dừng video','stop'),('Video đang phát gì?','status')]:
            with self.subTest(text=text): self.assertEqual(intent(text, True)['action'], action)
        self.assertEqual(intent('Ngừng',False)['action'],'no_media_context')
    def test_play_replace_routing(self):
        for text in ('Bật video Thánh Gióng của WeWIN','Phát video Thánh Gióng','Mở video Thánh Gióng','Cho tôi xem video Thánh Gióng của WeWIN'):
            self.assertEqual(intent(text,False), {'action':'play','query':'thanh giong'})
        self.assertEqual(intent('Chuyển sang video Con Rồng Cháu Tiên',True)['action'],'replace')


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.signing=ec.generate_private_key(ec.SECP256R1()); self.key=self.root/'authority.pem'
        self.key.write_bytes(self.signing.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.device=ec.generate_private_key(ec.SECP256R1()); self.pub=self.device.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint).hex()
        self.h={'type':'hello','device_id':'a'*32,'public_key':self.pub,'nonce':'b'*32}
        self.control=DeviceControl(self.root/'state',self.key,lambda:'10.20.30.40'); self.control.config['enabled']=True
        self.control.origin='udp://10.20.30.40:8767/wewin-control'
        from src.devices.store import DeviceStore
        from src.devices.registry import RobotRegistry
        from src.devices.enrollment import EnrollmentEngine
        self.registry=RobotRegistry(DeviceStore(self.root/'registry.sqlite3'))
        self.enrollment=EnrollmentEngine(self.registry,self.registry.store)
        registry_patch=patch('src.devices.registry.get_robot_registry',return_value=self.registry)
        registry_patch.start();self.addCleanup(registry_patch.stop)

    def pair(self):
        self.control.receive(json.dumps(self.h).encode(),('10.20.30.41',5678))
        from tests.test_devices_auth import physical_signature
        fp=crypto.fingerprint(self.pub)
        ch=self.enrollment.create_challenge('default-site','local-admin',self.h['device_id'],fp,self.pub)
        self.enrollment.confirm_challenge(ch['challenge_id'],'local-admin',ch['display_code'],
            device_signature=physical_signature(self.device,ch['challenge_id'],ch['display_code'],self.h['device_id'],fp))
        self.control.approve(self.h['device_id'],crypto.fingerprint(self.pub))
        a=json.loads(self.control.receive(json.dumps(self.h).encode(),('10.20.30.41',5678)))
        peer=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),bytes.fromhex(a['server_key']))
        key=HKDF(hashes.SHA256(),32,bytes.fromhex(self.h['nonce']),crypto.canonical(a)).derive(self.device.exchange(ec.ECDH(),peer))
        return a,key
    def test_discovery_not_auto_approved(self):
        self.assertIsNone(self.control.receive(json.dumps(self.h).encode(),('10.20.30.41',5678)))
        self.assertFalse(self.control.leases)
    def test_wrong_fingerprint_rejected(self):
        self.control.receive(json.dumps(self.h).encode(),('10.20.30.41',5678))
        with self.assertRaises(ValueError):self.control.approve(self.h['device_id'],'c'*64)
    def test_signed_ecdh_and_directional_aead(self):
        a,key=self.pair(); raw=bytes.fromhex(a['signature']); sig=utils.encode_dss_signature(int.from_bytes(raw[:32]),int.from_bytes(raw[32:]))
        self.signing.public_key().verify(sig,crypto.canonical(a),ec.ECDSA(hashes.SHA256()))
        sid=a['lease_id']; packet=crypto.encrypt(key,sid,1,0,{'type':'presence','stream':{'state':'IDLE'}})
        reply=self.control.receive(packet,('10.20.30.41',5678));self.assertEqual(crypto.decrypt(key,sid,0,1,reply)[1]['type'],'state')
        self.assertEqual(self.control.device()['ip'],'10.20.30.41')
    def test_volume_control_and_presence(self):
        a,key=self.pair()
        packet=crypto.encrypt(key,a['lease_id'],1,0,{'type':'presence','volume':65,'stream':{'state':'IDLE'}})
        self.control.receive(packet,('10.20.30.41',5678))
        self.assertEqual(self.control.device()['volume'], 65)
        self.assertFalse(self.control.device()['muted'])
        self.control.set_volume(30)
        self.assertEqual(self.control.device()['volume'], 30)
        self.control.set_volume(70)
        self.assertEqual(self.control.device()['volume'], 70)
        self.control.mute()
        self.assertEqual(self.control.device()['volume'], 0)
        self.assertTrue(self.control.device()['muted'])
        self.control.unmute()
        self.assertEqual(self.control.device()['volume'], 70)
        self.assertFalse(self.control.device()['muted'])
    def test_presence_ip_only_after_auth_and_dhcp_update(self):
        a,key=self.pair()
        with self.assertRaises(ValueError):self.control.device()
        for seq,ip in [(1,'10.20.30.41'),(2,'10.20.30.42')]:
            self.control.receive(crypto.encrypt(key,a['lease_id'],seq,0,{'type':'presence'}),(ip,5678))
        self.assertEqual(self.control.device()['ip'],'10.20.30.42')
    def test_replay_does_not_update_presence(self):
        a,key=self.pair();p=crypto.encrypt(key,a['lease_id'],1,0,{'type':'presence'});self.control.receive(p,('10.20.30.41',5678))
        with self.assertRaises(ValueError):self.control.receive(p,('10.20.30.42',5678))
        self.assertEqual(self.control.device()['ip'],'10.20.30.41')
    def test_tamper_wrong_key_direction_lease(self):
        a,key=self.pair();p=crypto.encrypt(key,a['lease_id'],1,0,{'descriptor':'private-capability'})
        self.assertNotIn(b'private-capability',p)
        for raw,k,lease,direction in [(p[:-1]+bytes([p[-1]^1]),key,a['lease_id'],0),(p,b'\0'*32,a['lease_id'],0),(p,key,'f'*32,0),(p,key,a['lease_id'],1)]:
            with self.assertRaises(Exception):crypto.decrypt(k,lease,0,direction,raw)
    def test_control_bounded(self):
        a,key=self.pair()
        with self.assertRaises(ValueError):crypto.encrypt(key,a['lease_id'],1,1,{'x':'a'*1100})
        with self.assertRaises(ValueError):crypto.decrypt(key,a['lease_id'],0,0,b'x'*2000)
    def test_public_ip_refused(self):
        with self.assertRaises(ValueError):self.control.receive(json.dumps(self.h).encode(),('8.8.8.8',5678))
    def test_pending_bounded_and_malformed_rejected(self):
        for n in range(15):self.control.receive(json.dumps({**self.h,'device_id':f'{n:032x}'}).encode(),('10.20.30.41',5678))
        self.assertLessEqual(len(self.control.pending),8)
        with self.assertRaises(ValueError):crypto.hello({**self.h,'token':'bad'})
    def test_reboot_new_key_requires_reapproval(self):
        self.pair();new=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint).hex()
        self.assertIsNone(self.control.receive(json.dumps({**self.h,'public_key':new}).encode(),('10.20.30.41',5678)))
    def test_status_and_saved_config_no_secret(self):
        a,key=self.pair();public=json.dumps(self.control.status())+(self.root/'state/settings.json').read_text()
        for secret in (key.hex(),a['signature'],a['server_key']):self.assertNotIn(secret,public)
    def test_unauthenticated_hello_cannot_revoke_live_lease(self):
        a,key=self.pair();self.control.receive(crypto.encrypt(key,a['lease_id'],1,0,{'type':'presence'}),('10.20.30.41',5678))
        self.control.receive(json.dumps({**self.h,'nonce':'c'*32}).encode(),('10.20.30.99',9999))
        self.assertTrue(self.control.device()['online']);self.assertEqual(self.control.device()['ip'],'10.20.30.41')
    def test_stale_discovery_not_approved(self):
        self.control.receive(json.dumps(self.h).encode(),('10.20.30.41',5678));self.control.pending[self.h['device_id']]['seen']-=31
        with self.assertRaises(ValueError):self.control.approve(self.h['device_id'],crypto.fingerprint(self.pub))


class Browser:
    def __init__(self,events):self.events=events;self.connected=True;self.state='PLAYER_READY';self.selected=None;self.confirm=True
    def status(self,*args):return dict(connected=self.connected,state=self.state,selected_video=self.selected)
    def command(self,owner,args,youtube,**kwargs):
        action=args['action'];self.events.append('browser:'+action)
        if not self.confirm:return {'status':'command_pending','state':self.state}
        if action=='select':self.selected=youtube.video(args['video_id'])
        self.state={'select':'VIDEO_SELECTED','play':'PLAYING','resume':'PLAYING','pause':'PAUSED','stop':'STOPPED'}[action]
        self.events.append('ack:'+self.state);return {'status':'command_confirmed','state':self.state}
class Stream:
    def __init__(self,events):self.events=events;self.state='IDLE';self.starts=0;self.owner=False
    def stop(self,graceful=False):self.events.append('stream:END' if graceful else 'stream:STOP');self.state='IDLE'
    def start(self,**kwargs):self.events.append('stream:prepare');self.starts+=1;self.state='CONNECTING';return {'descriptor':{'test':'private'}}
    def status(self):return {'state':self.state,'device_report':{'output_frames':1 if self.state=='PLAYING' else 0}}
    def heartbeat(self):pass
class Control:
    def __init__(self,stream,events):
        self.stream=stream;self.events=events;self.online=True;self.file=False;self.ack=None;self.gens=[]
        self.config=dict(capture_name='loopback',system_mix_consent=True,local_route_confirmed=True,default_device='a'*32)
        self.volume=70;self.muted=False;self.pre_mute_volume=70
    def device(self):
        if not self.online:raise ValueError('device_unavailable')
        return {'device_id':'a'*32,'ip':'10.20.30.41','stream':{'state':self.stream.state,'worker_running':self.stream.state=='PLAYING'},'file_active':self.file,'ack':self.ack,'volume':self.volume,'muted':self.muted}
    def send(self,op,generation,descriptor=None,value=None):
        self.events.append('device:'+op);self.gens.append(generation);self.ack=uuid4().hex
        if op=='start':self.stream.state='PLAYING'
        elif op in ('stop','end'):self.stream.state='IDLE'
        return self.ack
    def set_volume(self,val,generation=0):
        self.volume=max(0,min(100,int(val)));self.muted=(self.volume==0)
        if self.volume>0:self.pre_mute_volume=self.volume
        return self.send('set_volume',generation,value=self.volume)
    def mute(self,generation=0):
        if self.volume>0:self.pre_mute_volume=self.volume
        self.volume=0;self.muted=True
        return self.send('mute',generation,value=0)
    def unmute(self,val=None,generation=0):
        self.volume=val if val and val>0 else self.pre_mute_volume
        self.muted=False
        return self.send('unmute',generation,value=self.volume)


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        from src.media.orchestration import owner
        owner()  # Resolve app import before timing asynchronous jobs, no lifespan/DB startup.
        self.events=[];self.browser=Browser(self.events);self.stream=Stream(self.events);self.control=Control(self.stream,self.events)
        self.session=MediaSession(self.browser,YouTube(),self.stream,self.control,lambda:[{'name':'loopback','index':0}]);self.addCleanup(self.session.shutdown)
    def run_action(self,action,**kwargs):
        receipt=self.session.submit(dict(action=action,request_id=uuid4().hex,**kwargs));gen=receipt['generation'];until=time.monotonic()+3
        while time.monotonic()<until:
            s=self.session.status()
            if s['generation']==gen and s['state'] in ('PLAYING','PAUSED','IDLE','ENDED','ERROR'):return s
            time.sleep(.01)
        self.fail('job did not settle')
    def test_voice_play_waits_browser_ack_then_native_start(self):
        s=self.run_action('command',utterance='Bật video Thánh Gióng của WeWIN');self.assertEqual(s['state'],'PLAYING');self.assertEqual(s['video_id'],A['video_id'])
        self.assertLess(self.events.index('ack:VIDEO_SELECTED'),self.events.index('stream:prepare'));self.assertLess(self.events.index('stream:prepare'),self.events.index('device:start'));self.assertLess(self.events.index('device:start'),self.events.index('ack:PLAYING'));self.assertFalse(s['hardware_audio_verified'])
    def test_pause_resume_no_stale_generation(self):
        old=self.run_action('play',query='Thánh Gióng');paused=self.run_action('command',utterance='Ngừng');self.assertEqual(paused['state'],'PAUSED')
        new=self.run_action('command',utterance='Tiếp tục');self.assertEqual(new['state'],'PLAYING');self.assertGreater(new['generation'],old['generation']);self.assertEqual(self.stream.starts,2)
    def test_replace_clean_order(self):
        self.run_action('play',query='Thánh Gióng');self.events.clear();s=self.run_action('replace',query='Con Rồng Cháu Tiên')
        self.assertEqual(s['video_id'],B['video_id']);self.assertLess(self.events.index('device:stop'),self.events.index('browser:select'))
    def test_stop_idempotent(self):
        self.run_action('play',query='Thánh Gióng');self.assertEqual(self.run_action('stop')['state'],'IDLE');self.assertEqual(self.run_action('stop')['state'],'IDLE')
    def test_ended_sends_end_not_replay(self):
        self.run_action('play',query='Thánh Gióng');self.events.clear();self.assertEqual(self.run_action('ended')['state'],'ENDED');self.assertIn('stream:END',self.events);self.assertNotIn('stream:STOP',self.events);self.assertNotIn('device:start',self.events)
    def test_browser_ended_event_automatically_drains(self):
        self.run_action('play',query='Thánh Gióng');self.events.clear();self.browser.state='ENDED';until=time.monotonic()+2
        while time.monotonic()<until and self.session.status()['state']!='ENDED':time.sleep(.01)
        self.assertEqual(self.session.status()['state'],'ENDED');self.assertIn('stream:END',self.events);self.assertNotIn('stream:STOP',self.events)
    def test_device_unavailable_no_false_success(self):
        self.control.online=False;s=self.run_action('play',query='Thánh Gióng');self.assertEqual(s['state'],'ERROR');self.assertEqual(self.stream.starts,0)
    def test_browser_unavailable_no_stream(self):
        self.browser.connected=False;s=self.run_action('play',query='Thánh Gióng');self.assertEqual(s['last_error'],'browser_unavailable');self.assertEqual(self.stream.starts,0)
    def test_low_confidence_no_stream(self):
        s=self.run_action('play',query='một video không tồn tại');self.assertEqual(s['last_error'],'resolver_ambiguous');self.assertEqual(self.stream.starts,0)
    def test_browser_http_receipt_is_not_ack(self):
        self.browser.confirm=False;s=self.run_action('play',query='Thánh Gióng');self.assertEqual(s['state'],'ERROR');self.assertEqual(self.stream.starts,0)
    def test_file_owner_rejects_live(self):
        self.control.file=True;s=self.run_action('play',query='Thánh Gióng');self.assertEqual(s['last_error'],'file_owner_busy');self.assertEqual(self.stream.starts,0)
    def test_wake_interrupt_pauses_not_closes_and_allows_resume(self):
        self.run_action('play',query='Thánh Gióng');self.events.clear();self.assertEqual(self.run_action('interrupt')['state'],'PAUSED');self.assertIn('browser:pause',self.events);self.assertNotIn('browser:stop',self.events);self.assertEqual(self.run_action('resume')['state'],'PLAYING')
    def test_stop_cancels_slow_resolve_before_native_start(self):
        entered,release=threading.Event(),threading.Event();original=self.session.resolver.resolve
        def slow(*args):entered.set();release.wait(2);return original(*args)
        self.session.resolver.resolve=slow;self.session.submit({'action':'play','query':'Thánh Gióng','request_id':uuid4().hex});self.assertTrue(entered.wait(1));self.session.submit({'action':'stop','request_id':uuid4().hex});release.set()
        until=time.monotonic()+2
        while self.session.status()['state']!='IDLE' and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(self.stream.starts,0);self.assertEqual(self.session.status()['state'],'IDLE')
    def test_request_conflict_and_duplicates(self):
        body=dict(action='stop',request_id=uuid4().hex);self.session.submit(body);self.assertEqual(self.session.submit(body)['status'],'duplicate_request');self.assertEqual(self.session.submit({**body,'action':'pause'})['status'],'request_conflict')
    def test_nondefault_device_cannot_cancel_another_speaker(self):
        self.run_action('play',query='Thánh Gióng');before=self.session.status()['generation'];events=list(self.events)
        result=self.session.submit({'action':'stop','request_id':uuid4().hex},'b'*32)
        self.assertEqual(result['status'],'wrong_device');self.assertEqual(self.session.status()['generation'],before);self.assertEqual(self.events,events)
    def test_retry_after_error_requires_positive_owner_release(self):
        original=self.control.device
        def released():
            value=original();value['stream']={'state':'ERROR','worker_running':False,'owner_released':True};return value
        self.control.device=released;self.assertEqual(self.run_action('play',query='Thánh Gióng')['state'],'PLAYING')
    def test_unreleased_error_blocks_new_owner(self):
        original=self.control.device
        def unreleased():
            value=original();value['stream']={'state':'ERROR','worker_running':False,'owner_released':False};return value
        self.control.device=unreleased;s=self.run_action('play',query='Thánh Gióng');self.assertEqual(s['last_error'],'device_release_not_confirmed');self.assertEqual(self.stream.starts,0)
    def test_voice_volume_intents_do_not_disrupt_stream(self):
        self.run_action('play', query='Thánh Gióng')
        self.assertEqual(self.stream.starts, 1)
        gen = self.session.status()['generation']

        # Voice command: 50%
        r = self.session.submit({'action': 'command', 'utterance': 'Âm lượng 50 phần trăm', 'request_id': uuid4().hex})
        self.assertEqual(r['status'], 'intent_accepted')
        self.assertEqual(r['volume'], 50)
        self.assertEqual(self.session.status()['generation'], gen)
        self.assertEqual(self.stream.starts, 1)

        # Voice command: Tăng âm lượng (+10%)
        r = self.session.submit({'action': 'command', 'utterance': 'Tăng âm lượng', 'request_id': uuid4().hex})
        self.assertEqual(r['status'], 'intent_accepted')
        self.assertEqual(r['volume'], 60)
        self.assertEqual(self.session.status()['generation'], gen)
        self.assertEqual(self.stream.starts, 1)

        # Voice command: Giảm âm lượng (-10%)
        r = self.session.submit({'action': 'command', 'utterance': 'Giảm âm lượng', 'request_id': uuid4().hex})
        self.assertEqual(r['status'], 'intent_accepted')
        self.assertEqual(r['volume'], 50)
        self.assertEqual(self.session.status()['generation'], gen)
        self.assertEqual(self.stream.starts, 1)

        # Voice command: Tắt tiếng robot
        r = self.session.submit({'action': 'command', 'utterance': 'Tắt tiếng robot', 'request_id': uuid4().hex})
        self.assertEqual(r['status'], 'intent_accepted')
        self.assertEqual(r['volume'], 0)
        self.assertTrue(self.control.device()['muted'])
        self.assertEqual(self.session.status()['generation'], gen)
        self.assertEqual(self.stream.starts, 1)

        # Voice command: Bật tiếng robot (restores 50%)
        r = self.session.submit({'action': 'command', 'utterance': 'Bật tiếng robot', 'request_id': uuid4().hex})
        self.assertEqual(r['status'], 'intent_accepted')
        self.assertEqual(r['volume'], 50)
        self.assertFalse(self.control.device()['muted'])
        self.assertEqual(self.session.status()['generation'], gen)
        self.assertEqual(self.stream.starts, 1)
        self.assertEqual(self.session.status()['state'], 'PLAYING')


if __name__=='__main__':unittest.main()
