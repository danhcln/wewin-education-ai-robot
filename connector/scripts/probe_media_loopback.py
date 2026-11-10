"""Real run_bridge.py -> FastAPI -> paired browser probe. Fake Cloud only.

Scoped session JSON arrives on stdin (not CLI/logs). Requires an isolated test
server and a paired browser already playing. Never reads production credentials.
"""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlsplit,parse_qs
import httpx
from websockets.asyncio.server import serve
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

async def probe(args,pair):
    from scripts.rotate_admin_token import restrict_directory
    from scripts.server_ops import backup,inspect
    url=urlsplit(args.backend)
    if url.scheme!='http' or url.hostname!='127.0.0.1' or url.path:raise ValueError('Loopback only')
    directory=args.directory.resolve()
    if directory.exists() or not directory.is_relative_to(ROOT/'.maintenance'):raise ValueError('Use a new private evidence subfolder')
    restrict_directory(directory);backup(args.snapshot,directory/'copy.db');baseline=inspect(directory/'copy.db')
    done=asyncio.Event();events=[];errors=[];token=secrets.token_urlsafe(32)
    async def broker(ws):
        try:
            assert ws.request.headers.get('Authorization')=='Bearer '+token
            assert parse_qs(urlsplit(ws.request.path).query).get('token')==[token]
            async def rpc(method,params):
                await ws.send(json.dumps({'id':uuid4().hex,'method':method,'params':params}))
                reply=json.loads(await asyncio.wait_for(ws.recv(),25));assert 'result' in reply
                return reply['result']
            await rpc('initialize',{});listing=await rpc('tools/list',{});assert len(listing['tools'])==14
            target_video=None
            if args.verify_youtube_tools:
                for tool,arguments in [('youtube_search',{'query':'IELTS','scope':'wewin','limit':5}),('youtube_list_wewin_videos',{'limit':6})]:
                    reply=await rpc('tools/call',{'name':tool,'arguments':arguments})
                    data=json.loads(reply['content'][0]['text']);assert data['status']=='ok'
                    assert all(v['channel_id']==data['channel']['channel_id'] for v in data['videos'])
                    events.append({'tool':tool,'status':'PASS','videos':len(data['videos'])})
                    if tool=='youtube_list_wewin_videos':target_video=data['videos'][1]['video_id']
            async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
                steps=[('pause','PAUSED'),('resume','PLAYING'),('stop','STOPPED')]
                if args.verify_youtube_tools:steps += [('select','VIDEO_SELECTED'),('play','PLAYING'),('stop','STOPPED')]
                for action,state in steps:
                    arguments={**pair,'action':action,'request_id':uuid4().hex}
                    if action=='select':arguments['video_id']=target_video
                    result=await rpc('tools/call',{'name':'youtube_control','arguments':arguments})
                    receipt=json.loads(result['content'][0]['text']);assert receipt['status'].startswith('command_')
                    for _ in range(100):
                        if args.verify_youtube_tools:
                            reply=await rpc('tools/call',{'name':'youtube_get_status','arguments':pair})
                            status=json.loads(reply['content'][0]['text'])
                        else:
                            response=await client.post(args.backend+'/api/media/tool',json={'tool':'youtube_get_status','arguments':pair})
                            status=response.json()
                        if status.get('state')==state and not status.get('pending_command'):break
                        await asyncio.sleep(.1)
                    else:raise RuntimeError('Player did not confirm expected state')
                    events.append({'action':action,'confirmed_state':state,'receipt_only':receipt['status'],'observed_video_id':status.get('observed_video_id')})
        except Exception as e:errors.append(type(e).__name__)
        finally:done.set()
    process=None
    with (directory/'bridge.log').open('wb') as out:
        try:
            async with serve(broker,'127.0.0.1',0) as server:
                port=server.sockets[0].getsockname()[1]
                env={**os.environ,'DATABASE_PATH':str(directory/'copy.db'),'KNOWLEDGE_JSON_PATH':str(directory/'unused.json'),
                    'XIAOZHI_MCP_ENDPOINT':f'ws://127.0.0.1:{port}/','XIAOZHI_MCP_TOKEN':token,'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'',
                    'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'','AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false',
                    'BRIDGE_STATUS_PATH':str(directory/'status.json'),'MEDIA_BACKEND_URL':args.backend,'YOUTUBE_API_KEY':'',
                    'YOUTUBE_API_KEY_FILE':str(directory/'no-key'),'PYTHONDONTWRITEBYTECODE':'1'}
                opts={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
                process=subprocess.Popen([sys.executable,'-B',str(ROOT/'run_bridge.py')],cwd=directory,env=env,stdout=out,stderr=subprocess.STDOUT,**opts)
                await asyncio.wait_for(done.wait(),120 if args.verify_youtube_tools else 45)
        finally:
            if process and process.poll() is None:
                process.terminate()
                with suppress(subprocess.TimeoutExpired):await asyncio.to_thread(process.wait,5)
                if process.poll() is None:process.kill();process.wait()
    assert not errors,','.join(errors)
    assert inspect(directory/'copy.db')==baseline
    for f in directory.rglob('*.log'):
        data=f.read_bytes();assert token.encode() not in data and pair['control_token'].encode() not in data
    result={'status':'PASS','bridge_process':True,'cloud':'MOCK_LOOPBACK','player':'BROWSER_UNDER_TEST','youtube_metadata':'LIVE' if args.verify_youtube_tools else 'NOT_ASSERTED','transitions':events,'copied_database_unchanged':True}
    (directory/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({'status':'PASS','transitions':len(events)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',required=True);parser.add_argument('--snapshot',type=Path,required=True);parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--verify-youtube-tools',action='store_true',help='Explicit live metadata/paired-browser verification of all four YouTube tools')
    args=parser.parse_args();pair=json.loads(sys.stdin.read());asyncio.run(probe(args,pair))
