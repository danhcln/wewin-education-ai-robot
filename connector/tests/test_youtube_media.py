"""Official API mocked; isolated DB; real ASGI/WS; never production credentials."""
import contextlib
import importlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import httpx

CID='UC'+'W'*22
OTHER='UC'+'X'*22
VID='M7lc1UVf-VE'
UPLOAD='UU'+'W'*22

class Clock:
    def __init__(self):self.n=0;self.waits=[]
    def __call__(self):return self.n
    def sleep(self,n):self.waits.append(n);self.n+=n

class FakeAPI:
    def __init__(self):self.calls=[];self.failure=None;self.empty=False;self.channel=CID;self.video_channel=CID;self.embed=True
    def get(self,url,params,headers):
        resource=url.rsplit('/',1)[-1];self.calls.append((resource,params,headers))
        if isinstance(self.failure,Exception):raise self.failure
        if self.failure:return httpx.Response(self.failure,json={'error':{'errors':[{'reason':'quotaExceeded' if self.failure==403 else 'backendError'}]}})
        if self.empty:return httpx.Response(200,json={'items':[]})
        if resource=='channels':items=[{'id':self.channel,'snippet':{'title':'Fixture WeWIN','customUrl':'@WeWINEducation'},'contentDetails':{'relatedPlaylists':{'uploads':UPLOAD}}}]
        elif resource=='search':items=[{'id':{'videoId':VID}}]
        elif resource=='playlistItems':items=[{'contentDetails':{'videoId':VID}}]
        else:items=[{'id':VID,'snippet':{'title':'Fixture Cambridge &amp; IELTS','channelId':self.video_channel,'channelTitle':'Fixture channel',
            'publishedAt':'2026-10-01T00:00:00Z','thumbnails':{'medium':{'url':'https://i.ytimg.com/vi/'+VID+'/mqdefault.jpg'}}},
            'status':{'embeddable':self.embed,'privacyStatus':'public','uploadStatus':'processed'}}]
        return httpx.Response(200,json={'items':items})

