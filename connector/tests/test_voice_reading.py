"""Phase7A: isolated databases, ASGI/MCP, and injected public-network fixtures.

WEWIN_READING_FIXTURE is a sealed snapshot opened READ ONLY, never migrated.
External requests/Cloud/DNS are forbidden unless explicitly mocked below.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
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
import unicodedata
import unittest
from unittest.mock import MagicMock, patch


class Clock:
    def __init__(self):self.now=0;self.waits=[]
    def __call__(self):return self.now
    def sleep(self,seconds):self.waits.append(seconds);self.now+=seconds


class VoiceReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=contextlib.ExitStack();cls.addClassCleanup(cls.stack.close)
        cls.root=Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='wewin-reading-')))
        cls.stack.enter_context(patch.dict(os.environ,{
            'DATABASE_PATH':str(cls.root/'unused.db'),'KNOWLEDGE_JSON_PATH':str(cls.root/'unused.json'),
            'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),
            'ADMIN_SYNC_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'',
            'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','BRIDGE_STATUS_PATH':str(cls.root/'heartbeat.json')}))
        log=types.ModuleType('src.utils.logger');log.logger=logging.getLogger('phase7a-isolated')
        log.logger.handlers=[logging.NullHandler()];log.logger.propagate=False
        cls.stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':log}))
        cls.stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('External requests forbidden')))
        cls.stack.enter_context(patch('websockets.connect',side_effect=AssertionError('Cloud forbidden')))
        cls.stack.enter_context(patch('socket.getaddrinfo',side_effect=AssertionError('Real DNS forbidden')))
        from src.storage.db import DatabaseManager
        cls.DB=DatabaseManager

    def setUp(self):
        from src.reading.articles import ArticleReader
        self.dir=self.root/self._testMethodName;self.dir.mkdir()
        self.db=self.DB(self.dir/'test.db');self.clock=Clock()
        self.public={'url':'https://wewin.edu.vn/global-talent-test/','title':'Chương trình Global Talent',
                     'category':'general','content':''.join(f'Đoạn {n}: Học tiếng Anh cùng WeWIN và phát triển kỹ năng sáng tạo. ' for n in range(1,50))}
        self.private={'url':'https://wewin.edu.vn/wewin-sales-playbook/','title':'Sales Playbook',
                      'category':'general','content':'PrivateFixtureMarker là dữ liệu nội bộ dành cho nhân viên. '*8}
        self.review={'url':'https://wewin.edu.vn/review-test/','title':'Bài chờ duyệt',
                     'category':'general','content':'ReviewFixtureMarker nội dung cần được xem xét trước khi công bố. '*8}
        self.db.index_records([self.public,self.private,self.review])
        with self.db.get_connection() as conn:
            conn.execute("UPDATE knowledge_access SET visibility='review' WHERE page_id=(SELECT id FROM pages WHERE url=?)",(self.review['url'],))
        self.web=MagicMock();self.reader=ArticleReader(web=self.web,clock=self.clock)

    def client(self,db=None):
        from fastapi.testclient import TestClient
        from src.storage.db import get_db
        db=db or self.db;appmod=importlib.import_module('src.api.app');stack=contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(appmod,'get_db',return_value=db))
        stack.enter_context(patch('src.mcp.tools.get_db',return_value=db))
        stack.enter_context(patch('src.reading.articles.reader',self.reader))
        app=appmod.create_app();app.dependency_overrides[get_db]=lambda:db
        return stack.enter_context(TestClient(app))

    def start(self,**extra):return self.reader.start(self.db,{'url':self.public['url'],**extra})

    def assert_code(self,code,fn,*args,**kw):
        from src.reading.public_web import ReadError
        with self.assertRaises(ReadError) as e:fn(*args,**kw)
        self.assertEqual(e.exception.code,code)

    def web_reader(self,routes=None,resolver=None):
        from src.reading.public_web import PublicWebReader
        calls=[]
        def transport(url,ip,deadline,limit):
            calls.append((url,ip,self.clock()))
            if routes and url in routes:return routes[url]
            if url.endswith('/robots.txt'):return 200,{'content-type':'text/plain'},b'User-agent: *\nDisallow:\n'
            body=('<html><title>Bài tiếng Việt</title><article><p>'+self.public['content']+'</p></article></html>').encode()
            return 200,{'content-type':'text/html; charset=utf-8'},body
        reader=PublicWebReader(resolver=resolver or (lambda *args:['93.184.216.34']),transport=transport,clock=self.clock,sleep=self.clock.sleep)
        return reader,calls

    def test_01_registry_retains_knowledge_reading_youtube_and_audio_prepare_tools(self):
        from src.mcp.tools import TOOL_DEFINITIONS
        expected={'wewin_test_connection','wewin_search','wewin_get_page','wewin_get_programs','wewin_get_contact',
                  'wewin_find_article','wewin_read_article','wewin_continue_reading','wewin_stop_reading','wewin_read_url',
                  'youtube_search','youtube_list_wewin_videos','youtube_control','youtube_get_status',
                  'wewin_prepare_audio'}
        names=[t['name'] for t in TOOL_DEFINITIONS]
        self.assertEqual(set(names),expected);self.assertEqual(len(names),len(expected))

    def test_02_find_public_only(self):
        self.assertEqual(self.reader.find(self.db,{'query':'Global Talent'})['articles'][0]['url'],self.public['url'])
        for q in ['PrivateFixtureMarker','ReviewFixtureMarker']:
            self.assertEqual(self.reader.find(self.db,{'query':q})['articles'],[])

    def test_03_long_vietnamese_roundtrip_all_parts(self):
        from src.reading.articles import speech_text
        part=self.start(chunk_chars=200);body=[part['text']];self.assertGreater(part['total_parts'],2)
        while part['has_more']:
            part=self.reader.continue_reading(self.db,{'reading_id':part['reading_id'],'part':part['next_part']})
            self.assertLessEqual(len(part['text']),200);body.append(part['text'])
        self.assertEqual(' '.join(body),speech_text(self.public['content']))
        self.assertIsNone(part['next_part']);self.assertFalse(part['audio_generated'])

    def test_04_unicode_nfc(self):
        from src.reading.articles import speech_text
        text='Giới thiệu về WeWIN. Tiếng Việt có dấu.'
        self.assertEqual(speech_text(unicodedata.normalize('NFD',text)),text)

    def test_05_unbroken_long_word_is_bounded_without_loss(self):
        from src.reading.articles import chunks
        self.assertEqual(''.join(chunks('ắ'*2500,600)),'ắ'*2500)
        self.assertTrue(all(len(p)<=600 for p in chunks('ắ'*2500,600)))

    def test_06_summary_is_bounded_source_extract_not_session(self):
        r=self.start(mode='summary');self.assertLessEqual(len(r['text']),900)
        self.assertNotIn('reading_id',r);self.assertEqual(len(self.reader.sessions),0)
        self.assertIn(r['text'],self.public['content']);self.assertIn('extractive',r['summary_method'])

    def test_07_continue_retry_does_not_skip_part(self):
        r=self.start();args={'reading_id':r['reading_id'],'part':2}
        a=self.reader.continue_reading(self.db,args);b=self.reader.continue_reading(self.db,args)
        self.assertEqual(a,b);self.assertEqual(a['next_part'],3)

    def test_08_stop_idempotent_and_no_continue(self):
        r=self.start();args={'reading_id':r['reading_id']}
        self.assertEqual(self.reader.stop(args)['status'],'stopped');self.assertEqual(self.reader.stop(args)['status'],'stopped')
        self.assert_code('reading_not_found',self.reader.continue_reading,self.db,{**args,'part':2})

    def test_09_no_global_current_reading_or_guessed_id(self):
        self.start()
        self.assert_code('invalid_reading_id',self.reader.continue_reading,self.db,{'part':2})
        self.assert_code('reading_not_found',self.reader.continue_reading,self.db,{'reading_id':secrets.token_urlsafe(32),'part':2})

    def test_10_two_readers_separate_stop(self):
        a=self.start();b=self.start();self.assertNotEqual(a['reading_id'],b['reading_id'])
        self.reader.stop({'reading_id':a['reading_id']})
        self.assertEqual(self.reader.continue_reading(self.db,{'reading_id':b['reading_id'],'part':2})['part'],2)

    def test_11_ttl_and_process_restart(self):
        from src.reading.articles import ArticleReader
        r=self.start();self.clock.now=901
        self.assert_code('reading_not_found',self.reader.continue_reading,self.db,{'reading_id':r['reading_id'],'part':2})
        self.assert_code('reading_not_found',ArticleReader().continue_reading,self.db,{'reading_id':r['reading_id'],'part':2})

    def test_12_out_of_order_no_advance(self):
        r=self.start();self.assert_code('out_of_order',self.reader.continue_reading,self.db,{'reading_id':r['reading_id'],'part':3})
        self.assertEqual(self.reader.continue_reading(self.db,{'reading_id':r['reading_id'],'part':2})['part'],2)

    def test_13_revoked_publication_blocks_cached_chunks(self):
        r=self.start()
        with self.db.get_connection() as conn:conn.execute("UPDATE knowledge_access SET visibility='review' WHERE page_id=(SELECT id FROM pages WHERE url=?)",(self.public['url'],))
        self.assert_code('not_found',self.reader.continue_reading,self.db,{'reading_id':r['reading_id'],'part':2})
        self.assertEqual(self.reader.sessions,{})

    def test_14_changed_body_or_title_invalidates(self):
        for key in ['content','title']:
            r=self.start();changed={**self.public,key:self.public[key]+' mới'};self.db.index_records([changed])
            self.assert_code('article_changed',self.reader.continue_reading,self.db,{'reading_id':r['reading_id'],'part':2})
            self.db.index_records([self.public])

    def test_15_capacity_and_bounds(self):
        self.reader.max_sessions=1;self.start();self.assert_code('session_capacity',self.start)
        for args in [{'chunk_chars':199},{'chunk_chars':801},{'chunk_chars':True},{'mode':'audio'},{'url':None}]:
            self.assert_code('invalid_arguments',self.start,**args)

    def test_16_parallel_retry_is_atomic(self):
        r=self.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows=list(pool.map(lambda _:self.reader.continue_reading(self.db,{'reading_id':r['reading_id'],'part':2}),range(4)))
        self.assertTrue(all(row==rows[0] for row in rows));self.assertEqual(self.reader.sessions[r['reading_id']].cursor,2)

    def test_17_internal_review_read_and_summary_denied(self):
        for url in [self.private['url'],self.review['url']]:
            for mode in ['read','summary']:self.assert_code('not_found',self.reader.start,self.db,{'url':url,'mode':mode})

    def test_18_external_requires_explicit_request_before_fetch(self):
        self.assert_code('explicit_request_required',self.reader.start,self.db,{'url':'https://example.org/'},external=True)
        self.web.fetch.assert_not_called()

    def test_19_external_in_memory_only_and_continue_no_fetch(self):
        from scripts.server_ops import inspect
        before=inspect(self.db.db_path);self.web.fetch.return_value={**self.public,'url':'https://example.org/article'}
        r=self.reader.start(self.db,{'url':'https://example.org/article','user_requested':True},external=True)
        self.reader.continue_reading(self.db,{'reading_id':r['reading_id'],'part':2})
        self.web.fetch.assert_called_once();self.assertEqual(inspect(self.db.db_path),before)

    def test_20_external_mirror_of_held_content_denied(self):
        for source in [self.private,self.review]:
            self.web.fetch.return_value={**source,'url':'https://example.org/mirror'}
            self.assert_code('publication_review',self.reader.start,self.db,{'url':'https://example.org/mirror','user_requested':True},external=True)

    def test_21_url_and_ip_vectors(self):
        from src.reading.public_web import validate_url,ReadError
        urls=['file:///etc/passwd','ftp://example.org/a','gopher://example.org/','http://localhost/',
              'http://127.0.0.1/','http://127.1/','http://2130706433/','http://0x7f000001/','http://0177.0.0.1/',
              'http://10.1.2.3/','http://172.16.0.1/','http://192.168.1.1/','http://169.254.169.254/',
              'http://100.64.0.1/','http://0.0.0.0/','http://224.0.0.1/','http://[::1]/','http://[::]/',
              'http://[fc00::1]/','http://[fe80::1]/','http://[::ffff:127.0.0.1]/','http://[64:ff9b::7f00:1]/',
              'http://example.local/','http://metadata.google.internal/','http://intranet/',
              'http://user:password@example.org/','https://example.org:8443/','http://example.org\\@127.0.0.1/',
              'https://example.org/%0d%0aHeader','https://example.org/#fragment','https://example.org/?token=private',
              'https://wewin.edu.vn/review-test/','https://WWW.WEWIN.EDU.VN./review-test/']
        for url in urls:
            with self.subTest(url=url),self.assertRaises(ReadError):validate_url(url)
        self.assertEqual(validate_url('https://example.org/bài-viết'),'https://example.org/b%C3%A0i-vi%E1%BA%BFt')

    def test_22_mixed_or_private_dns_never_dispatched(self):
        for ips in [['127.0.0.1'],['93.184.216.34','192.168.1.1'],['::ffff:10.1.1.1']]:
            reader,calls=self.web_reader(resolver=lambda *_,ips=ips:ips)
            self.assert_code('blocked_address',reader.fetch,'https://example.org/article');self.assertEqual(calls,[])

    def test_23_redirect_to_internal_or_wewin_blocked(self):
        for target in ['http://127.0.0.1/admin','https://wewin.edu.vn/wewin-sales-playbook/','http://example.org/downgrade']:
            reader,calls=self.web_reader({'https://example.org/article':(302,{'location':target},b'')})
            from src.reading.public_web import ReadError
            with self.assertRaises(ReadError):reader.fetch('https://example.org/article')
            self.assertFalse(any(c[0]==target for c in calls))

    def test_24_redirect_revalidates_new_origin_dns(self):
        reader,calls=self.web_reader({'https://example.org/article':(302,{'location':'https://other.org/a'},b'')},
                                     resolver=lambda host,*_:['127.0.0.1'] if host=='other.org' else ['93.184.216.34'])
        self.assert_code('blocked_address',reader.fetch,'https://example.org/article')
        self.assertFalse(any('other.org' in c[0] for c in calls))

    def test_25_robots_denial_and_unavailable_fail_closed(self):
        for status,body,code in [(200,b'User-agent: *\nDisallow: /article','robots_denied'),(403,b'','robots_unavailable'),(500,b'','robots_unavailable'),(302,b'','robots_unavailable')]:
            reader,calls=self.web_reader({'https://example.org/robots.txt':(status,{},body)})
            self.assert_code(code,reader.fetch,'https://example.org/article');self.assertEqual(len(calls),1)

    def test_26_rate_and_robots_fractional_delay(self):
        reader,calls=self.web_reader({'https://example.org/robots.txt':(200,{},b'User-agent: *\nDisallow:\nCrawl-delay: 2.5\n')})
        self.assertEqual(reader.fetch('https://example.org/article')['title'],'Bài tiếng Việt')
        self.assertGreaterEqual(calls[1][2]-calls[0][2],2.5)

    def test_27_large_delay_defers_without_article_request(self):
        reader,calls=self.web_reader({'https://example.org/robots.txt':(200,{},b'User-agent: *\nDisallow:\nCrawl-delay: 60')})
        self.assert_code('deferred',reader.fetch,'https://example.org/article');self.assertEqual(len(calls),1)

    def test_28_response_size_type_and_restricted_content(self):
        fixtures=[(200,{'content-type':'text/html'},b'x'*262145,'too_large'),
                  (200,{'content-type':'application/pdf'},b'%PDF','unsupported_type'),
                  (200,{'content-type':'text/html'},b'<html><body><iframe src="https://example.org/form"></iframe></body></html>','empty_content'),
                  (200,{'content-type':'text/html'},b'<html><body><input type="password"></body></html>','access_restricted'),
                  (200,{'content-type':'text/html'},b'<html><body>Verify you are human CAPTCHA</body></html>','access_restricted'),
                  (200,{'content-type':'text/html'},b'<html><script>{"isAccessibleForFree":false}</script><body>Paywall</body></html>','access_restricted'),
                  (403,{},b'login','http_403'),(429,{'retry-after':'120'},b'busy','http_429')]
        for status,headers,body,code in fixtures:
            reader,calls=self.web_reader({'https://example.org/article':(status,headers,body)})
            self.assert_code(code,reader.fetch,'https://example.org/article')

    def test_29_retry_after_no_early_retry(self):
        reader,calls=self.web_reader({'https://example.org/article':(429,{'retry-after':'120'},b'')})
        self.assert_code('http_429',reader.fetch,'https://example.org/article');n=len(calls)
        self.assert_code('deferred',reader.fetch,'https://example.org/article');self.assertEqual(len(calls),n)

    def test_30_redirect_loop_limit(self):
        reader,calls=self.web_reader({'https://example.org/article':(302,{'location':'/article'},b'')})
        self.assert_code('redirect_limit',reader.fetch,'https://example.org/article');self.assertEqual(len(calls),5)

    def test_31_same_host_rebinding_second_dns_blocked(self):
        n=[0]
        def resolver(*_):n[0]+=1;return ['93.184.216.34'] if n[0]==1 else ['127.0.0.1']
        reader,calls=self.web_reader(resolver=resolver)
        self.assert_code('blocked_address',reader.fetch,'https://example.org/article');self.assertEqual(len(calls),1)

    def test_32_socket_pinned_numeric_ip_and_tls_hostname(self):
        from src.reading.public_web import PinnedConnection
        sock=MagicMock();sock.getpeername.return_value=('93.184.216.34',443);ctx=MagicMock()
        with patch('src.reading.public_web.socket.socket',return_value=sock),patch('src.reading.public_web.ssl.create_default_context',return_value=ctx):
            conn=PinnedConnection('example.org',443,'93.184.216.34',True,3);conn.connect()
        sock.connect.assert_called_once_with(('93.184.216.34',443));ctx.wrap_socket.assert_called_once_with(sock,server_hostname='example.org')

    def test_33_peer_ip_private_denied(self):
        from src.reading.public_web import PinnedConnection
        sock=MagicMock();sock.getpeername.return_value=('127.0.0.1',443)
        with patch('src.reading.public_web.socket.socket',return_value=sock):
            self.assert_code('blocked_address',PinnedConnection('example.org',443,'93.184.216.34',False,3).connect)

    def test_34_transport_size_compression_and_stream_limits(self):
        from src.reading.public_web import pinned_request
        import time
        for headers,payload,code in [([('Content-Length','999999')],b'','too_large'),
                                      ([('Content-Encoding','br')],b'','unsupported_encoding'),([],b'x'*101,'too_large')]:
            response=MagicMock();response.status=200;response.getheaders.return_value=headers
            response.isclosed.return_value=False
            response.read1.side_effect=[payload,b''];conn=MagicMock();conn.getresponse.return_value=response
            with patch('src.reading.public_web.PinnedConnection',return_value=conn):
                self.assert_code(code,pinned_request,'https://example.org/','93.184.216.34',time.monotonic()+15,100)
            conn.close.assert_called()

    def test_35_busy_reader_fails_without_network(self):
        reader,calls=self.web_reader();reader._lock.acquire()
        try:self.assert_code('busy',reader.fetch,'https://example.org/article')
        finally:reader._lock.release()
        self.assertEqual(calls,[])

    def test_36_http_api_and_ws_mcp_read_continue_stop(self):
        client=self.client()
        r=client.post('/api/xiaozhi/tool',json={'tool':'wewin_read_article','arguments':{'url':self.public['url']}}).json()['data']
        self.assertEqual(r['part'],1)
        with client.websocket_connect('/ws/mcp') as ws:
            for i,(tool,args) in enumerate([('wewin_continue_reading',{'reading_id':r['reading_id'],'part':2}),('wewin_stop_reading',{'reading_id':r['reading_id']})]):
                ws.send_json({'id':i,'method':'tools/call','params':{'name':tool,'arguments':args}})
                result=json.loads(ws.receive_json()['result']['content'][0]['text'])
                self.assertEqual(result['status'],'ok' if i==0 else 'stopped')
        self.assertEqual(client.get('/health').status_code,200)
        self.assertEqual(client.get('/api/mcp/tools').json()['total'],15)

    def test_37_bridge_dispatch_new_and_legacy(self):
        from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
        class Socket:
            def __init__(self):self.messages=[]
            async def send(self,text):self.messages.append(json.loads(text))
        async def run():
            bridge=XiaoZhiMcpBridge(endpoint='ws://fixture.invalid/',token='');ws=Socket()
            with patch('src.mcp.tools.get_db',return_value=self.db),patch('src.reading.articles.reader',self.reader):
                for i,(tool,args) in enumerate([('wewin_test_connection',{}),('wewin_read_article',{'url':self.public['url']})]):
                    await bridge.handle_message(ws,json.dumps({'id':i,'method':'tools/call','params':{'name':tool,'arguments':args}}))
            self.assertEqual(ws.messages[0]['result']['content'][0]['text'],'WeWIN MCP OK')
            self.assertEqual(json.loads(ws.messages[1]['result']['content'][0]['text'])['part'],1)
        asyncio.run(run())

    def test_38_current_22_held_pages_all_read_paths(self):
        from src.reading.articles import execute_reading_tool
        from scripts.server_ops import inspect
        fixture=os.environ.get('WEWIN_READING_FIXTURE')
        if not fixture:self.fail('Set WEWIN_READING_FIXTURE to a sealed snapshot, never production')
        db=self.DB.open_existing(Path(fixture),read_only=True);before=inspect(db.db_path)
        with db.get_connection() as conn:
            held=[dict(r) for r in conn.execute("SELECT p.url,p.content FROM pages p JOIN knowledge_access a ON a.page_id=p.id WHERE a.visibility!='public'")]
        self.assertEqual(len(held),22);client=self.client(db)
        with client.websocket_connect('/ws/mcp') as ws:
            for i,row in enumerate(held):
                for mode in ['read','summary']:
                    args={'url':row['url'],'mode':mode}
                    direct=execute_reading_tool('wewin_read_article',args,db)
                    self.assertEqual(direct['status'],'not_found')
                    result=client.post('/api/xiaozhi/tool',json={'tool':'wewin_read_article','arguments':args}).json()['data']
                    self.assertEqual(result['status'],'not_found')
                    ws.send_json({'id':i,'method':'tools/call','params':{'name':'wewin_read_article','arguments':args}})
                    self.assertEqual(json.loads(ws.receive_json()['result']['content'][0]['text'])['status'],'not_found')
                from src.reading.public_web import validate_url
                self.assert_code('use_wewin_cache',validate_url,row['url'])
                if row['content'].strip():self.assert_code('publication_review',self.reader._check_external_copy,db,' '.join(unicodedata.normalize('NFC',row['content']).split()))
        self.assertEqual(inspect(db.db_path),before)

    def test_39_bad_arguments_return_bounded_error(self):
        from src.reading.articles import execute_reading_tool
        for name,args in [('wewin_find_article',{'query':'x'*201}),('wewin_continue_reading',{'reading_id':'guess','part':2}),('wewin_read_article',['wrong'])]:
            out=execute_reading_tool(name,args,self.db);self.assertNotEqual(out['status'],'ok');self.assertLess(len(json.dumps(out)),500)

    def test_40_sentence_boundary_preserves_hard_max(self):
        from src.reading.articles import chunks
        text=('Câu đầu. '+'Câu tiếng Việt khá dài để đọc. '*20).strip()
        parts=chunks(text,200);self.assertEqual(' '.join(parts),text);self.assertTrue(all(len(s)<=200 for s in parts))

    def test_41_punctuation_at_limit_does_not_make_oversize_chunk(self):
        from src.reading.articles import chunks
        for n in [200,600,800]:self.assertTrue(all(len(p)<=n for p in chunks('ắ'*n+'. Câu sau.',n)))

    def test_42_ambiguous_path_and_port_zero_denied(self):
        from src.reading.public_web import validate_url,ReadError
        for path in ['/public/../private','/public/%2e%2e/private','/public/%252e%252e/private','/public%2fprivate']:
            with self.assertRaises(ReadError):validate_url('https://example.org'+path)
        self.assert_code('blocked_port',validate_url,'https://example.org:0/')

    def test_43_deadline_and_invalid_robots_html(self):
        reader,calls=self.web_reader({'https://example.org/robots.txt':(200,{},b'<html>CAPTCHA</html>')})
        self.assert_code('robots_unavailable',reader.fetch,'https://example.org/article')
        reader,calls=self.web_reader()
        transport=reader.transport
        def slow(*args):self.clock.now+=16;return transport(*args)
        reader.transport=slow
        self.assert_code('timeout',reader.fetch,'https://example.org/article')

    def test_44_dns_resolver_rejects_mixed_records(self):
        from src.reading.public_web import resolve_public
        records=[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('10.0.0.1',443))]
        with patch('src.reading.public_web.socket.getaddrinfo',return_value=records):
            self.assert_code('blocked_address',resolve_public,'example.org',443,1)

    def test_45_source_reported_on_external_failure_without_credentials(self):
        from src.reading.articles import execute_reading_tool
        from src.reading.public_web import ReadError
        self.web.fetch.side_effect=ReadError('http_403','Nguồn từ chối truy cập.')
        with patch('src.reading.articles.reader',self.reader):
            r=execute_reading_tool('wewin_read_url',{'url':'https://example.org/article','user_requested':True},self.db)
        self.assertEqual(r['source_url'],'https://example.org/article');self.assertEqual(r['status'],'http_403')

    def test_46_real_cache_title_match_finds_ielts_program(self):
        fixture=Path(os.environ['WEWIN_READING_FIXTURE']);db=self.DB.open_existing(fixture,read_only=True)
        rows=self.reader.find(db,{'query':'Tóm tắt chương trình luyện IELTS của WeWIN'})['articles']
        self.assertEqual(rows[0]['url'],'https://wewin.edu.vn/luyen-ielts-cung-wewin-education/')
        rows=self.reader.find(db,{'query':'Global Talent'})['articles']
        self.assertIn('wewin-global-talent-',rows[0]['url'])

    def test_47_closed_empty_response_never_touches_closed_socket(self):
        from src.reading.public_web import pinned_request
        import time
        response=MagicMock();response.status=200;response.getheaders.return_value=[('Content-Length','0')]
        response.isclosed.return_value=True
        conn=MagicMock();conn.getresponse.return_value=response;conn.sock.settimeout.side_effect=OSError(10038,'closed')
        with patch('src.reading.public_web.PinnedConnection',return_value=conn):
            status,headers,body=pinned_request('https://example.org/','93.184.216.34',time.monotonic()+15,100)
        self.assertEqual(body,b'');conn.sock.settimeout.assert_not_called()

    def test_48_completed_response_stops_before_next_socket_timeout(self):
        from src.reading.public_web import pinned_request
        import time
        response=MagicMock();response.status=200;response.getheaders.return_value=[('Content-Length','3')]
        response.isclosed.side_effect=[False,True];response.read1.return_value=b'abc'
        conn=MagicMock();conn.getresponse.return_value=response
        with patch('src.reading.public_web.PinnedConnection',return_value=conn):
            status,headers,body=pinned_request('https://example.org/','93.184.216.34',time.monotonic()+15,100)
        self.assertEqual(body,b'abc');self.assertEqual(conn.sock.settimeout.call_count,1)

    def test_49_gzip_success_and_decompression_bomb_bounded(self):
        from src.reading.public_web import pinned_request
        import gzip,time
        for data,code in [(b'Vietnamese text. '*4,None),(b'x'*10000,'too_large')]:
            payload=gzip.compress(data);response=MagicMock();response.status=200
            response.getheaders.return_value=[('Content-Encoding','gzip')]
            response.isclosed.side_effect=[False,True];response.read1.return_value=payload
            conn=MagicMock();conn.getresponse.return_value=response
            with patch('src.reading.public_web.PinnedConnection',return_value=conn):
                args=('https://example.org/','93.184.216.34',time.monotonic()+15,100)
                if code:self.assert_code(code,pinned_request,*args)
                else:self.assertEqual(pinned_request(*args)[2],data)

    def test_50_http_external_tool_uses_same_ephemeral_sessions(self):
        self.web.fetch.return_value={**self.public,'url':'https://example.org/article'};client=self.client()
        response=client.post('/api/xiaozhi/tool',json={'tool':'wewin_read_url','arguments':{'url':'https://example.org/article','user_requested':True}})
        state=response.json()['data'];self.assertEqual(state['source_kind'],'external')
        response=client.post('/api/xiaozhi/tool',json={'tool':'wewin_continue_reading','arguments':{'reading_id':state['reading_id'],'part':2}})
        self.assertEqual(response.json()['data']['part'],2);self.web.fetch.assert_called_once()

    def test_51_dns_timeout_and_capacity_are_bounded(self):
        from src.reading.public_web import resolve_public
        from concurrent.futures import TimeoutError
        pool=MagicMock();pool.submit.return_value.result.side_effect=TimeoutError()
        slots=MagicMock();slots.acquire.return_value=True
        with patch('src.reading.public_web._DNS_POOL',pool),patch('src.reading.public_web._DNS_SLOTS',slots):
            self.assert_code('timeout',resolve_public,'example.org',443,.1)
            pool.submit.return_value.result.assert_called_once_with(timeout=.1)
        slots.acquire.return_value=False
        with patch('src.reading.public_web._DNS_SLOTS',slots):
            self.assert_code('busy',resolve_public,'example.org',443,.1)


if __name__=='__main__':unittest.main(verbosity=2)
