"""Resource benchmark on isolated SQLite copies and loopback fixtures only.

No scheduler, production Cloud credentials, external crawl, or public listener.
Windows results are not Linux capacity certification. See the generated evidence.
"""
import argparse
import asyncio
from collections import defaultdict
from contextlib import suppress, closing
import html
import json
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import statistics
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values)-1)*q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi]-values[lo])*(pos-lo)


class Recorder:
    def __init__(self, directory, db):
        self.directory, self.db = directory, db
        self.roles, self.phase, self.samples = {}, 'initialization', []
        self.stop = threading.Event()
        self.previous = {}
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.started = time.perf_counter()

    def run(self):
        psutil.cpu_percent()
        with (self.directory/'samples.jsonl').open('w', encoding='utf-8') as stream:
            while not self.stop.is_set():
                now = time.perf_counter()
                row = {'t':now-self.started, 'phase':self.phase, 'roles':{},
                       'host_cpu_pct':psutil.cpu_percent(),
                       'host_available_bytes':psutil.virtual_memory().available}
                for role, pid in list(self.roles.items()):
                    totals = {'rss_bytes':0,'private_bytes':0,'cpu_pct_one_core':0,
                              'read_bytes':0,'write_bytes':0,'processes':0}
                    try:
                        proc = psutil.Process(pid)
                        children = [proc, *proc.children(recursive=True)]
                    except psutil.Error:
                        children = []
                    for process in children:
                        try:
                            memory = process.memory_info()
                            cpu = process.cpu_times()
                            used = cpu.user+cpu.system
                            key = (process.pid, process.create_time())
                            previous = self.previous.get(key)
                            self.previous[key] = (now, used)
                            totals['cpu_pct_one_core'] += max(0, (used-previous[1])/(now-previous[0])*100) if previous else 0
                            totals['rss_bytes'] += memory.rss
                            totals['private_bytes'] += getattr(memory,'private',memory.rss)
                            io = process.io_counters()
                            totals['read_bytes'] += io.read_bytes
                            totals['write_bytes'] += io.write_bytes
                            totals['processes'] += 1
                        except psutil.Error:
                            pass
                    row['roles'][role] = totals
                sizes = {}
                for suffix in ('','-wal','-shm'):
                    path = Path(str(self.db)+suffix)
                    try: sizes['db'+suffix] = path.stat().st_size
                    except OSError: sizes['db'+suffix] = 0
                for role in ('api','bridge'):
                    for part in ('stdout.log','logs/connector.log'):
                        path = self.directory/role/part
                        try: sizes[role+'/'+part] = path.stat().st_size
                        except OSError: sizes[role+'/'+part] = 0
                row['sizes'] = sizes
                row['harness_rss_bytes'] = psutil.Process().memory_info().rss
                self.samples.append(row)
                stream.write(json.dumps(row)+'\n')
                stream.flush()
                self.stop.wait(0.5)


class Broker:
    def __init__(self):
        self.ws = None
        self.ready = asyncio.Event()
        self.pending = {}
        self.serial = 0
        self.send_lock = asyncio.Lock()
        self.traffic = defaultdict(int)
        self.wire_instrumented = False

    async def handler(self, ws):
        self.ws = ws
        # Measure compressed WebSocket framing at the fixture transport boundary.
        try:
            original_write = ws.transport.write
            original_received = ws.data_received
            def write(data):
                self.traffic['ws_frame_to_bridge'] += len(data)
                return original_write(data)
            def received(data):
                self.traffic['ws_frame_from_bridge'] += len(data)
                return original_received(data)
            ws.transport.write = write
            ws.data_received = received
            self.wire_instrumented = True
        except (AttributeError, TypeError):
            self.wire_instrumented = False
        self.ready.set()
        try:
            async for raw in ws:
                self.traffic['json_from_bridge'] += len(raw.encode())
                data = json.loads(raw)
                future = self.pending.pop(data.get('id'), None)
                if future and not future.done():
                    future.set_result(data)
        finally:
            for future in self.pending.values():
                if not future.done():future.set_exception(ConnectionError('Fixture connection closed'))
            self.pending.clear()

    async def rpc(self, method, params):
        async with self.send_lock:
            self.serial += 1
            number = self.serial
            future = asyncio.get_running_loop().create_future()
            self.pending[number] = future
            raw = json.dumps({'jsonrpc':'2.0','id':number,'method':method,'params':params},ensure_ascii=False)
            self.traffic['json_to_bridge'] += len(raw.encode())
            await self.ws.send(raw)
        try:
            result = await asyncio.wait_for(future, 30)
            if 'error' in result or result.get('result',{}).get('isError'):
                raise RuntimeError('MCP error response')
            return result
        finally:
            self.pending.pop(number,None)


