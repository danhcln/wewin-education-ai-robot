"""Phase7C.3: isolated auth/knowledge stores, ASGI/WS, mocked external APIs."""
import contextlib
import importlib
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests.test_youtube_media import FakeAPI,Clock,VID

class AutoPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=contextlib.ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.root=Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='wewin-autopair-')))
        log=types.ModuleType('src.utils.logger');log.logger=logging.getLogger('autopair-isolated');log.logger.handlers=[logging.NullHandler()]
        cls.stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':log}))

    def setUp(self):
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.folder=self.root/self._testMethodName;self.folder.mkdir();self.admin=secrets.token_urlsafe(32)
        self.stack.enter_context(patch.dict(os.environ,{'DATABASE_PATH':str(self.folder/'knowledge.db'),'KNOWLEDGE_JSON_PATH':str(self.folder/'unused.json'),'ADMIN_SYNC_TOKEN':self.admin,'ADMIN_SYNC_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'','XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','BROWSER_SESSION_STORE':str(self.folder/'.secrets/browser.sqlite3'),'MEDIA_BRIDGE_KEY_FILE':str(self.folder/'.secrets/bridge.key'),'YOUTUBE_API_KEY':'','YOUTUBE_API_KEY_FILE':str(self.folder/'no-key')}))
        from src.config import settings
        settings.reload();self.settings=settings
        from src.api.browser_sessions import get_store,bridge_key
        self.store=get_store();self.key=bridge_key(True)
        from src.storage.db import DatabaseManager,get_db
        self.db=DatabaseManager(self.folder/'knowledge.db')
        appmod=importlib.import_module('src.api.app');self.app=appmod.create_app();self.app.dependency_overrides[get_db]=lambda:self.db
        from fastapi.testclient import TestClient
        self.client=TestClient(self.app,base_url='http://127.0.0.1');self.addCleanup(self.client.close)
        from src.media.youtube import YouTubeClient
        self.api=FakeAPI();self.clock=Clock();self.yt=YouTubeClient(lambda:'fixture-only',self.api,self.clock,self.clock.sleep,self.folder/'channel.json')
        self.stack.enter_context(patch('src.media.routes.youtube',self.yt));self.device=str(uuid4());self.csrf=None

    def login(self):
        response=self.client.post('/api/browser/login',headers={'Origin':'http://127.0.0.1','Authorization':'Bearer '+self.admin},json={})
        self.assertEqual(response.status_code,200);self.csrf=response.json()['csrf'];return response
    def post(self,path,body):return self.client.post(path,headers={'Origin':'http://127.0.0.1','X-WeWIN-CSRF':self.csrf or ''},json=body)
    def register(self):
        self.login();response=self.post('/api/media/auto/register',{'device_id':self.device,'name':'Private test player'});self.assertEqual(response.status_code,200);return response
    def authframe(self,ws):
        ws.send_json({'type':'authenticate','csrf':self.csrf,'device_id':self.device,'tab_id':uuid4().hex});self.assertEqual(ws.receive_json()['type'],'authenticated')
    def bridge(self,name,args=None):return self.client.post('/api/media/auto/bridge-tool',headers={'Authorization':'Bearer '+self.key},json={'tool':name,'arguments':args or {}})
    def test_01_anonymous_registration_denied(self):self.assertEqual(self.post('/api/media/auto/register',{'device_id':self.device}).status_code,401)
    def test_02_wrong_login_not_accepted(self):
        r=self.client.post('/api/browser/login',headers={'Origin':'http://127.0.0.1','Authorization':'Bearer wrong'},json={});self.assertEqual(r.status_code,401);self.assertFalse(self.client.cookies)
    def test_03_httponly_cookie_and_no_credential_response(self):
        r=self.login();cookie=r.headers['set-cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=strict',cookie);self.assertIn('Max-Age=',cookie)
        self.assertNotIn(self.admin,r.text);self.assertNotIn(self.client.cookies['wewin_browser'],r.text)
    def test_04_csrf_required(self):
        self.login();self.assertEqual(self.client.post('/api/media/auto/register',json={'device_id':self.device}).status_code,403)
    def test_05_host_and_origin_checked(self):
        self.login();r=self.client.post('/api/media/auto/register',headers={'Origin':'https://attacker.invalid','X-WeWIN-CSRF':self.csrf},json={'device_id':self.device});self.assertEqual(r.status_code,403)
    def test_06_idempotent_registration_and_default(self):
        r=self.register();self.post('/api/media/auto/register',{'device_id':self.device});self.assertEqual(len(self.store.devices('local-admin')),1)
        self.assertTrue(r.json()['is_default']);self.assertNotIn('control_token',r.text);self.assertNotIn('player_token',r.text)
    def test_07_cookie_persists_store_restart(self):
        self.login();from src.api.browser_sessions import BrowserStore
        again=BrowserStore(self.store.path);self.assertIsNotNone(again.read(self.client.cookies['wewin_browser']))
    def test_08_renew_and_absolute_expiry(self):
        self.login();token=self.client.cookies['wewin_browser'];now=time.time();self.store.clock=lambda:now+86400
        before=self.store.read(token)['expires'];self.store.renew(token);self.assertGreater(self.store.read(token)['expires'],before)
        self.store.clock=lambda:now+31*86400;self.assertIsNone(self.store.read(token))
    def test_09_logout_revokes_cookie(self):
        self.login();token=self.client.cookies['wewin_browser'];self.assertEqual(self.post('/api/browser/logout',{}).status_code,200);self.assertIsNone(self.store.read(token))
    def test_10_admin_rotation_invalidates_cookie(self):
        self.login();self.settings.ADMIN_SYNC_TOKEN=secrets.token_urlsafe(32);self.assertEqual(self.client.get('/api/browser/session').status_code,401)
    def test_11_cookie_authorizes_existing_admin_get_only_with_csrf_on_write(self):
        self.login();self.assertEqual(self.client.get('/api/dashboard/stats').status_code,200)
        self.assertEqual(self.client.post('/sync/unlock').status_code,403)
    def test_12_bridge_rejects_missing_or_wrong_key(self):
        r=self.client.post('/api/media/auto/bridge-tool',json={'tool':'youtube_get_status'});self.assertEqual(r.status_code,401)
    def test_13_browser_cannot_borrow_bridge_authority(self):
        self.login();self.assertEqual(self.bridge('youtube_get_status').status_code,403)
    def test_14_default_without_player_is_disconnected(self):self.assertEqual(self.bridge('youtube_get_status').json()['state'],'PLAYER_DISCONNECTED')
    def test_15_registered_but_not_ready_disconnected(self):
        self.register();self.client.cookies.clear();self.assertFalse(self.bridge('youtube_get_status').json()['connected'])
    def test_16_websocket_cookie_csrf_and_actual_readiness(self):
        self.register()
        with self.client.websocket_connect('ws://127.0.0.1/api/media/auto/player',headers={'Origin':'http://127.0.0.1'}) as ws:
            self.authframe(ws);ws.send_json({'type':'state','state':'PLAYER_READY','event_seq':1})
            time.sleep(.05);self.assertEqual(self.client.get('/api/media/auto/status').json()['state'],'PLAYER_READY')
        self.assertFalse(self.client.get('/api/media/auto/status').json()['connected'])
    def test_17_no_second_tab_takes_live_connection(self):
        self.register()
        with self.client.websocket_connect('ws://127.0.0.1/api/media/auto/player',headers={'Origin':'http://127.0.0.1'}) as first:
            self.authframe(first)
            with self.client.websocket_connect('ws://127.0.0.1/api/media/auto/player',headers={'Origin':'http://127.0.0.1'}) as second:
                second.send_json({'type':'authenticate','csrf':self.csrf,'device_id':self.device,'tab_id':uuid4().hex})
                self.assertEqual(second.receive_json()['code'],'player_in_use')
    def test_18_invalid_ws_proof_denied(self):
        self.register()
        with self.client.websocket_connect('ws://127.0.0.1/api/media/auto/player',headers={'Origin':'http://127.0.0.1'}) as ws:
            ws.send_json({'type':'authenticate','csrf':'wrong','device_id':self.device,'tab_id':uuid4().hex});self.assertEqual(ws.receive_json()['code'],'unauthorized')
    def test_19_wrong_owner_cannot_claim_device(self):
        self.register();from src.media.registry import get_registry
        with self.assertRaises(Exception):get_registry().status('other-owner',self.device)
    def test_20_default_selection_never_falls_back_to_other(self):
        self.register();other=str(uuid4());self.post('/api/media/auto/register',{'device_id':other});self.post('/api/media/auto/default',{'device_id':other})
        self.assertEqual(self.client.get('/api/media/auto/status').json()['device_id'],other)
    def test_21_forget_blocks_old_device(self):
        self.register();self.assertEqual(self.post('/api/media/auto/forget',{'device_id':self.device}).status_code,200)
        self.assertEqual(self.post('/api/media/auto/register',{'device_id':self.device}).status_code,409)
    def test_22_backend_restart_registers_new_epoch(self):
        self.register();from src.media.registry import PlayerRegistry,get_registry
        previous=get_registry().entry('local-admin',self.device)['epoch'];after=PlayerRegistry(self.store);after.register('local-admin',self.device,'test')
        self.assertNotEqual(previous,after.entry('local-admin',self.device)['epoch']);self.assertFalse(after.status('local-admin')['connected'])
    def test_23_old_intent_not_replayed_after_backend_restart(self):
        self.register();from src.media.registry import PlayerRegistry,get_registry
        reg=get_registry();e,cid=reg.connect('local-admin',self.device,uuid4().hex);hub=e['hub'];p=e['pair'];hub.event(p['session_id'],p['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        args={'action':'select','video_id':VID,'request_id':'persisted-request'};reg.command('local-admin',args,self.yt,wait_seconds=0)
        after=PlayerRegistry(self.store);after.register('local-admin',self.device,'test');e,cid=after.connect('local-admin',self.device,uuid4().hex);p=e['pair'];e['hub'].event(p['session_id'],p['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        from src.media.youtube import MediaError
        with self.assertRaises(MediaError) as error:after.command('local-admin',args,self.yt,wait_seconds=0)
        self.assertEqual(error.exception.code,'stale_command')
    def test_24_legacy_capabilities_not_retargeted(self):
        self.register();r=self.post('/api/media/auto/tool',{'tool':'youtube_control','arguments':{'session_id':'old','control_token':'old','action':'play','request_id':'request-001'}});self.assertEqual(r.json()['status'],'legacy_session_rejected')
    def test_25_public_mcp_cannot_route_default_player(self):
        self.register();from src.media.registry import get_registry
        reg=get_registry();e,cid=reg.connect('local-admin',self.device,uuid4().hex);p=e['pair']
        e['hub'].event(p['session_id'],p['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        r=self.client.post('/api/media/tool',json={'tool':'youtube_control','arguments':{'action':'play','request_id':'request-001'}})
        self.assertEqual(r.status_code,200)
        self.assertIn(r.json()['status'],('player_disconnected','invalid_session','unauthorized'))
        self.assertIsNone(e['hub'].session['pending'])
    def test_26_heartbeat_timeout_is_real(self):
        from src.media.registry import PlayerRegistry
        clock=Clock();reg=PlayerRegistry(self.store,clock);reg.register('local-admin',self.device,'test');e,cid=reg.connect('local-admin',self.device,uuid4().hex)
        clock.n+=31;self.assertFalse(reg.status('local-admin')['connected'])
    def test_27_command_awaits_actual_player_and_no_duplicate_replay(self):
        self.register();from src.media.registry import get_registry
        reg=get_registry();e,cid=reg.connect('local-admin',self.device,uuid4().hex);hub=e['hub'];pair=e['pair'];seq=1
        hub.event(pair['session_id'],pair['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':seq})
        args={'action':'select','video_id':VID,'request_id':'fresh-request'}
        def confirm():
            for _ in range(100):
                command=hub.tick(pair['session_id'],pair['player_token'],cid)
                if command:
                    hub.event(pair['session_id'],pair['player_token'],cid,{'type':'state','state':'VIDEO_SELECTED','video_id':VID,'event_seq':2,'command_id':command['command_id']});return
                time.sleep(.01)
        thread=threading.Thread(target=confirm);thread.start();result=reg.command('local-admin',args,self.yt);thread.join()
        self.assertEqual(result['status'],'command_confirmed');self.assertEqual(result['state'],'VIDEO_SELECTED');self.assertEqual(reg.command('local-admin',args,self.yt)['status'],'duplicate_request')
    def test_28_no_secret_in_session_or_registration(self):
        response=self.register();values=response.text+self.client.get('/api/media/auto/devices').text
        for secret in (self.admin,self.key,self.client.cookies['wewin_browser']):self.assertNotIn(secret,values)

    def test_29_concurrent_registration_has_one_default_and_one_session(self):
        from concurrent.futures import ThreadPoolExecutor
        from src.media.registry import get_registry
        reg=get_registry()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _:reg.register('local-admin',self.device,'Concurrent test'),range(12)))
        self.assertEqual(len(self.store.devices('local-admin')),1)
        self.assertEqual(sum(r['is_default'] for r in self.store.devices('local-admin')),1)
        self.assertEqual(len(reg.players),1)

    def test_30_offline_default_never_routes_to_another_live_device(self):
        self.register();from src.media.registry import get_registry
        from src.media.youtube import MediaError
        reg=get_registry();other=str(uuid4());reg.register('local-admin',other,'Other player')
        e,cid=reg.connect('local-admin',other,uuid4().hex);p=e['pair']
        e['hub'].event(p['session_id'],p['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        self.assertTrue(reg.status('local-admin',other)['connected'])
        with self.assertRaises(MediaError) as error:reg.command('local-admin',{'action':'play','request_id':'no-fallback-request'},self.yt)
        self.assertEqual(error.exception.code,'player_disconnected')
        self.assertIsNone(e['hub'].session['pending'])

    def test_31_concurrent_bridge_key_creation_never_rotates_existing_key(self):
        from concurrent.futures import ThreadPoolExecutor
        from src.api.browser_sessions import bridge_key
        path=self.folder/'.secrets/new-bridge.key'
        with patch.dict(os.environ,{'MEDIA_BRIDGE_KEY_FILE':str(path)}):
            with ThreadPoolExecutor(max_workers=6) as pool:values=list(pool.map(lambda _:bridge_key(True),range(12)))
            self.assertEqual(len(set(values)),1);self.assertEqual(bridge_key(True),values[0])

    def test_32_invalid_explicit_header_cannot_fall_back_to_valid_cookie(self):
        self.login();r=self.client.get('/api/dashboard/stats',headers={'Authorization':'Bearer wrong'})
        self.assertEqual(r.status_code,401)

    def test_33_latest_resolves_verified_queue_then_waits_select_and_play(self):
        self.register();from src.media.registry import get_registry
        reg=get_registry();e,cid=reg.connect('local-admin',self.device,uuid4().hex);hub=e['hub'];p=e['pair']
        hub.event(p['session_id'],p['player_token'],cid,{'type':'state','state':'PLAYER_READY','event_seq':1})
        observed=[];done=threading.Event()
        def confirm():
            seq=1
            while not done.is_set():
                command=hub.tick(p['session_id'],p['player_token'],cid)
                if command:
                    observed.append(command['action']);seq+=1
                    hub.event(p['session_id'],p['player_token'],cid,{'type':'state','state':'VIDEO_SELECTED' if command['action']=='select' else 'PLAYING','video_id':command['video_id'],'event_seq':seq,'command_id':command['command_id']})
                done.wait(.01)
        thread=threading.Thread(target=confirm);thread.start()
        try:result=reg.command('local-admin',{'action':'latest','request_id':'latest-new-intent'},self.yt)
        finally:done.set();thread.join(2)
        self.assertEqual(observed,['select','play']);self.assertEqual(result['status'],'command_confirmed')
        self.assertEqual(result['state'],'PLAYING');self.assertEqual(result['observed_video_id'],VID)

if __name__=='__main__':unittest.main(verbosity=2)
