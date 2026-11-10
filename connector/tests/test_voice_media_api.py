"""Authenticated Phase 2 UI routes; all stores/adapters temporary, no LAN listener."""
import contextlib
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient


class VoiceApiTests(unittest.TestCase):
    def setUp(self):
        self.stack=contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.secret=secrets.token_urlsafe(32)
        self.stack.enter_context(patch.dict(os.environ,{'BROWSER_SESSION_STORE':str(self.root/'.secrets/browser.sqlite3'),
            'DATABASE_PATH':str(self.root/'knowledge.db'),'ADMIN_SYNC_TOKEN':self.secret,'ADMIN_SYNC_TOKEN_FILE':'',
            'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false'}))
        from src.config import settings
        settings.reload()
        from src.api.app import create_app
        from src.media.device_control import DeviceControl
        self.control=DeviceControl(self.root/'control')
        self.start=Mock();self.control.start=self.start
        self.session=Mock();self.session.status.return_value={'state':'IDLE','hardware_audio_verified':False}
        self.session.submit.return_value={'status':'intent_accepted','playback_confirmed':False}
        self.stack.enter_context(patch('src.media.voice_routes.get_control',return_value=self.control))
        self.stack.enter_context(patch('src.media.voice_routes.get_session',return_value=self.session))
        self.client=TestClient(create_app(),base_url='http://127.0.0.1'); self.addCleanup(self.client.close)
        self.headers={'Origin':'http://127.0.0.1'}
    def login(self):
        r=self.client.post('/api/browser/login',headers={**self.headers,'Authorization':'Bearer '+self.secret},json={})
        self.assertEqual(r.status_code,200);self.headers['X-WeWIN-CSRF']=r.json()['csrf']
    def test_anonymous_status_denied(self):self.assertEqual(self.client.get('/api/media/voice/status').status_code,401)
    def test_anonymous_action_denied(self):self.assertEqual(self.client.post('/api/media/voice/action',headers=self.headers,json={'action':'stop','request_id':'test-123456'}).status_code,401)
    def test_csrf_required(self):
        self.login();self.assertEqual(self.client.post('/api/media/voice/action',json={'action':'stop','request_id':'test-123456'}).status_code,403)
    def test_cross_origin_denied(self):
        self.login();self.assertEqual(self.client.post('/api/media/voice/action',headers={**self.headers,'Origin':'https://evil.invalid'},json={'action':'stop','request_id':'test-123456'}).status_code,403)
    def test_disabled_action_refused(self):
        self.login();self.assertEqual(self.client.post('/api/media/voice/action',headers=self.headers,json={'action':'stop','request_id':'test-123456'}).status_code,409);self.session.submit.assert_not_called()
    def test_authorized_intent_does_not_claim_speaker(self):
        self.login();self.control.config['enabled']=True;r=self.client.post('/api/media/voice/action',headers=self.headers,json={'action':'play','query':'Thánh Gióng','request_id':'test-123456'})
        self.assertEqual(r.status_code,200);self.assertFalse(r.json()['playback_confirmed']);self.start.assert_not_called()
    def test_no_arbitrary_ip_descriptor_url(self):
        self.login();r=self.client.post('/api/media/voice/action',headers=self.headers,json={'action':'play','request_id':'test-123456','descriptor':{},'device_ip':'8.8.8.8','url':'file:///secret'})
        self.assertEqual(r.status_code,422);self.session.submit.assert_not_called()
    def test_setup_requires_consent(self):
        self.login();r=self.client.post('/api/media/voice/configure',headers=self.headers,json={'enabled':True,'capture_name':'loopback'})
        self.assertEqual(r.status_code,409);self.start.assert_not_called()
    def test_setup_explicit_opt_in_only(self):
        self.login();r=self.client.post('/api/media/voice/configure',headers=self.headers,json={'enabled':True,'capture_name':'loopback','system_mix_consent':True,'local_route_confirmed':True})
        self.assertEqual(r.status_code,200);self.start.assert_called_once()
    def test_approval_requires_fresh_discovery(self):
        self.login();r=self.client.post('/api/media/voice/approve',headers=self.headers,json={'device_id':'a'*32,'fingerprint':'b'*64})
        self.assertEqual(r.status_code,409);self.assertFalse(self.control.config['approved'])
    def test_status_read_only_and_no_secrets(self):
        self.login();r=self.client.get('/api/media/voice/status');self.assertEqual(r.status_code,200);self.assertFalse(r.json()['media']['hardware_audio_verified']);self.start.assert_not_called();self.assertNotIn('descriptor',r.text);self.assertNotIn(self.secret,r.text)
    def test_active_session_cannot_repair_or_reconfigure(self):
        self.login();self.session.status.return_value={'state':'PLAYING'}
        self.assertEqual(self.client.post('/api/media/voice/approve',headers=self.headers,json={'device_id':'a'*32,'fingerprint':'b'*64}).status_code,409)
        self.assertEqual(self.client.post('/api/media/voice/configure',headers=self.headers,json={'enabled':True,'capture_name':'loopback','system_mix_consent':True,'local_route_confirmed':True}).status_code,409)
        self.start.assert_not_called()


if __name__=='__main__':unittest.main()