class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=contextlib.ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.root=Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='wewin-media-')))
        cls.admin=secrets.token_urlsafe(32)
        cls.stack.enter_context(patch.dict(os.environ,{'DATABASE_PATH':str(cls.root/'unused.db'),'KNOWLEDGE_JSON_PATH':str(cls.root/'unused.json'),
            'ADMIN_SYNC_TOKEN':cls.admin,'ADMIN_SYNC_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'',
            'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false',
            'YOUTUBE_API_KEY':'','YOUTUBE_API_KEY_FILE':str(cls.root/'no-key'),'YOUTUBE_CHANNEL_FILE':str(cls.root/'no-channel.json')}))
        log=types.ModuleType('src.utils.logger');log.logger=logging.getLogger('media-isolated');log.logger.handlers=[logging.NullHandler()]
        cls.stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':log}))
        cls.stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('External HTTP forbidden')))
        cls.stack.enter_context(patch('websockets.connect',side_effect=AssertionError('Cloud forbidden')))
    def setUp(self):
        from src.config import settings
        settings.reload()  # Respect this test class environment even after other modules were collected.
        from src.media.youtube import YouTubeClient
        from src.media.hub import PlayerHub
        self.folder=self.root/self._testMethodName;self.folder.mkdir();self.api=FakeAPI();self.clock=Clock()
        self.key=secrets.token_urlsafe(32);self.yt=YouTubeClient(lambda:self.key,self.api,self.clock,self.clock.sleep,self.folder/'channel.json')
        self.hub=PlayerHub(self.clock);self.p=None;self.cid=None;self.event_seq=0
    def assert_code(self,code,fn,*args,**kwargs):
        from src.media.youtube import MediaError
        with self.assertRaises(MediaError) as e:fn(*args,**kwargs)
        self.assertEqual(e.exception.code,code)
    def connected(self):
        self.p=self.hub.pair();self.cid=self.hub.connect(self.p['session_id'],self.p['player_token']);self.emit('PLAYER_READY')
        return self.p
    def emit(self,state=None,**kw):
        self.event_seq+=1;event={'type':'state','state':state,'event_seq':self.event_seq,**kw}
        self.hub.event(self.p['session_id'],self.p['player_token'],self.cid,event)
    def enqueue(self,action='select',rid='request-001'):
        return self.hub.enqueue(self.p['session_id'],self.p['control_token'],action,rid,self.yt.video(VID) if action=='select' else None)
    def confirm(self,state):
        c=self.hub.tick(self.p['session_id'],self.p['player_token'],self.cid);self.emit(state,video_id=VID,command_id=c['command_id']);return c
    def client(self):
        from fastapi.testclient import TestClient
        from src.storage.db import DatabaseManager,get_db
        appmod=importlib.import_module('src.api.app');routes=importlib.import_module('src.media.routes')
        db=DatabaseManager(self.folder/'db.sqlite');db.index_records([{'url':'https://wewin.edu.vn/test/','title':'Public','content':'Public fixture article for WeWIN Education. '*8}])
        self.addCleanup(patch.stopall)
        patch.object(routes,'hub',self.hub).start();patch.object(routes,'youtube',self.yt).start();patch.object(appmod,'get_db',return_value=db).start()
        app=appmod.create_app();app.dependency_overrides[get_db]=lambda:db
        stack=contextlib.ExitStack();self.addCleanup(stack.close);return stack.enter_context(TestClient(app))

    def test_01_channel_resolved_by_handle_and_saved(self):
        result=self.yt.resolve_channel();self.assertEqual(result['channel_id'],CID)
        self.assertEqual(self.api.calls[0][1]['forHandle'],'@WeWINEducation')
        self.assertEqual(json.loads((self.folder/'channel.json').read_text())['uploads_playlist_id'],UPLOAD)
    def test_02_channel_invalid_or_empty_unverified(self):
        self.api.channel='guessed';self.assert_code('channel_unverified',self.yt.resolve_channel);self.assertIsNone(self.yt.channel)
    def test_03_wewin_search_restricts_channel_and_labels_exactly(self):
        r=self.yt.search('Cambridge');search=next(c for c in self.api.calls if c[0]=='search')
        self.assertEqual(search[1]['channelId'],CID);self.assertTrue(r['videos'][0]['is_wewin'])
    def test_04_all_search_does_not_label_unknown_channel(self):
        r=self.yt.search('IELTS','all');self.assertNotIn('channelId',self.api.calls[0][1]);self.assertFalse(r['videos'][0]['is_wewin'])
    def test_05_wrong_channel_never_wewin(self):
        self.api.video_channel=OTHER;self.assertEqual(self.yt.search('Movers')['videos'],[])
        result=self.yt.search('IELTS','all');self.assertFalse(result['videos'][0]['is_wewin'])
        original=self.yt.channel
        self.yt.channel={**original,'channel_id':OTHER}
        self.assertTrue(self.yt.search('IELTS','all')['videos'][0]['is_wewin'])
        self.yt.channel=original
        self.assertFalse(self.yt.search('IELTS','all')['videos'][0]['is_wewin'])
    def test_06_latest_uses_uploads_not_search(self):
        self.assertTrue(self.yt.latest()['videos']);self.assertNotIn('search',[c[0] for c in self.api.calls])
        self.assertEqual(next(c[1]['playlistId'] for c in self.api.calls if c[0]=='playlistItems'),UPLOAD)
    def test_07_empty_results(self):
        self.api.empty=True;self.assertEqual(self.yt.search('nothing','all')['videos'],[])
    def test_08_missing_key_and_no_fake_live(self):
        self.key='';self.assert_code('api_key_missing',self.yt.search,'IELTS');self.assertEqual(self.api.calls,[])
    def test_09_quota_no_retry(self):
        self.api.failure=403;self.assert_code('quota_exceeded',self.yt.resolve_channel);self.assertEqual(len(self.api.calls),1)
    def test_10_timeout_bounded_retry_backoff(self):
        self.api.failure=httpx.ReadTimeout('fixture');self.assert_code('youtube_timeout',self.yt.resolve_channel)
        self.assertEqual(len(self.api.calls),3);self.assertTrue(self.clock.waits)
        from datetime import datetime,timezone,timedelta
        from email.utils import format_datetime
        future=format_datetime(datetime.now(timezone.utc)+timedelta(minutes=2))
        with patch.object(self.api,'get',return_value=httpx.Response(429,headers={'Retry-After':future},json={'error':{}})) as get:
            self.assert_code('quota_or_rate_limited',self.yt.resolve_channel)
            self.assertEqual(get.call_count,1);self.assertGreater(self.yt.blocked_until-self.clock(),110)
    def test_11_cache_avoids_repeated_calls(self):
        a=self.yt.search('Cambridge');count=len(self.api.calls);self.assertEqual(self.yt.search('Cambridge'),a);self.assertEqual(len(self.api.calls),count)
    def test_12_invalid_video_id_and_unavailable(self):
        for v in ['https://youtube.com/watch?v='+VID,'../.env',';start calc','bad']:
            self.assert_code('invalid_video_id',self.yt.video,v)
        self.api.embed=False;self.assert_code('video_unavailable',self.yt.video,VID)
    def test_13_video_missing(self):
        self.api.empty=True;self.assert_code('video_not_found',self.yt.video,VID)
    def test_14_key_header_not_urls_or_results(self):
        r=self.yt.search('IELTS');self.assertNotIn(self.key,json.dumps(r));self.assertNotIn('key',self.api.calls[0][1]);self.assertEqual(self.api.calls[0][2]['X-Goog-Api-Key'],self.key)
    def test_15_no_player_no_success(self):
        self.assertEqual(self.hub.snapshot()['state'],'PLAYER_DISCONNECTED');self.assert_code('player_disconnected',self.hub.authorize,'missing','missing')
    def test_16_auth_scopes_and_wrong_session(self):
        p=self.connected();self.assert_code('unauthorized',self.hub.authorize,p['session_id'],p['player_token'])
        self.assert_code('invalid_session',self.hub.authorize,'wrong',p['control_token'])
    def test_17_pair_replaces_and_revokes_old_session(self):
        old=self.connected();new=self.hub.pair();self.assertNotEqual(old['session_id'],new['session_id'])
        self.assert_code('invalid_session',self.hub.authorize,old['session_id'],old['control_token'])
    def test_18_select_receipt_not_playing(self):
        self.connected();r=self.enqueue();self.assertEqual(r['status'],'command_queued');self.assertFalse(r['playback_confirmed'])
        s=self.hub.snapshot(self.p['session_id'],self.p['control_token']);self.assertEqual(s['state'],'PLAYER_READY')
    def test_19_received_not_confirmed(self):
        self.connected();self.enqueue();c=self.hub.tick(self.p['session_id'],self.p['player_token'],self.cid)
        self.emit(None,type='received',command_id=c['command_id'])
        s=self.hub.snapshot(self.p['session_id'],self.p['control_token']);self.assertEqual(s['pending_command']['command_status'],'received');self.assertEqual(s['state'],'PLAYER_READY')
    def test_20_play_pause_resume_stop_confirmed_by_events(self):
        self.connected();self.enqueue();self.confirm('VIDEO_SELECTED')
        for i,(action,state) in enumerate([('play','PLAYING'),('pause','PAUSED'),('resume','PLAYING'),('stop','STOPPED')]):
            self.enqueue(action,'request-action-'+str(i));self.confirm(state)
            self.assertEqual(self.hub.snapshot(self.p['session_id'],self.p['control_token'])['state'],state)
    def test_21_duplicate_and_conflict_no_replay(self):
        self.connected();a=self.enqueue();b=self.enqueue();self.assertEqual(a['command_id'],b['command_id'])
        self.assert_code('request_conflict',self.hub.enqueue,self.p['session_id'],self.p['control_token'],'play','request-001')
    def test_22_expired_command_not_delivered(self):
        self.connected();self.enqueue();self.clock.n+=13;self.hub.event(self.p['session_id'],self.p['player_token'],self.cid,{'type':'heartbeat'})
        self.assertIsNone(self.hub.tick(self.p['session_id'],self.p['player_token'],self.cid))
    def test_23_autoplay_blocked_and_error(self):
        self.connected();self.enqueue();c=self.hub.tick(self.p['session_id'],self.p['player_token'],self.cid)
        self.emit('AUTOPLAY_BLOCKED',video_id=VID,command_id=c['command_id']);s=self.hub.snapshot(self.p['session_id'],self.p['control_token'])
        self.assertIsNone(s['pending_command']);self.assertEqual(s['state'],'AUTOPLAY_BLOCKED')
    def test_24_heartbeat_and_closed_tab_disconnect(self):
        self.connected();self.clock.n+=16;self.assertEqual(self.hub.snapshot(self.p['session_id'],self.p['control_token'])['state'],'PLAYER_DISCONNECTED')
    def test_25_stale_event_and_wrong_video_rejected(self):
        self.connected();self.enqueue();self.assert_code('video_mismatch',self.emit,'PLAYING',video_id='aaaaaaaaaaa')
        self.assert_code('stale_event',self.hub.event,self.p['session_id'],self.p['player_token'],self.cid,{'type':'state','state':'PLAYING','event_seq':1})
    def test_26_pair_admin_required_and_no_cap_leak(self):
        c=self.client();self.assertEqual(c.post('/api/media/pair',json={}).status_code,401)
        p=c.post('/api/media/pair',json={},headers={'Authorization':'Bearer '+self.admin}).json()
        text=c.get('/api/media/config').text;self.assertNotIn(p['player_token'],text);self.assertNotIn(p['control_token'],text);self.assertNotIn(self.key,text)
    def test_27_ws_first_frame_auth_and_origin(self):
        c=self.client();p=self.hub.pair()
        with c.websocket_connect('/api/media/player',headers={'Origin':'http://testserver'}) as ws:
            ws.send_json({'type':'authenticate','session_id':p['session_id'],'player_token':p['player_token']});self.assertEqual(ws.receive_json()['type'],'authenticated')
        self.assertEqual(self.hub.snapshot(p['session_id'],p['control_token'])['state'],'PLAYER_DISCONNECTED')
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with c.websocket_connect('/api/media/player?token=forbidden',headers={'Origin':'https://evil.example'}):pass
    def test_28_http_control_unauthorized_before_lookup(self):
        c=self.client();p=self.connected()
        r=c.post('/api/media/tool',json={'tool':'youtube_control','arguments':{'session_id':p['session_id'],'control_token':'wrong','action':'select','video_id':VID}}).json()
        self.assertEqual(r['status'],'unauthorized');self.assertEqual(self.api.calls,[])
    def test_29_mcp_list_and_call_additive(self):
        c=self.client()
        with patch('src.mcp.tools.relay_media_tool',return_value={'status':'api_key_missing','message':'fixture'}):
            with c.websocket_connect('/ws/mcp') as ws:
                ws.send_json({'id':1,'method':'tools/list'});names={t['name'] for t in ws.receive_json()['result']['tools']}
                self.assertTrue({'wewin_read_article','wewin_stop_reading','youtube_control','youtube_search'}<=names)
                ws.send_json({'id':2,'method':'tools/call','params':{'name':'youtube_search','arguments':{'query':'IELTS'}}})
                self.assertEqual(json.loads(ws.receive_json()['result']['content'][0]['text'])['status'],'api_key_missing')
    def test_30_relay_rejects_non_loopback_target(self):
        from src.media.tools import relay_media_tool
        with patch.dict(os.environ,{'MEDIA_BACKEND_URL':'https://evil.example'}):self.assertEqual(relay_media_tool('youtube_get_status',{})['status'],'invalid_backend')
    def test_31_scope_cannot_be_widened_implicitly(self):
        self.assert_code('invalid_arguments',self.yt.search,'IELTS','anything')
    def test_32_cache_not_claimed_live_after_key_removed(self):
        self.yt.search('IELTS');self.key='';self.assert_code('api_key_missing',self.yt.search,'IELTS')
    def test_33_expiry_cleans_only_owned_metadata(self):
        self.yt.resolve_channel();record=json.loads((self.folder/'channel.json').read_text());record['verified_at']=0
        (self.folder/'channel.json').write_text(json.dumps(record));self.clock.n+=86401;self.yt.prune()
        self.assertFalse((self.folder/'channel.json').exists());self.assertEqual(self.yt.cache,{})
    def test_34_channel_cache_never_overwrites_other_json(self):
        (self.folder/'channel.json').write_text('{"important":"preserve"}')
        self.assert_code('channel_storage_conflict',self.yt.resolve_channel)
        self.assertEqual(json.loads((self.folder/'channel.json').read_text()),{'important':'preserve'})
    def test_35_dashboard_reports_current_local_registry(self):
        c=self.client();r=c.get('/api/dashboard/stats',headers={'Authorization':'Bearer '+self.admin})
        self.assertEqual(r.status_code,200);data=r.json()['mcp_bridge']
        from src.mcp.tools import TOOL_DEFINITIONS
        self.assertEqual(data['tools_registered'],len(TOOL_DEFINITIONS));self.assertIn('youtube_control',data['tools_list'])
        self.assertTrue({'wewin_education_search','wewin_education_browse','wewin_education_playlists'} <= set(data['tools_list']))
        self.assertIn('wewin_prepare_audio',data['tools_list'])

    def test_36_reconnect_keeps_scopes_without_replaying_disconnected_command(self):
        p=self.connected();old_cid=self.cid
        self.enqueue('select','disconnect-request')
        self.hub.disconnect(p['session_id'],old_cid)
        self.assert_code('player_disconnected',self.hub.authorize,p['session_id'],p['control_token'])
        self.cid=self.hub.connect(p['session_id'],p['player_token'])
        self.emit('PLAYER_READY')
        self.hub.authorize(p['session_id'],p['control_token'])
        self.assertIsNone(self.hub.tick(p['session_id'],p['player_token'],self.cid))
        self.hub.disconnect(p['session_id'],old_cid)
        self.assertTrue(self.hub.snapshot(p['session_id'],p['control_token'])['connected'])
        self.assertEqual(self.enqueue('select','disconnect-request')['status'],'command_disconnected')
        self.assertIsNone(self.hub.tick(p['session_id'],p['player_token'],self.cid))
        self.enqueue('select','fresh-after-reconnect');self.confirm('VIDEO_SELECTED')
        self.assertEqual(self.hub.snapshot(p['session_id'],p['control_token'])['state'],'VIDEO_SELECTED')

    def test_37_reconnect_cannot_restore_revoked_or_expired_grant(self):
        p=self.connected();self.hub.disconnect(p['session_id'],self.cid)
        self.assert_code('unauthorized',self.hub.connect,p['session_id'],p['control_token'])
        self.clock.n+=28801
        self.assert_code('session_expired',self.hub.connect,p['session_id'],p['player_token'])
        p=self.hub.pair();self.hub.revoke(p['session_id'])
        self.assert_code('player_disconnected',self.hub.connect,p['session_id'],p['player_token'])

if __name__=='__main__':unittest.main(verbosity=2)
