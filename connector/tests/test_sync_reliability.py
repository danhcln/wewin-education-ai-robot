"""FIX03A: isolated SQLite, mocked HTTP and real local OS-lock subprocess tests.

Run this module in its own process. No production database or website is used.
"""
import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
import importlib
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self): self.now, self.sleeps = 0, []
    def __call__(self): return self.now
    def sleep(self, delay): self.sleeps.append(delay); self.now += delay


class Session:
    def __init__(self, routes=None): self.routes, self.calls, self.headers = routes or {}, [], {}
    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith('/robots.txt') and url not in self.routes:
            item = (200, 'User-agent: *\nDisallow:\n', {})
        else:
            value = self.routes.get(url)
            if value is None: raise AssertionError('Unexpected mocked URL: ' + url)
            item = value.pop(0) if isinstance(value, list) else value
        if isinstance(item, Exception): raise item
        status, content, headers = item
        response = requests.Response()
        response.status_code, response.url = status, url
        response.headers.update(headers)
        response._content = content.encode('utf-8')
        response._content_consumed = True
        return response


class FakeCrawler:
    def __init__(self, urls=None):
        self.urls = urls or ['https://wewin.edu.vn/fixture-one/']
        self.discoveries, self.calls, self.fail, self.after_page = 0, [], False, None
    def get_batch_urls(self, **kwargs):
        self.discoveries += 1
        return self.urls, 58, len(self.urls), len(self.urls)
    def crawl_url_detailed(self, url):
        self.calls.append(url)
        if self.after_page: self.after_page(url)
        if self.fail: return {'status':'failed','data':None,'reason':'HTTP 503','http_status':503}
        return {'status':'success','http_status':200,'data':{'url':url,'title':'Fixture lesson', 'category':'materials','content':'A meaningful fixture lesson with enough originalword English content. ' * 2}}


class SyncReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack(); cls.addClassCleanup(cls.stack.close)
        cls.temp = Path(cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='wewin-sync-reliability-')))
        cls.stack.enter_context(patch.dict(os.environ, {'DATABASE_PATH':str(cls.temp/'never-used.db'), 'KNOWLEDGE_JSON_PATH':str(cls.temp/'never-used.json'), 'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'','AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','SYNC_SCHEDULER_OWNER':'windows','XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':''}))
        module = types.ModuleType('src.utils.logger'); module.logger = logging.getLogger('sync-isolated')
        module.logger.handlers = [logging.NullHandler()]; module.logger.propagate = False
        cls.stack.enter_context(patch.dict(sys.modules, {'src.utils.logger':module}))
        cls.stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Real HTTP forbidden')))
        cls.stack.enter_context(patch('websockets.connect', side_effect=AssertionError('Cloud forbidden')))
        from src.storage.db import DatabaseManager
        from src.sync.sync_engine import SyncEngine
        from src.sync.locking import SyncLock, SyncAlreadyRunningError
        from src.config import settings
        cls.DB, cls.Engine, cls.Lock, cls.Busy, cls.settings = DatabaseManager, SyncEngine, SyncLock, SyncAlreadyRunningError, settings

    def setUp(self):
        self.case = self.temp / self._testMethodName; self.case.mkdir()
        self.db = self.DB(self.case/'isolated.db')
        self.addCleanup(patch.stopall)
        patch.object(self.settings,'KNOWLEDGE_JSON_PATH',self.case/'knowledge.json').start()

    def engine(self, crawler=None): return self.Engine(db=self.db, crawler=crawler or FakeCrawler())

    def client(self, routes):
        from src.crawler.http_client import PoliteHttpClient
        clock = Clock(); session = Session(routes)
        return PoliteHttpClient(session, sleep=clock.sleep, clock=clock), session, clock

    def test_01_two_processes_compete_for_one_os_lock(self):
        code = """import os,time
from pathlib import Path
from src.sync.locking import SyncLock,SyncAlreadyRunningError
print('READY',flush=True)
while not Path(os.environ['GATE']).exists():time.sleep(.005)
lock=SyncLock(Path(os.environ['LOCK']))
try:
 lock.acquire();print('WON',flush=True);time.sleep(1);lock.release()
except SyncAlreadyRunningError:print('BLOCKED',flush=True)
"""
        env={**os.environ,'GATE':str(self.case/'go'),'LOCK':str(self.case/'sync.lock'),'PYTHONPATH':str(ROOT)}
        children=[]
        try:
            for _ in range(2):
                child=subprocess.Popen([sys.executable,'-B','-u','-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                children.append(child);self.assertEqual(child.stdout.readline().strip(),'READY')
            (self.case/'go').write_text('go')
            results=[c.stdout.readline().strip() for c in children]
            self.assertEqual(sorted(results),['BLOCKED','WON'])
            for child in children:self.assertEqual(child.wait(timeout=5),0)
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                child.stdout.close();child.stderr.close()

    def test_02_live_job_older_than_25_minutes_is_never_unlocked(self):
        owner=self.Lock(self.case/'sync.lock',timeout_minutes=25);owner.acquire()
        try:
            past=1000000000;os.utime(owner.lock_path,(past,past))
            contender=self.Lock(owner.lock_path,timeout_minutes=25)
            self.assertTrue(contender.is_locked())
            with self.assertRaises(self.Busy):contender.acquire()
            with self.assertRaises(self.Busy):contender.recover_stale()
            self.assertTrue(owner.lock_path.exists())
        finally:owner.release()

    def test_03_process_crash_releases_os_lock_and_orphan_is_recovered(self):
        path=self.case/'sync.lock'
        code="from pathlib import Path;from src.sync.locking import SyncLock;import time;lock=SyncLock(Path("+repr(str(path))+"));lock.acquire();print('LOCKED',flush=True);time.sleep(60)"
        child=subprocess.Popen([sys.executable,'-B','-u','-c',code],cwd=ROOT,env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:self.assertEqual(child.stdout.readline().strip(),'LOCKED')
        finally:child.kill();child.wait(timeout=5);child.stdout.close();child.stderr.close()
        self.assertTrue(path.exists())
        lock=self.Lock(path);self.assertFalse(lock.is_locked());lock.acquire();lock.release()
        self.assertFalse(path.exists());self.assertTrue(lock.guard_path.exists())

    def test_04_status_is_read_only_for_stale_and_live_metadata(self):
        path=self.case/'sync.lock';path.write_text(json.dumps({'pid':999999999,'started_at':'old'}))
        before=(path.read_bytes(),path.stat().st_mtime_ns)
        self.assertFalse(self.Lock(path).is_locked())
        self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)
        owner=self.Lock(path);owner.acquire()
        try:
            before=(path.read_bytes(),path.stat().st_mtime_ns,owner.guard_path.stat().st_mtime_ns)
            self.assertTrue(self.Lock(path).is_locked())
            self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns,owner.guard_path.stat().st_mtime_ns),before)
        finally:owner.release()

    def test_05_non_owner_release_and_admin_unlock_cannot_break_live_job(self):
        owner=self.Lock(self.case/'sync.lock');owner.acquire()
        try:
            other=self.Lock(owner.lock_path);self.assertFalse(other.release())
            with self.assertRaises(self.Busy):other.release(force=True)
            self.assertTrue(owner.is_locked())
        finally:owner.release()

    def test_06_corrupt_metadata_needs_explicit_recovery(self):
        path=self.case/'sync.lock';path.write_text('invalid-json')
        lock=self.Lock(path)
        with self.assertRaises(self.Busy):lock.acquire()
        with self.assertRaises(self.Busy):lock.recover_stale()
        self.assertTrue(lock.recover_stale(allow_corrupt=True));lock.acquire();lock.release()

    def test_07_two_sync_engines_cannot_run_concurrently(self):
        entered,release=threading.Event(),threading.Event();first=FakeCrawler()
        first.after_page=lambda url:(entered.set(),release.wait(5))
        engine=self.engine(first);results=[]
        thread=threading.Thread(target=lambda:results.append(engine.run_sync()));thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(self.Busy):self.engine().run_sync()
        finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(results[0].status,'success')

    def test_08_stop_and_resume_preserve_cursor_until_batch_finishes(self):
        urls=['https://wewin.edu.vn/lesson-'+str(i)+'/' for i in range(3)]
        crawler=FakeCrawler(urls);engine=self.engine(crawler);self.db.set_state('crawl_cursor','55')
        crawler.after_page=lambda url:engine.request_stop()
        first=engine.run_sync(max_pages=3)
        self.assertEqual((first.status,first.pages_unprocessed),('interrupted',2))
        self.assertEqual(self.db.get_state('crawl_cursor'),'55')
        crawler.after_page=None
        second=engine.run_sync(max_pages=1);self.assertTrue(second.resumed);self.assertEqual(second.pages_unprocessed,1)
        third=engine.run_sync(max_pages=1);self.assertEqual(third.pages_unprocessed,0)
        self.assertEqual(self.db.get_state('crawl_cursor'),'58');self.assertEqual(crawler.discoveries,1)
        self.assertEqual(len(crawler.calls),3);self.assertTrue(self.db.get_fts_status()['consistent'])

    def test_09_crash_mid_batch_resumes_checkpoint_from_subprocess(self):
        code="""import logging,os
logging.getLogger('wewin_connector').addHandler(logging.NullHandler())
from src.sync.sync_engine import SyncEngine
from src.storage.db import DatabaseManager
class Crawler:
 def get_batch_urls(self,**kwargs):return ['https://wewin.edu.vn/crash-one/','https://wewin.edu.vn/crash-two/'],22,2,2
 def crawl_url_detailed(self,url):
  if url.endswith('two/'):os._exit(7)
  return {'status':'success','data':{'url':url,'title':'Crash fixture','category':'materials','content':'Cached fixture content for crash recovery verification. '*2}}
SyncEngine(DatabaseManager.open_existing(os.environ['CASE_DB']),Crawler()).run_sync()
"""
        env={**os.environ,'CASE_DB':str(self.db.db_path),'PYTHONPATH':str(ROOT)}
        result=subprocess.run([sys.executable,'-B','-c',code],env=env,cwd=ROOT,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,7)
        checkpoint=json.loads(self.db.get_state('sync_checkpoint'));self.assertEqual(checkpoint['offset'],1)
        crawler=FakeCrawler();crawler.get_batch_urls=lambda **kw:(_ for _ in ()).throw(AssertionError('Must resume, not rediscover'))
        report=self.engine(crawler).run_sync();self.assertTrue(report.resumed)
        self.assertEqual(crawler.calls,['https://wewin.edu.vn/crash-two/'])
        self.assertEqual(self.db.get_state('crawl_cursor'),'22');self.assertTrue(self.db.get_fts_status()['consistent'])

    def test_10_http_failure_retains_cached_content_and_fts(self):
        crawler=FakeCrawler();engine=self.engine(crawler);engine.run_sync()
        before=self.db.get_page(crawler.urls[0]);crawler.fail=True
        report=engine.run_sync();after=self.db.get_page(crawler.urls[0])
        self.assertEqual(report.pages_failed,1)
        for key in ('title','content','content_hash','category'):self.assertEqual(before[key],after[key])
        self.assertEqual(after['http_status'],503);self.assertTrue(self.db.search('originalword'))
        self.assertIn(crawler.urls[0],json.loads(self.db.get_state('sync_retry_urls')))

    def test_11_retry_and_exponential_backoff_are_bounded(self):
        url='https://wewin.edu.vn/lesson/'
        http,session,clock=self.client({url:[(503,'busy',{}),(502,'busy',{}),(200,'ok',{})]})
        self.assertEqual(http.get(url).status_code,200);self.assertEqual(http.retry_count,2)
        self.assertEqual(session.calls.count(url),3)
        self.assertIn(1,clock.sleeps);self.assertIn(2,clock.sleeps)

    def test_12_retry_after_is_respected_and_long_deferral_is_not_ignored(self):
        from src.crawler.http_client import CrawlPolicyError
        url='https://wewin.edu.vn/lesson/'
        http,session,clock=self.client({url:[(429,'busy',{'Retry-After':'5'}),(200,'ok',{})]})
        self.assertEqual(http.get(url).status_code,200);self.assertIn(5,clock.sleeps)
        http,session,clock=self.client({url:(429,'busy',{'Retry-After':'999'})})
        with self.assertRaises(CrawlPolicyError):http.get(url)
        self.assertEqual(session.calls.count(url),1)

    def test_13_robots_disallow_and_crawl_delay_are_enforced(self):
        from src.crawler.http_client import CrawlPolicyError
        base='https://wewin.edu.vn'
        http,session,clock=self.client({base+'/robots.txt':(200,'User-agent: *\nDisallow: /private\nCrawl-delay: 3\n',{}),base+'/lesson/':(200,'ok',{})})
        with self.assertRaises(CrawlPolicyError):http.get(base+'/private/')
        self.assertNotIn(base+'/private/',session.calls)
        http.get(base+'/lesson/');self.assertGreaterEqual(sum(clock.sleeps),3)

    def test_14_cross_origin_and_disallowed_redirects_are_blocked(self):
        from src.crawler.http_client import CrawlPolicyError
        url='https://wewin.edu.vn/lesson/'
        http,session,_=self.client({url:(302,'',{'Location':'https://external.invalid/'})})
        with self.assertRaises(CrawlPolicyError):http.get(url)
        self.assertTrue(all(u.startswith('https://wewin.edu.vn/') for u in session.calls))
        for path in ('/allowed/../private/','/allowed/%2e%2e/private/','/allowed%5cprivate/'):
            with self.assertRaises(CrawlPolicyError):http.get('https://wewin.edu.vn'+path)

    def test_15_http_404_is_not_retried(self):
        url='https://wewin.edu.vn/missing/'
        http,session,_=self.client({url:(404,'missing',{})})
        self.assertEqual(http.get(url).status_code,404);self.assertEqual(session.calls.count(url),1)

    def sitemap_routes(self):
        base='https://wewin.edu.vn';ns='http://www.sitemaps.org/schemas/sitemap/0.9'
        index=f'<sitemapindex xmlns="{ns}"><sitemap><loc>{base}/page-sitemap.xml</loc></sitemap><sitemap><loc>{base}/post-sitemap.xml</loc></sitemap></sitemapindex>'
        page=f'<urlset xmlns="{ns}"><url><loc>{base}/lesson-one/</loc></url><url><loc>{base}/lesson-two/</loc></url></urlset>'
        return {base+'/sitemap_index.xml':(200,index,{}),base+'/page-sitemap.xml':(200,page,{}),base+'/post-sitemap.xml':(200,page,{})}

    def test_16_partial_sitemap_failure_never_advances_cursor(self):
        from src.crawler.sitemap_crawler import WeWinCrawler
        routes=self.sitemap_routes();routes['https://wewin.edu.vn/post-sitemap.xml']=(503,'busy',{})
        http,_,_=self.client(routes);self.db.set_state('crawl_cursor','55')
        report=self.engine(WeWinCrawler(http=http)).run_sync()
        self.assertEqual(report.status,'failed');self.assertEqual(self.db.get_state('crawl_cursor'),'55')
        self.assertFalse(self.db.get_state('sync_checkpoint',''))

    def test_17_safe_dry_run_fetches_metadata_only_and_writes_nothing(self):
        from src.crawler.sitemap_crawler import WeWinCrawler
        http,session,_=self.client(self.sitemap_routes());self.db.set_state('crawl_cursor','55')
        before=self.db.get_data_fingerprints();report=self.engine(WeWinCrawler(http=http)).run_sync(dry_run=True,max_pages=2)
        self.assertEqual(report.status,'dry_run');self.assertEqual(report.batch_target_count,2)
        self.assertEqual(self.db.get_data_fingerprints(),before)
        self.assertFalse((self.case/'sync.lock.guard').exists())
        self.assertTrue(all(url.endswith(('.xml','robots.txt')) for url in session.calls))

    def test_18_batch_limit_includes_priority_pages_and_deduplicates(self):
        from src.crawler.sitemap_crawler import WeWinCrawler
        http,_,_=self.client(self.sitemap_routes());crawler=WeWinCrawler(http=http)
        urls,cursor,raw,valid=crawler.get_batch_urls(batch_size=6,cursor=55)
        self.assertLessEqual(len(urls),6);self.assertEqual(len(urls),len(set(urls)))
        self.assertGreater(crawler.discovery_stats['duplicates'],0)

    def test_19_json_export_is_atomic_when_replace_fails(self):
        engine=self.engine();path=self.settings.KNOWLEDGE_JSON_PATH;path.write_text('[{"old":"snapshot"}]')
        original=path.read_bytes()
        with patch('src.sync.sync_engine.os.replace',side_effect=OSError('injected replace failure')):
            self.assertFalse(engine._export_knowledge_json())
        self.assertEqual(path.read_bytes(),original);self.assertEqual(list(self.case.glob('.knowledge-*')),[])
        self.assertTrue(engine._export_knowledge_json())

    def test_20_get_status_and_unlock_endpoint_respect_live_lock(self):
        from fastapi.testclient import TestClient
        routes=importlib.import_module('src.api.routes');appmod=importlib.import_module('src.api.app')
        app=appmod.create_app();app.dependency_overrides[routes.get_db]=lambda:self.db
        path=self.case/'sync.lock';owner=self.Lock(path);owner.acquire()
        headers={'Authorization':'Bearer '+self.settings.ADMIN_SYNC_TOKEN}
        try:
            before=(path.read_bytes(),path.stat().st_mtime_ns)
            with patch.object(routes,'SyncLock',side_effect=lambda:self.Lock(path)):
                with TestClient(app) as client:
                    self.assertEqual(client.get('/sync/status',headers=headers).status_code,200)
                    self.assertEqual(client.post('/sync/unlock',headers=headers).status_code,409)
            self.assertEqual((path.read_bytes(),path.stat().st_mtime_ns),before)
        finally:owner.release()

    def test_21_schedule_gate_prevents_windows_and_internal_overlap(self):
        crawler=FakeCrawler();engine=self.engine(crawler)
        self.assertEqual(engine.run_sync(trigger_type='task_scheduler').status,'disabled')
        with patch.object(self.settings,'SYNC_SCHEDULE_ARMED',True):
            self.assertEqual(engine.run_sync(trigger_type='scheduled').status,'disabled')
        self.assertEqual(crawler.calls,[]);self.assertEqual(crawler.discoveries,0)

    def test_22_scheduler_catches_up_once_and_persists_latest_slot(self):
        from src.sync.scheduler import BackgroundSyncScheduler
        from src.sync.sync_engine import SyncReport
        calls=[]
        fake=types.SimpleNamespace(db=self.db,run_sync=lambda **kw:(calls.append(kw) or SyncReport('start','finish','success',1,1,batch_target_count=1)))
        now=datetime(2026,10,25,9,tzinfo=timezone(timedelta(hours=7)))
        async def run():
            scheduler=BackgroundSyncScheduler()
            self.assertTrue(await scheduler.tick(now));self.assertFalse(await scheduler.tick(now))
            self.assertTrue(await scheduler.tick(now+timedelta(hours=12)))
        with patch.object(self.settings,'SYNC_SCHEDULER_OWNER','internal'),patch.object(self.settings,'SYNC_SCHEDULE_ARMED',True),patch.object(self.settings,'AUTO_SYNC_ENABLED',True),patch('src.sync.scheduler.get_sync_engine',return_value=fake):asyncio.run(run())
        self.assertEqual(len(calls),2)

    def test_23_read_only_database_rejects_writes(self):
        reader=self.DB.open_existing(self.db.db_path,read_only=True)
        with self.assertRaises(sqlite3.OperationalError):reader.set_state('should-not-write','1')
        self.assertIsNone(self.db.get_state('should-not-write'))

    def test_24_canonical_alias_is_reported_not_merged_or_deleted(self):
        from src.crawler.sitemap_crawler import WeWinCrawler
        url='https://wewin.edu.vn/alias/'
        html='<html><head><link rel="canonical" href="https://wewin.edu.vn/canonical/"></head><body><main>'+('Lesson content '*20)+'</main></body></html>'
        http,_,_=self.client({url:(200,html,{'Content-Type':'text/html'})})
        result=WeWinCrawler(http=http).crawl_url_detailed(url)
        self.assertEqual(result['status'],'skipped');self.assertEqual(result['canonical_url'],'https://wewin.edu.vn/canonical/')

    def test_25_cli_probe_is_noop_and_legacy_reset_flag_is_rejected(self):
        before=self.db.get_data_fingerprints()
        result=subprocess.run([sys.executable,'-B',str(ROOT/'run_sync.py'),'--scheduler-probe'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0);self.assertFalse(json.loads(result.stdout)['database_opened'])
        result=subprocess.run([sys.executable,'-B',str(ROOT/'run_sync.py'),'--reset-cursor'],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_26_status_reports_checkpoint_and_does_not_repair_corrupt_state(self):
        from fastapi.testclient import TestClient
        routes=importlib.import_module('src.api.routes');appmod=importlib.import_module('src.api.app')
        app=appmod.create_app();app.dependency_overrides[routes.get_db]=lambda:self.db
        headers={'Authorization':'Bearer '+self.settings.ADMIN_SYNC_TOKEN}
        self.db.set_states({'sync_checkpoint':json.dumps({'version':1,'urls':['a','b','c'],'offset':1}), 'sync_retry_urls':'["retry"]'})
        with patch.object(routes,'SyncLock',side_effect=lambda:self.Lock(self.case/'sync.lock')),TestClient(app) as client:
            before=self.db.get_data_fingerprints();r=client.get('/sync/status',headers=headers)
            self.assertEqual(r.status_code,200);self.assertEqual(r.json()['pending_urls'],2);self.assertEqual(r.json()['retry_urls'],1)
            self.assertEqual(self.db.get_data_fingerprints(),before)
            self.db.set_state('sync_checkpoint','corrupt-json');before=self.db.get_data_fingerprints()
            self.assertFalse(client.get('/sync/status',headers=headers).json()['checkpoint_valid'])
            self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_27_no_new_job_can_clear_an_active_stop_request(self):
        engine=self.engine();engine.lock.acquire()
        try:
            engine.request_stop()
            with self.assertRaises(self.Busy):engine.run_sync()
            self.assertTrue(engine._stop.is_set())
        finally:engine.lock.release()

    def test_28_empty_page_does_not_touch_last_good_retrieval(self):
        crawler=FakeCrawler();engine=self.engine(crawler);engine.run_sync();url=crawler.urls[0]
        before=self.db.get_page(url)
        crawler.crawl_url_detailed=lambda _: {'status':'skipped','data':None,'reason':'iframe_requires_review'}
        report=engine.run_sync()
        self.assertEqual(report.pages_skipped,1);self.assertEqual(self.db.get_page(url),before)
        self.assertTrue(self.db.get_fts_status()['consistent'])

    def test_29_discovery_manifest_is_frozen_until_cycle_finishes(self):
        from src.crawler.sitemap_crawler import WeWinCrawler
        routes=self.sitemap_routes()
        body='<html><head><title>Fixture Lesson</title></head><body><main>'+('Educational lesson content with vocabulary and grammar. '*20)+'</main></body></html>'
        for url in WeWinCrawler.CORE_PRIORITY_URLS+['https://wewin.edu.vn/lesson-one/','https://wewin.edu.vn/lesson-two/']:
            routes[url]=(200,body,{'Content-Type':'text/html'})
        http,session,_=self.client(routes);crawler=WeWinCrawler(http=http);engine=self.engine(crawler)
        self.db.set_state('crawl_cursor','55')
        first=engine.run_sync(max_pages=6)
        self.assertEqual(first.cycle_remaining,1)
        count=sum(url.endswith('.xml') for url in session.calls)
        # A new/failed discovery must not reorder an in-progress cycle.
        routes['https://wewin.edu.vn/post-sitemap.xml']=(503,'unavailable',{})
        second=engine.run_sync(max_pages=6)
        self.assertEqual(second.cycle_remaining,0)
        self.assertEqual(sum(url.endswith('.xml') for url in session.calls),count)
        self.assertEqual(self.db.get_state('sync_cycle'),'')
        self.assertTrue(self.db.get_fts_status()['consistent'])

    def test_30_unarmed_scheduled_cli_does_not_even_open_database(self):
        target=self.case/'must-not-exist.db'
        env={**os.environ,'DATABASE_PATH':str(target),'SYNC_SCHEDULE_ARMED':'false'}
        result=subprocess.run([sys.executable,'-B',str(ROOT/'run_sync.py'),'--trigger','task_scheduler','--execute'],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0);self.assertFalse(json.loads(result.stdout)['database_opened'])
        self.assertFalse(target.exists())

    def test_31_completed_slot_is_deduplicated_inside_job_lock(self):
        crawler=FakeCrawler();engine=self.engine(crawler)
        with patch.object(self.settings,'SYNC_SCHEDULER_OWNER','internal'),patch.object(self.settings,'SYNC_SCHEDULE_ARMED',True):
            first=engine.run_sync(trigger_type='scheduled',scheduled_slot='2026-10-25T08:00:00+07:00')
            self.assertEqual(first.status,'success');before=self.db.get_data_fingerprints()
            second=engine.run_sync(trigger_type='scheduled',scheduled_slot='2026-10-25T08:00:00+07:00')
            self.assertEqual(second.status,'already_completed');self.assertEqual(len(crawler.calls),1)
            self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_32_stop_before_worker_start_is_not_lost(self):
        cancelled=threading.Event();cancelled.set();crawler=FakeCrawler()
        before=self.db.get_data_fingerprints()
        report=self.engine(crawler).run_sync(cancel_event=cancelled)
        self.assertEqual(report.status,'interrupted');self.assertEqual(crawler.calls,[])
        self.assertEqual(self.db.get_data_fingerprints(),before)

    def test_33_scheduler_stop_waits_for_checkpoint_and_lock_release(self):
        from src.sync.scheduler import BackgroundSyncScheduler
        crawler=FakeCrawler(['https://wewin.edu.vn/stop-one/','https://wewin.edu.vn/stop-two/'])
        engine=self.engine(crawler);entered=threading.Event()
        def wait_for_stop(url):
            entered.set()
            if not engine._stop.wait(3):raise AssertionError('Scheduler did not signal its worker')
        crawler.after_page=wait_for_stop
        async def run():
            scheduler=BackgroundSyncScheduler();scheduler._task=asyncio.create_task(scheduler.tick())
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set());await scheduler.stop()
        with patch.object(self.settings,'SYNC_SCHEDULER_OWNER','internal'),patch.object(self.settings,'SYNC_SCHEDULE_ARMED',True),patch.object(self.settings,'AUTO_SYNC_ENABLED',True),patch('src.sync.scheduler.get_sync_engine',return_value=engine):asyncio.run(run())
        self.assertFalse(engine.lock.is_locked())
        self.assertEqual(json.loads(self.db.get_state('sync_checkpoint'))['offset'],1)
        self.assertTrue(self.db.get_fts_status()['consistent'])


if __name__ == '__main__':unittest.main(verbosity=2)
