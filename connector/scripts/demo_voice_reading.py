"""Windows text demo via real ASGI HTTP tools and a temporary read-only DB.

No listener, Cloud, crawler, scheduler, production DB writer, or audio output.
"""
import argparse
import importlib
from contextlib import ExitStack
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def demo(snapshot,url,mode,chunk_chars=600):
    from scripts.rotate_admin_token import restrict_directory
    from scripts.server_ops import backup
    with ExitStack() as stack:
        folder=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='wewin-reading-demo-',dir=ROOT/'.maintenance')))
        restrict_directory(folder);copy=folder/'demo.db';backup(snapshot,copy)
        stack.enter_context(patch.dict(os.environ,{'DATABASE_PATH':str(copy),'KNOWLEDGE_JSON_PATH':str(folder/'unused.json'),
            'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'',
            'XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'','XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'',
            'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','DEBUG':'false'}))
        log=types.ModuleType('src.utils.logger');log.logger=logging.getLogger('reading-demo')
        log.logger.handlers=[logging.NullHandler()];log.logger.propagate=False
        stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':log}))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=RuntimeError('Network disabled in demo')))
        stack.enter_context(patch('websockets.connect',side_effect=RuntimeError('Cloud disabled in demo')))
        stack.enter_context(patch('socket.getaddrinfo',side_effect=RuntimeError('DNS disabled in demo')))
        from src.storage.db import DatabaseManager,get_db
        appmod=importlib.import_module('src.api.app')
        from fastapi.testclient import TestClient
        db=DatabaseManager.open_existing(copy,read_only=True)
        stack.enter_context(patch.object(appmod,'get_db',return_value=db))
        stack.enter_context(patch('src.mcp.tools.get_db',return_value=db))
        app=appmod.create_app();app.dependency_overrides[get_db]=lambda:db
        client=stack.enter_context(TestClient(app))
        def call(name,args):
            r=client.post('/api/xiaozhi/tool',json={'tool':name,'arguments':args});r.raise_for_status()
            return r.json()['data']
        result=call('wewin_read_article',{'url':url,'mode':mode,'chunk_chars':chunk_chars})
        while True:
            if result['status']!='ok':
                print(result.get('message','Không thể đọc.'));return 1
            print(result['title']);print('Nguồn:',result['source_url'])
            if 'part' in result:print(f"Đoạn {result['part']}/{result['total_parts']}")
            print(result['text'])
            if mode=='summary' or not result.get('has_more'):return 0
            command=input('Gõ tiếp hoặc dừng: ').strip().casefold()
            if command not in ('tiếp','tiep','t'):
                print(call('wewin_stop_reading',{'reading_id':result['reading_id']})['text']);return 0
            result=call('wewin_continue_reading',{'reading_id':result['reading_id'],'part':result['next_part']})


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--mode',choices=['read','summary'],default='summary')
    parser.add_argument('--chunk-chars',type=int,default=600)
    args=parser.parse_args()
    if not 200<=args.chunk_chars<=800:parser.error('--chunk-chars must be between 200 and 800')
    sys.exit(demo(args.snapshot.resolve(strict=True),args.url,args.mode,args.chunk_chars))
