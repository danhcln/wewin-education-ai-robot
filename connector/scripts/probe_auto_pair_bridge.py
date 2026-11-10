"""Explicit local Cloud-broker simulation against an isolated Auto Player server."""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import urlsplit,parse_qs
from uuid import uuid4
from websockets.asyncio.server import serve
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

async def run(args):
    from scripts.rotate_admin_token import restrict_directory
    from scripts.server_ops import backup,inspect
    u=urlsplit(args.backend)
    if u.scheme!='http' or u.hostname!='127.0.0.1' or u.path:raise ValueError('Loopback only')
    folder=args.directory.resolve()
    if folder.exists() or not folder.is_relative_to(ROOT/'.maintenance'):raise ValueError('New private evidence folder required')
    restrict_directory(folder);backup(args.snapshot,folder/'knowledge.db');before=inspect(folder/'knowledge.db')
    args.key_file=args.key_file.resolve()
    if not args.key_file.is_relative_to(ROOT/'.maintenance'):raise ValueError('Only an isolated fixture bridge key is allowed')
    token=secrets.token_urlsafe(32);done=asyncio.Event();rows=[];failures=[]
    async def broker(ws):
        try:
            assert ws.request.headers.get('Authorization')=='Bearer '+token
            assert parse_qs(urlsplit(ws.request.path).query).get('token')==[token]
            async def rpc(method,params):
                rid=uuid4().hex;await ws.send(json.dumps({'jsonrpc':'2.0','id':rid,'method':method,'params':params}))
                reply=json.loads(await asyncio.wait_for(ws.recv(),45));assert reply['id']==rid and 'result' in reply;return reply['result']
            await rpc('initialize',{});listing=await rpc('tools/list',{});assert len(listing['tools'])==14
            definition=next(t for t in listing['tools'] if t['name']=='youtube_control')
            assert 'session_id' not in definition['inputSchema']['required'] and 'control_token' not in definition['inputSchema']['required']
            async def call(name,arguments):
                result=await rpc('tools/call',{'name':name,'arguments':arguments});return json.loads(result['content'][0]['text'])
            status=await call('youtube_get_status',{})
            if args.unavailable:
                assert not status['connected'];response=await call('youtube_control',{'action':'play','request_id':uuid4().hex});assert response['status']=='player_disconnected'
                rows.append({'case':'closed browser returns disconnected','status':'PASS'})
            else:
                assert status['connected']
                result=await call('youtube_list_wewin_videos',{'limit':5});assert result['status']=='ok'
                rows.append({'case':'MCP list videos','videos':len(result['videos']),'status':'PASS'})
                if args.live and not result['videos']:raise ValueError('No live WeWIN videos')
                result=await call('youtube_search',{'query':'học tiếng Anh','scope':'wewin','limit':5});assert result['status']=='ok'
                rows.append({'case':'MCP search','videos':len(result['videos']),'status':'PASS'})
                if args.live:await call('youtube_list_wewin_videos',{'limit':5})
                steps=[('first','PLAYING')]+([('next','PLAYING')] if args.live else [])+[('pause','PAUSED'),('resume','PLAYING'),('volume','PLAYING'),('stop','STOPPED')]
                for action,state in steps:
                    command={'action':action,'request_id':uuid4().hex}
                    if action=='volume':command['volume']=45
                    result=await call('youtube_control',command)
                    if result.get('state')=='AUTOPLAY_BLOCKED':
                        rows.append({'case':action,'status':'AUTOPLAY_BLOCKED','claim_playing':False});break
                    assert result['status']=='command_confirmed' and result['state']==state,(action,result.get('status'),result.get('state'))
                    if action=='volume':assert result['volume']==45
                    rows.append({'case':action,'state':state,'video_id':result.get('observed_video_id'),'status':'PASS'})
                invalid=await call('youtube_control',{'action':'play','request_id':uuid4().hex,'session_id':'old','control_token':'old'})
                assert invalid['status']=='legacy_session_rejected';rows.append({'case':'stale capability rejected','status':'PASS'})
        except Exception as error:failures.append({'type':type(error).__name__,'details':str(error)[:180]})
        finally:done.set()
    process=None
    with (folder/'bridge.log').open('wb') as log:
        try:
            async with serve(broker,'127.0.0.1',0) as server:
                port=server.sockets[0].getsockname()[1]
                env={**os.environ,'PYTHONPATH':str(ROOT),'DATABASE_PATH':str(folder/'knowledge.db'),'KNOWLEDGE_JSON_PATH':str(folder/'unused.json'),'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT':f'ws://127.0.0.1:{port}/','XIAOZHI_MCP_TOKEN':token,'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','MEDIA_BACKEND_URL':args.backend,'MEDIA_BRIDGE_KEY_FILE':str(args.key_file),'BROWSER_SESSION_STORE':str(folder/'.secrets/browser.sqlite3'),'BRIDGE_STATUS_PATH':str(folder/'bridge-status.json'),'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','PYTHONDONTWRITEBYTECODE':'1'}
                options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
                process=subprocess.Popen([sys.executable,'-B',str(ROOT/'run_bridge.py')],cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,**options)
                await asyncio.wait_for(done.wait(),150)
        finally:
            if process and process.poll() is None:
                process.terminate()
                with suppress(subprocess.TimeoutExpired):await asyncio.to_thread(process.wait,5)
                if process.poll() is None:process.kill();process.wait()
    assert inspect(folder/'knowledge.db')==before
    for path in folder.glob('*.log'):
        value=path.read_bytes();assert token.encode() not in value and args.key_file.read_bytes().strip() not in value
    result={'status':'FAIL' if failures else 'PASS','cloud':'LOOPBACK_SIMULATOR','bridge_process':True,'youtube_api':'LIVE' if args.live else 'MOCK','player':'BROWSER_UNDER_TEST','manual_session_codes':False,'rows':rows,'failures':failures,'knowledge_copy_unchanged':True}
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=True));assert not failures

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--backend',required=True);p.add_argument('--directory',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);p.add_argument('--unavailable',action='store_true');p.add_argument('--live',action='store_true');asyncio.run(run(p.parse_args()))
