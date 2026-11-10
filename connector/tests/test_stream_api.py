"""New dev API auth only; temporary browser/knowledge stores, no listeners/capture."""
import contextlib
import os
from pathlib import Path
import secrets
import tempfile
import logging
import sys
import types
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient


class StreamApiTests(unittest.TestCase):
    def setUp(self):
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.admin=secrets.token_urlsafe(32)
        logger=types.ModuleType('src.utils.logger');logger.logger=logging.getLogger('stream-isolated-tests');logger.logger.handlers=[logging.NullHandler()]
        self.stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':logger}))
        self.stack.enter_context(patch.dict(os.environ,{'BROWSER_SESSION_STORE':str(root/'.secrets/browser.sqlite3'),
            'DATABASE_PATH':str(root/'knowledge.db'),'ADMIN_SYNC_TOKEN':self.admin,'ADMIN_SYNC_TOKEN_FILE':'',
            'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false'}))
        from src.config import settings
        settings.reload()
        from src.api.app import create_app
        self.client=TestClient(create_app(),base_url='http://127.0.0.1');self.addCleanup(self.client.close)
        self.headers={'Origin':'http://127.0.0.1'}
    def login(self):
        r=self.client.post('/api/browser/login',headers={**self.headers,'Authorization':'Bearer '+self.admin},json={})
        self.assertEqual(r.status_code,200);self.headers['X-WeWIN-CSRF']=r.json()['csrf']
    def test_01_anonymous_status_denied(self):self.assertEqual(self.client.get('/api/stream/status').status_code,401)
    def test_02_anonymous_start_denied(self):
        self.assertEqual(self.client.post('/api/stream/start',headers=self.headers,json={'endpoint':0,'peer_ipv4':'10.1.2.3'}).status_code,401)
    def test_03_csrf_required(self):
        self.login();self.assertEqual(self.client.post('/api/stream/stop',json={}).status_code,403)
    def test_04_cross_origin_denied(self):
        self.login();self.assertEqual(self.client.post('/api/stream/stop',headers={**self.headers,'Origin':'https://evil.invalid'},json={}).status_code,403)
    def test_05_capture_consent_required_before_socket(self):
        self.login()
        with patch('src.streaming.service.socket') as socket_module:
            r=self.client.post('/api/stream/start',headers=self.headers,json={'endpoint':0,'peer_ipv4':'10.1.2.3'})
            self.assertEqual(r.json()['status'],'system_mix_consent_required');socket_module.socket.assert_not_called()
    def test_06_no_arbitrary_url_or_path(self):
        self.login();r=self.client.post('/api/stream/start',headers=self.headers,json={'endpoint':0,'peer_ipv4':'10.1.2.3','file':'C:/secret','url':'http://private'})
        self.assertEqual(r.status_code,422)
    def test_07_status_not_hardware_pass(self):
        self.login();r=self.client.get('/api/stream/status');self.assertFalse(r.json()['hardware_audio_verified']);self.assertNotIn('token',r.json())
    def test_08_read_status_never_starts_capture(self):
        self.login()
        with patch('src.streaming.service.CapturePipeline') as capture:
            self.client.get('/api/stream/status');capture.assert_not_called()
    def test_09_owner_heartbeat_csrf_required(self):
        self.login();self.assertEqual(self.client.post('/api/stream/heartbeat',json={}).status_code,403)


if __name__=='__main__':unittest.main()