def worker(directory, database, kind, count):
    """Run only against an explicit copy. External requests are forbidden."""
    directory, database = Path(directory), Path(database)
    assert database.resolve().is_relative_to(directory.resolve())
    from src.storage.db import DatabaseManager
    db = DatabaseManager.open_existing(database)
    cpu_start = psutil.Process().cpu_times()
    started = time.perf_counter()
    if kind == 'sql':
        import sqlite3
        queries = ['Oxford Phonics','tiếng Anh','IELTS','Cambridge','Relative Clause','học phí']
        output = {}
        for mode in ('raw_fts_diagnostic','public_search','public_like_fallback'):
            latencies=[]; index=0;begin=time.perf_counter()
            while time.perf_counter()-begin < (2 if count<20 else 6) and index<5000:
                query=queries[index%len(queries)];t=time.perf_counter()
                if mode=='raw_fts_diagnostic':
                    with closing(sqlite3.connect(database)) as conn:
                        conn.execute('SELECT rowid FROM pages_fts WHERE pages_fts MATCH ? LIMIT 4',(' OR '.join('"'+x+'"' for x in query.split()),)).fetchall()
                elif mode=='public_search':db.search(query,4)
                else:db._fallback_like_search(query.split(),4)
                latencies.append((time.perf_counter()-t)*1000);index+=1
            output[mode]={'operations':index,'elapsed':time.perf_counter()-begin,
                          'mean_ms':statistics.mean(latencies),'p95_ms':percentile(latencies,.95),'max_ms':max(latencies)}
        result={'kind':kind,'modes':output,'raw_fts_not_a_public_endpoint':True}
    else:
        import requests
        from unittest.mock import patch
        from src.crawler.http_client import PoliteHttpClient
        from src.crawler.sitemap_crawler import WeWinCrawler
        from src.sync.sync_engine import SyncEngine
        with db.get_connection() as conn:
            rows=[dict(r) for r in conn.execute("SELECT * FROM public_pages WHERE source_type='scraped' AND length(content) BETWEEN 300 AND 10000 AND url NOT LIKE '%oxford-phonics%' ORDER BY id LIMIT ?",(count,))]
        urls=[r['url'] for r in rows];lookup={r['url']:r for r in rows}
        sent=[];attempts=defaultdict(int)
        class Session:
            headers={}
            def get(self,url,**kwargs):
                attempts[url]+=1
                if url.endswith('/robots.txt'):
                    status,body,ctype=200,'User-agent: *\nDisallow:\nCrawl-delay: 2\n','text/plain'
                else:
                    assert url in lookup, 'Unexpected fixture URL'
                    index=urls.index(url);row=lookup[url]
                    if index==0 and attempts[url]==1:status,body=503,'fixture busy'
                    elif index==1:status,body=404,'fixture missing'
                    elif index==2:status,body=200,'<html><article><iframe src="https://example.invalid/form"></iframe></article></html>'
                    else:
                        status=200
                        body='<html><head><title>'+html.escape(row['title']+' [benchmark]')+'</title><link rel="canonical" href="'+html.escape(url)+'"></head><body><article class="entry-content"><p>'+html.escape(row['content'])+'</p></article></body></html>'
                    ctype='text/html; charset=utf-8'
                response=requests.Response();response.status_code=status;response.url=url
                response.headers.update({'Content-Type':ctype});response._content=body.encode();response._content_consumed=True
                sent.append({'status':status,'response_body_bytes':len(response.content)})
                return response
        http=PoliteHttpClient(session=Session())
        crawler=WeWinCrawler(http=http)
        crawler.get_batch_urls=lambda **kw:(urls,55,len(urls),len(urls))
        with patch('requests.sessions.Session.request',side_effect=AssertionError('External network forbidden')):
            report=SyncEngine(db=db,crawler=crawler).run_sync(trigger_type='benchmark_fixture',max_pages=count)
        with db.get_connection() as conn:
            for index in (1,2):
                if len(urls)>index:
                    row=dict(conn.execute('SELECT * FROM pages WHERE url=?',(urls[index],)).fetchone())
                    for key in ('content','title','category','content_hash'):assert row[key]==lookup[urls[index]][key]
        result={'kind':kind,'report':report.to_dict(),'http_attempts':len(sent),
                'fixture_body_bytes':sum(r['response_body_bytes'] for r in sent),
                'retry_count':http.retry_count,'external_network_bytes':0,'failed_empty_cache_preserved':True}
    cpu_end=psutil.Process().cpu_times()
    result.update(elapsed_seconds=time.perf_counter()-started,
                  cpu_seconds=(cpu_end.user+cpu_end.system)-(cpu_start.user+cpu_start.system),
                  rss_bytes=psutil.Process().memory_info().rss,
                  private_bytes=getattr(psutil.Process().memory_info(),'private',0))
    save(directory/(kind+'-worker-result.json'),result)
    print(json.dumps({'worker':kind,'elapsed':result['elapsed_seconds']}),flush=True)


