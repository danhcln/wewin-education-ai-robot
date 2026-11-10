"""Phase 6A: temp databases, real local ASGI/MCP, mocked external transports."""
import asyncio
import contextlib
import importlib
import io
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import types
import unittest
from unittest.mock import patch


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.addClassCleanup(cls.stack.close)
        cls.root = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='phase6a-tests-')))
        cls.stack.enter_context(patch.dict(os.environ, {
            'DATABASE_PATH': str(cls.root/'unused.db'), 'ADMIN_SYNC_TOKEN': secrets.token_urlsafe(32),
            'ADMIN_SYNC_TOKEN_FILE': '', 'XIAOZHI_MCP_ENDPOINT': '', 'XIAOZHI_MCP_TOKEN': '',
            'XIAOZHI_MCP_ENDPOINT_FILE': '', 'XIAOZHI_MCP_TOKEN_FILE': '',
            'AUTO_SYNC_ENABLED': 'false', 'SYNC_SCHEDULE_ARMED': 'false',
            'BRIDGE_STATUS_PATH': str(cls.root/'heartbeat.json')}))
        log = types.ModuleType('src.utils.logger')
        log.logger = logging.getLogger('readiness-isolated')
        log.logger.handlers = [logging.NullHandler()]
        cls.stack.enter_context(patch.dict('sys.modules', {'src.utils.logger': log}))
        cls.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Real network forbidden')))
        cls.stack.enter_context(patch('websockets.connect', side_effect=AssertionError('Cloud forbidden')))
        from src.storage.db import DatabaseManager
        cls.DB = DatabaseManager

    def setUp(self):
        self.dir = self.root/self._testMethodName
        self.dir.mkdir()
        self.db = self.DB(self.dir/'isolated.db')
        self.secret = {'url': 'https://wewin.edu.vn/wewin-sales-playbook/', 'title': 'Sales Playbook',
                       'category': 'general', 'content': 'CanaryPrivateMarker consult sales methods. '*8}
        self.public = {'url': 'https://wewin.edu.vn/public-lesson/', 'title': 'English và tiếng Việt',
                       'category': 'materials', 'content': 'PublicLessonMarker học tiếng Anh Relative Clause và Oxford Phonics. '*5,
                       'retrieved_at': '2026-10-26T00:00:00+00:00'}
        self.db.index_records([self.secret, self.public])

    def client(self):
        from fastapi.testclient import TestClient
        from src.storage.db import get_db
        appmod = importlib.import_module('src.api.app')
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(appmod, 'get_db', return_value=self.db))
        stack.enter_context(patch('src.mcp.tools.get_db', return_value=self.db))
        app = appmod.create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(stack.close)
        return stack.enter_context(TestClient(app))

    def test_01_public_search_and_private_cache_preserved(self):
        self.assertTrue(self.db.search('PublicLessonMarker'))
        self.assertEqual(self.db.search('CanaryPrivateMarker'), [])
        with self.db.get_connection() as conn:
            self.assertEqual(conn.execute('SELECT content FROM pages WHERE url=?', (self.secret['url'],)).fetchone()[0], self.secret['content'])
            self.assertEqual(conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'CanaryPrivateMarker'").fetchone()[0], 1)

    def test_02_fallback_also_filters_internal(self):
        self.assertEqual(self.db._fallback_like_search(['CanaryPrivateMarker'], 100), [])

    def test_03_get_page_url_spellings_do_not_bypass(self):
        for url in [self.secret['url'], self.secret['url'].upper(), self.secret['url']+'?utm_source=x',
                    self.secret['url'].replace('sales', '%73ales')]:
            self.assertIsNone(self.db.get_page(url))

    def test_04_rename_internal_url_and_id_cannot_publish(self):
        with self.db.get_connection() as conn:
            conn.execute("UPDATE pages SET url='https://wewin.edu.vn/renamed/',title='Normal lesson',id=999 WHERE url=?", (self.secret['url'],))
        self.assertIsNone(self.db.get_page('https://wewin.edu.vn/renamed/'))
        self.assertEqual(self.db.search('CanaryPrivateMarker'), [])

    def test_05_copy_internal_body_to_new_url_blocked(self):
        self.db.index_records([{**self.secret, 'url':'https://wewin.edu.vn/copy/', 'title':'Normal lesson', 'visibility':'public'}])
        self.assertIsNone(self.db.get_page('https://wewin.edu.vn/copy/'))

    def test_06_in_place_sensitive_edit_blocked_before_query(self):
        with self.db.get_connection() as conn:
            conn.execute("UPDATE pages SET content='Confidential CanaryPrivateMarker' WHERE url=?", (self.public['url'],))
        self.assertIsNone(self.db.get_page(self.public['url']))
        self.assertEqual(self.db.search('CanaryPrivateMarker'), [])

    def test_07_unclassified_direct_insert_fails_closed(self):
        with self.db.get_connection() as conn:
            conn.execute("INSERT INTO pages(url,title,content,retrieved_at) VALUES('https://wewin.edu.vn/raw/','Raw','RawPrivateMarker','now')")
        self.assertEqual(self.db.search('RawPrivateMarker'), [])

    def test_08_rest_and_http_tool_cannot_leak(self):
        client = self.client()
        self.assertEqual(client.get('/page',params={'url':self.secret['url']}).status_code,404)
        for path in ['/search?q=CanaryPrivateMarker','/page?id=1','/.maintenance/phase6a-20261026/before.db']:
            self.assertNotIn(self.secret['content'],client.get(path).text)
        for tool,args in [('wewin_search',{'query':'CanaryPrivateMarker'}),('wewin_get_page',{'url':self.secret['url']})]:
            response=client.post('/api/xiaozhi/tool',json={'tool':tool,'arguments':args})
            self.assertNotIn('CanaryPrivateMarker',response.text)
        self.assertIn('PublicLessonMarker',client.get('/page',params={'url':self.public['url']}).text)

    def test_09_admin_only_cache_and_no_anonymous_export(self):
        client=self.client()
        self.assertIn(client.get('/api/knowledge/pages').status_code,(401,403))
        for path in ['/data/wewin_knowledge.json','/data/wewin_fts.db','/export','/api/export']:
            self.assertIn(client.get(path).status_code,(404,405))

    def test_10_local_mcp_initialize_list_search_and_get_page(self):
        client=self.client()
        with client.websocket_connect('/ws/mcp') as ws:
            calls=[('initialize',{}),('tools/list',{}),('tools/call',{'name':'wewin_search','arguments':{'query':'CanaryPrivateMarker'}}),
                   ('tools/call',{'name':'wewin_get_page','arguments':{'url':self.secret['url']}}),
                   ('tools/call',{'name':'wewin_search','arguments':{'query':'PublicLessonMarker'}})]
            for i,(method,params) in enumerate(calls):
                ws.send_json({'jsonrpc':'2.0','id':i,'method':method,'params':params})
                reply=ws.receive_json();self.assertEqual(reply['id'],i)
                if i==1:
                    from src.mcp.tools import TOOL_DEFINITIONS
                    self.assertEqual({t['name'] for t in reply['result']['tools']},{t['name'] for t in TOOL_DEFINITIONS})
                # An unsuccessful search may echo the submitted query; no cached text may escape.
                self.assertNotIn('consult sales methods',json.dumps(reply))
                if i==4:self.assertIn('PublicLessonMarker',json.dumps(reply))

    def test_11_json_export_contains_public_only(self):
        from src.sync.sync_engine import SyncEngine
        from src.config import settings
        target=self.dir/'export.json'
        with patch.object(settings,'KNOWLEDGE_JSON_PATH',target):
            self.assertTrue(SyncEngine(db=self.db,crawler=object())._export_knowledge_json())
        self.assertNotIn('CanaryPrivateMarker',target.read_text(encoding='utf-8'))

    def test_12_incremental_gate_preserves_good_page(self):
        from src.sync.sync_engine import SyncEngine
        for body in ['tiny','Confidential private text '*20,'<iframe src="https://forms.google.com"></iframe>']:
            crawler=types.SimpleNamespace(crawl_url_detailed=lambda url:{'status':'success','data':{**self.public,'content':body}})
            before=self.db.get_data_fingerprints()
            result,_=SyncEngine(db=self.db,crawler=crawler)._process_url(self.public['url'],self.db.get_existing_hashes(),set())
            self.assertEqual(result,'skipped');self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_13_incremental_seed_shrink_duplicate_guards(self):
        from src.storage.knowledge_policy import result_record,text_hash
        for old,body,hashes in [({**self.public,'source_type':'seed'},self.public['content'],{}),
                ({**self.public,'content':'x'*1000},'x'*150,{}),
                (None,self.public['content'],{text_hash(self.public['content']):['https://wewin.edu.vn/other/']})]:
            record,decision=result_record({'status':'success','data':{**self.public,'content':body}},old,hashes)
            self.assertIsNone(record);self.assertEqual(decision['status'],'review')

    def test_14_incremental_metadata_updates_preserve_fts(self):
        from src.sync.sync_engine import SyncEngine
        page={**self.public,'title':'NewMetadataMarker','category':'newcategory'}
        crawler=types.SimpleNamespace(crawl_url_detailed=lambda url:{'status':'success','data':page})
        result,_=SyncEngine(db=self.db,crawler=crawler)._process_url(page['url'],self.db.get_existing_hashes(),set())
        self.assertEqual(result,'updated');self.assertTrue(self.db.search('NewMetadataMarker'))
        self.assertTrue(self.db.get_fts_status()['consistent'])

    def test_15_footer_is_not_a_lesson(self):
        from src.storage.knowledge_policy import classify
        self.assertEqual(classify(self.public['url'],'Lesson','WEWIN EDUCATION Hotline https://a.test https://b.test')[0],'review')

    def test_16_backup_restore_including_access_tables(self):
        from scripts.server_ops import backup,restore,inspect
        original=inspect(self.db.db_path)
        backup(self.db.db_path,self.dir/'backup.db')
        self.db.index_records([{**self.public,'title':'Changed'}])
        actual=restore(self.dir/'backup.db',self.db.db_path,self.dir/'safety.db',services_stopped=True)
        self.assertEqual(actual['fingerprints'],original['fingerprints'])
        self.assertIsNone(self.db.get_page(self.secret['url']))

    def test_17_restore_refuses_live_sync_or_missing_stop_confirmation(self):
        from scripts.server_ops import backup,restore
        from src.sync.locking import SyncLock,SyncAlreadyRunningError
        backup(self.db.db_path,self.dir/'backup.db')
        with self.assertRaises(ValueError):restore(self.dir/'backup.db',self.db.db_path,self.dir/'safety.db')
        lock=SyncLock(self.dir/'sync.lock');lock.acquire()
        try:
            with self.assertRaises(SyncAlreadyRunningError):restore(self.dir/'backup.db',self.db.db_path,self.dir/'safety.db',True)
        finally:lock.release()

    def test_18_migration_never_changes_original_pages(self):
        from scripts.prepare_knowledge_access import migrate
        before=self.db.get_data_fingerprints()
        migrate(self.db.db_path)
        self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_19_bridge_state_unknown_stale_and_independent(self):
        from src.mcp.bridge_status import read_status,publish
        path=self.dir/'bridge.json'
        with patch.dict(os.environ,{'BRIDGE_STATUS_PATH':str(path)}):
            self.assertEqual(read_status(),'unknown')
            publish('connected');self.assertEqual(read_status(),'connected')
            obj=json.loads(path.read_text());obj['updated_at']=time.time()-60;path.write_text(json.dumps(obj))
            self.assertEqual(read_status(),'unknown')

    def test_20_bridge_log_does_not_echo_remote_payload(self):
        from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
        from src.utils.logger import logger
        stream=io.StringIO();handler=logging.StreamHandler(stream);logger.addHandler(handler);logger.setLevel(logging.INFO)
        async def run():
            bridge=XiaoZhiMcpBridge(endpoint='wss://fixture.invalid',token='')
            await bridge.handle_message(None,'PRIVATE_SECRET_INVALID_JSON')
            await bridge.handle_message(None,json.dumps({'result':{'token':'PRIVATE_SECRET'}}))
        try:asyncio.run(run())
        finally:logger.removeHandler(handler)
        self.assertNotIn('PRIVATE_SECRET',stream.getvalue())
        self.assertNotIn('PRIVATE_SECRET',XiaoZhiMcpBridge.mask_url('wss://user:PRIVATE_SECRET@fixture.invalid/?jwt=PRIVATE_SECRET'))

    def test_21_bridge_backoff_and_cancellation_without_cloud(self):
        from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
        bridge=XiaoZhiMcpBridge(endpoint='wss://fixture.invalid',token='')
        waits=[]
        async def sleep(seconds):
            waits.append(seconds)
            if len(waits)==3:bridge.is_running=False
        with patch('src.mcp.xiaozhi_bridge.publish'),patch('src.mcp.xiaozhi_bridge.websockets.connect',side_effect=OSError('SECRET')),patch('src.mcp.xiaozhi_bridge.asyncio.sleep',side_effect=sleep):
            asyncio.run(bridge.run())
        self.assertEqual(waits,[2,4,8])

    def test_22_transport_spacing_and_pressure_circuit(self):
        from tests.test_sync_reliability import Session,Clock
        from src.crawler.http_client import PoliteHttpClient,CrawlPolicyError
        url='https://wewin.edu.vn/probe/'
        session=Session({url:[(503,'busy',{}),(503,'busy',{}),(503,'busy',{})]});clock=Clock()
        http=PoliteHttpClient(session,sleep=clock.sleep,clock=clock)
        with self.assertRaises(CrawlPolicyError):http.get(url)
        count=len(session.calls)
        with self.assertRaises(CrawlPolicyError):http.get(url)
        self.assertEqual(len(session.calls),count)
        self.assertTrue(all(b['monotonic']-a['monotonic']>=2.05-1e-9 for a,b in zip(http.dispatches,http.dispatches[1:])))

    def test_23_dashboard_never_claims_robot_connected(self):
        from src.config import settings
        response=self.client().get('/api/dashboard/stats',headers={'Authorization':'Bearer '+settings.ADMIN_SYNC_TOKEN})
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['robots'][0]['status'],'unknown')
        self.assertEqual(data['robots'][0]['firmware'],'Unknown')
        self.assertEqual(data['assistants'][0]['model'],'Unknown')
        self.assertFalse(data['sync_engine']['auto_sync_enabled'])
        self.assertEqual(data['database']['public_searchable'],1)

    def test_24_installed_websocket_api_compatibility(self):
        import inspect
        # The live connector itself is mocked; inspect the installed library's class.
        from websockets.asyncio.client import connect
        parameters=inspect.signature(connect).parameters
        self.assertIn('additional_headers',parameters)
        self.assertIn('proxy',parameters)
        self.assertIn('max_size',parameters)

    def test_25_linux_templates_are_private_and_schedule_unarmed(self):
        root=Path(__file__).resolve().parent.parent/'deploy/linux'
        api=(root/'wewin-api.service').read_text()
        self.assertIn('--host 127.0.0.1',api)
        self.assertNotIn('--reload',api)
        for name in ['wewin-api.service','wewin-bridge.service','wewin-sync.service']:
            text=(root/name).read_text()
            for required in ['User=wewin','UMask=0077','ProtectSystem=strict','NoNewPrivileges=true']:
                self.assertIn(required,text)
        env=(root/'server.env.example').read_text()
        for required in ['AUTO_SYNC_ENABLED=false','SYNC_SCHEDULE_ARMED=false','SYNC_SCHEDULER_OWNER=external']:
            self.assertIn(required,env)
        self.assertIn('WakeSystem=false',(root/'wewin-sync.timer').read_text())

    def test_26_incremental_shrink_uses_actual_cached_body(self):
        from src.sync.sync_engine import SyncEngine
        existing = self.db.get_existing_hashes()
        crawler = types.SimpleNamespace(crawl_url_detailed=lambda url: {
            'status': 'success', 'data': {**self.public, 'content': 'z' * 130}})
        before = self.db.get_data_fingerprints()
        outcome, detail = SyncEngine(db=self.db, crawler=crawler)._process_url(
            self.public['url'], existing, set())
        self.assertEqual(outcome, 'skipped')
        self.assertEqual(detail['reason'], 'large_content_shrink_requires_review')
        self.assertEqual(self.db.get_data_fingerprints(), before)

    def test_27_review_cli_help_works_without_pythonpath(self):
        import subprocess
        import sys
        script = Path(__file__).resolve().parent.parent / 'scripts/prepare_knowledge_access.py'
        result = subprocess.run([sys.executable, '-I', '-B', str(script), '--help'],
                                cwd=self.dir, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--database', result.stdout)


if __name__=='__main__':
    unittest.main(verbosity=2)
