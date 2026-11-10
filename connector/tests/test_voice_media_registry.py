"""Real registry/hub command+ACK, simulated IFrame and native stream. Temp SQLite only."""
import tempfile
from pathlib import Path
import threading
import time
import unittest
from uuid import uuid4
from tests.test_voice_media import A, B, YouTube, Stream, Control
from src.media.orchestration import MediaSession, owner
from src.media.youtube import MediaError


class RegistryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.user=owner()
        from src.api.browser_sessions import BrowserStore
        from src.media.registry import PlayerRegistry
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=BrowserStore(Path(self.temp.name)/'.secrets/browser.sqlite3');self.registry=PlayerRegistry(self.store)
        self.device=uuid4().hex;self.registry.register(self.user,self.device,'Host test frame')
        self.entry,self.cid=self.registry.connect(self.user,self.device,uuid4().hex)
        self.hub=self.entry['hub'];self.pair=self.entry['pair'];self.seq=1
        self.hub.event(self.pair['session_id'],self.pair['player_token'],self.cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        self.events=[];self.stream=Stream(self.events);self.control=Control(self.stream,self.events)
        self.session=MediaSession(self.registry,YouTube(),self.stream,self.control,lambda:[{'name':'loopback','index':0}])
        self.closed=threading.Event()
        def frame():
            while not self.closed.is_set():
                try:
                    command=self.hub.tick(self.pair['session_id'],self.pair['player_token'],self.cid)
                    if command:
                        self.seq+=1;state={'select':'VIDEO_SELECTED','play':'PLAYING','resume':'PLAYING','pause':'PAUSED','stop':'STOPPED'}[command['action']]
                        self.hub.event(self.pair['session_id'],self.pair['player_token'],self.cid,{'type':'state','state':state,'video_id':command['video_id'],'command_id':command['command_id'],'media_generation':command['media_generation'],'event_seq':self.seq})
                except MediaError:pass
                self.closed.wait(.01)
        self.thread=threading.Thread(target=frame,daemon=True);self.thread.start()
        self.addCleanup(self.cleanup_workers)
    def cleanup_workers(self):
        self.session.shutdown();self.closed.set();self.thread.join(1)
        if self.session.thread:self.session.thread.join(1)
    def action(self,action,**kwargs):
        self.session.submit(dict(action=action,request_id=uuid4().hex,**kwargs));until=time.monotonic()+5
        while time.monotonic()<until:
            status=self.session.status()
            if status['state'] in ('PLAYING','PAUSED','IDLE','ERROR','ENDED'):return status
            time.sleep(.01)
        self.fail('No correlated frame ACK')
    def test_real_registry_play_pause_resume_replace_stop(self):
        self.assertEqual(self.action('play',query='Thánh Gióng')['state'],'PLAYING')
        self.assertEqual(self.action('pause')['state'],'PAUSED')
        self.assertEqual(self.action('resume')['state'],'PLAYING')
        changed=self.action('replace',query='Con Rồng Cháu Tiên');self.assertEqual(changed['state'],'PLAYING');self.assertEqual(changed['video_id'],B['video_id'])
        self.assertEqual(self.action('stop')['state'],'IDLE')
    def test_stale_generation_ack_never_confirms_new_command(self):
        self.closed.set();self.thread.join(1)
        sid=self.pair['session_id'];cap=self.pair['control_token'];token=self.pair['player_token']
        self.hub.enqueue(sid,cap,'select','old-request-123',A,media_generation=3)
        self.hub.enqueue(sid,cap,'stop','new-request-123',media_generation=4)
        c=self.hub.tick(sid,token,self.cid)
        with self.assertRaises(MediaError):self.hub.event(sid,token,self.cid,{'type':'state','state':'STOPPED','video_id':A['video_id'],'command_id':c['command_id'],'media_generation':3,'event_seq':2})
        self.assertNotEqual(self.hub.snapshot(sid,cap)['last_command']['command_status'],'confirmed')
    def test_browser_pin_is_stable_when_default_changes(self):
        self.assertEqual(self.action('play',query='Thánh Gióng')['state'],'PLAYING')
        other=uuid4().hex;self.registry.register(self.user,other,'Other frame');self.store.choose(self.user,other)
        self.assertEqual(self.action('pause')['state'],'PAUSED');self.assertEqual(self.session.status()['browser_device_id'],self.device)


if __name__=='__main__':unittest.main()