async def benchmark(snapshot, directory, smoke=False):
    import httpx
    from websockets.asyncio.server import serve
    from scripts.server_ops import backup,inspect
    from scripts.rotate_admin_token import restrict_directory
    directory=Path(directory).resolve();snapshot=Path(snapshot).resolve(strict=True)
    if directory.exists() or directory.is_relative_to(ROOT/'data') or directory.is_relative_to(ROOT/'frontend'):
        raise ValueError('Use a new private benchmark directory')
    restrict_directory(directory)
    db=directory/'benchmark.db';backup(snapshot,db)
    baseline=inspect(db);save(directory/'baseline.json',baseline)
    from src.storage.db import DatabaseManager
    readonly=DatabaseManager.open_existing(db,read_only=True)
    with readonly.get_connection() as conn:
        pages=[r[0] for r in conn.execute('SELECT url FROM public_pages ORDER BY id LIMIT 8')]
    token=secrets.token_urlsafe(32)
    base_env={**os.environ,'DATABASE_PATH':str(db),'KNOWLEDGE_JSON_PATH':str(directory/'public-export.json'),
              'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'',
              'XIAOZHI_MCP_TOKEN':token,'XIAOZHI_MCP_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT_FILE':'',
              'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','SYNC_SCHEDULER_OWNER':'external',
              'DEBUG':'false','CRAWLER_DELAY_SECONDS':'2.05','CRAWLER_RETRY_BACKOFF_SECONDS':'2',
              'BRIDGE_STATUS_PATH':str(directory/'bridge-status.json'),'PYTHONUNBUFFERED':'1','PYTHONDONTWRITEBYTECODE':'1'}
    recorder=Recorder(directory,db);recorder.thread.start()
    children=[];streams=[];phases=[];operations=[];broker=Broker();http_traffic=defaultdict(int)
    def spawn(role,args,env):
        cwd=directory/role;cwd.mkdir(exist_ok=True)
        stream=(cwd/'stdout.log').open('wb');streams.append(stream)
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        process=subprocess.Popen(args,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,**flags)
        children.append(process);recorder.roles[role]=process.pid
        return process
    async def phase(name,action):
        recorder.phase=name;begin=time.perf_counter()
        before=dict(broker.traffic);before_http=dict(http_traffic);initial=len(operations)
        print(json.dumps({'event':'phase_start','phase':name}),flush=True)
        await action()
        end=time.perf_counter();part=operations[initial:]
        durations=[r['latency_ms'] for r in part if not r['error']]
        summary={'name':name,'start':begin-recorder.started,'end':end-recorder.started,'duration':end-begin,
                 'operations':len(part),'errors':sum(bool(r['error']) for r in part),
                 'throughput_rps':len(part)/(end-begin),
                 'latency_mean_ms':statistics.mean(durations) if durations else None,
                 'latency_p50_ms':percentile(durations,.5),'latency_p95_ms':percentile(durations,.95),
                 'latency_max_ms':max(durations) if durations else None,
                 'ws_bytes':{k:broker.traffic[k]-before.get(k,0) for k in broker.traffic},
                 'http_bytes':{k:http_traffic[k]-before_http.get(k,0) for k in http_traffic}}
        phases.append(summary);save(directory/'phases.json',phases)
        save(directory/'operations.json',operations)
        print(json.dumps({'event':'phase_end',**summary}),flush=True)
    queries=['tiếng Anh','Oxford Phonics','IELTS','Cambridge','Relative Clause','học phí','fixture_unmatched_zz']
    def operation(index):
        mod=index%10
        if mod<7:return 'wewin_search',{'query':queries[mod],'limit':3}
        if mod<9:return 'wewin_get_page',{'url':pages[index%len(pages)]}
        return ('wewin_get_contact',{}) if (index//10)%2 else ('wewin_get_programs',{'age':9})
    async def load(channel,clients,duration,interval):
        start=time.perf_counter();deadline=start+duration
        async def client(number):
            i=0;next_at=start
            while time.perf_counter()<deadline:
                if interval:await asyncio.sleep(max(0,next_at-time.perf_counter()))
                if time.perf_counter()>=deadline:break
                name,args=operation(i+number);begin=time.perf_counter();error=''
                try:
                    if channel=='mcp':await broker.rpc('tools/call',{'name':name,'arguments':args})
                    else:
                        path,params=('/search',{'q':args['query'],'limit':3}) if name=='wewin_search' else ('/page',{'url':args['url']}) if name=='wewin_get_page' else ('/contact',{}) if name=='wewin_get_contact' else ('/programs',args)
                        response=await api_client.get(path,params=params)
                        response.raise_for_status()
                        http_traffic['response_body']+=response.num_bytes_downloaded
                        http_traffic['request_body']+=len(response.request.content)
                        http_traffic['headers_estimate']+=sum(len(k)+len(v)+4 for k,v in response.headers.raw)+sum(len(k)+len(v)+4 for k,v in response.request.headers.raw)+len(response.request.url.raw_path)+48
                except Exception as exc:error=type(exc).__name__
                operations.append({'t':begin-recorder.started,'phase':recorder.phase,'channel':channel,
                                   'client':number,'tool':name,'latency_ms':(time.perf_counter()-begin)*1000,'error':error})
                i+=1
                if interval:
                    next_at=start+i*interval
                    if next_at<time.perf_counter():
                        i=max(i,math.ceil((time.perf_counter()-start)/interval));next_at=start+i*interval
        await asyncio.gather(*(client(n) for n in range(clients)))
    try:
        async with serve(broker.handler,'127.0.0.1',0,max_size=1024*1024) as server:
            ws_port=server.sockets[0].getsockname()[1]
            with socket.socket() as free:
                free.bind(('127.0.0.1',0));api_port=free.getsockname()[1]
            env={**base_env,'XIAOZHI_MCP_ENDPOINT':f'ws://127.0.0.1:{ws_port}/mcp/'}
            startup=time.perf_counter()
            api=spawn('api',[sys.executable,'-B','-m','uvicorn','src.api.app:app','--app-dir',str(ROOT),'--host','127.0.0.1','--port',str(api_port),'--workers','1','--loop','asyncio','--http','h11','--no-access-log'],env)
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{api_port}',timeout=30,trust_env=False,limits=httpx.Limits(max_connections=20,max_keepalive_connections=20)) as api_client:
                while True:
                    try:
                        response=await api_client.get('/health')
                        if response.status_code==200 and response.json()['database_ok']:break
                    except httpx.HTTPError:pass
                    if api.poll() is not None or time.perf_counter()-startup>30:raise RuntimeError('API startup failed')
                    await asyncio.sleep(.1)
                api_ready=time.perf_counter()-startup
                bridge_started=time.perf_counter()
                bridge=spawn('bridge',[sys.executable,'-B',str(ROOT/'run_bridge.py')],env)
                await asyncio.wait_for(broker.ready.wait(),30)
                await broker.rpc('initialize',{})
                tools=await broker.rpc('tools/list',{})
                from src.mcp.tools import TOOL_DEFINITIONS
                assert {t['name'] for t in tools['result']['tools']}=={t['name'] for t in TOOL_DEFINITIONS}
                bridge_ready=time.perf_counter()-bridge_started
                cold=time.perf_counter();await broker.rpc('tools/call',{'name':'wewin_search','arguments':{'query':'Oxford Phonics'}})
                startup_info={'api_spawn_to_health_seconds':api_ready,'bridge_spawn_to_initialize_seconds':bridge_ready,'first_bridge_search_ms':(time.perf_counter()-cold)*1000,'os_disk_cache_cold':False,'wire_instrumented':broker.wire_instrumented,'python':platform.python_version(),'host_os':platform.system()}
                save(directory/'startup.json',startup_info)
                for _ in range(5):await broker.rpc('tools/call',{'name':'wewin_search','arguments':{'query':'tiếng Anh'}})
                await phase('idle',lambda:asyncio.sleep(1 if smoke else 45))
                async def gui():
                    data=[]
                    paths=['/']+['/'+p.relative_to(ROOT/'frontend/dist').as_posix() for p in (ROOT/'frontend/dist').rglob('*') if p.is_file() and p.name!='index.html' and p.suffix in ('.js','.css','.png','.svg','.ico','.woff','.woff2','.jpg','.webp')]
                    for path in paths:
                        begin=time.perf_counter();r=await api_client.get(path)
                        cold_ms=(time.perf_counter()-begin)*1000
                        warm=await api_client.get(path,headers={'If-None-Match':r.headers.get('etag','')})
                        data.append({'path':path,'status':r.status_code,'bytes':r.num_bytes_downloaded,'cold_ms':cold_ms,'conditional_status':warm.status_code,'conditional_bytes':warm.num_bytes_downloaded,'content_encoding':r.headers.get('content-encoding')})
                    save(directory/'gui_transfer.json',{'assets':data,'browser_render_measured':False,'all_static_assets_upper_bound':True})
                await phase('gui_static_transfer',gui)
                for clients in (1,5,10):
                    duration=2 if smoke else (300 if clients==1 else 120)
                    await phase(f'mcp_paced_{clients}',lambda c=clients,d=duration:load('mcp',c,d,5 if not smoke else .5))
                await phase('mcp_soak_10',lambda:load('mcp',10,5 if smoke else 600,.5 if smoke else 5))
                for clients in (1,5,10):
                    await phase(f'api_burst_{clients}',lambda c=clients:load('http',c,2 if smoke else 20,0))
                await phase('mcp_burst_10',lambda:load('mcp',10,2 if smoke else 20,0))
                async def sql():
                    process=spawn('sql',[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','sql','--directory',str(directory),'--database',str(db),'--count','3' if smoke else '20'],env)
                    code=await asyncio.to_thread(process.wait,90)
                    if code:raise RuntimeError('SQL worker failed')
                await phase('sqlite_micro',sql)
                async def sync():
                    process=spawn('sync',[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','sync','--directory',str(directory),'--database',str(db),'--count','4' if smoke else '20'],env)
                    async def readers():
                        while process.poll() is None:await load('mcp',10,5,5)
                    await asyncio.gather(asyncio.to_thread(process.wait,180),readers())
                    if process.returncode:raise RuntimeError('Sync worker failed')
                await phase('sync_fixture_with_10_clients',sync)
                await phase('post_sync_idle',lambda:asyncio.sleep(1 if smoke else 30))
                assert api.poll() is None and bridge.poll() is None
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                with suppress(subprocess.TimeoutExpired):await asyncio.to_thread(process.wait,10)
                if process.poll() is None:process.kill();process.wait()
        recorder.stop.set();recorder.thread.join(5)
        for stream in streams:stream.close()
    final=inspect(db)
    assert final['fts']['consistent'] and final['fts']['pages']==257 and final['visibility']==baseline['visibility']
    for path in directory.rglob('*.log'):
        assert token.encode() not in path.read_bytes(),'Fixture token leaked'
    save(directory/'final_database.json',final)
    errors=sum(p['errors'] for p in phases)
    save(directory/'run_summary.json',{'status':'PASS' if errors==0 else 'FAIL','smoke':smoke,'host_os':platform.system(),'linux_runtime':False,'production_cloud':False,'external_crawl':False,'phases':phases,'startup':startup_info,'errors':errors,'all_children_stopped':True})
    print(json.dumps({'event':'completed','directory':str(directory),'errors':sum(p['errors'] for p in phases)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--worker',choices=('sql','sync'))
    parser.add_argument('--database',type=Path)
    parser.add_argument('--count',type=int,default=20)
    args=parser.parse_args()
    if args.worker:worker(args.directory,args.database,args.worker,args.count)
    else:
        if not args.snapshot:parser.error('--snapshot required')
        asyncio.run(benchmark(args.snapshot,args.directory,args.smoke))
