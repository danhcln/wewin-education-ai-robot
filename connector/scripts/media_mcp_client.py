"""Local MCP simulator. Never connects to XiaoZhi Cloud or reads production tokens."""
import argparse
import asyncio
import getpass
import json
import sys
from uuid import uuid4
import websockets
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

async def run(args):
    payload={}
    if args.tool=='youtube_search':payload={'query':args.query,'scope':args.scope,'limit':5}
    elif args.tool=='youtube_list_wewin_videos':payload={'limit':5}
    elif args.legacy_session:
        try:
            pair=json.loads(getpass.getpass('Paste session JSON copied from Media Player (hidden): '))
            payload={'session_id':pair['session_id'],'control_token':pair['control_token']}
        except (ValueError,KeyError,TypeError):raise SystemExit('Invalid session JSON; nothing sent.') from None
        if args.tool=='youtube_control':payload.update(action=args.action,request_id=uuid4().hex,**({'video_id':args.video_id} if args.video_id else {}))
    if not args.legacy_session:
        import os
        os.environ['MEDIA_BACKEND_URL']=f'http://127.0.0.1:{args.port}'
        from src.media.tools import relay_cloud_media_tool
        if args.tool=='youtube_control':payload.update(action=args.action,request_id=uuid4().hex,**({'video_id':args.video_id} if args.video_id else {}),**({'volume':args.volume} if args.volume is not None else {}))
        result=await asyncio.to_thread(relay_cloud_media_tool,args.tool,payload)
        print(json.dumps(result,ensure_ascii=False));return
    async with websockets.connect(f'ws://127.0.0.1:{args.port}/ws/mcp',proxy=None,open_timeout=5,max_size=1048576) as ws:
        for number,(method,params) in enumerate([('initialize',{}),('tools/list',{}),('tools/call',{'name':args.tool,'arguments':payload})]):
            await ws.send(json.dumps({'jsonrpc':'2.0','id':number,'method':method,'params':params}))
            reply=json.loads(await asyncio.wait_for(ws.recv(),25))
            if method=='tools/call':print(reply['result']['content'][0]['text'])
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000);parser.add_argument('--tool',choices=['youtube_search','youtube_list_wewin_videos','youtube_control','youtube_get_status'],required=True)
    parser.add_argument('--query',default='');parser.add_argument('--scope',choices=['wewin','all'],default='wewin')
    parser.add_argument('--action',choices=['select','play','pause','resume','stop','volume','first','next','latest'],default='play');parser.add_argument('--video-id');parser.add_argument('--volume',type=int);parser.add_argument('--legacy-session',action='store_true',help='Only for legacy capability fixtures; normal default-player use needs no session codes')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('Invalid port')
    asyncio.run(run(args))
